"""API routes for Leave Management."""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, Query, status

from app.core.exceptions import AppException, NotFoundException
from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.repositories.employee_repository import EmployeeRepository
from app.schemas.auth import APIResponse
from app.schemas.leave import (
    LeaveApprovalRequest,
    LeaveBalanceResponse,
    LeaveEmployeeItem,
    LeaveRequestCreate,
    LeaveRequestResponse,
)
from app.services.leave_service import LeaveService

router = APIRouter(prefix="/leaves", tags=["Leave Management"])


def _resolve_company_id(claims: dict) -> uuid.UUID:
    """Resolve caller's company UUID or reject with 403."""
    cid_raw = claims.get("company_id")
    if not cid_raw:
        raise AppException(
            message="Your account is not associated with an active company context.",
            status_code=status.HTTP_403_FORBIDDEN,
        )
    try:
        return uuid.UUID(str(cid_raw))
    except (ValueError, TypeError):
        raise AppException(
            message="Invalid company association.",
            status_code=status.HTTP_403_FORBIDDEN,
        )


async def _get_current_employee_id(claims: dict, db: Any) -> uuid.UUID:
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
    "/balances",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[list[LeaveBalanceResponse]],
    summary="Get current employee's leave balances",
)
async def get_balances(
    claims: dict = Depends(get_current_user_claims),
    db: Any = Depends(get_db_session),
) -> APIResponse[list[LeaveBalanceResponse]]:
    employee_id = await _get_current_employee_id(claims, db)
    service = LeaveService(db)
    balances = await service.get_leave_balances(employee_id)
    return APIResponse[list[LeaveBalanceResponse]](
        success=True,
        message="Leave balances retrieved.",
        data=balances,
    )


@router.post(
    "/apply",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[LeaveRequestResponse],
    summary="Apply for leave",
)
async def apply_leave(
    body: LeaveRequestCreate,
    claims: dict = Depends(get_current_user_claims),
    db: Any = Depends(get_db_session),
) -> APIResponse[LeaveRequestResponse]:
    employee_id = await _get_current_employee_id(claims, db)
    role = claims.get("role", "employee")
    service = LeaveService(db)
    leave = await service.apply_leave(employee_id, body, role=role)
    return APIResponse[LeaveRequestResponse](
        success=True,
        message="Leave applied successfully.",
        data=LeaveRequestResponse.model_validate(leave),
    )


@router.get(
    "/history",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[list[LeaveRequestResponse]],
    summary="Get leave history for current employee",
)
async def get_history(
    claims: dict = Depends(get_current_user_claims),
    db: Any = Depends(get_db_session),
) -> APIResponse[list[LeaveRequestResponse]]:
    employee_id = await _get_current_employee_id(claims, db)
    service = LeaveService(db)
    history = await service.get_employee_leaves(employee_id)
    return APIResponse[list[LeaveRequestResponse]](
        success=True,
        message="Leave history retrieved.",
        data=[LeaveRequestResponse.model_validate(l) for l in history],
    )


@router.get(
    "/pending",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[list[LeaveRequestResponse]],
    summary="Get all leaves pending approval",
)
async def get_pending(
    claims: dict = Depends(get_current_user_claims),
    db: Any = Depends(get_db_session),
) -> APIResponse[list[LeaveRequestResponse]]:
    role = claims.get("role", "").lower()
    if role not in ("super_admin", "hr_admin", "manager"):
        raise AppException(message="Access denied. Managers or Admins only.", status_code=status.HTTP_403_FORBIDDEN)

    company_id = _resolve_company_id(claims)
    caller_user_id = uuid.UUID(str(claims["sub"]))

    service = LeaveService(db)
    pending = await service.get_pending_leaves(
        company_id=company_id, caller_user_id=caller_user_id, caller_role=role
    )
    return APIResponse[list[LeaveRequestResponse]](
        success=True,
        message="Pending leaves retrieved.",
        data=[LeaveRequestResponse.model_validate(l) for l in pending],
    )


