"""EmployeeBankAccount model."""
from __future__ import annotations
from datetime import datetime
from typing import TYPE_CHECKING
import uuid
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base
if TYPE_CHECKING:
    from app.models.employee import Employee

class EmployeeBankAccount(Base):
    """Bank account details for salary processing."""
    __tablename__ = "employee_bank_accounts"
    __table_args__ = (Index("ix_employee_bank_accounts_employee_id", "employee_id"),)

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    bank_name: Mapped[str] = mapped_column(String(150), nullable=False)
    account_holder_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    account_number: Mapped[str] = mapped_column(String(30), nullable=False)
    ifsc_code: Mapped[str] = mapped_column(String(15), nullable=False)
    account_type: Mapped[str] = mapped_column(String(20), nullable=False, default="SAVINGS", server_default=text("'SAVINGS'"))
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    branch: Mapped[str | None] = mapped_column(String(100), nullable=True)
    upi_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    cancelled_cheque_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    passbook_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    employee: Mapped[Employee] = relationship("Employee", back_populates="bank_accounts")
