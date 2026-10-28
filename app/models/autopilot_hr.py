"""Autopilot HR policy, exception and immutable audit models.

The tables intentionally store JSON snapshots rather than references to a
second workflow system.  A rollback therefore has everything it needs to
restore the exact domain row that an autopilot decision changed.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, Numeric, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, synonym

from app.db.base import Base, TenantMixin, TimestampMixin


class AutopilotPolicyRule(TenantMixin, TimestampMixin, Base):
    __tablename__ = "autopilot_policy_rules"
    __table_args__ = (
        Index("ix_autopilot_rules_company_domain", "company_id", "domain"),
        Index("ix_autopilot_rules_enabled", "enabled"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    domain: Mapped[str] = mapped_column(String(50), nullable=False)
    action: Mapped[str] = mapped_column(String(40), nullable=False, default="FLAG_EXCEPTION")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    # ``is_active`` is a compatibility alias used by a few HR configuration
    # clients; both names refer to the same persisted value.
    is_active = synonym("enabled")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100, server_default=text("100"))
    confidence_threshold: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False, default=0.85, server_default=text("0.85"))
    conditions_json: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    escalation_ladder_json: Mapped[list | dict | None] = mapped_column(JSON, nullable=True)
    sla_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=24, server_default=text("24"))
    rule_metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class AutopilotExceptionItem(TenantMixin, TimestampMixin, Base):
    __tablename__ = "autopilot_exception_items"
    __table_args__ = (
        Index("ix_autopilot_exceptions_company_status", "company_id", "status"),
        Index("ix_autopilot_exceptions_sla", "sla_due_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    rule_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("autopilot_policy_rules.id", ondelete="SET NULL"), nullable=True)
    domain: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    employee_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="OPEN", server_default=text("'OPEN'"))
    explanation: Mapped[str] = mapped_column(Text, nullable=False, default="")
    exception_reasons: Mapped[list | None] = mapped_column(JSON, nullable=True)
    policy_trace_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    confidence_score: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    escalation_level: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    escalation_ladder_json: Mapped[list | dict | None] = mapped_column(JSON, nullable=True)
    assigned_to_user_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    assigned_role: Mapped[str | None] = mapped_column(String(50), nullable=True)
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sla_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    before_snapshot_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after_snapshot_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AutopilotAuditLog(TenantMixin, TimestampMixin, Base):
    __tablename__ = "autopilot_audit_logs"
    __table_args__ = (
        Index("ix_autopilot_audit_company_created", "company_id", "created_at"),
        Index("ix_autopilot_audit_entity", "domain", "entity_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    rule_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("autopilot_policy_rules.id", ondelete="SET NULL"), nullable=True)
    domain: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    employee_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    decision: Mapped[str] = mapped_column(String(40), nullable=False)
    confidence_score: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    before_snapshot_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after_snapshot_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    policy_trace_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_rolled_back: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    rolled_back_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rollback_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    rollback_metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


__all__ = ["AutopilotPolicyRule", "AutopilotExceptionItem", "AutopilotAuditLog"]
