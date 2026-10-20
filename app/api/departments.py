"""Department Management API routes - Canonical and unified router for OFC360."""

from __future__ import annotations

import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response, status

from app.middleware.auth import get_current_user_claims
from app.schemas.auth import APIResponse
from app.schemas.department import (
    AssignEmployeesRequest,
    AssignManagerRequest,
    BulkActionResponse,
    BulkAssignManagerRequest,
    BulkDeleteRequest,
    BulkStatusRequest,
    DepartmentAnalyticsResponse,
    DepartmentCreate,
    DepartmentHierarchyNode,
    DepartmentImportRequest,
    DepartmentListItem,
    DepartmentListResponse,
    DepartmentResponse,
    DepartmentStats,
    DepartmentSummary,
    DepartmentUpdate,
    TransferEmployeesRequest,
)
from app.services.department_service import DepartmentService, get_department_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/departments", tags=["Department Management"])


def _get_cid(claims: dict | None) -> uuid.UUID | None:
    if not claims:
        return None
    cid = claims.get("company_id")
    try:
        return uuid.UUID(str(cid)) if cid else None
    except (ValueError, TypeError):
        return None


# Helper dependencies for RBAC
async def require_admin_or_hr(claims: Annotated[dict, Depends(get_current_user_claims)]) -> dict:
    role = str(claims.get("role") or "").lower()
    if role not in {"super_admin", "hr_admin", "it_admin"}:
        from app.core.exceptions import AppException
        raise AppException(
            message="Only Super Admin, HR Admin and IT Admin can manage departments.",
            status_code=status.HTTP_403_FORBIDDEN,
        )
    return claims


async def require_admin_or_hr_or_manager(claims: Annotated[dict, Depends(get_current_user_claims)]) -> dict:
    role = str(claims.get("role") or "").lower()
    if role not in {"super_admin", "hr_admin", "manager", "executive", "it_admin"}:
        from app.core.exceptions import AppException
        raise AppException(
            message="Admin, HR, IT Admin or Executive access required.",
            status_code=status.HTTP_403_FORBIDDEN,
        )
    return claims


# ==============================================================================
# 1. Base Department CRUD (Create & List)
# ==============================================================================

@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[DepartmentResponse],
    summary="Create a new department",
)
async def create_department(
    payload: DepartmentCreate,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[DepartmentService, Depends(get_department_service)],
) -> APIResponse[DepartmentResponse]:
    """Create a new department. Admin, HR Admin, and IT Admin only."""
    user_id = uuid.UUID(claims["sub"])
    cid = _get_cid(claims)
    dept = await service.create_department(user_id, payload, company_id=cid)
    return APIResponse[DepartmentResponse](
        success=True,
        message="Department created successfully.",
        data=dept,
        errors=None,
    )


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[DepartmentListResponse],
    summary="List all departments",
)
async def list_departments(
    status_filter: str | None = Query(None, alias="status", description="Filter by status (ACTIVE/INACTIVE/HIRING)"),
    search: str | None = Query(None, description="Search by name or code"),
    sort_by: str | None = Query(None, description="Sort field"),
    sort_order: str | None = Query(None, description="Sort order (asc/desc)"),
    parent_id: uuid.UUID | None = Query(None, description="Filter by parent department ID"),
    page: int = Query(1, ge=1, description="Page number (>= 1)"),
    limit: int = Query(20, ge=1, le=100, description="Items per page (1 to 100)"),
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    service: Annotated[DepartmentService, Depends(get_department_service)] = None,
) -> APIResponse[DepartmentListResponse]:
    """List departments. Supports page, limit, search, status, sort_by, sort_order, and parent_id filters."""
    try:
        cid = _get_cid(claims)
        result = await service.list_departments(
            status_filter=status_filter,
            search=search,
            sort_by=sort_by,
            sort_order=sort_order,
            parent_id=parent_id,
            page=page,
            limit=limit,
            company_id=cid,
        )
        return APIResponse[DepartmentListResponse](
            success=True,
            message="Departments retrieved successfully.",
            data=result,
            errors=None,
        )
    except Exception as exc:
        from app.core.exceptions import AppException
        if isinstance(exc, AppException):
            raise exc
        logger.exception("list_departments failed: %s", exc)
        return APIResponse[DepartmentListResponse](
            success=False,
            message=f"Failed to fetch departments: {str(exc)}",
            data=DepartmentListResponse(items=[], total=0, page=page, limit=limit, pages=0),
            errors=[{"field": "query", "message": str(exc)}],
        )


