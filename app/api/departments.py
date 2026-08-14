"""Department Management API routes."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.core.rbac import require_admin, require_admin_or_manager
from app.middleware.auth import get_current_user_claims
from app.schemas.auth import APIResponse
from app.schemas.department import (
    AssignEmployeesRequest,
    AssignManagerRequest,
    DepartmentCreate,
    DepartmentListResponse,
    DepartmentResponse,
    DepartmentUpdate,
    DepartmentStats,
)
from app.services.department_service import DepartmentService, get_department_service

router = APIRouter(prefix="/departments", tags=["Department Management"])

# Helper dependency to enforce Admin, HR, or IT Admin for write operations
async def require_admin_or_hr(claims: Annotated[dict, Depends(get_current_user_claims)]) -> dict:
    role = str(claims.get("role") or "").lower()
    if role not in {"super_admin", "hr_admin", "it_admin"}:
        from app.core.exceptions import AppException
        raise AppException(message="Only Super Admin, HR Admin and IT Admin can manage departments.", status_code=status.HTTP_403_FORBIDDEN)
    return claims


async def require_admin_or_hr_or_manager(claims: Annotated[dict, Depends(get_current_user_claims)]) -> dict:
    role = str(claims.get("role") or "").lower()
    if role not in {"super_admin", "hr_admin", "manager", "executive", "it_admin"}:
        from app.core.exceptions import AppException
        raise AppException(message="Admin, HR, IT Admin or Executive access required.", status_code=status.HTTP_403_FORBIDDEN)
    return claims


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
    """Create a new department. Admin and HR only."""
    user_id = uuid.UUID(claims["sub"])
    dept = await service.create_department(user_id, payload)
    return APIResponse[DepartmentResponse](
        success=True,
        message="Department created successfully.",
        data=dept,
        errors=None,
    )

from app.middleware.auth import get_current_user_claims, get_current_user_claims_optional

@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[DepartmentListResponse],
    summary="List all departments",
)
async def list_departments(
    status_filter: str | None = Query(None, alias="status", description="Filter by status (ACTIVE/INACTIVE)"),
    search: str | None = Query(None, description="Search by name or code"),
    sort_by: str | None = Query(None, description="Sort field"),
    sort_order: str | None = Query(None, description="Sort order (asc/desc)"),
    page: int = Query(1, ge=1, le=100000),
    limit: int = Query(20, ge=1, le=10000),
    claims: Annotated[dict | None, Depends(get_current_user_claims_optional)] = None,
    service: Annotated[DepartmentService, Depends(get_department_service)] = None,
) -> APIResponse[DepartmentListResponse]:
    """List departments. Supports page, limit, search, status, sort_by, and sort_order filters."""
    try:
        result = await service.list_departments(
            status_filter=status_filter,
            search=search,
            sort_by=sort_by,
            sort_order=sort_order,
            page=page,
            limit=limit,
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
    """Get department by ID. Managers/Employees can only access if they belong to it (checked inside or allowed)."""
    # For now, retrieve details
    dept = await service.get_department(id)
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
async def update_department(
    id: uuid.UUID,
    payload: DepartmentUpdate,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[DepartmentService, Depends(get_department_service)],
) -> APIResponse[DepartmentResponse]:
    """Update department details. Admin and HR only."""
    user_id = uuid.UUID(claims["sub"])
    dept = await service.update_department(user_id, id, payload)
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
    """Soft delete department. Guard checks if employees are assigned. Admin and HR only."""
    user_id = uuid.UUID(claims["sub"])
    await service.delete_department(user_id, id)
    return APIResponse[None](
        success=True,
        message="Department deleted successfully.",
        data=None,
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
    await service.assign_manager(user_id, id, payload)
    return APIResponse[None](
        success=True,
        message="Department head assigned successfully.",
        data=None,
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
    await service.assign_employees(user_id, id, payload)
    return APIResponse[None](
        success=True,
        message="Employees assigned successfully.",
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
    await service.remove_manager(user_id, id)
    return APIResponse[None](
        success=True,
        message="Department head removed successfully.",
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
    await service.remove_employee(user_id, id, employee_id)
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
    """List employees assigned to department. Allowed for anyone (managers, employees, HR, admin)."""
    employees = await service.get_department_employees(id)
    # Convert models to serialization-safe dicts/briefs
    from fastapi.encoders import jsonable_encoder
    return APIResponse[list](
        success=True,
        message="Department employees retrieved successfully.",
        data=jsonable_encoder(employees),
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
    dept = await service.get_department(id)
    from fastapi.encoders import jsonable_encoder
    return APIResponse[dict | None](
        success=True,
        message="Department manager retrieved successfully.",
        data=jsonable_encoder(dept.manager_details) if dept.manager_details else None,
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
    """Retrieve statistics (employee counts, sub-departments count) for a department."""
    stats = await service.get_department_stats(id)
    return APIResponse[DepartmentStats](
        success=True,
        message="Department statistics retrieved successfully.",
        data=stats,
        errors=None,
    )
