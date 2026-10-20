"""Users and Employee Profile service separating auth identity from HR employee profile."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset.asset import Asset
from app.models.document.company import CompanyDocument
from app.models.employee import Employee
from app.models.user import User
from app.schemas.core_modules.users_profile import ProfileUpdateRequest, UserUpdateRequest

logger = logging.getLogger(__name__)


class UsersProfileService:
    """Service handling account users and HR employee profiles."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Users (Auth / Account Identity) ────────────────────────────────────────

    async def list_users(
        self,
        company_id: Optional[uuid.UUID] = None,
        role: Optional[str] = None,
        page: int = 1,
        limit: int = 20,
    ) -> Dict[str, Any]:
        stmt = select(User).where(User.is_deleted == False)
        if company_id:
            stmt = stmt.where(User.company_id == company_id)
        if role:
            stmt = stmt.where(User.role.ilike(role))

        total = (await self.session.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
        stmt = stmt.order_by(desc(User.created_at)).offset((page - 1) * limit).limit(limit)
        items = (await self.session.execute(stmt)).scalars().all()

        return {
            "total": total,
            "page": page,
            "limit": limit,
            "items": [
                {
                    "id": str(u.id),
                    "email": u.email,
                    "name": u.name,
                    "phone": u.phone,
                    "role": u.role,
                    "is_active": u.is_active,
                    "is_verified": u.is_verified,
                    "account_status": getattr(u, "account_status", "ACTIVE"),
                    "created_at": u.created_at.isoformat() if u.created_at else None,
                }
                for u in items
            ],
        }

    async def get_user_by_id(self, user_id: uuid.UUID) -> Optional[User]:
        stmt = select(User).where(User.id == user_id, User.is_deleted == False)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def update_user(self, user_id: uuid.UUID, payload: UserUpdateRequest) -> User:
        user = await self.get_user_by_id(user_id)
        if not user:
            raise ValueError("User not found")

        if payload.name is not None:
            user.name = payload.name
        if payload.email is not None:
            user.email = payload.email
        if payload.phone is not None:
            user.phone = payload.phone
        if payload.role is not None:
            user.role = payload.role
        if payload.is_active is not None:
            user.is_active = payload.is_active
        if payload.account_status is not None:
            user.account_status = payload.account_status

        await self.session.commit()
        await self.session.refresh(user)
        return user

    # ── Employee Profile (HR Details) ──────────────────────────────────────────

    async def get_profile_by_user_id(self, user_id: uuid.UUID) -> Optional[Employee]:
        stmt = select(Employee).where(Employee.user_id == user_id, Employee.is_deleted == False)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def update_profile(self, user_id: uuid.UUID, payload: ProfileUpdateRequest) -> Employee:
        emp = await self.get_profile_by_user_id(user_id)
        if not emp:
            raise ValueError("Employee profile not found")

        if payload.first_name is not None:
            emp.first_name = payload.first_name
        if payload.last_name is not None:
            emp.last_name = payload.last_name
        if payload.phone is not None:
            emp.phone = payload.phone
        if payload.alternate_phone is not None:
            emp.alternate_phone = payload.alternate_phone
        if payload.personal_email is not None:
            emp.personal_email = payload.personal_email
        if payload.marital_status is not None:
            emp.marital_status = payload.marital_status
        if payload.blood_group is not None:
            emp.blood_group = payload.blood_group
        if payload.work_location is not None:
            emp.work_location = payload.work_location
        if payload.work_mode is not None:
            emp.work_mode = payload.work_mode

        await self.session.commit()
        await self.session.refresh(emp)
        return emp

    async def get_profile_documents(self, employee_id: uuid.UUID) -> List[Dict[str, Any]]:
        stmt = select(CompanyDocument).where(CompanyDocument.is_deleted == False).limit(10)
        docs = (await self.session.execute(stmt)).scalars().all()
        return [
            {
                "id": str(d.id),
                "title": d.title,
                "file_name": d.file_name,
                "file_size": d.file_size,
                "status": d.status,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in docs
        ]

    async def get_profile_assets(self, employee_id: uuid.UUID, company_id: Optional[uuid.UUID] = None) -> List[Dict[str, Any]]:
        if not company_id:
            return []
        stmt = select(Asset).where(Asset.employee_id == employee_id, Asset.company_id == company_id)
        assets = (await self.session.execute(stmt)).scalars().all()
        return [
            {
                "id": str(a.id),
                "tag": a.tag,
                "name": a.name,
                "category": a.category,
                "status": a.status,
                "assigned_at": a.assigned_at.isoformat() if a.assigned_at else None,
            }
            for a in assets
        ]

    async def get_profile_activity(self, user_id: uuid.UUID) -> List[Dict[str, Any]]:
        return [
            {"event": "User logged in", "timestamp": "2026-09-27T08:30:00Z", "ip": "127.0.0.1"},
            {"event": "Checked in for attendance", "timestamp": "2026-09-27T08:31:00Z"},
            {"event": "Viewed pay component statement", "timestamp": "2026-09-26T16:20:00Z"},
        ]