# ==============================================================================
# 2. Static Endpoints (MUST be registered before /{id} to avoid 422 routing conflicts)
# ==============================================================================

@router.get(
    "/summary",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[DepartmentSummary],
    summary="Get department summary metrics",
)
async def get_departments_summary(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[DepartmentService, Depends(get_department_service)],
) -> APIResponse[DepartmentSummary]:
    """Get department summary metrics. Scoped by company_id."""
    cid = _get_cid(claims)
    summary = await service.get_departments_summary(company_id=cid)
    return APIResponse[DepartmentSummary](
        success=True,
        message="Department summary retrieved successfully.",
        data=summary,
        errors=None,
    )


@router.get(
    "/stats",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[DepartmentSummary],
    summary="Get department statistics overview",
)
async def get_departments_overview_stats(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[DepartmentService, Depends(get_department_service)],
) -> APIResponse[DepartmentSummary]:
    """Overview department statistics (alias to summary metrics)."""
    cid = _get_cid(claims)
    summary = await service.get_departments_summary(company_id=cid)
    return APIResponse[DepartmentSummary](
        success=True,
        message="Department statistics retrieved successfully.",
        data=summary,
        errors=None,
    )


@router.get(
    "/analytics",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[DepartmentAnalyticsResponse],
    summary="Get department detailed analytics",
)
async def get_department_analytics(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[DepartmentService, Depends(get_department_service)],
) -> APIResponse[DepartmentAnalyticsResponse]:
    """Get deep department analytics (capacity utilization, budget allocation, team size breakdown)."""
    cid = _get_cid(claims)
    analytics = await service.get_department_analytics(company_id=cid)
    return APIResponse[DepartmentAnalyticsResponse](
        success=True,
        message="Department analytics retrieved successfully.",
        data=analytics,
        errors=None,
    )


@router.get(
    "/hierarchy",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[list[DepartmentHierarchyNode]],
    summary="Get organizational hierarchy tree of departments",
)
@router.get(
    "/tree",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[list[DepartmentHierarchyNode]],
    summary="Get organizational hierarchy tree of departments (alias)",
)
async def get_department_hierarchy(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[DepartmentService, Depends(get_department_service)],
) -> APIResponse[list[DepartmentHierarchyNode]]:
    """Retrieve full company department hierarchy tree with employee counts and manager assignments."""
    cid = _get_cid(claims)
    tree = await service.get_department_hierarchy(company_id=cid)
    return APIResponse[list[DepartmentHierarchyNode]](
        success=True,
        message="Department hierarchy tree retrieved successfully.",
        data=tree,
        errors=None,
    )


@router.post(
    "/bulk-delete",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[BulkActionResponse],
    summary="Bulk soft delete departments",
)
async def bulk_delete_departments(
    payload: BulkDeleteRequest,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[DepartmentService, Depends(get_department_service)],
) -> APIResponse[BulkActionResponse]:
    """Bulk soft delete departments. Blocks any departments with active employees assigned."""
    user_id = uuid.UUID(claims["sub"])
    cid = _get_cid(claims)
    result = await service.bulk_delete_departments(user_id, payload.department_ids, company_id=cid)
    return APIResponse[BulkActionResponse](
        success=True,
        message=f"Bulk delete completed. {result.affected_count} departments deleted.",
        data=result,
        errors=result.errors,
    )


@router.post(
    "/bulk-status",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[BulkActionResponse],
    summary="Bulk update department status",
)
async def bulk_update_status(
    payload: BulkStatusRequest,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[DepartmentService, Depends(get_department_service)],
) -> APIResponse[BulkActionResponse]:
    """Bulk update status for departments (ACTIVE, INACTIVE, HIRING, GROWING)."""
    user_id = uuid.UUID(claims["sub"])
    cid = _get_cid(claims)
    result = await service.bulk_update_status(user_id, payload.department_ids, payload.status, company_id=cid)
    return APIResponse[BulkActionResponse](
        success=True,
        message=f"Status updated to '{payload.status}' for {result.affected_count} departments.",
        data=result,
        errors=None,
    )


@router.post(
    "/bulk-assign-manager",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[BulkActionResponse],
    summary="Bulk assign manager to departments",
)
async def bulk_assign_manager(
    payload: BulkAssignManagerRequest,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[DepartmentService, Depends(get_department_service)],
) -> APIResponse[BulkActionResponse]:
    """Bulk assign department head/manager to multiple departments."""
    user_id = uuid.UUID(claims["sub"])
    cid = _get_cid(claims)
    result = await service.bulk_assign_manager(user_id, payload.department_ids, payload.manager_user_id, company_id=cid)
    return APIResponse[BulkActionResponse](
        success=True,
        message=f"Manager assigned across {result.affected_count} departments.",
        data=result,
        errors=None,
    )


