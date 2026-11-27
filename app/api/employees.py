"""Employee Management API routes.

CONTRACT: Every route is scoped to the current admin's company_id (extracted from JWT claims).
Multi-tenant: employees from other companies are never exposed — they return 404.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, File, UploadFile, Response, status, Request

from app.core.exceptions import AppException
from app.core.rbac import require_admin, require_admin_or_manager, ADMIN_MANAGER_ROLES
from app.middleware.auth import get_current_user_claims, get_current_user_claims_optional
from app.schemas.auth import APIResponse
from app.schemas.hierarchy import HierarchyTreeResponse
from app.services.hierarchy_service import HierarchyService, get_hierarchy_service
from app.schemas.employee import (
    ActivateEmployeeRequest,
    ApproveRejectRequest,
    EmployeeCreate,
    EmployeeListItem,
    EmployeeListItemFull,
    EmployeeListResponse,
    EmployeeOnboardingStatusResponse,
    EmployeeResponse,
    EmployeeUpdate,
    DeactivateEmployeeRequest,
)
from app.services.employee_service import EmployeeService, get_employee_service
from app.services.hierarchy_service import HierarchyService, get_hierarchy_service
from app.schemas.hierarchy import HierarchyTreeResponse
from app.middleware.auth import get_current_user_claims_optional

router = APIRouter(prefix="/employees", tags=["Employee Management"])


def _get_company_id(claims: dict) -> uuid.UUID:
    """Extract and validate the company_id from JWT claims. Raises 403 if missing."""
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


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[EmployeeResponse],
    summary="Create a new employee",
    responses={
        status.HTTP_201_CREATED: {"model": APIResponse[EmployeeResponse]},
        status.HTTP_400_BAD_REQUEST: {"model": APIResponse[None]},
        status.HTTP_401_UNAUTHORIZED: {"model": APIResponse[None]},
        status.HTTP_403_FORBIDDEN: {"model": APIResponse[None]},
        status.HTTP_409_CONFLICT: {"model": APIResponse[None]},
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"model": APIResponse[None]},
    },
)
async def create_employee(
    payload: EmployeeCreate,
    claims: Annotated[dict, Depends(require_admin)],
    service: Annotated[EmployeeService, Depends(get_employee_service)],
) -> APIResponse[EmployeeResponse]:
    """Create a new employee record and send an activation email. Admin only."""
    admin_id = uuid.UUID(claims["sub"])
    company_id = _get_company_id(claims)
    employee = await service.create_employee(admin_id, company_id, payload)
    email_sent = getattr(employee, "_email_sent", True)
    message = (
        "Employee created successfully. Invitation email sent."
        if email_sent
        else "Employee created but invitation email could not be sent. Use Resend Invitation to retry."
    )
    return APIResponse[EmployeeResponse](
        success=True,
        message=message,
        data=employee,
        errors=None,
    )


@router.get(
    "/dashboard",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Get employee management dashboard analytics",
)
@router.get(
    "/stats",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Get employee stats overview",
)
async def get_employee_dashboard_stats(
    claims: Annotated[dict, Depends(require_admin_or_manager)],
    service: Annotated[EmployeeService, Depends(get_employee_service)],
) -> APIResponse[dict]:
    """Retrieve aggregation metrics and breakdown stats for employee dashboard."""
    company_id = _get_company_id(claims)
    stats = await service.get_dashboard_stats(company_id)
    return APIResponse[dict](
        success=True,
        message="Employee dashboard statistics retrieved successfully.",
        data=stats,
        errors=None,
    )


@router.post(
    "/import",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Bulk import employees from Excel or CSV sheet",
)
async def import_employees(
    file: UploadFile = File(...),
    claims: Annotated[dict, Depends(require_admin)] = None,
    service: Annotated[EmployeeService, Depends(get_employee_service)] = None,
) -> APIResponse[dict]:
    """Bulk import employee records from uploaded Excel (.xlsx) or CSV file."""
    admin_id = uuid.UUID(claims["sub"])
    company_id = _get_company_id(claims)
    content = await file.read()
    result = await service.bulk_import_employees(
        admin_id=admin_id,
        company_id=company_id,
        file_bytes=content,
        filename=file.filename or "employees.xlsx",
    )
    return APIResponse[dict](
        success=True,
        message=f"Import complete. Processed {result['total_processed']} rows ({result['imported_count']} imported, {result['skipped_count']} skipped).",
        data=result,
        errors=None,
    )


@router.get(
    "/export",
    status_code=status.HTTP_200_OK,
    summary="Export employee records as Excel, CSV, or PDF",
)
async def export_employees(
    request: Request,
    format: str = Query("xlsx", description="xlsx, csv, or pdf"),
    search: str | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    department: str | None = Query(None),
    designation: str | None = Query(None),
    claims: Annotated[dict, Depends(require_admin_or_manager)] = None,
    service: Annotated[EmployeeService, Depends(get_employee_service)] = None,
) -> Response:
    """Export employee records with filtering as formatted Excel (.xlsx), CSV, or PDF file."""
    company_id = _get_company_id(claims)
    from app.services.export_service import ExportService
    export_svc = ExportService(service.session)
    user_id = uuid.UUID(claims["sub"])
    filters = {
        "search": search,
        "status": status_filter,
        "department": department,
        "designation": designation,
    }
    content, filename, media_type = await export_svc.export_module(
        user_id=user_id,
        company_id=company_id,
        module="employees",
        filters=filters,
        fmt=format,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[EmployeeListResponse],
    summary="List all employees",
)
async def list_employees(
    claims: Annotated[dict, Depends(require_admin_or_manager)],
    service: Annotated[EmployeeService, Depends(get_employee_service)],
    department: str | None = Query(None, description="Filter by department (use 'all' to skip)"),
    status_filter: str | None = Query(None, alias="status", description="Filter by employee status"),
    role: str | None = Query(None, description="Filter by role"),
    employment_type: str | None = Query(None, description="Filter by employment type"),
    designation: str | None = Query(None, description="Filter by designation"),
    shift: str | None = Query(None, description="Filter by shift"),
    search: str | None = Query(None, description="Search across names, employee ID, and emails"),
    sort: str | None = Query(None, description="Field to sort by"),
    order: str | None = Query("asc", description="Sort order (asc/desc)"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(10, ge=1, le=2000, description="Records per page"),
) -> APIResponse[EmployeeListResponse]:
    """Retrieve a paginated, filterable list of employee records scoped to the admin's company."""
    company_id = _get_company_id(claims)
    result = await service.list_employees(
        company_id=company_id,
        department=department,
        status_filter=status_filter,
        employment_type=employment_type,
        search=search,
        page=page,
        limit=limit,
        designation=designation,
        shift=shift,
        role=role,
        sort=sort,
        order=order,
    )
    return APIResponse[EmployeeListResponse](
        success=True,
        message="Employees retrieved successfully.",
        data=result,
        errors=None,
    )


