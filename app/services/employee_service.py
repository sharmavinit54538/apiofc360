"""Employee service layer: all business logic, transactions, and structured logging.

MULTI-TENANT: Every method that reads or writes employee rows MUST scope by company_id.
Never return data from another company — this is a hard security requirement.
"""

from __future__ import annotations

import logging
import math
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, status
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AppException, ConflictException, DatabaseException
from app.core.redis_client import redis_client
from app.core.security import hash_password
from app.db.database import get_db_session
from app.repositories.auth_repository import AuthRepository
from app.repositories.employee_repository import EmployeeRepository
from app.schemas.employee import (
    ActivateEmployeeRequest,
    ApproveRejectRequest,
    EmployeeCreate,
    EmployeeListResponse,
    EmployeeOnboardingStatusResponse,
    EmployeeOnboardingStepResponse,
    EmployeeResponse,
    EmployeeUpdate,
    EmployeeListItem,
)
from app.services.email_service import EmailService, get_email_service
from app.models.audit_log import AuditLog
from app.utils.employee import (
    generate_activation_token,
    generate_company_email,
    generate_employee_id,
    generate_temp_password,
)

logger = logging.getLogger(__name__)

_VALID_SEND_INVITATION_STATUSES = {"CREATED", "INVITATION_SENT"}
_VALID_APPROVE_STATUSES = {"ONBOARDING_PENDING", "DOCUMENT_PENDING", "UNDER_VERIFICATION", "PASSWORD_CREATED"}


def _mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    masked = local[:1] + "***" if len(local) > 1 else "***"
    return masked + "@" + domain


def mask_token(token: str | None) -> str:
    """Mask token for safe diagnostic logging (e.g. FjUB...SYUQ)."""
    if not token:
        return "N/A"
    clean = token.strip()
    if len(clean) <= 8:
        return "***"
    return f"{clean[:4]}...{clean[-4:]}"


