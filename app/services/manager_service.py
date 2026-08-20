"""Manager service layer: all business logic, transactions, and structured logging."""

from __future__ import annotations

import logging
import math
import traceback
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Depends, status
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AppException, ConflictException, DatabaseException
from app.core.redis_client import redis_client
from app.core.security import hash_password
from app.db.database import get_db_session
from app.models.user import User, UserRole
from app.repositories.auth_repository import AuthRepository
from app.repositories.manager_repository import ManagerRepository
from app.schemas.manager import (
    ActivateManagerRequest,
    ManagerCreate,
    ManagerListResponse,
    ManagerResponse,
    ManagerUpdate,
    ManagerListItem,
    ActivateManagerOnboardingRequest,
    ManagerOnboardingCompleteRequest,
)
from app.services.email_service import EmailService, get_email_service
from app.utils.employee import (
    generate_activation_token,
    generate_temp_password,
)

logger = logging.getLogger(__name__)

_VALID_SEND_INVITATION_STATUSES = {"CREATED", "INVITATION_SENT"}

def _mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    masked = local[:1] + "***" if len(local) > 1 else "***"
    return masked + "@" + domain

# ---------------------------------------------------------------------------
# Sequential Manager ID Generator
# ---------------------------------------------------------------------------

async def generate_manager_id(session: AsyncSession) -> str:
    from app.models.manager import Manager
    year_month = datetime.now(timezone.utc).strftime("%Y%m")
    prefix = f"MGR-{year_month}-"
    from sqlalchemy import select
    result = await session.execute(
        select(Manager.manager_id)
        .where(Manager.manager_id.like(prefix + "%"))
        .order_by(Manager.manager_id.desc())
        .limit(1)
    )
    last_id = result.scalar_one_or_none()
    if last_id:
        try:
            seq = int(last_id.split("-")[-1]) + 1
        except (ValueError, IndexError):
            seq = 1
    else:
        seq = 1
    return f"{prefix}{seq:04d}"

# ---------------------------------------------------------------------------
# Company Email collision generator for Managers
# ---------------------------------------------------------------------------

async def generate_manager_company_email(
    first_name: str,
    last_name: str,
    domain: str,
    session: AsyncSession,
) -> str:
    from app.models.manager import Manager
    from app.utils.employee import _sanitize_name_part
    from sqlalchemy import select
    first = _sanitize_name_part(first_name)
    last = _sanitize_name_part(last_name)
    base_local = f"{first}.{last}"

    for suffix in [""] + [str(i) for i in range(1, 100)]:
        candidate = f"{base_local}{suffix}@{domain}"
        result = await session.execute(
            select(Manager.company_email).where(Manager.company_email == candidate)
        )
        if result.scalar_one_or_none() is None:
            return candidate

    return f"{base_local}.{uuid.uuid4().hex[:6]}@{domain}"


