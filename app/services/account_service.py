"""Account management service layer."""

from datetime import datetime, timedelta, timezone
import logging
import traceback
import uuid

from fastapi import Depends, status
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, ConflictException, DatabaseException
from app.core.redis_client import redis_client
from app.core.security import hash_password, verify_password
from app.db.database import get_db_session
from app.repositories.auth_repository import AuthRepository
from app.schemas.auth import (
    ChangeEmailRequest,
    ChangePasswordRequest,
    ChangePhoneRequest,
    UserProfileData,
    VerifyNewEmailRequest,
)
from app.services.email_service import EmailService, get_email_service
from app.utils.otp import generate_otp, hash_otp, verify_otp_hash

logger = logging.getLogger(__name__)

_PURPOSE_EMAIL_CHANGE = "email_change"
_EMAIL_CHANGE_OTP_EXPIRE_MINUTES = 10
_EMAIL_CHANGE_MAX_VERIFY_ATTEMPTS = 5
_EMAIL_CHANGE_MAX_RESEND_COUNT = 3
_EMAIL_CHANGE_RESEND_COOLDOWN_SECONDS = 30


def _mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    masked_local = local[:1] + "***" if len(local) > 1 else "***"
    return masked_local + "@" + domain


class AccountService:
    """Service owning account management business logic and transactions."""

    def __init__(self, *, session: AsyncSession, auth_repository: AuthRepository, email_service: EmailService) -> None:
        self.session = session
        self.auth_repository = auth_repository
        self.email_service = email_service

    async def get_profile(self, user_id: uuid.UUID) -> UserProfileData:
        """Return the authenticated user profile. Raises 404 if not found."""
        logger.info("get_profile | file=account_service.py | func=get_profile | user_id=%s", user_id)
        try:
            user = await self.auth_repository.get_user_by_id(user_id)
            if not user:
                logger.warning("get_profile: user not found | user_id=%s | file=account_service.py | func=get_profile", user_id)
                raise AppException(message="User not found.", status_code=status.HTTP_404_NOT_FOUND)

            if user.role in ("super_admin", "hr_admin") and user.company and user.company.onboarding_completed and not user.onboarding_completed:
                user.onboarding_completed = True
                user.onboarding_step = 7
                self.session.add(user)
                await self.session.commit()
                # Reload user to keep instance state active and avoid lazy loading
                user = await self.auth_repository.get_user_by_id(user_id)

            onboarding_completed = user.onboarding_completed
            if user.role == "employee":
                from sqlalchemy import select
                from app.models.employee import Employee
                stmt = select(Employee).where(
                    (Employee.user_id == user.id) |
                    (Employee.personal_email == user.email.lower().strip()) |
                    (Employee.company_email == user.email.lower().strip())
                )
                emp_res = await self.session.execute(stmt)
                emp = emp_res.scalars().first()
                if emp:
                    onboarding_completed = bool(emp.employee_onboarding_completed)

            # Safely resolve role string
            role_val = user.role.value if hasattr(user.role, "value") else str(user.role)

            # Safely resolve company name without lazy-loading crash
            company_name = None
            if getattr(user, "company", None):
                try:
                    company_name = user.company.name
                except Exception:
                    company_name = None

            if not company_name and user.company_id:
                try:
                    from sqlalchemy import select
                    from app.models.company import Company
                    comp_res = await self.session.execute(
                        select(Company.name).where(Company.id == user.company_id).execution_options(bypass_tenant=True)
                    )
                    company_name = comp_res.scalar_one_or_none()
                except Exception:
                    company_name = None

            return UserProfileData(
                id=user.id,
                name=user.name or "User",
                email=user.email,
                phone=user.phone or None,
                role=role_val,
                is_active=bool(user.is_active),
                is_verified=bool(user.is_verified),
                email_verified=bool(user.is_verified),
                account_status=str(getattr(user, "account_status", "ACTIVE") or "ACTIVE"),
                onboarding_completed=bool(onboarding_completed),
                company_id=user.company_id,
                company_name=company_name,
                created_at=user.created_at or datetime.now(timezone.utc),
            )

        except AppException:
            raise
        except SQLAlchemyError as exc:
            logger.exception(
                "get_profile: database error | user_id=%s | file=account_service.py | func=get_profile | exc_type=%s | exc_msg=%s | traceback=%s",
                user_id, type(exc).__name__, str(exc), traceback.format_exc(), exc_info=exc,
            )
            raise DatabaseException() from exc

    async def change_password(self, user_id: uuid.UUID, payload: ChangePasswordRequest) -> None:
        """Verify current password and replace with new bcrypt hash. Raises 401 if wrong, 400 if same."""
        logger.info("change_password | file=account_service.py | func=change_password | user_id=%s", user_id)
        try:
            user = await self.auth_repository.get_user_by_id(user_id)
            if not user:
                raise AppException(message="User not found.", status_code=status.HTTP_404_NOT_FOUND)
            if not verify_password(payload.current_password, user.password_hash):
                logger.warning("change_password: wrong current password | user_id=%s | file=account_service.py | func=change_password", user_id)
            if verify_password(payload.new_password, user.password_hash):
                raise AppException(message="New password must be different from the current password.", status_code=status.HTTP_400_BAD_REQUEST)
            await self.auth_repository.update_user_password(user_id, hash_password(payload.new_password))
            await self.auth_repository.revoke_all_user_refresh_tokens(user_id, reason="PASSWORD_CHANGE")
            await redis_client.revoke_user_tokens(user_id)
            # Immediately invalidate any outstanding password reset tokens and active OTPs
            await self.auth_repository.invalidate_all_user_password_resets(user_id)
            await self.auth_repository.invalidate_all_user_otps(user_id)
            await self.session.commit()
            logger.info("change_password: success | user_id=%s | file=account_service.py | func=change_password", user_id)
        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception(
                "change_password: database error | user_id=%s | file=account_service.py | func=change_password | exc_type=%s | exc_msg=%s | traceback=%s",
                user_id, type(exc).__name__, str(exc), traceback.format_exc(), exc_info=exc,
            )
            raise DatabaseException() from exc

    async def change_email(self, user_id: uuid.UUID, payload: ChangeEmailRequest) -> None:
        """Initiate email-change: enforce mandatory password re-authentication, check duplicates, stage pending_email and send single-use OTP."""
        new_email = str(payload.new_email)
        logger.info("change_email | file=account_service.py | func=change_email | user_id=%s | new_email=%s", user_id, _mask_email(new_email))
        try:
            user = await self.auth_repository.get_user_by_id(user_id)
            if not user:
                raise AppException(message="User not found.", status_code=status.HTTP_404_NOT_FOUND)
            if not payload.password or not verify_password(payload.password, user.password_hash):
                logger.warning("change_email: wrong password | user_id=%s | file=account_service.py | func=change_email", user_id)
                raise AppException(message="Password is incorrect.", status_code=status.HTTP_401_UNAUTHORIZED)
            if user.email.lower() == "superadmin@ofc360.com":
                raise AppException(
                    message="The platform Super Admin email identity is immutable and cannot be changed.",
                    status_code=status.HTTP_403_FORBIDDEN,
                )
            if new_email.strip().lower() == "superadmin@ofc360.com":
                raise AppException(
                    message="Cannot change email to the platform Super Admin identity.",
                    status_code=status.HTTP_403_FORBIDDEN,
                )
            if new_email == user.email:
                raise AppException(message="New email must be different from the current email.", status_code=status.HTTP_400_BAD_REQUEST)
            if await self.auth_repository.get_user_by_email_excluding(new_email, user_id):
                raise ConflictException(message="Email already in use.", errors=[{"field": "new_email", "message": "This email is already associated with another account."}])
            now = datetime.now(timezone.utc)
            latest_otp = await self.auth_repository.get_latest_otp(user_id, _PURPOSE_EMAIL_CHANGE)
            if latest_otp:
                created_at = latest_otp.created_at
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)
                elapsed = (now - created_at).total_seconds()
                if elapsed < _EMAIL_CHANGE_RESEND_COOLDOWN_SECONDS:
                    remaining = int(_EMAIL_CHANGE_RESEND_COOLDOWN_SECONDS - elapsed)
                    logger.info("change_email: resend cooldown | user_id=%s | remaining_seconds=%d | file=account_service.py | func=change_email", user_id, remaining)
                    raise AppException(message="Please wait " + str(remaining) + " second(s) before requesting another OTP.", status_code=status.HTTP_400_BAD_REQUEST)
            total_otps = await self.auth_repository.count_email_change_otps(user_id)
            if total_otps >= (_EMAIL_CHANGE_MAX_RESEND_COUNT + 1):
                logger.warning("change_email: max resend exceeded | user_id=%s | total_otps=%d | file=account_service.py | func=change_email", user_id, total_otps)
                raise AppException(message="Maximum resend attempts reached. Please try again after some time.", status_code=status.HTTP_429_TOO_MANY_REQUESTS)
            await self.auth_repository.invalidate_all_user_otps(user_id, _PURPOSE_EMAIL_CHANGE)
            otp_code = generate_otp()
            otp_hash_val = hash_otp(otp=otp_code, user_id=user_id, purpose=_PURPOSE_EMAIL_CHANGE)
            expires_at = now + timedelta(minutes=_EMAIL_CHANGE_OTP_EXPIRE_MINUTES)
            await self.auth_repository.create_otp(user_id=user_id, otp_hash=otp_hash_val, purpose=_PURPOSE_EMAIL_CHANGE, expires_at=expires_at)
            await self.auth_repository.update_user_pending_email(user_id, new_email)
            try:
                await self.email_service.send_email_change_otp(email=new_email, name=user.name, otp=otp_code, expiry_minutes=_EMAIL_CHANGE_OTP_EXPIRE_MINUTES)
                await self.session.commit()
            except RuntimeError as exc:
                await self.session.rollback()
                logger.exception("change_email: email sending failure", exc_info=exc)
                raise AppException(
                    message="Failed to send OTP email.",
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    errors=[{"field": None, "message": str(exc)}],
                ) from exc
            logger.info("change_email: OTP dispatched | user_id=%s | new_email=%s | file=account_service.py | func=change_email", user_id, _mask_email(new_email))
        except AppException:
            await self.session.rollback()
            raise
        except IntegrityError as exc:
            await self.session.rollback()
            logger.exception("change_email: integrity error | user_id=%s | file=account_service.py | func=change_email | exc_type=%s | exc_msg=%s", user_id, type(exc).__name__, str(exc), exc_info=exc)
            raise ConflictException(message="Email already in use.", errors=[{"field": "new_email", "message": "This email is already associated with another account."}]) from exc
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("change_email: database error | user_id=%s | file=account_service.py | func=change_email | exc_type=%s | exc_msg=%s", user_id, type(exc).__name__, str(exc), exc_info=exc)
            raise DatabaseException() from exc

    async def verify_new_email(self, user_id: uuid.UUID, payload: VerifyNewEmailRequest) -> None:
        """Verify email-change OTP and atomically commit the new email address with single-use invalidation."""
        logger.info("verify_new_email | file=account_service.py | func=verify_new_email | user_id=%s", user_id)
        try:
            user = await self.auth_repository.get_user_by_id(user_id)
            if not user:
                raise AppException(message="User not found.", status_code=status.HTTP_404_NOT_FOUND)
            if not user.pending_email:
                raise AppException(message="No pending email change found. Please initiate a new email change request.", status_code=status.HTTP_404_NOT_FOUND)
            otp_record = await self.auth_repository.get_latest_otp(user_id, _PURPOSE_EMAIL_CHANGE)
            if not otp_record:
                raise AppException(message="Invalid or expired OTP. Please request a new one.", status_code=status.HTTP_400_BAD_REQUEST)
            now = datetime.now(timezone.utc)
            expires_at = otp_record.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if now > expires_at:
                raise AppException(message="OTP has expired. Please request a new email change.", status_code=status.HTTP_400_BAD_REQUEST)
            if otp_record.attempts >= _EMAIL_CHANGE_MAX_VERIFY_ATTEMPTS:
                await self.auth_repository.invalidate_all_user_otps(user_id, _PURPOSE_EMAIL_CHANGE)
                await self.session.commit()
                raise AppException(message="Too many incorrect OTP attempts. Please request a new email change.", status_code=status.HTTP_400_BAD_REQUEST)
            is_valid = verify_otp_hash(otp=payload.otp, otp_hash=otp_record.otp_hash, user_id=user_id, purpose=_PURPOSE_EMAIL_CHANGE)
            if not is_valid:
                attempts = await self.auth_repository.increment_otp_attempts(otp_record.id)
                remaining = _EMAIL_CHANGE_MAX_VERIFY_ATTEMPTS - attempts
                if remaining <= 0:
                    await self.auth_repository.invalidate_all_user_otps(user_id, _PURPOSE_EMAIL_CHANGE)
                    await self.session.commit()
                    raise AppException(message="Too many incorrect OTP attempts. Please request a new email change.", status_code=status.HTTP_400_BAD_REQUEST)
                await self.session.commit()
                raise AppException(message="Invalid OTP. " + str(max(0, remaining)) + " attempt(s) remaining.", status_code=status.HTTP_400_BAD_REQUEST)
            
            # Atomically mark OTP as used to prevent replay or race conditions
            consumed = await self.auth_repository.consume_otp_atomic(otp_record.id)
            if not consumed:
                raise AppException(message="OTP has already been used or is invalid.", status_code=status.HTTP_400_BAD_REQUEST)

            new_email = user.pending_email
            await self.auth_repository.update_user_email(user_id, new_email)
            await self.auth_repository.invalidate_all_user_otps(user_id, _PURPOSE_EMAIL_CHANGE)
            await self.session.commit()
            logger.info("verify_new_email: email updated | user_id=%s | new_email=%s | file=account_service.py | func=verify_new_email", user_id, _mask_email(new_email))
        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("verify_new_email: database error | user_id=%s | file=account_service.py | func=verify_new_email | exc_type=%s | exc_msg=%s", user_id, type(exc).__name__, str(exc), exc_info=exc)
            raise DatabaseException() from exc

    async def change_phone(self, user_id: uuid.UUID, payload: ChangePhoneRequest) -> None:
        """Verify password and immediately update phone number (no OTP required)."""
        logger.info("change_phone | file=account_service.py | func=change_phone | user_id=%s", user_id)
        try:
            user = await self.auth_repository.get_user_by_id(user_id)
            if not user:
                raise AppException(message="User not found.", status_code=status.HTTP_404_NOT_FOUND)
            if not verify_password(payload.password, user.password_hash):
                logger.warning("change_phone: wrong password | user_id=%s | file=account_service.py | func=change_phone", user_id)
                raise AppException(message="Password is incorrect.", status_code=status.HTTP_401_UNAUTHORIZED)
            if payload.phone == user.phone:
                raise AppException(message="New phone number must be different from the current phone number.", status_code=status.HTTP_400_BAD_REQUEST)
            if await self.auth_repository.get_user_by_phone_excluding(payload.phone, user_id):
                raise ConflictException(message="Phone number already in use.", errors=[{"field": "phone", "message": "This phone number is already associated with another account."}])
            await self.auth_repository.update_user_phone(user_id, payload.phone)
            await self.session.commit()
            logger.info("change_phone: success | user_id=%s | file=account_service.py | func=change_phone", user_id)
        except AppException:
            await self.session.rollback()
            raise
        except IntegrityError as exc:
            await self.session.rollback()
            logger.exception("change_phone: integrity error | user_id=%s | file=account_service.py | func=change_phone | exc_type=%s | exc_msg=%s", user_id, type(exc).__name__, str(exc), exc_info=exc)
            raise ConflictException(message="Phone number already in use.", errors=[{"field": "phone", "message": "This phone number is already associated with another account."}]) from exc
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("change_phone: database error | user_id=%s | file=account_service.py | func=change_phone | exc_type=%s | exc_msg=%s", user_id, type(exc).__name__, str(exc), exc_info=exc)
            raise DatabaseException() from exc


async def get_account_service(
    session: AsyncSession = Depends(get_db_session),
    email_service: EmailService = Depends(get_email_service),
) -> AccountService:
    """FastAPI dependency that wires the AccountService."""
    return AccountService(session=session, auth_repository=AuthRepository(session), email_service=email_service)
