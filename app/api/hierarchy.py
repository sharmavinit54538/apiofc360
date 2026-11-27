"""FastAPI router for the Employee Hierarchy module."""

from __future__ import annotations

import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import and_, select
from sqlalchemy.orm import load_only, noload

from app.core.exceptions import AppException, BadRequestException, ForbiddenException, NotFoundException
from app.core.rbac import (
    normalize_operational_role,
    reject_super_admin_operational_access,
    require_admin_or_manager,
    require_tenant_admin_or_manager,
    require_tenant_employee_or_above,
    require_tenant_hr_admin,
)
from app.middleware.auth import get_current_user_claims, get_current_user_claims_optional
from app.models.employee import Employee
from app.models.user import User
from app.repositories.hierarchy_repository import _HIERARCHY_EMPLOYEE_COLUMNS
from app.schemas.auth import APIResponse
from app.schemas.hierarchy import (
    AssignManagerRequest,
    ChangeManagerRequest,
    HierarchyAnalyticsResponse,
    HierarchyNodeResponse,
    HierarchyTreeResponse,
    OrganizationChartNode,
    ReportingChainResponse,
    ReportingPathResponse,
)
from app.services.hierarchy_service import HierarchyService, get_hierarchy_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/hierarchy", tags=["Employee Hierarchy"])


def _get_company_id(claims: dict | None) -> uuid.UUID:
    """Extract and validate the company_id from JWT claims. Raises 403 if missing."""
    if not claims or not isinstance(claims, dict):
        raise AppException(
            message="Your account is not associated with a company.",
            status_code=status.HTTP_403_FORBIDDEN,
        )
    raw = claims.get("company_id")
    if not raw:
        raise AppException(
            message="Your account is not associated with a company.",
            status_code=status.HTTP_403_FORBIDDEN,
        )
    try:
        return uuid.UUID(str(raw))
    except ValueError:
        raise AppException(
            message="Invalid company association in token.",
            status_code=status.HTTP_403_FORBIDDEN,
        )


def _get_company_id_safe(claims: dict | None) -> uuid.UUID | None:
    """Safely extract company_id from claims without throwing exceptions."""
    if not claims or not isinstance(claims, dict):
        return None
    raw = claims.get("company_id")
    if not raw:
        return None
    try:
        return uuid.UUID(str(raw))
    except (ValueError, TypeError):
        return None


async def _get_is_super_admin(
    user_uuid_raw: Any,
    claims: dict | None,
    service: HierarchyService,
) -> bool:
    """Super Admin never receives operational hierarchy access."""
    return False


async def get_current_employee(claims: dict | None, service: HierarchyService) -> Employee | None:
    """Helper to fetch the current user's Employee record without loading encrypted PII."""
    if not claims or "sub" not in claims:
        return None
    try:
        user_uuid = uuid.UUID(str(claims["sub"]))
        company_uuid = _get_company_id_safe(claims)
        if not company_uuid:
            return None
        stmt = (
            select(Employee)
            .where(
                and_(
                    Employee.user_id == user_uuid,
                    Employee.company_id == company_uuid,
                    Employee.is_deleted == False,  # noqa: E712
                )
            )
            .options(load_only(*_HIERARCHY_EMPLOYEE_COLUMNS))
        )
        res = await service.session.execute(stmt)
        return res.scalar_one_or_none()
    except Exception:
        return None


async def check_access_to_employee(
    current_user_id: uuid.UUID,
    target_employee_id: uuid.UUID,
    claims: dict,
    service: HierarchyService,
) -> Employee:
    """Enforce tenant isolation and RBAC boundaries for viewing employee hierarchy details."""
    role = reject_super_admin_operational_access(claims)
    company_uuid = _get_company_id(claims)

    # Load target employee strictly within caller's company using safe hierarchy columns only
    target_emp = await service.repo.get_employee_by_id(target_employee_id, company_id=company_uuid)
    if not target_emp or target_emp.company_id != company_uuid:
        raise NotFoundException("Employee not found.")

    # Admin / HR / Executive roles within tenant
    if role in {"hr_admin", "executive"}:
        return target_emp

    # Load caller's employee record within tenant
    caller_emp = await get_current_employee(claims, service)
    if not caller_emp:
        raise ForbiddenException("Access denied: employee profile is required.")

    if caller_emp.id == target_employee_id:
        return target_emp

    if role == "manager":
        is_subordinate = await service.repo.is_subordinate(
            caller_emp.id,
            target_employee_id,
            company_id=company_uuid,
        )
        if is_subordinate:
            return target_emp

    raise ForbiddenException(
        "Access denied: you may only view reporting hierarchy details for yourself or your reporting team."
    )


