"""Persistent employee leave balance/opening ledger used by leave and FnF."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TenantMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.employee import Employee


class LeaveBalance(Base, TenantMixin, TimestampMixin):
    """Current balance for one leave type and optional financial-year start year.

    ``balance_days`` is authoritative for imported/current balances.  When it is
    null, the remaining balance is allocated + carried-forward - used.
    """

    __tablename__ = "leave_balances"
    __table_args__ = (
        UniqueConstraint("employee_id", "leave_type", "year", name="uq_leave_balances_employee_type_year"),
        Index("ix_leave_balances_company_employee", "company_id", "employee_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    leave_type: Mapped[str] = mapped_column(String(50), nullable=False)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    allocated_days: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False, default=0, server_default=text("0"))
    used_days: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False, default=0, server_default=text("0"))
    carried_forward_days: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False, default=0, server_default=text("0"))
    balance_days: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    encashable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    encashable_days: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    encashment_base: Mapped[str] = mapped_column(String(10), nullable=False, default="BASIC", server_default=text("'BASIC'"))
    encashment_divisor: Mapped[int] = mapped_column(Integer, nullable=False, default=30, server_default=text("30"))

    employee: Mapped[Employee] = relationship("Employee", lazy="select")

    @property
    def remaining_days(self) -> Decimal:
        if self.balance_days is not None:
            return max(Decimal("0"), Decimal(str(self.balance_days)))
        return max(
            Decimal("0"), Decimal(str(self.allocated_days or 0))
            + Decimal(str(self.carried_forward_days or 0)) - Decimal(str(self.used_days or 0))
        )


__all__ = ["LeaveBalance"]
