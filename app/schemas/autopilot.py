"""Validated Autopilot HR contracts for API v2."""

from __future__ import annotations

from datetime import datetime, date
from typing import Annotated, Any, Literal, Union
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator


AutopilotDomain = Literal[
    "attendance",
    "leave",
    "payroll",
    "onboarding",
    "offboarding",
    "performance",
    "expenses",
    "documents",
    "assets",
    "compliance",
]

AutopilotAction = Literal[
    "FLAG_EXCEPTION",
    "AUTO_APPROVE",
    "AUTO_REJECT",
    "SEND_NOTIFICATION",
    "CREATE_TASK",
    "ESCALATE",
    "UPDATE_RECORD",
]

AutopilotRuleStatus = Literal["active", "inactive"]
AutopilotExceptionStatus = Literal["OPEN", "IN_REVIEW", "RESOLVED", "DISMISSED", "ESCALATED"]
AutopilotAuditAction = Literal[
    "RULE_CREATED",
    "RULE_UPDATED",
    "RULE_DELETED",
    "RULE_ENABLED",
    "RULE_DISABLED",
    "EXCEPTION_CREATED",
    "EXCEPTION_DECIDED",
    "EXCEPTION_ESCALATED",
    "ACTION_EXECUTED",
    "ACTION_UNDONE",
    "ACTION_OVERRIDDEN",
    "ALERT_ACKNOWLEDGED",
    "ALERT_SNOOZED",
    "ONBOARDING_STARTED",
    "ONBOARDING_STEP_COMPLETED",
    "ONBOARDING_RETRIED",
    "PAYROLL_AUTOMATION_STARTED",
    "PAYROLL_AUTOMATION_COMPLETED",
]

AutopilotAlertSeverity = Literal["info", "warning", "critical"]
AutopilotAlertStatus = Literal["active", "acknowledged", "snoozed", "resolved"]


class AutopilotBase(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ConditionNode(AutopilotBase):
    field: str = Field(min_length=1, max_length=100)
    operator: Literal["eq", "ne", "gt", "gte", "lt", "lte", "in", "nin", "contains", "startswith", "endswith"]
    value: Any


class ConditionGroup(AutopilotBase):
    logic: Literal["AND", "OR"] = "AND"
    conditions: list[Union[ConditionNode, "ConditionGroup"]] = Field(default_factory=list, min_length=1)


class EscalationStep(AutopilotBase):
    role: str = Field(min_length=1, max_length=50)
    delay_hours: int = Field(ge=0, le=168)
    notify_channels: list[Literal["email", "slack", "in_app"]] = Field(default_factory=list)


class AutopilotSettingsBase(AutopilotBase):
    enabled: bool = True
    default_sla_hours: int = Field(default=24, ge=1, le=168)
    max_retries: int = Field(default=3, ge=0, le=10)
    allowed_domains: list[AutopilotDomain] = Field(default_factory=list)
    require_approval_for: list[AutopilotAction] = Field(
        default_factory=lambda: ["AUTO_APPROVE", "AUTO_REJECT", "UPDATE_RECORD"]
    )


class AutopilotSettingsCreate(AutopilotSettingsBase):
    pass


class AutopilotSettingsUpdate(AutopilotSettingsBase):
    enabled: bool | None = None
    default_sla_hours: int | None = None
    max_retries: int | None = None
    allowed_domains: list[AutopilotDomain] | None = None
    require_approval_for: list[AutopilotAction] | None = None


class AutopilotSettingsResponse(AutopilotSettingsBase):
    company_id: UUID
    updated_at: datetime
    updated_by: UUID | None = None


class AutopilotRuleBase(AutopilotBase):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=1000)
    domain: AutopilotDomain
    action: AutopilotAction
    enabled: bool = True
    priority: int = Field(default=100, ge=1, le=1000)
    confidence_threshold: float = Field(default=0.85, ge=0.0, le=1.0)
    conditions: ConditionGroup
    escalation_ladder: list[EscalationStep] = Field(default_factory=list)
    sla_hours: int = Field(default=24, ge=1, le=168)
    rule_metadata: dict[str, Any] | None = None


