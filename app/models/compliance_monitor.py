"""AI Compliance Monitor model."""
from __future__ import annotations
from datetime import datetime
import uuid
from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base

class ComplianceAuditLog(Base):
    __tablename__ = "compliance_audit_logs"
    __table_args__ = (Index("ix_compliance_audit_company_id", "company_id"),)
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    audit_scope: Mapped[str] = mapped_column(String(50), nullable=False)   # HR_POLICY, ATTENDANCE, PAYROLL, LABOR_LAW, DATA_PRIVACY
    findings: Mapped[str | None] = mapped_column(Text, nullable=True)      # JSON: violations found
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False, default="LOW")  # LOW, MEDIUM, HIGH, CRITICAL
    recommendations: Mapped[str | None] = mapped_column(Text, nullable=True)
    auto_corrected: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON: actions taken
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
