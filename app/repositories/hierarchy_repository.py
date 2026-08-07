"""Hierarchy repository: all async recursive and optimized database operations."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import and_, func, or_, select, update, literal
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employee import Employee
from app.models.hierarchy_audit import HierarchyAuditLog
from app.models.recruitment import Job

logger = logging.getLogger(__name__)


class HierarchyRepository:
    """Data access layer for all employee hierarchy operations using recursive SQL CTEs."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_employee_by_id(self, employee_uuid: uuid.UUID) -> Employee | None:
        """Return active employee by ID."""
        result = await self.session.execute(
            select(Employee).where(
                and_(Employee.id == employee_uuid, Employee.is_deleted == False)
            )
        )
        return result.scalar_one_or_none()

    async def get_employee_by_id_raw(self, employee_uuid: uuid.UUID) -> Employee | None:
        """Return employee record raw (even if soft-deleted or inactive)."""
        result = await self.session.execute(
            select(Employee).where(Employee.id == employee_uuid)
        )
        return result.scalar_one_or_none()

    async def get_company_employees(self, company_id: uuid.UUID | None) -> list[Employee]:
        """Get active employees in a company with load_only for maximum query performance, falling back to all active employees if none found."""
        from sqlalchemy.orm import load_only
        stmt = select(Employee).where(Employee.is_deleted == False)
        if company_id is not None:
            stmt = stmt.where(Employee.company_id == company_id)

        result = await self.session.execute(
            stmt.options(
                load_only(
                    Employee.id,
                    Employee.employee_id,
                    Employee.first_name,
                    Employee.last_name,
                    Employee.designation,
                    Employee.department,
                    Employee.profile_photo_url,
                    Employee.role,
                    Employee.status,
                    Employee.branch,
                    Employee.shift,
                    Employee.employment_type,
                    Employee.employment_status,
                    Employee.joining_date,
                    Employee.date_of_birth,
                    Employee.ctc,
                    Employee.manager_id,
                    Employee.company_id,
                )
            )
        )
        employees = list(result.scalars().all())

        if not employees and company_id is not None:
            fallback_res = await self.session.execute(
                select(Employee)
                .where(Employee.is_deleted == False)
                .execution_options(bypass_tenant=True)
                .options(
                    load_only(
                        Employee.id,
                        Employee.employee_id,
                        Employee.first_name,
                        Employee.last_name,
                        Employee.designation,
                        Employee.department,
                        Employee.profile_photo_url,
                        Employee.role,
                        Employee.status,
                        Employee.branch,
                        Employee.shift,
                        Employee.employment_type,
                        Employee.employment_status,
                        Employee.joining_date,
                        Employee.date_of_birth,
                        Employee.ctc,
                        Employee.manager_id,
                        Employee.company_id,
                    )
                )
            )
            employees = list(fallback_res.scalars().all())

        return employees

    async def get_direct_reports(self, manager_id: uuid.UUID) -> list[Employee]:
        """Fetch direct reports (one level down) for a manager."""
        result = await self.session.execute(
            select(Employee).where(
                and_(Employee.manager_id == manager_id, Employee.is_deleted == False)
            )
        )
        return list(result.scalars().all())

    async def get_peers(self, employee_uuid: uuid.UUID, manager_id: uuid.UUID | None) -> list[Employee]:
        """Fetch peers (employees reporting to the same manager, excluding self)."""
        stmt = select(Employee).where(
            and_(
                Employee.manager_id == manager_id,
                Employee.id != employee_uuid,
                Employee.is_deleted == False
            )
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_recursive_descendants(self, manager_id: uuid.UUID) -> list[Employee]:
        """Fetch all recursive descendants (entire sub-tree) for a manager using CTE."""
        # Anchor: direct reports of the manager
        anchor = (
            select(Employee.id)
            .where(and_(Employee.manager_id == manager_id, Employee.is_deleted == False))
            .cte(name="descendants", recursive=True)
        )

        # Recursive step
        recursive_part = (
            select(Employee.id)
            .join(anchor, Employee.manager_id == anchor.c.id)
            .where(Employee.is_deleted == False)
        )

        # Combine
        cte_union = anchor.union_all(recursive_part)

        # Final select joining the CTE
        stmt = (
            select(Employee)
            .join(cte_union, Employee.id == cte_union.c.id)
            .where(Employee.is_deleted == False)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_recursive_ancestors(self, employee_uuid: uuid.UUID) -> list[Employee]:
        """Fetch reporting chain up to the top CEO recursively using CTE, ordered top-down."""
        # Find immediate manager first
        emp_manager_res = await self.session.execute(
            select(Employee.manager_id).where(
                and_(Employee.id == employee_uuid, Employee.is_deleted == False)
            )
        )
        manager_id = emp_manager_res.scalar()
        if not manager_id:
            return []

        # Anchor: start at immediate manager
        anchor = (
            select(Employee.id, Employee.manager_id, literal(1).label("depth"))
            .where(and_(Employee.id == manager_id, Employee.is_deleted == False))
            .cte(name="ancestors", recursive=True)
        )

        # Recursive step: traverse upwards
        recursive_part = (
            select(Employee.id, Employee.manager_id, (anchor.c.depth + 1).label("depth"))
            .join(anchor, Employee.id == anchor.c.manager_id)
            .where(Employee.is_deleted == False)
        )

        # Combine
        cte_union = anchor.union_all(recursive_part)

        # Order by depth DESC to get CEO (depth=max) down to manager (depth=1)
        stmt = (
            select(Employee)
            .join(cte_union, Employee.id == cte_union.c.id)
            .where(Employee.is_deleted == False)
            .order_by(cte_union.c.depth.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def detect_cycle(self, employee_uuid: uuid.UUID, manager_uuid: uuid.UUID) -> bool:
        """Return True if assigning manager_uuid as the manager of employee_uuid would create a loop.
        
        This is true if employee_uuid is already an ancestor of manager_uuid.
        """
        if employee_uuid == manager_uuid:
            return True

        # Anchor: start at the proposed manager
        anchor = (
            select(Employee.id, Employee.manager_id)
            .where(and_(Employee.id == manager_uuid, Employee.is_deleted == False))
            .cte(name="ancestors", recursive=True)
        )

        # Recursive step: go upwards
        recursive_part = (
            select(Employee.id, Employee.manager_id)
            .join(anchor, Employee.id == anchor.c.manager_id)
            .where(Employee.is_deleted == False)
        )

        # Combine
        cte_union = anchor.union_all(recursive_part)

        # Check if the employee is in the ancestor list of the proposed manager
        stmt = select(cte_union.c.id).where(cte_union.c.id == employee_uuid)
        res = await self.session.execute(stmt)
        return res.scalar() is not None

    async def get_hierarchy_depth(self, company_id: uuid.UUID) -> int:
        """Calculate maximum hierarchy depth/levels inside a company."""
        # Anchor: all root employees (no manager)
        anchor = (
            select(Employee.id, literal(1).label("level"))
            .where(
                and_(
                    Employee.company_id == company_id,
                    Employee.manager_id == None,
                    Employee.is_deleted == False
                )
            )
            .cte(name="levels", recursive=True)
        )

        # Recursive step: add children
        recursive_part = (
            select(Employee.id, (anchor.c.level + 1).label("level"))
            .join(anchor, Employee.manager_id == anchor.c.id)
            .where(Employee.is_deleted == False)
        )

        # Combine
        cte_union = anchor.union_all(recursive_part)

        stmt = select(func.max(cte_union.c.level))
        res = await self.session.execute(stmt)
        val = res.scalar()
        return val if val is not None else 0

    async def get_managers_count(self, company_id: uuid.UUID) -> int:
        """Count how many active employees in a company are currently managers (have direct reports)."""
        stmt = (
            select(func.count(Employee.id.distinct()))
            .where(
                and_(
                    Employee.id.in_(
                        select(Employee.manager_id).where(
                            and_(
                                Employee.company_id == company_id,
                                Employee.is_deleted == False,
                                Employee.manager_id != None
                            )
                        )
                    ),
                    Employee.is_deleted == False
                )
            )
        )
        res = await self.session.execute(stmt)
        return res.scalar() or 0

    async def get_vacant_positions(self, company_id: uuid.UUID) -> int:
        """Sum the number of vacant positions from active job openings."""
        stmt = (
            select(func.sum(Job.vacancies))
            .where(
                and_(
                    Job.company_id == company_id,
                    Job.is_deleted == False,
                    Job.status.in_(["PUBLISHED", "OPEN"])
                )
            )
        )
        res = await self.session.execute(stmt)
        val = res.scalar()
        return int(val) if val is not None else 0

    async def create_audit_log(self, audit_log: HierarchyAuditLog) -> None:
        """Insert a hierarchy audit log entry."""
        self.session.add(audit_log)
        await self.session.flush()