def _strip_salary_from_node(node: Any, allow_salary: bool) -> Any:
    if allow_salary or node is None:
        return node
    if hasattr(node, "ctc"):
        node.ctc = None
    if hasattr(node, "children") and node.children:
        for child in node.children:
            _strip_salary_from_node(child, False)
    return node


@router.get(
    "",
    response_model=APIResponse[list[HierarchyTreeResponse]],
    summary="Get complete organization tree",
)
async def get_hierarchy(
    department: str | None = Query(None),
    designation: str | None = Query(None),
    location: str | None = Query(None),
    employment_type: str | None = Query(None),
    reporting_manager_id: str | None = Query(None),
    search: str | None = Query(None),
    claims: Annotated[dict, Depends(require_tenant_employee_or_above)] = None,
    service: Annotated[HierarchyService, Depends(get_hierarchy_service)] = None,
) -> APIResponse[list[HierarchyTreeResponse]]:
    """Return nested organization hierarchy tree scoped to tenant and caller role."""
    role = reject_super_admin_operational_access(claims)
    company_uuid = _get_company_id(claims)
    allow_salary = role in {"hr_admin", "executive"}

    root_id = None
    if role not in {"hr_admin", "executive"}:
        caller_emp = await get_current_employee(claims, service)
        if not caller_emp:
            return APIResponse(
                success=True,
                message="Organization tree fetched successfully.",
                data=[],
                errors=None,
            )
        root_id = caller_emp.id

    tree = await service.build_tree(
        company_id=company_uuid,
        root_manager_id=root_id,
        department=department,
        designation=designation,
        location=location,
        employment_type=employment_type,
        reporting_manager_id=reporting_manager_id,
        search=search,
        include_salary=allow_salary,
    )
    return APIResponse(
        success=True,
        message="Organization tree fetched successfully.",
        data=tree,
        errors=None,
    )


@router.get(
    "/tree",
    response_model=APIResponse[list[HierarchyTreeResponse]],
    summary="Get nested hierarchy tree JSON",
)
async def get_hierarchy_tree(
    department: str | None = Query(None),
    designation: str | None = Query(None),
    location: str | None = Query(None),
    employment_type: str | None = Query(None),
    reporting_manager_id: str | None = Query(None),
    search: str | None = Query(None),
    claims: Annotated[dict, Depends(require_tenant_employee_or_above)] = None,
    service: Annotated[HierarchyService, Depends(get_hierarchy_service)] = None,
) -> APIResponse[list[HierarchyTreeResponse]]:
    """Alias endpoint for nested hierarchy tree JSON."""
    return await get_hierarchy(
        department=department,
        designation=designation,
        location=location,
        employment_type=employment_type,
        reporting_manager_id=reporting_manager_id,
        search=search,
        claims=claims,
        service=service,
    )


@router.get(
    "/chart",
    response_model=APIResponse[list[OrganizationChartNode]],
    summary="Get hierarchy flat list optimized for React Flow",
)
async def get_hierarchy_chart(
    department: str | None = Query(None),
    designation: str | None = Query(None),
    location: str | None = Query(None),
    employment_type: str | None = Query(None),
    reporting_manager_id: str | None = Query(None),
    search: str | None = Query(None),
    claims: Annotated[dict, Depends(require_tenant_employee_or_above)] = None,
    service: Annotated[HierarchyService, Depends(get_hierarchy_service)] = None,
) -> APIResponse[list[OrganizationChartNode]]:
    """Get flat representation of employee relationships optimized for rendering React Flow charts."""
    role = reject_super_admin_operational_access(claims)
    company_uuid = _get_company_id(claims)
    allow_salary = role in {"hr_admin", "executive"}

    root_id = None
    if role not in {"hr_admin", "executive"}:
        caller_emp = await get_current_employee(claims, service)
        if not caller_emp:
            return APIResponse(
                success=True,
                message="React Flow chart data fetched successfully.",
                data=[],
                errors=None,
            )
        root_id = caller_emp.id

    chart = await service.get_flat_chart(
        company_id=company_uuid,
        root_manager_id=root_id,
        department=department,
        designation=designation,
        location=location,
        employment_type=employment_type,
        reporting_manager_id=reporting_manager_id,
        search=search,
        include_salary=allow_salary,
    )
    return APIResponse(
        success=True,
        message="React Flow chart data fetched successfully.",
        data=chart,
        errors=None,
    )


