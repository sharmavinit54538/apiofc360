"""Autopilot HR Automation API v2 — 24 endpoints for rules, exceptions, agent, audit, alerts, onboarding, payroll."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v2.enterprise_dependencies import company_id as _tenant_id, user_id as _actor_id
from app.db.database import get_db_session
from app.schemas.autopilot import (
    AgentActionCancel,
    AgentActionConfirm,
    AgentActionProposal,
    AgentChatRequest,
    AgentChatResponse,
    AutopilotAlertCreateTask,
    AutopilotAlertResponse,
    AutopilotAlertSnooze,
    AutopilotAuditOverrideRequest,
    AutopilotAuditResponse,
    AutopilotAuditUndoRequest,
    AutopilotExceptionDecision,
    AutopilotExceptionResponse,
    AutopilotOverviewResponse,
    AutopilotRuleCreate,
    AutopilotRuleResponse,
    AutopilotRuleSimulateRequest,
    AutopilotRuleSimulateResponse,
    AutopilotRuleUpdate,
    AutopilotSettingsCreate,
    AutopilotSettingsResponse,
    AutopilotSettingsUpdate,
    OnboardingRetryRequest,
    OnboardingRunDetailResponse,
    OnboardingRunResponse,
    PayrollAutomationStatusResponse,
)
from app.schemas.auth import APIResponse
from app.services.autopilot_service import AutopilotService

router = APIRouter(prefix="/autopilot", tags=["Autopilot HR v2"])


def _ok(data: Any, message: str = "Operation successful") -> dict[str, Any]:
    return {"success": True, "data": data, "message": message}


# ── Settings ────────────────────────────────────────────────────────────────────

@router.get(
    "/settings",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[AutopilotSettingsResponse],
    summary="Get autopilot HR automation settings",
)
async def get_autopilot_settings(
    claims: Annotated[dict, Depends(_tenant_id)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[AutopilotSettingsResponse]:
    """Retrieve organization-specific automation settings."""
    company_uuid = _tenant_id(claims)
    actor_uuid = _actor_id(claims)
    service = AutopilotService(db, company_uuid, actor_uuid)
    data = await service.get_settings()
    return APIResponse[AutopilotSettingsResponse](
        success=True,
        message="Autopilot settings retrieved successfully.",
        data=AutopilotSettingsResponse(**data),
        errors=None,
    )


@router.put(
    "/settings",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[AutopilotSettingsResponse],
    summary="Update autopilot HR automation settings",
)
async def update_autopilot_settings(
    payload: AutopilotSettingsUpdate,
    claims: Annotated[dict, Depends(_tenant_id)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[AutopilotSettingsResponse]:
    """Update organization-specific automation settings."""
    company_uuid = _tenant_id(claims)
    actor_uuid = _actor_id(claims)
    service = AutopilotService(db, company_uuid, actor_uuid)
    data = await service.update_settings(payload.model_dump(exclude_unset=True))
    return APIResponse[AutopilotSettingsResponse](
        success=True,
        message="Autopilot settings updated successfully.",
        data=AutopilotSettingsResponse(**data),
        errors=None,
    )


# ── Rules CRUD ──────────────────────────────────────────────────────────────────

@router.get(
    "/rules",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="List automation rules",
)
async def list_autopilot_rules(
    domain: str | None = Query(None, description="Filter by domain"),
    enabled: bool | None = Query(None, description="Filter by enabled status"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    search: str | None = Query(None, description="Search in name/description"),
    claims: Annotated[dict, Depends(_tenant_id)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """List automation rules with pagination and filters."""
    company_uuid = _tenant_id(claims)
    actor_uuid = _actor_id(claims)
    service = AutopilotService(db, company_uuid, actor_uuid)
    result = await service.list_rules(domain=domain, enabled=enabled, page=page, limit=limit, search=search)
    return APIResponse[dict](success=True, message="Rules retrieved successfully.", data=result, errors=None)


@router.post(
    "/rules",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[AutopilotRuleResponse],
    summary="Create a new automation rule",
)
async def create_autopilot_rule(
    payload: AutopilotRuleCreate,
    claims: Annotated[dict, Depends(_tenant_id)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[AutopilotRuleResponse]:
    """Create a new automation rule with conditions, triggers, and actions."""
    company_uuid = _tenant_id(claims)
    actor_uuid = _actor_id(claims)
    service = AutopilotService(db, company_uuid, actor_uuid)
    rule = await service.create_rule(payload.model_dump())
    return APIResponse[AutopilotRuleResponse](
        success=True,
        message="Automation rule created successfully.",
        data=AutopilotRuleResponse(**service._serialize_rule(rule)),
        errors=None,
    )


@router.get(
    "/rules/{rule_id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[AutopilotRuleResponse],
    summary="Get automation rule by ID",
)
async def get_autopilot_rule(
    rule_id: uuid.UUID,
    claims: Annotated[dict, Depends(_tenant_id)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[AutopilotRuleResponse]:
    """Retrieve a single automation rule with full details."""
    company_uuid = _tenant_id(claims)
    actor_uuid = _actor_id(claims)
    service = AutopilotService(db, company_uuid, actor_uuid)
    rule = await service.get_rule(rule_id)
    return APIResponse[AutopilotRuleResponse](
        success=True,
        message="Rule retrieved successfully.",
        data=AutopilotRuleResponse(**service._serialize_rule(rule)),
        errors=None,
    )


@router.put(
    "/rules/{rule_id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[AutopilotRuleResponse],
    summary="Update an automation rule",
)
async def update_autopilot_rule(
    rule_id: uuid.UUID,
    payload: AutopilotRuleUpdate,
    claims: Annotated[dict, Depends(_tenant_id)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[AutopilotRuleResponse]:
    """Update automation rule conditions, triggers, actions, enable/disable."""
    company_uuid = _tenant_id(claims)
    actor_uuid = _actor_id(claims)
    service = AutopilotService(db, company_uuid, actor_uuid)
    rule = await service.update_rule(rule_id, payload.model_dump(exclude_unset=True))
    return APIResponse[AutopilotRuleResponse](
        success=True,
        message="Automation rule updated successfully.",
        data=AutopilotRuleResponse(**service._serialize_rule(rule)),
        errors=None,
    )


@router.delete(
    "/rules/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Delete an automation rule",
)
async def delete_autopilot_rule(
    rule_id: uuid.UUID,
    claims: Annotated[dict, Depends(_tenant_id)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> Response:
    """Delete an automation rule."""
    company_uuid = _tenant_id(claims)
    actor_uuid = _actor_id(claims)
    service = AutopilotService(db, company_uuid, actor_uuid)
    await service.delete_rule(rule_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/rules/simulate",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[AutopilotRuleSimulateResponse],
    summary="Simulate rule execution without side effects",
)
async def simulate_autopilot_rule(
    payload: AutopilotRuleSimulateRequest,
    claims: Annotated[dict, Depends(_tenant_id)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[AutopilotRuleSimulateResponse]:
    """Simulate a rule against provided context using authorized persisted data."""
    company_uuid = _tenant_id(claims)
    actor_uuid = _actor_id(claims)
    service = AutopilotService(db, company_uuid, actor_uuid)
    result = await service.simulate_rule(payload.rule_id, payload.entity_id, payload.context)
    return APIResponse[AutopilotRuleSimulateResponse](
        success=True,
        message="Rule simulation completed.",
        data=AutopilotRuleSimulateResponse(**result),
        errors=None,
    )


# ── Exceptions ────────────────────────────────────────────────────────────────

@router.get(
    "/exceptions",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="List automation exceptions",
)
async def list_autopilot_exceptions(
    status_filter: str | None = Query(None, alias="status", description="Filter by status"),
    domain: str | None = Query(None, description="Filter by domain"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    claims: Annotated[dict, Depends(_tenant_id)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """List automation exceptions requiring human review."""
    company_uuid = _tenant_id(claims)
    actor_uuid = _actor_id(claims)
    service = AutopilotService(db, company_uuid, actor_uuid)
    result = await service.list_exceptions(status=status_filter, domain=domain, page=page, limit=limit)
    return APIResponse[dict](success=True, message="Exceptions retrieved successfully.", data=result, errors=None)


@router.get(
    "/exceptions/{exception_id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[AutopilotExceptionResponse],
    summary="Get exception details",
)
async def get_autopilot_exception(
    exception_id: uuid.UUID,
    claims: Annotated[dict, Depends(_tenant_id)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[AutopilotExceptionResponse]:
    """Retrieve full exception details with policy trace and snapshots."""
    company_uuid = _tenant_id(claims)
    actor_uuid = _actor_id(claims)
    service = AutopilotService(db, company_uuid, actor_uuid)
    exception = await service.get_exception(exception_id)
    return APIResponse[AutopilotExceptionResponse](
        success=True,
        message="Exception retrieved successfully.",
        data=AutopilotExceptionResponse(**service._serialize_exception(exception)),
        errors=None,
    )


@router.post(
    "/exceptions/{exception_id}/decision",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[AutopilotExceptionResponse],
    summary="Decide on an automation exception",
)
async def decide_autopilot_exception(
    exception_id: uuid.UUID,
    payload: AutopilotExceptionDecision,
    claims: Annotated[dict, Depends(_tenant_id)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[AutopilotExceptionResponse]:
    """Review and decide on an exception: APPROVE, REJECT, ESCALATE, DISMISS."""
    company_uuid = _tenant_id(claims)
    actor_uuid = _actor_id(claims)
    service = AutopilotService(db, company_uuid, actor_uuid)
    exception = await service.decide_exception(
        exception_id,
        payload.decision,
        payload.reason,
        payload.assignee_user_id,
    )
    return APIResponse[AutopilotExceptionResponse](
        success=True,
        message=f"Exception {payload.decision.lower()}d successfully.",
        data=AutopilotExceptionResponse(**service._serialize_exception(exception)),
        errors=None,
    )


# ── Agent (AI Copilot) ────────────────────────────────────────────────────────

@router.post(
    "/agent/chat",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[AgentChatResponse],
    summary="Process AI agent conversation",
)
async def autopilot_agent_chat(
    payload: AgentChatRequest,
    claims: Annotated[dict, Depends(_tenant_id)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[AgentChatResponse]:
    """Process natural language conversation through configured LLM provider."""
    company_uuid = _tenant_id(claims)
    actor_uuid = _actor_id(claims)
    service = AutopilotService(db, company_uuid, actor_uuid)
    result = await service.agent_chat(payload.message, payload.context, payload.conversation_id)
    return APIResponse[AgentChatResponse](
        success=True,
        message="Agent response generated.",
        data=AgentChatResponse(**result),
        errors=None,
    )


@router.get(
    "/agent/actions/{action_id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[AgentActionProposal | None],
    summary="Get proposed action details",
)
async def get_agent_action(
    action_id: uuid.UUID,
    claims: Annotated[dict, Depends(_tenant_id)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[AgentActionProposal | None]:
    """Retrieve a pending AI-proposed action."""
    company_uuid = _tenant_id(claims)
    actor_uuid = _actor_id(claims)
    service = AutopilotService(db, company_uuid, actor_uuid)
    action = await service.get_proposed_action(action_id)
    if action is None:
        return APIResponse[AgentActionProposal | None](
            success=True,
            message="Action not found.",
            data=None,
            errors=None,
        )
    return APIResponse[AgentActionProposal](
        success=True,
        message="Action retrieved successfully.",
        data=AgentActionProposal(**action),
        errors=None,
    )


@router.post(
    "/agent/actions/{action_id}/confirm",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Confirm a pending AI action",
)
async def confirm_agent_action(
    action_id: uuid.UUID,
    payload: AgentActionConfirm,
    claims: Annotated[dict, Depends(_tenant_id)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[dict]:
    """Explicitly approve a sensitive AI-generated action."""
    company_uuid = _tenant_id(claims)
    actor_uuid = _actor_id(claims)
    service = AutopilotService(db, company_uuid, actor_uuid)
    result = await service.confirm_action(action_id, payload.approval_comment)
    return APIResponse[dict](success=True, message="Action confirmed and executed.", data=result, errors=None)


@router.post(
    "/agent/actions/{action_id}/cancel",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Cancel a pending AI action",
)
async def cancel_agent_action(
    action_id: uuid.UUID,
    payload: AgentActionCancel,
    claims: Annotated[dict, Depends(_tenant_id)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[dict]:
    """Cancel a pending AI-proposed action before execution."""
    company_uuid = _tenant_id(claims)
    actor_uuid = _actor_id(claims)
    service = AutopilotService(db, company_uuid, actor_uuid)
    result = await service.cancel_action(action_id, payload.cancellation_reason)
    return APIResponse[dict](success=True, message="Action cancelled.", data=result, errors=None)


# ── Audit ─────────────────────────────────────────────────────────────────────

@router.get(
    "/audit",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="List automation audit trail",
)
async def list_autopilot_audit(
    domain: str | None = Query(None, description="Filter by domain"),
    entity_id: uuid.UUID | None = Query(None, description="Filter by entity"),
    action: str | None = Query(None, description="Filter by action type"),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    claims: Annotated[dict, Depends(_tenant_id)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Detailed audit trail of all automation decisions."""
    company_uuid = _tenant_id(claims)
    actor_uuid = _actor_id(claims)
    service = AutopilotService(db, company_uuid, actor_uuid)
    result = await service.list_audit(domain=domain, entity_id=entity_id, action=action, page=page, limit=limit)
    return APIResponse[dict](success=True, message="Audit trail retrieved successfully.", data=result, errors=None)