class AutopilotRuleCreate(AutopilotRuleBase):
    pass


class AutopilotRuleUpdate(AutopilotRuleBase):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = None
    domain: AutopilotDomain | None = None
    action: AutopilotAction | None = None
    enabled: bool | None = None
    priority: int | None = Field(default=None, ge=1, le=1000)
    confidence_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    conditions: ConditionGroup | None = None
    escalation_ladder: list[EscalationStep] | None = None
    sla_hours: int | None = Field(default=None, ge=1, le=168)
    rule_metadata: dict[str, Any] | None = None


class AutopilotRuleResponse(AutopilotRuleBase):
    id: UUID
    company_id: UUID
    created_at: datetime
    updated_at: datetime
    created_by: UUID
    last_triggered_at: datetime | None = None
    trigger_count: int = 0


class AutopilotRuleSimulateRequest(AutopilotBase):
    entity_id: UUID
    domain: AutopilotDomain
    context: dict[str, Any] = Field(default_factory=dict)
    dry_run: bool = True


class AutopilotRuleSimulateResponse(AutopilotBase):
    rule_id: UUID
    rule_name: str
    matched: bool
    confidence_score: float | None = None
    would_trigger_action: AutopilotAction | None = None
    would_create_exception: bool = False
    exception_reasons: list[str] | None = None
    policy_trace: dict[str, Any] | None = None


class AutopilotExceptionDecision(AutopilotBase):
    decision: Literal["APPROVE", "REJECT", "ESCALATE", "DISMISS"]
    reason: str = Field(min_length=1, max_length=1000)
    assignee_user_id: UUID | None = None


class AutopilotExceptionResponse(AutopilotBase):
    id: UUID
    rule_id: UUID | None
    domain: AutopilotDomain
    entity_id: UUID
    employee_id: UUID | None
    status: AutopilotExceptionStatus
    explanation: str
    exception_reasons: list[str] | None
    policy_trace: dict[str, Any] | None
    confidence_score: float | None
    escalation_level: int
    assigned_to_user_id: UUID | None
    assigned_role: str | None
    escalated_at: datetime | None
    resolved_at: datetime | None
    sla_due_at: datetime | None
    before_snapshot: dict[str, Any] | None
    after_snapshot: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


class AgentChatRequest(AutopilotBase):
    message: str = Field(min_length=1, max_length=4000)
    context: dict[str, Any] | None = None
    conversation_id: UUID | None = None


class AgentChatResponse(AutopilotBase):
    conversation_id: UUID
    response: str
    proposed_actions: list[dict[str, Any]] = Field(default_factory=list)
    requires_approval: bool = False


class AgentActionProposal(AutopilotBase):
    id: UUID
    conversation_id: UUID
    action_type: AutopilotAction
    domain: AutopilotDomain
    entity_id: UUID | None
    parameters: dict[str, Any]
    reasoning: str
    confidence_score: float
    status: Literal["pending", "approved", "rejected", "cancelled", "executed"]
    created_at: datetime
    approved_by: UUID | None = None
    approved_at: datetime | None = None
    executed_at: datetime | None = None
    execution_result: dict[str, Any] | None = None


class AgentActionConfirm(AutopilotBase):
    approval_comment: str | None = Field(default=None, max_length=500)


class AgentActionCancel(AutopilotBase):
    cancellation_reason: str = Field(min_length=1, max_length=500)


class AutopilotAuditResponse(AutopilotBase):
    id: UUID
    rule_id: UUID | None
    domain: AutopilotDomain
    entity_id: UUID
    employee_id: UUID | None
    action: AutopilotAuditAction
    decision: str
    confidence_score: float | None
    actor_id: UUID | None
    before_snapshot: dict[str, Any] | None
    after_snapshot: dict[str, Any] | None
    policy_trace: dict[str, Any] | None
    explanation: str | None
    is_rolled_back: bool
    rolled_back_by: UUID | None
    rolled_back_at: datetime | None
    rollback_reason: str | None
    rollback_metadata: dict[str, Any] | None
    created_at: datetime