# Static routes MUST come before /{id} to avoid UUID parsing conflicts
@router.get(
    "/hierarchy",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[list[HierarchyTreeResponse]],
    summary="Get organization employee hierarchy tree",
)
async def get_employees_hierarchy(
    department: str | None = Query(None),
    designation: str | None = Query(None),
    location: str | None = Query(None),
    employment_type: str | None = Query(None),
    reporting_manager_id: str | None = Query(None),
    search: str | None = Query(None),
    claims: Annotated[dict | None, Depends(get_current_user_claims_optional)] = None,
    service: Annotated[HierarchyService, Depends(get_hierarchy_service)] = None,
) -> APIResponse[list[HierarchyTreeResponse]]:
    """Return nested organization hierarchy tree (compatibility alias for /api/v1/hierarchy)."""
    from app.api.hierarchy import get_hierarchy

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
    "/validate-invitation",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Validate employee invitation token",
)
async def validate_employee_invitation(
    token: str = Query(..., description="Employee activation / invitation token"),
    service: Annotated[EmployeeService, Depends(get_employee_service)] = None,
) -> APIResponse[dict]:
    """Validate that the invitation token is valid, not expired, and belongs to an invited employee."""
    data = await service.validate_invitation_token(token)
    return APIResponse[dict](
        success=True,
        message="Token is valid.",
        data=data,
        errors=None,
    )


@router.get(
    "/validate-token",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Validate employee invitation token alias",
)
async def validate_employee_invitation_token_alias(
    token: str = Query(..., description="Employee activation / invitation token"),
    service: Annotated[EmployeeService, Depends(get_employee_service)] = None,
) -> APIResponse[dict]:
    """Validate employee invitation token alias."""
    data = await service.validate_invitation_token(token)
    return APIResponse[dict](
        success=True,
        message="Token is valid.",
        data=data,
        errors=None,
    )


@router.get(
    "/validate",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Validate employee invitation token alias",
)
async def validate_employee_invitation_alias(
    token: str = Query(..., description="Employee activation / invitation token"),
    service: Annotated[EmployeeService, Depends(get_employee_service)] = None,
) -> APIResponse[dict]:
    """Validate employee invitation token alias."""
    data = await service.validate_invitation_token(token)
    return APIResponse[dict](
        success=True,
        message="Token is valid.",
        data=data,
        errors=None,
    )