@router.get(
    "/analytics",
    response_model=APIResponse[HierarchyAnalyticsResponse],
    summary="Get hierarchy analytics metrics",
)
async def get_analytics(
    claims: Annotated[dict, Depends(require_tenant_admin_or_manager)],
    service: Annotated[HierarchyService, Depends(get_hierarchy_service)],
) -> APIResponse[HierarchyAnalyticsResponse]:
    """Retrieve aggregate team size, levels depth, vacant positions, etc."""
    reject_super_admin_operational_access(claims)
    company_uuid = _get_company_id(claims)
    analytics = await service.get_analytics(company_uuid)
    return APIResponse(
        success=True,
        message="Hierarchy analytics calculated successfully.",
        data=analytics,
        errors=None,
    )


@router.get(
    "/{employee_id}",
    response_model=APIResponse[ReportingChainResponse],
    summary="Get employee reporting chain details",
)
async def get_employee_hierarchy_details(
    employee_id: uuid.UUID,
    claims: Annotated[dict, Depends(require_tenant_employee_or_above)],
    service: Annotated[HierarchyService, Depends(get_hierarchy_service)],
) -> APIResponse[ReportingChainResponse]:
    """Fetch manager, peers, direct reports, reporting chain, and organizational level for an employee."""
    role = reject_super_admin_operational_access(claims)
    user_uuid = uuid.UUID(claims["sub"])
    company_uuid = _get_company_id(claims)

    # Enforce RBAC security and reuse preloaded target employee
    target_emp = await check_access_to_employee(user_uuid, employee_id, claims, service)
    effective_company_id = target_emp.company_id or company_uuid

    details = await service.get_employee_reporting_details(
        employee_id,
        effective_company_id,
        preloaded_employee=target_emp,
        include_salary=(role in {"hr_admin", "executive"}),
    )
    return APIResponse(
        success=True,
        message="Reporting details fetched successfully.",
        data=details,
        errors=None,
    )


@router.get(
    "/path/{employee_id}",
    response_model=APIResponse[ReportingPathResponse],
    summary="Get reporting path from CEO down to employee",
)
async def get_reporting_path(
    employee_id: uuid.UUID,
    claims: Annotated[dict, Depends(require_tenant_employee_or_above)],
    service: Annotated[HierarchyService, Depends(get_hierarchy_service)],
) -> APIResponse[ReportingPathResponse]:
    """Return visual list showing hierarchy levels path, e.g. CEO -> Vice President -> Employee."""
    role = reject_super_admin_operational_access(claims)
    user_uuid = uuid.UUID(claims["sub"])
    company_uuid = _get_company_id(claims)

    # Enforce RBAC security and reuse preloaded target employee
    emp = await check_access_to_employee(user_uuid, employee_id, claims, service)

    # Fetch ancestors (top-down) within same company
    ancestors = await service.repo.get_recursive_ancestors(employee_id, company_id=company_uuid)

    full_path = ancestors + [emp]
    allow_salary = role in {"hr_admin", "executive"}
    path_nodes = [
        _strip_salary_from_node(HierarchyNodeResponse.model_validate(x), allow_salary)
        for x in full_path
    ]

    # Format the path string using ↓ separator
    names = [f"{x.first_name} {x.last_name} ({x.designation})" for x in full_path]
    formatted = " \u2193 ".join(names)

    data = ReportingPathResponse(path=path_nodes, formatted_path=formatted)
    return APIResponse(
        success=True,
        message="Reporting path generated successfully.",
        data=data,
        errors=None,
    )


@router.put(
    "/assign-manager",
    response_model=APIResponse[HierarchyNodeResponse],
    summary="Assign reporting manager",
)
async def assign_manager(
    payload: AssignManagerRequest,
    claims: Annotated[dict, Depends(require_tenant_hr_admin)],
    service: Annotated[HierarchyService, Depends(get_hierarchy_service)],
) -> APIResponse[HierarchyNodeResponse]:
    """Set employee manager, executing circular references and active manager validations. Admin/HR only."""
    user_uuid = uuid.UUID(claims["sub"])
    company_uuid = _get_company_id(claims)
    emp = await service.assign_manager(
        payload.employee_id,
        payload.manager_id,
        user_uuid,
        company_id=company_uuid,
    )

    return APIResponse(
        success=True,
        message="Manager assigned successfully.",
        data=HierarchyNodeResponse.model_validate(emp),
        errors=None,
    )