@router.post(
    "/transfer-employees",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[BulkActionResponse],
    summary="Transfer employees between departments",
)
async def transfer_employees(
    payload: TransferEmployeesRequest,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[DepartmentService, Depends(get_department_service)],
) -> APIResponse[BulkActionResponse]:
    """Transfer employees from one department to another."""
    user_id = uuid.UUID(claims["sub"])
    cid = _get_cid(claims)
    result = await service.transfer_employees(
        user_id,
        payload.source_department_id,
        payload.target_department_id,
        payload.employee_ids,
        company_id=cid,
    )
    return APIResponse[BulkActionResponse](
        success=True,
        message=f"Transferred {result.affected_count} employees successfully.",
        data=result,
        errors=None,
    )


@router.get(
    "/export",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[list[dict[str, Any]]],
    summary="Export all company departments",
)
async def export_departments(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[DepartmentService, Depends(get_department_service)],
) -> APIResponse[list[dict[str, Any]]]:
    """Export departments as structured JSON list."""
    cid = _get_cid(claims)
    records = await service.export_departments(company_id=cid)
    return APIResponse[list[dict[str, Any]]](
        success=True,
        message=f"Exported {len(records)} departments.",
        data=records,
        errors=None,
    )


@router.get(
    "/export/csv",
    status_code=status.HTTP_200_OK,
    summary="Export departments as CSV file",
)
async def export_departments_csv(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[DepartmentService, Depends(get_department_service)],
) -> Response:
    """Export departments as CSV download."""
    cid = _get_cid(claims)
    csv_content = await service.export_departments_csv(company_id=cid)
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=departments.csv"},
    )


@router.post(
    "/import",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[BulkActionResponse],
    summary="Bulk import departments",
)
async def import_departments(
    payload: DepartmentImportRequest,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[DepartmentService, Depends(get_department_service)],
) -> APIResponse[BulkActionResponse]:
    """Bulk import departments."""
    user_id = uuid.UUID(claims["sub"])
    cid = _get_cid(claims)
    result = await service.import_departments(user_id, payload.departments, company_id=cid)
    return APIResponse[BulkActionResponse](
        success=True,
        message=f"Import completed. {result.affected_count} departments created.",
        data=result,
        errors=result.errors,
    )


# ==============================================================================
# 3. Dynamic Endpoints By Department ID (/{id})
# ==============================================================================

@router.get(
    "/{id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[DepartmentResponse],
    summary="Get department details by ID",
)
async def get_department(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[DepartmentService, Depends(get_department_service)],
) -> APIResponse[DepartmentResponse]:
    """Get department by ID."""
    cid = _get_cid(claims)
    dept = await service.get_department(id, company_id=cid)
    return APIResponse[DepartmentResponse](
        success=True,
        message="Department details retrieved successfully.",
        data=dept,
        errors=None,
    )


@router.put(
    "/{id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[DepartmentResponse],
    summary="Update department details",
)
@router.patch(
    "/{id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[DepartmentResponse],
    summary="Update department details (partial)",
)
async def update_department(
    id: uuid.UUID,
    payload: DepartmentUpdate,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[DepartmentService, Depends(get_department_service)],
) -> APIResponse[DepartmentResponse]:
    """Update department details. Admin, HR Admin, and IT Admin only."""
    user_id = uuid.UUID(claims["sub"])
    cid = _get_cid(claims)
    dept = await service.update_department(user_id, id, payload, company_id=cid)
    return APIResponse[DepartmentResponse](
        success=True,
        message="Department updated successfully.",
        data=dept,
        errors=None,
    )


@router.delete(
    "/{id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[None],
    summary="Soft delete a department",
)
async def delete_department(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[DepartmentService, Depends(get_department_service)],
) -> APIResponse[None]:
    """Soft delete department. Guard checks if active employees are assigned."""
    user_id = uuid.UUID(claims["sub"])
    cid = _get_cid(claims)
    await service.delete_department(user_id, id, company_id=cid)
    return APIResponse[None](
        success=True,
        message="Department deleted successfully.",
        data=None,
        errors=None,
    )


