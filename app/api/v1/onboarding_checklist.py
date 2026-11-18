"""Onboarding Checklist API v1 — Employee self-service checklist."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.models.employee_onboarding import OnboardingTaskChecklist
from app.models.employee import Employee
from app.schemas.auth import APIResponse

router = APIRouter(prefix="/onboarding-checklist", tags=["Onboarding Checklist"])


class ChecklistItemResponse(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    category: str
    task_key: str
    title: str
    owner_role: str
    status: str
    is_required: bool
    due_date: str | None = None
    details_json: dict | None = None
    completed_by: uuid.UUID | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ChecklistResponse(BaseModel):
    employee_id: uuid.UUID
    employee_name: str
    completion_percentage: float
    completed_tasks: int
    total_tasks: int
    items: list[ChecklistItemResponse]


class ChecklistItemUpdate(BaseModel):
    status: str = Field(pattern="^(PENDING|IN_PROGRESS|COMPLETED|BLOCKED)$")
    details_json: dict | None = None


async def get_current_employee(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> Employee:
    """Get current employee from claims."""
    user_id_str = claims.get("sub")
    if not user_id_str:
        raise HTTPException(status_code=401, detail="Invalid authentication claims")
    user_id = uuid.UUID(user_id_str)

    emp_stmt = select(Employee).where(
        Employee.user_id == user_id,
        Employee.is_deleted == False,
    )
    emp_res = await db.execute(emp_stmt)
    employee = emp_res.scalar_one_or_none()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee profile not found")
    return employee


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ChecklistResponse],
    summary="Get employee's onboarding checklist",
)
async def get_onboarding_checklist(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[ChecklistResponse]:
    """Fetch the authenticated employee's onboarding checklist items."""
    employee = await get_current_employee(claims, db)

    # Get all checklist items for this employee
    stmt = select(OnboardingTaskChecklist).where(
        OnboardingTaskChecklist.employee_id == employee.id
    ).order_by(OnboardingTaskChecklist.category, OnboardingTaskChecklist.task_key)
    result = await db.execute(stmt)
    tasks = result.scalars().all()

    required = [task for task in tasks if task.is_required]
    completed = [task for task in required if task.status == "COMPLETED"]
    percentage = round(len(completed) * 100 / len(required), 2) if required else 100.0

    items = []
    for task in tasks:
        items.append(ChecklistItemResponse(
            id=task.id,
            employee_id=task.employee_id,
            category=task.category,
            task_key=task.task_key,
            title=task.title,
            owner_role=task.owner_role,
            status=task.status,
            is_required=task.is_required,
            due_date=task.due_date.isoformat() if task.due_date else None,
            details_json=task.details_json,
            completed_by=task.completed_by,
            completed_at=task.completed_at,
            created_at=task.created_at,
            updated_at=task.updated_at,
        ))

    return APIResponse[ChecklistResponse](
        success=True,
        message="Onboarding checklist retrieved successfully.",
        data=ChecklistResponse(
            employee_id=employee.id,
            employee_name=f"{employee.first_name} {employee.last_name}".strip(),
            completion_percentage=percentage,
            completed_tasks=len(completed),
            total_tasks=len(required),
            items=items,
        ),
        errors=None,
    )


@router.patch(
    "/{checklist_id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ChecklistItemResponse],
    summary="Update onboarding checklist item",
)
async def update_checklist_item(
    checklist_id: uuid.UUID,
    payload: ChecklistItemUpdate,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[ChecklistItemResponse]:
    """Update a checklist item status (employee can mark their tasks as completed)."""
    employee = await get_current_employee(claims, db)

    stmt = select(OnboardingTaskChecklist).where(
        OnboardingTaskChecklist.id == checklist_id,
        OnboardingTaskChecklist.employee_id == employee.id,
    )
    result = await db.execute(stmt)
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Checklist item not found")

    # Validate status transition
    valid_transitions = {
        "PENDING": ["IN_PROGRESS", "COMPLETED", "BLOCKED"],
        "IN_PROGRESS": ["COMPLETED", "BLOCKED", "PENDING"],
        "COMPLETED": ["PENDING", "IN_PROGRESS"],  # Allow reopening
        "BLOCKED": ["PENDING", "IN_PROGRESS"],
    }
    if payload.status not in valid_transitions.get(task.status, []):
        raise HTTPException(
            status_code=409,
            detail=f"Invalid status transition from {task.status} to {payload.status}",
        )

    task.status = payload.status
    if payload.details_json is not None:
        task.details_json = payload.details_json

    if payload.status == "COMPLETED":
        task.completed_by = uuid.UUID(claims["sub"])
        task.completed_at = datetime.now(timezone.utc)
    elif task.status == "COMPLETED" and payload.status != "COMPLETED":
        task.completed_by = None
        task.completed_at = None

    task.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(task)

    return APIResponse[ChecklistItemResponse](
        success=True,
        message="Checklist item updated successfully.",
        data=ChecklistItemResponse(
            id=task.id,
            employee_id=task.employee_id,
            category=task.category,
            task_key=task.task_key,
            title=task.title,
            owner_role=task.owner_role,
            status=task.status,
            is_required=task.is_required,
            due_date=task.due_date.isoformat() if task.due_date else None,
            details_json=task.details_json,
            completed_by=task.completed_by,
            completed_at=task.completed_at,
            created_at=task.created_at,
            updated_at=task.updated_at,
        ),
        errors=None,
    )