@router.get(
    "/hierarchy",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[list[HierarchyTreeResponse]],
    summary="Get complete organization hierarchy tree",
)
async def get_employee_hierarchy(
    department: str | None = Query(None),
    designation: str | None = Query(None),
    location: str | None = Query(None),
    employment_type: str | None = Query(None),
    reporting_manager_id: str | None = Query(None),
    search: str | None = Query(None),
    claims: Annotated[dict | None, Depends(get_current_user_claims_optional)] = None,
    hierarchy_service: Annotated[HierarchyService, Depends(get_hierarchy_service)] = None,
) -> APIResponse[list[HierarchyTreeResponse]]:
    """Return nested organization hierarchy tree scoped to roles with optional filtering.
    
    This endpoint provides the same hierarchy data as /api/v1/hierarchy/ but under the
    /api/v1/employees/ prefix for frontend compatibility.
    """
    role = str(claims.get("role", "")).lower() if claims else ""
    user_uuid_raw = claims.get("sub") if claims else None
    
    # Reuse the super admin check logic from hierarchy router
    is_super = False
    if user_uuid_raw and role == "super_admin":
        try:
            user_uuid = uuid.UUID(str(user_uuid_raw))
            from app.models.user import User
            from sqlalchemy import select
            from sqlalchemy.orm import load_only, noload
            res = await hierarchy_service.session.execute(
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
            if user and not user.is_deleted and user.is_active:
                if str(getattr(user, "account_status", "") or "").upper() == "ACTIVE":
                    is_super = bool(user.is_super_admin)
        except Exception:
            pass
    
    from app.api.hierarchy import _get_company_id_safe
    company_uuid = None if is_super else _get_company_id_safe(claims)

    root_id = None
    allowed_admin_roles = {"super_admin", "hr_admin", "executive"}
    if not is_super and role not in allowed_admin_roles:
        if role == "manager":
            from app.models.employee import Employee
            from sqlalchemy import and_, select
            from sqlalchemy.orm import load_only
            from app.repositories.hierarchy_repository import _HIERARCHY_EMPLOYEE_COLUMNS
            try:
                user_uuid = uuid.UUID(str(user_uuid_raw))
                conditions = [Employee.user_id == user_uuid, Employee.is_deleted == False]
                if company_uuid is not None:
                    conditions.append(Employee.company_id == company_uuid)
                stmt = (
                    select(Employee)
                    .where(and_(*conditions))
                    .options(load_only(*_HIERARCHY_EMPLOYEE_COLUMNS))
                )
                res = await hierarchy_service.session.execute(stmt)
                caller_emp = res.scalar_one_or_none()
                if caller_emp:
                    root_id = caller_emp.id
            except Exception:
                pass

    tree = await hierarchy_service.build_tree(
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
    "/{id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[EmployeeResponse],
    summary="Get employee by ID",
)
async def get_employee(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[EmployeeService, Depends(get_employee_service)],
) -> APIResponse[EmployeeResponse]:
    """Retrieve full employee profile. Admin/Manager scoped to their company. Employees can only view their own."""
    user_role = claims.get("role")
    user_id = uuid.UUID(claims["sub"])
    company_id = _get_company_id(claims)

    if user_role not in ADMIN_MANAGER_ROLES:
        # Employees may only view their own profile (within same company)
        employee = await service.get_employee(id, company_id)
        if employee.user_id != user_id:
            raise AppException(
                message="You do not have permission to view this profile.",
                status_code=status.HTTP_403_FORBIDDEN,
            )
        return APIResponse[EmployeeResponse](
            success=True,
            message="Employee profile retrieved successfully.",
            data=employee,
            errors=None,
        )

    employee = await service.get_employee(id, company_id)
    return APIResponse[EmployeeResponse](
        success=True,
        message="Employee profile retrieved successfully.",
        data=employee,
        errors=None,
    )


@router.put(
    "/{id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[EmployeeResponse],
    summary="Update employee details",
)
@router.patch(
    "/{id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[EmployeeResponse],
    summary="Update employee details (PATCH)",
)
async def update_employee(
    id: uuid.UUID,
    payload: EmployeeUpdate,
    claims: Annotated[dict, Depends(require_admin)],
    service: Annotated[EmployeeService, Depends(get_employee_service)],
    request: Request,
) -> APIResponse[EmployeeResponse]:
    """Partially update employee details. Admin only. Scoped to admin's company."""
    admin_id = uuid.UUID(claims["sub"])
    company_id = _get_company_id(claims)
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    
    import logging
    logger = logging.getLogger(__name__)
    logger.info("PATCH /employees/%s received | admin_id=%s | company_id=%s", id, admin_id, company_id)

    try:
        employee = await service.update_employee(
            admin_id=admin_id,
            company_id=company_id,
            employee_uuid=id,
            payload=payload,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return APIResponse[EmployeeResponse](
            success=True,
            message="Employee updated successfully.",
            data=employee,
            errors=None,
        )
    except Exception as exc:
        logger.exception("Error during PATCH /employees/%s update: %s", id, str(exc), exc_info=exc)
        raise


@router.delete(
    "/{id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[None],
    summary="Soft delete an employee",
)
async def delete_employee(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin)],
    service: Annotated[EmployeeService, Depends(get_employee_service)],
) -> APIResponse[None]:
    """Soft delete employee and revoke all their active JWT refresh tokens. Admin only."""
    admin_id = uuid.UUID(claims["sub"])
    company_id = _get_company_id(claims)
    await service.delete_employee(admin_id, company_id, id)
    return APIResponse[None](
        success=True,
        message="Employee deleted successfully and active sessions revoked.",
        data=None,
        errors=None,
    )