async def validate_employee_invitation_token(
    session: AsyncSession,
    token: str,
) -> tuple[Any, dict[str, Any]]:
    """Canonical token validation service for employee invitations.

    Performs:
    1. Safe surrounding whitespace normalization and non-empty check.
    2. Primary lookup on Employee.activation_token (with is_deleted=False).
    3. Fallback lookup on linked User.email_verification_token.
    4. Deactivation / deletion check.
    5. Already consumed / active status check.
    6. Valid status check (INVITED, INVITATION_SENT, CREATED, PENDING, PROBATION, ONBOARDING_PENDING).
    7. Deterministic timezone-aware UTC expiry check.
    8. Safe company name resolution.
    9. Sanitized safe payload generation (no hashes, tokens, or JWT secrets).
    """
    clean_token = token.strip() if token else ""
    token_masked = mask_token(clean_token)
    logger.info("validate_employee_invitation_token: validating | token=%s", token_masked)

    if not clean_token:
        logger.warning("validate_employee_invitation_token: rejected empty token")
        raise AppException(
            message="Invalid invitation token.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    import inspect
    from sqlalchemy import select
    from app.models.employee import Employee
    from app.models.user import User
    from app.models.company import Company

    # 1. Primary lookup by Employee.activation_token
    emp_result = await session.execute(
        select(Employee).where(
            Employee.activation_token == clean_token,
            Employee.is_deleted.is_(False),
        )
    )
    employee = None
    if hasattr(emp_result, "scalar_one_or_none"):
        res = emp_result.scalar_one_or_none()
        employee = await res if inspect.isawaitable(res) else res
    elif hasattr(emp_result, "scalars"):
        scalars = emp_result.scalars()
        res = scalars.first() if hasattr(scalars, "first") else None
        employee = await res if inspect.isawaitable(res) else res
    elif emp_result is not None and not inspect.isawaitable(emp_result):
        employee = emp_result

    # 2. Secondary fallback lookup via linked User.email_verification_token
    if not employee:
        user_emp_res = await session.execute(
            select(Employee).join(User, Employee.user_id == User.id).where(
                User.email_verification_token == clean_token,
                Employee.is_deleted.is_(False),
            )
        )
        if hasattr(user_emp_res, "scalar_one_or_none"):
            res = user_emp_res.scalar_one_or_none()
            employee = await res if inspect.isawaitable(res) else res
        elif hasattr(user_emp_res, "scalars"):
            scalars = user_emp_res.scalars()
            res = scalars.first() if hasattr(scalars, "first") else None
            employee = await res if inspect.isawaitable(res) else res
        elif user_emp_res is not None and not inspect.isawaitable(user_emp_res):
            employee = user_emp_res

    if not employee or inspect.isawaitable(employee):
        logger.warning("validate_employee_invitation_token: token not found | token=%s", token_masked)
        raise AppException(
            message="Invalid invitation token.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    # 3. Check deactivation status
    if getattr(employee, "is_deactivated", False):
        logger.warning("validate_employee_invitation_token: employee is deactivated | employee_id=%s", employee.id)
        raise AppException(
            message="Invitation is no longer valid. Request a new invitation.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    # 4. Check if already activated / used
    if employee.status == "ACTIVE" or (not employee.activation_token and employee.user_id):
        logger.warning("validate_employee_invitation_token: invitation already consumed | employee_id=%s", employee.id)
        raise AppException(
            message="Invitation already used. Please log in or contact your administrator.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    # 5. Check allowed pending activation statuses
    valid_statuses = {"INVITED", "INVITATION_SENT", "CREATED", "PENDING", "PROBATION", "ONBOARDING_PENDING"}
    if employee.status not in valid_statuses:
        logger.warning(
            "validate_employee_invitation_token: invalid status for activation | employee_id=%s | status=%s",
            employee.id, employee.status,
        )
        raise AppException(
            message="Invitation is no longer valid. Request a new invitation.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    # 6. Check expiration (timezone-aware UTC comparison)
    now = datetime.now(timezone.utc)
    expires_at = employee.activation_token_expires_at
    if expires_at:
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        remaining_seconds = (expires_at - now).total_seconds()
        logger.info(
            "validate_employee_invitation_token: expiry check | employee_id=%s | now=%s | expires_at=%s | remaining_sec=%.2f",
            employee.id, now.isoformat(), expires_at.isoformat(), remaining_seconds,
        )
        if remaining_seconds <= 0:
            logger.warning(
                "validate_employee_invitation_token: token expired | employee_id=%s | expires_at=%s",
                employee.id, expires_at.isoformat(),
            )
            raise AppException(
                message="Invitation expired. Request new invitation.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
    else:
        logger.info("validate_employee_invitation_token: no expiration timestamp on record | employee_id=%s", employee.id)

    # 7. Safe company name resolution
    company_name = "OFC360"
    if employee.company_id:
        comp_res = await session.execute(select(Company.name).where(Company.id == employee.company_id))
        c_name = None
        if hasattr(comp_res, "scalar_one_or_none"):
            c_val = comp_res.scalar_one_or_none()
            c_name = await c_val if inspect.isawaitable(c_val) else c_val
        elif hasattr(comp_res, "scalars"):
            scalars = comp_res.scalars()
            c_val = scalars.first() if hasattr(scalars, "first") else None
            c_name = await c_val if inspect.isawaitable(c_val) else c_val
        if c_name:
            company_name = c_name

    logger.info("validate_employee_invitation_token: success | employee_id=%s", employee.id)

    data = {
        "id": str(employee.id),
        "employee_id": str(employee.id),
        "employee_uuid": str(employee.id),
        "employee_code": employee.employee_id,
        "first_name": employee.first_name,
        "last_name": employee.last_name,
        "name": f"{employee.first_name} {employee.last_name}".strip(),
        "full_name": f"{employee.first_name} {employee.last_name}".strip(),
        "personal_email": employee.personal_email,
        "company_email": employee.company_email,
        "email": employee.personal_email or employee.company_email,
        "phone": employee.phone,
        "department": employee.department,
        "designation": employee.designation,
        "company_id": str(employee.company_id) if employee.company_id else None,
        "company_name": company_name,
        "joining_date": employee.joining_date.isoformat() if employee.joining_date else None,
        "valid": True,
    }
    return employee, data


class EmployeeService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        employee_repository: EmployeeRepository,
        auth_repository: AuthRepository,
        email_service: EmailService,
    ) -> None:
        self.session = session
        self.repo = employee_repository
        self.auth_repo = auth_repository
        self.email_service = email_service

    # ------------------------------------------------------------------
    # Internal helpers: always company-scoped
    # ------------------------------------------------------------------

    async def _get_employee_in_company(
        self,
        employee_uuid: uuid.UUID,
        company_id: uuid.UUID,
        *,
        include_deleted: bool = False,
    ):
        """Fetch a single employee, enforcing company scope. Returns None if not found or wrong company."""
        employee = await self.repo.get_by_id_raw(employee_uuid)
        if not employee:
            return None
        if employee.company_id != company_id:
            # Never leak that the employee exists in another company — return None (→ 404)
            return None
        if not include_deleted and employee.is_deleted:
            return None
        return employee

    async def _require_employee_in_company(
        self,
        employee_uuid: uuid.UUID,
        company_id: uuid.UUID,
        *,
        include_deleted: bool = False,
    ):
        """Like _get_employee_in_company but raises 404 AppException on miss."""
        employee = await self._get_employee_in_company(
            employee_uuid, company_id, include_deleted=include_deleted
        )
        if not employee:
            raise AppException(
                message="Employee not found.",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return employee

    async def _resolve_reporting_manager(self, manager_id: uuid.UUID, company_id: uuid.UUID) -> bool:
        """Verify if a reporting manager exists in the employees table.
        If the ID belongs to a Manager in the managers table or User table (matching company_id),
        resolves or creates a corresponding Employee profile to satisfy database constraints.
        Returns True if resolved successfully, False otherwise.
        """
        from sqlalchemy import select
        from app.models.employee import Employee
        from app.models.manager import Manager
        from app.models.user import User
        from datetime import date

        # 1. Check if manager_id is an Employee ID
        manager = await self.repo.get_by_id_raw(manager_id)
        if manager and manager.company_id == company_id:
            return True

        # 2. Check if manager_id is an Employee user_id
        res_emp_user = await self.session.execute(
            select(Employee).where(Employee.user_id == manager_id, Employee.company_id == company_id)
        )
        emp_by_user = res_emp_user.scalar_one_or_none()
        if emp_by_user:
            return True

        # 3. Check if manager_id is a Manager ID or Manager user_id
        res_mgr = await self.session.execute(
            select(Manager).where((Manager.id == manager_id) | (Manager.user_id == manager_id))
        )
        mgr = res_mgr.scalar_one_or_none()
        if mgr and mgr.company_id == company_id:
            existing_emp = await self.repo.get_by_id_raw(mgr.id)
            if existing_emp:
                return True

            employee_id = mgr.manager_id
            new_emp = Employee(
                id=mgr.id,
                user_id=mgr.user_id,
                company_id=company_id,
                employee_id=employee_id,
                first_name=mgr.first_name,
                last_name=mgr.last_name,
                personal_email=mgr.personal_email,
                company_email=mgr.company_email,
                phone=mgr.phone,
                department=mgr.department,
                designation=mgr.designation,
                joining_date=date.today(),
                employment_type="FULL_TIME",
                employment_status="CONFIRMED",
                role="manager",
                status="ACTIVE"
            )
            self.session.add(new_emp)
            await self.session.flush()
            return True

        # 4. Check if manager_id is a User ID matching company_id
        res_usr = await self.session.execute(
            select(User).where(User.id == manager_id, User.company_id == company_id)
        )
        usr = res_usr.scalar_one_or_none()
        if usr:
            existing_user_emp = await self.repo.get_by_id_raw(usr.id)
            if existing_user_emp:
                return True

            names = usr.name.split(" ", 1)
            first_name = names[0]
            last_name = names[1] if len(names) > 1 else ""
            new_emp = Employee(
                id=usr.id,
                user_id=usr.id,
                company_id=company_id,
                employee_id=f"EMP-MGR-{uuid.uuid4().hex[:6].upper()}",
                first_name=first_name,
                last_name=last_name or "Manager",
                personal_email=usr.email,
                company_email=usr.email,
                phone=usr.phone or "0000000000",
                department="Management",
                designation="Reporting Manager",
                joining_date=date.today(),
                employment_type="FULL_TIME",
                employment_status="CONFIRMED",
                role=usr.role.value if hasattr(usr.role, "value") else str(usr.role),
                status="ACTIVE"
            )
            self.session.add(new_emp)
            await self.session.flush()
            return True

        return False

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    async def create_employee(
        self, admin_id: uuid.UUID, company_id: uuid.UUID, payload: EmployeeCreate
    ) -> EmployeeResponse:
        logger.info(
            "create_employee | admin_id=%s | company_id=%s | email=%s",
            admin_id, company_id, _mask_email(str(payload.personal_email)),
        )
        try:
            from sqlalchemy import select
            from app.models.company import Company

            result = await self.session.execute(
                select(Company).where(Company.id == company_id)
            )
            company_obj = result.scalar_one_or_none()
            company_name = company_obj.name if company_obj else "Our Company"

            # Check: personal_email unique globally
            personal_email = str(payload.personal_email).strip().lower()
            if personal_email == "superadmin@ofc360.com":
                raise ConflictException(
                    message="The platform Super Admin email cannot be used for company employee records.",
                    field="personal_email",
                    errors=[{"field": "personal_email", "message": "Super Admin email reserved."}],
                )

            if payload.role and payload.role.strip().lower() == "super_admin":
                raise AppException(
                    message="Company employees cannot be assigned the Super Admin role.",
                    status_code=status.HTTP_403_FORBIDDEN,
                    errors=[{"field": "role", "message": "Super Admin role cannot be assigned."}],
                )

            if await self.repo.get_by_personal_email(personal_email):
                raise ConflictException(
                    message="Email already exists.",
                    field="personal_email",
                    errors=[{"field": "personal_email", "message": "Email already in use."}],
                )

            # Check: company_email unique within this company (if provided)
            company_email = payload.company_email.strip().lower() if payload.company_email else personal_email
            if payload.company_email and await self.repo.get_by_company_email_in_company(company_email, company_id):
                raise ConflictException(
                    message="Company email already exists.",
                    field="company_email",
                    errors=[{"field": "company_email", "message": "Company email already in use."}],
                )

            # Check: employee_id unique globally
            if payload.employee_id:
                if await self.repo.get_by_employee_id(payload.employee_id):
                    raise ConflictException(
                        message="Employee ID already exists.",
                        field="employee_id",
                        errors=[{"field": "employee_id", "message": "Employee ID already in use."}],
                    )
                employee_id = payload.employee_id
            else:
                employee_id = await generate_employee_id(self.session)


            if payload.reporting_manager_id:
                if not await self._resolve_reporting_manager(payload.reporting_manager_id, company_id):
                    raise AppException(
                        message="Reporting manager not found.",
                        status_code=status.HTTP_400_BAD_REQUEST,
                    )

            probation_end_date = None
            if payload.probation_period_months and payload.probation_period_months > 0:
                from datetime import date
                jd = payload.joining_date
                month = jd.month + payload.probation_period_months
                year = jd.year + (month - 1) // 12
                month = (month - 1) % 12 + 1
                probation_end_date = date(year, month, jd.day)

            import secrets
            token = secrets.token_urlsafe(32)
            token_expires = datetime.now(timezone.utc) + timedelta(
                hours=settings.ACTIVATION_TOKEN_EXPIRE_HOURS
            )

            emp_kwargs = {
                "user_id": None,
                "company_id": company_id,
                "employee_id": employee_id,
                "first_name": payload.first_name.strip(),
                "last_name": payload.last_name.strip(),
                "profile_photo_url": payload.profile_photo_url,
                "gender": payload.gender,
                "date_of_birth": payload.date_of_birth,
                "personal_email": personal_email,
                "company_email": company_email,
                "phone": payload.phone,
                "alternate_phone": payload.alternate_phone,
                "blood_group": payload.blood_group,
                "marital_status": payload.marital_status,
                "department": payload.department,
                "designation": payload.designation,
                "team": payload.team,
                "reporting_manager_id": payload.reporting_manager_id,
                "manager_id": payload.reporting_manager_id,
                "branch": payload.branch,
                "work_location": payload.work_location,
                "employment_type": payload.employment_type,
                "employment_status": "PROBATION",
                "joining_date": payload.joining_date,
                "probation_end_date": probation_end_date,
                "shift": payload.shift,
                "employee_capacity": getattr(payload, "employee_capacity", 100) or 100,
                "cost_center_id": getattr(payload, "cost_center_id", None),
                "ctc": payload.ctc,
                "basic_salary": payload.basic_salary,
                "hra": payload.hra,
                "bonus": payload.bonus,
                "pf": payload.pf,
                "esi": payload.esi,
                "professional_tax": payload.professional_tax,
                "role": payload.role,
                "leave_group": payload.leave_group,
                "role_metadata": payload.role_metadata or {},
                "verification_status": "PENDING_ADMIN_CREATED",
                "status": "INVITED",
                "activation_token": token,
                "activation_token_expires_at": token_expires,
                "invited_at": datetime.now(timezone.utc),
                "invited_by": admin_id,
                "created_by": admin_id,
            }
            employee = await self.repo.create_employee(**emp_kwargs)
            for addr in payload.addresses:
                data = addr.model_dump(exclude={"address_type"})
                await self.repo.upsert_address(employee.id, addr.address_type, data)
            for doc in payload.documents:
                await self.repo.create_document(employee.id, doc.model_dump())
            for edu in payload.education:
                await self.repo.create_education(employee.id, edu.model_dump())
            for exp in payload.experience:
                await self.repo.create_experience(employee.id, exp.model_dump())
            for skill in payload.skills:
                await self.repo.create_skill(employee.id, skill.model_dump())
            for ec in payload.emergency_contacts:
                await self.repo.create_emergency_contact(employee.id, ec.model_dump())
            for ba in payload.bank_accounts:
                await self.repo.create_bank_account(employee.id, ba.model_dump())
            await self.repo.create_onboarding_steps(employee.id)
            await self.session.commit()

            activation_url = f"{settings.FRONTEND_BASE_URL}/employee/activate?token={token}"
            logger.info(
                "create_employee: token generated | employee_id=%s | expires=%s | url=%s",
                employee_id, token_expires.isoformat(), activation_url,
            )

            email_sent = False
            try:
                await self.email_service.send_employee_onboarding_invite(
                    email=personal_email,
                    name=payload.first_name,
                    employee_id=employee_id,
                    department=payload.department,
                    designation=payload.designation,
                    joining_date=str(payload.joining_date),
                    activation_url=activation_url,
                    company_name=company_name,
                )
                email_sent = True
                logger.info(
                    "create_employee: invitation email sent | employee_id=%s | email=%s",
                    employee_id, _mask_email(personal_email),
                )
            except Exception as mail_exc:
                logger.error(
                    "create_employee: invitation email FAILED | employee_id=%s | email=%s | error=%s",
                    employee_id, _mask_email(personal_email), str(mail_exc),
                    exc_info=True,
                )

            logger.info(
                "create_employee: success | employee_id=%s | email_sent=%s",
                employee_id, email_sent,
            )
            try:
                full_employee = await self.repo.get_by_id(employee.id)
                if full_employee is not None:
                    result_obj = EmployeeResponse.model_validate(full_employee)
                else:
                    result_obj = EmployeeResponse.model_validate(employee)
            except SQLAlchemyError as load_exc:
                logger.warning(
                    "create_employee: post-commit eager-load failed (%s); building response from committed employee record",
                    load_exc,
                    exc_info=True,
                )
                result_obj = EmployeeResponse.model_validate(employee)

            result_obj.email_sent = email_sent
            result_obj.__dict__["_email_sent"] = email_sent
            return result_obj
        except (AppException, ConflictException):
            await self.session.rollback()
            raise
        except IntegrityError as exc:
            await self.session.rollback()
            err_detail = str(exc).lower()
            if "ix_employees_employee_id" in err_detail or "key (employee_id)" in err_detail or "employees.employee_id" in err_detail:
                # employee_id collision — retry with a fresh ID
                logger.warning("create_employee: employee_id collision, retrying with new ID")
                return await self.create_employee(admin_id, company_id, payload)
            logger.exception("create_employee: integrity error", exc_info=exc)
            raise ConflictException(
                message="Email already exists.",
                field="personal_email",
                errors=[{"field": "personal_email", "message": "Email already in use."}],
            ) from exc
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("create_employee: db error", exc_info=exc)
            raise DatabaseException() from exc

    # ------------------------------------------------------------------
    # Synchronization helper
    # ------------------------------------------------------------------

    async def _sync_managers_to_employees(self, company_id: uuid.UUID) -> None:
        """Ensure all managers in managers table have a synchronized workforce Employee record."""
        try:
            from sqlalchemy import select
            from app.models.manager import Manager
            from app.models.employee import Employee

            mgr_stmt = select(Manager).where(
                Manager.company_id == company_id,
                Manager.is_deleted.is_(False),
            )
            mgr_res = await self.session.execute(mgr_stmt)
            managers = mgr_res.scalars().all()

            for mgr in managers:
                emp_res = await self.session.execute(
                    select(Employee).where(
                        (Employee.id == mgr.id) | (Employee.personal_email == mgr.personal_email)
                    )
                )
                emp = emp_res.scalar_one_or_none()
                if not emp:
                    new_emp = Employee(
                        id=mgr.id,
                        user_id=mgr.user_id,
                        company_id=company_id,
                        employee_id=mgr.manager_id,
                        first_name=mgr.first_name,
                        last_name=mgr.last_name,
                        profile_photo_url=mgr.profile_photo_url,
                        gender=mgr.gender,
                        date_of_birth=mgr.date_of_birth,
                        personal_email=mgr.personal_email,
                        company_email=mgr.company_email,
                        phone=mgr.phone,
                        alternate_phone=mgr.alternate_phone,
                        blood_group=mgr.blood_group,
                        marital_status=mgr.marital_status,
                        department=mgr.department,
                        designation=mgr.designation,
                        branch=mgr.branch,
                        work_location=mgr.work_location,
                        joining_date=mgr.joining_date,
                        employment_type=mgr.employment_type or "FULL_TIME",
                        employment_status=mgr.employment_status or "CONFIRMED",
                        shift=mgr.shift,
                        probation_period_months=mgr.probation_period_months,
                        ctc=mgr.ctc,
                        basic_salary=mgr.basic_salary,
                        hra=mgr.hra,
                        bonus=mgr.bonus,
                        pf=mgr.pf,
                        esi=mgr.esi,
                        professional_tax=mgr.professional_tax,
                        role="manager",
                        leave_group=mgr.leave_group,
                        status=mgr.status or "ACTIVE",
                        activation_token=mgr.activation_token,
                        activation_token_expires_at=mgr.activation_token_expires_at,
                        invited_at=mgr.invited_at,
                        invited_by=mgr.invited_by,
                        created_by=mgr.created_by,
                        is_deleted=mgr.is_deleted,
                        reporting_manager_id=mgr.reporting_to,
                        manager_id=mgr.reporting_to,
                    )
                    self.session.add(new_emp)
                    await self.session.flush()
                else:
                    updated = False
                    if emp.user_id != mgr.user_id and mgr.user_id is not None:
                        emp.user_id = mgr.user_id
                        updated = True
                    if emp.status != mgr.status and mgr.status is not None:
                        emp.status = mgr.status
                        updated = True
                    if not emp.role or emp.role.lower() == "employee":
                        emp.role = "manager"
                        updated = True
                    if updated:
                        await self.session.flush()
            await self.session.commit()
        except Exception as sync_exc:
            logger.warning("_sync_managers_to_employees warning: %s", str(sync_exc))
            await self.session.rollback()

    # ------------------------------------------------------------------
    # List
    # ------------------------------------------------------------------

    async def list_employees(
        self,
        company_id: uuid.UUID,
        department: str | None,
        status_filter: str | None,
        employment_type: str | None,
        search: str | None,
        page: int,
        limit: int,
        designation: str | None = None,
        shift: str | None = None,
        role: str | None = None,
        sort: str | None = None,
        order: str | None = "asc",
    ) -> EmployeeListResponse:
        try:
            await self._sync_managers_to_employees(company_id)
            offset = (page - 1) * limit
            employees = await self.repo.list_employees(
                company_id=company_id,
                department=department,
                status=status_filter,
                employment_type=employment_type,
                search=search,
                limit=limit,
                offset=offset,
                designation=designation,
                shift=shift,
                role=role,
                sort=sort,
                order=order,
            )
            total = await self.repo.count_employees(
                company_id=company_id,
                department=department,
                status=status_filter,
                employment_type=employment_type,
                search=search,
                designation=designation,
                shift=shift,
                role=role,
            )
            items = [EmployeeListItem.model_validate(e) for e in employees]
            pages = math.ceil(total / limit) if limit > 0 else 0
            has_next = page < pages
            has_previous = page > 1
            return EmployeeListResponse(
                items=items,
                total=total,
                page=page,
                limit=limit,
                pages=pages,
                total_pages=pages,
                has_next=has_next,
                has_previous=has_previous,
            )
        except SQLAlchemyError as exc:
            logger.exception("list_employees: db error", exc_info=exc)
            raise DatabaseException() from exc

    # ------------------------------------------------------------------
    # Get single
    # ------------------------------------------------------------------

    async def get_employee(
        self,
        employee_uuid: uuid.UUID,
        company_id: uuid.UUID | None = None,
    ) -> EmployeeResponse:
        """Get a single employee, optionally scoped to a company."""
        try:
            employee = await self.repo.get_by_id(employee_uuid)
            if not employee and company_id:
                await self._sync_managers_to_employees(company_id)
                employee = await self.repo.get_by_id(employee_uuid)
            if not employee:
                raise AppException(message="Employee not found.", status_code=status.HTTP_404_NOT_FOUND)
            # Enforce company scope when company_id is provided
            if company_id is not None and employee.company_id != company_id:
                raise AppException(message="Employee not found.", status_code=status.HTTP_404_NOT_FOUND)
            return EmployeeResponse.model_validate(employee)
        except AppException:
            raise
        except SQLAlchemyError as exc:
            logger.exception("get_employee: db error", exc_info=exc)
            try:
                raw_employee = await self.repo.get_by_id_raw(employee_uuid, company_id=company_id)
                if raw_employee:
                    return EmployeeResponse.model_validate(raw_employee)
            except Exception:
                pass
            raise DatabaseException() from exc

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    async def update_employee(
        self,
        admin_id: uuid.UUID,
        company_id: uuid.UUID,
        employee_uuid: uuid.UUID,
        payload: EmployeeUpdate,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> EmployeeResponse:
        update_data = payload.model_dump(exclude_unset=True)
        logger.info(
            "update_employee start | admin_id=%s | company_id=%s | employee_id=%s | update_fields=%s",
            admin_id, company_id, employee_uuid, list(update_data.keys()),
        )
        try:
            employee = await self._require_employee_in_company(employee_uuid, company_id)

            if not update_data:
                logger.info("update_employee: no fields provided in PATCH payload, returning current record | employee_id=%s", employee_uuid)
                full_employee = await self.repo.get_by_id(employee_uuid)
                return EmployeeResponse.model_validate(full_employee)

            # Prevent overwriting immutable fields: id, company_id, created_at, user_id
            for immutable_field in ["id", "company_id", "created_at", "user_id"]:
                if immutable_field in update_data:
                    del update_data[immutable_field]

            if "role" in update_data and update_data["role"]:
                if str(update_data["role"]).strip().lower() == "super_admin":
                    raise AppException(
                        message="Company employees cannot be assigned the Super Admin role.",
                        status_code=status.HTTP_403_FORBIDDEN,
                        errors=[{"field": "role", "message": "Super Admin role cannot be assigned."}],
                    )

            if "reporting_manager_id" in update_data:
                rm_id = update_data["reporting_manager_id"]
                if rm_id is not None:
                    if rm_id == employee_uuid:
                        raise AppException(
                            message="An employee cannot be their own reporting manager.",
                            status_code=status.HTTP_400_BAD_REQUEST,
                        )
                    if not await self._resolve_reporting_manager(rm_id, company_id):
                        raise AppException(
                            message="Reporting manager not found.",
                            status_code=status.HTTP_400_BAD_REQUEST,
                        )
                    update_data["manager_id"] = rm_id
                else:
                    update_data["manager_id"] = None

            # Verify uniqueness constraints before updating
            if "personal_email" in update_data and update_data["personal_email"] is not None:
                personal_email = str(update_data["personal_email"]).strip().lower()
                if personal_email == "superadmin@ofc360.com":
                    raise ConflictException(
                        message="The platform Super Admin email cannot be used for company employee records.",
                        field="personal_email",
                        errors=[{"field": "personal_email", "message": "Super Admin email reserved."}],
                    )
                if personal_email != (employee.personal_email or "").strip().lower():
                    existing = await self.repo.get_by_personal_email(personal_email)
                    if existing and existing.id != employee_uuid:
                        raise ConflictException(
                            message="Personal email already exists for another employee.",
                            field="personal_email",
                            errors=[{"field": "personal_email", "message": "Personal email already in use."}],
                        )

            if "company_email" in update_data and update_data["company_email"] is not None:
                company_email = str(update_data["company_email"]).strip().lower()
                if company_email != (employee.company_email or "").strip().lower():
                    existing = await self.repo.get_by_company_email_in_company(company_email, company_id)
                    if existing and existing.id != employee_uuid:
                        raise ConflictException(
                            message="Company email already exists for another employee.",
                            field="company_email",
                            errors=[{"field": "company_email", "message": "Company email already in use."}],
                        )

            if "phone" in update_data and update_data["phone"] is not None:
                phone_val = str(update_data["phone"]).strip()
                if phone_val and phone_val != (employee.phone or "").strip():
                    existing = await self.repo.get_by_phone_in_company(phone_val, company_id)
                    if existing and existing.id != employee_uuid:
                        raise ConflictException(
                            message="Phone number already exists for another employee.",
                            field="phone",
                            errors=[{"field": "phone", "message": "Phone number already in use."}],
                        )

            if "employee_id" in update_data and update_data["employee_id"] is not None:
                emp_id = str(update_data["employee_id"]).strip()
                if emp_id != (employee.employee_id or "").strip():
                    existing = await self.repo.get_by_employee_id(emp_id)
                    if existing and existing.id != employee_uuid:
                        raise ConflictException(
                            message="Employee ID already exists for another employee.",
                            field="employee_id",
                            errors=[{"field": "employee_id", "message": "Employee ID already in use."}],
                        )

            # Salary cross-field validation with merged DB state
            salary_keys = ["ctc", "basic_salary", "hra", "bonus", "pf", "esi", "professional_tax"]
            has_salary_update = any(k in update_data for k in salary_keys)

            # Build merged salary state (incoming values override existing DB values; omitted fields preserve existing DB values)
            merged_ctc = update_data.get("ctc") if ("ctc" in update_data and update_data["ctc"] is not None) else employee.ctc
            merged_basic = update_data.get("basic_salary") if ("basic_salary" in update_data and update_data["basic_salary"] is not None) else employee.basic_salary
            merged_hra = update_data.get("hra") if ("hra" in update_data and update_data["hra"] is not None) else employee.hra
            merged_bonus = update_data.get("bonus") if ("bonus" in update_data and update_data["bonus"] is not None) else employee.bonus
            merged_pf = update_data.get("pf") if ("pf" in update_data and update_data["pf"] is not None) else employee.pf
            merged_esi = update_data.get("esi") if ("esi" in update_data and update_data["esi"] is not None) else employee.esi
            merged_pt = update_data.get("professional_tax") if ("professional_tax" in update_data and update_data["professional_tax"] is not None) else employee.professional_tax

            if has_salary_update:
                from decimal import Decimal
                if merged_ctc is not None and Decimal(str(merged_ctc)) > 0:
                    ctc_dec = Decimal(str(merged_ctc))
                    components = [
                        ("basic_salary", merged_basic),
                        ("hra", merged_hra),
                        ("bonus", merged_bonus),
                        ("pf", merged_pf),
                        ("esi", merged_esi),
                        ("professional_tax", merged_pt),
                    ]
                    for comp_name, comp_val in components:
                        if comp_val is not None:
                            val_dec = Decimal(str(comp_val))
                            if val_dec > ctc_dec:
                                raise AppException(
                                    message=f"{comp_name} ({comp_val}) cannot exceed ctc ({merged_ctc})",
                                    status_code=status.HTTP_400_BAD_REQUEST,
                                    errors=[{"field": comp_name, "message": f"{comp_name} cannot exceed ctc."}],
                                )

                    b_dec = Decimal(str(merged_basic)) if merged_basic is not None else Decimal("0")
                    h_dec = Decimal(str(merged_hra)) if merged_hra is not None else Decimal("0")
                    bon_dec = Decimal(str(merged_bonus)) if merged_bonus is not None else Decimal("0")

                    if merged_basic is not None or merged_hra is not None or merged_bonus is not None:
                        combined = b_dec + h_dec + bon_dec
                        max_allowed = ctc_dec * Decimal("1.01")
                        if combined > max_allowed:
                            raise AppException(
                                message="basic_salary + hra + bonus exceeds ctc — check the compensation breakup",
                                status_code=status.HTTP_400_BAD_REQUEST,
                                errors=[{"field": "ctc", "message": "basic_salary + hra + bonus exceeds ctc."}],
                            )
                else:
                    components = [
                        ("basic_salary", merged_basic),
                        ("hra", merged_hra),
                        ("bonus", merged_bonus),
                        ("pf", merged_pf),
                        ("esi", merged_esi),
                        ("professional_tax", merged_pt),
                    ]
                    for comp_name, comp_val in components:
                        if comp_val is not None and Decimal(str(comp_val)) > 0:
                            raise AppException(
                                message=f"{comp_name} ({comp_val}) cannot exceed ctc (0)",
                                status_code=status.HTTP_400_BAD_REQUEST,
                                errors=[{"field": comp_name, "message": f"{comp_name} cannot be set without ctc."}],
                            )

            # Merge role_metadata (don't replace, merge keys)
            if "role_metadata" in update_data and update_data["role_metadata"] is not None:
                existing_metadata = employee.role_metadata or {}
                incoming_metadata = update_data["role_metadata"] or {}
                merged = {**existing_metadata, **incoming_metadata}
                update_data["role_metadata"] = merged

            # Extract nested relation lists if provided
            addresses = update_data.pop("addresses", None)
            documents = update_data.pop("documents", None)
            education = update_data.pop("education", None)
            experience = update_data.pop("experience", None)
            skills = update_data.pop("skills", None)
            emergency_contacts = update_data.pop("emergency_contacts", None)
            bank_accounts = update_data.pop("bank_accounts", None)

            # Remove non-table column alias keys
            for alias_key in ("cost_id", "costID", "costCenterId", "cost_code", "costCode", "costId",
                              "activationToken", "invite_token", "inviteToken", "token",
                              "activation_url", "activationUrl", "invite_link", "inviteLink",
                              "invite_url", "inviteUrl", "onboarding_url", "onboardingUrl",
                              "onboarding_link", "onboardingLink"):
                update_data.pop(alias_key, None)

            # Compare and track changed fields
            changed_fields = []
            for field, val in update_data.items():
                old_val = getattr(employee, field, None)
                if old_val != val:
                    changed_fields.append(field)

            logger.info("update_employee: executing db update | employee_id=%s | changed_fields=%s", employee_uuid, changed_fields)
            if update_data:
                await self.repo.update_employee(employee_uuid, **update_data)

            # Synchronize User active state if employee active status or lifecycle changed
            if employee.user_id:
                from sqlalchemy import update as sa_update
                from app.models.user import User
                new_is_active = update_data.get("is_active", employee.is_active)
                new_status = (update_data.get("status") or employee.status or "").upper()
                new_emp_status = (update_data.get("employment_status") or employee.employment_status or "").upper()

                if (
                    new_is_active is False
                    or new_status in ("DISABLED", "INACTIVE", "DEACTIVATED", "ARCHIVED", "TERMINATED", "EXITED", "DELETED")
                    or new_emp_status in ("EXITED", "TERMINATED")
                ):
                    await self.session.execute(
                        sa_update(User).where(User.id == employee.user_id).values(
                            is_active=False,
                        )
                    )
                    await self.auth_repo.revoke_all_user_refresh_tokens(employee.user_id)
                    await redis_client.revoke_user_tokens(employee.user_id)
                elif new_is_active is True and new_status == "ACTIVE":
                    await self.session.execute(
                        sa_update(User).where(User.id == employee.user_id).values(
                            is_active=True,
                        )
                    )

            from sqlalchemy import delete
            
            # Update Addresses
            if addresses is not None:
                from app.models.employee_address import EmployeeAddress
                await self.session.execute(
                    delete(EmployeeAddress).where(EmployeeAddress.employee_id == employee_uuid)
                )
                for addr in addresses:
                    data = {k: v for k, v in addr.items() if k != "address_type"}
                    await self.repo.upsert_address(employee_uuid, addr.get("address_type"), data)
                changed_fields.append("addresses")

            # Update Documents
            if documents is not None:
                from app.models.employee_document import EmployeeDocument
                await self.session.execute(
                    delete(EmployeeDocument).where(EmployeeDocument.employee_id == employee_uuid)
                )
                for doc in documents:
                    await self.repo.create_document(employee_uuid, doc)
                changed_fields.append("documents")

            # Update Education
            if education is not None:
                from app.models.employee_education import EmployeeEducation
                await self.session.execute(
                    delete(EmployeeEducation).where(EmployeeEducation.employee_id == employee_uuid)
                )
                for edu in education:
                    await self.repo.create_education(employee_uuid, edu)
                changed_fields.append("education")

            # Update Experience
            if experience is not None:
                from app.models.employee_experience import EmployeeExperience
                await self.session.execute(
                    delete(EmployeeExperience).where(EmployeeExperience.employee_id == employee_uuid)
                )
                for exp in experience:
                    await self.repo.create_experience(employee_uuid, exp)
                changed_fields.append("experience")

            # Update Skills
            if skills is not None:
                from app.models.employee_skill import EmployeeSkill
                await self.session.execute(
                    delete(EmployeeSkill).where(EmployeeSkill.employee_id == employee_uuid)
                )
                for skill in skills:
                    await self.repo.create_skill(employee_uuid, skill)
                changed_fields.append("skills")

            # Update Emergency Contacts
            if emergency_contacts is not None:
                from app.models.employee_emergency_contact import EmployeeEmergencyContact
                await self.session.execute(
                    delete(EmployeeEmergencyContact).where(EmployeeEmergencyContact.employee_id == employee_uuid)
                )
                for ec in emergency_contacts:
                    await self.repo.create_emergency_contact(employee_uuid, ec)
                changed_fields.append("emergency_contacts")

            # Update Bank Accounts
            if bank_accounts is not None:
                from app.models.employee_bank_account import EmployeeBankAccount
                await self.session.execute(
                    delete(EmployeeBankAccount).where(EmployeeBankAccount.employee_id == employee_uuid)
                )
                for ba in bank_accounts:
                    await self.repo.create_bank_account(employee_uuid, ba)
                changed_fields.append("bank_accounts")

            # Write Audit log safely
            if changed_fields:
                audit_user_id = admin_id
                if audit_user_id:
                    from sqlalchemy import select
                    from app.models.user import User
                    u_chk = await self.session.execute(select(User.id).where(User.id == audit_user_id))
                    if not u_chk.scalar_one_or_none():
                        audit_user_id = None

                audit_log = AuditLog(
                    id=uuid.uuid4(),
                    user_id=audit_user_id,
                    company_id=company_id,
                    action="Employee Updated",
                    details=f"Updated employee {employee_uuid}. Changed fields: {', '.join(changed_fields)}",
                    ip_address=ip_address,
                    user_agent=user_agent,
                )
                self.session.add(audit_log)

            await self.session.commit()
            logger.info("update_employee: db commit success | employee_id=%s", employee_uuid)
            full_employee = await self.repo.get_by_id(employee_uuid)
            return EmployeeResponse.model_validate(full_employee)
        except AppException:
            await self.session.rollback()
            raise
        except ValueError as exc:
            await self.session.rollback()
            logger.exception("ValueError in update_employee for employee_id=%s", employee_uuid, exc_info=exc)
            raise AppException(message=str(exc), status_code=status.HTTP_400_BAD_REQUEST)
        except IntegrityError as exc:
            await self.session.rollback()
            logger.exception("IntegrityError in update_employee for employee_id=%s", employee_uuid, exc_info=exc)
            orig_str = str(getattr(exc, "orig", exc))
            orig_lower = orig_str.lower()
            if "ix_employees_personal_email" in orig_lower or "personal_email_key" in orig_lower:
                raise ConflictException(
                    message="Personal email already exists for another employee.",
                    field="personal_email",
                    errors=[{"field": "personal_email", "message": "Personal email already in use."}],
                )
            if "ix_employees_company_email" in orig_lower or "company_email_key" in orig_lower:
                raise ConflictException(
                    message="Company email already exists for another employee.",
                    field="company_email",
                    errors=[{"field": "company_email", "message": "Company email already in use."}],
                )
            if "ix_employees_employee_id" in orig_lower or "employee_id_key" in orig_lower:
                raise ConflictException(
                    message="Employee ID already exists for another employee.",
                    field="employee_id",
                    errors=[{"field": "employee_id", "message": "Employee ID already in use."}],
                )
            if "phone" in orig_lower and ("unique" in orig_lower or "key" in orig_lower):
                raise ConflictException(
                    message="Phone number already exists for another employee.",
                    field="phone",
                    errors=[{"field": "phone", "message": "Phone number already in use."}],
                )
            if "foreign key" in orig_lower or "fk_" in orig_lower:
                raise ConflictException(
                    message="Referenced record (department, manager, branch or user) does not exist.",
                    field="unknown",
                    errors=[{"field": "unknown", "message": "Foreign key constraint failed."}],
                )
            raise ConflictException(
                message="Database constraint violation.",
                field="unknown",
                errors=[{"field": "unknown", "message": orig_str}]
            )
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("update_employee: db error for employee_id=%s", employee_uuid, exc_info=exc)
            raise DatabaseException() from exc
        except Exception as exc:
            await self.session.rollback()
            logger.exception("Unexpected exception in update_employee for employee_id=%s", employee_uuid, exc_info=exc)
            raise

    # ------------------------------------------------------------------
    # Delete (soft)
    # ------------------------------------------------------------------

    async def delete_employee(
        self, admin_id: uuid.UUID, company_id: uuid.UUID, employee_uuid: uuid.UUID
    ) -> None:
        logger.info(
            "delete_employee | admin_id=%s | company_id=%s | employee_id=%s",
            admin_id, company_id, employee_uuid,
        )
        try:
            employee = await self._require_employee_in_company(employee_uuid, company_id)
            await self.repo.soft_delete(employee_uuid, deleted_by=admin_id)
            if employee.user_id:
                from app.models.user import User
                from sqlalchemy import select
                import uuid as py_uuid

                user_res = await self.session.execute(
                    select(User).where(User.id == employee.user_id)
                )
                user = user_res.scalar_one_or_none()
                if user:
                    new_user_email = f"del_{py_uuid.uuid4().hex[:8]}_{user.email}"
                    if len(new_user_email) > 255:
                        new_user_email = new_user_email[:255]
                    new_user_phone = py_uuid.uuid4().hex[:10]
                    user.is_active = False
                    user.account_status = "DEACTIVATED"
                    user.is_deleted = True
                    user.email = new_user_email
                    user.phone = new_user_phone

                await self.auth_repo.revoke_all_user_refresh_tokens(employee.user_id)
                await redis_client.revoke_user_tokens(employee.user_id)
            await self.session.commit()
            logger.info("delete_employee: success | employee_id=%s", employee_uuid)
        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("delete_employee: db error", exc_info=exc)
            raise DatabaseException() from exc

    # ------------------------------------------------------------------
    # Send invitation
    # ------------------------------------------------------------------

    async def send_invitation(
        self, admin_id: uuid.UUID, company_id: uuid.UUID, employee_uuid: uuid.UUID
    ) -> None:
        logger.info(
            "send_invitation | admin_id=%s | company_id=%s | employee_id=%s",
            admin_id, company_id, employee_uuid,
        )
        try:
            from sqlalchemy import select
            from app.models.company import Company

            employee = await self._require_employee_in_company(employee_uuid, company_id)
            if employee.status == "ACTIVE":
                raise AppException(
                    message="Employee has already activated their account.",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            result = await self.session.execute(
                select(Company).where(Company.id == company_id)
            )
            company_obj = result.scalar_one_or_none()
            company_name = company_obj.name if company_obj else "Our Company"

            import secrets
            token = secrets.token_urlsafe(32)
            token_expires = datetime.now(timezone.utc) + timedelta(
                hours=settings.ACTIVATION_TOKEN_EXPIRE_HOURS
            )
            await self.repo.update_employee(
                employee_uuid,
                activation_token=token,
                activation_token_expires_at=token_expires,
                status="INVITED",
                invited_at=datetime.now(timezone.utc),
                invited_by=admin_id,
            )
            if employee.user_id:
                from sqlalchemy import update as sa_update
                from app.models.user import User
                await self.session.execute(
                    sa_update(User).where(User.id == employee.user_id).values(
                        email_verification_token=token,
                        email_verification_expires_at=token_expires,
                    )
                )
            await self.session.commit()
            activation_url = f"{settings.FRONTEND_BASE_URL}/employee/activate?token={token}"
            logger.info(
                "send_invitation: token generated | employee_id=%s | expires=%s | url=%s",
                employee_uuid, token_expires.isoformat(), activation_url,
            )
            email_sent = False
            try:
                await self.email_service.send_employee_onboarding_invite(
                    email=employee.personal_email,
                    name=employee.first_name,
                    employee_id=employee.employee_id,
                    department=employee.department,
                    designation=employee.designation,
                    joining_date=str(employee.joining_date),
                    activation_url=activation_url,
                    company_name=company_name,
                )
                email_sent = True
                logger.info(
                    "send_invitation: email sent | employee_id=%s | email=%s",
                    employee_uuid, _mask_email(employee.personal_email),
                )
            except Exception as mail_exc:
                logger.warning(
                    "send_invitation: invitation email send failed (link generated successfully) | employee_id=%s | error=%s",
                    employee_uuid, str(mail_exc),
                )
            logger.info("send_invitation: success | employee_id=%s", employee_uuid)
            return {
                "activation_token": token,
                "activationToken": token,
                "invite_token": token,
                "inviteToken": token,
                "token": token,
                "activation_url": activation_url,
                "activationUrl": activation_url,
                "invite_link": activation_url,
                "inviteLink": activation_url,
                "invite_url": activation_url,
                "inviteUrl": activation_url,
                "onboarding_url": activation_url,
                "onboardingUrl": activation_url,
                "onboarding_link": activation_url,
                "onboardingLink": activation_url,
                "email_sent": email_sent,
            }
        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("send_invitation: db error", exc_info=exc)
            raise DatabaseException() from exc

    # ------------------------------------------------------------------
    # Deactivate
    # ------------------------------------------------------------------

    async def deactivate_employee(
        self, admin_id: uuid.UUID, company_id: uuid.UUID, employee_uuid: uuid.UUID, reason: str
    ) -> None:
        logger.info(
            "deactivate_employee | admin_id=%s | company_id=%s | employee_id=%s | reason=%s",
            admin_id, company_id, employee_uuid, reason,
        )
        try:
            employee = await self._require_employee_in_company(employee_uuid, company_id)
            employee.is_active = False
            employee.deactivated_at = datetime.now(timezone.utc)
            employee.deactivated_by = admin_id
            employee.deactivation_reason = reason
            employee.status = "DISABLED"

            if employee.user_id:
                from sqlalchemy import update as sa_update
                from app.models.user import User
                await self.session.execute(
                    sa_update(User).where(User.id == employee.user_id).values(
                        is_active=False,
                    )
                )
                await self.auth_repo.revoke_all_user_refresh_tokens(employee.user_id)
                await redis_client.revoke_user_tokens(employee.user_id)

            # Write Audit log
            audit_log = AuditLog(
                id=uuid.uuid4(),
                user_id=admin_id,
                company_id=company_id or employee.company_id,
                action="Employee Deactivated",
                details=f"Deactivated employee {employee_uuid} (Role: {employee.role}). Reason: {reason}",
                ip_address=None,
                user_agent=None,
            )
            self.session.add(audit_log)

            await self.session.commit()
            logger.info("deactivate_employee: success | employee_id=%s", employee_uuid)
        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("deactivate_employee: db error", exc_info=exc)
            raise DatabaseException() from exc

    # ------------------------------------------------------------------
    # Activate by admin (creates User row if needed)
    # ------------------------------------------------------------------

    async def activate_employee_by_admin(
        self, admin_id: uuid.UUID, company_id: uuid.UUID, employee_uuid: uuid.UUID
    ) -> None:
        """Activate an employee's portal account.

        - If employees.user_id is NULL: creates a linked users row with role='EMPLOYEE',
          must_change_password=True, is_active=True, and a random temp password (hashed).
          The employee's phone is normalised to the last 10 digits before inserting into
          users.phone (which is VARCHAR(10) UNIQUE). Returns 409 on phone collision.
        - If user_id already exists: just sets users.is_active=True.
        - Sets employees.status = 'ACTIVE' in both cases.
        """
        logger.info(
            "activate_employee_by_admin | admin_id=%s | company_id=%s | employee_id=%s",
            admin_id, company_id, employee_uuid,
        )
        try:
            from sqlalchemy import select, update as sa_update
            from app.models.user import User, UserRole

            employee = await self._require_employee_in_company(employee_uuid, company_id)


            employee.is_active = True
            employee.deactivated_at = None
            employee.deactivated_by = None
            employee.deactivation_reason = None

            if employee.user_id is None:
                # Determine the email to use for the user account
                user_email = employee.company_email or employee.personal_email

                # Normalize phone: take last 10 digits
                raw_phone = employee.phone or ""
                digits_only = "".join(c for c in raw_phone if c.isdigit())
                normalized_phone = digits_only[-10:] if len(digits_only) >= 10 else digits_only

                # Check for phone collision in users table
                existing_user_phone = await self.session.execute(
                    select(User).where(
                        User.phone == normalized_phone,
                        User.is_deleted == False,
                    )
                )
                if existing_user_phone.scalar_one_or_none():
                    raise ConflictException(
                        message="A user account with this phone number already exists. "
                                "Please update the employee's phone before activating.",
                        field="phone",
                        errors=[{"field": "phone", "message": "Phone number already in use by another account."}],
                    )

                # Generate a temporary password
                temp_password = generate_temp_password()
                password_hash = hash_password(temp_password)

                new_user = await self.auth_repo.create_user(
                    name=f"{employee.first_name} {employee.last_name}",
                    email=user_email,
                    phone=normalized_phone,
                    password_hash=password_hash,
                    role=UserRole.EMPLOYEE,  # uppercase enum
                    is_active=True,
                    is_verified=True,
                    must_change_password=True,
                    company_id=company_id,
                )
                # Link back the new user to the employee
                await self.repo.update_employee(employee_uuid, user_id=new_user.id)

                logger.info(
                    "activate_employee_by_admin: new user created | user_id=%s | employee_id=%s",
                    new_user.id, employee_uuid,
                )

                # Send temp password by email (best-effort)
                try:
                    await self.email_service.send_employee_password_reset_email(
                        email=user_email,
                        name=employee.first_name,
                        temp_password=temp_password,
                    )
                except Exception as mail_exc:
                    logger.warning(
                        "activate_employee_by_admin: temp-password email failed | employee_id=%s | err=%s",
                        employee_uuid, str(mail_exc),
                    )
            else:
                # User already exists — just reactivate
                await self.session.execute(
                    sa_update(User).where(User.id == employee.user_id).values(is_active=True)
                )

            # Set employee status to ACTIVE
            await self.repo.update_status(employee_uuid, "ACTIVE")
            await self.session.commit()
            logger.info("activate_employee_by_admin: success | employee_id=%s", employee_uuid)
        except (AppException, ConflictException):
            await self.session.rollback()
            raise
        except IntegrityError as exc:
            await self.session.rollback()
            logger.exception("activate_employee_by_admin: integrity error (likely phone/email collision)", exc_info=exc)
            raise ConflictException(
                message="A user account with this email or phone already exists.",
                field="email",
                errors=[{"field": "email", "message": "Email or phone already in use."}],
            ) from exc
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("activate_employee_by_admin: db error", exc_info=exc)
            raise DatabaseException() from exc

    # ------------------------------------------------------------------
    # Self-activation (via onboarding link)
    # ------------------------------------------------------------------

    async def validate_invitation_token(self, token: str) -> dict:
        """Validate employee invitation token and return employee information using canonical validator."""
        _, data = await validate_employee_invitation_token(self.session, token)
        return data

    async def activate_employee(
        self,
        employee_uuid: uuid.UUID | None,
        payload: ActivateEmployeeRequest,
        id_str: str | None = None,
    ) -> None:
        clean_token = payload.token.strip() if payload.token else ""
        token_masked = mask_token(clean_token)
        logger.info("activate_employee: request | id=%s | token=%s", employee_uuid or id_str, token_masked)
        try:
            import inspect
            from sqlalchemy import select, func
            from app.models.user import User, UserRole

            employee = None
            if hasattr(self, "repo") and self.repo:
                if employee_uuid and hasattr(self.repo, "get_by_id_raw"):
                    res = self.repo.get_by_id_raw(employee_uuid)
                    employee = await res if inspect.isawaitable(res) else res
                if not employee and id_str and hasattr(self.repo, "get_by_employee_id"):
                    res = self.repo.get_by_employee_id(id_str)
                    employee = await res if inspect.isawaitable(res) else res
                if not employee and clean_token and hasattr(self.repo, "get_by_activation_token"):
                    res = self.repo.get_by_activation_token(clean_token)
                    employee = await res if inspect.isawaitable(res) else res

            if not employee and clean_token:
                employee, _ = await validate_employee_invitation_token(self.session, clean_token)

            if not employee or getattr(employee, "is_deleted", False):
                raise AppException(message="Employee not found.", status_code=status.HTTP_404_NOT_FOUND)

            if getattr(employee, "is_deactivated", False):
                raise AppException(message="Invitation is no longer valid. Request a new invitation.", status_code=status.HTTP_400_BAD_REQUEST)

            if not employee.activation_token:
                raise AppException(
                    message="No activation token found or invitation already accepted. Please request a new invitation if needed.",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            if employee.activation_token != clean_token:
                raise AppException(message="Invalid activation token.", status_code=status.HTTP_400_BAD_REQUEST)

            now = datetime.now(timezone.utc)
            expires_at = employee.activation_token_expires_at
            if expires_at:
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)
                remaining_seconds = (expires_at - now).total_seconds()
                if remaining_seconds <= 0:
                    raise AppException(
                        message="Activation link has expired. Please contact your HR team for a new invitation.",
                        status_code=status.HTTP_400_BAD_REQUEST,
                    )

            valid_statuses = {"CREATED", "INVITATION_SENT", "INVITED", "PENDING", "PROBATION", "ONBOARDING_PENDING"}
            if employee.status not in valid_statuses:
                raise AppException(
                    message="This account has already been activated.",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            now = datetime.now(timezone.utc)
            new_hash = hash_password(payload.new_password)
            user_email = (employee.company_email or employee.personal_email).lower().strip()

            raw_phone = employee.phone or ""
            digits_only = "".join(c for c in raw_phone if c.isdigit())
            clean_phone = digits_only[-10:] if len(digits_only) >= 10 else digits_only

            user = None
            if employee.user_id:
                user_res = await self.session.execute(
                    select(User).where(User.id == employee.user_id)
                )
                user = user_res.scalar_one_or_none()

            if not user:
                user_res = await self.session.execute(
                    select(User).where(
                        (func.lower(User.email) == user_email) |
                        (func.lower(User.email) == employee.personal_email.lower().strip())
                    )
                )
                user = user_res.scalar_one_or_none()

            if user:
                user.password_hash = new_hash
                user.is_active = True
                user.is_verified = True
                user.must_change_password = False
                user.account_status = "ACTIVE"
                user.email_verification_token = None
                user.email_verification_expires_at = None
                if not user.email_verified_at:
                    user.email_verified_at = now
                if not user.company_id and employee.company_id:
                    user.company_id = employee.company_id
                self.session.add(user)
                await self.session.flush()
                employee.user_id = user.id
            else:
                if clean_phone:
                    phone_check = await self.session.execute(
                        select(User).where(User.phone == clean_phone, User.is_deleted.is_(False))
                    )
                    if phone_check.scalar_one_or_none():
                        clean_phone = None

                db_role = getattr(UserRole, (employee.role or "").upper(), UserRole.EMPLOYEE) if hasattr(UserRole, (employee.role or "").upper()) else UserRole.EMPLOYEE

                new_user = User(
                    id=uuid.uuid4(),
                    company_id=employee.company_id,
                    name=f"{employee.first_name} {employee.last_name}".strip(),
                    email=user_email,
                    phone=clean_phone or "0000000000",
                    password_hash=new_hash,
                    role=db_role,
                    is_active=True,
                    is_verified=True,
                    must_change_password=False,
                    account_status="ACTIVE",
                    email_verified_at=now,
                    onboarding_completed=False,
                    email_verification_token=None,
                    email_verification_expires_at=None,
                )
                self.session.add(new_user)
                await self.session.flush()
                employee.user_id = new_user.id

            # Clear invitation token on employee & update status
            employee.activation_token = None
            employee.activation_token_expires_at = None
            employee.is_active = True
            employee.status = "ONBOARDING_PENDING"

            # Sync linked Manager record if present
            from app.models.manager import Manager
            active_user_id = user.id if user else employee.user_id
            mgr_res = await self.session.execute(
                select(Manager).where(
                    (Manager.user_id == active_user_id) |
                    (
                        (Manager.company_id == employee.company_id) &
                        (
                            (func.lower(Manager.personal_email) == user_email) |
                            (func.lower(Manager.company_email) == user_email)
                        )
                    )
                ).execution_options(bypass_tenant=True)
            )
            mgr = mgr_res.scalars().first()
            if mgr:
                mgr.status = "ACTIVE"
                mgr.activation_token = None
                mgr.activation_token_expires_at = None
                if not mgr.user_id and active_user_id:
                    mgr.user_id = active_user_id
                self.session.add(mgr)

            await self.session.commit()
            logger.info("activate_employee: success | employee_id=%s | user_id=%s", employee.id, employee.user_id)

            try:
                await self.email_service.send_employee_welcome_email(
                    email=user_email,
                    name=employee.first_name,
                    employee_id=employee.employee_id,
                )
            except Exception as mail_exc:
                logger.warning(
                    "activate_employee: welcome email send notice | employee_id=%s | error=%s",
                    employee.id, str(mail_exc)
                )

        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("activate_employee: db error", exc_info=exc)
            raise DatabaseException() from exc

    # ------------------------------------------------------------------
    # Approve / Reject (onboarding workflow)
    # ------------------------------------------------------------------

    async def approve_employee(self, admin_id: uuid.UUID, company_id: uuid.UUID, employee_uuid: uuid.UUID) -> None:
        logger.info(
            "approve_employee | admin_id=%s | company_id=%s | employee_id=%s",
            admin_id, company_id, employee_uuid,
        )
        try:
            employee = await self._require_employee_in_company(employee_uuid, company_id)
            if employee.status not in _VALID_APPROVE_STATUSES:
                raise AppException(
                    message="Employee cannot be approved from current status: " + employee.status,
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
            await self.repo.update_status(employee_uuid, "ACTIVE")
            await self.session.commit()
            try:
                await self.email_service.send_employee_welcome_email(
                    email=employee.company_email or employee.personal_email,
                    name=employee.first_name,
                    employee_id=employee.employee_id,
                )
            except Exception as mail_exc:
                logger.error(
                    "approve_employee: welcome email failed | employee_id=%s | exc=%s",
                    employee_uuid, str(mail_exc),
                )
            logger.info("approve_employee: success | employee_id=%s", employee_uuid)
        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("approve_employee: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def reject_employee(
        self,
        admin_id: uuid.UUID,
        company_id: uuid.UUID,
        employee_uuid: uuid.UUID,
        payload: ApproveRejectRequest,
    ) -> None:
        logger.info(
            "reject_employee | admin_id=%s | company_id=%s | employee_id=%s",
            admin_id, company_id, employee_uuid,
        )
        try:
            employee = await self._require_employee_in_company(employee_uuid, company_id)
            employee.is_active = False
            employee.status = "INACTIVE"
            await self.repo.update_status(employee_uuid, "INACTIVE")
            if employee.user_id:
                from sqlalchemy import update as sa_update
                from app.models.user import User
                await self.session.execute(
                    sa_update(User).where(User.id == employee.user_id).values(
                        is_active=False,
                        account_status="DEACTIVATED",
                    )
                )
                await self.auth_repo.revoke_all_user_refresh_tokens(employee.user_id)
                await redis_client.revoke_user_tokens(employee.user_id)
            await self.session.commit()
            logger.info(
                "reject_employee: success | employee_id=%s | reason=%s",
                employee_uuid, payload.reason,
            )
        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("reject_employee: db error", exc_info=exc)
            raise DatabaseException() from exc

    # ------------------------------------------------------------------
    # Reset password (admin-triggered)
    # ------------------------------------------------------------------

    async def reset_employee_password(
        self, admin_id: uuid.UUID, company_id: uuid.UUID, employee_uuid: uuid.UUID
    ) -> None:
        logger.info(
            "reset_employee_password | admin_id=%s | company_id=%s | employee_id=%s",
            admin_id, company_id, employee_uuid,
        )
        try:
            employee = await self._require_employee_in_company(employee_uuid, company_id)
            if not employee.user_id:
                raise AppException(
                    message="No user account linked to this employee.",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
            temp_password = generate_temp_password()
            password_hash = hash_password(temp_password)
            from sqlalchemy import update as sa_update
            from app.models.user import User
            await self.session.execute(
                sa_update(User).where(User.id == employee.user_id).values(
                    password_hash=password_hash, must_change_password=True
                )
            )
            await self.session.commit()
            try:
                await self.email_service.send_employee_password_reset_email(
                    email=employee.company_email or employee.personal_email,
                    name=employee.first_name,
                    temp_password=temp_password,
                )
            except Exception as mail_exc:
                logger.error(
                    "reset_employee_password: email failed | employee_id=%s | exc=%s",
                    employee_uuid, str(mail_exc),
                )
            logger.info("reset_employee_password: success | employee_id=%s", employee_uuid)
        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("reset_employee_password: db error", exc_info=exc)
            raise DatabaseException() from exc

    # ------------------------------------------------------------------
    # Onboarding status
    # ------------------------------------------------------------------

    async def get_onboarding_status(
        self,
        employee_uuid: uuid.UUID,
        company_id: uuid.UUID | None = None,
    ) -> EmployeeOnboardingStatusResponse:
        try:
            employee = await self.repo.get_by_id_raw(employee_uuid)
            if not employee:
                raise AppException(message="Employee not found.", status_code=status.HTTP_404_NOT_FOUND)
            if company_id is not None and employee.company_id != company_id:
                raise AppException(message="Employee not found.", status_code=status.HTTP_404_NOT_FOUND)
            steps = await self.repo.get_onboarding_steps(employee_uuid)
            total = len(steps)
            completed = sum(1 for s in steps if s.is_completed)
            pct = round((completed / total * 100), 1) if total > 0 else 0.0
            step_responses = [EmployeeOnboardingStepResponse.model_validate(s) for s in steps]
            return EmployeeOnboardingStatusResponse(
                employee_id=employee_uuid,
                status=employee.status,
                total_steps=total,
                completed_steps=completed,
                completion_percentage=pct,
                steps=step_responses,
            )
        except AppException:
            raise
        except SQLAlchemyError as exc:
            logger.exception("get_onboarding_status: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def get_dashboard_stats(self, company_id: uuid.UUID) -> dict[str, Any]:
        """Fetch aggregation analytics for the employee management dashboard.
        
        Optimized: single combined query + 30s in-memory cache.
        """
        from app.core.cache import cache_get, cache_set
        
        cache_key = f"emp_dashboard:{company_id}"
        cached = cache_get(cache_key)
        if cached is not None:
            return cached

        from sqlalchemy import select, func, case
        from app.models.employee import Employee

        base_filter = [Employee.company_id == company_id, Employee.is_deleted == False]

        # Single combined query: total, capacity, status/dept/type/cc breakdowns
        combined_stmt = select(
            func.count().label("total"),
            func.coalesce(func.sum(Employee.employee_capacity), 0).label("total_capacity"),
            # Status counts via conditional aggregation
            func.count(case((Employee.status == "ACTIVE", 1))).label("active"),
            func.count(case((Employee.status.in_(["INACTIVE", "DEACTIVATED"]), 1))).label("inactive"),
            func.count(case((Employee.status.in_(["INVITED", "ONBOARDING", "ONBOARDING_PENDING"]), 1))).label("onboarding"),
            func.count(case((Employee.status == "PROBATION", 1))).label("probation"),
            func.count(case((Employee.status == "NOTICE_PERIOD", 1))).label("notice"),
        ).select_from(Employee).where(*base_filter)

        combined_res = await self.session.execute(combined_stmt)
        row = combined_res.one()

        total_employees = row.total or 0
        total_capacity = int(row.total_capacity or 0)
        active_cnt = row.active or 0
        inactive_cnt = row.inactive or 0
        onboarding_cnt = row.onboarding or 0
        probation_cnt = row.probation or 0
        notice_cnt = row.notice or 0

        # Breakdown queries (these are lightweight GROUP BY, run concurrently)
        import asyncio

        async def _status_breakdown():
            stmt = select(Employee.status, func.count()).where(*base_filter).group_by(Employee.status)
            res = await self.session.execute(stmt)
            return {r[0] or "UNKNOWN": r[1] for r in res.all()}

        async def _dept_breakdown():
            stmt = select(Employee.department, func.count()).where(*base_filter).group_by(Employee.department)
            res = await self.session.execute(stmt)
            return {r[0] or "Unassigned": r[1] for r in res.all()}

        async def _cc_breakdown():
            stmt = select(Employee.cost_center_id, func.count()).where(*base_filter).group_by(Employee.cost_center_id)
            res = await self.session.execute(stmt)
            return {r[0] or "Default": r[1] for r in res.all()}

        async def _type_breakdown():
            stmt = select(Employee.employment_type, func.count()).where(*base_filter).group_by(Employee.employment_type)
            res = await self.session.execute(stmt)
            return {r[0] or "FULL_TIME": r[1] for r in res.all()}

        status_breakdown = await _status_breakdown()
        dept_breakdown = await _dept_breakdown()
        cc_breakdown = await _cc_breakdown()
        type_breakdown = await _type_breakdown()

        result = {
            "total_employees": total_employees,
            "active_employees": active_cnt,
            "inactive_employees": inactive_cnt,
            "onboarding_employees": onboarding_cnt,
            "probation_employees": probation_cnt,
            "notice_period_employees": notice_cnt,
            "total_capacity": total_capacity,
            "status_breakdown": status_breakdown,
            "department_breakdown": dept_breakdown,
            "cost_center_breakdown": cc_breakdown,
            "employment_type_breakdown": type_breakdown,
        }

        cache_set(cache_key, result, ttl_seconds=30.0)
        return result

    async def bulk_import_employees(
        self, admin_id: uuid.UUID, company_id: uuid.UUID, file_bytes: bytes, filename: str
    ) -> dict[str, Any]:
        """Import employees from uploaded Excel (.xlsx) or CSV file."""
        import io, csv
        rows_data = []

        if filename.lower().endswith(".csv"):
            content = file_bytes.decode("utf-8-sig", errors="ignore")
            reader = csv.DictReader(io.StringIO(content))
            rows_data = list(reader)
        else:
            try:
                import openpyxl
                wb = openpyxl.load_workbook(filename=io.BytesIO(file_bytes), data_only=True)
                sheet = wb.active
                headers = [str(cell.value or "").strip().lower().replace(" ", "_") for cell in sheet[1]]
                for row in sheet.iter_rows(min_row=2, values_only=True):
                    if not any(row):
                        continue
                    row_dict = {}
                    for idx, val in enumerate(row):
                        if idx < len(headers) and headers[idx]:
                            row_dict[headers[idx]] = str(val).strip() if val is not None else ""
                    rows_data.append(row_dict)
            except Exception as exc:
                raise AppException(message=f"Failed to parse Excel file: {str(exc)}", status_code=status.HTTP_400_BAD_REQUEST)

        total_processed = len(rows_data)
        imported_count = 0
        skipped_count = 0
        errors = []

        for idx, row in enumerate(rows_data, start=2):
            first_name = row.get("first_name") or row.get("firstname") or (row.get("name", "").split(" ")[0] if row.get("name") else "")
            last_name = row.get("last_name") or row.get("lastname") or (row.get("name", "").split(" ")[1] if row.get("name") and len(row.get("name").split(" ")) > 1 else "Employee")
            personal_email = row.get("personal_email") or row.get("email")
            phone = row.get("phone") or row.get("mobile") or row.get("contact")

            if not first_name or not personal_email or not phone:
                skipped_count += 1
                errors.append({"row": idx, "message": "Missing required fields (first_name, personal_email, phone)."})
                continue

            personal_email = str(personal_email).strip().lower()
            if await self.repo.get_by_personal_email(personal_email):
                skipped_count += 1
                errors.append({"row": idx, "message": f"Email '{personal_email}' already exists."})
                continue

            dept = row.get("department") or "General"
            desig = row.get("designation") or "Staff"
            joining_str = row.get("joining_date") or row.get("doj")
            from datetime import date
            joining_date = date.today()
            if joining_str:
                try:
                    joining_date = date.fromisoformat(str(joining_str).split("T")[0])
                except Exception:
                    pass

            emp_capacity = 100
            if row.get("employee_capacity") or row.get("capacity"):
                try:
                    emp_capacity = int(row.get("employee_capacity") or row.get("capacity"))
                except ValueError:
                    pass

            cost_center = row.get("cost_center_id") or row.get("cost_center") or None

            from app.models.employee import Employee
            emp_id = row.get("employee_id") or await generate_employee_id(self.session)

            new_emp = Employee(
                user_id=None,
                company_id=company_id,
                employee_id=str(emp_id),
                first_name=str(first_name),
                last_name=str(last_name),
                personal_email=personal_email,
                company_email=str(row.get("company_email") or personal_email),
                phone=str(phone),
                department=str(dept),
                designation=str(desig),
                joining_date=joining_date,
                employment_type=str(row.get("employment_type", "FULL_TIME")).upper(),
                employment_status="CONFIRMED",
                employee_capacity=emp_capacity,
                cost_center_id=cost_center,
                role="employee",
                status=str(row.get("status") or "ACTIVE").upper(),
                created_by=admin_id,
            )
            self.session.add(new_emp)
            await self.session.flush()
            imported_count += 1

        await self.session.commit()
        return {
            "total_processed": total_processed,
            "imported_count": imported_count,
            "skipped_count": skipped_count,
            "errors": errors,
        }


async def get_employee_service(
    session: AsyncSession = Depends(get_db_session),
    email_service: EmailService = Depends(get_email_service),
) -> EmployeeService:
    return EmployeeService(
        session=session,
        employee_repository=EmployeeRepository(session),
        auth_repository=AuthRepository(session),
        email_service=email_service,
    )

