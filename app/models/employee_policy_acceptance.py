"""EmployeePolicyAcceptance database model."""
from __future__ import annotations
from datetime import datetime
from typing import TYPE_CHECKING
import uuid
from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base

if TYPE_CHECKING:
    from app.models.employee import Employee

class EmployeePolicyAcceptance(Base):
    """Tracks employee acceptance of various corporate policies."""
    __tablename__ = "employee_policy_acceptances"
    __table_args__ = (Index("ix_employee_policy_acceptances_employee_id", "employee_id"),)

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    policy_name: Mapped[str] = mapped_column(String(150), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0")
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    digital_signature: Mapped[str] = mapped_column(Text, nullable=False)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    employee: Mapped[Employee] = relationship("Employee", backref="policy_acceptances")
