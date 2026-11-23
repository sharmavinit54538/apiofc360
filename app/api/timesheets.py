"""API routes for Timesheet Management."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status

from app.core.exceptions import AppException
from app.core.rbac import require_admin_or_manager, RoleEnum
from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims, get_current_employee, get_current_company
from app.repositories.employee_repository import EmployeeRepository
from app.models.company import Company
from app.models.employee import Employee
from sqlalchemy.ext.asyncio import AsyncSession
from app.schemas.auth import APIResponse
from app.schemas.timesheet import TimesheetResponse, TimesheetEntryCreate, TimesheetApprovalRequest
from app.services.timesheet_service import TimesheetService

router = APIRouter(prefix="/timesheets", tags=["Timesheet Management"])


async def _get_current_employee_id(claims: dict, db: AsyncSession) -> uuid.UUID:
    """Resolve current employee ID from logged-in user claims."""
    user_id_raw = claims.get("sub")
    if not user_id_raw:
        raise AppException(message="Invalid user association.", status_code=status.HTTP_401_UNAUTHORIZED)

    user_id = uuid.UUID(str(user_id_raw))
    emp_repo = EmployeeRepository(db)
    employee = await emp_repo.get_by_user_id(user_id)
    if not employee:
        raise AppException(message="Employee profile not found.", status_code=status.HTTP_404_NOT_FOUND)
    return employee.id


@router.get(
    "/weekly",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[TimesheetResponse],
    summary="Get or create weekly timesheet for current employee"
)
async def get_weekly_timesheet(
    week_start_date: date = Query(..., description="Monday date of target week"),
    claims: dict = Depends(get_current_user_claims),
    db: Annotated[Any, Depends(get_db_session)] = None,
    current_employee: Employee = Depends(get_current_employee),
    current_company: Company = Depends(get_current_company),
) -> APIResponse[TimesheetResponse]:
    employee_id = current_employee.id
    company_id = current_company.id
    service = TimesheetService(db)
    timesheet = await service.get_or_create_weekly_timesheet(employee_id, week_start_date, company_id)
    return APIResponse[TimesheetResponse](
        success=True,
        message="Weekly timesheet retrieved.",
        data=TimesheetResponse.model_validate(timesheet)
    )


@router.post(
    "/weekly",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[TimesheetResponse],
    summary="Save weekly timesheet entries"
)
async def save_weekly_entries(
    entries: list[TimesheetEntryCreate],
    week_start_date: date = Query(..., description="Monday date of target week"),
    claims: dict = Depends(get_current_user_claims),
    db: Annotated[Any, Depends(get_db_session)] = None,
    current_employee: Employee = Depends(get_current_employee),
    current_company: Company = Depends(get_current_company),
) -> APIResponse[TimesheetResponse]:
    employee_id = current_employee.id
    company_id = current_company.id
    service = TimesheetService(db)
    timesheet = await service.save_timesheet_entries(employee_id, week_start_date, entries, company_id)
    return APIResponse[TimesheetResponse](
        success=True,
        message="Timesheet entries saved successfully.",
        data=TimesheetResponse.model_validate(timesheet)
    )


@router.post(
    "/weekly/submit",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[TimesheetResponse],
    summary="Submit weekly timesheet for approval"
)
async def submit_weekly_timesheet(
    week_start_date: date = Query(..., description="Monday date of target week"),
    claims: dict = Depends(get_current_user_claims),
    db: Annotated[Any, Depends(get_db_session)] = None,
    current_employee: Employee = Depends(get_current_employee),
    current_company: Company = Depends(get_current_company),
) -> APIResponse[TimesheetResponse]:
    employee_id = current_employee.id
    company_id = current_company.id
    service = TimesheetService(db)
    timesheet = await service.submit_timesheet(employee_id, week_start_date, company_id)
    return APIResponse[TimesheetResponse](
        success=True,
        message="Timesheet submitted for approval.",
        data=TimesheetResponse.model_validate(timesheet)
    )


@router.get(
    "/history",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[list[TimesheetResponse]],
    summary="Get timesheet history for current employee"
)
async def get_history(
    claims: dict = Depends(get_current_user_claims),
    db: Annotated[Any, Depends(get_db_session)] = None,
    current_employee: Employee = Depends(get_current_employee),
    current_company: Company = Depends(get_current_company),
) -> APIResponse[list[TimesheetResponse]]:
    employee_id = current_employee.id
    company_id = current_company.id
    service = TimesheetService(db)
    history = await service.get_employee_timesheet_history(employee_id, company_id)
    return APIResponse[list[TimesheetResponse]](
        success=True,
        message="Timesheet history retrieved.",
        data=[TimesheetResponse.model_validate(t) for t in history]
    )


@router.get(
    "/pending",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[list[TimesheetResponse]],
    summary="Get all timesheets pending approval (tenant-isolated, role-filtered)"
)
async def get_pending(
    claims: dict = Depends(get_current_user_claims),
    db: Annotated[Any, Depends(get_db_session)] = None,
    current_employee: Employee = Depends(get_current_employee),
    current_company: Company = Depends(get_current_company),
) -> APIResponse[list[TimesheetResponse]]:
    role = (claims.get("role") or "").lower().strip()
    if role not in (RoleEnum.SUPER_ADMIN.value, RoleEnum.HR_ADMIN.value, RoleEnum.MANAGER.value, RoleEnum.EXECUTIVE.value):
        raise AppException(message="Access denied. Managers or Admins only.", status_code=status.HTTP_403_FORBIDDEN)

    company_id = current_company.id
    reviewer_employee_id = current_employee.id
    service = TimesheetService(db)
    pending = await service.get_pending_timesheets_for_review(company_id, reviewer_employee_id, role)
    return APIResponse[list[TimesheetResponse]](
        success=True,
        message="Pending timesheets retrieved.",
        data=[TimesheetResponse.model_validate(t) for t in pending]
    )


@router.post(
    "/{timesheet_id}/review",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[TimesheetResponse],
    summary="Approve or reject a timesheet (tenant-isolated, authorization-checked)"
)
async def review_timesheet(
    timesheet_id: uuid.UUID,
    review: TimesheetApprovalRequest,
    claims: dict = Depends(get_current_user_claims),
    db: Annotated[Any, Depends(get_db_session)] = None,
    current_employee: Employee = Depends(get_current_employee),
    current_company: Company = Depends(get_current_company),
) -> APIResponse[TimesheetResponse]:
    role = (claims.get("role") or "").lower().strip()
    if role not in (RoleEnum.SUPER_ADMIN.value, RoleEnum.HR_ADMIN.value, RoleEnum.MANAGER.value, RoleEnum.EXECUTIVE.value):
        raise AppException(message="Access denied. Managers or Admins only.", status_code=status.HTTP_403_FORBIDDEN)

    user_id = uuid.UUID(claims["sub"])
    company_id = current_company.id
    reviewer_employee_id = current_employee.id

    service = TimesheetService(db)
    timesheet = await service.review_timesheet(
        timesheet_id=timesheet_id,
        status=review.status,
        approved_by_id=user_id,
        rejection_reason=review.rejection_reason,
        company_id=company_id,
        reviewer_employee_id=reviewer_employee_id,
        reviewer_role=role
    )
    return APIResponse[TimesheetResponse](
        success=True,
        message=f"Timesheet successfully {review.status.lower()}.",
        data=TimesheetResponse.model_validate(timesheet)
    )