@router.put(
    "/change-manager",
    response_model=APIResponse[HierarchyNodeResponse],
    summary="Transfer reporting manager",
)
async def change_manager(
    payload: ChangeManagerRequest,
    claims: Annotated[dict, Depends(require_tenant_hr_admin)],
    service: Annotated[HierarchyService, Depends(get_hierarchy_service)],
) -> APIResponse[HierarchyNodeResponse]:
    """Change employee reporting manager. Admin/HR only."""
    user_uuid = uuid.UUID(claims["sub"])
    company_uuid = _get_company_id(claims)
    emp = await service.change_manager(
        payload.employee_id,
        payload.new_manager_id,
        user_uuid,
        company_id=company_uuid,
    )

    return APIResponse(
        success=True,
        message="Manager transferred successfully.",
        data=HierarchyNodeResponse.model_validate(emp),
        errors=None,
    )


@router.delete(
    "/remove-manager/{employee_id}",
    response_model=APIResponse[HierarchyNodeResponse],
    summary="Remove manager link",
)
async def remove_manager(
    employee_id: uuid.UUID,
    claims: Annotated[dict, Depends(require_tenant_hr_admin)],
    service: Annotated[HierarchyService, Depends(get_hierarchy_service)],
) -> APIResponse[HierarchyNodeResponse]:
    """Remove employee's manager (orphaning or upgrading employee to top level). Admin/HR only."""
    user_uuid = uuid.UUID(claims["sub"])
    company_uuid = _get_company_id(claims)
    emp = await service.remove_manager(
        employee_id,
        user_uuid,
        company_id=company_uuid,
    )

    return APIResponse(
        success=True,
        message="Manager removed successfully.",
        data=HierarchyNodeResponse.model_validate(emp),
        errors=None,
    )


@router.get(
    "/direct-reports/{manager_id}",
    response_model=APIResponse[list[HierarchyNodeResponse]],
    summary="List direct reports of a manager",
)
async def get_direct_reports(
    manager_id: uuid.UUID,
    claims: Annotated[dict, Depends(require_tenant_employee_or_above)],
    service: Annotated[HierarchyService, Depends(get_hierarchy_service)],
) -> APIResponse[list[HierarchyNodeResponse]]:
    """List direct reports of a manager. Subject to caller view boundaries."""
    role = reject_super_admin_operational_access(claims)
    user_uuid = uuid.UUID(claims["sub"])
    company_uuid = _get_company_id(claims)

    # Enforce RBAC security
    await check_access_to_employee(user_uuid, manager_id, claims, service)

    reports = await service.repo.get_direct_reports(manager_id, company_id=company_uuid)
    allow_salary = role in {"hr_admin", "executive"}
    data = [
        _strip_salary_from_node(HierarchyNodeResponse.model_validate(r), allow_salary)
        for r in reports
    ]
    return APIResponse(
        success=True,
        message="Direct reports fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/team/{manager_id}",
    response_model=APIResponse[list[HierarchyNodeResponse]],
    summary="List recursive team descendants of a manager",
)
async def get_team(
    manager_id: uuid.UUID,
    claims: Annotated[dict, Depends(require_tenant_employee_or_above)],
    service: Annotated[HierarchyService, Depends(get_hierarchy_service)],
) -> APIResponse[list[HierarchyNodeResponse]]:
    """List all descendants (entire direct + indirect team) of a manager. Subject to caller view boundaries."""
    role = reject_super_admin_operational_access(claims)
    user_uuid = uuid.UUID(claims["sub"])
    company_uuid = _get_company_id(claims)

    # Enforce RBAC security
    await check_access_to_employee(user_uuid, manager_id, claims, service)

    team = await service.repo.get_recursive_descendants(manager_id, company_id=company_uuid)
    allow_salary = role in {"hr_admin", "executive"}
    data = [
        _strip_salary_from_node(HierarchyNodeResponse.model_validate(t), allow_salary)
        for t in team
    ]
    return APIResponse(
        success=True,
        message="Recursive team descendants fetched successfully.",
        data=data,
        errors=None,
    )
