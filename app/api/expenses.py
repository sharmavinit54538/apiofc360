"""Expense Management API v1 — Reimbursement claims with full approval workflow."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.auth import APIResponse
from app.schemas.expenses import (
    ExpenseCreate,
    ExpenseFilters,
    ExpensePage,
    ExpensePayment,
    ExpenseReason,
    ExpenseResponse,
    ExpenseStatusUpdate,
    ExpenseUpdate,
)
from app.services.expense_access import resolve_expense_actor
from app.services.expense_service import ExpenseService

router = APIRouter(prefix="/expenses", tags=["Expense Management v1"])


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ExpensePage],
    summary="List expense claims with pagination and filters",
)
async def list_expenses(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    status_filter: str | None = Query(None, alias="status", description="Filter by status"),
    employee_id: uuid.UUID | None = Query(None, description="Filter by employee"),
    category: str | None = Query(None, description="Filter by category"),
    date_from: str | None = Query(None, description="Start date (YYYY-MM-DD)"),
    date_to: str | None = Query(None, description="End date (YYYY-MM-DD)"),
    search: str | None = Query(None, description="Search in description, merchant, category"),
    sort_by: str = Query("created_at", description="Sort field"),
    sort_order: str = Query("desc", description="Sort order: asc or desc"),
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[ExpensePage]:
    """Retrieve paginated expense claims with tenant-scoped access control."""
    actor = await resolve_expense_actor(db, claims)
    service = ExpenseService(db, actor)

    from datetime import date
    filters = ExpenseFilters(
        page=page,
        limit=limit,
        status=status_filter,
        employee_id=employee_id,
        category=category,
        date_from=date.fromisoformat(date_from) if date_from else None,
        date_to=date.fromisoformat(date_to) if date_to else None,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    result = await service.list(filters)
    return APIResponse[ExpensePage](
        success=True,
        message="Expenses retrieved successfully.",
        data=ExpensePage(**result),
        errors=None,
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[ExpenseResponse],
    summary="Create a new expense claim",
)
async def create_expense(
    payload: ExpenseCreate,
    submitted: bool = Query(False, description="Submit immediately instead of saving as draft"),
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[ExpenseResponse]:
    """Create a new expense claim. Defaults to DRAFT unless submitted=true."""
    actor = await resolve_expense_actor(db, claims)
    service = ExpenseService(db, actor)
    claim = await service.create(payload, submitted=submitted)
    return APIResponse[ExpenseResponse](
        success=True,
        message="Expense claim created successfully.",
        data=ExpenseService.serialize(claim),
        errors=None,
    )


@router.get(
    "/{expense_id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ExpenseResponse],
    summary="Get expense claim by ID",
)
async def get_expense(
    expense_id: uuid.UUID,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[ExpenseResponse]:
    """Retrieve a single expense claim with full details."""
    actor = await resolve_expense_actor(db, claims)
    service = ExpenseService(db, actor)
    claim = await service.get(expense_id)
    return APIResponse[ExpenseResponse](
        success=True,
        message="Expense retrieved successfully.",
        data=ExpenseService.serialize(claim),
        errors=None,
    )


@router.patch(
    "/{expense_id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ExpenseResponse],
    summary="Update an expense claim (draft or changes_requested only)",
)
async def update_expense(
    expense_id: uuid.UUID,
    payload: ExpenseUpdate,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[ExpenseResponse]:
    """Update expense fields. Only allowed for DRAFT or CHANGES_REQUESTED status."""
    actor = await resolve_expense_actor(db, claims)
    service = ExpenseService(db, actor)
    claim = await service.update(expense_id, payload)
    return APIResponse[ExpenseResponse](
        success=True,
        message="Expense updated successfully.",
        data=ExpenseService.serialize(claim),
        errors=None,
    )


@router.delete(
    "/{expense_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an expense claim (draft, changes_requested, or rejected only)",
)
async def delete_expense(
    expense_id: uuid.UUID,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> None:
    """Soft-delete an expense claim. Only allowed for non-approved states."""
    actor = await resolve_expense_actor(db, claims)
    service = ExpenseService(db, actor)
    await service.delete(expense_id)


@router.post(
    "/{expense_id}/submit",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ExpenseResponse],
    summary="Submit a draft expense for approval",
)
async def submit_expense(
    expense_id: uuid.UUID,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[ExpenseResponse]:
    """Transition a DRAFT expense to SUBMITTED status."""
    actor = await resolve_expense_actor(db, claims)
    service = ExpenseService(db, actor)
    claim = await service.transition(expense_id, "SUBMITTED")
    return APIResponse[ExpenseResponse](
        success=True,
        message="Expense submitted for approval.",
        data=ExpenseService.serialize(claim),
        errors=None,
    )


@router.post(
    "/{expense_id}/approve",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ExpenseResponse],
    summary="Approve a submitted expense",
)
async def approve_expense(
    expense_id: uuid.UUID,
    payload: ExpenseReason | None = None,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[ExpenseResponse]:
    """Approve a SUBMITTED expense. Requires review permission (not self)."""
    actor = await resolve_expense_actor(db, claims)
    service = ExpenseService(db, actor)
    reason = payload.reason if payload else None
    claim = await service.transition(expense_id, "APPROVED", reason=reason)
    return APIResponse[ExpenseResponse](
        success=True,
        message="Expense approved successfully.",
        data=ExpenseService.serialize(claim),
        errors=None,
    )


@router.post(
    "/{expense_id}/reject",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ExpenseResponse],
    summary="Reject a submitted expense",
)
async def reject_expense(
    expense_id: uuid.UUID,
    payload: ExpenseReason,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[ExpenseResponse]:
    """Reject a SUBMITTED expense with mandatory reason. Requires review permission (not self)."""
    actor = await resolve_expense_actor(db, claims)
    service = ExpenseService(db, actor)
    claim = await service.transition(expense_id, "REJECTED", reason=payload.reason)
    return APIResponse[ExpenseResponse](
        success=True,
        message="Expense rejected.",
        data=ExpenseService.serialize(claim),
        errors=None,
    )


@router.post(
    "/{expense_id}/request-changes",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ExpenseResponse],
    summary="Request changes on a submitted expense",
)
async def request_changes_expense(
    expense_id: uuid.UUID,
    payload: ExpenseReason,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[ExpenseResponse]:
    """Request changes on a SUBMITTED expense with mandatory reason. Requires review permission (not self)."""
    actor = await resolve_expense_actor(db, claims)
    service = ExpenseService(db, actor)
    claim = await service.transition(expense_id, "CHANGES_REQUESTED", reason=payload.reason)
    return APIResponse[ExpenseResponse](
        success=True,
        message="Changes requested on expense.",
        data=ExpenseService.serialize(claim),
        errors=None,
    )


@router.post(
    "/{expense_id}/mark-paid",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ExpenseResponse],
    summary="Mark an approved expense as paid",
)
async def mark_paid_expense(
    expense_id: uuid.UUID,
    payload: ExpensePayment,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[ExpenseResponse]:
    """Record payment for an APPROVED expense. Requires explicit expenses:pay permission."""
    actor = await resolve_expense_actor(db, claims)
    service = ExpenseService(db, actor)
    claim = await service.transition(expense_id, "PAID", payment=payload)
    return APIResponse[ExpenseResponse](
        success=True,
        message="Expense marked as paid.",
        data=ExpenseService.serialize(claim),
        errors=None,
    )


@router.patch(
    "/{expense_id}/status",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ExpenseResponse],
    summary="Generic status transition for an expense",
)
async def update_expense_status(
    expense_id: uuid.UUID,
    payload: ExpenseStatusUpdate,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[ExpenseResponse]:
    """Unified status transition endpoint supporting all valid transitions with validation."""
    actor = await resolve_expense_actor(db, claims)
    service = ExpenseService(db, actor)

    payment = None
    if payload.status == "paid":
        if not payload.payment_reference or not payload.payment_method or not payload.paid_at:
            from fastapi import HTTPException
            raise HTTPException(422, "Payment reference, method, and timestamp are required for paid transition.")
        payment = ExpensePayment(
            payment_reference=payload.payment_reference,
            payment_method=payload.payment_method,
            paid_at=payload.paid_at,
        )

    claim = await service.transition(
        expense_id,
        payload.status.upper(),
        reason=payload.reason,
        payment=payment,
    )
    return APIResponse[ExpenseResponse](
        success=True,
        message=f"Expense status updated to {payload.status}.",
        data=ExpenseService.serialize(claim),
        errors=None,
    )