@router.post(
    "/{id}/send-invitation",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Resend employee invitation link",
)
async def send_invitation(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin)],
    service: Annotated[EmployeeService, Depends(get_employee_service)],
) -> APIResponse[dict]:
    """Generate a new activation token and resend the email invitation. Admin only."""
    admin_id = uuid.UUID(claims["sub"])
    company_id = _get_company_id(claims)
    token_data = await service.send_invitation(admin_id, company_id, id)
    return APIResponse[dict](
        success=True,
        message="Invitation email sent successfully.",
        data=token_data,
        errors=None,
    )


@router.post(
    "/{id}/send-invite",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Resend employee invitation link (alias)",
)
async def send_invite_alias(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin)],
    service: Annotated[EmployeeService, Depends(get_employee_service)],
) -> APIResponse[dict]:
    """Alias for send-invitation — same behaviour, different URL."""
    admin_id = uuid.UUID(claims["sub"])
    company_id = _get_company_id(claims)
    token_data = await service.send_invitation(admin_id, company_id, id)
    return APIResponse[dict](
        success=True,
        message="Invitation email sent successfully.",
        data=token_data,
        errors=None,
    )


@router.post(
    "/{id}/deactivate",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[None],
    summary="Deactivate employee account",
)
async def deactivate_employee(
    id: uuid.UUID,
    payload: DeactivateEmployeeRequest,
    claims: Annotated[dict, Depends(require_admin)],
    service: Annotated[EmployeeService, Depends(get_employee_service)],
) -> APIResponse[None]:
    """Set employee status to DISABLED and revoke portal access. Admin only."""
    admin_id = uuid.UUID(claims["sub"])
    company_id = _get_company_id(claims)
    await service.deactivate_employee(admin_id, company_id, id, payload.reason)
    return APIResponse[None](
        success=True,
        message="Employee account deactivated successfully.",
        data=None,
        errors=None,
    )


@router.post(
    "/{id}/activate-by-admin",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[None],
    summary="Activate employee account by Admin",
)
async def activate_employee_by_admin(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin)],
    service: Annotated[EmployeeService, Depends(get_employee_service)],
) -> APIResponse[None]:
    """Activate employee: creates a linked users row if needed and grants portal access. Admin only."""
    admin_id = uuid.UUID(claims["sub"])
    company_id = _get_company_id(claims)
    await service.activate_employee_by_admin(admin_id, company_id, id)
    return APIResponse[None](
        success=True,
        message="Employee account activated successfully.",
        data=None,
        errors=None,
    )


@router.post(
    "/{id}/activate",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[None],
    summary="Activate employee account (self-activation via email link)",
)
async def activate_employee(
    id: str,
    payload: ActivateEmployeeRequest,
    service: Annotated[EmployeeService, Depends(get_employee_service)],
) -> APIResponse[None]:
    """Submit the activation token from email along with the chosen permanent password. Public endpoint."""
    parsed_uuid: uuid.UUID | None = None
    try:
        parsed_uuid = uuid.UUID(id)
    except (ValueError, AttributeError):
        parsed_uuid = None

    await service.activate_employee(parsed_uuid, payload, id_str=id)
    return APIResponse[None](
        success=True,
        message="Account activated successfully. You can now log in.",
        data=None,
        errors=None,
    )


