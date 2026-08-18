"""HR Admin service for creating and managing internal company users."""

from datetime import date, datetime, timedelta, timezone
import logging
import secrets
import uuid

from fastapi import Depends, status
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.exceptions import AppException, ConflictException
from app.core.security import hash_password
from app.db.database import get_db_session
from app.models.audit_log import AuditLog
from app.models.employee import Employee
from app.models.manager import Manager
from app.models.user import User, UserRole, UserAccountStatus
from app.schemas.hr_admin import (
    ALLOWED_HR_ADMIN_ROLES,
    HRAdminCreateUserRequest,
    HRAdminUpdateUserRequest,
    HRAdminUserListResponse,
    HRAdminUserResponse,
)
from app.services.email_service import EmailService, get_email_service
from app.utils.employee import generate_employee_id, generate_temp_password

logger = logging.getLogger(__name__)


class HRAdminService:
    """Service handling HR Admin operations on internal company users."""

    def __init__(self, session: AsyncSession, email_service: EmailService) -> None:
        self.session = session
        self.email_service = email_service

    async def create_user(
        self,
        admin_id: uuid.UUID,
        company_id: uuid.UUID,
        payload: HRAdminCreateUserRequest,
    ) -> HRAdminUserResponse:
        """Create a new internal company user (Employee, Manager, Executive, IT Admin) under the caller's organization."""

        # 1. Role validation & Privilege Escalation Prevention
        role_str = payload.role.strip().lower()
        if role_str not in ALLOWED_HR_ADMIN_ROLES:
            raise AppException(
                message="HR Admins can only create EMPLOYEE, MANAGER, EXECUTIVE, or IT_ADMIN accounts.",
                status_code=status.HTTP_403_FORBIDDEN,
                errors=[{"field": "role", "message": "Unauthorized role selection."}],
            )

        # 2. Email uniqueness check
        email_clean = str(payload.email).strip().lower()
        existing_user = await self.session.execute(
            select(User).where(
                func.lower(User.email) == email_clean,
                (User.is_deleted.is_(False) | User.is_deleted.is_(None)),
            ).execution_options(bypass_tenant=True)
        )
        if existing_user.scalars().first():
            raise ConflictException(
                message="A user with this email address already exists.",
                field="email",
                errors=[{"field": "email", "message": "Email already in use."}],
            )

        # 3. Generate activation token & temporary credentials
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.ACTIVATION_TOKEN_EXPIRE_HOURS)
        temp_password = generate_temp_password()
        password_hash = hash_password(temp_password)

        full_name = f"{payload.first_name} {payload.last_name}".strip()
        user_role_enum = UserRole.from_str(role_str)

        # 4. Create User Record (bound to company_id)
        user = User(
            id=uuid.uuid4(),
            company_id=company_id,
            name=full_name,
            email=email_clean,
            phone=payload.phone or "0000000000",
            password_hash=password_hash,
            role=user_role_enum,
            account_status=UserAccountStatus.INVITED.value,
            email_verification_token=token,
            email_verification_expires_at=expires_at,
            created_by=admin_id,
            is_active=False,
            is_verified=False,
            must_change_password=True,
        )
        self.session.add(user)
        await self.session.flush()

        # 5. Create Employee Profile
        emp_code = await generate_employee_id(self.session)
        employee = Employee(
            id=uuid.uuid4(),
            user_id=user.id,
            company_id=company_id,
            employee_id=emp_code,
            first_name=payload.first_name.strip(),
            last_name=payload.last_name.strip(),
            personal_email=email_clean,
            company_email=email_clean,
            phone=payload.phone or "0000000000",
            department=payload.department or "General",
            designation=payload.designation or role_str.capitalize(),
            role=role_str,
            employment_type=payload.employment_type or "FULL_TIME",
            status="INVITED",
            verification_status="PENDING_ADMIN_CREATED",
            joining_date=payload.joining_date or datetime.now(timezone.utc).date(),
            basic_salary=payload.basic_salary,
            ctc=payload.ctc,
            activation_token=token,
            activation_token_expires_at=expires_at,
            invited_at=datetime.now(timezone.utc),
            invited_by=admin_id,
            created_by=admin_id,
        )
        self.session.add(employee)

        # 6. If role is MANAGER, create Manager record for manager table compatibility
        if role_str == UserRole.MANAGER.value:
            mgr_record = Manager(
                id=uuid.uuid4(),
                user_id=user.id,
                company_id=company_id,
                manager_id=f"MGR-{emp_code.split('-')[-1] if '-' in emp_code else emp_code}",
                first_name=payload.first_name.strip(),
                last_name=payload.last_name.strip(),
                personal_email=email_clean,
                company_email=email_clean,
                phone=payload.phone or "0000000000",
                department=payload.department or "Management",
                designation=payload.designation or "Manager",
                role="manager",
                status="INVITED",
                activation_token=token,
                activation_token_expires_at=expires_at,
                created_by=admin_id,
            )
            self.session.add(mgr_record)

        # 7. Audit Log
        audit = AuditLog(
            id=uuid.uuid4(),
            user_id=admin_id,
            company_id=company_id,
            action="CREATE_INTERNAL_USER",
            details=f"Created {role_str} user {email_clean} ({full_name})",
        )
        self.session.add(audit)

        await self.session.commit()
        await self.session.refresh(user)

        # 8. Send Invitation / Activation Email
        activation_url = f"{settings.FRONTEND_BASE_URL}/employee/activate?token={token}"
        try:
            from app.models.company import Company
            comp = await self.session.get(Company, company_id)
            comp_name = comp.name if comp else "OFC360"
            await self.email_service.send_employee_onboarding_invite(
                email=email_clean,
                name=payload.first_name,
                employee_id=emp_code,
                department=payload.department or "General",
                designation=payload.designation or role_str.capitalize(),
                joining_date=str(payload.joining_date or date.today()),
                activation_url=activation_url,
                company_name=comp_name,
            )
            logger.info("Sent onboarding invite email to %s (token=%s)", email_clean, token[:8])
        except Exception as mail_err:
            logger.warning("Failed to send invite email to %s: %s", email_clean, mail_err)

        return HRAdminUserResponse(
            id=user.id,
            name=user.name,
            first_name=payload.first_name,
            last_name=payload.last_name,
            email=user.email,
            phone=user.phone,
            role=role_str,
            department=payload.department,
            designation=payload.designation,
            account_status=user.account_status,
            is_active=bool(user.is_active),
            is_verified=bool(user.is_verified),
            created_at=user.created_at or datetime.now(timezone.utc),
            last_login_at=user.last_login_at,
            employee_id=emp_code,
        )

    async def list_users(
        self,
        company_id: uuid.UUID,
        role: str | None = None,
        status_filter: str | None = None,
        search: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> HRAdminUserListResponse:
        """List internal company users strictly scoped to the caller's company_id."""

        stmt = select(User).where(
            User.company_id == company_id,
            (User.is_deleted.is_(False) | User.is_deleted.is_(None)),
        )

        if role:
            role_clean = role.strip().lower()
            stmt = stmt.where(User.role == role_clean)

        if status_filter:
            status_clean = status_filter.strip().upper()
            if status_clean in ("ACTIVE", "INVITED", "SUSPENDED", "DEACTIVATED", "PENDING_EMAIL_VERIFICATION"):
                stmt = stmt.where(User.account_status == status_clean)
            elif status_clean == "INACTIVE":
                stmt = stmt.where(User.is_active == False)

        if search:
            search_term = f"%{search.strip()}%"
            stmt = stmt.where(
                or_(
                    User.name.ilike(search_term),
                    User.email.ilike(search_term),
                    User.phone.ilike(search_term),
                )
            )

        # Count total
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.execute(count_stmt)).scalar() or 0

        # Pagination & sorting
        offset = max(0, (page - 1) * page_size)
        stmt = stmt.order_by(User.created_at.desc()).offset(offset).limit(page_size)

        result = await self.session.execute(stmt)
        users = result.scalars().all()

        # Eager load employee info for department and designation
        items: list[HRAdminUserResponse] = []
        for u in users:
            emp_res = await self.session.execute(
                select(Employee).where(Employee.user_id == u.id, Employee.company_id == company_id)
            )
            emp = emp_res.scalars().first()

            role_val = u.role.value if hasattr(u.role, "value") else str(u.role)
            first_name = emp.first_name if emp else u.name.partition(" ")[0]
            last_name = emp.last_name if emp else u.name.partition(" ")[2]

            items.append(
                HRAdminUserResponse(
                    id=u.id,
                    name=u.name,
                    first_name=first_name,
                    last_name=last_name,
                    email=u.email,
                    phone=u.phone,
                    role=role_val,
                    department=emp.department if emp else None,
                    designation=emp.designation if emp else None,
                    account_status=getattr(u, "account_status", "ACTIVE") or "ACTIVE",
                    is_active=bool(u.is_active),
                    is_verified=bool(u.is_verified),
                    created_at=u.created_at,
                    last_login_at=u.last_login_at,
                    employee_id=emp.employee_id if emp else None,
                )
            )

        return HRAdminUserListResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
        )

    async def get_user(
        self,
        target_user_id: uuid.UUID,
        company_id: uuid.UUID,
    ) -> HRAdminUserResponse:
        """Fetch details of a company user. Enforces strict company isolation (404 on miss/cross-tenant)."""

        result = await self.session.execute(
            select(User).where(
                User.id == target_user_id,
                User.company_id == company_id,
                (User.is_deleted.is_(False) | User.is_deleted.is_(None)),
            )
        )
        user = result.scalars().first()
        if not user:
            raise AppException(message="User not found in your organization.", status_code=status.HTTP_404_NOT_FOUND)

        emp_res = await self.session.execute(
            select(Employee).where(Employee.user_id == user.id, Employee.company_id == company_id)
        )
        emp = emp_res.scalars().first()

        role_val = user.role.value if hasattr(user.role, "value") else str(user.role)
        first_name = emp.first_name if emp else user.name.partition(" ")[0]
        last_name = emp.last_name if emp else user.name.partition(" ")[2]

        return HRAdminUserResponse(
            id=user.id,
            name=user.name,
            first_name=first_name,
            last_name=last_name,
            email=user.email,
            phone=user.phone,
            role=role_val,
            department=emp.department if emp else None,
            designation=emp.designation if emp else None,
            account_status=getattr(user, "account_status", "ACTIVE") or "ACTIVE",
            is_active=bool(user.is_active),
            is_verified=bool(user.is_verified),
            created_at=user.created_at,
            last_login_at=user.last_login_at,
            employee_id=emp.employee_id if emp else None,
        )

    async def update_user(
        self,
        admin_id: uuid.UUID,
        company_id: uuid.UUID,
        target_user_id: uuid.UUID,
        payload: HRAdminUpdateUserRequest,
    ) -> HRAdminUserResponse:
        """Update internal company user details with privilege escalation checks."""

        result = await self.session.execute(
            select(User).where(
                User.id == target_user_id,
                User.company_id == company_id,
                (User.is_deleted.is_(False) | User.is_deleted.is_(None)),
            )
        )
        user = result.scalars().first()
        if not user:
            raise AppException(message="User not found in your organization.", status_code=status.HTTP_404_NOT_FOUND)

        # Privilege escalation prevention
        if payload.role:
            role_clean = payload.role.strip().lower()
            if role_clean not in ALLOWED_HR_ADMIN_ROLES:
                raise AppException(
                    message="Unauthorized role. HR Admins cannot assign Super Admin or HR Admin roles.",
                    status_code=status.HTTP_403_FORBIDDEN,
                )
            user.role = UserRole.from_str(role_clean)

        if payload.first_name is not None or payload.last_name is not None:
            first = payload.first_name if payload.first_name is not None else user.name.partition(" ")[0]
            last = payload.last_name if payload.last_name is not None else user.name.partition(" ")[2]
            user.name = f"{first} {last}".strip()

        if payload.phone is not None:
            user.phone = payload.phone

        if payload.is_active is not None:
            user.is_active = payload.is_active
            if payload.is_active is False and user.account_status == "ACTIVE":
                user.account_status = "SUSPENDED"
            elif payload.is_active is True and user.account_status in ("SUSPENDED", "INACTIVE"):
                user.account_status = "ACTIVE"

        if payload.account_status is not None:
            user.account_status = payload.account_status
            if payload.account_status == "ACTIVE":
                user.is_active = True
                user.is_verified = True
            elif payload.account_status in ("SUSPENDED", "DEACTIVATED"):
                user.is_active = False

        # Sync Employee record
        emp_res = await self.session.execute(
            select(Employee).where(Employee.user_id == user.id, Employee.company_id == company_id)
        )
        emp = emp_res.scalars().first()
        if emp:
            if payload.first_name is not None:
                emp.first_name = payload.first_name.strip()
            if payload.last_name is not None:
                emp.last_name = payload.last_name.strip()
            if payload.department is not None:
                emp.department = payload.department
            if payload.designation is not None:
                emp.designation = payload.designation
            if payload.phone is not None:
                emp.phone = payload.phone
            if payload.role:
                emp.role = payload.role.strip().lower()
            if payload.is_active is False or user.is_active is False:
                emp.is_active = False
                emp.status = "DEACTIVATED"
                emp.deactivated_at = datetime.now(timezone.utc)
                emp.deactivated_by = admin_id
            elif payload.is_active is True and user.is_active is True:
                emp.is_active = True
                emp.status = "ACTIVE"
                emp.deactivated_at = None
                emp.deactivated_by = None
                emp.deactivation_reason = None

        # Sync Manager record if exists
        mgr_res = await self.session.execute(
            select(Manager).where(Manager.user_id == user.id, Manager.company_id == company_id)
        )
        mgr = mgr_res.scalars().first()
        if mgr:
            if payload.first_name is not None:
                mgr.first_name = payload.first_name.strip()
            if payload.last_name is not None:
                mgr.last_name = payload.last_name.strip()
            if payload.department is not None:
                mgr.department = payload.department
            if payload.designation is not None:
                mgr.designation = payload.designation
            if payload.phone is not None:
                mgr.phone = payload.phone
            if payload.is_active is False or user.is_active is False:
                mgr.is_active = False
                mgr.status = "DEACTIVATED"
                mgr.deactivated_at = datetime.now(timezone.utc)
                mgr.deactivated_by = admin_id
            elif payload.is_active is True and user.is_active is True:
                mgr.is_active = True
                mgr.status = "ACTIVE"
                mgr.deactivated_at = None
                mgr.deactivated_by = None
                mgr.deactivation_reason = None

        if user.is_active is False or user.account_status in ("SUSPENDED", "DEACTIVATED"):
            from app.models.refresh_token import RefreshToken
            from app.core.redis_client import redis_client
            await self.session.execute(
                update(RefreshToken).where(RefreshToken.user_id == user.id, RefreshToken.revoked == False).values(
                    revoked=True,
                    revoked_at=datetime.now(timezone.utc),
                    revoked_reason="HR_ADMIN_LOCK"
                )
            )
            await redis_client.revoke_user_tokens(user.id)

        # Log audit
        audit = AuditLog(
            id=uuid.uuid4(),
            user_id=admin_id,
            company_id=company_id,
            action="UPDATE_INTERNAL_USER",
            details=f"Updated user {user.email}",
        )
        self.session.add(audit)

        await self.session.commit()
        await self.session.refresh(user)

        role_val = user.role.value if hasattr(user.role, "value") else str(user.role)
        return HRAdminUserResponse(
            id=user.id,
            name=user.name,
            first_name=emp.first_name if emp else user.name.partition(" ")[0],
            last_name=emp.last_name if emp else user.name.partition(" ")[2],
            email=user.email,
            phone=user.phone,
            role=role_val,
            department=emp.department if emp else None,
            designation=emp.designation if emp else None,
            account_status=user.account_status,
            is_active=bool(user.is_active),
            is_verified=bool(user.is_verified),
            created_at=user.created_at,
            last_login_at=user.last_login_at,
            employee_id=emp.employee_id if emp else None,
        )

    async def deactivate_user(
        self,
        admin_id: uuid.UUID,
        company_id: uuid.UUID,
        target_user_id: uuid.UUID,
    ) -> None:
        """Deactivate an internal company user and all linked profiles. Blocks self-deactivation."""

        if admin_id == target_user_id:
            raise AppException(message="You cannot deactivate your own account.", status_code=status.HTTP_400_BAD_REQUEST)

        result = await self.session.execute(
            select(User).where(
                User.id == target_user_id,
                User.company_id == company_id,
                (User.is_deleted.is_(False) | User.is_deleted.is_(None)),
            )
        )
        user = result.scalars().first()
        if not user:
            raise AppException(message="User not found in your organization.", status_code=status.HTTP_404_NOT_FOUND)

        now_utc = datetime.now(timezone.utc)
        user.is_active = False
        user.account_status = UserAccountStatus.DEACTIVATED.value

        # Deactivate employee record
        emp_res = await self.session.execute(
            select(Employee).where(Employee.user_id == user.id, Employee.company_id == company_id)
        )
        emp = emp_res.scalars().first()
        if emp:
            emp.is_active = False
            emp.status = "DEACTIVATED"
            emp.deactivated_at = now_utc
            emp.deactivated_by = admin_id

        # Deactivate manager record
        mgr_res = await self.session.execute(
            select(Manager).where(Manager.user_id == user.id, Manager.company_id == company_id)
        )
        mgr = mgr_res.scalars().first()
        if mgr:
            mgr.is_active = False
            mgr.status = "DEACTIVATED"
            mgr.deactivated_at = now_utc
            mgr.deactivated_by = admin_id

        # Revoke tokens
        from app.models.refresh_token import RefreshToken
        await self.session.execute(
            update(RefreshToken).where(RefreshToken.user_id == user.id).values(revoked=True)
        )

        audit = AuditLog(
            id=uuid.uuid4(),
            user_id=admin_id,
            company_id=company_id,
            action="DEACTIVATE_INTERNAL_USER",
            details=f"Deactivated user {user.email}",
        )
        self.session.add(audit)

        await self.session.commit()

    async def resend_invitation(
        self,
        admin_id: uuid.UUID,
        company_id: uuid.UUID,
        target_user_id: uuid.UUID,
    ) -> None:
        """Regenerate activation token and resend onboarding invite email."""

        result = await self.session.execute(
            select(User).where(
                User.id == target_user_id,
                User.company_id == company_id,
                (User.is_deleted.is_(False) | User.is_deleted.is_(None)),
            )
        )
        user = result.scalars().first()
        if not user:
            raise AppException(message="User not found in your organization.", status_code=status.HTTP_404_NOT_FOUND)

        if user.is_verified and user.account_status == "ACTIVE":
            raise AppException(message="User is already active and verified.", status_code=status.HTTP_400_BAD_REQUEST)

        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.ACTIVATION_TOKEN_EXPIRE_HOURS)

        user.email_verification_token = token
        user.email_verification_expires_at = expires_at

        emp_res = await self.session.execute(
            select(Employee).where(Employee.user_id == user.id, Employee.company_id == company_id)
        )
        emp = emp_res.scalars().first()
        if emp:
            emp.activation_token = token
            emp.activation_token_expires_at = expires_at

        await self.session.commit()

        activation_url = f"{settings.FRONTEND_BASE_URL}/employee/activate?token={token}"
        from app.models.company import Company
        comp = await self.session.get(Company, company_id)
        comp_name = comp.name if comp else "OFC360"

        await self.email_service.send_employee_onboarding_invite(
            email=user.email,
            name=user.name,
            employee_id=emp.employee_id if emp else "EMP-001",
            department=emp.department if emp else "General",
            designation=emp.designation if emp else "Employee",
            joining_date=str(emp.joining_date if emp and emp.joining_date else date.today()),
            activation_url=activation_url,
            company_name=comp_name,
        )


async def get_hr_admin_service(
    session: AsyncSession = Depends(get_db_session),
    email_service: EmailService = Depends(get_email_service),
) -> HRAdminService:
    """Dependency provider for HRAdminService."""
    return HRAdminService(session=session, email_service=email_service)
