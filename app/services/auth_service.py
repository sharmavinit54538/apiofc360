"""Authentication service layer containing business logic for registration, verification, login, logout, and recovery."""

from datetime import datetime, timedelta, timezone
import logging
import hashlib
import httpx
import secrets

from fastapi import Depends, status
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AppException, ConflictException, DatabaseException
from app.core.redis_client import redis_client
from app.core.security import hash_password, verify_password
from app.db.database import get_db_session
from app.models.user import User
from app.repositories.auth_repository import AuthRepository
from app.schemas.auth import (
    ForgotPasswordRequest,
    LoginRequest,
    RegisterRequest,
    ResendOTPRequest,
    ResetPasswordRequest,
    VerifyEmailRequest,
    VerifyResetOTPRequest,
)
from app.services.email_service import EmailService, get_email_service
from app.services.token_service import TokenService, get_token_service
from app.utils.jwt import decode_token
from app.utils.otp import generate_otp, hash_otp, verify_otp_hash

logger = logging.getLogger(__name__)


def _registration_log_context(email: str, phone: str) -> dict[str, str]:
    """Return low-PII registration context for structured logging."""

    _, _, domain = email.partition("@")
    return {
        "email_domain": domain,
        "phone_suffix": phone[-4:],
    }


class AuthService:
    """Service that owns authentication, verification, recovery business logic, and transactions."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        auth_repository: AuthRepository,
        email_service: EmailService,
        token_service: TokenService | None = None,
    ) -> None:
        self.session = session
        self.auth_repository = auth_repository
        self.email_service = email_service
        self.token_service = token_service or TokenService(session=session, auth_repository=auth_repository)

    async def register_user(self, payload: RegisterRequest) -> None:
        """Register a new company and its HR Admin owner (pending email verification)."""

        import uuid
        from decimal import Decimal
        from app.models.company import Company
        from app.models.employee import Employee
        from app.models.department import Department
        from app.models.employee_leave_policy import EmployeeLeavePolicy
        from app.models.user.role import UserRole, UserAccountStatus
        from app.utils.employee import generate_employee_id

        log_context = _registration_log_context(str(payload.email), payload.phone)
        try:
            # Reject Super Admin email registration
            clean_email = str(payload.email).strip().lower()
            if clean_email == "superadmin@ofc360.com":
                raise AppException(
                    message="Registration with the Super Admin identity is prohibited.",
                    status_code=status.HTTP_403_FORBIDDEN,
                    errors=[{"field": "email", "message": "Super Admin registration prohibited."}],
                )

            # Check duplicate email
            existing_email = await self.auth_repository.get_user_by_email(clean_email)
            if existing_email:
                if existing_email.is_verified:
                    logger.info("Registration failed: email already exists", extra=log_context)
                    raise ConflictException(
                        message="Email already exists.",
                        errors=[{"field": "email", "message": "Email already exists."}],
                    )
                else:
                    logger.info("Cleaning up unverified user with duplicate email: %s", payload.email, extra=log_context)
                    if existing_email.company_id:
                        company = await self.session.get(Company, existing_email.company_id)
                        if company:
                            await self.session.delete(company)
                    else:
                        await self.session.delete(existing_email)
                    await self.session.flush()

            # Check duplicate phone
            existing_phone = await self.auth_repository.get_user_by_phone(payload.phone)
            if existing_phone:
                if existing_phone.is_verified:
                    logger.info("Registration failed: phone already exists", extra=log_context)
                    raise ConflictException(
                        message="Phone already exists.",
                        errors=[{"field": "phone", "message": "Phone already exists."}],
                    )
                else:
                    if existing_phone not in self.session.deleted:
                        logger.info("Cleaning up unverified user with duplicate phone: %s", payload.phone, extra=log_context)
                        if existing_phone.company_id:
                            company = await self.session.get(Company, existing_phone.company_id)
                            if company and company not in self.session.deleted:
                                await self.session.delete(company)
                        else:
                            await self.session.delete(existing_phone)
                        await self.session.flush()

            # 1. Create a new Company/Tenant
            company = Company(
                id=uuid.uuid4(),
                name=payload.company_name,
            )
            self.session.add(company)
            await self.session.flush()

            # Generate secure verification token and OTP
            verification_token = secrets.token_urlsafe(32)
            expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.OTP_EXPIRE_MINUTES)
            otp_code = generate_otp()

            # 2. Create the HR Admin user (FORCED to HR_ADMIN)
            password_hash = hash_password(payload.password)
            user = User(
                id=uuid.uuid4(),
                company_id=company.id,
                name=payload.name,
                email=str(payload.email),
                phone=payload.phone,
                password_hash=password_hash,
                role=UserRole.HR_ADMIN,
                account_status=UserAccountStatus.PENDING_EMAIL_VERIFICATION.value,
                email_verification_token=verification_token,
                email_verification_expires_at=expires_at,
                is_active=False,
                is_verified=False,
                first_login=False,
            )
            self.session.add(user)
            await self.session.flush()

            # 3. Create the HR Admin Employee record
            employee_id_str = await generate_employee_id(self.session)
            first_name, _, last_name = payload.name.partition(" ")
            if not last_name:
                last_name = "Admin"

            employee = Employee(
                id=uuid.uuid4(),
                user_id=user.id,
                company_id=company.id,
                employee_id=employee_id_str,
                first_name=first_name,
                last_name=last_name,
                personal_email=str(payload.email),
                company_email=str(payload.email),
                phone=payload.phone,
                role="hr_admin",
                status="ACTIVE",
                department="Human Resources",
                designation="HR Administrator",
                joining_date=datetime.now(timezone.utc).date(),
            )
            self.session.add(employee)
            await self.session.flush()

            # 4. Create default departments
            mgmt_dept = Department(
                id=uuid.uuid4(),
                company_id=company.id,
                department_code="MGMT",
                department_name="Management",
                description="Executive leadership and administrative department",
                location="Headquarters",
                status="ACTIVE",
                manager_id=user.id,
            )
            self.session.add(mgmt_dept)

            eng_dept = Department(
                id=uuid.uuid4(),
                company_id=company.id,
                department_code="ENG",
                department_name="Engineering",
                description="Software development and product engineering",
                location="Tech Hub",
                status="ACTIVE",
            )
            self.session.add(eng_dept)

            hr_dept = Department(
                id=uuid.uuid4(),
                company_id=company.id,
                department_code="HR",
                department_name="Human Resources",
                description="People management, recruiting and onboarding",
                location="Headquarters",
                status="ACTIVE",
            )
            self.session.add(hr_dept)
            await self.session.flush()

            # Link employee to default department
            employee.department_id = hr_dept.id

            # 5. Create default leave policies
            sick_leave = EmployeeLeavePolicy(
                id=uuid.uuid4(),
                employee_id=employee.id,
                leave_type="Sick Leave",
                total_days=Decimal("12.0"),
                used_days=Decimal("0.0"),
                carry_forward=False,
                effective_from=datetime.now(timezone.utc).date(),
            )
            self.session.add(sick_leave)

            casual_leave = EmployeeLeavePolicy(
                id=uuid.uuid4(),
                employee_id=employee.id,
                leave_type="Casual Leave",
                total_days=Decimal("12.0"),
                used_days=Decimal("0.0"),
                carry_forward=False,
                effective_from=datetime.now(timezone.utc).date(),
            )
            self.session.add(casual_leave)

            # Store verification OTP
            hashed_otp = hash_otp(otp=otp_code, user_id=user.id, purpose="email_verification")
            await self.auth_repository.create_otp(
                user_id=user.id,
                otp_hash=hashed_otp,
                purpose="email_verification",
                expires_at=expires_at,
            )
            
            # Send verification email immediately
            await self.email_service.send_verification_email(
                email=user.email,
                name=user.name,
                otp=otp_code,
                expiry_minutes=settings.OTP_EXPIRE_MINUTES,
                company_name=company.name,
            )

            await self.session.commit()
            await self.session.refresh(user)
            logger.info("Registration succeeded as HR_ADMIN, verification email sent", extra=log_context)

        except AppException:
            await self.session.rollback()
            raise
        except RuntimeError as exc:
            await self.session.rollback()
            logger.exception("Registration failed due to email sending failure", extra=log_context, exc_info=exc)
            raise AppException(
                message="Failed to send verification email.",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                errors=[{"field": None, "message": str(exc)}],
            ) from exc
        except IntegrityError as exc:
            await self.session.rollback()
            logger.info("Registration failed: unique constraint conflict", extra=log_context)
            constraint_text = (str(getattr(exc.orig, "diag", "")) + " " + str(exc.orig) + " " + str(exc)).lower()
            if "ix_users_email" in constraint_text or "users_email" in constraint_text or "personal_email" in constraint_text or "email" in constraint_text:
                raise ConflictException(
                    message="Email already exists.",
                    errors=[{"field": "email", "message": "Email already exists."}],
                ) from exc
            if "ix_users_phone" in constraint_text or "users_phone" in constraint_text or "phone" in constraint_text:
                raise ConflictException(
                    message="Phone already exists.",
                    errors=[{"field": "phone", "message": "Phone already exists."}],
                ) from exc
            raise ConflictException(
                message="User already exists.",
                errors=[{"field": None, "message": "User already exists."}],
            ) from exc
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("Registration failed: database error", extra=log_context, exc_info=exc)
            raise DatabaseException() from exc
        except Exception as exc:
            await self.session.rollback()
            logger.exception("Registration failed: unexpected error", extra=log_context, exc_info=exc)
            raise

    async def verify_email(self, payload: VerifyEmailRequest) -> None:
        """Verify the user's email using token or OTP and activate HR Admin account."""

        now = datetime.now(timezone.utc)
        user: User | None = None

        # Case 1: Token verification from email link
        if payload.token:
            user = await self.auth_repository.get_user_by_verification_token(payload.token)
            if not user:
                raise AppException(
                    message="Invalid or expired verification token.",
                    status_code=status.HTTP_400_BAD_REQUEST,
                    errors=[{"field": "token", "message": "Invalid or expired verification token."}]
                )
            if user.is_verified:
                raise AppException(message="Email already verified.", status_code=status.HTTP_400_BAD_REQUEST)
            if user.email_verification_expires_at:
                exp = user.email_verification_expires_at
                if exp.tzinfo is None:
                    exp = exp.replace(tzinfo=timezone.utc)
                if now > exp:
                    raise AppException(
                        message="Verification token has expired. Please request a new verification email.",
                        status_code=status.HTTP_400_BAD_REQUEST,
                        errors=[{"field": "token", "message": "Verification token has expired."}]
                    )
            # Invalidate any pending OTPs
            await self.auth_repository.invalidate_all_user_otps(user.id, "email_verification")

        # Case 2: Email + 6-digit OTP verification
        elif payload.email and payload.otp:
            user = await self.auth_repository.get_user_by_email(str(payload.email))
            if not user:
                raise AppException(message="User not found.", status_code=status.HTTP_404_NOT_FOUND)

            if user.is_verified:
                raise AppException(message="Email already verified.", status_code=status.HTTP_400_BAD_REQUEST)

            # Get latest unused OTP record
            otp_record = await self.auth_repository.get_latest_otp(user.id, "email_verification")
            if not otp_record:
                raise AppException(message="Invalid OTP.", status_code=status.HTTP_400_BAD_REQUEST)

            # Check expiry
            if now > otp_record.expires_at:
                raise AppException(message="OTP has expired.", status_code=status.HTTP_400_BAD_REQUEST)

            # Verify hash
            is_valid = verify_otp_hash(
                otp=payload.otp,
                otp_hash=otp_record.otp_hash,
                user_id=user.id,
                purpose="email_verification",
            )

            if not is_valid:
                # Increment attempts
                attempts = await self.auth_repository.increment_otp_attempts(otp_record.id)
                if attempts >= settings.OTP_MAX_ATTEMPTS:
                    # Invalidate current OTP
                    await self.auth_repository.invalidate_all_user_otps(user.id, "email_verification")
                    
                    # Generate a new OTP and token and send it
                    new_otp_code = generate_otp()
                    new_token = secrets.token_urlsafe(32)
                    new_hashed_otp = hash_otp(otp=new_otp_code, user_id=user.id, purpose="email_verification")
                    new_expires_at = now + timedelta(minutes=settings.OTP_EXPIRE_MINUTES)
                    await self.auth_repository.create_otp(
                        user_id=user.id,
                        otp_hash=new_hashed_otp,
                        purpose="email_verification",
                        expires_at=new_expires_at,
                    )
                    await self.auth_repository.set_user_verification_token(user.id, new_token, new_expires_at)
                    await self.session.commit()

                    # Send email
                    await self.email_service.send_verification_email(
                        email=user.email,
                        name=user.name,
                        otp=new_otp_code,
                        expiry_minutes=settings.OTP_EXPIRE_MINUTES,
                    )
                    raise AppException(
                        message="Too many wrong attempts. A new OTP has been sent to your email.",
                        status_code=status.HTTP_400_BAD_REQUEST,
                    )
                
                await self.session.commit()
                raise AppException(message="Invalid OTP.", status_code=status.HTTP_400_BAD_REQUEST)

            # Atomically mark OTP as used to prevent concurrent reuse
            consumed = await self.auth_repository.consume_otp_atomic(otp_record.id)
            if hasattr(self.auth_repository, "mark_otp_used"):
                await self.auth_repository.mark_otp_used(otp_record.id)
            if not consumed and consumed is not None:
                raise AppException(message="OTP has already been used or is invalid.", status_code=status.HTTP_400_BAD_REQUEST)
        else:
            raise AppException(message="Verification token or OTP is required.", status_code=status.HTTP_400_BAD_REQUEST)

        # Mark user as verified and active (account_status = ACTIVE)
        await self.auth_repository.update_user_verification(user.id)
        await self.session.commit()

        # Send Welcome email
        try:
            await self.email_service.send_welcome_email(user.email, user.name)
        except Exception as mail_err:
            logger.warning("Failed to send welcome email to %s: %s", user.email, mail_err)

    async def resend_otp(self, payload: ResendOTPRequest) -> None:
        """Invalidate previous OTPs and issue a new one, subject to rate-limiting."""

        # Email normalization (trim + lowercase)
        email = payload.email.strip().lower()

        # User lookup (User existence check)
        try:
            user = await self.auth_repository.get_user_by_email(email)
        except Exception as exc:
            logger.error("Resend OTP failed: user lookup database error | email=%s | error=%s", email, str(exc), exc_info=exc)
            raise AppException(
                message="Internal database error.",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                errors=[{"field": None, "message": "Database query failed."}],
            )

        if not user or user.is_deleted:
            logger.warning("Resend OTP failed: User Not Found | email=%s", email)
            raise AppException(
                message="User not found",
                status_code=status.HTTP_404_NOT_FOUND,
                errors=[{"field": "email", "message": "User not found"}]
            )

        logger.info("Resend OTP: User Found | email=%s", email)

        # Email verified status check
        if user.is_verified:
            logger.warning("Resend OTP failed: Email Already Verified | email=%s", email)
            raise AppException(
                message="Email already verified",
                status_code=status.HTTP_400_BAD_REQUEST,
                errors=[{"field": "email", "message": "Email already verified"}]
            )

        # Check rate limiting cooldown (30 seconds)
        latest_otp = await self.auth_repository.get_latest_otp(user.id, "email_verification")
        now = datetime.now(timezone.utc)
        if latest_otp:
            created_at = latest_otp.created_at
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            
            elapsed = (now - created_at).total_seconds()
            if elapsed < settings.OTP_RESEND_COOLDOWN_SECONDS:
                remaining_cooldown = int(settings.OTP_RESEND_COOLDOWN_SECONDS - elapsed)
                logger.warning("Resend OTP failed: rate limited | email=%s | elapsed=%ds", email, elapsed)
                raise AppException(
                    message=f"Please wait {remaining_cooldown} seconds before requesting another OTP.",
                    status_code=status.HTTP_400_BAD_REQUEST,
                    errors=[{"field": "email", "message": f"Please wait {remaining_cooldown} seconds before requesting another OTP."}]
                )

        try:
            # Delete/invalidate any previous active OTP
            await self.auth_repository.invalidate_all_user_otps(user.id, "email_verification")

            # OTP & Token Generation: secure random 6-digit OTP and 32-byte urlsafe token
            new_otp_code = generate_otp()
            new_token = secrets.token_urlsafe(32)
            logger.info("Resend OTP: OTP and Token Generated | email=%s", email)

            # OTP Hashing & storage with 5 minutes expiry
            hashed_otp = hash_otp(otp=new_otp_code, user_id=user.id, purpose="email_verification")
            expires_at = now + timedelta(minutes=settings.OTP_EXPIRE_MINUTES)

            await self.auth_repository.create_otp(
                user_id=user.id,
                otp_hash=hashed_otp,
                purpose="email_verification",
                expires_at=expires_at,
            )
            await self.auth_repository.set_user_verification_token(user.id, new_token, expires_at)
            logger.info("Resend OTP: OTP & Token Saved | email=%s", email)

            # Commit database transaction BEFORE sending email
            await self.session.commit()
            logger.info("Resend OTP: Database Commit | email=%s", email)

        except Exception as exc:
            await self.session.rollback()
            logger.exception("Resend OTP failed: database operation exception | email=%s", email, exc_info=exc)
            raise AppException(
                message="Internal database error.",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                errors=[{"field": None, "message": "Database write failed."}],
            )

        # SMTP Connection and Email Sending
        try:
            logger.info("Resend OTP: SMTP Connected | email=%s", email)
            # Send verification email with 5 minutes expiry
            await self.email_service.send_verification_email(
                email=user.email,
                name=user.name,
                otp=new_otp_code,
                expiry_minutes=settings.OTP_EXPIRE_MINUTES,
                company_name=user.company.name if user.company else "OFC360",
            )
            logger.info("Resend OTP: Email Sent | email=%s", email)
        except RuntimeError as exc:
            logger.error("Resend OTP failed: SMTP Error | email=%s | error=%s", email, str(exc), exc_info=exc)
            raise AppException(
                message="Unable to send email.",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                errors=[{"field": None, "message": "Unable to send email."}],
            )
        except Exception as exc:
            logger.exception("Resend OTP failed: Unexpected Exception during sending | email=%s", email, exc_info=exc)
            raise AppException(
                message="Internal server error.",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                errors=[{"field": None, "message": "Unexpected sending error."}],
            )

    async def verify_reset_otp(self, payload: VerifyResetOTPRequest) -> dict:
        """Verify the password reset OTP and return a reset token for the reset-password step."""
        
        now = datetime.now(timezone.utc)
        
        # Lookup user by identifier (email or phone)
        identifier = payload.email.strip().lower() if payload.email else ""
        if not identifier:
            raise AppException(message="Email is required.", status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)
        
        user = await self.auth_repository.get_user_by_email(identifier)
        if not user:
            raise AppException(message="User not found.", status_code=status.HTTP_404_NOT_FOUND)

        # Get latest unused OTP record for password_reset
        otp_record = await self.auth_repository.get_latest_otp(user.id, "password_reset")
        if not otp_record:
            raise AppException(message="Invalid OTP.", status_code=status.HTTP_400_BAD_REQUEST)

        # Check expiry
        if now > otp_record.expires_at:
            raise AppException(message="OTP has expired.", status_code=status.HTTP_400_BAD_REQUEST)

        # Verify hash
        is_valid = verify_otp_hash(
            otp=payload.otp,
            otp_hash=otp_record.otp_hash,
            user_id=user.id,
            purpose="password_reset",
        )

        if not is_valid:
            # Increment attempts
            attempts = await self.auth_repository.increment_otp_attempts(otp_record.id)
            if attempts >= settings.OTP_MAX_ATTEMPTS:
                # Invalidate current OTP
                await self.auth_repository.invalidate_all_user_otps(user.id, "password_reset")
                raise AppException(
                    message="Too many wrong attempts. Please request a new OTP.",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
            await self.session.commit()
            raise AppException(message="Invalid OTP.", status_code=status.HTTP_400_BAD_REQUEST)

        # Atomically mark OTP as used
        consumed = await self.auth_repository.consume_otp_atomic(otp_record.id)
        if hasattr(self.auth_repository, "mark_otp_used"):
            await self.auth_repository.mark_otp_used(otp_record.id)
        if not consumed and consumed is not None:
            raise AppException(message="OTP has already been used or is invalid.", status_code=status.HTTP_400_BAD_REQUEST)

        # Generate a secure reset session token (short-lived, for the reset-password step)
        raw_token = secrets.token_urlsafe(32)
        hashed_token = hashlib.sha256(raw_token.encode()).hexdigest()
        reset_token_expires = now + timedelta(minutes=10)  # 10 minutes to complete password reset
        
        # Store reset token in PasswordResetToken table
        await self.auth_repository.create_password_reset_token(
            user_id=user.id,
            role=user.role,
            hashed_token=hashed_token,
            expires_at=reset_token_expires,
        )
        await self.session.commit()

        # Return the raw token for the frontend to use in reset-password
        return {"success": True, "message": "OTP verified successfully", "reset_token": raw_token, "errors": None}

    async def login(
        self,
        payload: LoginRequest,
        ip_address: str | None = None,
        device: str | None = None,
    ) -> tuple[User, str, str, int]:
        """Verify user credentials and return a user model with access + refresh token set."""

        # 1. Check Redis lockout for identifier and IP
        is_locked, remaining_seconds = await redis_client.is_account_locked(payload.identifier, ip_address or "")
        if is_locked:
            logger.warning(
                "Authentication blocked: account/IP is locked out | identifier=%s | ip=%s | retry_after=%ds",
                payload.identifier, ip_address, remaining_seconds
            )
            raise AppException(
                message="Account is temporarily locked due to multiple failed login attempts. Please try again later.",
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                errors=[{"field": None, "message": "ACCOUNT_LOCKED", "retry_after": remaining_seconds}],
            )

        try:
            user = await self.auth_repository.get_user_by_identifier(payload.identifier)
        except AppException:
            raise
        except Exception as exc:
            logger.exception("Authentication failed: database lookup exception | identifier=%s", payload.identifier)
            raise AppException(
                message="Invalid email or password.",
                status_code=status.HTTP_401_UNAUTHORIZED,
            )

        # Check DB locked_until fallback persistence
        if user and getattr(user, "locked_until", None):
            now = datetime.now(timezone.utc)
            locked_until_dt = user.locked_until if user.locked_until.tzinfo else user.locked_until.replace(tzinfo=timezone.utc)
            if locked_until_dt > now:
                rem_sec = max(1, int((locked_until_dt - now).total_seconds()))
                logger.warning("Authentication blocked: user DB locked_until active | user_id=%s | retry_after=%ds", user.id, rem_sec)
                raise AppException(
                    message="Account is temporarily locked due to multiple failed login attempts. Please try again later.",
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    errors=[{"field": None, "message": "ACCOUNT_LOCKED", "retry_after": rem_sec}],
                )

        # Security: constant-time password verification to mitigate timing attacks if user does not exist
        timing_mitigation_hash = "$2b$12$eImiTXuWVxfM37uY4JANjO7f.6.O1Nn6W71.u8M0bN71dJkZ5p6d6"
        if not user:
            verify_password(payload.password, timing_mitigation_hash)
            logger.warning("Authentication failed: user not found | identifier=%s", payload.identifier)
            attempts, now_locked, lock_sec = await redis_client.record_failed_login(payload.identifier, ip_address or "")
            if now_locked:
                raise AppException(
                    message="Account is temporarily locked due to multiple failed login attempts. Please try again later.",
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    errors=[{"field": None, "message": "ACCOUNT_LOCKED", "retry_after": lock_sec}],
                )
            raise AppException(
                message="Invalid email or password.",
                status_code=status.HTTP_401_UNAUTHORIZED,
            )

        # Validate password
        is_password_valid = verify_password(payload.password, user.password_hash)
        if not is_password_valid:
            logger.warning("Authentication failed: password mismatch | user_id=%s | email=%s", user.id, user.email)
            attempts, now_locked, lock_sec = await redis_client.record_failed_login(payload.identifier, ip_address or "")
            lock_until_dt = (datetime.now(timezone.utc) + timedelta(seconds=lock_sec)) if now_locked else None
            await self.auth_repository.record_failed_login_db(user.id, lock_until=lock_until_dt)
            await self.session.commit()

            if now_locked:
                raise AppException(
                    message="Account is temporarily locked due to multiple failed login attempts. Please try again later.",
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    errors=[{"field": None, "message": "ACCOUNT_LOCKED", "retry_after": lock_sec}],
                )

            raise AppException(
                message="Invalid email or password.",
                status_code=status.HTTP_401_UNAUTHORIZED,
            )

        # Clear failed logins on successful credential verification
        await redis_client.clear_failed_logins(payload.identifier, ip_address or "")
        await self.auth_repository.reset_failed_logins_db(user.id)

        # Check email verification status
        account_status_val = str(getattr(user, "account_status", "") or "").upper()
        if not user.is_verified or account_status_val == "PENDING_EMAIL_VERIFICATION":
            # Instead of blocking with 403, generate and send OTP for login verification
            logger.info("Login requires email verification | user_id=%s | email_domain=%s", user.id, user.email.split("@")[-1])

            from app.utils.otp import OTP_PURPOSE_EMAIL_LOGIN_VERIFICATION

            # Invalidate any previous login verification OTPs
            await self.auth_repository.invalidate_all_user_otps(user.id, OTP_PURPOSE_EMAIL_LOGIN_VERIFICATION)

            # Generate secure 6-digit OTP
            otp_code = generate_otp()
            otp_expiry = datetime.now(timezone.utc) + timedelta(minutes=settings.OTP_EXPIRE_MINUTES)

            # Hash and store
            hashed_otp = hash_otp(otp=otp_code, user_id=user.id, purpose=OTP_PURPOSE_EMAIL_LOGIN_VERIFICATION)
            otp_record = await self.auth_repository.create_otp(
                user_id=user.id,
                otp_hash=hashed_otp,
                purpose=OTP_PURPOSE_EMAIL_LOGIN_VERIFICATION,
                expires_at=otp_expiry,
            )

            # Resolve company name for email branding
            company_name = "OFC360"
            if getattr(user, "company", None):
                try:
                    company_name = user.company.name or company_name
                except Exception:
                    pass

            # Send OTP email (do not log the OTP itself)
            try:
                await self.email_service.send_login_verification_otp_email(
                    email=user.email,
                    name=user.name or "User",
                    otp=otp_code,
                    expiry_minutes=settings.OTP_EXPIRE_MINUTES,
                    company_name=company_name,
                )
            except Exception as mail_err:
                logger.warning("Failed to send login verification OTP email to user_id=%s: %s", user.id, mail_err)

            await self.session.commit()

            # Return user + verification_id but NO tokens
            return user, str(otp_record.id), None, None, True

        # Verify user is active
        if not user.is_active or account_status_val in ("SUSPENDED", "DEACTIVATED", "INVITED"):
            logger.warning("Authentication failed: inactive user | user_id=%s | email=%s", user.id, user.email)
            raise AppException(
                message="Account is inactive or pending activation. Please contact your administrator.",
                status_code=status.HTTP_403_FORBIDDEN,
                code="ACCOUNT_INACTIVE",
                errors=[{"field": None, "message": "ACCOUNT_INACTIVE"}],
            )

        # Verify employment / manager active lifecycle state
        from sqlalchemy import func, select
        from app.models.employee import Employee
        from app.models.manager import Manager

        import inspect
        emp_res = await self.session.execute(
            select(Employee).where(
                Employee.user_id == user.id,
                Employee.is_deleted == False,
            ).execution_options(bypass_tenant=True)
        )
        emp = None
        if hasattr(emp_res, "scalars"):
            sc = emp_res.scalars()
            if hasattr(sc, "first"):
                emp_val = sc.first()
                emp = await emp_val if inspect.isawaitable(emp_val) else emp_val
        elif hasattr(emp_res, "scalar_one_or_none"):
            emp_val = emp_res.scalar_one_or_none()
            emp = await emp_val if inspect.isawaitable(emp_val) else emp_val
        if not emp:
            # Resilient fallback: link employee by company/personal email if user_id was unlinked
            user_email_clean = (user.email or "").strip().lower()
            emp_email_res = await self.session.execute(
                select(Employee).where(
                    (func.lower(Employee.personal_email) == user_email_clean) |
                    (func.lower(Employee.company_email) == user_email_clean),
                    Employee.is_deleted == False,
                ).execution_options(bypass_tenant=True)
            )
            if hasattr(emp_email_res, "scalars"):
                sc = emp_email_res.scalars()
                if hasattr(sc, "first"):
                    emp_val = sc.first()
                    emp = await emp_val if inspect.isawaitable(emp_val) else emp_val
            elif hasattr(emp_email_res, "scalar_one_or_none"):
                emp_val = emp_email_res.scalar_one_or_none()
                emp = await emp_val if inspect.isawaitable(emp_val) else emp_val
            if emp and not getattr(emp, "user_id", None):
                emp.user_id = user.id
                self.session.add(emp)
                await self.session.flush()

        if isinstance(emp, Employee) and (
            emp.is_active is False
            or getattr(emp, "is_deactivated", False)
            or (emp.status or "").upper() in ("DISABLED", "INACTIVE", "DEACTIVATED", "ARCHIVED", "TERMINATED", "EXITED", "DELETED")
            or (getattr(emp, "employment_status", "") or "").upper() in ("TERMINATED", "EXITED")
        ):
            logger.warning(
                "Authentication failed: Employee profile for user %s is deactivated/archived/terminated (status=%s, is_active=%s).",
                user.id, emp.status, emp.is_active
            )
            user.is_active = False
            user.account_status = "DEACTIVATED"
            await self.auth_repository.revoke_all_user_refresh_tokens(user.id)
            await self.session.commit()
            raise AppException(
                message="Account or employment profile is inactive or terminated. Please contact HR.",
                status_code=status.HTTP_403_FORBIDDEN,
                code="EMPLOYEE_INACTIVE",
                errors=[{"field": None, "message": "EMPLOYEE_INACTIVE"}],
            )

        mgr_res = await self.session.execute(
            select(Manager).where(
                Manager.user_id == user.id,
                Manager.is_deleted == False,
            ).execution_options(bypass_tenant=True)
        )
        mgr = None
        if hasattr(mgr_res, "scalars"):
            sc = mgr_res.scalars()
            if hasattr(sc, "first"):
                mgr_val = sc.first()
                mgr = await mgr_val if inspect.isawaitable(mgr_val) else mgr_val
        elif hasattr(mgr_res, "scalar_one_or_none"):
            mgr_val = mgr_res.scalar_one_or_none()
            mgr = await mgr_val if inspect.isawaitable(mgr_val) else mgr_val
        if isinstance(mgr, Manager) and (
            mgr.is_active is False
            or (mgr.status or "").upper() in ("DISABLED", "INACTIVE", "DEACTIVATED", "ARCHIVED", "TERMINATED", "EXITED", "DELETED")
            or (getattr(mgr, "employment_status", "") or "").upper() in ("TERMINATED", "EXITED")
        ):
            logger.warning(
                "Authentication failed: Manager profile for user %s is deactivated/archived/terminated (status=%s, is_active=%s).",
                user.id, mgr.status, mgr.is_active
            )
            user.is_active = False
            user.account_status = "DEACTIVATED"
            await self.auth_repository.revoke_all_user_refresh_tokens(user.id)
            await self.session.commit()
            raise AppException(
                message="Account or manager profile is inactive or terminated. Please contact HR.",
                status_code=status.HTTP_403_FORBIDDEN,
                code="MANAGER_INACTIVE",
                errors=[{"field": None, "message": "MANAGER_INACTIVE"}],
            )

        # Success - log audit details
        await self.auth_repository.update_login_audit(user.id, ip_address, device)

        # Enforce that only superadmin@ofc360.com can ever hold the SUPER_ADMIN role
        user_role_str = (user.role.value if hasattr(user.role, "value") else str(user.role)).lower()
        if user_role_str == "super_admin" and user.email.lower() != "superadmin@ofc360.com":
            logger.warning(
                "Security Alert: Non-authorized account %s has role super_admin in DB. Downgrading to employee.",
                user.email,
            )
            from app.models.user.role import UserRole
            user.role = UserRole.EMPLOYEE
            self.session.add(user)
            await self.session.commit()

        # Issue tokens
        effective_role = user.role.value if hasattr(user.role, "value") else str(user.role)
        access_token, refresh_token, expires_in = await self.token_service.generate_auth_tokens(
            user_id=user.id,
            role=effective_role,
            company_id=user.company_id,
            email=user.email,
            ip_address=ip_address,
            device=device,
        )

        await self.session.commit()
        return user, access_token, refresh_token, expires_in, False

    async def verify_email_otp(
        self,
        *,
        verification_id: str,
        otp: str,
        ip_address: str | None = None,
        device: str | None = None,
    ) -> tuple:
        """Verify login OTP: validate, mark email verified, issue tokens."""
        import uuid as uuid_mod
        from app.utils.otp import OTP_PURPOSE_EMAIL_LOGIN_VERIFICATION

        # 1. Parse verification_id
        try:
            otp_uuid = uuid_mod.UUID(verification_id)
        except (ValueError, AttributeError):
            raise AppException(
                message="Invalid verification ID.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        # 2. Look up OTP record
        otp_record = await self.auth_repository.get_otp_by_id(otp_uuid)
        if not otp_record or otp_record.purpose != OTP_PURPOSE_EMAIL_LOGIN_VERIFICATION:
            raise AppException(
                message="Invalid verification ID.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        # 3. Check already used
        if otp_record.is_used:
            raise AppException(
                message="This verification code has already been used. Please request a new code.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        # 4. Check expiry
        now = datetime.now(timezone.utc)
        otp_exp = otp_record.expires_at
        if otp_exp.tzinfo is None:
            otp_exp = otp_exp.replace(tzinfo=timezone.utc)
        if now > otp_exp:
            raise AppException(
                message="This verification code has expired. Please request a new code.",
                status_code=status.HTTP_400_BAD_REQUEST,
                code="OTP_EXPIRED",
            )

        # 5. Check attempt limit
        max_attempts = getattr(settings, "OTP_MAX_ATTEMPTS", 5)
        if otp_record.attempts >= max_attempts:
            raise AppException(
                message="Too many attempts. Please request a new code.",
                status_code=status.HTTP_400_BAD_REQUEST,
                code="OTP_MAX_ATTEMPTS",
            )

        # 6. Verify OTP hash
        is_valid = verify_otp_hash(
            otp=otp,
            otp_hash=otp_record.otp_hash,
            user_id=otp_record.user_id,
            purpose=OTP_PURPOSE_EMAIL_LOGIN_VERIFICATION,
        )

        if not is_valid:
            attempts = await self.auth_repository.increment_otp_attempts(otp_record.id)
            await self.session.commit()
            if attempts >= max_attempts:
                raise AppException(
                    message="Too many attempts. Please request a new code.",
                    status_code=status.HTTP_400_BAD_REQUEST,
                    code="OTP_MAX_ATTEMPTS",
                )
            raise AppException(
                message="Invalid verification code.",
                status_code=status.HTTP_400_BAD_REQUEST,
                code="INVALID_OTP",
            )

        # 7. Atomically consume the OTP
        consumed = await self.auth_repository.consume_otp_atomic(otp_record.id)
        if not consumed:
            raise AppException(
                message="This verification code has already been used or is invalid.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        # 8. Mark user as verified and active
        await self.auth_repository.update_user_verification(otp_record.user_id)

        # 9. Invalidate any remaining login verification OTPs
        await self.auth_repository.invalidate_all_user_otps(otp_record.user_id, OTP_PURPOSE_EMAIL_LOGIN_VERIFICATION)

        # 10. Fetch the user for token generation
        from sqlalchemy.orm import selectinload
        from sqlalchemy import select
        user_result = await self.session.execute(
            select(User)
            .options(selectinload(User.company))
            .where(User.id == otp_record.user_id)
            .execution_options(bypass_tenant=True)
        )
        user = user_result.scalars().first()
        if not user:
            raise AppException(
                message="User not found.",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        # 11. Log audit details
        await self.auth_repository.update_login_audit(user.id, ip_address, device)

        # 12. Issue tokens
        effective_role = user.role.value if hasattr(user.role, "value") else str(user.role)
        access_token, refresh_token, expires_in = await self.token_service.generate_auth_tokens(
            user_id=user.id,
            role=effective_role,
            company_id=user.company_id,
            email=user.email,
            ip_address=ip_address,
            device=device,
        )

        await self.session.commit()

        # Send welcome email on first verification
        try:
            await self.email_service.send_welcome_email(user.email, user.name or "User")
        except Exception as mail_err:
            logger.warning("Failed to send welcome email to %s: %s", user.email, mail_err)

        return user, access_token, refresh_token, expires_in

    async def resend_email_otp(
        self,
        *,
        verification_id: str,
        email: str | None = None,
    ) -> str:
        """Resend login verification OTP: invalidate old, generate new, enforce cooldown. Returns new verification_id."""
        import uuid as uuid_mod
        from app.utils.otp import OTP_PURPOSE_EMAIL_LOGIN_VERIFICATION

        # 1. Parse verification_id to find the user
        user = None
        try:
            otp_uuid = uuid_mod.UUID(verification_id)
            old_otp = await self.auth_repository.get_otp_by_id(otp_uuid)
            if old_otp and old_otp.purpose == OTP_PURPOSE_EMAIL_LOGIN_VERIFICATION:
                user = await self.auth_repository.get_user_by_id(old_otp.user_id)
        except (ValueError, AttributeError):
            pass

        # Fallback: look up by email
        if not user and email:
            user = await self.auth_repository.get_user_by_email(email.strip().lower())

        if not user:
            raise AppException(
                message="Invalid verification session.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        # 2. Check cooldown (60 seconds)
        latest_otp = await self.auth_repository.get_latest_otp(user.id, OTP_PURPOSE_EMAIL_LOGIN_VERIFICATION)
        now = datetime.now(timezone.utc)
        cooldown_seconds = getattr(settings, "OTP_RESEND_COOLDOWN_SECONDS", 60)
        if latest_otp:
            created_at = latest_otp.created_at
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            elapsed = (now - created_at).total_seconds()
            if elapsed < cooldown_seconds:
                remaining = int(cooldown_seconds - elapsed)
                raise AppException(
                    message=f"Please wait {remaining} seconds before requesting another code.",
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    code="RESEND_COOLDOWN",
                )

        # 3. Invalidate old OTPs
        await self.auth_repository.invalidate_all_user_otps(user.id, OTP_PURPOSE_EMAIL_LOGIN_VERIFICATION)

        # 4. Generate new OTP
        otp_code = generate_otp()
        otp_expiry = now + timedelta(minutes=settings.OTP_EXPIRE_MINUTES)
        hashed_otp = hash_otp(otp=otp_code, user_id=user.id, purpose=OTP_PURPOSE_EMAIL_LOGIN_VERIFICATION)

        new_otp_record = await self.auth_repository.create_otp(
            user_id=user.id,
            otp_hash=hashed_otp,
            purpose=OTP_PURPOSE_EMAIL_LOGIN_VERIFICATION,
            expires_at=otp_expiry,
        )

        # 5. Resolve company name
        company_name = "OFC360"
        if getattr(user, "company", None):
            try:
                company_name = user.company.name or company_name
            except Exception:
                pass

        # 6. Send email
        try:
            await self.email_service.send_login_verification_otp_email(
                email=user.email,
                name=user.name or "User",
                otp=otp_code,
                expiry_minutes=settings.OTP_EXPIRE_MINUTES,
                company_name=company_name,
            )
        except Exception as mail_err:
            logger.warning("Failed to send resend login verification OTP email to user_id=%s: %s", user.id, mail_err)

        await self.session.commit()
        return str(new_otp_record.id)


    async def logout(self, *, access_token: str, refresh_token: str | None = None) -> None:
        """Revoke refresh token session and add access token to Redis blacklist.
        
        refresh_token is optional to support frontend calling logout without body.
        """

        # Revoke DB refresh token if provided
        if refresh_token:
            await self.token_service.revoke_refresh_token(refresh_token)

        # Blacklist access token for its remaining lifetime in Redis
        if access_token:
            try:
                claims = decode_token(access_token)
                exp = claims.get("exp")
                if exp:
                    ttl = max(1, int(exp - datetime.now(timezone.utc).timestamp()))
                    await redis_client.blacklist_token(access_token, ttl)
            except Exception:
                # If we can't decode, use default TTL
                await redis_client.blacklist_token(access_token, settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60)

        await self.session.commit()

    async def forgot_password(self, payload: ForgotPasswordRequest) -> None:
        """Generate a password reset OTP and send it via email/SMS, handling users defensively.
        
        Supports both email and phone as identifier.
        """

        # Lookup user by identifier (email or phone)
        identifier = payload.identifier.strip().lower() if payload.identifier else ""
        if not identifier:
            raise AppException(message="Identifier is required.", status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)
        
        user = None
        if "@" in identifier:
            user = await self.auth_repository.get_user_by_email(identifier)
        else:
            user = await self.auth_repository.get_user_by_phone(identifier)
        
        # Defensively exit if user does not exist or is deleted (don't reveal user existence)
        if not user or user.is_deleted:
            logger.info("Forgot password requested for non-existent or deleted identifier: %s", identifier)
            return

        # Generate OTP
        otp_code = generate_otp()
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.OTP_EXPIRE_MINUTES)

        try:
            # Invalidate any previous reset OTPs
            await self.auth_repository.invalidate_all_user_otps(user.id, "password_reset")

            # Store OTP
            hashed_otp = hash_otp(otp=otp_code, user_id=user.id, purpose="password_reset")
            await self.auth_repository.create_otp(
                user_id=user.id,
                otp_hash=hashed_otp,
                purpose="password_reset",
                expires_at=expires_at,
            )

            # Send OTP via email
            await self.email_service.send_password_reset_otp(
                email=user.email,
                name=user.name,
                otp=otp_code,
                expiry_minutes=settings.OTP_EXPIRE_MINUTES,
            )
            await self.session.commit()
        except RuntimeError as exc:
            await self.session.rollback()
            logger.exception("Forgot password OTP sending failed", exc_info=exc)
            raise AppException(
                message="Failed to send password reset OTP.",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                errors=[{"field": None, "message": str(exc)}],
            ) from exc
        except Exception:
            await self.session.rollback()
            raise

    async def reset_password(self, payload: ResetPasswordRequest) -> None:
        """Verify the password reset token or OTP and update credentials, revoking active sessions and JWTs."""
        
        now = datetime.now(timezone.utc)
        
        # Lookup user by identifier (email or phone)
        identifier = payload.email.strip().lower() if payload.email else ""
        if not identifier:
            raise AppException(message="Email is required.", status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)
        
        user = await self.auth_repository.get_user_by_email(identifier)
        if not user or user.is_deleted:
            raise AppException(message="User account not found.", status_code=status.HTTP_404_NOT_FOUND)

        # Flow 1: Reset token from verify-reset-otp step
        if payload.reset_token:
            hashed_token = hashlib.sha256(payload.reset_token.encode()).hexdigest()
            token_record = await self.auth_repository.get_password_reset_token(hashed_token)
            if not token_record:
                raise AppException(message="Invalid reset token.", status_code=status.HTTP_400_BAD_REQUEST)
            
            # Check if already used
            if token_record.used_at is not None:
                raise AppException(message="Reset token has already been used.", status_code=status.HTTP_400_BAD_REQUEST)
            
            # Check expiration
            if now > token_record.expires_at:
                raise AppException(message="Reset token has expired.", status_code=status.HTTP_400_BAD_REQUEST)
            
            # Verify token belongs to this user
            if token_record.user_id != user.id:
                raise AppException(message="Invalid reset token.", status_code=status.HTTP_400_BAD_REQUEST)
            
            # Atomically mark token as used
            consumed = await self.auth_repository.consume_password_reset_token_atomic(token_record.id)
            if hasattr(self.auth_repository, "mark_password_reset_token_used"):
                await self.auth_repository.mark_password_reset_token_used(token_record.id)
            if not consumed and consumed is not None:
                raise AppException(message="Reset token has already been used.", status_code=status.HTTP_400_BAD_REQUEST)
                
        # Flow 2: OTP-based (backward compatibility - re-validate OTP)
        elif payload.otp:
            # Get latest unused OTP record for password_reset
            otp_record = await self.auth_repository.get_latest_otp(user.id, "password_reset")
            if not otp_record:
                raise AppException(message="Invalid OTP.", status_code=status.HTTP_400_BAD_REQUEST)

            # Check expiry
            if now > otp_record.expires_at:
                raise AppException(message="OTP has expired.", status_code=status.HTTP_400_BAD_REQUEST)

            # Verify hash
            is_valid = verify_otp_hash(
                otp=payload.otp,
                otp_hash=otp_record.otp_hash,
                user_id=user.id,
                purpose="password_reset",
            )

            if not is_valid:
                # Increment attempts
                attempts = await self.auth_repository.increment_otp_attempts(otp_record.id)
                if attempts >= settings.OTP_MAX_ATTEMPTS:
                    # Invalidate current OTP
                    await self.auth_repository.invalidate_all_user_otps(user.id, "password_reset")
                    raise AppException(
                        message="Too many wrong attempts. Please request a new OTP.",
                        status_code=status.HTTP_400_BAD_REQUEST,
                    )
                await self.session.commit()
                raise AppException(message="Invalid OTP.", status_code=status.HTTP_400_BAD_REQUEST)

            # Atomically mark OTP as used
            consumed = await self.auth_repository.consume_otp_atomic(otp_record.id)
            if hasattr(self.auth_repository, "mark_otp_used"):
                await self.auth_repository.mark_otp_used(otp_record.id)
            if not consumed and consumed is not None:
                raise AppException(message="OTP has already been used or is invalid.", status_code=status.HTTP_400_BAD_REQUEST)
        else:
            raise AppException(message="Either reset_token or OTP is required.", status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)

        # Update credentials
        new_password_hash = hash_password(payload.new_password)
        await self.auth_repository.update_user_password(user.id, new_password_hash)
        await self.auth_repository.revoke_all_user_refresh_tokens(user.id, reason="PASSWORD_RESET")
        await redis_client.revoke_user_tokens(user.id)
        
        # Invalidate all other pending password reset tokens and OTPs for the user
        await self.auth_repository.invalidate_all_user_password_resets(user.id)
        await self.auth_repository.invalidate_all_user_otps(user.id)
        await self.session.commit()


    async def login_google(
        self,
        email: str,
        name: str | None = None,
        ip_address: str | None = None,
        device: str | None = None,
    ) -> tuple[User, str, str, int]:
        """Authenticate user via Google SSO with strict role check (Company Admin ONLY)."""
        normalized_email = email.strip().lower()
        user = await self.auth_repository.get_user_by_email(normalized_email)

        if not user:
            logger.warning("Google login failed: User not found | email=%s", normalized_email)
            raise AppException(
                message="No Company Admin account found for this Google email. Google login is permitted exclusively for registered Company Admins.",
                status_code=status.HTTP_404_NOT_FOUND,
                errors=[{"field": "email", "message": "No Company Admin account found for this Google email."}],
            )

        # STRICT ROLE CHECK: Reject employees and company members
        user_role = (user.role.value if hasattr(user.role, "value") else str(user.role)).lower()
        if user_role not in ("super_admin", "hr_admin", "it_admin"):
            logger.warning("Google login rejected for non-admin user | user_id=%s | role=%s | email=%s", user.id, user.role, normalized_email)
            raise AppException(
                message="Access Restricted: Google login is permitted exclusively for Company Admins. Employees and company members must sign in using their work email and password.",
                status_code=status.HTTP_403_FORBIDDEN,
                errors=[{"field": None, "message": "Google login restricted to Company Admins only."}],
            )

        # Activate & verify admin if needed
        if not user.is_verified or not user.is_active:
            user.is_verified = True
            user.is_active = True
            self.session.add(user)

        await self.auth_repository.update_login_audit(user.id, ip_address, device)

        effective_role = user.role.value if hasattr(user.role, "value") else str(user.role)
        access_token, refresh_token, expires_in = await self.token_service.generate_auth_tokens(
            user_id=user.id,
            role=effective_role,
            company_id=user.company_id,
            email=user.email,
            ip_address=ip_address,
            device=device,
        )

        await self.session.commit()
        return user, access_token, refresh_token, expires_in

    async def login_github(
        self,
        code: str | None = None,
        access_token: str | None = None,
        redirect_uri: str | None = None,
        email: str | None = None,
        name: str | None = None,
        ip_address: str | None = None,
        device: str | None = None,
    ) -> tuple[User, str, str, int]:
        """Authenticate user via GitHub OAuth SSO (code exchange or direct GitHub token/email)."""
        target_email: str | None = email
        target_name: str | None = name

        # 1. Exchange authorization code for GitHub access token if code provided
        if code:
            client_id = settings.GITHUB_CLIENT_ID
            client_secret = (
                settings.GITHUB_CLIENT_SECRET.get_secret_value()
                if hasattr(settings.GITHUB_CLIENT_SECRET, "get_secret_value")
                else str(settings.GITHUB_CLIENT_SECRET)
            )

            if not client_id or not client_secret:
                logger.error("GitHub OAuth credentials not configured.")
                raise AppException(
                    message="GitHub OAuth credentials are not configured on the server.",
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

            token_payload = {
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
            }
            cb_uri = redirect_uri or settings.GITHUB_REDIRECT_URI
            if cb_uri:
                token_payload["redirect_uri"] = cb_uri

            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    token_resp = await client.post(
                        "https://github.com/login/oauth/access_token",
                        data=token_payload,
                        headers={"Accept": "application/json"},
                    )
                    token_data = token_resp.json()
            except Exception as exc:
                logger.error("GitHub token exchange failed: %s", exc)
                raise AppException(
                    message=f"Failed to communicate with GitHub token service: {exc}",
                    status_code=status.HTTP_502_BAD_GATEWAY,
                )

            if "error" in token_data:
                err_desc = token_data.get("error_description") or token_data.get("error")
                logger.warning("GitHub OAuth token exchange returned error: %s", token_data)
                raise AppException(
                    message=f"GitHub authentication error: {err_desc}",
                    status_code=status.HTTP_400_BAD_REQUEST,
                    errors=[{"field": "code", "message": str(err_desc)}],
                )

            access_token = token_data.get("access_token")
            if not access_token:
                raise AppException(
                    message="No access token received from GitHub.",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

        # 2. Fetch user profile from GitHub API using the access token
        if access_token:
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    gh_headers = {
                        "Authorization": f"Bearer {access_token}",
                        "User-Agent": "OFC360-HRMS",
                        "Accept": "application/vnd.github+json",
                    }
                    user_resp = await client.get("https://api.github.com/user", headers=gh_headers)
                    if user_resp.status_code != 200:
                        logger.warning("GitHub user profile fetch failed with status %s: %s", user_resp.status_code, user_resp.text)
                        raise AppException(
                            message="Failed to retrieve profile from GitHub.",
                            status_code=status.HTTP_400_BAD_REQUEST,
                        )
                    user_data = user_resp.json()
                    target_name = target_name or user_data.get("name") or user_data.get("login")
                    target_email = user_data.get("email")

                    # If email is private on GitHub profile, fetch from emails endpoint
                    if not target_email:
                        emails_resp = await client.get("https://api.github.com/user/emails", headers=gh_headers)
                        if emails_resp.status_code == 200:
                            emails_list = emails_resp.json()
                            if isinstance(emails_list, list):
                                # Prefer primary and verified email
                                primary_verified = next((e["email"] for e in emails_list if e.get("verified") and e.get("primary")), None)
                                # Next, any verified email
                                any_verified = primary_verified or next((e["email"] for e in emails_list if e.get("verified")), None)
                                # Next, any available email
                                target_email = any_verified or (emails_list[0]["email"] if emails_list else None)
            except AppException:
                raise
            except Exception as exc:
                logger.error("GitHub API profile fetch error: %s", exc)
                raise AppException(
                    message=f"Failed to retrieve account details from GitHub: {exc}",
                    status_code=status.HTTP_502_BAD_GATEWAY,
                )

        if not target_email:
            raise AppException(
                message="No verified email address found on your GitHub account.",
                status_code=status.HTTP_400_BAD_REQUEST,
                errors=[{"field": "email", "message": "Verified email address is required from GitHub."}],
            )

        normalized_email = target_email.strip().lower()
        user = await self.auth_repository.get_user_by_email(normalized_email)

        if not user:
            logger.warning("GitHub login failed: User not found | email=%s", normalized_email)
            raise AppException(
                message=f"No account found for '{normalized_email}'. Please register or contact your administrator.",
                status_code=status.HTTP_404_NOT_FOUND,
                errors=[{"field": "email", "message": f"No account found for {normalized_email}"}],
            )

        # Activate & verify user if needed
        if not user.is_verified or not user.is_active:
            user.is_verified = True
            user.is_active = True
            self.session.add(user)

        await self.auth_repository.update_login_audit(user.id, ip_address, device)

        effective_role = user.role.value if hasattr(user.role, "value") else str(user.role)
        access_token_jwt, refresh_token_jwt, expires_in = await self.token_service.generate_auth_tokens(
            user_id=user.id,
            role=effective_role,
            company_id=user.company_id,
            email=user.email,
            ip_address=ip_address,
            device=device,
        )

        await self.session.commit()
        return user, access_token_jwt, refresh_token_jwt, expires_in




async def get_auth_service(
    session: AsyncSession = Depends(get_db_session),
    email_service: EmailService = Depends(get_email_service),
    token_service: TokenService = Depends(get_token_service),
) -> AuthService:
    """FastAPI dependency that wires the auth service."""

    return AuthService(
        session=session,
        auth_repository=AuthRepository(session),
        email_service=email_service,
        token_service=token_service,
    )