@router.get(
    "/employees",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[list[LeaveEmployeeItem]],
    summary="List company employees (HR Admin only)",
)
async def get_company_employees(
    q: Optional[str] = Query(None, description="Search by name, employee code, department, or designation"),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    claims: dict = Depends(get_current_user_claims),
    db: Any = Depends(get_db_session),
) -> APIResponse[list[LeaveEmployeeItem]]:
    role = claims.get("role", "").lower()
    if role not in ("super_admin", "hr_admin"):
        raise AppException(message="Access denied. HR Admins only.", status_code=status.HTTP_403_FORBIDDEN)

    company_id = _resolve_company_id(claims)
    service = LeaveService(db)
    employees = await service.get_company_employees(company_id=company_id, search=q, page=page, limit=limit)
    return APIResponse[list[LeaveEmployeeItem]](
        success=True,
        message="Company employees retrieved.",
        data=employees,
    )


@router.get(
    "/balances/{employee_id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[list[LeaveBalanceResponse]],
    summary="Get leave balances for a specific employee (Admin/Manager only)",
)
async def get_employee_balances(
    employee_id: uuid.UUID,
    claims: dict = Depends(get_current_user_claims),
    db: Any = Depends(get_db_session),
) -> APIResponse[list[LeaveBalanceResponse]]:
    role = claims.get("role", "").lower()
    if role not in ("super_admin", "hr_admin", "manager"):
        raise AppException(message="Access denied. Admin or Manager only.", status_code=status.HTTP_403_FORBIDDEN)

    company_id = _resolve_company_id(claims)
    service = LeaveService(db)

    # Tenant isolation: verify target employee belongs to caller's company
    target_emp = await service.repo.get_employee_by_id(employee_id)
    if not target_emp or target_emp.company_id != company_id:
        raise NotFoundException(message="Employee profile not found.")

    balances = await service.get_leave_balances(employee_id)
    return APIResponse[list[LeaveBalanceResponse]](
        success=True,
        message="Employee leave balances retrieved.",
        data=balances,
    )


@router.post(
    "/{leave_id}/review",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[LeaveRequestResponse],
    summary="Approve or reject a leave request",
)
async def review_leave(
    leave_id: uuid.UUID,
    review: LeaveApprovalRequest,
    claims: dict = Depends(get_current_user_claims),
    db: Any = Depends(get_db_session),
) -> APIResponse[LeaveRequestResponse]:
    role = claims.get("role", "").lower()
    if role not in ("super_admin", "hr_admin", "manager"):
        raise AppException(message="Access denied. Managers or Admins only.", status_code=status.HTTP_403_FORBIDDEN)

    company_id = _resolve_company_id(claims)
    user_id = uuid.UUID(str(claims["sub"]))

    service = LeaveService(db)
    leave = await service.review_leave(
        leave_id=leave_id,
        status=review.status,
        reviewer_user_id=user_id,
        reviewer_role=role,
        reviewer_company_id=company_id,
        rejection_reason=review.rejection_reason,
    )
    return APIResponse[LeaveRequestResponse](
        success=True,
        message=f"Leave request successfully {review.status.lower()}.",
        data=LeaveRequestResponse.model_validate(leave),
    )


@router.post(
    "/{leave_id}/cancel",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[LeaveRequestResponse],
    summary="Cancel a leave request",
)
async def cancel_leave(
    leave_id: uuid.UUID,
    claims: dict = Depends(get_current_user_claims),
    db: Any = Depends(get_db_session),
) -> APIResponse[LeaveRequestResponse]:
    company_id = _resolve_company_id(claims)
    user_id = uuid.UUID(str(claims["sub"]))
    role = claims.get("role", "employee").lower()

    service = LeaveService(db)
    leave = await service.cancel_leave(
        leave_id=leave_id,
        caller_user_id=user_id,
        caller_role=role,
        caller_company_id=company_id,
    )
    return APIResponse[LeaveRequestResponse](
        success=True,
        message="Leave request cancelled successfully.",
        data=LeaveRequestResponse.model_validate(leave),
    )
