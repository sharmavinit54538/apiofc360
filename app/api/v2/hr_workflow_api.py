"""API v2 router for the AI Workflow Automation Engine."""

from __future__ import annotations

import uuid
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.auth import APIResponse
from app.services.hr_workflow_service import HRWorkflowService
from app.models.hr_workflow import HRWorkflowStepInstance

import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/workflows", tags=["AI Workflow Automation v2"])


# Schemas
class DefinitionRequest(BaseModel):
    name: str = Field(..., min_length=2)
    trigger_event: str = Field(..., description="LEAVE_REQUESTED | PAYROLL_RUN_COMPLETED | OFFER_CREATED")
    rule_criteria: Optional[dict] = None

class TriggerRequest(BaseModel):
    trigger_event: str
    context_id: uuid.UUID
    context_data: dict

class DecisionRequest(BaseModel):
    action: str = Field(..., description="APPROVED | REJECTED")
    notes: Optional[str] = None


@router.post(
    "/definitions",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[dict],
    summary="Register a new workflow rule definition",
)
async def create_definition(
    body: DefinitionRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Sets up a trigger configuration with JSON rule criteria thresholds."""
    service = HRWorkflowService(db)
    definition = await service.register_workflow_definition(
        name=body.name,
        trigger_event=body.trigger_event,
        rule_criteria=body.rule_criteria
    )
    return APIResponse[dict](
        success=True,
        message="Workflow rule definition created.",
        data={
            "definition_id": str(definition.id),
            "name": definition.name,
            "trigger_event": definition.trigger_event,
            "is_active": definition.is_active,
        },
        errors=None
    )


@router.post(
    "/trigger",
    response_model=APIResponse[dict],
    summary="Manually trigger a workflow process instance",
)
async def trigger_workflow(
    body: TriggerRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Kicks off a workflow instance, evaluates criteria matching, and triggers AI audit steps."""
    service = HRWorkflowService(db)
    instance = await service.trigger_event_workflow(
        event_name=body.trigger_event,
        context_id=body.context_id,
        context_data=body.context_data
    )

    if not instance:
        return APIResponse[dict](
            success=False,
            message="Workflow did not trigger. Event mismatch or rule engine criteria not met.",
            data=None,
            errors=None
        )

    return APIResponse[dict](
        success=True,
        message="Workflow instance triggered successfully.",
        data={
            "instance_id": str(instance.id),
            "status": instance.status,
            "current_step": instance.current_step_order,
        },
        errors=None
    )


@router.patch(
    "/steps/{step_id}/decision",
    response_model=APIResponse[dict],
    summary="Submit approval or rejection step decision",
)
async def submit_decision(
    step_id: uuid.UUID,
    body: DecisionRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Logs human manager approval action and transitions the workflow status."""
    user_id = uuid.UUID(claims["sub"]) if claims else None
    service = HRWorkflowService(db)
    try:
        success = await service.evaluate_step_decision(
            step_id=step_id,
            action=body.action,
            notes=body.notes,
            user_id=user_id
        )
    except ValueError as val_err:
        raise HTTPException(status_code=400, detail=str(val_err))

    if not success:
        raise HTTPException(status_code=404, detail="Workflow step not found.")

    return APIResponse[dict](
        success=True,
        message=f"Workflow step evaluation registered as: {body.action}",
        data={"step_id": str(step_id)},
        errors=None
    )


@router.get(
    "/instances/my-pending",
    response_model=APIResponse[list[dict]],
    summary="Get pending approval workflow steps assigned to user",
)
async def get_my_pending(
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[list[dict]]:
    """Retrieves all pending approval instances that require input from the authenticated user."""
    user_id = uuid.UUID(claims["sub"]) if claims else None
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication claims required to retrieve approvals.")

    stmt = (
        select(HRWorkflowStepInstance)
        .options(selectinload(HRWorkflowStepInstance.instance).selectinload(HRWorkflowInstance.definition))
        .where(
            HRWorkflowStepInstance.status == "PENDING",
            HRWorkflowStepInstance.assigned_to_user_id == user_id
        )
    )
    res = await db.execute(stmt)
    steps = res.scalars().all()

    data = [
        {
            "step_id": str(s.id),
            "step_name": s.step_name,
            "step_order": s.step_order,
            "workflow_name": s.instance.definition.name,
            "context_id": str(s.instance.context_id),
            "instance_status": s.instance.status,
        }
        for s in steps
    ]

    return APIResponse[list[dict]](
        success=True,
        message="Pending approval tasks retrieved.",
        data=data,
        errors=None
    )