@router.get(
    "/{id}/hierarchy",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[DepartmentHierarchyNode],
    summary="Get department subtree hierarchy",
)
async def get_department_subtree_hierarchy(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[DepartmentService, Depends(get_department_service)],
) -> APIResponse[DepartmentHierarchyNode]:
    """Retrieve subtree hierarchy rooted at the specified department."""
    cid = _get_cid(claims)
    subtree = await service.get_department_subtree_hierarchy(id, company_id=cid)
    return APIResponse[DepartmentHierarchyNode](
        success=True,
        message="Subtree hierarchy retrieved successfully.",
        data=subtree,
        errors=None,
    )


@router.post(
    "/{id}/assign-manager",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[None],
    summary="Assign Head of Department (Manager)",
)
async def assign_manager(
    id: uuid.UUID,
    payload: AssignManagerRequest,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[DepartmentService, Depends(get_department_service)],
) -> APIResponse[None]:
    """Assign Head of Department. Admin and HR only."""
    user_id = uuid.UUID(claims["sub"])
    cid = _get_cid(claims)
    await service.assign_manager(user_id, id, payload, company_id=cid)
    return APIResponse[None](
        success=True,
        message="Department head assigned successfully.",
        data=None,
        errors=None,
    )


@router.delete(
    "/{id}/remove-manager",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[None],
    summary="Remove Head of Department",
)
async def remove_manager(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[DepartmentService, Depends(get_department_service)],
) -> APIResponse[None]:
    """Remove Department Head. Admin and HR only."""
    user_id = uuid.UUID(claims["sub"])
    cid = _get_cid(claims)
    await service.remove_manager(user_id, id, company_id=cid)
    return APIResponse[None](
        success=True,
        message="Department head removed successfully.",
        data=None,
        errors=None,
    )


@router.get(
    "/{id}/manager",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict | None],
    summary="Get department manager (Head of Department)",
)
async def get_manager(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[DepartmentService, Depends(get_department_service)],
) -> APIResponse[dict | None]:
    """Get the manager of a department."""
    cid = _get_cid(claims)
    dept = await service.get_department(id, company_id=cid)
    from fastapi.encoders import jsonable_encoder
    return APIResponse[dict | None](
        success=True,
        message="Department manager retrieved successfully.",
        data=jsonable_encoder(dept.manager_details) if dept.manager_details else None,
        errors=None,
    )


@router.post(
    "/{id}/assign-employees",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[None],
    summary="Assign multiple employees to a department",
)
async def assign_employees(
    id: uuid.UUID,
    payload: AssignEmployeesRequest,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[DepartmentService, Depends(get_department_service)],
) -> APIResponse[None]:
    """Assign employees to department. Admin and HR only."""
    user_id = uuid.UUID(claims["sub"])
    cid = _get_cid(claims)
    await service.assign_employees(user_id, id, payload, company_id=cid)
    return APIResponse[None](
        success=True,
        message="Employees assigned successfully.",
        data=None,
        errors=None,
    )


@router.delete(
    "/{id}/remove-employee/{employee_id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[None],
    summary="Remove an employee from a department",
)
async def remove_employee(
    id: uuid.UUID,
    employee_id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[DepartmentService, Depends(get_department_service)],
) -> APIResponse[None]:
    """Remove employee from department. Admin and HR only."""
    user_id = uuid.UUID(claims["sub"])
    cid = _get_cid(claims)
    await service.remove_employee(user_id, id, employee_id, company_id=cid)
    return APIResponse[None](
        success=True,
        message="Employee removed from department successfully.",
        data=None,
        errors=None,
    )


@router.get(
    "/{id}/employees",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[list],
    summary="Get all employees in a department",
)
async def get_employees(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[DepartmentService, Depends(get_department_service)],
) -> APIResponse[list]:
    """List employees assigned to department."""
    cid = _get_cid(claims)
    employees = await service.get_department_employees(id, company_id=cid)
    from fastapi.encoders import jsonable_encoder
    return APIResponse[list](
        success=True,
        message="Department employees retrieved successfully.",
        data=jsonable_encoder(employees),
        errors=None,
    )


@router.get(
    "/{id}/stats",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[DepartmentStats],
    summary="Get department statistics",
)
async def get_stats(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[DepartmentService, Depends(get_department_service)],
) -> APIResponse[DepartmentStats]:
    """Retrieve statistics (employee counts, sub-departments count) for a specific department."""
    cid = _get_cid(claims)
    stats = await service.get_department_stats(id, company_id=cid)
    return APIResponse[DepartmentStats](
        success=True,
        message="Department statistics retrieved successfully.",
        data=stats,
        errors=None,
    )