@router.post(
    "/{id}/approve",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[None],
    summary="HR Approval for Onboarding",
)
async def approve_employee(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin)],
    service: Annotated[EmployeeService, Depends(get_employee_service)],
) -> APIResponse[None]:
    """HR approval of employee onboarding documents. Sets status to ACTIVE. Admin only."""
    admin_id = uuid.UUID(claims["sub"])
    company_id = _get_company_id(claims)
    await service.approve_employee(admin_id, company_id, id)
    return APIResponse[None](
        success=True,
        message="Employee onboarding approved. Status set to ACTIVE.",
        data=None,
        errors=None,
    )


@router.post(
    "/{id}/reject",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[None],
    summary="Reject Onboarding",
)
async def reject_employee(
    id: uuid.UUID,
    payload: ApproveRejectRequest,
    claims: Annotated[dict, Depends(require_admin)],
    service: Annotated[EmployeeService, Depends(get_employee_service)],
) -> APIResponse[None]:
    """Reject employee onboarding. Sets status to INACTIVE. Admin only."""
    admin_id = uuid.UUID(claims["sub"])
    company_id = _get_company_id(claims)
    await service.reject_employee(admin_id, company_id, id, payload)
    return APIResponse[None](
        success=True,
        message="Employee onboarding rejected. Status set to INACTIVE.",
        data=None,
        errors=None,
    )


@router.post(
    "/{id}/reset-password",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[None],
    summary="Admin reset of employee password",
)
async def reset_password(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin)],
    service: Annotated[EmployeeService, Depends(get_employee_service)],
) -> APIResponse[None]:
    """Admin-triggered password reset. Generates a temporary password and emails it to the employee."""
    admin_id = uuid.UUID(claims["sub"])
    company_id = _get_company_id(claims)
    await service.reset_employee_password(admin_id, company_id, id)
    return APIResponse[None](
        success=True,
        message="Employee password reset successfully. Temporary password emailed.",
        data=None,
        errors=None,
    )


@router.get(
    "/{id}/onboarding-status",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[EmployeeOnboardingStatusResponse],
    summary="Get onboarding checklist progress",
)
async def get_onboarding_status(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[EmployeeService, Depends(get_employee_service)],
) -> APIResponse[EmployeeOnboardingStatusResponse]:
    """Retrieve progress of onboarding checklist steps. Admin/Manager or owner employee only."""
    user_role = claims.get("role")
    user_id = uuid.UUID(claims["sub"])
    company_id = _get_company_id(claims)

    if user_role not in ADMIN_MANAGER_ROLES:
        employee = await service.get_employee(id, company_id)
        if employee.user_id != user_id:
            raise AppException(
                message="You do not have permission to view this onboarding status.",
                status_code=status.HTTP_403_FORBIDDEN,
            )

    result = await service.get_onboarding_status(id, company_id)
    return APIResponse[EmployeeOnboardingStatusResponse](
        success=True,
        message="Onboarding status retrieved successfully.",
        data=result,
        errors=None,
    )


@router.get(
    "/{id}/reporting",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Get employee reporting hierarchy details",
)
async def get_employee_reporting_details_compat(
    id: uuid.UUID,
    claims: Annotated[dict | None, Depends(get_current_user_claims_optional)] = None,
    service: Annotated[HierarchyService, Depends(get_hierarchy_service)] = None,
) -> APIResponse[dict]:
    """Compatibility alias delegating to /api/v1/hierarchy/{employee_id}."""
    from app.api.hierarchy import get_employee_hierarchy_details

    return await get_employee_hierarchy_details(
        employee_id=id,
        claims=claims,
        service=service,
    )


@router.get(
    "/{id}/reporting",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Get employee reporting hierarchy details",
)
async def get_employee_reporting(
    id: uuid.UUID,
    claims: Annotated[dict | None, Depends(get_current_user_claims_optional)] = None,
    service: Annotated[HierarchyService, Depends(get_hierarchy_service)] = None,
) -> APIResponse[dict]:
    """Return manager, peers, direct reports, and reporting chain (compatibility alias for /api/v1/hierarchy/{id})."""
    from app.api.hierarchy import get_employee_hierarchy_details

    res = await get_employee_hierarchy_details(
        employee_id=id,
        claims=claims,
        service=service,
    )
    payload = res.data.model_dump() if hasattr(res.data, "model_dump") else dict(res.data)
    return APIResponse[dict](
        success=True,
        message=res.message,
        data=payload,
        errors=None,
    )

