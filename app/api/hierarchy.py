"""FastAPI router for the Employee Hierarchy module."""

from __future__ import annotations

import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import and_, select
from sqlalchemy.orm import load_only, noload

from app.core.exceptions import AppException, BadRequestException, ForbiddenException, NotFoundException
from app.core.rbac import require_admin_or_manager
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
    """Resolve immutable super_admin status without triggering User.company selectin."""
    if not user_uuid_raw:
        return False
    role = str(claims.get("role", "")).lower() if claims else ""
    if role != "super_admin":
        return False
    try:
        user_uuid = uuid.UUID(str(user_uuid_raw))
    except (ValueError, TypeError):
        return False
    res = await service.session.execute(
        select(User)
        .options(
            load_only(
                User.id,
                User.email,
                User.role,
                User.is_active,
                User.is_deleted,
                User.account_status,
            ),
            noload(User.company),
        )
        .where(User.id == user_uuid)
        .execution_options(bypass_tenant=True)
    )
    user = res.scalar_one_or_none()
    if not user or user.is_deleted or not user.is_active:
        return False
    if str(getattr(user, "account_status", "") or "").upper() != "ACTIVE":
        return False
    return bool(user.is_super_admin)


async def get_current_employee(claims: dict | None, service: HierarchyService) -> Employee | None:
    """Helper to fetch the current user's Employee record without loading encrypted PII."""
    if not claims or "sub" not in claims:
        return None
    try:
        user_uuid = uuid.UUID(str(claims["sub"]))
        company_uuid = _get_company_id_safe(claims)
        conditions = [Employee.user_id == user_uuid, Employee.is_deleted == False]
        if company_uuid is not None:
            conditions.append(Employee.company_id == company_uuid)
        stmt = (
            select(Employee)
            .where(and_(*conditions))
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
    role = str(claims.get("role", "")).lower() if claims else ""

    # 1. Lightweight Super Admin flag lookup (avoids User.company selectin query)
    is_super = await _get_is_super_admin(current_user_id, claims, service)
    company_uuid = None if is_super else _get_company_id_safe(claims)

    # Load target employee with safe hierarchy columns only
    target_emp = await service.repo.get_employee_by_id(target_employee_id)
    if not target_emp:
        raise NotFoundException("Employee not found.")

    if not is_super:
        if not company_uuid or target_emp.company_id != company_uuid:
            raise ForbiddenException("Access denied: cross-company hierarchy access is prohibited.")

    # 2. Admin / HR / Executive roles within tenant
    allowed_roles = {"super_admin", "hr_admin", "admin", "it_admin", "executive", "ceo", "cfo"}
    if is_super or role in allowed_roles:
        return target_emp

    # Load caller's employee record within tenant
    caller_emp = await get_current_employee(claims, service)
    if not caller_emp:
        raise ForbiddenException("Access denied: employee profile is required.")

    # 3. Self access or manager access to reporting subtree
    if caller_emp.id == target_employee_id:
        return target_emp

    if role == "manager":
        is_subordinate = await service.repo.detect_cycle(caller_emp.id, target_employee_id)
        if is_subordinate:
            return target_emp

    raise ForbiddenException(
        "Access denied: you may only view reporting hierarchy details for yourself or your reporting team."
    )


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
    claims: Annotated[dict | None, Depends(get_current_user_claims_optional)] = None,
    service: Annotated[HierarchyService, Depends(get_hierarchy_service)] = None,
) -> APIResponse[list[HierarchyTreeResponse]]:
    """Return nested organization hierarchy tree scoped to roles with optional filtering."""
    role = str(claims.get("role", "")).lower() if claims else ""
    user_uuid_raw = claims.get("sub") if claims else None
    is_super = await _get_is_super_admin(user_uuid_raw, claims, service)
    company_uuid = None if is_super else _get_company_id_safe(claims)

    root_id = None
    allowed_admin_roles = {"super_admin", "hr_admin", "executive"}
    if not is_super and role not in allowed_admin_roles:
        if role == "manager":
            caller_emp = await get_current_employee(claims, service)
            if caller_emp:
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
    claims: Annotated[dict | None, Depends(get_current_user_claims_optional)] = None,
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
    claims: Annotated[dict | None, Depends(get_current_user_claims_optional)] = None,
    service: Annotated[HierarchyService, Depends(get_hierarchy_service)] = None,
) -> APIResponse[list[OrganizationChartNode]]:
    """Get flat representation of employee relationships optimized for rendering React Flow charts."""
    role = str(claims.get("role", "")).lower() if claims else ""
    user_uuid_raw = claims.get("sub") if claims else None
    is_super = await _get_is_super_admin(user_uuid_raw, claims, service)
    company_uuid = None if is_super else _get_company_id_safe(claims)

    root_id = None
    allowed_admin_roles = {"super_admin", "hr_admin", "executive"}
    if not is_super and role not in allowed_admin_roles:
        if role == "manager":
            caller_emp = await get_current_employee(claims, service)
            if caller_emp:
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
    claims: Annotated[dict | None, Depends(get_current_user_claims_optional)],
    service: Annotated[HierarchyService, Depends(get_hierarchy_service)],
) -> APIResponse[HierarchyAnalyticsResponse]:
    """Retrieve aggregate team size, levels depth, vacant positions, etc."""
    company_uuid = _get_company_id_safe(claims)
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
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[HierarchyService, Depends(get_hierarchy_service)],
) -> APIResponse[ReportingChainResponse]:
    """Fetch manager, peers, direct reports, reporting chain, and organizational level for an employee."""
    user_uuid = uuid.UUID(claims["sub"])
    company_uuid = _get_company_id(claims)

    # Enforce RBAC security and reuse preloaded target employee
    target_emp = await check_access_to_employee(user_uuid, employee_id, claims, service)
    effective_company_id = target_emp.company_id or company_uuid

    details = await service.get_employee_reporting_details(
        employee_id,
        effective_company_id,
        preloaded_employee=target_emp,
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
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[HierarchyService, Depends(get_hierarchy_service)],
) -> APIResponse[ReportingPathResponse]:
    """Return visual list showing hierarchy levels path, e.g. CEO -> Vice President -> Employee."""
    user_uuid = uuid.UUID(claims["sub"])

    # Enforce RBAC security and reuse preloaded target employee
    emp = await check_access_to_employee(user_uuid, employee_id, claims, service)

    # Fetch ancestors (top-down)
    ancestors = await service.repo.get_recursive_ancestors(employee_id)

    full_path = ancestors + [emp]
    path_nodes = [HierarchyNodeResponse.model_validate(x) for x in full_path]

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
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[HierarchyService, Depends(get_hierarchy_service)],
) -> APIResponse[HierarchyNodeResponse]:
    """Set employee manager, executing circular references and active manager validations. Admin/HR only."""
    role = claims.get("role")
    if role not in {"super_admin", "hr_admin"}:
        raise AppException(message="Access denied: Hierarchy edits are restricted to Admin/HR.", status_code=status.HTTP_403_FORBIDDEN)

    user_uuid = uuid.UUID(claims["sub"])
    emp = await service.assign_manager(payload.employee_id, payload.manager_id, user_uuid)
    
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
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[HierarchyService, Depends(get_hierarchy_service)],
) -> APIResponse[HierarchyNodeResponse]:
    """Change employee reporting manager. Admin/HR only."""
    role = claims.get("role")
    if role not in {"super_admin", "hr_admin"}:
        raise AppException(message="Access denied: Hierarchy edits are restricted to Admin/HR.", status_code=status.HTTP_403_FORBIDDEN)

    user_uuid = uuid.UUID(claims["sub"])
    emp = await service.change_manager(payload.employee_id, payload.new_manager_id, user_uuid)
    
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
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[HierarchyService, Depends(get_hierarchy_service)],
) -> APIResponse[HierarchyNodeResponse]:
    """Remove employee's manager (orphaning or upgrading employee to top level). Admin/HR only."""
    role = claims.get("role")
    if role not in {"super_admin", "hr_admin"}:
        raise AppException(message="Access denied: Hierarchy edits are restricted to Admin/HR.", status_code=status.HTTP_403_FORBIDDEN)

    user_uuid = uuid.UUID(claims["sub"])
    emp = await service.remove_manager(employee_id, user_uuid)
    
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
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[HierarchyService, Depends(get_hierarchy_service)],
) -> APIResponse[list[HierarchyNodeResponse]]:
    """List direct reports of a manager. Subject to caller view boundaries."""
    user_uuid = uuid.UUID(claims["sub"])
    
    # Enforce RBAC security
    await check_access_to_employee(user_uuid, manager_id, claims, service)

    reports = await service.repo.get_direct_reports(manager_id)
    data = [HierarchyNodeResponse.model_validate(r) for r in reports]
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
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[HierarchyService, Depends(get_hierarchy_service)],
) -> APIResponse[list[HierarchyNodeResponse]]:
    """List all descendants (entire direct + indirect team) of a manager. Subject to caller view boundaries."""
    user_uuid = uuid.UUID(claims["sub"])
    
    # Enforce RBAC security
    await check_access_to_employee(user_uuid, manager_id, claims, service)

    team = await service.repo.get_recursive_descendants(manager_id)
    data = [HierarchyNodeResponse.model_validate(t) for t in team]
    return APIResponse(
        success=True,
        message="Recursive team descendants fetched successfully.",
        data=data,
        errors=None,
    )