class ManagerService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        manager_repository: ManagerRepository,
        auth_repository: AuthRepository,
        email_service: EmailService,
    ) -> None:
        self.session = session
        self.repo = manager_repository
        self.auth_repo = auth_repository
        self.email_service = email_service

    async def create_manager(self, admin_id: uuid.UUID, payload: ManagerCreate) -> ManagerResponse:
        logger.info("create_manager | admin_id=%s | email=%s", admin_id, _mask_email(str(payload.personal_email)))
        try:
            from sqlalchemy import select
            from app.models.company import Company
            admin_user = await self.auth_repo.get_user_by_id(admin_id)
            if not admin_user or not admin_user.company_id:
                raise AppException(message="Admin company not found.", status_code=status.HTTP_400_BAD_REQUEST)
            company_name = "Our Company"
            try:
                result = await self.session.execute(
                    select(Company).where(Company.id == admin_user.company_id)
                )
                import inspect
                if hasattr(result, "scalar_one_or_none"):
                    res = result.scalar_one_or_none()
                    company_obj = await res if inspect.isawaitable(res) else res
                    if company_obj and hasattr(company_obj, "name"):
                        company_name = company_obj.name
            except Exception:
                pass

            # --- Uniqueness checks ---
            personal_email = str(payload.personal_email).strip().lower()
            if await self.repo.get_by_personal_email(personal_email):
                raise ConflictException(
                    message="Email already exists",
                    field="personal_email",
                    errors=[{"field": "personal_email", "message": "Email already in use."}]
                )
            if payload.company_email:
                if await self.repo.get_by_company_email(str(payload.company_email)):
                    raise ConflictException(
                        message="Company email already exists",
                        field="company_email",
                        errors=[{"field": "company_email", "message": "Company email already in use."}]
                    )
                company_email = str(payload.company_email)
            else:
                company_email = await generate_manager_company_email(
                    payload.first_name, payload.last_name, settings.COMPANY_EMAIL_DOMAIN, self.session
                )
            if await self.repo.get_by_phone(payload.phone):
                raise ConflictException(
                    message="Phone number already exists",
                    field="phone",
                    errors=[{"field": "phone", "message": "Phone number already in use."}]
                )

            if payload.manager_id:
                if await self.repo.get_by_manager_id(payload.manager_id):
                    raise ConflictException(
                        message="Employee ID already exists",
                        field="manager_id",
                        errors=[{"field": "manager_id", "message": "Employee ID already in use."}]
                    )
                manager_id = payload.manager_id
            else:
                manager_id = await generate_manager_id(self.session)

            # --- Generate onboarding token (7 days) ---
            import secrets
            token = secrets.token_urlsafe(32)
            token_expires = datetime.now(timezone.utc) + timedelta(days=7)

            mgr_kwargs = {
                "user_id": None,  # No user record created – employee invitation pattern
                "company_id": admin_user.company_id,
                "manager_id": manager_id,
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
                "branch": payload.branch,
                "office_location": payload.branch,
                "work_location": payload.work_location,
                "joining_date": payload.joining_date,
                "employment_type": payload.employment_type,
                "employment_status": payload.employment_status,
                "shift": payload.shift,
                "probation_period_months": payload.probation_period_months,
                "ctc": payload.ctc,
                "basic_salary": payload.basic_salary,
                "hra": payload.hra,
                "bonus": payload.bonus,
                "pf": payload.pf,
                "esi": payload.esi,
                "professional_tax": payload.professional_tax,
                "role": "manager",
                "leave_group": payload.leave_group,
                "status": "INVITED",
                "activation_token": token,
                "activation_token_expires_at": token_expires,
                "invited_at": datetime.now(timezone.utc),
                "invited_by": admin_id,
                "created_by": admin_id,
                "reporting_to": payload.reporting_to,
                # Permissions & Access Settings
                "can_approve_leave": payload.can_approve_leave,
                "can_approve_attendance": payload.can_approve_attendance,
                "can_manage_employees": payload.can_manage_employees,
                "can_view_payroll": payload.can_view_payroll,
                "can_edit_departments": payload.can_edit_departments,
                "can_invite_users": payload.can_invite_users,
                "can_manage_recruitment": payload.can_manage_recruitment,
                "can_manage_performance": payload.can_manage_performance,
            }

            manager = await self.repo.create_manager(**mgr_kwargs)

            # Create synchronized Employee workforce record for directory & organizational parity
            from app.models.employee import Employee
            emp_record = Employee(
                id=manager.id,
                user_id=manager.user_id,
                company_id=admin_user.company_id,
                employee_id=manager_id,
                first_name=payload.first_name.strip(),
                last_name=payload.last_name.strip(),
                profile_photo_url=payload.profile_photo_url,
                gender=payload.gender,
                date_of_birth=payload.date_of_birth,
                personal_email=personal_email,
                company_email=company_email,
                phone=payload.phone,
                alternate_phone=payload.alternate_phone,
                blood_group=payload.blood_group,
                marital_status=payload.marital_status,
                department=payload.department,
                designation=payload.designation,
                branch=payload.branch,
                work_location=payload.work_location,
                joining_date=payload.joining_date,
                employment_type=payload.employment_type or "FULL_TIME",
                employment_status=payload.employment_status or "CONFIRMED",
                shift=payload.shift,
                probation_period_months=payload.probation_period_months,
                ctc=payload.ctc,
                basic_salary=payload.basic_salary,
                hra=payload.hra,
                bonus=payload.bonus,
                pf=payload.pf,
                esi=payload.esi,
                professional_tax=payload.professional_tax,
                role="manager",
                leave_group=payload.leave_group,
                status="INVITED" if not manager.user_id else "ACTIVE",
                activation_token=token,
                activation_token_expires_at=token_expires,
                invited_at=datetime.now(timezone.utc),
                invited_by=admin_id,
                created_by=admin_id,
                reporting_manager_id=payload.reporting_to,
                manager_id=payload.reporting_to,
            )
            self.session.add(emp_record)

            for addr in payload.addresses:
                data = addr.model_dump(exclude={"address_type"})
                await self.repo.upsert_address(manager.id, addr.address_type, data)
            for doc in payload.documents:
                await self.repo.create_document(manager.id, doc.model_dump())
            for edu in payload.education:
                await self.repo.create_education(manager.id, edu.model_dump())
            for exp in payload.experience:
                await self.repo.create_experience(manager.id, exp.model_dump())
            for skill in payload.skills:
                await self.repo.create_skill(manager.id, skill.model_dump())
            for ec in payload.emergency_contacts:
                await self.repo.create_emergency_contact(manager.id, ec.model_dump())

            # Commit BEFORE sending email (employee invitation pattern)
            await self.session.commit()

            activation_url = f"{settings.FRONTEND_BASE_URL.rstrip('/')}/manager/activate?token={token}"
            logger.info(
                "create_manager: token generated | manager_id=%s | expires=%s | url=%s",
                manager_id, token_expires.isoformat(), activation_url,
            )

            email_sent = False
            try:
                await self.email_service.send_manager_onboarding_invite(
                    email=personal_email,
                    name=payload.first_name,
                    employee_id=manager_id,
                    department=payload.department,
                    designation=payload.designation,
                    joining_date=str(payload.joining_date),
                    activation_url=activation_url,
                    company_name=company_name,
                )
                email_sent = True
                logger.info(
                    "create_manager: invitation email sent | manager_id=%s | email=%s",
                    manager_id, _mask_email(personal_email),
                )
            except Exception as mail_exc:
                logger.error(
                    "create_manager: invitation email FAILED | manager_id=%s | email=%s | error=%s",
                    manager_id, _mask_email(personal_email), str(mail_exc),
                    exc_info=True,
                )

            logger.info(
                "create_manager: success | manager_id=%s | email_sent=%s",
                manager_id, email_sent,
            )
            full_manager = await self.repo.get_by_id(manager.id)
            result = ManagerResponse.model_validate(full_manager)
            result.__dict__["_email_sent"] = email_sent
            return result

        except (AppException, ConflictException):
            await self.session.rollback()
            raise
        except IntegrityError as exc:
            await self.session.rollback()
            logger.exception("create_manager: integrity error", exc_info=exc)
            raise ConflictException(
                message="Manager with this email or phone already exists.",
                errors=[{"field": "personal_email", "message": "Duplicate value."}]
            ) from exc
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("create_manager: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def list_managers(
        self,
        department: str | None,
        status_filter: str | None,
        employment_type: str | None,
        search: str | None,
        page: int,
        limit: int,
    ) -> ManagerListResponse:
        try:
            offset = (page - 1) * limit
            managers = await self.repo.list_managers(
                department=department,
                status=status_filter,
                employment_type=employment_type,
                search=search,
                limit=limit,
                offset=offset,
            )
            total = await self.repo.count_managers(
                department=department,
                status=status_filter,
                employment_type=employment_type,
                search=search,
            )
            items = [ManagerListItem.model_validate(m) for m in managers]
            pages = math.ceil(total / limit) if limit > 0 else 0
            return ManagerListResponse(items=items, total=total, page=page, limit=limit, pages=pages)
        except SQLAlchemyError as exc:
            logger.exception("list_managers: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def get_manager(self, manager_uuid: uuid.UUID) -> ManagerResponse:
        try:
            manager = await self.repo.get_by_id(manager_uuid)
            if not manager:
                raise AppException(message="Manager not found.", status_code=status.HTTP_404_NOT_FOUND)
            return ManagerResponse.model_validate(manager)
        except AppException:
            raise
        except SQLAlchemyError as exc:
            logger.exception("get_manager: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def update_manager(
        self, admin_id: uuid.UUID, manager_uuid: uuid.UUID, payload: ManagerUpdate
    ) -> ManagerResponse:
        logger.info("update_manager | admin_id=%s | manager_id=%s", admin_id, manager_uuid)
        try:
            manager = await self.repo.get_by_id_raw(manager_uuid)
            if not manager or manager.is_deleted:
                raise AppException(message="Manager not found.", status_code=status.HTTP_404_NOT_FOUND)
            
            update_data = payload.model_dump(exclude_unset=True)

            # Prevent updating immutable fields
            for immutable in ["id", "company_id", "created_at", "user_id", "created_by"]:
                update_data.pop(immutable, None)

            # Self-reporting prevention
            if "reporting_to" in update_data and update_data["reporting_to"] == manager_uuid:
                raise AppException(
                    message="A manager cannot report to themselves.",
                    status_code=status.HTTP_400_BAD_REQUEST,
                    errors=[{"field": "reporting_to", "message": "Self-reporting is not allowed."}]
                )

            # Extract nested relations if present
            addresses = update_data.pop("addresses", None)
            documents = update_data.pop("documents", None)
            education = update_data.pop("education", None)
            experience = update_data.pop("experience", None)
            skills = update_data.pop("skills", None)
            emergency_contacts = update_data.pop("emergency_contacts", None)

            # Duplicate uniqueness checks
            if "personal_email" in update_data and update_data["personal_email"] is not None:
                p_email = str(update_data["personal_email"]).strip().lower()
                existing = await self.repo.get_by_personal_email(p_email)
                if existing and existing.id != manager_uuid:
                    raise ConflictException(
                        message="Email already exists",
                        field="personal_email",
                        errors=[{"field": "personal_email", "message": "Email already in use."}]
                    )
                update_data["personal_email"] = p_email

            if "company_email" in update_data and update_data["company_email"] is not None:
                c_email = str(update_data["company_email"]).strip().lower()
                existing = await self.repo.get_by_company_email(c_email)
                if existing and existing.id != manager_uuid:
                    raise ConflictException(
                        message="Company email already exists",
                        field="company_email",
                        errors=[{"field": "company_email", "message": "Company email already in use."}]
                    )
                update_data["company_email"] = c_email

            if "phone" in update_data and update_data["phone"] is not None:
                phone_str = str(update_data["phone"]).strip()
                existing = await self.repo.get_by_phone(phone_str)
                if existing and existing.id != manager_uuid:
                    raise ConflictException(
                        message="Phone number already exists",
                        field="phone",
                        errors=[{"field": "phone", "message": "Phone number already in use."}]
                    )
                update_data["phone"] = phone_str

            if "manager_id" in update_data and update_data["manager_id"] is not None:
                m_code = str(update_data["manager_id"]).strip()
                existing = await self.repo.get_by_manager_id(m_code)
                if existing and existing.id != manager_uuid:
                    raise ConflictException(
                        message="Employee ID already exists",
                        field="manager_id",
                        errors=[{"field": "manager_id", "message": "Employee ID already in use."}]
                    )
                update_data["manager_id"] = m_code

            if "branch" in update_data:
                update_data["office_location"] = update_data["branch"]

            if not update_data and addresses is None and documents is None and education is None and experience is None and skills is None and emergency_contacts is None:
                full_manager = await self.repo.get_by_id(manager_uuid)
                return ManagerResponse.model_validate(full_manager)

            if update_data:
                await self.repo.update_manager(manager_uuid, **update_data)

            # Synchronize Employee record
            from sqlalchemy import update as sa_update
            from app.models.employee import Employee
            emp_update_fields = {
                k: v for k, v in update_data.items()
                if k in {
                    "first_name", "last_name", "profile_photo_url", "gender", "date_of_birth",
                    "personal_email", "company_email", "phone", "alternate_phone", "blood_group",
                    "marital_status", "department", "designation", "branch", "work_location",
                    "joining_date", "employment_type", "employment_status", "shift",
                    "probation_period_months", "ctc", "basic_salary", "hra", "bonus", "pf",
                    "esi", "professional_tax", "role", "leave_group", "status", "is_active"
                }
            }
            if "manager_id" in update_data:
                emp_update_fields["employee_id"] = update_data["manager_id"]
            if "reporting_to" in update_data:
                emp_update_fields["reporting_manager_id"] = update_data["reporting_to"]
                emp_update_fields["manager_id"] = update_data["reporting_to"]

            if emp_update_fields:
                await self.session.execute(
                    sa_update(Employee).where(
                        (Employee.id == manager_uuid) | (Employee.personal_email == manager.personal_email)
                    ).values(**emp_update_fields)
                )

            # Process nested relations if provided
            if addresses is not None:
                for addr in addresses:
                    addr_dict = addr if isinstance(addr, dict) else addr.model_dump()
                    addr_type = addr_dict.pop("address_type", "CURRENT")
                    await self.repo.upsert_address(manager_uuid, addr_type, addr_dict)

            # Synchronize User active state if manager active status or lifecycle changed
            if manager.user_id:
                from app.models.user import User
                new_is_active = update_data.get("is_active", manager.is_active)
                new_status = (update_data.get("status") or manager.status or "").upper()

                if (
                    new_is_active is False
                    or new_status in ("DISABLED", "INACTIVE", "DEACTIVATED", "ARCHIVED", "TERMINATED", "EXITED", "DELETED")
                ):
                    await self.session.execute(
                        sa_update(User).where(User.id == manager.user_id).values(
                            is_active=False,
                        )
                    )
                    await self.auth_repo.revoke_all_user_refresh_tokens(manager.user_id)
                    await redis_client.revoke_user_tokens(manager.user_id)
                elif new_is_active is True and new_status == "ACTIVE":
                    await self.session.execute(
                        sa_update(User).where(User.id == manager.user_id).values(
                            is_active=True,
                        )
                    )

            await self.session.commit()
            logger.info("update_manager: success | manager_id=%s", manager_uuid)
            full_manager = await self.repo.get_by_id(manager_uuid)
            return ManagerResponse.model_validate(full_manager)
        except (AppException, ConflictException):
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("update_manager: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def delete_manager(self, admin_id: uuid.UUID, manager_uuid: uuid.UUID) -> None:
        logger.info("delete_manager | admin_id=%s | manager_id=%s", admin_id, manager_uuid)
        try:
            manager = await self.repo.get_by_id_raw(manager_uuid)
            if not manager or manager.is_deleted:
                raise AppException(message="Manager not found.", status_code=status.HTTP_404_NOT_FOUND)
            manager.is_active = False
            await self.repo.soft_delete(manager_uuid, deleted_by=admin_id)
            from sqlalchemy import update as sa_update
            from app.models.employee import Employee
            await self.session.execute(
                sa_update(Employee).where(
                    (Employee.id == manager_uuid) | (Employee.personal_email == manager.personal_email)
                ).values(
                    is_active=False,
                    is_deleted=True,
                    deleted_at=datetime.now(timezone.utc),
                )
            )
            if manager.user_id:
                from app.models.user import User
                await self.session.execute(
                    sa_update(User).where(User.id == manager.user_id).values(
                        is_active=False,
                        is_deleted=True,
                    )
                )
                await self.auth_repo.revoke_all_user_refresh_tokens(manager.user_id)
                await redis_client.revoke_user_tokens(manager.user_id)
            await self.session.commit()
            logger.info("delete_manager: success | manager_id=%s", manager_uuid)
        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("delete_manager: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def send_invitation(self, admin_id: uuid.UUID, manager_uuid: uuid.UUID) -> None:
        logger.info("send_invitation | admin_id=%s | manager_id=%s", admin_id, manager_uuid)
        try:
            from sqlalchemy import select, update as sa_update
            from app.models.company import Company
            from app.models.employee import Employee
            manager = await self.repo.get_by_id_raw(manager_uuid)
            if not manager:
                raise AppException(message="Manager not found.", status_code=status.HTTP_404_NOT_FOUND)
            if manager.status == "ACTIVE":
                raise AppException(
                    message="Manager has already activated their account.",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
            admin_user = await self.auth_repo.get_user_by_id(admin_id)
            if not admin_user or not admin_user.company_id:
                raise AppException(message="Admin company not found.", status_code=status.HTTP_400_BAD_REQUEST)
            
            company_name = "Our Company"
            try:
                result = await self.session.execute(
                    select(Company).where(Company.id == admin_user.company_id)
                )
                import inspect
                if hasattr(result, "scalar_one_or_none"):
                    res = result.scalar_one_or_none()
                    company_obj = await res if inspect.isawaitable(res) else res
                    if company_obj and hasattr(company_obj, "name"):
                        company_name = company_obj.name
            except Exception:
                pass

            import secrets
            token = secrets.token_urlsafe(32)
            token_expires = datetime.now(timezone.utc) + timedelta(days=7)
            await self.repo.update_manager(
                manager_uuid,
                activation_token=token,
                activation_token_expires_at=token_expires,
                status="INVITED",
                invited_at=datetime.now(timezone.utc),
                invited_by=admin_id,
            )
            await self.session.execute(
                sa_update(Employee).where(
                    (Employee.id == manager_uuid) | (Employee.personal_email == manager.personal_email)
                ).values(
                    activation_token=token,
                    activation_token_expires_at=token_expires,
                    status="INVITED",
                    invited_at=datetime.now(timezone.utc),
                    invited_by=admin_id,
                )
            )
            await self.session.commit()
            activation_url = f"{settings.FRONTEND_BASE_URL.rstrip('/')}/manager/activate?token={token}"
            logger.info(
                "send_invitation: token generated | manager_id=%s | expires=%s | url=%s",
                manager_uuid, token_expires.isoformat(), activation_url,
            )
            try:
                await self.email_service.send_manager_onboarding_invite(
                    email=manager.personal_email,
                    name=manager.first_name,
                    employee_id=manager.manager_id,
                    department=manager.department,
                    designation=manager.designation,
                    joining_date=str(manager.joining_date),
                    activation_url=activation_url,
                    company_name=company_name,
                )
                logger.info(
                    "send_invitation: email sent | manager_id=%s | email=%s",
                    manager_uuid, _mask_email(manager.personal_email),
                )
            except Exception as mail_exc:
                logger.error(
                    "send_invitation: email FAILED | manager_id=%s | email=%s | error=%s",
                    manager_uuid, _mask_email(manager.personal_email), str(mail_exc),
                    exc_info=True,
                )
                raise AppException(
                    message="Invitation email could not be sent. Check SMTP configuration.",
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                ) from mail_exc
            logger.info("send_invitation: success | manager_id=%s", manager_uuid)
        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("send_invitation: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def activate_manager(self, manager_uuid: uuid.UUID, payload: ActivateManagerRequest) -> None:
        logger.info("activate_manager | manager_id=%s", manager_uuid)
        try:
            manager = await self.repo.get_by_id_raw(manager_uuid)
            if not manager:
                raise AppException(message="Manager not found.", status_code=status.HTTP_404_NOT_FOUND)
            if not manager.activation_token:
                raise AppException(
                    message="No activation token found. Please request a new invitation.",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
            if manager.activation_token != payload.token:
                raise AppException(message="Invalid activation token.", status_code=status.HTTP_400_BAD_REQUEST)
            now = datetime.now(timezone.utc)
            expires_at = manager.activation_token_expires_at
            if expires_at:
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)
                if now > expires_at:
                    raise AppException(
                        message="Activation link has expired. Please contact your HR team for a new invitation.",
                        status_code=status.HTTP_400_BAD_REQUEST,
                    )
            if manager.status not in {"CREATED", "INVITATION_SENT"}:
                raise AppException(message="This account has already been activated.", status_code=status.HTTP_400_BAD_REQUEST)
            if not manager.user_id:
                raise AppException(message="No user account linked. Please contact HR.", status_code=status.HTTP_400_BAD_REQUEST)
            new_hash = hash_password(payload.new_password)
            await self.auth_repo.update_user_activation(
                manager.user_id,
                password_hash=new_hash,
                is_active=True,
                is_verified=True,
                must_change_password=False,
            )
            await self.repo.update_manager(
                manager_uuid,
                activation_token=None,
                activation_token_expires_at=None,
                status="ACTIVE",  # Activated managers directly go to ACTIVE status
            )
            from sqlalchemy import update as sa_update
            from app.models.employee import Employee
            await self.session.execute(
                sa_update(Employee).where(
                    (Employee.id == manager_uuid) | (Employee.personal_email == manager.personal_email)
                ).values(
                    activation_token=None,
                    activation_token_expires_at=None,
                    status="ACTIVE",
                    is_active=True,
                )
            )
            await self.session.commit()

            try:
                await self.email_service.send_manager_welcome_email(
                    email=manager.company_email or manager.personal_email,
                    name=manager.first_name,
                    employee_id=manager.manager_id,
                )
            except Exception as mail_exc:
                logger.error("activate_manager: welcome email failed | manager_id=%s | exc=%s", manager_uuid, str(mail_exc))

            logger.info("activate_manager: success | manager_id=%s", manager_uuid)
        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("activate_manager: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def reset_manager_password(self, admin_id: uuid.UUID, manager_uuid: uuid.UUID) -> None:
        logger.info("reset_manager_password | admin_id=%s | manager_id=%s", admin_id, manager_uuid)
        try:
            manager = await self.repo.get_by_id_raw(manager_uuid)
            if not manager:
                raise AppException(message="Manager not found.", status_code=status.HTTP_404_NOT_FOUND)
            if not manager.user_id:
                raise AppException(message="No user account linked to this manager.", status_code=status.HTTP_400_BAD_REQUEST)
            temp_password = generate_temp_password()
            password_hash = hash_password(temp_password)

            from sqlalchemy import update as sa_update
            from app.models.user import User
            await self.session.execute(
                sa_update(User).where(User.id == manager.user_id).values(
                    password_hash=password_hash, must_change_password=True
                )
            )
            await self.session.commit()

            try:
                await self.email_service.send_manager_password_reset_email(
                    email=manager.company_email or manager.personal_email,
                    name=manager.first_name,
                    temp_password=temp_password,
                )
            except Exception as mail_exc:
                logger.error("reset_manager_password: email failed | manager_id=%s | exc=%s", manager_uuid, str(mail_exc))

            logger.info("reset_manager_password: success | manager_id=%s", manager_uuid)
        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("reset_manager_password: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def get_onboarding_token_status(self, token: str) -> dict:
        clean_token = token.strip() if token else ""
        if not clean_token:
            raise AppException(message="Invitation token is required.", status_code=status.HTTP_400_BAD_REQUEST)
        try:
            from sqlalchemy import select
            from app.models.manager import Manager
            from app.models.company import Company
            result = await self.session.execute(
                select(Manager).where(Manager.activation_token == clean_token)
            )
            manager = result.scalar_one_or_none()
            if not manager or manager.is_deleted:
                raise AppException(message="Invitation token is invalid or has expired.", status_code=status.HTTP_400_BAD_REQUEST)
            if manager.status != "INVITED":
                raise AppException(message="This invitation has already been accepted.", status_code=status.HTTP_400_BAD_REQUEST)
            now = datetime.now(timezone.utc)
            expires_at = manager.activation_token_expires_at
            if expires_at:
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)
                if now > expires_at:
                    raise AppException(message="This invitation token has expired.", status_code=status.HTTP_400_BAD_REQUEST)

            company_name = "Our Company"
            if manager.company_id:
                comp_res = await self.session.execute(select(Company).where(Company.id == manager.company_id))
                comp_obj = comp_res.scalar_one_or_none()
                if comp_obj:
                    company_name = comp_obj.name

            return {
                "valid": True,
                "first_name": manager.first_name,
                "last_name": manager.last_name,
                "email": manager.personal_email,
                "department": manager.department,
                "designation": manager.designation,
                "company_name": company_name,
                "status": manager.status,
            }
        except AppException:
            raise
        except SQLAlchemyError as exc:
            logger.exception("get_onboarding_token_status: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def validate_onboarding_token(self, token: str) -> dict:
        clean_token = token.strip() if token else ""
        logger.info("validate_onboarding_token: request | token_prefix=%s", clean_token[:8] if clean_token else "N/A")
        if not clean_token:
            raise AppException(
                message="Invitation token is required.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        try:
            from sqlalchemy import select
            from app.models.manager import Manager
            from app.models.company import Company
            
            result = await self.session.execute(
                select(Manager).where(Manager.activation_token == clean_token)
            )
            manager = result.scalar_one_or_none()

            if not manager or manager.is_deleted:
                logger.warning("validate_onboarding_token: token not found or manager deleted")
                raise AppException(
                    message="Invitation token is invalid or expired.",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            if manager.status != "INVITED":
                logger.warning(
                    "validate_onboarding_token: wrong status | manager_id=%s | status=%s",
                    manager.manager_id, manager.status,
                )
                raise AppException(
                    message="Invitation has already been accepted.",
                    status_code=status.HTTP_409_CONFLICT,
                )

            now = datetime.now(timezone.utc)
            expires_at = manager.activation_token_expires_at
            if expires_at:
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)
                if now > expires_at:
                    logger.warning(
                        "validate_onboarding_token: token expired | manager_id=%s | expired_at=%s",
                        manager.manager_id, expires_at.isoformat(),
                    )
                    raise AppException(
                        message="Invitation token has expired.",
                        status_code=status.HTTP_410_GONE,
                    )

            company_name = "OFC360"
            if manager.company_id:
                comp_res = await self.session.execute(select(Company.name).where(Company.id == manager.company_id))
                c_name = comp_res.scalar_one_or_none()
                if c_name:
                    company_name = c_name

            logger.info(
                "validate_onboarding_token: valid | manager_id=%s | email=%s",
                manager.manager_id, manager.personal_email[:3] + "***",
            )
            return {
                "id": str(manager.id),
                "manager_id": manager.manager_id,
                "first_name": manager.first_name,
                "last_name": manager.last_name,
                "name": f"{manager.first_name} {manager.last_name}".strip(),
                "personal_email": manager.personal_email,
                "company_email": manager.company_email,
                "email": manager.company_email or manager.personal_email,
                "phone": manager.phone,
                "department": manager.department,
                "designation": manager.designation,
                "company_name": company_name,
                "role": manager.role or "manager",
                "status": manager.status,
                "joining_date": manager.joining_date.isoformat() if manager.joining_date else None,
            }
        except AppException:
            raise
        except Exception as exc:
            logger.exception("validate_onboarding_token: error", exc_info=exc)
            raise DatabaseException() from exc

    async def activate_onboarding_manager(self, payload: ActivateManagerOnboardingRequest) -> dict:
        clean_token = payload.token.strip() if payload.token else ""
        logger.info("activate_onboarding_manager: request | token_prefix=%s", clean_token[:8] if clean_token else "N/A")
        if not clean_token:
            raise AppException(
                message="Invitation token is required.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        try:
            from sqlalchemy import select, func, update as sa_update
            from app.models.manager import Manager
            from app.models.employee import Employee
            from app.models.user import User
            from app.core.security import hash_password
            from app.services.token_service import TokenService

            result = await self.session.execute(
                select(Manager).where(Manager.activation_token == clean_token)
            )
            manager = result.scalar_one_or_none()

            if not manager or manager.is_deleted:
                logger.warning("activate_onboarding_manager: invalid token | token_prefix=%s", clean_token[:8] if clean_token else "N/A")
                raise AppException(
                    message="Invitation token is invalid or expired.",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            if manager.status != "INVITED":
                logger.warning("activate_onboarding_manager: wrong status | status=%s", manager.status)
                raise AppException(
                    message="Invitation has already been accepted.",
                    status_code=status.HTTP_409_CONFLICT,
                )

            now = datetime.now(timezone.utc)
            expires_at = manager.activation_token_expires_at
            if expires_at:
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)
                if now > expires_at:
                    logger.warning("activate_onboarding_manager: token expired | manager_id=%s", manager.manager_id)
                    raise AppException(
                        message="Invitation token has expired.",
                        status_code=status.HTTP_410_GONE,
                    )

            password = payload.password
            if (
                len(password) < 8 or
                not any(c.isupper() for c in password) or
                not any(c.islower() for c in password) or
                not any(c.isdigit() for c in password) or
                not any(not c.isalnum() for c in password)
            ):
                logger.warning("activate_onboarding_manager: weak password | manager_id=%s", manager.manager_id)
                raise AppException(
                    message="Password must be at least 8 characters long and contain at least 1 uppercase letter, 1 lowercase letter, 1 number, and 1 special character.",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            password_hash = hash_password(password)

            # Clean phone
            phone_to_use = payload.phone or manager.phone
            clean_phone = "".join(filter(str.isdigit, phone_to_use)) if phone_to_use else ""
            if len(clean_phone) > 10:
                clean_phone = clean_phone[-10:]

            # Resolve or create active User
            user = None
            if manager.user_id:
                u_res = await self.session.execute(select(User).where(User.id == manager.user_id))
                user = u_res.scalar_one_or_none()

            if not user:
                target_email = manager.personal_email.lower().strip()
                email_check = await self.session.execute(
                    select(User).where(
                        (func.lower(User.email) == target_email) |
                        (func.lower(User.email) == (manager.company_email or target_email).lower().strip())
                    )
                )
                user = email_check.scalar_one_or_none()

            db_role = getattr(UserRole, manager.role.upper(), UserRole.MANAGER) if hasattr(UserRole, manager.role.upper()) else UserRole.MANAGER

            if user:
                user.password_hash = password_hash
                user.is_active = True
                user.is_verified = True
                user.email_verified_at = now
                user.must_change_password = False
                if clean_phone:
                    user.phone = clean_phone
                if not user.role or user.role == UserRole.EMPLOYEE:
                    user.role = db_role
            else:
                user = User(
                    company_id=manager.company_id,
                    name=f"{manager.first_name} {manager.last_name}".strip(),
                    email=manager.personal_email.lower().strip(),
                    phone=clean_phone or manager.phone,
                    password_hash=password_hash,
                    is_active=True,
                    is_verified=True,
                    role=db_role,
                    email_verified_at=now,
                    onboarding_completed=False,
                )
                self.session.add(user)

            await self.session.flush()

            # Link user to manager, transition status, delete token
            manager.user_id = user.id
            manager.status = "ACTIVE"
            manager.is_active = True
            manager.activation_token = None
            manager.activation_token_expires_at = None

            if payload.phone:
                manager.phone = payload.phone
            if payload.profile_photo_url:
                manager.profile_photo_url = payload.profile_photo_url

            # Also update synchronized Employee record
            await self.session.execute(
                sa_update(Employee).where(
                    (Employee.id == manager.id) | (Employee.personal_email == manager.personal_email)
                ).values(
                    user_id=user.id,
                    status="ACTIVE",
                    is_active=True,
                    activation_token=None,
                    activation_token_expires_at=None,
                    phone=manager.phone,
                    profile_photo_url=manager.profile_photo_url,
                )
            )

            # Emergency Contact
            if payload.emergency_contact_name and payload.emergency_contact_phone:
                from app.models.manager_emergency_contact import ManagerEmergencyContact
                ec = ManagerEmergencyContact(
                    manager_id=manager.id,
                    name=payload.emergency_contact_name,
                    relation="Emergency Contact",
                    phone=payload.emergency_contact_phone,
                )
                self.session.add(ec)

            await self.session.commit()
            logger.info("activate_onboarding_manager: committed | user_id=%s", user.id)

            # Welcome Email
            try:
                await self.email_service.send_manager_welcome_email(
                    email=manager.personal_email,
                    name=manager.first_name,
                    employee_id=manager.manager_id,
                )
            except Exception as welcome_exc:
                logger.error("activate_onboarding_manager: welcome email failed | manager_id=%s | error=%s", manager.manager_id, str(welcome_exc))

            # Auto login by generating tokens
            token_service = TokenService(session=self.session, auth_repository=self.auth_repo)
            access_token, refresh_token, expires_in = await token_service.generate_auth_tokens(
                user_id=user.id,
                role=user.role,
                company_id=user.company_id,
            )
            user_id_str = str(getattr(user, "id", manager.user_id or manager.id))
            user_name_str = getattr(user, "name", f"{manager.first_name} {manager.last_name}".strip())
            user_email_str = getattr(user, "email", manager.personal_email)
            user_role_str = getattr(user, "role", manager.role or "manager")
            comp_id_val = getattr(user, "company_id", manager.company_id)
            user_comp_str = str(comp_id_val) if comp_id_val else None

            return {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "token_type": "bearer",
                "user": {
                    "id": user_id_str,
                    "name": user_name_str,
                    "email": user_email_str,
                    "role": user_role_str,
                    "company_id": user_comp_str,
                    "is_verified": True,
                    "onboarding_completed": False,
                }
            }
        except AppException:
            await self.session.rollback()
            raise
        except Exception as exc:
            await self.session.rollback()
            logger.exception("activate_onboarding_manager: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def deactivate_manager(self, admin_id: uuid.UUID, manager_uuid: uuid.UUID) -> None:
        logger.info("deactivate_manager | admin_id=%s | manager_id=%s", admin_id, manager_uuid)
        try:
            manager = await self.repo.get_by_id_raw(manager_uuid)
            if not manager:
                raise AppException(message="Manager not found.", status_code=status.HTTP_404_NOT_FOUND)
            manager.is_active = False
            manager.deactivated_at = datetime.now(timezone.utc)
            manager.deactivated_by = admin_id
            manager.status = "DISABLED"
            await self.repo.update_status(manager_uuid, "DISABLED")
            from sqlalchemy import update as sa_update
            from app.models.employee import Employee
            await self.session.execute(
                sa_update(Employee).where(
                    (Employee.id == manager_uuid) | (Employee.personal_email == manager.personal_email)
                ).values(
                    is_active=False,
                    status="DISABLED",
                    deactivated_at=datetime.now(timezone.utc),
                    deactivated_by=admin_id,
                )
            )
            if manager.user_id:
                from app.models.user import User
                await self.session.execute(
                    sa_update(User).where(User.id == manager.user_id).values(
                        is_active=False,
                    )
                )
                await self.auth_repo.revoke_all_user_refresh_tokens(manager.user_id)
                await redis_client.revoke_user_tokens(manager.user_id)
            await self.session.commit()
            logger.info("deactivate_manager: success | manager_id=%s", manager_uuid)
        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("deactivate_manager: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def activate_manager_by_admin(self, admin_id: uuid.UUID, manager_uuid: uuid.UUID) -> None:
        logger.info("activate_manager_by_admin | admin_id=%s | manager_id=%s", admin_id, manager_uuid)
        try:
            manager = await self.repo.get_by_id_raw(manager_uuid)
            if not manager:
                raise AppException(message="Manager not found.", status_code=status.HTTP_404_NOT_FOUND)
            manager.is_active = True
            manager.deactivated_at = None
            manager.deactivated_by = None
            manager.deactivation_reason = None
            manager.status = "ACTIVE"
            await self.repo.update_status(manager_uuid, "ACTIVE")
            from sqlalchemy import update as sa_update
            from app.models.employee import Employee
            await self.session.execute(
                sa_update(Employee).where(
                    (Employee.id == manager_uuid) | (Employee.personal_email == manager.personal_email)
                ).values(
                    is_active=True,
                    status="ACTIVE",
                    deactivated_at=None,
                    deactivated_by=None,
                )
            )
            if manager.user_id:
                from app.models.user import User
                await self.session.execute(
                    sa_update(User).where(User.id == manager.user_id).values(
                        is_active=True,
                    )
                )
            await self.session.commit()
            logger.info("activate_manager_by_admin: success | manager_id=%s", manager_uuid)
        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("activate_manager_by_admin: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def complete_manager_onboarding(
        self, user_uuid: uuid.UUID, payload: ManagerOnboardingCompleteRequest
    ) -> ManagerResponse:
        logger.info("complete_manager_onboarding | user_id=%s", user_uuid)
        try:
            manager = await self.repo.get_by_user_id(user_uuid)
            if not manager:
                raise AppException(message="Manager profile not found.", status_code=status.HTTP_404_NOT_FOUND)
            
            # Update basic and onboarding columns on Manager
            manager.first_name = payload.first_name.strip()
            manager.last_name = payload.last_name.strip()
            manager.phone = payload.phone.strip()
            manager.department = payload.department.strip()
            manager.designation = payload.designation.strip()
            manager.manager_id = payload.manager_id.strip()
            manager.office_location = payload.office_location
            manager.branch = payload.office_location
            manager.reporting_to = payload.reporting_to
            manager.joining_date = payload.joining_date
            manager.avatar = payload.avatar
            manager.profile_photo_url = payload.avatar
            manager.bio = payload.bio
            manager.timezone = payload.timezone
            manager.language = payload.language
            manager.is_first_login = False
            manager.profile_completed = True
            
            # Update emergency contact
            if payload.emergency_contact_name and payload.emergency_contact_phone:
                from app.models.manager_emergency_contact import ManagerEmergencyContact
                from sqlalchemy import delete as sa_delete
                # delete existing contacts first
                await self.session.execute(
                    sa_delete(ManagerEmergencyContact).where(ManagerEmergencyContact.manager_id == manager.id)
                )
                ec = ManagerEmergencyContact(
                    manager_id=manager.id,
                    name=payload.emergency_contact_name.strip(),
                    relation="Emergency Contact",
                    phone=payload.emergency_contact_phone.strip(),
                )
                self.session.add(ec)

            # Update linked User
            user = await self.auth_repo.get_user_by_id(user_uuid)
            if user:
                user.name = f"{payload.first_name} {payload.last_name}".strip()
                user.phone = payload.phone
                user.onboarding_completed = True
                user.first_login = False
                if payload.password:
                    user.password_hash = hash_password(payload.password)

            await self.session.commit()
            logger.info("complete_manager_onboarding: success | manager_id=%s", manager.id)
            full_manager = await self.repo.get_by_id(manager.id)
            return ManagerResponse.model_validate(full_manager)
        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("complete_manager_onboarding: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def get_manager_by_user_id(self, user_uuid: uuid.UUID) -> ManagerResponse:
        try:
            manager = await self.repo.get_by_user_id(user_uuid)
            if not manager:
                raise AppException(message="Manager profile not found.", status_code=status.HTTP_404_NOT_FOUND)
            return ManagerResponse.model_validate(manager)
        except AppException:
            raise
        except SQLAlchemyError as exc:
            logger.exception("get_manager_by_user_id: db error", exc_info=exc)
            raise DatabaseException() from exc



async def get_manager_service(
    session: AsyncSession = Depends(get_db_session),
    email_service: EmailService = Depends(get_email_service),
) -> ManagerService:
    return ManagerService(
        session=session,
        manager_repository=ManagerRepository(session),
        auth_repository=AuthRepository(session),
        email_service=email_service,
    )
