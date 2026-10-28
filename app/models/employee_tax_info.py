"""EmployeeTaxInfo database model."""
from __future__ import annotations
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING
import uuid
from sqlalchemy import Boolean, BigInteger, Date, DateTime, ForeignKey, Index, Integer, String, Numeric, JSON, func, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base

if TYPE_CHECKING:
    from app.models.employee import Employee

class EmployeeTaxInfo(Base):
    """Stores tax regime, nominee and statutory tax details for employees."""
    __tablename__ = "employee_tax_info"
    __table_args__ = (Index("ix_employee_tax_info_employee_id", "employee_id"),)

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    tax_regime: Mapped[str] = mapped_column(String(20), nullable=False, default="NEW")  # OLD / NEW
    investment_declaration: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # Declared amounts
    professional_tax: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    salary_account: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Declaration / proof workflow and migrated-employer tax data.  Monetary
    # values that feed the payroll engine are integer paise, never floats.
    proof_status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING", server_default=text("'PENDING'"))
    proof_cutoff_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    use_verified_declarations: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    declared_details_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    verified_details_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    previous_employer_income_paise: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default=text("0"))
    previous_employer_tds_paise: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default=text("0"))
    ytd_tds_paise: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default=text("0"))
    one_time_bonus_paise: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default=text("0"))
    variable_pay_paise: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default=text("0"))
    proof_submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_verified_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    
    # Nominee Details
    nominee_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    nominee_relation: Mapped[str | None] = mapped_column(String(50), nullable=True)
    nominee_aadhaar: Mapped[str | None] = mapped_column(String(20), nullable=True)
    nominee_dob: Mapped[str | None] = mapped_column(String(20), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    employee: Mapped[Employee] = relationship("Employee", backref="tax_info")
