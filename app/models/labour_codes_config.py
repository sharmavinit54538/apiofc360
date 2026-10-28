"""ORM registry for the Labour Codes configuration table."""

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects import postgresql

from app.db.base import Base


class LabourCodesConfig(Base):
    """Company-specific, effective-dated Labour Codes configuration."""

    __tablename__ = "labour_codes_configs"
    __table_args__ = (
        Index("ix_labour_codes_configs_company_id", "company_id"),
        Index("ix_labour_codes_configs_effective_from", "effective_from"),
    )

    id = Column(
        postgresql.UUID(as_uuid=True),
        primary_key=True,
        default=text("gen_random_uuid()"),
    )
    company_id = Column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=True,
    )

    basic_wage_min_pct = Column(Numeric(5, 4), nullable=False, server_default=text("0.50"))
    basic_wage_rule_enabled = Column(Boolean, nullable=False, server_default=text("true"))
    basic_wage_source_note = Column(String(500), nullable=True)
    needs_ca_validation_basic_wage = Column(Boolean, nullable=False, server_default=text("true"))
    wages_inclusions = Column(JSON, nullable=False, server_default=text("'[]'::json"))
    wages_exclusions = Column(JSON, nullable=False, server_default=text("'[]'::json"))
    wages_definition_source_note = Column(String(500), nullable=True)
    needs_ca_validation_wages_definition = Column(Boolean, nullable=False, server_default=text("true"))

    gratuity_enabled = Column(Boolean, nullable=False, server_default=text("true"))
    gratuity_eligible_service_years = Column(Integer, nullable=False, server_default=text("5"))
    gratuity_calculation_base = Column(String(30), nullable=False, server_default=text("'LAST_DRAWN_WAGES'"))
    gratuity_max_limit = Column(Numeric(14, 2), nullable=True)
    gratuity_source_note = Column(String(500), nullable=True)
    needs_ca_validation_gratuity = Column(Boolean, nullable=False, server_default=text("true"))

    pf_on_wages_definition = Column(Boolean, nullable=False, server_default=text("false"))
    pf_wage_ceiling_labour_codes = Column(Numeric(14, 2), nullable=True)
    pf_source_note = Column(String(500), nullable=True)
    needs_ca_validation_pf_labour_codes = Column(Boolean, nullable=False, server_default=text("true"))

    fixed_term_enabled = Column(Boolean, nullable=False, server_default=text("true"))
    fixed_term_max_duration_months = Column(Integer, nullable=False, server_default=text("24"))
    fixed_term_renewal_allowed = Column(Boolean, nullable=False, server_default=text("true"))
    fixed_term_gratuity_pro_rata = Column(Boolean, nullable=False, server_default=text("true"))
    fixed_term_source_note = Column(String(500), nullable=True)
    needs_ca_validation_fixed_term = Column(Boolean, nullable=False, server_default=text("true"))

    overtime_max_hours_per_quarter = Column(Integer, nullable=False, server_default=text("125"))
    overtime_source_note = Column(String(500), nullable=True)
    needs_ca_validation_overtime = Column(Boolean, nullable=False, server_default=text("true"))

    spread_over_max_hours = Column(Integer, nullable=False, server_default=text("12"))
    night_shift_allowance_pct = Column(Numeric(5, 4), nullable=True)
    night_shift_source_note = Column(String(500), nullable=True)
    needs_ca_validation_night_shift = Column(Boolean, nullable=False, server_default=text("true"))

    earned_leave_per_year = Column(Integer, nullable=False, server_default=text("15"))
    sick_leave_per_year = Column(Integer, nullable=False, server_default=text("12"))
    casual_leave_per_year = Column(Integer, nullable=False, server_default=text("12"))
    maternity_leave_weeks = Column(Integer, nullable=False, server_default=text("26"))
    paternity_leave_days = Column(Integer, nullable=False, server_default=text("15"))
    leave_source_note = Column(String(500), nullable=True)
    needs_ca_validation_leave = Column(Boolean, nullable=False, server_default=text("true"))

    settings_data = Column(postgresql.JSONB(astext_type=Text), nullable=True)
    effective_from = Column(Date, nullable=False, server_default=text("CURRENT_DATE"))
    is_active = Column(Boolean, nullable=False, server_default=text("true"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=text("now()"),
    )
