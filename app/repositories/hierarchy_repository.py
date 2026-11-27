"""Hierarchy repository: all async recursive and optimized database operations."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import and_, func, or_, select, update, literal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.models.employee import Employee
from app.models.hierarchy_audit import HierarchyAuditLog
from app.models.recruitment import Job

logger = logging.getLogger(__name__)

# Strict safe column projection for hierarchy queries: excludes encrypted national IDs
# so org charts and reporting chains never decrypt or leak PAN/Aadhaar/UAN/Passport/Voter ID.
_HIERARCHY_EMPLOYEE_COLUMNS = (
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
    Employee.reporting_manager_id,
    Employee.company_id,
    Employee.user_id,
    Employee.is_deleted,
)


class HierarchyRepository:
    """Data access layer for all employee hierarchy operations using recursive SQL CTEs."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_employee_by_id(
        self,
        employee_uuid: uuid.UUID,
        company_id: uuid.UUID | None = None,
    ) -> Employee | None:
        """Return active employee by ID within optional tenant scope without decrypting PII."""
        conditions = [Employee.id == employee_uuid, Employee.is_deleted == False]  # noqa: E712
        if company_id is not None:
            conditions.append(Employee.company_id == company_id)
        result = await self.session.execute(
            select(Employee)
            .where(and_(*conditions))
            .options(load_only(*_HIERARCHY_EMPLOYEE_COLUMNS))
        )
        return result.scalar_one_or_none()

    async def get_employee_by_id_raw(
        self,
        employee_uuid: uuid.UUID,
        company_id: uuid.UUID | None = None,
    ) -> Employee | None:
        """Return employee record raw (even if soft-deleted or inactive) without PII columns."""
        conditions = [Employee.id == employee_uuid]
        if company_id is not None:
            conditions.append(Employee.company_id == company_id)
        result = await self.session.execute(
            select(Employee)
            .where(and_(*conditions))
            .options(load_only(*_HIERARCHY_EMPLOYEE_COLUMNS))
        )
        return result.scalar_one_or_none()

    async def get_company_employees(self, company_id: uuid.UUID) -> list[Employee]:
        """Get active employees strictly scoped to a single company with load_only."""
        if company_id is None:
            raise ValueError("company_id is required for tenant-scoped hierarchy queries.")

        stmt = (
            select(Employee)
            .where(Employee.company_id == company_id)
            .where(Employee.is_deleted == False)  # noqa: E712
            .options(load_only(*_HIERARCHY_EMPLOYEE_COLUMNS))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    def _effective_manager_expr():
        return func.coalesce(Employee.reporting_manager_id, Employee.manager_id)

    async def get_direct_reports(
        self,
        manager_id: uuid.UUID,
        company_id: uuid.UUID | None = None,
    ) -> list[Employee]:
        """Fetch direct reports (one level down) for a manager within tenant boundary."""
        from sqlalchemy import or_

        conditions = [
            or_(Employee.reporting_manager_id == manager_id, Employee.manager_id == manager_id),
            Employee.is_deleted == False,  # noqa: E712
        ]
        if company_id is not None:
            conditions.append(Employee.company_id == company_id)
        result = await self.session.execute(
            select(Employee)
            .where(and_(*conditions))
            .options(load_only(*_HIERARCHY_EMPLOYEE_COLUMNS))
        )
        return list(result.scalars().all())

    async def get_peers(
        self,
        employee_uuid: uuid.UUID,
        manager_id: uuid.UUID | None,
        company_id: uuid.UUID | None = None,
    ) -> list[Employee]:
        """Fetch peers (employees reporting to the same manager, excluding self)."""
        if manager_id is None:
            return []
        from sqlalchemy import or_

        conditions = [
            or_(Employee.reporting_manager_id == manager_id, Employee.manager_id == manager_id),
            Employee.id != employee_uuid,
            Employee.is_deleted == False,  # noqa: E712
        ]
        if company_id is not None:
            conditions.append(Employee.company_id == company_id)
        stmt = (
            select(Employee)
            .where(and_(*conditions))
            .options(load_only(*_HIERARCHY_EMPLOYEE_COLUMNS))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_recursive_descendants(
        self,
        manager_id: uuid.UUID,
        company_id: uuid.UUID | None = None,
        max_depth: int = 50,
    ) -> list[Employee]:
        """Fetch all recursive descendants for a manager using cycle-bounded CTE."""
        from sqlalchemy import or_

        anchor_conds = [
            or_(Employee.reporting_manager_id == manager_id, Employee.manager_id == manager_id),
            Employee.is_deleted == False,  # noqa: E712
            Employee.id != manager_id,
        ]
        if company_id is not None:
            anchor_conds.append(Employee.company_id == company_id)

        anchor = (
            select(Employee.id, literal(1).label("depth"))
            .where(and_(*anchor_conds))
            .cte(name="descendants", recursive=True)
        )

        rec_conds = [
            Employee.is_deleted == False,  # noqa: E712
            anchor.c.depth < max_depth,
            Employee.id != manager_id,
        ]
        if company_id is not None:
            rec_conds.append(Employee.company_id == company_id)

        recursive_part = (
            select(Employee.id, (anchor.c.depth + 1).label("depth"))
            .join(
                anchor,
                or_(Employee.reporting_manager_id == anchor.c.id, Employee.manager_id == anchor.c.id),
            )
            .where(and_(*rec_conds))
        )

        cte_union = anchor.union(recursive_part)

        stmt_conds = [Employee.is_deleted == False]  # noqa: E712
        if company_id is not None:
            stmt_conds.append(Employee.company_id == company_id)

        stmt = (
            select(Employee)
            .join(cte_union, Employee.id == cte_union.c.id)
            .where(and_(*stmt_conds))
            .options(load_only(*_HIERARCHY_EMPLOYEE_COLUMNS))
        )
        result = await self.session.execute(stmt)
        # Deduplicate while preserving order in case of diamond/pre-existing cycles
        seen: set[uuid.UUID] = set()
        out: list[Employee] = []
        for emp in result.scalars().all():
            if emp.id not in seen:
                seen.add(emp.id)
                out.append(emp)
        return out

    async def get_recursive_ancestors(
        self,
        employee_uuid: uuid.UUID,
        company_id: uuid.UUID | None = None,
        max_depth: int = 50,
    ) -> list[Employee]:
        """Fetch reporting chain up to top root recursively using depth-bounded CTE, top-down."""
        emp_conds = [Employee.id == employee_uuid, Employee.is_deleted == False]  # noqa: E712
        if company_id is not None:
            emp_conds.append(Employee.company_id == company_id)

        emp_manager_res = await self.session.execute(
            select(self._effective_manager_expr()).where(and_(*emp_conds))
        )
        manager_id = emp_manager_res.scalar()
        if not manager_id or manager_id == employee_uuid:
            return []

        anchor_conds = [Employee.id == manager_id, Employee.is_deleted == False]  # noqa: E712
        if company_id is not None:
            anchor_conds.append(Employee.company_id == company_id)

        anchor = (
            select(
                Employee.id,
                self._effective_manager_expr().label("mgr_id"),
                literal(1).label("depth"),
            )
            .where(and_(*anchor_conds))
            .cte(name="ancestors", recursive=True)
        )

        rec_conds = [
            Employee.is_deleted == False,  # noqa: E712
            anchor.c.depth < max_depth,
            Employee.id != employee_uuid,
        ]
        if company_id is not None:
            rec_conds.append(Employee.company_id == company_id)

        recursive_part = (
            select(
                Employee.id,
                self._effective_manager_expr().label("mgr_id"),
                (anchor.c.depth + 1).label("depth"),
            )
            .join(anchor, Employee.id == anchor.c.mgr_id)
            .where(and_(*rec_conds))
        )

        cte_union = anchor.union(recursive_part)

        stmt_conds = [Employee.is_deleted == False]  # noqa: E712
        if company_id is not None:
            stmt_conds.append(Employee.company_id == company_id)

        stmt = (
            select(Employee)
            .join(cte_union, Employee.id == cte_union.c.id)
            .where(and_(*stmt_conds))
            .options(load_only(*_HIERARCHY_EMPLOYEE_COLUMNS))
            .order_by(cte_union.c.depth.desc())
        )
        result = await self.session.execute(stmt)
        seen: set[uuid.UUID] = set()
        chain: list[Employee] = []
        for anc in result.scalars().all():
            if anc.id not in seen:
                seen.add(anc.id)
                chain.append(anc)
        return chain

    async def detect_cycle(
        self,
        employee_uuid: uuid.UUID,
        manager_uuid: uuid.UUID,
        company_id: uuid.UUID | None = None,
        max_depth: int = 50,
    ) -> bool:
        """Return True if assigning manager_uuid as the manager of employee_uuid would create a loop."""
        if employee_uuid == manager_uuid:
            return True

        anchor_conds = [Employee.id == manager_uuid, Employee.is_deleted == False]  # noqa: E712
        if company_id is not None:
            anchor_conds.append(Employee.company_id == company_id)

        anchor = (
            select(
                Employee.id,
                self._effective_manager_expr().label("mgr_id"),
                literal(1).label("depth"),
            )
            .where(and_(*anchor_conds))
            .cte(name="ancestors", recursive=True)
        )

        rec_conds = [Employee.is_deleted == False, anchor.c.depth < max_depth]  # noqa: E712
        if company_id is not None:
            rec_conds.append(Employee.company_id == company_id)

        recursive_part = (
            select(
                Employee.id,
                self._effective_manager_expr().label("mgr_id"),
                (anchor.c.depth + 1).label("depth"),
            )
            .join(anchor, Employee.id == anchor.c.mgr_id)
            .where(and_(*rec_conds))
        )

        cte_union = anchor.union(recursive_part)
        stmt = select(cte_union.c.id).where(cte_union.c.id == employee_uuid).limit(1)
        res = await self.session.execute(stmt)
        return res.scalar() is not None

    async def is_subordinate(
        self,
        manager_emp_id: uuid.UUID,
        target_emp_id: uuid.UUID,
        company_id: uuid.UUID | None = None,
    ) -> bool:
        """Return True if target_emp_id reports (directly or transitively) to manager_emp_id."""
        if manager_emp_id == target_emp_id:
            return False
        return await self.detect_cycle(manager_emp_id, target_emp_id, company_id=company_id)

    async def get_hierarchy_depth(self, company_id: uuid.UUID, max_depth: int = 50) -> int:
        """Calculate maximum hierarchy depth/levels inside a company."""
        from sqlalchemy import or_

        anchor = (
            select(Employee.id, literal(1).label("level"))
            .where(
                and_(
                    Employee.company_id == company_id,
                    Employee.reporting_manager_id.is_(None),
                    Employee.manager_id.is_(None),
                    Employee.is_deleted == False,  # noqa: E712
                )
            )
            .cte(name="levels", recursive=True)
        )

        recursive_part = (
            select(Employee.id, (anchor.c.level + 1).label("level"))
            .join(
                anchor,
                or_(Employee.reporting_manager_id == anchor.c.id, Employee.manager_id == anchor.c.id),
            )
            .where(
                and_(
                    Employee.company_id == company_id,
                    Employee.is_deleted == False,  # noqa: E712
                    anchor.c.level < max_depth,
                )
            )
        )

        cte_union = anchor.union(recursive_part)
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