class AutopilotAuditUndoRequest(AutopilotBase):
    reason: str = Field(min_length=1, max_length=1000)
    compensation_action: dict[str, Any] | None = None


class AutopilotAuditOverrideRequest(AutopilotBase):
    reason: str = Field(min_length=1, max_length=1000)
    new_values: dict[str, Any]


class AutopilotAlertResponse(AutopilotBase):
    id: UUID
    rule_id: UUID | None
    domain: AutopilotDomain
    entity_id: UUID | None
    employee_id: UUID | None
    title: str
    message: str
    severity: AutopilotAlertSeverity
    status: AutopilotAlertStatus
    acknowledged_by: UUID | None
    acknowledged_at: datetime | None
    snoozed_until: datetime | None
    task_created: bool
    task_id: UUID | None
    created_at: datetime
    updated_at: datetime


class AutopilotAlertAck(AutopilotBase):
    pass


class AutopilotAlertSnooze(AutopilotBase):
    snooze_until: AwareDatetime


class AutopilotAlertCreateTask(AutopilotBase):
    task_title: str = Field(min_length=1, max_length=200)
    task_description: str | None = Field(default=None, max_length=1000)
    assignee_user_id: UUID | None = None
    due_at: AwareDatetime | None = None


class AutopilotOverviewResponse(AutopilotBase):
    total_rules: int
    active_rules: int
    total_exceptions_open: int
    exceptions_by_domain: dict[str, int]
    exceptions_by_status: dict[str, int]
    alerts_active: int
    alerts_acknowledged: int
    alerts_snoozed: int
    audit_entries_24h: int
    onboarding_runs_active: int
    payroll_automation_status: str
    last_automation_run: datetime | None


class OnboardingRunResponse(AutopilotBase):
    id: UUID
    employee_id: UUID
    employee_name: str
    template_id: UUID | None
    status: Literal["pending", "in_progress", "completed", "failed", "paused"]
    current_step: str | None
    completed_steps: list[str]
    failed_step: str | None
    failure_reason: str | None
    started_at: datetime
    completed_at: datetime | None
    created_at: datetime


class OnboardingRunDetailResponse(OnboardingRunResponse):
    steps: list[dict[str, Any]]
    step_history: list[dict[str, Any]]


class OnboardingRetryRequest(AutopilotBase):
    idempotency_key: str = Field(min_length=1, max_length=100)


class PayrollAutomationStatusResponse(AutopilotBase):
    status: Literal["idle", "running", "completed", "failed", "paused"]
    current_phase: str | None
    progress_percentage: float
    employees_processed: int
    employees_total: int
    errors_count: int
    warnings_count: int
    started_at: datetime | None
    estimated_completion: datetime | None
    last_run: datetime | None
    last_run_status: str | None
    next_scheduled_run: datetime | None


__all__ = [
    "AutopilotDomain",
    "AutopilotAction",
    "AutopilotRuleStatus",
    "AutopilotExceptionStatus",
    "AutopilotAuditAction",
    "AutopilotAlertSeverity",
    "AutopilotAlertStatus",
    "ConditionNode",
    "ConditionGroup",
    "EscalationStep",
    "AutopilotSettingsCreate",
    "AutopilotSettingsUpdate",
    "AutopilotSettingsResponse",
    "AutopilotRuleCreate",
    "AutopilotRuleUpdate",
    "AutopilotRuleResponse",
    "AutopilotRuleSimulateRequest",
    "AutopilotRuleSimulateResponse",
    "AutopilotExceptionDecision",
    "AutopilotExceptionResponse",
    "AgentChatRequest",
    "AgentChatResponse",
    "AgentActionProposal",
    "AgentActionConfirm",
    "AgentActionCancel",
    "AutopilotAuditResponse",
    "AutopilotAuditUndoRequest",
    "AutopilotAuditOverrideRequest",
    "AutopilotAlertResponse",
    "AutopilotAlertAck",
    "AutopilotAlertSnooze",
    "AutopilotAlertCreateTask",
    "AutopilotOverviewResponse",
    "OnboardingRunResponse",
    "OnboardingRunDetailResponse",
    "OnboardingRetryRequest",
    "PayrollAutomationStatusResponse",
]