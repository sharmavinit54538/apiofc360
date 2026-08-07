"""Manager repository layer: direct database operations for the Manager module."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.manager import Manager
from app.models.manager_address import ManagerAddress
from app.models.manager_document import ManagerDocument
from app.models.manager_education import ManagerEducation
from app.models.manager_emergency_contact import ManagerEmergencyContact
from app.models.manager_experience import ManagerExperience
from app.models.manager_skill import ManagerSkill

logger = logging.getLogger(__name__)


class ManagerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _active_filter(self):
        return Manager.is_deleted == False  # noqa: E712

    def _with_relations(self):
        return [
            selectinload(Manager.addresses),
            selectinload(Manager.documents),
            selectinload(Manager.education),
            selectinload(Manager.experience),
            selectinload(Manager.skills),
            selectinload(Manager.emergency_contacts),
            selectinload(Manager.reporting_manager),
        ]

    async def create_manager(self, **kwargs: Any) -> Manager:
        manager = Manager(**kwargs)
        self.session.add(manager)
        await self.session.flush()
        return manager

    async def get_by_id(self, manager_uuid: uuid.UUID) -> Manager | None:
        result = await self.session.execute(
            select(Manager)
            .where(and_(Manager.id == manager_uuid, self._active_filter()))
            .options(*self._with_relations())
        )
        return result.scalar_one_or_none()

    async def get_by_user_id(self, user_uuid: uuid.UUID) -> Manager | None:
        result = await self.session.execute(
            select(Manager)
            .where(and_(Manager.user_id == user_uuid, self._active_filter()))
            .options(*self._with_relations())
        )
        return result.scalar_one_or_none()

    async def get_by_id_raw(self, manager_uuid: uuid.UUID) -> Manager | None:
        result = await self.session.execute(
            select(Manager).where(Manager.id == manager_uuid)
        )
        return result.scalar_one_or_none()

    async def get_by_manager_id(self, manager_id: str) -> Manager | None:
        result = await self.session.execute(
            select(Manager)
            .where(and_(Manager.manager_id == manager_id, self._active_filter()))
            .execution_options(bypass_tenant=True)
        )
        return result.scalar_one_or_none()

    async def get_by_personal_email(self, email: str) -> Manager | None:
        result = await self.session.execute(
            select(Manager)
            .where(and_(Manager.personal_email == email.lower(), self._active_filter()))
            .execution_options(bypass_tenant=True)
        )
        return result.scalar_one_or_none()

    async def get_by_company_email(self, email: str) -> Manager | None:
        result = await self.session.execute(
            select(Manager)
            .where(and_(Manager.company_email == email.lower(), self._active_filter()))
            .execution_options(bypass_tenant=True)
        )
        return result.scalar_one_or_none()

    async def get_by_phone(self, phone: str) -> Manager | None:
        result = await self.session.execute(
            select(Manager)
            .where(and_(Manager.phone == phone, self._active_filter()))
            .execution_options(bypass_tenant=True)
        )
        return result.scalar_one_or_none()

    async def get_by_activation_token(self, token: str) -> Manager | None:
        result = await self.session.execute(
            select(Manager).where(Manager.activation_token == token)
        )
        return result.scalar_one_or_none()

    async def list_managers(
        self,
        department: str | None = None,
        status: str | None = None,
        employment_type: str | None = None,
        search: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Manager]:
        stmt = select(Manager).where(self._active_filter()).options(selectinload(Manager.reporting_manager))

        if department:
            stmt = stmt.where(Manager.department.ilike(f"%{department}%"))
        if status:
            stmt = stmt.where(Manager.status == status.upper())
        if employment_type:
            stmt = stmt.where(Manager.employment_type == employment_type.upper())
        if search:
            pattern = f"%{search}%"
            stmt = stmt.where(
                or_(
                    Manager.first_name.ilike(pattern),
                    Manager.last_name.ilike(pattern),
                    (Manager.first_name + " " + Manager.last_name).ilike(pattern),
                    Manager.manager_id.ilike(pattern),
                    Manager.personal_email.ilike(pattern),
                    Manager.company_email.ilike(pattern),
                    Manager.phone.ilike(pattern),
                    Manager.designation.ilike(pattern),
                    Manager.department.ilike(pattern),
                    Manager.branch.ilike(pattern),
                )
            )

        stmt = stmt.order_by(Manager.created_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_managers(
        self,
        department: str | None = None,
        status: str | None = None,
        employment_type: str | None = None,
        search: str | None = None,
    ) -> int:
        stmt = select(func.count()).select_from(Manager).where(self._active_filter())

        if department:
            stmt = stmt.where(Manager.department.ilike(f"%{department}%"))
        if status:
            stmt = stmt.where(Manager.status == status.upper())
        if employment_type:
            stmt = stmt.where(Manager.employment_type == employment_type.upper())
        if search:
            pattern = f"%{search}%"
            stmt = stmt.where(
                or_(
                    Manager.first_name.ilike(pattern),
                    Manager.last_name.ilike(pattern),
                    (Manager.first_name + " " + Manager.last_name).ilike(pattern),
                    Manager.manager_id.ilike(pattern),
                    Manager.personal_email.ilike(pattern),
                    Manager.company_email.ilike(pattern),
                    Manager.phone.ilike(pattern),
                    Manager.designation.ilike(pattern),
                    Manager.department.ilike(pattern),
                    Manager.branch.ilike(pattern),
                )
            )

        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def update_manager(self, manager_uuid: uuid.UUID, **kwargs: Any) -> None:
        await self.session.execute(
            update(Manager).where(Manager.id == manager_uuid).values(**kwargs)
        )

    async def soft_delete(self, manager_uuid: uuid.UUID, deleted_by: uuid.UUID | None = None) -> None:
        import uuid as py_uuid
        manager = await self.get_by_id_raw(manager_uuid)
        if manager:
            new_email = f"del_{py_uuid.uuid4().hex[:8]}_{manager.personal_email}"
            if len(new_email) > 255:
                new_email = new_email[:255]
            new_mgr_id = f"del_{py_uuid.uuid4().hex[:6]}_{manager.manager_id}"
            if len(new_mgr_id) > 20:
                new_mgr_id = new_mgr_id[:20]
            new_phone = py_uuid.uuid4().hex[:10]
            
            await self.session.execute(
                update(Manager)
                .where(Manager.id == manager_uuid)
                .values(
                    is_deleted=True,
                    deleted_at=datetime.now(timezone.utc),
                    personal_email=new_email,
                    company_email=f"del_{py_uuid.uuid4().hex[:8]}_{manager.company_email or ''}"[:255],
                    manager_id=new_mgr_id,
                    phone=new_phone,
                )
            )

    async def update_status(self, manager_uuid: uuid.UUID, status: str) -> None:
        await self.session.execute(
            update(Manager)
            .where(Manager.id == manager_uuid)
            .values(status=status)
        )

    # ------------------------------------------------------------------
    # Address/Document/Education etc. Creators
    # ------------------------------------------------------------------

    async def upsert_address(self, manager_uuid: uuid.UUID, address_type: str, data: dict) -> ManagerAddress:
        result = await self.session.execute(
            select(ManagerAddress).where(
                and_(
                    ManagerAddress.manager_id == manager_uuid,
                    ManagerAddress.address_type == address_type,
                )
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            for k, v in data.items():
                setattr(existing, k, v)
            return existing
        addr = ManagerAddress(manager_id=manager_uuid, address_type=address_type, **data)
        self.session.add(addr)
        await self.session.flush()
        return addr

    async def create_document(self, manager_uuid: uuid.UUID, data: dict) -> ManagerDocument:
        obj = ManagerDocument(manager_id=manager_uuid, **data)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def create_education(self, manager_uuid: uuid.UUID, data: dict) -> ManagerEducation:
        obj = ManagerEducation(manager_id=manager_uuid, **data)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def create_experience(self, manager_uuid: uuid.UUID, data: dict) -> ManagerExperience:
        obj = ManagerExperience(manager_id=manager_uuid, **data)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def create_skill(self, manager_uuid: uuid.UUID, data: dict) -> ManagerSkill:
        obj = ManagerSkill(manager_id=manager_uuid, **data)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def create_emergency_contact(self, manager_uuid: uuid.UUID, data: dict) -> ManagerEmergencyContact:
        obj = ManagerEmergencyContact(manager_id=manager_uuid, **data)
        self.session.add(obj)
        await self.session.flush()
        return obj
