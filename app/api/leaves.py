"""API routes for Leave Management."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, status

from app.core.exceptions import AppException
from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.repositories.employee_repository import EmployeeRepository
from app.schemas.auth import APIResponse
from app.schemas.leave import LeaveRequestResponse, LeaveRequestCreate, LeaveApprovalRequest, LeaveBalanceResponse
from app.services.leave_service import LeaveService

router = APIRouter(prefix="/leaves", tags=["Leave Management"])


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
    summary="Get current employee's leave balances"
)
async def get_balances(
    claims: dict = Depends(get_current_user_claims),
    db: Any = Depends(get_db_session)
) -> APIResponse[list[LeaveBalanceResponse]]:
    employee_id = await _get_current_employee_id(claims, db)
    service = LeaveService(db)
    balances = await service.get_leave_balances(employee_id)
    return APIResponse[list[LeaveBalanceResponse]](
        success=True,
        message="Leave balances retrieved.",
        data=balances
    )


@router.post(
    "/apply",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[LeaveRequestResponse],
    summary="Apply for leave"
)
async def apply_leave(
    body: LeaveRequestCreate,
    claims: dict = Depends(get_current_user_claims),
    db: Any = Depends(get_db_session)
) -> APIResponse[LeaveRequestResponse]:
    employee_id = await _get_current_employee_id(claims, db)
    service = LeaveService(db)
    leave = await service.apply_leave(employee_id, body)
    return APIResponse[LeaveRequestResponse](
        success=True,
        message="Leave applied successfully.",
        data=LeaveRequestResponse.model_validate(leave)
    )


@router.get(
    "/history",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[list[LeaveRequestResponse]],
    summary="Get leave history for current employee"
)
async def get_history(
    claims: dict = Depends(get_current_user_claims),
    db: Any = Depends(get_db_session)
) -> APIResponse[list[LeaveRequestResponse]]:
    employee_id = await _get_current_employee_id(claims, db)
    service = LeaveService(db)
    history = await service.get_employee_leaves(employee_id)
    return APIResponse[list[LeaveRequestResponse]](
        success=True,
        message="Leave history retrieved.",
        data=[LeaveRequestResponse.model_validate(l) for l in history]
    )


@router.get(
    "/pending",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[list[LeaveRequestResponse]],
    summary="Get all leaves pending approval"
)
async def get_pending(
    claims: dict = Depends(get_current_user_claims),
    db: Any = Depends(get_db_session)
) -> APIResponse[list[LeaveRequestResponse]]:
    role = claims.get("role", "").lower()
    if role not in ("super_admin", "hr_admin", "manager"):
        raise AppException(message="Access denied. Managers or Admins only.", status_code=status.HTTP_403_FORBIDDEN)
    
    company_id_raw = claims.get("company_id")
    if not company_id_raw:
        raise AppException(message="Your account is not associated with a company.", status_code=status.HTTP_403_FORBIDDEN)
    company_id = uuid.UUID(str(company_id_raw))

    service = LeaveService(db)
    pending = await service.get_pending_leaves(company_id)
    return APIResponse[list[LeaveRequestResponse]](
        success=True,
        message="Pending leaves retrieved.",
        data=[LeaveRequestResponse.model_validate(l) for l in pending]
    )


@router.post(
    "/{leave_id}/review",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[LeaveRequestResponse],
    summary="Approve or reject a leave request"
)
async def review_leave(
    leave_id: uuid.UUID,
    review: LeaveApprovalRequest,
    claims: dict = Depends(get_current_user_claims),
    db: Any = Depends(get_db_session)
) -> APIResponse[LeaveRequestResponse]:
    role = claims.get("role", "").lower()
    if role not in ("super_admin", "hr_admin", "manager"):
        raise AppException(message="Access denied. Managers or Admins only.", status_code=status.HTTP_403_FORBIDDEN)
    
    user_id = uuid.UUID(claims["sub"])
    service = LeaveService(db)
    leave = await service.review_leave(
        leave_id=leave_id,
        status=review.status,
        approved_by_id=user_id,
        rejection_reason=review.rejection_reason
    )
    return APIResponse[LeaveRequestResponse](
        success=True,
        message=f"Leave request successfully {review.status.lower()}.",
        data=LeaveRequestResponse.model_validate(leave)
    )


@router.get(
    "/balances/{employee_id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[list[LeaveBalanceResponse]],
    summary="Get leave balances for a specific employee (Admin/Manager only)"
)
async def get_employee_balances(
    employee_id: uuid.UUID,
    claims: dict = Depends(get_current_user_claims),
    db: Any = Depends(get_db_session)
) -> APIResponse[list[LeaveBalanceResponse]]:
    role = claims.get("role", "").lower()
    if role not in ("super_admin", "hr_admin", "manager"):
        raise AppException(message="Access denied. Admin or Manager only.", status_code=status.HTTP_403_FORBIDDEN)
    
    service = LeaveService(db)
    balances = await service.get_leave_balances(employee_id)
    return APIResponse[list[LeaveBalanceResponse]](
        success=True,
        message="Employee leave balances retrieved.",
        data=balances
    )