@router.post(
    "/audit/{audit_id}/undo",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Undo an automation action (where safe compensating operation exists)",
)
async def undo_autopilot_audit(
    audit_id: uuid.UUID,
    payload: AutopilotAuditUndoRequest,
    claims: Annotated[dict, Depends(_tenant_id)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[dict]:
    """Undo an action only where a safe compensating operation exists."""
    company_uuid = _tenant_id(claims)
    actor_uuid = _actor_id(claims)
    service = AutopilotService(db, company_uuid, actor_uuid)
    result = await service.undo_audit(audit_id, payload.reason, payload.compensation_action)
    return APIResponse[dict](success=True, message="Action undone successfully.", data=result, errors=None)


@router.post(
    "/audit/{audit_id}/override",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Administrator override with mandatory reason",
)
async def override_autopilot_audit(
    audit_id: uuid.UUID,
    payload: AutopilotAuditOverrideRequest,
    claims: Annotated[dict, Depends(_tenant_id)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[dict]:
    """Admin override of an automation decision with mandatory reason."""
    company_uuid = _tenant_id(claims)
    actor_uuid = _actor_id(claims)
    service = AutopilotService(db, company_uuid, actor_uuid)
    result = await service.override_audit(audit_id, payload.reason, payload.new_values)
    return APIResponse[dict](success=True, message="Override recorded successfully.", data=result, errors=None)


# ── Alerts ────────────────────────────────────────────────────────────────────

@router.get(
    "/alerts",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="List automation alerts",
)
async def list_autopilot_alerts(
    status_filter: str | None = Query(None, alias="status", description="Filter by status"),
    severity: str | None = Query(None, description="Filter by severity"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    claims: Annotated[dict, Depends(_tenant_id)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Automation alerts and notifications."""
    company_uuid = _tenant_id(claims)
    actor_uuid = _actor_id(claims)
    service = AutopilotService(db, company_uuid, actor_uuid)
    result = await service.list_alerts(status=status_filter, severity=severity, page=page, limit=limit)
    return APIResponse[dict](success=True, message="Alerts retrieved successfully.", data=result, errors=None)


@router.post(
    "/alerts/{alert_id}/ack",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Acknowledge an alert",
)
async def acknowledge_autopilot_alert(
    alert_id: uuid.UUID,
    claims: Annotated[dict, Depends(_tenant_id)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[dict]:
    """Acknowledge an automation alert."""
    company_uuid = _tenant_id(claims)
    actor_uuid = _actor_id(claims)
    service = AutopilotService(db, company_uuid, actor_uuid)
    result = await service.acknowledge_alert(alert_id)
    return APIResponse[dict](success=True, message="Alert acknowledged.", data=result, errors=None)


@router.post(
    "/alerts/{alert_id}/snooze",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Snooze an alert",
)
async def snooze_autopilot_alert(
    alert_id: uuid.UUID,
    payload: AutopilotAlertSnooze,
    claims: Annotated[dict, Depends(_tenant_id)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[dict]:
    """Snooze an alert until a specific time."""
    company_uuid = _tenant_id(claims)
    actor_uuid = _actor_id(claims)
    service = AutopilotService(db, company_uuid, actor_uuid)
    result = await service.snooze_alert(alert_id, payload.snooze_until)
    return APIResponse[dict](success=True, message="Alert snoozed.", data=result, errors=None)


@router.post(
    "/alerts/{alert_id}/task",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[dict],
    summary="Create follow-up task from alert",
)
async def create_autopilot_alert_task(
    alert_id: uuid.UUID,
    payload: AutopilotAlertCreateTask,
    claims: Annotated[dict, Depends(_tenant_id)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[dict]:
    """Create a follow-up task from an alert."""
    company_uuid = _tenant_id(claims)
    actor_uuid = _actor_id(claims)
    service = AutopilotService(db, company_uuid, actor_uuid)
    result = await service.create_alert_task(
        alert_id,
        payload.task_title,
        payload.task_description,
        payload.assignee_user_id,
        payload.due_at,
    )
    return APIResponse[dict](success=True, message="Follow-up task created.", data=result, errors=None)


# ── Overview ──────────────────────────────────────────────────────────────────

@router.get(
    "/overview",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[AutopilotOverviewResponse],
    summary="Get autopilot overview metrics",
)
async def get_autopilot_overview(
    claims: Annotated[dict, Depends(_tenant_id)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[AutopilotOverviewResponse]:
    """Aggregated autopilot metrics for dashboard."""
    company_uuid = _tenant_id(claims)
    actor_uuid = _actor_id(claims)
    service = AutopilotService(db, company_uuid, actor_uuid)
    data = await service.get_overview()
    return APIResponse[AutopilotOverviewResponse](
        success=True,
        message="Autopilot overview retrieved successfully.",
        data=AutopilotOverviewResponse(**data),
        errors=None,
    )


# ── Onboarding Automation Runs ────────────────────────────────────────────────

@router.get(
    "/onboarding/runs",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="List onboarding automation runs",
)
async def list_autopilot_onboarding_runs(
    status_filter: str | None = Query(None, alias="status", description="Filter by status"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    claims: Annotated[dict, Depends(_tenant_id)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Employee onboarding automation run history."""
    company_uuid = _tenant_id(claims)
    actor_uuid = _actor_id(claims)
    service = AutopilotService(db, company_uuid, actor_uuid)
    result = await service.list_onboarding_runs(status=status_filter, page=page, limit=limit)
    return APIResponse[dict](success=True, message="Onboarding runs retrieved successfully.", data=result, errors=None)


@router.get(
    "/onboarding/runs/{run_id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[OnboardingRunDetailResponse],
    summary="Get onboarding run details",
)
async def get_autopilot_onboarding_run(
    run_id: uuid.UUID,
    claims: Annotated[dict, Depends(_tenant_id)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[OnboardingRunDetailResponse]:
    """Detailed onboarding run with step history."""
    company_uuid = _tenant_id(claims)
    actor_uuid = _actor_id(claims)
    service = AutopilotService(db, company_uuid, actor_uuid)
    data = await service.get_onboarding_run(run_id)
    return APIResponse[OnboardingRunDetailResponse](
        success=True,
        message="Onboarding run retrieved successfully.",
        data=OnboardingRunDetailResponse(**data),
        errors=None,
    )


@router.post(
    "/onboarding/runs/{run_id}/retry-step",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Retry failed onboarding step with idempotency",
)
async def retry_autopilot_onboarding_step(
    run_id: uuid.UUID,
    payload: OnboardingRetryRequest,
    claims: Annotated[dict, Depends(_tenant_id)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[dict]:
    """Retry a failed onboarding step with idempotency key."""
    company_uuid = _tenant_id(claims)
    actor_uuid = _actor_id(claims)
    service = AutopilotService(db, company_uuid, actor_uuid)
    result = await service.retry_onboarding_step(run_id, payload.idempotency_key)
    return APIResponse[dict](success=True, message="Step retry initiated.", data=result, errors=None)


# ── Payroll Automation Status ─────────────────────────────────────────────────

@router.get(
    "/payroll/status",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[PayrollAutomationStatusResponse],
    summary="Get payroll automation status",
)
async def get_autopilot_payroll_status(
    claims: Annotated[dict, Depends(_tenant_id)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[PayrollAutomationStatusResponse]:
    """Real payroll automation status with phase and progress."""
    company_uuid = _tenant_id(claims)
    actor_uuid = _actor_id(claims)
    service = AutopilotService(db, company_uuid, actor_uuid)
    data = await service.get_payroll_automation_status()
    return APIResponse[PayrollAutomationStatusResponse](
        success=True,
        message="Payroll automation status retrieved successfully.",
        data=PayrollAutomationStatusResponse(**data),
        errors=None,
    )