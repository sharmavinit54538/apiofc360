"""Department core module service: delegates all business logic to canonical DepartmentService and DepartmentRepository."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.department import Department
from app.repositories.department_repository import DepartmentRepository
from app.schemas.core_modules.departments import DepartmentCreateRequest, DepartmentUpdateRequest
from app.services.department_service import DepartmentService

logger = logging.getLogger(__name__)


class DepartmentCoreService:
    """Consolidated wrapper for hierarchical departments, soft deletes, and employee lookups.
    
    Delegates all operations to canonical DepartmentRepository and DepartmentService to maintain
    single source of truth and DRY business logic.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = DepartmentRepository(session)
        self.service = DepartmentService(session=session, department_repository=self.repo)

    async def list_departments(
        self,
        company_id: Optional[uuid.UUID] = None,
        parent_id: Optional[uuid.UUID] = None,
        page: int = 1,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """List active departments scoped to company and parent."""
        offset = max(0, (page - 1) * limit)
        items = await self.repo.list_departments(
            company_id=company_id,
            parent_id=parent_id,
            limit=limit,
            offset=offset,
        )
        total = await self.repo.count_departments(
            company_id=company_id,
            parent_id=parent_id,
        )

        return {
            "total": total,
            "page": page,
            "limit": limit,
            "items": [
                {
                    "id": str(d.id),
                    "department_name": d.department_name,
                    "department_code": d.department_code,
                    "description": d.description or "",
                    "manager_id": str(d.manager_id) if d.manager_id else None,
                    "parent_department_id": str(d.parent_department_id) if d.parent_department_id else None,
                    "location": d.location,
                    "status": d.status,
                    "is_deleted": d.is_deleted,
                    "created_at": d.created_at.isoformat() if d.created_at else None,
                }
                for d in items
            ],
        }

    async def get_department(self, department_id: uuid.UUID) -> Optional[Department]:
        """Retrieve department by ID."""
        return await self.repo.get_by_id(department_id)

    async def create_department(
        self, company_id: Optional[uuid.UUID], payload: DepartmentCreateRequest
    ) -> Department:
        """Create department via canonical service."""
        system_user_id = uuid.uuid4()
        resp = await self.service.create_department(user_id=system_user_id, payload=payload, company_id=company_id)
        dept = await self.repo.get_by_id(resp.id, company_id=company_id)
        if not dept:
            raise RuntimeError("Failed to retrieve created department.")
        return dept

    async def update_department(
        self, department_id: uuid.UUID, payload: DepartmentUpdateRequest
    ) -> Department:
        """Update department via canonical service."""
        system_user_id = uuid.uuid4()
        resp = await self.service.update_department(user_id=system_user_id, department_uuid=department_id, payload=payload)
        dept = await self.repo.get_by_id(resp.id)
        if not dept:
            raise RuntimeError("Failed to retrieve updated department.")
        return dept

    async def delete_department(self, department_id: uuid.UUID) -> bool:
        """Soft delete department via canonical service."""
        system_user_id = uuid.uuid4()
        try:
            await self.service.delete_department(user_id=system_user_id, department_uuid=department_id)
            return True
        except Exception as exc:
            logger.warning("delete_department failed for %s: %s", department_id, exc)
            return False

    async def get_department_employees(
        self,
        department_id: uuid.UUID,
        include_sub_departments: bool = False,
        page: int = 1,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """Retrieve paginated department employees, optionally including sub-departments."""
        employees, total = await self.repo.get_department_employees_paginated(
            department_uuid=department_id,
            include_sub_departments=include_sub_departments,
            page=page,
            limit=limit,
        )

        return {
            "department_id": str(department_id),
            "include_sub_departments": include_sub_departments,
            "total": total,
            "page": page,
            "limit": limit,
            "employees": [
                {
                    "id": str(e.id),
                    "first_name": e.first_name,
                    "last_name": e.last_name,
                    "email": e.company_email or e.personal_email,
                    "designation": e.designation,
                    "is_active": e.is_active,
                }
                for e in employees
            ],
        }
