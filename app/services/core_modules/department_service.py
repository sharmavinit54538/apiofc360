"""Department service implementing hierarchical department management and employee associations."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.department import Department
from app.models.employee import Employee
from app.schemas.core_modules.departments import DepartmentCreateRequest, DepartmentUpdateRequest

logger = logging.getLogger(__name__)


class DepartmentCoreService:
    """Service handling hierarchical departments, soft deletes, and employee lookups."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_departments(
        self,
        company_id: Optional[uuid.UUID] = None,
        parent_id: Optional[uuid.UUID] = None,
        page: int = 1,
        limit: int = 50,
    ) -> Dict[str, Any]:
        stmt = select(Department).where(Department.is_deleted == False)
        if company_id:
            stmt = stmt.where(Department.company_id == company_id)
        if parent_id is not None:
            stmt = stmt.where(Department.parent_department_id == parent_id)

        total = (await self.session.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
        stmt = stmt.order_by(Department.department_name).offset((page - 1) * limit).limit(limit)
        items = (await self.session.execute(stmt)).scalars().all()

        return {
            "total": total,
            "page": page,
            "limit": limit,
            "items": [
                {
                    "id": str(d.id),
                    "department_name": d.department_name,
                    "department_code": d.department_code,
                    "description": d.description,
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
        stmt = select(Department).where(Department.id == department_id, Department.is_deleted == False)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def create_department(
        self, company_id: Optional[uuid.UUID], payload: DepartmentCreateRequest
    ) -> Department:
        dept = Department(
            id=uuid.uuid4(),
            company_id=company_id,
            department_name=payload.department_name,
            department_code=payload.department_code,
            description=payload.description,
            manager_id=payload.manager_id,
            parent_department_id=payload.parent_department_id,
            location=payload.location,
            cost_center=payload.cost_center,
            budget=payload.budget,
            status="Active",
            is_deleted=False,
        )
        self.session.add(dept)
        await self.session.commit()
        await self.session.refresh(dept)
        return dept

    async def update_department(
        self, department_id: uuid.UUID, payload: DepartmentUpdateRequest
    ) -> Department:
        dept = await self.get_department(department_id)
        if not dept:
            raise ValueError("Department not found")

        if payload.department_name is not None:
            dept.department_name = payload.department_name
        if payload.department_code is not None:
            dept.department_code = payload.department_code
        if payload.description is not None:
            dept.description = payload.description
        if payload.manager_id is not None:
            dept.manager_id = payload.manager_id
        if payload.parent_department_id is not None:
            dept.parent_department_id = payload.parent_department_id
        if payload.location is not None:
            dept.location = payload.location
        if payload.cost_center is not None:
            dept.cost_center = payload.cost_center
        if payload.budget is not None:
            dept.budget = payload.budget
        if payload.status is not None:
            dept.status = payload.status

        await self.session.commit()
        await self.session.refresh(dept)
        return dept

    async def delete_department(self, department_id: uuid.UUID) -> bool:
        dept = await self.get_department(department_id)
        if not dept:
            return False
        dept.is_deleted = True
        dept.deleted_at = datetime.now(timezone.utc)
        await self.session.commit()
        return True

    async def get_department_employees(
        self,
        department_id: uuid.UUID,
        include_sub_departments: bool = False,
        page: int = 1,
        limit: int = 50,
    ) -> Dict[str, Any]:
        dept_ids = [department_id]

        if include_sub_departments:
            sub_stmt = select(Department.id).where(
                Department.parent_department_id == department_id,
                Department.is_deleted == False,
            )
            sub_res = await self.session.execute(sub_stmt)
            dept_ids.extend(sub_res.scalars().all())

        stmt = select(Employee).where(
            Employee.department_id.in_(dept_ids),
            Employee.is_deleted == False,
        )

        total = (await self.session.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
        stmt = stmt.offset((page - 1) * limit).limit(limit)
        employees = (await self.session.execute(stmt)).scalars().all()

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
