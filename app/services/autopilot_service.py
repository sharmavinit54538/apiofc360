"""Autopilot HR Automation Service — Business logic for rules, exceptions, agent, audit, alerts, onboarding, payroll."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from typing import Any
from math import ceil

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.autopilot_hr import AutopilotAuditLog, AutopilotExceptionItem, AutopilotPolicyRule
from app.models.company import Company
from app.models.employee import Employee
from app.models.user import User


class AutopilotService:
    """Tenant-scoped service for Autopilot HR automation."""

    def __init__(self, db: AsyncSession, company_id: uuid.UUID, actor_id: uuid.UUID):
        self.db = db
        self.company_id = company_id
        self.actor_id = actor_id

    # ── Settings ────────────────────────────────────────────────────────────────

    async def get_settings(self) -> dict[str, Any]:
        """Get or create autopilot settings for the company."""
        stmt = select(Company).where(Company.id == self.company_id)
        result = await self.db.execute(stmt)
        company = result.scalar_one_or_none()
        if not company:
            raise ValueError("Company not found")

        hr_settings = company.hr_settings or {}
        autopilot = hr_settings.get("autopilot") or {
            "enabled": True,
            "default_sla_hours": 24,
            "max_retries": 3,
            "allowed_domains": [
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
            ],
            "require_approval_for": ["AUTO_APPROVE", "AUTO_REJECT", "UPDATE_RECORD"],
        }
        return {
            "company_id": str(self.company_id),
            **autopilot,
            "updated_at": company.updated_at.isoformat() if company.updated_at else None,
            "updated_by": str(company.updated_by) if hasattr(company, "updated_by") and company.updated_by else None,
        }

    async def update_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Update autopilot settings for the company."""
        stmt = select(Company).where(Company.id == self.company_id)
        result = await self.db.execute(stmt)
        company = result.scalar_one_or_none()
        if not company:
            raise ValueError("Company not found")

        hr_settings = company.hr_settings or {}
        autopilot = hr_settings.get("autopilot") or {}
        autopilot.update({k: v for k, v in payload.items() if v is not None})
        hr_settings["autopilot"] = autopilot
        company.hr_settings = hr_settings

        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(company, "hr_settings")
        company.updated_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(company)

        await self._audit(
            action="SETTINGS_UPDATED",
            domain="settings",
            entity_id=self.company_id,
            explanation="Updated autopilot HR automation settings",
        )
        return await self.get_settings()

    # ── Rules CRUD ──────────────────────────────────────────────────────────────

    async def list_rules(
        self,
        domain: str | None = None,
        enabled: bool | None = None,
        page: int = 1,
        limit: int = 20,
        search: str | None = None,
    ) -> dict[str, Any]:
        """List automation rules with pagination and filters."""
        stmt = select(AutopilotPolicyRule).where(AutopilotPolicyRule.company_id == self.company_id)

        if domain:
            stmt = stmt.where(AutopilotPolicyRule.domain == domain)
        if enabled is not None:
            stmt = stmt.where(AutopilotPolicyRule.enabled == enabled)
        if search:
            term = f"%{search}%"
            stmt = stmt.where(
                or_(
                    AutopilotPolicyRule.name.ilike(term),
                    AutopilotPolicyRule.description.ilike(term),
                )
            )

        total = (await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()

        stmt = stmt.order_by(AutopilotPolicyRule.priority.asc(), AutopilotPolicyRule.created_at.desc())
        stmt = stmt.offset((page - 1) * limit).limit(limit)
        result = await self.db.execute(stmt)
        rules = result.scalars().all()

        items = [self._serialize_rule(r) for r in rules]
        pages = ceil(total / limit) if limit > 0 else 1
        return {
            "items": items,
            "total": total,
            "page": page,
            "limit": limit,
            "pages": pages,
            "has_next": page < pages,
            "has_previous": page > 1,
        }

    async def get_rule(self, rule_id: uuid.UUID) -> AutopilotPolicyRule:
        """Get a single rule by ID."""
        stmt = select(AutopilotPolicyRule).where(
            AutopilotPolicyRule.id == rule_id,
            AutopilotPolicyRule.company_id == self.company_id,
        )
        result = await self.db.execute(stmt)
        rule = result.scalar_one_or_none()
        if not rule:
            raise ValueError("Rule not found")
        return rule

    async def create_rule(self, payload: dict[str, Any]) -> AutopilotPolicyRule:
        """Create a new automation rule."""
        rule = AutopilotPolicyRule(
            id=uuid.uuid4(),
            company_id=self.company_id,
            name=payload["name"],
            description=payload.get("description"),
            domain=payload["domain"],
            action=payload["action"],
            enabled=payload.get("enabled", True),
            priority=payload.get("priority", 100),
            confidence_threshold=payload.get("confidence_threshold", 0.85),
            conditions_json=payload.get("conditions"),
            escalation_ladder_json=payload.get("escalation_ladder", []),
            sla_hours=payload.get("sla_hours", 24),
            rule_metadata_json=payload.get("rule_metadata"),
        )
        self.db.add(rule)
        await self._audit(
            action="RULE_CREATED",
            domain="rules",
            entity_id=rule.id,
            explanation=f"Created automation rule: {rule.name}",
            rule_id=rule.id,
        )
        await self.db.commit()
        await self.db.refresh(rule)
        return rule

    async def update_rule(self, rule_id: uuid.UUID, payload: dict[str, Any]) -> AutopilotPolicyRule:
        """Update an automation rule."""
        rule = await self.get_rule(rule_id)
        before = self._serialize_rule(rule)

        for key, value in payload.items():
            if value is not None and key not in {"id", "company_id", "created_at", "created_by"}:
                if key == "conditions":
                    rule.conditions_json = value
                elif key == "escalation_ladder":
                    rule.escalation_ladder_json = value
                elif key == "rule_metadata":
                    rule.rule_metadata_json = value
                else:
                    setattr(rule, key, value)

        rule.updated_at = datetime.now(timezone.utc)
        await self._audit(
            action="RULE_UPDATED",
            domain="rules",
            entity_id=rule.id,
            explanation=f"Updated automation rule: {rule.name}",
            before_snapshot=before,
            after_snapshot=self._serialize_rule(rule),
            rule_id=rule.id,
        )
        await self.db.commit()
        await self.db.refresh(rule)
        return rule

    async def delete_rule(self, rule_id: uuid.UUID) -> None:
        """Delete an automation rule."""
        rule = await self.get_rule(rule_id)
        await self._audit(
            action="RULE_DELETED",
            domain="rules",
            entity_id=rule.id,
            explanation=f"Deleted automation rule: {rule.name}",
            rule_id=rule.id,
        )
        await self.db.delete(rule)
        await self.db.commit()

    async def simulate_rule(self, rule_id: uuid.UUID, entity_id: uuid.UUID, context: dict[str, Any]) -> dict[str, Any]:
        """Simulate a rule execution without side effects."""
        rule = await self.get_rule(rule_id)

        # Evaluate conditions against context
        matched, confidence, reasons = self._evaluate_conditions(rule.conditions_json, context)

        result = {
            "rule_id": str(rule.id),
            "rule_name": rule.name,
            "matched": matched,
            "confidence_score": confidence,
            "would_trigger_action": rule.action if matched and confidence >= rule.confidence_threshold else None,
            "would_create_exception": matched and confidence < rule.confidence_threshold,
            "exception_reasons": reasons if matched and confidence < rule.confidence_threshold else None,
            "policy_trace": {
                "rule_id": str(rule.id),
                "rule_name": rule.name,
                "domain": rule.domain,
                "action": rule.action,
                "confidence_threshold": float(rule.confidence_threshold),
                "conditions_evaluated": rule.conditions_json,
                "context_keys": list(context.keys()),
                "matched": matched,
                "confidence": confidence,
            },
        }
        return result

    # ── Exceptions ──────────────────────────────────────────────────────────────

    async def list_exceptions(
        self,
        status: str | None = None,
        domain: str | None = None,
        page: int = 1,
        limit: int = 20,
    ) -> dict[str, Any]:
        """List automation exceptions with pagination."""
        stmt = select(AutopilotExceptionItem).where(AutopilotExceptionItem.company_id == self.company_id)

        if status:
            stmt = stmt.where(AutopilotExceptionItem.status == status)
        if domain:
            stmt = stmt.where(AutopilotExceptionItem.domain == domain)

        total = (await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()

        stmt = stmt.order_by(AutopilotExceptionItem.created_at.desc())
        stmt = stmt.offset((page - 1) * limit).limit(limit)
        result = await self.db.execute(stmt)
        exceptions = result.scalars().all()

        items = [self._serialize_exception(e) for e in exceptions]
        pages = ceil(total / limit) if limit > 0 else 1
        return {
            "items": items,
            "total": total,
            "page": page,
            "limit": limit,
            "pages": pages,
            "has_next": page < pages,
            "has_previous": page > 1,
        }

    async def get_exception(self, exception_id: uuid.UUID) -> AutopilotExceptionItem:
        """Get a single exception by ID."""
        stmt = select(AutopilotExceptionItem).where(
            AutopilotExceptionItem.id == exception_id,
            AutopilotExceptionItem.company_id == self.company_id,
        )
        result = await self.db.execute(stmt)
        exception = result.scalar_one_or_none()
        if not exception:
            raise ValueError("Exception not found")
        return exception

    async def decide_exception(self, exception_id: uuid.UUID, decision: str, reason: str, assignee_user_id: uuid.UUID | None = None) -> AutopilotExceptionItem:
        """Decide on an exception: APPROVE, REJECT, ESCALATE, DISMISS."""
        exception = await self.get_exception(exception_id)

        if exception.status not in {"OPEN", "IN_REVIEW"}:
            raise ValueError(f"Cannot decide exception in status: {exception.status}")

        before = self._serialize_exception(exception)
        now = datetime.now(timezone.utc)

        if decision == "APPROVE":
            exception.status = "RESOLVED"
            exception.resolved_at = now
        elif decision == "REJECT":
            exception.status = "DISMISSED"
            exception.resolved_at = now
        elif decision == "ESCALATE":
            exception.status = "ESCALATED"
            exception.escalation_level += 1
            exception.escalated_at = now
            if assignee_user_id:
                exception.assigned_to_user_id = assignee_user_id
        elif decision == "DISMISS":
            exception.status = "DISMISSED"
            exception.resolved_at = now
        else:
            raise ValueError(f"Invalid decision: {decision}")

        exception.updated_at = now
        await self._audit(
            action="EXCEPTION_DECIDED",
            domain="exceptions",
            entity_id=exception.id,
            explanation=f"Exception {decision.lower()}: {reason}",
            decision=decision,
            before_snapshot=before,
            after_snapshot=self._serialize_exception(exception),
            rule_id=exception.rule_id,
        )
        await self.db.commit()
        await self.db.refresh(exception)
        return exception

    # ── Agent (AI Copilot) ──────────────────────────────────────────────────────

    async def agent_chat(self, message: str, context: dict[str, Any] | None = None, conversation_id: uuid.UUID | None = None) -> dict[str, Any]:
        from app.services.autopilot_chat import chat
        return await chat(message, context, conversation_id)

    async def get_proposed_action(self, action_id: uuid.UUID) -> dict[str, Any] | None:
        """Get a proposed action by ID (from audit log)."""
        stmt = select(AutopilotAuditLog).where(
            AutopilotAuditLog.id == action_id,
            AutopilotAuditLog.company_id == self.company_id,
        )
        result = await self.db.execute(stmt)
        audit = result.scalar_one_or_none()
        if not audit:
            return None
        return self._serialize_audit(audit)

    async def confirm_action(self, action_id: uuid.UUID, approval_comment: str | None = None) -> dict[str, Any]:
        """Confirm a pending AI-proposed action."""
        audit = await self.get_proposed_action(action_id)
        if not audit:
            raise ValueError("Action not found")

        from fastapi import HTTPException
        raise HTTPException(409, "No executable action is attached to this record. Use the authorized domain workflow.")

    async def cancel_action(self, action_id: uuid.UUID, cancellation_reason: str) -> dict[str, Any]:
        """Cancel a pending AI-proposed action."""
        audit = await self.get_proposed_action(action_id)
        if not audit:
            raise ValueError("Action not found")

        await self._audit(
            action="ACTION_CANCELLED",
            domain=audit.get("domain"),
            entity_id=uuid.UUID(audit.get("entity_id")) if audit.get("entity_id") else None,
            explanation=f"Cancelled AI action: {cancellation_reason}",
            after_snapshot={"cancelled": True, "cancellation_reason": cancellation_reason},
            rule_id=uuid.UUID(audit.get("rule_id")) if audit.get("rule_id") else None,
        )
        await self.db.commit()
        return {"action_id": str(action_id), "status": "cancelled", "cancelled_at": datetime.now(timezone.utc).isoformat()}

    # ── Audit ──────────────────────────────────────────────────────────────────

    async def list_audit(
        self,
        domain: str | None = None,
        entity_id: uuid.UUID | None = None,
        action: str | None = None,
        page: int = 1,
        limit: int = 50,
    ) -> dict[str, Any]:
        """List audit logs with pagination and filters."""
        stmt = select(AutopilotAuditLog).where(AutopilotAuditLog.company_id == self.company_id)

        if domain:
            stmt = stmt.where(AutopilotAuditLog.domain == domain)
        if entity_id:
            stmt = stmt.where(AutopilotAuditLog.entity_id == entity_id)
        if action:
            stmt = stmt.where(AutopilotAuditLog.action == action)

        total = (await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()

        stmt = stmt.order_by(AutopilotAuditLog.created_at.desc())
        stmt = stmt.offset((page - 1) * limit).limit(limit)
        result = await self.db.execute(stmt)
        logs = result.scalars().all()

        items = [self._serialize_audit(l) for l in logs]
        pages = ceil(total / limit) if limit > 0 else 1
        return {
            "items": items,
            "total": total,
            "page": page,
            "limit": limit,
            "pages": pages,
            "has_next": page < pages,
            "has_previous": page > 1,
        }

    async def undo_audit(self, audit_id: uuid.UUID, reason: str, compensation_action: dict[str, Any] | None = None) -> dict[str, Any]:
        """Undo an audited action by creating a compensating operation."""
        stmt = select(AutopilotAuditLog).where(
            AutopilotAuditLog.id == audit_id,
            AutopilotAuditLog.company_id == self.company_id,
        )
        result = await self.db.execute(stmt)
        audit = result.scalar_one_or_none()
        if not audit:
            raise ValueError("Audit entry not found")

        if audit.is_rolled_back:
            raise ValueError("Action already rolled back")

        # Check if undo is safe (only certain actions can be undone)
        safe_actions = {"RULE_ENABLED", "RULE_DISABLED", "ACTION_EXECUTED", "EXCEPTION_DECIDED"}
        if audit.action not in safe_actions:
            raise ValueError(f"Cannot undo action type: {audit.action}")

        audit.is_rolled_back = True
        audit.rolled_back_by = self.actor_id
        audit.rolled_back_at = datetime.now(timezone.utc)
        audit.rollback_reason = reason
        audit.rollback_metadata_json = compensation_action or {}

        # Create new audit entry for the rollback
        await self._audit(
            action="ACTION_UNDONE",
            domain=audit.domain,
            entity_id=audit.entity_id,
            explanation=f"Undid action {audit.action}: {reason}",
            before_snapshot=self._serialize_audit(audit),
            after_snapshot={"rolled_back": True, "compensation": compensation_action},
            rule_id=audit.rule_id,
        )
        await self.db.commit()
        return {"audit_id": str(audit_id), "rolled_back": True, "rolled_back_at": audit.rolled_back_at.isoformat()}

    async def override_audit(self, audit_id: uuid.UUID, reason: str, new_values: dict[str, Any]) -> dict[str, Any]:
        """Administrator override of an audited action."""
        stmt = select(AutopilotAuditLog).where(
            AutopilotAuditLog.id == audit_id,
            AutopilotAuditLog.company_id == self.company_id,
        )
        result = await self.db.execute(stmt)
        audit = result.scalar_one_or_none()
        if not audit:
            raise ValueError("Audit entry not found")

        await self._audit(
            action="ACTION_OVERRIDDEN",
            domain=audit.domain,
            entity_id=audit.entity_id,
            explanation=f"Admin override: {reason}",
            before_snapshot=self._serialize_audit(audit),
            after_snapshot=new_values,
            rule_id=audit.rule_id,
        )
        await self.db.commit()
        return {"audit_id": str(audit_id), "overridden": True, "overridden_at": datetime.now(timezone.utc).isoformat()}

    # ── Alerts ──────────────────────────────────────────────────────────────────

    async def list_alerts(
        self,
        status: str | None = None,
        severity: str | None = None,
        page: int = 1,
        limit: int = 20,
    ) -> dict[str, Any]:
        """List automation alerts."""
        # Alerts are derived from exceptions with SLA breaches and audit entries
        # For now, return empty list - full implementation would query a dedicated alerts table
        return {
            "items": [],
            "total": 0,
            "page": page,
            "limit": limit,
            "pages": 1,
            "has_next": False,
            "has_previous": False,
        }

    async def acknowledge_alert(self, alert_id: uuid.UUID) -> dict[str, Any]:
        """Acknowledge an alert."""
        return {"alert_id": str(alert_id), "acknowledged": True, "acknowledged_at": datetime.now(timezone.utc).isoformat()}

    async def snooze_alert(self, alert_id: uuid.UUID, snooze_until: datetime) -> dict[str, Any]:
        """Snooze an alert until a specific time."""
        return {"alert_id": str(alert_id), "snoozed": True, "snoozed_until": snooze_until.isoformat()}

    async def create_alert_task(self, alert_id: uuid.UUID, task_title: str, task_description: str | None, assignee_user_id: uuid.UUID | None, due_at: datetime | None) -> dict[str, Any]:
        """Create a follow-up task from an alert."""
        task_id = uuid.uuid4()
        return {
            "task_id": str(task_id),
            "alert_id": str(alert_id),
            "title": task_title,
            "description": task_description,
            "assignee_user_id": str(assignee_user_id) if assignee_user_id else None,
            "due_at": due_at.isoformat() if due_at else None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    # ── Overview ────────────────────────────────────────────────────────────────

    async def get_overview(self) -> dict[str, Any]:
        """Get autopilot overview metrics."""
        # Count rules
        rules_stmt = select(func.count(AutopilotPolicyRule.id)).where(AutopilotPolicyRule.company_id == self.company_id)
        total_rules = (await self.db.execute(rules_stmt)).scalar_one() or 0

        active_rules_stmt = select(func.count(AutopilotPolicyRule.id)).where(
            AutopilotPolicyRule.company_id == self.company_id,
            AutopilotPolicyRule.enabled == True,
        )
        active_rules = (await self.db.execute(active_rules_stmt)).scalar_one() or 0

        # Count exceptions
        exc_stmt = select(func.count(AutopilotExceptionItem.id)).where(AutopilotExceptionItem.company_id == self.company_id)
        total_exceptions = (await self.db.execute(exc_stmt)).scalar_one() or 0

        open_exc_stmt = select(func.count(AutopilotExceptionItem.id)).where(
            AutopilotExceptionItem.company_id == self.company_id,
            AutopilotExceptionItem.status == "OPEN",
        )
        open_exceptions = (await self.db.execute(open_exc_stmt)).scalar_one() or 0

        # By domain
        domain_stmt = select(AutopilotExceptionItem.domain, func.count(AutopilotExceptionItem.id)).where(
            AutopilotExceptionItem.company_id == self.company_id
        ).group_by(AutopilotExceptionItem.domain)
        domain_result = await self.db.execute(domain_stmt)
        exceptions_by_domain = {row[0]: row[1] for row in domain_result.all()}

        # By status
        status_stmt = select(AutopilotExceptionItem.status, func.count(AutopilotExceptionItem.id)).where(
            AutopilotExceptionItem.company_id == self.company_id
        ).group_by(AutopilotExceptionItem.status)
        status_result = await self.db.execute(status_stmt)
        exceptions_by_status = {row[0]: row[1] for row in status_result.all()}

        return {
            "total_rules": total_rules,
            "active_rules": active_rules,
            "total_exceptions_open": open_exceptions,
            "exceptions_by_domain": exceptions_by_domain,
            "exceptions_by_status": exceptions_by_status,
            "alerts_active": 0,
            "alerts_acknowledged": 0,
            "alerts_snoozed": 0,
            "audit_entries_24h": 0,
            "onboarding_runs_active": 0,
            "payroll_automation_status": "idle",
            "last_automation_run": None,
        }

    # ── Onboarding Runs ─────────────────────────────────────────────────────────

    async def list_onboarding_runs(
        self,
        status: str | None = None,
        page: int = 1,
        limit: int = 20,
    ) -> dict[str, Any]:
        """List onboarding automation runs."""
        # Placeholder - would query onboarding automation runs table
        return {
            "items": [],
            "total": 0,
            "page": page,
            "limit": limit,
            "pages": 1,
            "has_next": False,
            "has_previous": False,
        }

    async def get_onboarding_run(self, run_id: uuid.UUID) -> dict[str, Any]:
        """Get onboarding run details."""
        # Placeholder
        return {"id": str(run_id), "status": "not_found"}

    async def retry_onboarding_step(self, run_id: uuid.UUID, idempotency_key: str) -> dict[str, Any]:
        """Retry a failed onboarding step with idempotency."""
        # Placeholder
        return {"run_id": str(run_id), "retried": True, "idempotency_key": idempotency_key}

    # ── Payroll Automation Status ──────────────────────────────────────────────

    async def get_payroll_automation_status(self) -> dict[str, Any]:
        """Get payroll automation status."""
        return {
            "status": "idle",
            "current_phase": None,
            "progress_percentage": 0.0,
            "employees_processed": 0,
            "employees_total": 0,
            "errors_count": 0,
            "warnings_count": 0,
            "started_at": None,
            "estimated_completion": None,
            "last_run": None,
            "last_run_status": None,
            "next_scheduled_run": None,
        }

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _evaluate_conditions(self, conditions: dict[str, Any] | None, context: dict[str, Any]) -> tuple[bool, float, list[str]]:
        """Evaluate condition tree against context. Returns (matched, confidence, reasons)."""
        if not conditions:
            return False, 0.0, ["No conditions defined"]

        # Simplified evaluation - in production this would be a full rule engine
        matched = True
        confidence = 0.95
        reasons = []

        if isinstance(conditions, dict) and "conditions" in conditions:
            for cond in conditions["conditions"]:
                field = cond.get("field")
                operator = cond.get("operator")
                expected = cond.get("value")
                actual = context.get(field)

                if actual is None:
                    matched = False
                    reasons.append(f"Field '{field}' not found in context")
                    continue

                field_matched = self._compare(actual, operator, expected)
                if not field_matched:
                    matched = False
                    reasons.append(f"Condition failed: {field} {operator} {expected} (actual: {actual})")
                else:
                    reasons.append(f"Condition passed: {field} {operator} {expected}")

        return matched, confidence, reasons

    def _compare(self, actual: Any, operator: str, expected: Any) -> bool:
        """Compare actual value against expected using operator."""
        try:
            if operator == "eq":
                return actual == expected
            elif operator == "ne":
                return actual != expected
            elif operator == "gt":
                return actual > expected
            elif operator == "gte":
                return actual >= expected
            elif operator == "lt":
                return actual < expected
            elif operator == "lte":
                return actual <= expected
            elif operator == "in":
                return actual in expected if isinstance(expected, list) else False
            elif operator == "nin":
                return actual not in expected if isinstance(expected, list) else True
            elif operator == "contains":
                return str(expected).lower() in str(actual).lower()
            elif operator == "startswith":
                return str(actual).lower().startswith(str(expected).lower())
            elif operator == "endswith":
                return str(actual).lower().endswith(str(expected).lower())
        except Exception:
            return False
        return False

    def _serialize_rule(self, rule: AutopilotPolicyRule) -> dict[str, Any]:
        return {
            "id": str(rule.id),
            "company_id": str(rule.company_id),
            "name": rule.name,
            "description": rule.description,
            "domain": rule.domain,
            "action": rule.action,
            "enabled": rule.enabled,
            "priority": rule.priority,
            "confidence_threshold": float(rule.confidence_threshold) if rule.confidence_threshold else 0.85,
            "conditions": rule.conditions_json,
            "escalation_ladder": rule.escalation_ladder_json,
            "sla_hours": rule.sla_hours,
            "rule_metadata": rule.rule_metadata_json,
            "created_at": rule.created_at.isoformat() if rule.created_at else None,
            "updated_at": rule.updated_at.isoformat() if rule.updated_at else None,
            "created_by": str(rule.created_by) if hasattr(rule, "created_by") and rule.created_by else None,
            "last_triggered_at": rule.last_triggered_at.isoformat() if hasattr(rule, "last_triggered_at") and rule.last_triggered_at else None,
            "trigger_count": getattr(rule, "trigger_count", 0) or 0,
        }

    def _serialize_exception(self, exc: AutopilotExceptionItem) -> dict[str, Any]:
        return {
            "id": str(exc.id),
            "rule_id": str(exc.rule_id) if exc.rule_id else None,
            "domain": exc.domain,
            "entity_id": str(exc.entity_id),
            "employee_id": str(exc.employee_id) if exc.employee_id else None,
            "status": exc.status,
            "explanation": exc.explanation,
            "exception_reasons": exc.exception_reasons,
            "policy_trace": exc.policy_trace_json,
            "confidence_score": float(exc.confidence_score) if exc.confidence_score else None,
            "escalation_level": exc.escalation_level,
            "assigned_to_user_id": str(exc.assigned_to_user_id) if exc.assigned_to_user_id else None,
            "assigned_role": exc.assigned_role,
            "escalated_at": exc.escalated_at.isoformat() if exc.escalated_at else None,
            "resolved_at": exc.resolved_at.isoformat() if exc.resolved_at else None,
            "sla_due_at": exc.sla_due_at.isoformat() if exc.sla_due_at else None,
            "before_snapshot": exc.before_snapshot_json,
            "after_snapshot": exc.after_snapshot_json,
            "created_at": exc.created_at.isoformat() if exc.created_at else None,
            "updated_at": exc.updated_at.isoformat() if exc.updated_at else None,
        }

    def _serialize_audit(self, audit: AutopilotAuditLog) -> dict[str, Any]:
        return {
            "id": str(audit.id),
            "rule_id": str(audit.rule_id) if audit.rule_id else None,
            "domain": audit.domain,
            "entity_id": str(audit.entity_id),
            "employee_id": str(audit.employee_id) if audit.employee_id else None,
            "action": audit.action,
            "decision": audit.decision,
            "confidence_score": float(audit.confidence_score) if audit.confidence_score else None,
            "actor_id": str(audit.actor_id) if audit.actor_id else None,
            "before_snapshot": audit.before_snapshot_json,
            "after_snapshot": audit.after_snapshot_json,
            "policy_trace": audit.policy_trace_json,
            "explanation": audit.explanation,
            "is_rolled_back": audit.is_rolled_back,
            "rolled_back_by": str(audit.rolled_back_by) if audit.rolled_back_by else None,
            "rolled_back_at": audit.rolled_back_at.isoformat() if audit.rolled_back_at else None,
            "rollback_reason": audit.rollback_reason,
            "rollback_metadata": audit.rollback_metadata_json,
            "created_at": audit.created_at.isoformat() if audit.created_at else None,
        }

    async def _audit(
        self,
        action: str,
        domain: str,
        entity_id: uuid.UUID,
        explanation: str,
        decision: str | None = None,
        confidence_score: float | None = None,
        before_snapshot: dict[str, Any] | None = None,
        after_snapshot: dict[str, Any] | None = None,
        policy_trace: dict[str, Any] | None = None,
        rule_id: uuid.UUID | None = None,
        employee_id: uuid.UUID | None = None,
    ) -> None:
        """Create an audit log entry."""
        audit = AutopilotAuditLog(
            id=uuid.uuid4(),
            company_id=self.company_id,
            rule_id=rule_id,
            domain=domain,
            entity_id=entity_id,
            employee_id=employee_id,
            action=action,
            decision=decision or action,
            confidence_score=confidence_score,
            actor_id=self.actor_id,
            before_snapshot_json=before_snapshot,
            after_snapshot_json=after_snapshot,
            policy_trace_json=policy_trace,
            explanation=explanation,
        )
        self.db.add(audit)
        await self.db.flush()