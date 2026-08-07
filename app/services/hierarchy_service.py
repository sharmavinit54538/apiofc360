"""Hierarchy service: business logic, validations, and analytics calculations."""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from app.core.exceptions import BadRequestException, NotFoundException
from app.db.database import get_db_session
from app.models.employee import Employee
from app.models.hierarchy_audit import HierarchyAuditLog
from app.repositories.hierarchy_repository import HierarchyRepository
from app.schemas.hierarchy import (
    HierarchyAnalyticsResponse,
    HierarchyNodeResponse,
    HierarchyTreeResponse,
    OrganizationChartNode,
    ReportingChainResponse,
    ReportingPathResponse,
)

logger = logging.getLogger(__name__)


class HierarchyService:
    """Service layer coordinating hierarchy business logic and transactions."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = HierarchyRepository(session)

    def _make_node(
        self,
        emp,
        emp_lookup: dict | None = None,
        reporting_manager_name: str | None = None,
    ) -> HierarchyNodeResponse:
        """Build a HierarchyNodeResponse from an Employee ORM object.
        
        Populates all fields including computed reporting_manager_name.
        """
        # Resolve manager name if not already passed
        if reporting_manager_name is None and emp.manager_id:
            if emp_lookup and emp.manager_id in emp_lookup:
                m = emp_lookup[emp.manager_id]
                reporting_manager_name = f"{m.first_name} {m.last_name}".strip()

        return HierarchyNodeResponse(
            id=emp.id,
            employee_id=emp.employee_id,
            first_name=emp.first_name,
            last_name=emp.last_name,
            designation=emp.designation,
            department=emp.department,
            profile_photo_url=emp.profile_photo_url,
            role=emp.role,
            status=emp.status,
            branch=emp.branch,
            shift=emp.shift,
            employment_type=emp.employment_type,
            employment_status=emp.employment_status,
            joining_date=emp.joining_date,
            date_of_birth=emp.date_of_birth,
            ctc=emp.ctc,
            reporting_to=emp.manager_id,
            reporting_manager_name=reporting_manager_name,
        )

    def _matches_filter(
        self,
        emp,
        department: str | None = None,
        designation: str | None = None,
        location: str | None = None,
        employment_type: str | None = None,
        reporting_manager_id: str | None = None,
        search: str | None = None,
    ) -> bool:
        def norm(s):
            return (s or "").strip().lower()

        def norm_type(s):
            return (s or "").strip().lower().replace("_", " ").replace("-", " ")

        if search and search.strip():
            s = search.strip().lower()
            name = f"{emp.first_name or ''} {emp.last_name or ''}".strip().lower()
            emp_id = norm(emp.employee_id)
            dept = norm(emp.department)
            desig = norm(emp.designation)
            if s not in name and s not in emp_id and s not in dept and s not in desig:
                return False

        if department and department.strip() and department.strip().lower() != "all":
            if norm(emp.department) != norm(department):
                return False

        if designation and designation.strip() and designation.strip().lower() != "all":
            if norm(emp.designation) != norm(designation):
                return False

        if location and location.strip() and location.strip().lower() != "all":
            emp_loc = norm(emp.branch or getattr(emp, "location", None))
            if emp_loc != norm(location):
                return False

        if employment_type and employment_type.strip() and employment_type.strip().lower() != "all":
            if norm_type(emp.employment_type) != norm_type(employment_type):
                return False

        if reporting_manager_id and reporting_manager_id.strip() and reporting_manager_id.strip().lower() != "all":
            mgr_str = norm(reporting_manager_id)
            emp_id_str = str(emp.id).lower()
            mgr_id_str = str(emp.manager_id).lower() if emp.manager_id else ""
            if mgr_str != emp_id_str and mgr_str != mgr_id_str:
                return False

        return True

    async def build_tree(
        self,
        company_id: uuid.UUID | None,
        root_manager_id: uuid.UUID | None = None,
        department: str | None = None,
        designation: str | None = None,
        location: str | None = None,
        employment_type: str | None = None,
        reporting_manager_id: str | None = None,
        search: str | None = None,
    ) -> list[HierarchyTreeResponse]:
        """Fetch all employees and build a nested tree structure with optional filtering."""
        if root_manager_id:
            root_emp = await self.repo.get_employee_by_id(root_manager_id)
            if root_emp:
                descendants = await self.repo.get_recursive_descendants(root_manager_id)
                employees = [root_emp] + descendants
            else:
                employees = await self.repo.get_company_employees(company_id)
        else:
            employees = await self.repo.get_company_employees(company_id)

        # O(N) lookup for manager names
        emp_lookup = {emp.id: emp for emp in employees}

        # Build node map — including all new fields
        nodes = {}
        for emp in employees:
            m_name = None
            if emp.manager_id and emp.manager_id in emp_lookup:
                m = emp_lookup[emp.manager_id]
                m_name = f"{m.first_name} {m.last_name}".strip()

            nodes[emp.id] = HierarchyTreeResponse(
                id=emp.id,
                employee_id=emp.employee_id,
                first_name=emp.first_name,
                last_name=emp.last_name,
                designation=emp.designation,
                department=emp.department,
                profile_photo_url=emp.profile_photo_url,
                role=emp.role,
                status=emp.status,
                branch=emp.branch,
                shift=emp.shift,
                employment_type=emp.employment_type,
                employment_status=emp.employment_status,
                joining_date=emp.joining_date,
                date_of_birth=emp.date_of_birth,
                ctc=emp.ctc,
                reporting_to=emp.manager_id,
                reporting_manager_name=m_name,
                children=[],
            )

        roots = []
        for emp in employees:
            node = nodes[emp.id]
            # Root node conditions
            if root_manager_id and emp.id == root_manager_id:
                roots.append(node)
            elif not root_manager_id and (emp.manager_id is None or emp.manager_id not in nodes):
                roots.append(node)
            else:
                parent_id = emp.manager_id
                if parent_id in nodes:
                    nodes[parent_id].children.append(node)

        if not roots and nodes:
            roots = list(nodes.values())

        has_filters = any([department, designation, location, employment_type, reporting_manager_id, search])
        if not has_filters:
            return roots

        def filter_node_tree(node: HierarchyTreeResponse) -> HierarchyTreeResponse | None:
            emp_obj = emp_lookup.get(node.id)
            is_match = self._matches_filter(
                emp_obj, department, designation, location, employment_type, reporting_manager_id, search
            ) if emp_obj else True

            filtered_children = []
            for child in node.children:
                fc = filter_node_tree(child)
                if fc:
                    filtered_children.append(fc)

            if is_match or filtered_children:
                node.children = filtered_children
                return node
            return None

        filtered_roots = []
        for r in roots:
            fr = filter_node_tree(r)
            if fr:
                filtered_roots.append(fr)

        return filtered_roots

    async def get_flat_chart(
        self,
        company_id: uuid.UUID | None,
        root_manager_id: uuid.UUID | None = None,
        department: str | None = None,
        designation: str | None = None,
        location: str | None = None,
        employment_type: str | None = None,
        reporting_manager_id: str | None = None,
        search: str | None = None,
    ) -> list[OrganizationChartNode]:
        """Fetch hierarchy flat representation optimized for React Flow rendering with optional filtering."""
        if root_manager_id:
            root_emp = await self.repo.get_employee_by_id(root_manager_id)
            if root_emp:
                descendants = await self.repo.get_recursive_descendants(root_manager_id)
                employees = [root_emp] + descendants
            else:
                employees = await self.repo.get_company_employees(company_id)
        else:
            employees = await self.repo.get_company_employees(company_id)

        has_filters = any([department, designation, location, employment_type, reporting_manager_id, search])
        if has_filters:
            employees = [
                emp for emp in employees
                if self._matches_filter(
                    emp, department, designation, location, employment_type, reporting_manager_id, search
                )
            ]

        # O(N) lookup tables for team sizes and manager names
        subordinates = {emp.id: [] for emp in employees}
        emp_lookup = {emp.id: emp for emp in employees}
        for emp in employees:
            if emp.manager_id in subordinates:
                subordinates[emp.manager_id].append(emp.id)

        memo_team_size = {}

        def get_recursive_size(emp_uuid: uuid.UUID) -> int:
            if emp_uuid in memo_team_size:
                return memo_team_size[emp_uuid]
            size = 0
            for sub_id in subordinates.get(emp_uuid, []):
                size += 1 + get_recursive_size(sub_id)
            memo_team_size[emp_uuid] = size
            return size

        # Precompute sizes
        for emp in employees:
            get_recursive_size(emp.id)

        chart_nodes = []
        for emp in employees:
            manager_name = None
            if emp.manager_id:
                m_emp = emp_lookup.get(emp.manager_id)
                if not m_emp:
                    # Look up from database if not in current company subset
                    m_emp = await self.repo.get_employee_by_id_raw(emp.manager_id)
                if m_emp:
                    manager_name = f"{m_emp.first_name} {m_emp.last_name}".strip()

            chart_nodes.append(
                OrganizationChartNode(
                    id=str(emp.id),
                    parentId=str(emp.manager_id) if emp.manager_id else None,
                    name=f"{emp.first_name} {emp.last_name}".strip(),
                    designation=emp.designation,
                    department=emp.department,
                    avatar=emp.profile_photo_url,
                    status=emp.status,
                    role=emp.role,
                    branch=emp.branch,
                    shift=emp.shift,
                    manager=manager_name,
                    teamSize=memo_team_size.get(emp.id, 0),
                )
            )

        return chart_nodes

    async def assign_manager(
        self, employee_id: uuid.UUID, manager_id: uuid.UUID, updated_by: uuid.UUID
    ) -> Employee:
        """Assign reporting manager to an employee, performing all validations & logging audit."""
        employee = await self.repo.get_employee_by_id(employee_id)
        if not employee:
            raise NotFoundException("Employee not found.")

        # Business validations
        await self.validate_hierarchy(employee_id, manager_id)

        previous_manager_id = employee.manager_id

        # Skip update if manager is already assigned
        if previous_manager_id == manager_id:
            return employee

        # Log action info
        logger.info(
            "Assigning manager | employee=%s | manager=%s | updated_by=%s",
            employee_id,
            manager_id,
            updated_by,
        )

        # Apply updates to both manager_id and reporting_manager_id to keep schemas in sync
        employee.manager_id = manager_id
        employee.reporting_manager_id = manager_id

        # Insert audit log entry
        audit = HierarchyAuditLog(
            employee_id=employee_id,
            previous_manager_id=previous_manager_id,
            new_manager_id=manager_id,
            updated_by=updated_by,
        )
        await self.repo.create_audit_log(audit)

        # Commit changes
        await self.session.commit()
        return employee

    async def change_manager(
        self, employee_id: uuid.UUID, new_manager_id: uuid.UUID, updated_by: uuid.UUID
    ) -> Employee:
        """Transfer reporting manager. Syntactic sugar over assign_manager with explicit log contexts."""
        logger.info(
            "Transferring manager | employee=%s | new_manager=%s | updated_by=%s",
            employee_id,
            new_manager_id,
            updated_by,
        )
        return await self.assign_manager(employee_id, new_manager_id, updated_by)

    async def remove_manager(self, employee_id: uuid.UUID, updated_by: uuid.UUID) -> Employee:
        """Remove reporting manager (orphan node / top-level root transition)."""
        employee = await self.repo.get_employee_by_id(employee_id)
        if not employee:
            raise NotFoundException("Employee not found.")

        previous_manager_id = employee.manager_id
        if previous_manager_id is None:
            return employee

        logger.info(
            "Removing manager | employee=%s | previous_manager=%s | updated_by=%s",
            employee_id,
            previous_manager_id,
            updated_by,
        )

        # Apply null updates
        employee.manager_id = None
        employee.reporting_manager_id = None

        # Audit log entry
        audit = HierarchyAuditLog(
            employee_id=employee_id,
            previous_manager_id=previous_manager_id,
            new_manager_id=None,
            updated_by=updated_by,
        )
        await self.repo.create_audit_log(audit)

        # Commit
        await self.session.commit()
        return employee

    async def get_reporting_chain(self, employee_id: uuid.UUID) -> list[Employee]:
        """Fetch recursive managers list starting from direct manager up to root."""
        return await self.repo.get_recursive_ancestors(employee_id)

    async def get_team(self, manager_id: uuid.UUID) -> list[Employee]:
        """Fetch all recursive descendants reporting to this manager."""
        return await self.repo.get_recursive_descendants(manager_id)

    async def detect_cycle(self, employee_id: uuid.UUID, manager_id: uuid.UUID) -> bool:
        """Return True if assigning manager_id to employee_id creates a circular loop."""
        return await self.repo.detect_cycle(employee_id, manager_id)

    async def validate_hierarchy(self, employee_id: uuid.UUID, manager_id: uuid.UUID) -> None:
        """Execute all business validation rules before assigning a manager."""
        if employee_id == manager_id:
            logger.warning("Validation error: Self-reporting attempt | employee=%s", employee_id)
            raise BadRequestException("Employee cannot report to themselves.")

        # Load employee
        employee = await self.repo.get_employee_by_id(employee_id)
        if not employee:
            raise NotFoundException("Employee not found.")

        # Load manager
        manager = await self.repo.get_employee_by_id_raw(manager_id)
        if not manager:
            raise NotFoundException("Proposed manager not found.")

        # Check soft-deletion
        if manager.is_deleted:
            logger.warning("Validation error: Manager is soft-deleted | manager=%s", manager_id)
            raise BadRequestException("Soft deleted employee cannot become manager.")

        # Check status active
        if manager.status != "ACTIVE":
            logger.warning("Validation error: Manager is inactive | manager=%s | status=%s", manager_id, manager.status)
            raise BadRequestException("Inactive employee cannot become manager.")

        # Check company alignment
        if employee.company_id != manager.company_id:
            logger.warning(
                "Validation error: Company mismatch | employee=%s (company=%s) | manager=%s (company=%s)",
                employee_id,
                employee.company_id,
                manager_id,
                manager.company_id,
            )
            raise BadRequestException("Manager must belong to the same company.")

        # Check cycle loop (cannot report to subordinate)
        if await self.repo.detect_cycle(employee_id, manager_id):
            logger.warning(
                "Validation error: Cycle detected | employee=%s | manager=%s",
                employee_id,
                manager_id,
            )
            raise BadRequestException(
                "Circular hierarchy detected: Employee cannot report to their subordinate."
            )

    async def calculate_depth(self, company_id: uuid.UUID) -> int:
        """Calculate the max levels in the hierarchy tree."""
        return await self.repo.get_hierarchy_depth(company_id)

    async def calculate_team_size(self, manager_id: uuid.UUID) -> int:
        """Calculate direct reports count + recursive reports."""
        descendants = await self.repo.get_recursive_descendants(manager_id)
        return len(descendants)

    async def get_analytics(self, company_id: uuid.UUID) -> HierarchyAnalyticsResponse:
        """Compute complete hierarchy analytics in O(N) runtime."""
        employees = await self.repo.get_company_employees(company_id)

        total_employees = len(employees)
        if total_employees == 0:
            return HierarchyAnalyticsResponse(
                total_employees=0,
                managers_count=0,
                hierarchy_levels=0,
                average_team_size=0.0,
                largest_team=0,
                employees_without_manager=0,
                vacant_positions=await self.repo.get_vacant_positions(company_id),
                hierarchy_depth=0,
            )

        # Build adjacency maps
        subordinates = {emp.id: [] for emp in employees}
        for emp in employees:
            if emp.manager_id in subordinates:
                subordinates[emp.manager_id].append(emp.id)

        # Count how many have direct reports
        managers_count = sum(1 for emp in employees if len(subordinates[emp.id]) > 0)

        # Compute recursive sizes using memoized search
        memo_team_size = {}

        def get_recursive_size(emp_uuid: uuid.UUID) -> int:
            if emp_uuid in memo_team_size:
                return memo_team_size[emp_uuid]
            size = 0
            for sub_id in subordinates.get(emp_uuid, []):
                size += 1 + get_recursive_size(sub_id)
            memo_team_size[emp_uuid] = size
            return size

        # Largest team (direct + recursive)
        largest_team = 0
        for emp in employees:
            sz = get_recursive_size(emp.id)
            if sz > largest_team:
                largest_team = sz

        # Average team size (total subordinates / managers_count)
        employees_with_manager = sum(1 for emp in employees if emp.manager_id is not None)
        average_team_size = (
            float(employees_with_manager) / float(managers_count) if managers_count > 0 else 0.0
        )

        # Compute level depths for each node
        depths = {}
        roots = [
            emp.id
            for emp in employees
            if emp.manager_id is None or emp.manager_id not in subordinates
        ]

        def compute_depth(emp_uuid: uuid.UUID, current_depth: int):
            depths[emp_uuid] = current_depth
            for sub_id in subordinates.get(emp_uuid, []):
                compute_depth(sub_id, current_depth + 1)

        for r_id in roots:
            compute_depth(r_id, 1)

        hierarchy_depth = max(depths.values()) if depths else 0

        # Vacant Positions
        vacant_positions = await self.repo.get_vacant_positions(company_id)

        return HierarchyAnalyticsResponse(
            total_employees=total_employees,
            managers_count=managers_count,
            hierarchy_levels=hierarchy_depth,
            average_team_size=average_team_size,
            largest_team=largest_team,
            employees_without_manager=len(roots),
            vacant_positions=vacant_positions,
            hierarchy_depth=hierarchy_depth,
        )

    async def get_employee_reporting_details(
        self, employee_uuid: uuid.UUID, company_id: uuid.UUID
    ) -> ReportingChainResponse:
        """Fetch employee direct details, manager, peers, direct reports, reporting chain and level."""
        employee = await self.repo.get_employee_by_id(employee_uuid)
        if not employee or employee.company_id != company_id:
            raise NotFoundException("Employee not found.")

        # Fetch manager
        manager = None
        manager_name = None
        if employee.manager_id:
            manager = await self.repo.get_employee_by_id(employee.manager_id)
            if manager:
                manager_name = f"{manager.first_name} {manager.last_name}".strip()

        peers = await self.repo.get_peers(employee_uuid, employee.manager_id)
        direct_reports = await self.repo.get_direct_reports(employee_uuid)
        reporting_chain = await self.repo.get_recursive_ancestors(employee_uuid)

        # Build emp_lookup for resolving manager names in related employees
        all_related = ([manager] if manager else []) + list(peers) + list(direct_reports) + list(reporting_chain)
        emp_lookup = {e.id: e for e in all_related if e}

        # Organization Level (depth from top root manager)
        level = len(reporting_chain) + 1

        def _node(emp, override_manager_name: str | None = None) -> HierarchyNodeResponse:
            """Build HierarchyNodeResponse with all fields populated."""
            m_name = override_manager_name
            if m_name is None and emp.manager_id and emp.manager_id in emp_lookup:
                m = emp_lookup[emp.manager_id]
                m_name = f"{m.first_name} {m.last_name}".strip()
            return HierarchyNodeResponse(
                id=emp.id,
                employee_id=emp.employee_id,
                first_name=emp.first_name,
                last_name=emp.last_name,
                designation=emp.designation,
                department=emp.department,
                profile_photo_url=emp.profile_photo_url,
                role=emp.role,
                status=emp.status,
                branch=emp.branch,
                shift=emp.shift,
                employment_type=emp.employment_type,
                employment_status=emp.employment_status,
                joining_date=emp.joining_date,
                date_of_birth=emp.date_of_birth,
                ctc=emp.ctc,
                reporting_to=emp.manager_id,
                reporting_manager_name=m_name,
            )

        return ReportingChainResponse(
            employee=_node(employee, override_manager_name=manager_name),
            manager=_node(manager) if manager else None,
            peers=[_node(p) for p in peers],
            direct_reports=[_node(d) for d in direct_reports],
            reporting_chain=[_node(r) for r in reporting_chain],
            organization_level=level,
        )


async def get_hierarchy_service(
    session: AsyncSession = Depends(get_db_session),
) -> HierarchyService:
    """Dependency injection provider for HierarchyService."""
    return HierarchyService(session=session)
