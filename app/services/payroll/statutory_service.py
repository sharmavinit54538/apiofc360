"""Service for Indian Statutory Compliance calculation engine and government filing reports.

Implements deterministic calculations for:
1. PF (Provident Fund):
   - Employee: 12% of Basic (+ DA).
   - Employer: 3.67% EPF + 8.33% EPS (capped at ₹1,250/mo on ₹15,000 wage ceiling) + 0.5% EDLI + 0.5% Admin charges.
   - Configurable toggle for "Wage Ceiling (₹15,000)" vs "Actual Basic".
2. ESI (Employee State Insurance):
   - Applicable only if Gross Monthly Salary <= ₹21,000.
   - Employee: 0.75% of Gross (ROUND_HALF_UP to nearest rupee).
   - Employer: 3.25% of Gross (ROUND_HALF_UP to nearest rupee).
3. PT (Professional Tax):
   - State-wise slab engine (Maharashtra, Karnataka, Gujarat, Andhra Pradesh, Telangana, Tamil Nadu, West Bengal, MP, Rajasthan, Delhi, etc.)
4. LWF (Labour Welfare Fund):
   - State-specific contribution frequency & slabs.
5. TDS (Income Tax - Old vs New Regime):
   - Annualized taxable income projection, Standard Deduction (₹75,000 new / ₹50,000 old), 80C/80D/HRA exemptions, Section 87A rebate, 4% Health & Education Cess, divided across remaining months.
6. Gratuity provision:
   - (15 / 26) * Basic / 12 (~4.81% of basic).
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employee import Employee
from app.models.payroll import EmployeeInvestmentDeclaration, Payslip, StatutoryComplianceConfig
from app.models.payroll_compliance import (
    ComplianceChallan,
    ComplianceDueDate,
    FinancialYearTaxRule,
    PayrollCompliance,
    StateStatutoryRule,
    StatutoryForm,
)
from app.models.payroll_models import PayrollPeriod
from app.services.storage_service import StorageService
from app.services.payroll.money import as_decimal, round_to_rupee_paise

logger = logging.getLogger(__name__)


class StatutoryService:
    """Business logic for Indian statutory calculations, compliance config, and filing reports."""

    STATE_ALIASES = {
        "MAHARASHTRA": "MH", "MH": "MH", "KARNATAKA": "KA", "KA": "KA",
        "TAMIL NADU": "TN", "TAMILNADU": "TN", "TN": "TN", "TELANGANA": "TS",
        "TS": "TS", "TG": "TS", "DELHI": "DL", "DL": "DL", "HARYANA": "HR",
        "HR": "HR", "UTTAR PRADESH": "UP", "UP": "UP", "WEST BENGAL": "WB",
        "WB": "WB", "GUJARAT": "GJ", "GJ": "GJ", "RAJASTHAN": "RJ", "RJ": "RJ",
        "MADHYA PRADESH": "MP", "MP": "MP", "ANDHRA PRADESH": "AP", "AP": "AP",
        "MUMBAI": "MH", "PUNE": "MH", "NAGPUR": "MH", "BENGALURU": "KA",
        "BANGALORE": "KA", "CHENNAI": "TN", "HYDERABAD": "TS", "NEW DELHI": "DL",
        "GURUGRAM": "HR", "GURGAON": "HR", "FARIDABAD": "HR", "NOIDA": "UP",
        "LUCKNOW": "UP", "KOLKATA": "WB", "AHMEDABAD": "GJ", "SURAT": "GJ",
        "JAIPUR": "RJ", "INDORE": "MP", "BHOPAL": "MP",
    }

    # Seeded defaults are also used as a safe offline fallback for a new tenant.
    # Every amount is paise; ``max_gross_paise=None`` means no upper bound.
    DEFAULT_STATE_RULES: dict[str, dict[str, Any]] = {
        "MH": {"state_name": "Maharashtra", "pt_slabs": [
            {"min_gross_paise": 0, "max_gross_paise": 750000, "amount_paise": 0, "gender": "MALE"},
            {"min_gross_paise": 750001, "max_gross_paise": 1000000, "amount_paise": 17500, "gender": "MALE"},
            {"min_gross_paise": 0, "max_gross_paise": 1000000, "amount_paise": 0, "gender": "FEMALE"},
            {"min_gross_paise": 1000001, "max_gross_paise": None, "amount_paise": 20000, "monthly_amounts": {"2": 30000}},
        ], "lwf_employee_paise": 1200, "lwf_employer_paise": 3600, "lwf_frequency": "SEMI_ANNUAL", "lwf_applicable_months": [6, 12]},
        "KA": {"state_name": "Karnataka", "pt_slabs": [
            {"min_gross_paise": 0, "max_gross_paise": 1499999, "amount_paise": 0},
            {"min_gross_paise": 1500000, "max_gross_paise": None, "amount_paise": 20000},
        ], "lwf_employee_paise": 2000, "lwf_employer_paise": 4000, "lwf_frequency": "ANNUAL", "lwf_applicable_months": [12]},
        "TN": {"state_name": "Tamil Nadu", "pt_slabs": [
            {"min_gross_paise": 0, "max_gross_paise": 2100000, "amount_paise": 0},
            {"min_gross_paise": 2100001, "max_gross_paise": 3000000, "amount_paise": 10000},
            {"min_gross_paise": 3000001, "max_gross_paise": 4500000, "amount_paise": 23500},
            {"min_gross_paise": 4500001, "max_gross_paise": 6000000, "amount_paise": 51000},
            {"min_gross_paise": 6000001, "max_gross_paise": 7500000, "amount_paise": 76000},
            {"min_gross_paise": 7500001, "max_gross_paise": None, "amount_paise": 102500},
        ], "lwf_employee_paise": 0, "lwf_employer_paise": 0, "lwf_frequency": "ANNUAL", "lwf_applicable_months": [12]},
        "TS": {"state_name": "Telangana", "pt_slabs": [
            {"min_gross_paise": 0, "max_gross_paise": 1500000, "amount_paise": 0},
            {"min_gross_paise": 1500001, "max_gross_paise": 2000000, "amount_paise": 15000},
            {"min_gross_paise": 2000001, "max_gross_paise": None, "amount_paise": 20000},
        ], "lwf_employee_paise": 0, "lwf_employer_paise": 0, "lwf_frequency": "ANNUAL", "lwf_applicable_months": [12]},
        "DL": {"state_name": "Delhi", "pt_slabs": [], "lwf_employee_paise": 100, "lwf_employer_paise": 300, "lwf_frequency": "SEMI_ANNUAL", "lwf_applicable_months": [6, 12]},
        "HR": {"state_name": "Haryana", "pt_slabs": [], "lwf_employee_paise": 2500, "lwf_employer_paise": 5000, "lwf_frequency": "MONTHLY", "lwf_applicable_months": list(range(1, 13)), "lwf_employee_rate": "0.002", "lwf_employee_cap_paise": 2500, "lwf_employer_cap_paise": 5000},
        "UP": {"state_name": "Uttar Pradesh", "pt_slabs": [], "lwf_employee_paise": 0, "lwf_employer_paise": 0, "lwf_frequency": "MONTHLY", "lwf_applicable_months": []},
        "WB": {"state_name": "West Bengal", "pt_slabs": [
            {"min_gross_paise": 0, "max_gross_paise": 1000000, "amount_paise": 0},
            {"min_gross_paise": 1000001, "max_gross_paise": 1500000, "amount_paise": 11000},
            {"min_gross_paise": 1500001, "max_gross_paise": 2500000, "amount_paise": 13000},
            {"min_gross_paise": 2500001, "max_gross_paise": 4000000, "amount_paise": 15000},
            {"min_gross_paise": 4000001, "max_gross_paise": None, "amount_paise": 20000},
        ], "lwf_employee_paise": 0, "lwf_employer_paise": 0, "lwf_frequency": "SEMI_ANNUAL", "lwf_applicable_months": [6, 12]},
        "GJ": {"state_name": "Gujarat", "pt_slabs": [
            {"min_gross_paise": 0, "max_gross_paise": 1200000, "amount_paise": 0},
            {"min_gross_paise": 1200001, "max_gross_paise": None, "amount_paise": 20000},
        ], "lwf_employee_paise": 600, "lwf_employer_paise": 1200, "lwf_frequency": "SEMI_ANNUAL", "lwf_applicable_months": [6, 12]},
        "RJ": {"state_name": "Rajasthan", "pt_slabs": [], "lwf_employee_paise": 0, "lwf_employer_paise": 0, "lwf_frequency": "MONTHLY", "lwf_applicable_months": []},
        "MP": {"state_name": "Madhya Pradesh", "pt_slabs": [
            {"min_gross_paise": 0, "max_gross_paise": 1875000, "amount_paise": 0},
            {"min_gross_paise": 1875001, "max_gross_paise": 2500000, "amount_paise": 12500},
            {"min_gross_paise": 2500001, "max_gross_paise": 3333300, "amount_paise": 16700},
            {"min_gross_paise": 3333301, "max_gross_paise": None, "amount_paise": 20800, "monthly_amounts": {"3": 21200}},
        ], "lwf_employee_paise": 0, "lwf_employer_paise": 0, "lwf_frequency": "SEMI_ANNUAL", "lwf_applicable_months": [6, 12]},
    }


    # ─────────────────────────────────────────────────────────────────────────
    # 1. Config CRUD
    # ─────────────────────────────────────────────────────────────────────────

    @classmethod
    async def get_config(
        cls, session: AsyncSession, company_id: Optional[uuid.UUID] = None
    ) -> StatutoryComplianceConfig:
        stmt = select(StatutoryComplianceConfig).where(StatutoryComplianceConfig.is_active == True)
        if company_id:
            stmt = stmt.where(
                or_(
                    StatutoryComplianceConfig.company_id == company_id,
                    StatutoryComplianceConfig.company_id.is_(None),
                )
            )
        cfg = (await session.execute(stmt)).scalar_one_or_none()
        if not cfg:
            # Multi-tenancy: the auto-provisioned row always belongs to the
            # requesting tenant.  A company_id-less row is a shared template and
            # must never be created implicitly on a tenant's behalf.
            cfg = StatutoryComplianceConfig(is_active=True, company_id=company_id)
            session.add(cfg)
            await session.commit()
            await session.refresh(cfg)
        return cfg

    @classmethod
    async def update_config(
        cls,
        session: AsyncSession,
        payload: dict[str, Any],
        company_id: Optional[uuid.UUID] = None,
    ) -> StatutoryComplianceConfig:
        cfg = await cls.get_config(session, company_id=company_id)
        for field, value in payload.items():
            if hasattr(cfg, field) and value is not None:
                setattr(cfg, field, value)
        await session.commit()
        await session.refresh(cfg)
        return cfg

    #: ``needs_ca_validation_*`` scope name -> config attribute.
    CA_VALIDATION_SCOPE_FIELDS = {
        "pf_rates": "needs_ca_validation_pf_rates",
        "esi_rates": "needs_ca_validation_esi_rates",
        "pt_slabs": "needs_ca_validation_pt_slabs",
        "tds_slabs": "needs_ca_validation_tds_slabs",
        "gratuity": "needs_ca_validation_gratuity",
        "lwf": "needs_ca_validation_lwf",
        "labour_codes": "needs_ca_validation_labour_codes",
    }

    @classmethod
    async def ca_signoff(
        cls,
        session: AsyncSession,
        *,
        company_id: Optional[uuid.UUID],
        verified_by: Optional[uuid.UUID],
        certificate_ref: Optional[str] = None,
        formula_version: Optional[str] = None,
        scopes: Optional[list[str]] = None,
        remarks: Optional[str] = None,
        actor_role: Optional[str] = None,
    ) -> dict[str, Any]:
        """Record a CA / payroll-expert validation sign-off on the tenant config.

        Clears the selected ``needs_ca_validation_*`` flags (all of them when no
        scope list is supplied), stamps the verifying user/timestamp and the
        certificate + formula version, and writes an immutable payroll audit
        record.  The configuration row is always the requesting tenant's own
        active row; a shared template row is never modified.
        """
        from app.services.payroll.audit_service import PayrollAuditService

        if company_id is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Statutory configuration not found for this organization.",
            )

        stmt = select(StatutoryComplianceConfig).where(
            StatutoryComplianceConfig.company_id == company_id,
            StatutoryComplianceConfig.is_active == True,  # noqa: E712
        )
        cfg = (await session.execute(stmt)).scalar_one_or_none()
        if not cfg:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Statutory configuration not found for this organization.",
            )

        requested = [str(s).strip().lower() for s in (scopes or [])] or list(
            cls.CA_VALIDATION_SCOPE_FIELDS.keys()
        )
        unknown = [s for s in requested if s not in cls.CA_VALIDATION_SCOPE_FIELDS]
        if unknown:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "Unknown validation scope(s): "
                    + ", ".join(unknown)
                    + ". Allowed: "
                    + ", ".join(cls.CA_VALIDATION_SCOPE_FIELDS.keys())
                ),
            )

        before = {
            scope: bool(getattr(cfg, field, False))
            for scope, field in cls.CA_VALIDATION_SCOPE_FIELDS.items()
        }
        for scope in requested:
            setattr(cfg, cls.CA_VALIDATION_SCOPE_FIELDS[scope], False)

        signed_at = datetime.now(timezone.utc)
        if verified_by is not None:
            cfg.ca_verified_by = verified_by
        cfg.ca_verified_at = signed_at
        if certificate_ref:
            cfg.ca_certificate_ref = str(certificate_ref).strip()
        if formula_version:
            cfg.formula_version = str(formula_version).strip()

        note_bits = [
            f"CA sign-off by {verified_by} on {signed_at.isoformat()}",
            f"scopes={','.join(requested)}" if requested else None,
            f"certificate={cfg.ca_certificate_ref}" if cfg.ca_certificate_ref else None,
            f"formula_version={cfg.formula_version}" if cfg.formula_version else None,
            remarks,
        ]
        cfg.source_note = " | ".join(bit for bit in note_bits if bit)

        await PayrollAuditService.log_event(
            session=session,
            entity_type="StatutoryComplianceConfig",
            entity_id=cfg.id,
            action="CA_SIGNOFF",
            company_id=cfg.company_id,
            actor_id=verified_by,
            actor_role=actor_role,
            before_status=None,
            after_status=None,
            reason=remarks or "CA / payroll expert validation sign-off recorded",
            extra_data={
                "scopes": requested,
                "needs_ca_validation_before": before,
                "certificate_ref": cfg.ca_certificate_ref,
                "formula_version": cfg.formula_version,
            },
        )

        await session.commit()
        await session.refresh(cfg)

        return {
            "config_id": str(cfg.id),
            "company_id": str(cfg.company_id) if cfg.company_id else None,
            "ca_verified_by": str(cfg.ca_verified_by) if cfg.ca_verified_by else None,
            "ca_verified_at": cfg.ca_verified_at.isoformat() if cfg.ca_verified_at else None,
            "ca_certificate_ref": cfg.ca_certificate_ref,
            "formula_version": cfg.formula_version,
            "scopes_signed_off": requested,
            "needs_ca_validation": {
                scope: bool(getattr(cfg, field, False))
                for scope, field in cls.CA_VALIDATION_SCOPE_FIELDS.items()
            },
            "source_note": cfg.source_note,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # 2. Provident Fund (PF) Calculation Engine
    # ─────────────────────────────────────────────────────────────────────────

    @classmethod
    def calculate_pf(
        cls,
        basic_paise: int,
        da_paise: int = 0,
        config: Optional[StatutoryComplianceConfig] = None,
        pf_on_full_basic: Optional[bool] = None,
        is_pf_eligible: bool = True,
        is_international_worker: bool = False,
        pf_wage_ceiling_applicable: bool = True,
        age: Optional[int] = None,
        vpf_rate: Decimal | float | str | int = Decimal("0"),
        pf_higher_wage_opted: bool = False,
        pf_membership_active: bool = True,
        uan_number: Optional[str] = None,
        require_uan: bool = False,
        eps_rate: Optional[Decimal | float | str] = None,
        edli_rate: Optional[Decimal | float | str] = None,
        admin_rate: Optional[Decimal | float | str] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Calculate EPF/EPS/EDLI/admin using integer paise throughout.

        ``vpf_rate`` is a fraction (``0.05`` means five percent); percentages
        such as ``5`` are accepted for API convenience.  EPS wages are capped
        at the statutory ceiling unless the employee has explicitly opted for
        higher-wage pension (or is an international worker).
        """
        if "higher_wage_opted" in kwargs:
            pf_higher_wage_opted = bool(kwargs["higher_wage_opted"])
        if "vpf_percentage" in kwargs and not vpf_rate:
            vpf_rate = kwargs["vpf_percentage"]
        if "is_active" in kwargs:
            pf_membership_active = bool(kwargs["is_active"])

        uan_valid = True
        if uan_number is not None or require_uan:
            uan_valid, uan_error = Employee.validate_uan_format(uan_number)
            if require_uan and not uan_valid:
                raise ValueError(uan_error)
        else:
            uan_error = None

        wages_paise = max(0, int(basic_paise or 0) + int(da_paise or 0))
        enabled = bool(getattr(config, "pf_enabled", True)) if config else True
        zero = {
            "pf_wage_paise": 0, "eps_wage_paise": 0, "edli_wage_paise": 0,
            "employee_epf_paise": 0, "employee_vpf_paise": 0,
            "employee_pf_paise": 0, "employer_epf_paise": 0,
            "employer_eps_paise": 0, "employer_edli_paise": 0,
            "employer_admin_paise": 0, "total_employer_pf_paise": 0,
            "total_pf_liability_paise": 0, "wage_ceiling_applied": False,
            "is_active": False, "uan_valid": uan_valid,
            "vpf_rate": 0.0,
        }
        if not enabled or not is_pf_eligible or not pf_membership_active or wages_paise <= 0:
            return zero

        full_basic = (
            pf_on_full_basic if pf_on_full_basic is not None
            else bool(getattr(config, "pf_on_full_basic", False)) if config else False
        )
        ceiling_paise = int(as_decimal(getattr(config, "pf_wage_ceiling", 15000) if config else 15000) * 100)
        ceiling_paise = max(0, ceiling_paise)
        higher_wage = bool(pf_higher_wage_opted)

        if is_international_worker or higher_wage or not pf_wage_ceiling_applicable or full_basic:
            pf_wage_paise = wages_paise
        else:
            pf_wage_paise = min(wages_paise, ceiling_paise)
        if is_international_worker or higher_wage:
            eps_wage_paise = wages_paise
        else:
            eps_wage_paise = min(wages_paise, ceiling_paise)
        edli_wage_paise = min(wages_paise, ceiling_paise)

        employee_rate = as_decimal(getattr(config, "employee_pf_rate", Decimal("0.12")) if config else Decimal("0.12"))
        employer_rate = as_decimal(getattr(config, "employer_pf_rate", Decimal("0.12")) if config else Decimal("0.12"))
        pension_rate = as_decimal(eps_rate if eps_rate is not None else (getattr(config, "employer_eps_rate", Decimal("0.0833")) if config else Decimal("0.0833")))
        edli_rate_dec = as_decimal(edli_rate if edli_rate is not None else (getattr(config, "employer_edli_rate", Decimal("0.005")) if config else Decimal("0.005")))
        admin_rate_dec = as_decimal(admin_rate if admin_rate is not None else (getattr(config, "pf_admin_rate", Decimal("0.005")) if config else Decimal("0.005")))
        vpf_rate_dec = as_decimal(vpf_rate)
        if vpf_rate_dec > 1:
            vpf_rate_dec /= Decimal("100")
        vpf_rate_dec = max(Decimal("0"), min(vpf_rate_dec, Decimal("1")))

        employee_epf_paise = round_to_rupee_paise(Decimal(pf_wage_paise) * employee_rate)
        employee_vpf_paise = round_to_rupee_paise(Decimal(pf_wage_paise) * vpf_rate_dec)
        employee_pf_paise = employee_epf_paise + employee_vpf_paise
        if age is not None and age >= 58:
            employer_eps_paise = 0
        else:
            employer_eps_paise = round_to_rupee_paise(Decimal(eps_wage_paise) * pension_rate)
            if not (is_international_worker or higher_wage):
                employer_eps_paise = min(125000, employer_eps_paise)
        total_employer_12_paise = round_to_rupee_paise(Decimal(pf_wage_paise) * employer_rate)
        employer_epf_paise = max(0, total_employer_12_paise - employer_eps_paise)
        employer_edli_paise = round_to_rupee_paise(Decimal(edli_wage_paise) * edli_rate_dec)
        employer_admin_paise = round_to_rupee_paise(Decimal(pf_wage_paise) * admin_rate_dec)
        total_employer_pf_paise = employer_epf_paise + employer_eps_paise

        return {
            "pf_wage_paise": pf_wage_paise,
            "eps_wage_paise": eps_wage_paise,
            "edli_wage_paise": edli_wage_paise,
            "employee_epf_paise": employee_epf_paise,
            "employee_vpf_paise": employee_vpf_paise,
            "employee_pf_paise": employee_pf_paise,
            "employer_epf_paise": employer_epf_paise,
            "employer_eps_paise": employer_eps_paise,
            "employer_edli_paise": employer_edli_paise,
            "employer_admin_paise": employer_admin_paise,
            "total_employer_pf_paise": total_employer_pf_paise,
            "total_pf_liability_paise": employee_pf_paise + total_employer_pf_paise + employer_edli_paise + employer_admin_paise,
            "wage_ceiling_applied": pf_wage_paise < wages_paise,
            "is_active": True,
            "uan_valid": uan_valid,
            "uan_error": uan_error,
            "vpf_rate": float(vpf_rate_dec),
        }


    # ─────────────────────────────────────────────────────────────────────────
    # 2b. Labour Codes — "Wages" Definition (50% Rule)
    # ─────────────────────────────────────────────────────────────────────────

    #: Component codes that are *never* treated as excluded allowances, because
    #: the Code on Wages explicitly counts them inside "wages".
    ALWAYS_WAGE_COMPONENTS = frozenset({"BASIC", "DA", "DEARNESS_ALLOWANCE", "RETAINING_ALLOWANCE"})

    DEFAULT_EXCLUDED_ALLOWANCES = (
        "HRA", "CONVEYANCE", "OVERTIME", "STATUTORY_BONUS", "COMMISSION",
    )

    @classmethod
    def _excluded_allowance_codes(cls, config: Optional[StatutoryComplianceConfig]) -> list[str]:
        """Read the excluded-allowance component codes from config (upper-cased)."""
        raw = getattr(config, "excluded_allowance_components_json", None) if config else None
        if not raw:
            raw = list(cls.DEFAULT_EXCLUDED_ALLOWANCES)
        if isinstance(raw, str):
            raw = [raw]
        codes: list[str] = []
        for item in raw:
            code = str(item).strip().upper()
            if code:
                codes.append(code)
        return codes

    @classmethod
    def apply_labour_code_wage_rule(
        cls,
        *,
        gross_remuneration_paise: int,
        basic_paise: int,
        da_paise: int = 0,
        allowances: Optional[dict[str, int]] = None,
        config: Optional[StatutoryComplianceConfig] = None,
    ) -> dict[str, Any]:
        """Apply the Code on Wages, 2019 definition of "wages" (the 50% rule).

        Under the Code, "wages" means all remuneration **except** the excluded
        allowances (HRA, conveyance, overtime, statutory bonus, commission, ...),
        *provided* those exclusions do not exceed 50% (configurable via
        ``min_basic_wage_ratio``) of the total remuneration.  Any excess must be
        added back into the wage base used for PF, ESI and Gratuity.

        Everything is integer paise; the ratio arithmetic uses ``Decimal`` with
        ``ROUND_HALF_UP`` so no float ever touches a money value.

        Returns a breakdown dict.  ``statutory_wages_paise`` is the amount PF /
        ESI / Gratuity must be computed on.
        """
        gross_paise = int(gross_remuneration_paise or 0)
        base_wages_paise = int(basic_paise or 0) + int(da_paise or 0)
        excluded_codes = cls._excluded_allowance_codes(config)
        allowance_map = {
            str(k).strip().upper(): int(v or 0) for k, v in (allowances or {}).items()
        }

        enabled = bool(getattr(config, "labour_code_enabled", False)) if config else False

        excluded_paise = sum(
            amount for code, amount in allowance_map.items()
            if code in excluded_codes and code not in cls.ALWAYS_WAGE_COMPONENTS
        )

        if not enabled:
            return {
                "labour_code_enabled": False,
                "applied": False,
                "min_basic_wage_ratio": None,
                "excluded_components": excluded_codes,
                "excluded_allowances_paise": excluded_paise,
                "max_excluded_paise": None,
                "excess_paise": 0,
                "basic_da_paise": base_wages_paise,
                "statutory_wages_paise": base_wages_paise,
                "gross_remuneration_paise": gross_paise,
            }

        ratio_raw = getattr(config, "min_basic_wage_ratio", None)
        ratio = Decimal(str(ratio_raw)) if ratio_raw is not None else Decimal("0.5")
        if ratio < Decimal("0"):
            ratio = Decimal("0")
        elif ratio > Decimal("1"):
            ratio = Decimal("1")

        max_excluded = (
            Decimal(gross_paise) * (Decimal("1") - ratio)
        ).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        max_excluded_paise = int(max_excluded)

        excess_paise = max(0, excluded_paise - max_excluded_paise)
        statutory_wages_paise = base_wages_paise + excess_paise

        return {
            "labour_code_enabled": True,
            "applied": excess_paise > 0,
            "min_basic_wage_ratio": float(ratio),
            "excluded_components": excluded_codes,
            "excluded_allowances_paise": excluded_paise,
            "max_excluded_paise": max_excluded_paise,
            "excess_paise": excess_paise,
            "basic_da_paise": base_wages_paise,
            "statutory_wages_paise": statutory_wages_paise,
            "gross_remuneration_paise": gross_paise,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # 3. Employee State Insurance (ESI) Calculation Engine
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def esi_contribution_period(value: date) -> tuple[date, date]:
        """Return the ESIC contribution period containing ``value``.

        April–September and October–March are deliberately calculated from
        dates rather than calendar quarters.  The returned start date is the
        lock key used when an employee's salary changes mid-period.
        """
        if value.month >= 10:
            return date(value.year, 10, 1), date(value.year + 1, 3, 31)
        if value.month >= 4:
            return date(value.year, 4, 1), date(value.year, 9, 30)
        return date(value.year - 1, 10, 1), date(value.year, 3, 31)

    @classmethod
    def get_esi_contribution_period(cls, value: date) -> dict[str, Any]:
        start, end = cls.esi_contribution_period(value)
        return {"start": start, "end": end, "key": start.isoformat()}

    @classmethod
    def calculate_esi(
        cls,
        gross_monthly_paise: int,
        config: Optional[StatutoryComplianceConfig] = None,
        contribution_wage_paise: Optional[int] = None,
        is_pwd: bool = False,
        covered_at_period_start: Optional[bool] = None,
        as_of_date: Optional[date] = None,
        contribution_period_start: Optional[date] = None,
        period_start: Optional[date] = None,
        previously_covered: Optional[bool] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Calculate ESI with the PwD ceiling and six-month coverage lock.

        Coverage is tested against gross monthly wages at the beginning of an
        ESIC contribution period.  Once covered, later salary growth does not
        switch contributions off until the next contribution period.
        """
        if "pwd" in kwargs:
            is_pwd = bool(kwargs["pwd"])
        if "is_person_with_disability" in kwargs:
            is_pwd = bool(kwargs["is_person_with_disability"])
        if "covered_at_contribution_period_start" in kwargs and covered_at_period_start is None:
            covered_at_period_start = bool(kwargs["covered_at_contribution_period_start"])
        for alias in ("covered_at_start", "esi_covered_at_period_start", "is_covered_at_period_start"):
            if alias in kwargs and covered_at_period_start is None:
                covered_at_period_start = bool(kwargs[alias])
        if previously_covered is not None and covered_at_period_start is None:
            covered_at_period_start = previously_covered

        gross = max(0, int(gross_monthly_paise or 0))
        enabled = bool(getattr(config, "esi_enabled", True)) if config else True
        regular_ceiling = int(as_decimal(getattr(config, "esi_wage_ceiling", 21000) if config else 21000) * 100)
        pwd_ceiling = int(as_decimal(getattr(config, "esi_pwd_wage_ceiling", 25000) if config else 25000) * 100)
        ceiling = pwd_ceiling if is_pwd else regular_ceiling
        supplied_lock_start = contribution_period_start or period_start
        # When only the contribution-period start is supplied, it is also the
        # evaluation context; this keeps pure calculation calls deterministic.
        current_date = as_of_date or supplied_lock_start or date.today()
        lock_start, lock_end = cls.esi_contribution_period(current_date)
        lock_matches = True
        if as_of_date is not None and supplied_lock_start is not None:
            supplied_start, _ = cls.esi_contribution_period(supplied_lock_start)
            lock_matches = supplied_start == lock_start
        locked = bool(covered_at_period_start) and lock_matches
        covered = gross <= ceiling or locked

        reason = "Eligible under gross wage ceiling"
        if locked and gross > ceiling:
            reason = "Covered at contribution-period start; six-month lock applies"
        elif not covered and gross > ceiling:
            reason = f"Exceeds ₹{ceiling // 100:,} gross wage ceiling"
        elif not enabled or gross <= 0:
            reason = "ESI disabled or zero gross"

        wage_base = max(0, int(contribution_wage_paise if contribution_wage_paise is not None else gross))
        if not enabled or gross <= 0 or not covered:
            employee = employer = 0
        else:
            emp_rate = as_decimal(getattr(config, "employee_esi_rate", Decimal("0.0075")) if config else Decimal("0.0075"))
            empr_rate = as_decimal(getattr(config, "employer_esi_rate", Decimal("0.0325")) if config else Decimal("0.0325"))
            employee = round_to_rupee_paise(Decimal(wage_base) * emp_rate)
            employer = round_to_rupee_paise(Decimal(wage_base) * empr_rate)

        applicable = bool(enabled and gross > 0 and covered)
        return {
            "is_applicable": applicable,
            "gross_paise": gross,
            "contribution_wage_paise": wage_base,
            "employee_esi_paise": employee,
            "employer_esi_paise": employer,
            "total_esi_liability_paise": employee + employer,
            "ceiling_paise": ceiling,
            "is_pwd": bool(is_pwd),
            "contribution_period_lock": locked,
            "covered_at_period_start": bool(covered_at_period_start) if covered_at_period_start is not None else gross <= ceiling,
            "contribution_period_start": lock_start.isoformat(),
            "contribution_period_end": lock_end.isoformat(),
            "reason": reason,
        }


    # ─────────────────────────────────────────────────────────────────────────
    # 4. Professional Tax (PT) State-Wise Slab Engine
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _state_code(state: str | None) -> str:
        raw = re.sub(r"\s+", " ", (state or "MAHARASHTRA").strip().upper())
        if raw in StatutoryService.STATE_ALIASES:
            return StatutoryService.STATE_ALIASES[raw]
        for label, code in sorted(StatutoryService.STATE_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
            if len(label) > 2 and re.search(rf"\b{re.escape(label)}\b", raw):
                return code
        return raw

    @staticmethod
    def _rule_value(rule: Any, *names: str, default: Any = None) -> Any:
        if rule is None:
            return default
        for name in names:
            if isinstance(rule, dict) and name in rule:
                return rule[name]
            if hasattr(rule, name):
                return getattr(rule, name)
        return default

    @staticmethod
    def _amount_paise(value: Any, *, paise: bool = False) -> int:
        if value is None:
            return 0
        amount = as_decimal(value)
        return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP) if paise else (amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    @classmethod
    def _default_rule(cls, state: str) -> dict[str, Any]:
        code = cls._state_code(state)
        return cls.DEFAULT_STATE_RULES.get(code, {
            "state_name": code, "pt_slabs": [
                {"min_gross_paise": 0, "max_gross_paise": 1000000, "amount_paise": 0},
                {"min_gross_paise": 1000001, "max_gross_paise": None, "amount_paise": 20000},
            ], "lwf_employee_paise": 1000, "lwf_employer_paise": 2000,
            "lwf_frequency": "MONTHLY", "lwf_applicable_months": list(range(1, 13)),
        })

    @classmethod
    async def get_state_statutory_rule(
        cls, session: AsyncSession, state: str, company_id: Optional[uuid.UUID] = None,
        as_of: Optional[date] = None,
    ) -> Optional[StateStatutoryRule]:
        """Resolve the latest effective tenant rule, falling back to defaults."""
        code = cls._state_code(state)
        on_date = as_of or date.today()
        stmt = select(StateStatutoryRule).where(
            StateStatutoryRule.state_code == code,
            StateStatutoryRule.is_active == True,
            StateStatutoryRule.effective_from <= on_date,
            or_(StateStatutoryRule.effective_to.is_(None), StateStatutoryRule.effective_to >= on_date),
        )
        if company_id:
            stmt = stmt.where(or_(StateStatutoryRule.company_id == company_id, StateStatutoryRule.company_id.is_(None)))
        else:
            stmt = stmt.where(StateStatutoryRule.company_id.is_(None))
        rows = (await session.execute(stmt)).scalars().all()
        if not rows:
            return None
        rows.sort(key=lambda r: (r.company_id == company_id if company_id else False, r.effective_from), reverse=True)
        return rows[0]

    @classmethod
    async def seed_state_statutory_rules(
        cls, session: AsyncSession, company_id: Optional[uuid.UUID] = None,
    ) -> int:
        """Idempotently seed the eleven requested state rule sets."""
        created = 0
        for code, values in cls.DEFAULT_STATE_RULES.items():
            stmt = select(StateStatutoryRule).where(
                StateStatutoryRule.state_code == code,
                StateStatutoryRule.company_id.is_(None) if company_id is None else StateStatutoryRule.company_id == company_id,
                StateStatutoryRule.effective_from == date(2020, 1, 1),
            )
            if (await session.execute(stmt)).scalar_one_or_none():
                continue
            session.add(StateStatutoryRule(
                company_id=company_id, state_code=code, state_name=values["state_name"],
                effective_from=date(2020, 1, 1), pt_slabs_json=values["pt_slabs"],
                lwf_employee_paise=values.get("lwf_employee_paise", 0),
                lwf_employer_paise=values.get("lwf_employer_paise", 0),
                lwf_frequency=values.get("lwf_frequency", "MONTHLY"),
                lwf_applicable_months=values.get("lwf_applicable_months", []),
                needs_ca_validation=True,
            ))
            created += 1
        if created:
            await session.commit()
        return created

    @classmethod
    async def upsert_state_statutory_rule(
        cls, session: AsyncSession, state: str, payload: dict[str, Any],
        company_id: Optional[uuid.UUID] = None,
    ) -> StateStatutoryRule:
        code = cls._state_code(state)
        effective_from = payload.get("effective_from") or payload.get("effectiveFrom") or date.today()
        if isinstance(effective_from, str):
            effective_from = date.fromisoformat(effective_from)
        stmt = select(StateStatutoryRule).where(
            StateStatutoryRule.state_code == code,
            StateStatutoryRule.effective_from == effective_from,
            StateStatutoryRule.company_id.is_(None) if company_id is None else StateStatutoryRule.company_id == company_id,
        )
        rule = (await session.execute(stmt)).scalar_one_or_none()
        defaults = cls._default_rule(code)
        if not rule:
            rule = StateStatutoryRule(
                state_code=code, state_name=defaults["state_name"], company_id=company_id,
                effective_from=effective_from, pt_slabs_json=defaults["pt_slabs"],
                lwf_employee_paise=defaults.get("lwf_employee_paise", 0),
                lwf_employer_paise=defaults.get("lwf_employer_paise", 0),
                lwf_frequency=defaults.get("lwf_frequency", "MONTHLY"),
                lwf_applicable_months=defaults.get("lwf_applicable_months", []),
            )
            session.add(rule)
        for field, aliases in {
            "state_name": ("state_name", "stateName"), "effective_to": ("effective_to", "effectiveTo"),
            "pt_slabs_json": ("pt_slabs_json", "pt_slabs", "ptSlabs"),
            "lwf_employee_paise": ("lwf_employee_paise", "lwfEmployeePaise"),
            "lwf_employer_paise": ("lwf_employer_paise", "lwfEmployerPaise"),
            "lwf_frequency": ("lwf_frequency", "lwfFrequency"),
            "lwf_applicable_months": ("lwf_applicable_months", "lwfApplicableMonths"),
            "needs_ca_validation": ("needs_ca_validation", "needsCaValidation"),
            "is_active": ("is_active", "isActive"),
        }.items():
            value = next((payload[name] for name in aliases if name in payload), None)
            if value is not None:
                if field == "effective_to" and isinstance(value, str):
                    value = date.fromisoformat(value)
                setattr(rule, field, value)
        await session.commit()
        await session.refresh(rule)
        return rule


    @classmethod
    def calculate_pt(
        cls,
        gross_monthly_paise: int,
        state: str = "MAHARASHTRA",
        month: int = 3,
        gender: str = "MALE",
        rule: Any = None,
        state_rule: Any = None,
        pt_slabs: Optional[list[dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Evaluate PT slabs by state, gender and month using integer paise."""
        selected_rule = rule or state_rule
        code = cls._state_code(state)
        defaults = cls._default_rule(code)
        slabs = pt_slabs
        if slabs is None:
            slabs = cls._rule_value(selected_rule, "pt_slabs_json", "pt_slabs", "slabs", default=None)
        if slabs is None:
            slabs = defaults["pt_slabs"]
        gross = max(0, int(gross_monthly_paise or 0))
        gender_code = (gender or "MALE").strip().upper()
        if gender_code in {"M", "MALE"}:
            gender_code = "MALE"
        elif gender_code in {"F", "FEMALE", "W", "WOMAN"}:
            gender_code = "FEMALE"
        candidates: list[tuple[int, int, dict[str, Any]]] = []
        for slab in slabs or []:
            if not isinstance(slab, dict):
                continue
            slab_gender = str(slab.get("gender", slab.get("applicable_gender", "ALL"))).upper()
            if slab_gender not in {"ALL", "ANY", "BOTH", gender_code}:
                continue
            months = slab.get("months", slab.get("applicable_months"))
            if months and int(month) not in {int(m) for m in months}:
                continue
            if slab.get("month") is not None and int(slab["month"]) != int(month):
                continue
            min_gross = slab.get("min_gross_paise")
            min_gross = cls._amount_paise(min_gross, paise=True) if min_gross is not None else cls._amount_paise(slab.get("min_gross", slab.get("from", 0)))
            max_raw = slab.get("max_gross_paise", slab.get("max_gross", slab.get("to")))
            max_gross = None if max_raw is None else cls._amount_paise(max_raw, paise="max_gross_paise" in slab)
            if gross < min_gross or (max_gross is not None and gross > max_gross):
                continue
            candidates.append((1 if slab_gender == gender_code else 0, min_gross, slab))
        amount = 0
        selected_slab: Optional[dict[str, Any]] = None
        if candidates:
            _, _, selected_slab = max(candidates, key=lambda item: (item[0], item[1]))
            monthly = selected_slab.get("monthly_amounts", {})
            if str(month) in monthly:
                amount = cls._amount_paise(monthly[str(month)], paise=True)
            elif month in monthly:
                amount = cls._amount_paise(monthly[month], paise=True)
            elif month == 2 and selected_slab.get("february_amount_paise") is not None:
                amount = cls._amount_paise(selected_slab["february_amount_paise"], paise=True)
            elif "amount_paise" in selected_slab:
                amount = cls._amount_paise(selected_slab["amount_paise"], paise=True)
            else:
                amount = cls._amount_paise(selected_slab.get("amount", selected_slab.get("pt_amount", 0)))
        return {
            "state": code, "state_code": code, "gross_paise": gross,
            "pt_paise": max(0, amount), "pt_inr": Decimal(max(0, amount)) / 100,
            "month": int(month), "gender": gender_code,
            "rule_id": str(cls._rule_value(selected_rule, "id", default="")) or None,
            "needs_ca_validation": bool(cls._rule_value(selected_rule, "needs_ca_validation", default=True)),
            "slab": selected_slab,
        }

    @classmethod
    def calculate_lwf(
        cls,
        gross_monthly_paise: int,
        state: str = "MAHARASHTRA",
        month: int = 6,
        rule: Any = None,
        state_rule: Any = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Calculate state/month-specific employee and employer LWF in paise."""
        selected_rule = rule or state_rule
        code = cls._state_code(state)
        defaults = cls._default_rule(code)
        gross = max(0, int(gross_monthly_paise or 0))
        frequency = str(cls._rule_value(selected_rule, "lwf_frequency", "frequency", default=defaults.get("lwf_frequency", "MONTHLY"))).upper()
        months = cls._rule_value(selected_rule, "lwf_applicable_months", "applicable_months", default=None)
        if months is None:
            months = defaults.get("lwf_applicable_months", [])
        if not months:
            months = list(range(1, 13)) if frequency == "MONTHLY" else ([12] if frequency == "ANNUAL" else [6, 12])
        applicable_month = int(month) in {int(m) for m in months}
        employee = cls._rule_value(selected_rule, "lwf_employee_paise", "employee_lwf_paise", default=None)
        employer = cls._rule_value(selected_rule, "lwf_employer_paise", "employer_lwf_paise", default=None)
        if employee is None:
            employee = defaults.get("lwf_employee_paise", 0)
        if employer is None:
            employer = defaults.get("lwf_employer_paise", 0)
        employee_paise = cls._amount_paise(employee, paise=True)
        employer_paise = cls._amount_paise(employer, paise=True)
        # Some states express LWF as a percentage with a monthly cap (HR).
        emp_rate = cls._rule_value(selected_rule, "lwf_employee_rate", "employee_rate", default=defaults.get("lwf_employee_rate"))
        if emp_rate is not None:
            employee_paise = round_to_rupee_paise(Decimal(gross) * as_decimal(emp_rate))
            cap = cls._rule_value(selected_rule, "lwf_employee_cap_paise", "employee_cap_paise", default=defaults.get("lwf_employee_cap_paise"))
            if cap is not None:
                employee_paise = min(employee_paise, cls._amount_paise(cap, paise=True))
            employer_paise = employee_paise * 2
            employer_cap = cls._rule_value(selected_rule, "lwf_employer_cap_paise", "employer_cap_paise", default=defaults.get("lwf_employer_cap_paise"))
            if employer_cap is not None:
                employer_paise = min(employer_paise, cls._amount_paise(employer_cap, paise=True))
        if gross <= 0 or not applicable_month:
            employee_paise = employer_paise = 0
        return {
            "employee_lwf_paise": employee_paise, "employer_lwf_paise": employer_paise,
            "is_applicable": bool(employee_paise + employer_paise), "state": code,
            "state_code": code, "month": int(month), "frequency": frequency,
            "applicable_months": sorted({int(m) for m in months}),
            "rule_id": str(cls._rule_value(selected_rule, "id", default="")) or None,
        }


    # ─────────────────────────────────────────────────────────────────────────
    # 6. TDS (Income Tax - Old vs New Regime) Projection Engine
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _fy_start_year(financial_year: str | None) -> int:
        match = re.search(r"(20\d{2})", str(financial_year or ""))
        return int(match.group(1)) if match else 2024

    @classmethod
    def _default_tax_rule(cls, financial_year: str, regime: str) -> dict[str, Any]:
        """Return editable statutory defaults; no calculation uses float slabs."""
        old = regime == "OLD"
        if old:
            return {
                "standard_deduction_paise": 5000000,
                "slabs": [
                    {"up_to_paise": 25000000, "rate": Decimal("0")},
                    {"up_to_paise": 50000000, "rate": Decimal("0.05")},
                    {"up_to_paise": 100000000, "rate": Decimal("0.20")},
                    {"up_to_paise": None, "rate": Decimal("0.30")},
                ],
                "rebate_87a_limit_paise": 50000000, "rebate_87a_max_paise": 1250000,
                "chapter_via_limits": {"80C": 15000000, "80D": 5000000, "80CCD1B": 5000000, "80TTA": 1000000, "24B": 20000000},
                "cess_rate": Decimal("0.04"),
                "surcharge_slabs": [
                    {"above_paise": 500000000, "rate": Decimal("0.10")},
                    {"above_paise": 1000000000, "rate": Decimal("0.15")},
                    {"above_paise": 2000000000, "rate": Decimal("0.25")},
                    {"above_paise": 5000000000, "rate": Decimal("0.37")},
                ],
            }
        # FY 2025-26 onwards uses the revised new-regime slab structure.  The
        # legacy structure remains available explicitly for earlier FYs.
        if cls._fy_start_year(financial_year) >= 2025:
            slabs = [
                {"up_to_paise": 40000000, "rate": Decimal("0")},
                {"up_to_paise": 80000000, "rate": Decimal("0.05")},
                {"up_to_paise": 120000000, "rate": Decimal("0.10")},
                {"up_to_paise": 160000000, "rate": Decimal("0.15")},
                {"up_to_paise": 200000000, "rate": Decimal("0.20")},
                {"up_to_paise": 240000000, "rate": Decimal("0.25")},
                {"up_to_paise": None, "rate": Decimal("0.30")},
            ]
            rebate_limit, rebate_max = 120000000, 6000000
        else:
            slabs = [
                {"up_to_paise": 30000000, "rate": Decimal("0")},
                {"up_to_paise": 70000000, "rate": Decimal("0.05")},
                {"up_to_paise": 100000000, "rate": Decimal("0.10")},
                {"up_to_paise": 120000000, "rate": Decimal("0.15")},
                {"up_to_paise": 150000000, "rate": Decimal("0.20")},
                {"up_to_paise": None, "rate": Decimal("0.30")},
            ]
            rebate_limit, rebate_max = 70000000, 2500000
        return {
            "standard_deduction_paise": 7500000 if cls._fy_start_year(financial_year) >= 2024 else 5000000, "slabs": slabs,
            "rebate_87a_limit_paise": rebate_limit, "rebate_87a_max_paise": rebate_max,
            "chapter_via_limits": {"80CCD2": None}, "cess_rate": Decimal("0.04"),
            "surcharge_slabs": [
                {"above_paise": 500000000, "rate": Decimal("0.10")},
                {"above_paise": 1000000000, "rate": Decimal("0.15")},
                {"above_paise": 2000000000, "rate": Decimal("0.25")},
            ],
        }

    @classmethod
    def _tax_rule_dict(cls, rule: Any, financial_year: str, regime: str) -> dict[str, Any]:
        defaults = cls._default_tax_rule(financial_year, regime)
        if rule is None:
            return defaults
        if isinstance(rule, (list, tuple)):
            result = dict(defaults)
            result["slabs"] = rule
            return result
        if isinstance(rule, dict) and ("OLD" in rule or "NEW" in rule):
            rule = rule.get(regime) or rule.get(regime.lower()) or {}
        result = dict(defaults)
        for key, aliases in {
            "slabs": ("slabs_json", "slabs", "tax_slabs"),
            "standard_deduction_paise": ("standard_deduction_paise",),
            "rebate_87a_limit_paise": ("rebate_87a_limit_paise", "rebate_limit_paise"),
            "rebate_87a_max_paise": ("rebate_87a_max_paise", "rebate_max_paise"),
            "chapter_via_limits": ("chapter_via_limits_json", "chapter_via_limits"),
            "surcharge_slabs": ("surcharge_slabs_json", "surcharge_slabs"),
            "cess_rate": ("cess_rate",),
        }.items():
            value = cls._rule_value(rule, *aliases, default=None)
            if value is not None:
                result[key] = value
        # Rupee-facing configuration fields are converted once, at the edge.
        for key, aliases in {
            "standard_deduction_paise": ("standard_deduction", "standard_deduction_inr"),
            "rebate_87a_limit_paise": ("rebate_87a_limit", "rebate_limit"),
            "rebate_87a_max_paise": ("rebate_87a_max", "rebate_max"),
        }.items():
            value = cls._rule_value(rule, *aliases, default=None)
            if value is not None:
                result[key] = cls._amount_paise(value)
        return result

    @classmethod
    async def get_financial_year_tax_rule(
        cls, session: AsyncSession, financial_year: str, regime: str,
        company_id: Optional[uuid.UUID] = None,
    ) -> Optional[FinancialYearTaxRule]:
        regime_code = "OLD" if str(regime).upper().startswith("OLD") else "NEW"
        stmt = select(FinancialYearTaxRule).where(
            FinancialYearTaxRule.financial_year == financial_year,
            FinancialYearTaxRule.regime == regime_code,
            FinancialYearTaxRule.is_active == True,
        )
        if company_id:
            stmt = stmt.where(or_(FinancialYearTaxRule.company_id == company_id, FinancialYearTaxRule.company_id.is_(None)))
        else:
            stmt = stmt.where(FinancialYearTaxRule.company_id.is_(None))
        rows = (await session.execute(stmt)).scalars().all()
        if company_id:
            rows.sort(key=lambda row: row.company_id == company_id, reverse=True)
        return rows[0] if rows else None

    @classmethod
    async def upsert_financial_year_tax_rule(
        cls, session: AsyncSession, financial_year: str, regime: str,
        payload: dict[str, Any], company_id: Optional[uuid.UUID] = None,
    ) -> FinancialYearTaxRule:
        regime_code = "OLD" if str(regime).upper().startswith("OLD") else "NEW"
        stmt = select(FinancialYearTaxRule).where(
            FinancialYearTaxRule.financial_year == financial_year,
            FinancialYearTaxRule.regime == regime_code,
            FinancialYearTaxRule.company_id.is_(None) if company_id is None else FinancialYearTaxRule.company_id == company_id,
        )
        rule = (await session.execute(stmt)).scalar_one_or_none()
        if not rule:
            defaults = cls._default_tax_rule(financial_year, regime_code)
            rule = FinancialYearTaxRule(
                financial_year=financial_year, regime=regime_code, company_id=company_id,
                slabs_json=cls._json_safe(defaults["slabs"]),
                standard_deduction_paise=defaults["standard_deduction_paise"],
                rebate_87a_limit_paise=defaults["rebate_87a_limit_paise"],
                rebate_87a_max_paise=defaults["rebate_87a_max_paise"],
                chapter_via_limits_json=defaults["chapter_via_limits"],
                surcharge_slabs_json=cls._json_safe(defaults["surcharge_slabs"]),
            )
            session.add(rule)
        for field in ("slabs_json", "standard_deduction_paise", "rebate_87a_limit_paise", "rebate_87a_max_paise", "chapter_via_limits_json", "surcharge_slabs_json", "cess_rate", "proof_cutoff_date", "needs_ca_validation", "is_active"):
            alias = field.replace("_json", "")
            if field in payload:
                value = payload[field]
            elif alias in payload:
                value = payload[alias]
            else:
                continue
            if field == "proof_cutoff_date" and isinstance(value, str):
                value = date.fromisoformat(value)
            setattr(rule, field, value)
        await session.commit()
        await session.refresh(rule)
        return rule


    @classmethod
    def _normalise_slabs(cls, raw_slabs: Any, default: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not raw_slabs:
            return default
        normalized = []
        for slab in raw_slabs:
            if not isinstance(slab, dict):
                continue
            up_to = slab.get("up_to_paise", slab.get("max_paise"))
            paise_bound = up_to is not None
            if up_to is None:
                up_to = slab.get("up_to", slab.get("max", slab.get("to", slab.get("upper_limit", slab.get("upper", slab.get("max_income"))))))
            if up_to is not None:
                up_to = cls._amount_paise(up_to, paise=paise_bound)
            rate = as_decimal(slab.get("rate", slab.get("tax_rate", slab.get("percentage", 0))))
            if rate > 1:
                rate /= Decimal("100")
            normalized.append({"up_to_paise": up_to, "rate": max(Decimal("0"), rate)})
        return sorted(normalized, key=lambda x: (x["up_to_paise"] is None, x["up_to_paise"] or 0)) or default

    @classmethod
    def _declaration_paise(cls, declarations: dict[str, Any], name: str, default: int = 0) -> int:
        paise_keys = (f"{name}_paise", f"{name}_amount_paise")
        for key in paise_keys:
            if key in declarations and declarations[key] is not None:
                return max(0, cls._amount_paise(declarations[key], paise=True))
        for key in (name, f"{name}_inr", f"{name}_amount"):
            if key in declarations and declarations[key] is not None:
                return max(0, cls._amount_paise(declarations[key]))
        return default

    @classmethod
    def calculate_hra_exemption(
        cls, *, actual_hra_paise: int = 0, rent_paid_annual_paise: int = 0,
        basic_annual_paise: int = 0, metro: bool = False,
    ) -> int:
        """Section 10(13A): least of HRA, rent less 10% basic, and 50/40% basic."""
        if actual_hra_paise <= 0 or basic_annual_paise <= 0:
            return 0
        city_limit = int(Decimal(basic_annual_paise) * (Decimal("0.50") if metro else Decimal("0.40")))
        rent_excess = max(0, int(rent_paid_annual_paise) - int(Decimal(basic_annual_paise) * Decimal("0.10")))
        return max(0, min(int(actual_hra_paise), rent_excess, city_limit))

    @classmethod
    def calculate_tds(
        cls,
        annual_gross_paise: int,
        tax_regime: str = "NEW",
        declarations: Optional[dict[str, Any]] = None,
        remaining_months: int = 12,
        financial_year: str = "2024-2025",
        tax_rules: Any = None,
        tax_rule: Any = None,
        verified_declarations: Optional[dict[str, Any]] = None,
        proof_cutoff_passed: bool = False,
        use_verified_declarations: Optional[bool] = None,
        ytd_tds_paise: int = 0,
        previous_employer_tds_paise: int = 0,
        previous_employer_income_paise: int = 0,
        current_month: Optional[int] = None,
        one_time_bonus_paise: int = 0,
        variable_pay_paise: int = 0,
        bonus_paise: Optional[int] = None,
        basic_annual_paise: int = 0,
        hra_annual_paise: int = 0,
        rent_paid_annual_paise: int = 0,
        metro: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Project annual tax and deduct the unpaid balance over FY months.

        All public monetary inputs/outputs are paise.  Declaration dictionaries
        retain the legacy rupee-facing keys (``section_80c`` etc.) and also
        accept explicit ``*_paise`` keys.  A verified declaration set is used
        only after the proof cutoff (or when explicitly requested).
        """
        regime = "OLD" if str(tax_regime or "NEW").upper().strip().startswith("OLD") else "NEW"
        supplied_rule = tax_rules if tax_rules is not None else tax_rule
        rule = cls._tax_rule_dict(supplied_rule, financial_year, regime)
        # Direct keyword overrides are useful for a payroll preview and avoid
        # requiring a database rule row for every what-if calculation.
        if kwargs.get("slabs") is not None or kwargs.get("tax_slabs") is not None:
            rule["slabs"] = kwargs.get("slabs", kwargs.get("tax_slabs"))
        for key, aliases in {
            "standard_deduction_paise": ("standard_deduction_paise",),
            "rebate_87a_limit_paise": ("rebate_87a_limit_paise", "rebate_limit_paise"),
            "rebate_87a_max_paise": ("rebate_87a_max_paise", "rebate_max_paise"),
            "cess_rate": ("cess_rate",),
            "chapter_via_limits": ("chapter_via_limits", "chapter_via_limits_json"),
            "surcharge_slabs": ("surcharge_slabs", "surcharge_slabs_json"),
        }.items():
            value = next((kwargs[name] for name in aliases if name in kwargs), None)
            if value is not None:
                rule[key] = value
        if kwargs.get("standard_deduction") is not None:
            rule["standard_deduction_paise"] = cls._amount_paise(kwargs["standard_deduction"])
        declared = declarations or {}
        if use_verified_declarations is None:
            use_verified_declarations = proof_cutoff_passed and verified_declarations is not None
        if use_verified_declarations and verified_declarations is not None:
            decl = verified_declarations
        else:
            decl = declared
        if not isinstance(decl, dict):
            decl = {key: getattr(decl, key, 0) for key in ("section_80c", "section_80d", "section_80ccd1b_nps", "home_loan_interest_24b", "section_80g", "hra_claimed", "lta_claimed", "other_deductions")}
        else:
            decl = dict(decl)
        for alias, canonical in {
            "80C": "section_80c", "80D": "section_80d", "80CCD1B": "section_80ccd1b_nps",
            "80CCD(1B)": "section_80ccd1b_nps", "80G": "section_80g", "80TTA": "section_80tta",
            "24B": "home_loan_interest_24b", "24b": "home_loan_interest_24b", "HRA": "hra_claimed",
        }.items():
            if alias in decl and canonical not in decl:
                decl[canonical] = decl[alias]
        if bonus_paise is not None:
            one_time_bonus_paise = bonus_paise
        ytd_tds_paise = int(kwargs.get("already_deducted_tds_paise", ytd_tds_paise) or 0)
        previous_employer_tds_paise = int(kwargs.get("previous_tds_paise", previous_employer_tds_paise) or 0)
        if "previous_employer_income" in kwargs and not previous_employer_income_paise:
            previous_employer_income_paise = cls._amount_paise(kwargs["previous_employer_income"])
        if "ytd_tds" in kwargs and not ytd_tds_paise:
            ytd_tds_paise = cls._amount_paise(kwargs["ytd_tds"])
        base_gross = max(0, int(annual_gross_paise or 0)) + max(0, int(previous_employer_income_paise or 0))
        one_time = max(0, int(one_time_bonus_paise or 0)) + max(0, int(variable_pay_paise or 0))
        total_gross = base_gross + one_time

        standard = cls._amount_paise(rule.get("standard_deduction_paise"), paise=True)
        limits_raw = rule.get("chapter_via_limits") or {}
        limits: dict[str, Optional[int]] = {}
        for key, value in limits_raw.items():
            if value is None:
                limits[str(key).upper()] = None
            elif str(key).upper().endswith("_PAISE"):
                limits[str(key).upper()] = cls._amount_paise(value, paise=True)
            else:
                # Default rule limits are paise; custom rupee maps can use
                # ``chapter_via_limits_inr`` when needed.
                limits[str(key).upper()] = cls._amount_paise(value, paise=isinstance(value, int) and value >= 1000000)
        custom_limits_paise = kwargs.get("chapter_via_limits_paise") or cls._rule_value(supplied_rule, "chapter_via_limits_paise", default=None)
        if custom_limits_paise:
            for key, value in custom_limits_paise.items():
                limits[str(key).upper()] = cls._amount_paise(value, paise=True)
        custom_limits_inr = cls._rule_value(supplied_rule, "chapter_via_limits_inr", default=None)
        if custom_limits_inr:
            for key, value in custom_limits_inr.items():
                limits[str(key).upper()] = cls._amount_paise(value)

        def compute(gross: int) -> dict[str, int]:
            exemption = 0
            deduction = 0
            hra_exemption = 0
            sec_24b = 0
            chapter_via = 0
            professional_tax = 0
            if regime == "OLD":
                actual_hra = hra_annual_paise or cls._declaration_paise(decl, "hra_annual")
                basic_for_hra = basic_annual_paise or cls._declaration_paise(decl, "basic_annual")
                rent = rent_paid_annual_paise or cls._declaration_paise(decl, "rent_paid_annual")
                computed_hra = cls.calculate_hra_exemption(
                    actual_hra_paise=actual_hra, rent_paid_annual_paise=rent,
                    basic_annual_paise=basic_for_hra, metro=metro,
                )
                claimed_hra = cls._declaration_paise(decl, "hra_exemption", cls._declaration_paise(decl, "hra_claimed"))
                hra_exemption = computed_hra or claimed_hra
                if actual_hra:
                    hra_exemption = min(hra_exemption, actual_hra)
                exemption += hra_exemption + cls._declaration_paise(decl, "lta_claimed")
                sec_24b = cls._declaration_paise(decl, "home_loan_interest_24b", cls._declaration_paise(decl, "section_24b"))
                sec_24b_cap = limits.get("24B", 20000000)
                sec_24b = min(sec_24b, sec_24b_cap) if sec_24b_cap is not None else sec_24b
                values = {
                    "80C": cls._declaration_paise(decl, "section_80c"),
                    "80D": cls._declaration_paise(decl, "section_80d"),
                    "80CCD1B": cls._declaration_paise(decl, "section_80ccd1b_nps", cls._declaration_paise(decl, "section_80ccd1b")),
                    "80G": cls._declaration_paise(decl, "section_80g"),
                    "80TTA": cls._declaration_paise(decl, "section_80tta"),
                    "80TTB": cls._declaration_paise(decl, "section_80ttb"),
                }
                for section, value in values.items():
                    cap = limits.get(section)
                    chapter_via += min(value, cap) if cap is not None else value
                chapter_via += cls._declaration_paise(decl, "other_deductions")
                professional_tax = min(cls._declaration_paise(decl, "professional_tax"), 250000)
                deduction = chapter_via + sec_24b + professional_tax
            else:
                # New regime generally excludes Chapter VI-A/HRA/24b.  Employer
                # NPS (80CCD(2)) remains separately configurable.
                nps_employer = cls._declaration_paise(decl, "section_80ccd2")
                deduction = nps_employer
            taxable = max(0, gross - standard - exemption - deduction)
            previous = 0
            tax_before = 0
            for slab in cls._normalise_slabs(rule.get("slabs"), cls._default_tax_rule(financial_year, regime)["slabs"]):
                upper = slab["up_to_paise"]
                band_end = taxable if upper is None else min(taxable, upper)
                if band_end > previous:
                    tax_before += int((Decimal(band_end - previous) * slab["rate"]).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
                if upper is None or taxable <= upper:
                    break
                previous = upper
            rebate_limit = int(rule.get("rebate_87a_limit_paise") or 0)
            rebate_max = int(rule.get("rebate_87a_max_paise") or 0)
            rebate = min(tax_before, rebate_max) if taxable <= rebate_limit else 0
            after_rebate = max(0, tax_before - rebate)
            marginal_relief = 0
            if taxable > rebate_limit and rebate_limit > 0:
                excess = taxable - rebate_limit
                if after_rebate > excess:
                    marginal_relief = after_rebate - excess
                    after_rebate = excess
            surcharge_rate = Decimal("0")
            for item in rule.get("surcharge_slabs") or []:
                above = item.get("above_paise")
                is_paise = above is not None
                if above is None:
                    above = item.get("above", item.get("threshold", 0))
                above_paise = cls._amount_paise(above, paise=is_paise)
                if taxable > above_paise:
                    surcharge_rate = as_decimal(item.get("rate", 0))
                    if surcharge_rate > 1:
                        surcharge_rate /= Decimal("100")
            surcharge = int((Decimal(after_rebate) * surcharge_rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            cess_rate = as_decimal(rule.get("cess_rate", Decimal("0.04")))
            if cess_rate > 1:
                cess_rate /= Decimal("100")
            cess = int((Decimal(after_rebate + surcharge) * cess_rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            return {
                "standard": standard, "exemption": exemption + standard,
                "hra": hra_exemption, "sec_24b": sec_24b, "chapter_via": chapter_via,
                "professional": professional_tax, "taxable": taxable, "tax_before": tax_before, "rebate": rebate,
                "marginal_relief": marginal_relief, "after_rebate": after_rebate,
                "surcharge": surcharge, "cess": cess,
                "annual": after_rebate + surcharge + cess,
            }

        result = compute(total_gross)
        base_result = compute(base_gross) if one_time else result
        if current_month is not None:
            rem = max(1, min(12, 12 - ((int(current_month) - 4) % 12)))
        else:
            rem = max(1, min(12, int(remaining_months or 12)))
        already = max(0, ytd_tds_paise) + max(0, previous_employer_tds_paise)
        balance = max(0, result["annual"] - already)
        monthly = int((Decimal(balance) / Decimal(rem)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        recurring_balance = max(0, base_result["annual"] - already)
        recurring_monthly = int((Decimal(recurring_balance) / Decimal(rem)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        bonus_tax = max(0, result["annual"] - base_result["annual"])
        one_time_due = min(balance, bonus_tax)
        current_month_tds = recurring_monthly + one_time_due
        return {
            "tax_regime": regime, "financial_year": financial_year,
            "annual_gross_paise": total_gross, "current_employer_gross_paise": max(0, int(annual_gross_paise or 0)),
            "previous_employer_income_paise": int(previous_employer_income_paise or 0),
            "one_time_bonus_paise": int(one_time_bonus_paise or 0), "variable_pay_paise": int(variable_pay_paise or 0),
            "standard_deduction_paise": result["standard"], "total_exemptions_paise": result["exemption"],
            "hra_exemption_paise": result["hra"], "section_24b_paise": result["sec_24b"],
            "chapter_via_deduction_paise": result["chapter_via"], "professional_tax_paise": result["professional"],
            "total_deductions_paise": result["exemption"] + result["chapter_via"] + result["sec_24b"] + result["professional"],
            "taxable_income_paise": result["taxable"], "gross_tax_paise": result["tax_before"],
            "tax_before_cess_paise": result["after_rebate"] + result["surcharge"],
            "tax_after_rebate_paise": result["after_rebate"], "rebate_87a_paise": result["rebate"],
            "marginal_relief_paise": result["marginal_relief"], "surcharge_paise": result["surcharge"],
            "cess_paise": result["cess"], "annual_tax_paise": result["annual"],
            "base_annual_tax_paise": base_result["annual"], "one_time_bonus_tax_paise": bonus_tax,
            "one_time_tax_paise": bonus_tax, "ytd_tds_paise": max(0, ytd_tds_paise),
            "previous_employer_tds_paise": max(0, previous_employer_tds_paise),
            "already_deducted_tds_paise": already, "balance_tax_payable_paise": balance,
            "remaining_months": rem, "monthly_tds_paise": monthly,
            "recurring_monthly_tds_paise": recurring_monthly,
            "regular_monthly_tds_paise": recurring_monthly,
            "one_time_tds_paise": one_time_due,
            "current_month_tds_paise": current_month_tds,
            "declaration_source": "VERIFIED" if use_verified_declarations and verified_declarations is not None else "DECLARED",
            "monthly_tds": float(Decimal(monthly) / 100), "annual_tax": float(Decimal(result["annual"]) / 100),
        }


    # ─────────────────────────────────────────────────────────────────────────
    # 7. Gratuity Provision Engine
    # ─────────────────────────────────────────────────────────────────────────

    @classmethod
    def calculate_gratuity(
        cls,
        basic_monthly_paise: int,
        statutory_wage_paise: Optional[int] = None,
    ) -> dict[str, Any]:
        """Calculates Gratuity provision: (15 / 26) * monthly_basic / 12 (~4.81% of basic).

        When the Code on Wages "wages" definition is in force the caller passes
        ``statutory_wage_paise`` (basic + DA plus any excess excluded allowances
        folded back by the 50% rule) and the provision is computed on that base.
        """
        base_paise = (
            int(statutory_wage_paise) if statutory_wage_paise is not None else int(basic_monthly_paise)
        )
        base_paise = max(0, base_paise)
        provision = (
            (Decimal("15") / Decimal("26")) * Decimal(base_paise) / Decimal("12")
        ).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        provision_paise = int(provision)
        return {
            "gratuity_wage_base_paise": base_paise,
            "monthly_gratuity_provision_paise": provision_paise,
            "annual_gratuity_provision_paise": provision_paise * 12,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # 8. Complete Statutory Simulation Endpoint Helper
    # ─────────────────────────────────────────────────────────────────────────

    @classmethod
    def simulate_statutory_calculation(
        cls,
        basic_monthly_paise: int,
        hra_monthly_paise: int = 0,
        special_allowance_monthly_paise: int = 0,
        other_earnings_paise: int = 0,
        paid_days: float = 30.0,
        total_days: float = 30.0,
        state: str = "MAHARASHTRA",
        month: int = 3,
        tax_regime: str = "NEW",
        pf_on_full_basic: bool = False,
        declarations: Optional[dict[str, Any]] = None,
        config: Optional[StatutoryComplianceConfig] = None,
    ) -> dict[str, Any]:
        """Simulate end-to-end Gross-to-Net Indian Statutory Calculation."""
        day_ratio = max(0.0, min(1.0, paid_days / total_days)) if total_days > 0 else 1.0

        # Pro-rated earnings
        pro_basic = int(basic_monthly_paise * day_ratio)
        pro_hra = int(hra_monthly_paise * day_ratio)
        pro_special = int(special_allowance_monthly_paise * day_ratio)
        earned_gross_paise = pro_basic + pro_hra + pro_special + other_earnings_paise

        # 1. PF
        pf_res = cls.calculate_pf(
            basic_paise=pro_basic,
            config=config,
            pf_on_full_basic=pf_on_full_basic,
        )

        # 2. ESI
        esi_res = cls.calculate_esi(
            gross_monthly_paise=earned_gross_paise,
            config=config,
        )

        # 3. PT
        pt_res = cls.calculate_pt(
            gross_monthly_paise=earned_gross_paise,
            state=state,
            month=month,
        )

        # 4. LWF
        lwf_res = cls.calculate_lwf(
            gross_monthly_paise=earned_gross_paise,
            state=state,
            month=month,
        )

        # 5. TDS
        projected_annual_gross = earned_gross_paise * 12
        tds_res = cls.calculate_tds(
            annual_gross_paise=projected_annual_gross,
            tax_regime=tax_regime,
            declarations=declarations,
            remaining_months=12 - month + 1 if month >= 4 else 4 - month,
        )

        # 6. Gratuity
        grat_res = cls.calculate_gratuity(pro_basic)

        # Summary deductions & Net Pay
        total_employee_deductions = (
            pf_res["employee_pf_paise"]
            + esi_res["employee_esi_paise"]
            + pt_res["pt_paise"]
            + lwf_res["employee_lwf_paise"]
            + tds_res["monthly_tds_paise"]
        )

        net_pay_paise = max(0, earned_gross_paise - total_employee_deductions)

        # Employer Cost (CTC Monthly) = Earned Gross + Employer PF + Employer ESI + Employer LWF + Gratuity
        employer_cost_paise = (
            earned_gross_paise
            + pf_res["total_employer_pf_paise"]
            + pf_res["employer_edli_paise"]
            + pf_res["employer_admin_paise"]
            + esi_res["employer_esi_paise"]
            + lwf_res["employer_lwf_paise"]
            + grat_res["monthly_gratuity_provision_paise"]
        )

        return {
            "inputs": {
                "basic_monthly_paise": basic_monthly_paise,
                "hra_monthly_paise": hra_monthly_paise,
                "special_allowance_monthly_paise": special_allowance_monthly_paise,
                "paid_days": paid_days,
                "total_days": total_days,
                "day_ratio": day_ratio,
                "state": state,
                "month": month,
                "tax_regime": tax_regime,
                "pf_on_full_basic": pf_on_full_basic,
            },
            "earnings": {
                "earned_basic_paise": pro_basic,
                "earned_hra_paise": pro_hra,
                "earned_special_paise": pro_special,
                "other_earnings_paise": other_earnings_paise,
                "earned_gross_paise": earned_gross_paise,
                "earned_gross_inr": earned_gross_paise / 100.0,
            },
            "deductions": {
                "employee_pf": pf_res,
                "employee_esi": esi_res,
                "professional_tax": pt_res,
                "labour_welfare_fund": lwf_res,
                "tds": tds_res,
                "total_deductions_paise": total_employee_deductions,
                "total_deductions_inr": total_employee_deductions / 100.0,
            },
            "employer_contributions": {
                "employer_pf_paise": pf_res["total_employer_pf_paise"],
                "employer_eps_paise": pf_res["employer_eps_paise"],
                "employer_epf_paise": pf_res["employer_epf_paise"],
                "employer_edli_paise": pf_res["employer_edli_paise"],
                "employer_admin_paise": pf_res["employer_admin_paise"],
                "employer_esi_paise": esi_res["employer_esi_paise"],
                "employer_lwf_paise": lwf_res["employer_lwf_paise"],
                "gratuity_provision_paise": grat_res["monthly_gratuity_provision_paise"],
            },
            "take_home": {
                "net_pay_paise": net_pay_paise,
                "net_pay_inr": net_pay_paise / 100.0,
            },
            "employer_cost": {
                "employer_ctc_monthly_paise": employer_cost_paise,
                "employer_ctc_monthly_inr": employer_cost_paise / 100.0,
            },
        }

    # ─────────────────────────────────────────────────────────────────────────
    # 9. Period Summary & Government Filing Reports (EPFO ECR / ESIC)
    # ─────────────────────────────────────────────────────────────────────────

    @classmethod
    async def get_summary(
        cls,
        session: AsyncSession,
        period_id: uuid.UUID,
        component: Optional[str] = None,
        company_id: Optional[uuid.UUID] = None,
    ) -> dict[str, Any]:
        p_stmt = select(PayrollPeriod).where(PayrollPeriod.id == period_id)
        period = (await session.execute(p_stmt)).scalar_one_or_none()
        if not period:
            raise HTTPException(status_code=404, detail="Payroll period not found.")

        # Query payslips for this period month/year
        ps_stmt = select(Payslip).where(
            Payslip.period_month == period.period_month,
            Payslip.period_year == period.period_year,
        )
        if company_id:
            ps_stmt = ps_stmt.where(Payslip.company_id == company_id)
        payslips = (await session.execute(ps_stmt)).scalars().all()

        emp_contrib = 0
        empr_contrib = 0
        comp_name = (component or "PF").upper()

        for ps in payslips:
            if comp_name == "PF":
                emp_contrib += int(ps.employee_pf * 100)
                empr_contrib += int(ps.employer_pf * 100)
            elif comp_name == "ESI":
                emp_contrib += int(ps.employee_esi * 100)
                empr_contrib += int(ps.employer_esi * 100)
            elif comp_name == "PT":
                emp_contrib += int(ps.professional_tax * 100)
            elif comp_name == "TDS":
                emp_contrib += int(ps.tds * 100)

        total_liability = emp_contrib + empr_contrib

        return {
            "component": comp_name,
            "period_id": str(period_id),
            "total_employees": len(payslips),
            "employee_contribution_paise": emp_contrib,
            "employer_contribution_paise": empr_contrib,
            "total_liability_paise": total_liability,
            "breakup": [
                {
                    "employee_count": len(payslips),
                    "employee_total": emp_contrib / 100.0,
                    "employer_total": empr_contrib / 100.0,
                    "total": total_liability / 100.0,
                }
            ],
        }

    @classmethod
    async def generate_report_file(
        cls,
        session: AsyncSession,
        component: str,
        period_id: uuid.UUID,
        file_format: str = "csv",
    ) -> dict[str, Any]:
        p_stmt = select(PayrollPeriod).where(PayrollPeriod.id == period_id)
        period = (await session.execute(p_stmt)).scalar_one_or_none()
        if not period:
            raise HTTPException(status_code=404, detail="Payroll period not found.")

        ps_stmt = (
            select(Payslip)
            .join(Employee, Payslip.employee_id == Employee.id)
            .where(
                Payslip.period_month == period.period_month,
                Payslip.period_year == period.period_year,
            )
        )
        payslips = (await session.execute(ps_stmt)).scalars().all()

        output = io.StringIO()
        comp = component.upper()

        if file_format == "txt" and comp == "PF":
            # EPFO Electronic Challan Return (ECR) v2.0 format (#|~|# delimiter)
            ecr_res = await cls.generate_pf_ecr(session, period_id=period_id, delimiter="#|~|#", include_invalid=True, apply_admin_minimum=True)
            return {
                "component": comp,
                "period_id": str(period_id),
                "file_name": ecr_res["filename"],
                "format": file_format,
                "total_records": ecr_res["record_count"],
                "content": ecr_res["ecr_text"],
            }
        else:
            writer = csv.writer(output)
            writer.writerow(["Employee ID", "Name", "Component", "Employee Share", "Employer Share", "Total"])
            for ps in payslips:
                emp_info = (
                    await session.execute(select(Employee).where(Employee.id == ps.employee_id))
                ).scalar_one_or_none()
                name = f"{emp_info.first_name} {emp_info.last_name}".strip() if emp_info else "Employee"
                emp_code = emp_info.employee_id if emp_info else str(ps.employee_id)
                emp_s = ps.employee_pf if comp == "PF" else ps.employee_esi
                empr_s = ps.employer_pf if comp == "PF" else ps.employer_esi
                writer.writerow([emp_code, name, comp, f"{emp_s:.2f}", f"{empr_s:.2f}", f"{(emp_s + empr_s):.2f}"])

        file_name = f"Statutory_{comp}_{period.period_year}_{period.period_month:02d}.{file_format}"
        return {
            "component": comp,
            "period_id": str(period_id),
            "file_name": file_name,
            "format": file_format,
            "total_records": len(payslips),
            "content": output.getvalue(),
        }

    # ─────────────────────────────────────────────────────────────────────────
    # 7. EPFO PF ECR v2.0 Generator & Summary Engine (#|~|# separated)
    # ─────────────────────────────────────────────────────────────────────────

    @classmethod
    async def generate_pf_ecr(
        cls,
        session: AsyncSession,
        period_id: uuid.UUID,
        company_id: Optional[uuid.UUID] = None,
        delimiter: str = "#~#",
        include_invalid: bool = False,
        apply_admin_minimum: bool = False,
        strict: bool = False,
    ) -> dict[str, Any]:
        """Generate the eleven-column EPFO ECR v2 payload.

        The current Unified Portal contract uses ``#~#``.  ``delimiter`` and
        ``include_invalid`` are intentionally available only for the legacy
        endpoint, whose historical ``#|~|#`` consumers remain supported.
        Invalid UANs and inactive PF memberships are reported as validation
        errors and never silently emitted by the new download contract.
        """
        period_stmt = select(PayrollPeriod).where(PayrollPeriod.id == period_id)
        if company_id:
            period_stmt = period_stmt.where(PayrollPeriod.company_id == company_id)
        period = (await session.execute(period_stmt)).scalar_one_or_none()
        if not period:
            raise HTTPException(status_code=404, detail="Payroll period not found.")
        config = await cls.get_config(session, company_id=company_id or period.company_id)
        ps_stmt = select(Payslip, Employee).join(Employee, Payslip.employee_id == Employee.id).where(
            Payslip.period_month == period.period_month,
            Payslip.period_year == period.period_year,
        )
        if company_id:
            ps_stmt = ps_stmt.where(Payslip.company_id == company_id, Employee.company_id == company_id)
        rows = (await session.execute(ps_stmt)).all()
        records: list[dict[str, Any]] = []
        raw_lines: list[str] = []
        validation_errors: list[dict[str, Any]] = []
        totals = {key: 0 for key in ("gross", "epf_wages", "eps_wages", "edli_wages", "ee", "eps", "er_diff", "edli", "admin_wages")}
        missing_uan_count = 0

        for ps, emp in rows:
            uan = (getattr(emp, "uan_number", None) or "").strip()
            uan_valid, uan_error = Employee.validate_uan_format(uan)
            active = bool(getattr(emp, "is_active", True)) and not bool(getattr(emp, "is_deleted", False))
            member_active = bool(getattr(emp, "pf_membership_active", True))
            eligible = bool(getattr(emp, "is_pf_eligible", True))
            if not uan_valid:
                missing_uan_count += 1
            if not uan_valid or not active or not member_active or not eligible:
                error = {
                    "employee_id": str(emp.id), "employee_code": emp.employee_id,
                    "uan_number": uan or None, "uan_valid": uan_valid,
                    "active_membership": bool(active and member_active and eligible),
                    "reason": uan_error if not uan_valid else "Employee is not an active PF member",
                }
                validation_errors.append(error)
                if not include_invalid:
                    continue

            age = None
            if emp.date_of_birth:
                on_date = period.end_date or date(period.period_year, period.period_month, 1)
                age = on_date.year - emp.date_of_birth.year - ((on_date.month, on_date.day) < (emp.date_of_birth.month, emp.date_of_birth.day))
            pf = cls.calculate_pf(
                basic_paise=int(as_decimal(ps.basic or 0) * 100), da_paise=0, config=config,
                is_pf_eligible=eligible and active and member_active,
                is_international_worker=bool(getattr(emp, "is_international_worker", False)),
                pf_wage_ceiling_applicable=bool(getattr(emp, "pf_wage_ceiling_applicable", True)),
                pf_higher_wage_opted=bool(getattr(emp, "pf_higher_wage_opted", False)),
                pf_membership_active=member_active,
                vpf_rate=getattr(emp, "vpf_rate", Decimal("0")), age=age,
            )
            gross_paise = int(as_decimal(ps.gross_earnings or 0) * 100)
            if not uan_valid or not active or not member_active or not eligible:
                # Legacy compatibility: retain a visibly invalid row, but never
                # invent a contribution for an inactive/invalid member.
                pf = {key: 0 for key in ("pf_wage_paise", "eps_wage_paise", "edli_wage_paise", "employee_pf_paise", "employer_eps_paise", "employer_epf_paise", "employer_edli_paise", "employer_admin_paise")}
            name = re.sub(r"[^A-Za-z0-9 ]", "", f"{emp.first_name} {emp.last_name}".strip()).strip().upper()[:80] or "MEMBER"
            ncp_days = int(as_decimal(ps.lop_days or 0))
            values = [
                uan if uan_valid else (uan or "000000000000"), name,
                str(round_to_rupee_paise(gross_paise) // 100),
                str(round_to_rupee_paise(pf.get("pf_wage_paise", 0)) // 100),
                str(round_to_rupee_paise(pf.get("eps_wage_paise", 0)) // 100),
                str(round_to_rupee_paise(pf.get("edli_wage_paise", 0)) // 100),
                str(round_to_rupee_paise(pf.get("employee_pf_paise", 0)) // 100),
                str(round_to_rupee_paise(pf.get("employer_eps_paise", 0)) // 100),
                str(round_to_rupee_paise(pf.get("employer_epf_paise", 0)) // 100),
                str(ncp_days), "0",
            ]
            raw_lines.append(delimiter.join(values))
            record = {
                "employee_id": str(emp.id), "uan": values[0], "member_name": name,
                "gross_wages": float(Decimal(values[2])), "epf_wages": float(Decimal(values[3])),
                "eps_wages": float(Decimal(values[4])), "edli_wages": float(Decimal(values[5])),
                "ee_remitted": float(Decimal(values[6])), "eps_remitted": float(Decimal(values[7])),
                "er_diff_remitted": float(Decimal(values[8])), "ncp_days": ncp_days, "refund_advances": 0.0,
                "employee_vpf_paise": pf.get("employee_vpf_paise", 0),
            }
            records.append(record)
            totals["gross"] += gross_paise
            totals["epf_wages"] += pf.get("pf_wage_paise", 0)
            totals["eps_wages"] += pf.get("eps_wage_paise", 0)
            totals["edli_wages"] += pf.get("edli_wage_paise", 0)
            totals["ee"] += pf.get("employee_pf_paise", 0)
            totals["eps"] += pf.get("employer_eps_paise", 0)
            totals["er_diff"] += pf.get("employer_epf_paise", 0)
            totals["edli"] += pf.get("employer_edli_paise", 0)
            totals["admin_wages"] += pf.get("pf_wage_paise", 0)

        admin_rate = as_decimal(getattr(config, "pf_admin_rate", Decimal("0.005")))
        admin_paise = round_to_rupee_paise(Decimal(totals["admin_wages"]) * admin_rate) if totals["admin_wages"] else 0
        if apply_admin_minimum and admin_paise:
            admin_paise = max(50000, admin_paise)
        total_liability_paise = totals["ee"] + totals["eps"] + totals["er_diff"] + totals["edli"] + admin_paise
        ecr_text = "\r\n".join(raw_lines) + ("\r\n" if raw_lines else "")
        filename = f"EPFO_ECR_{period.period_year}_{period.period_month:02d}.txt"
        if strict and validation_errors:
            raise HTTPException(status_code=422, detail={"message": "ECR validation failed", "errors": validation_errors})

        challan_stmt = select(ComplianceChallan).where(
            ComplianceChallan.period_id == period_id, ComplianceChallan.challan_type == "EPFO_ECR",
        )
        if company_id:
            challan_stmt = challan_stmt.where(ComplianceChallan.company_id == company_id)
        challan = (await session.execute(challan_stmt)).scalar_one_or_none()
        rupee = lambda value: (Decimal(value) / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if not challan:
            challan = ComplianceChallan(
                id=uuid.uuid4(), company_id=company_id or period.company_id, period_id=period_id,
                challan_type="EPFO_ECR", period_month=period.period_month, period_year=period.period_year,
            )
            session.add(challan)
        challan.total_amount = rupee(total_liability_paise)
        challan.employee_count = len(records)
        challan.epf_employee_amount = rupee(totals["ee"])
        challan.epf_employer_amount = rupee(totals["er_diff"])
        challan.eps_amount = rupee(totals["eps"])
        challan.edli_amount = rupee(totals["edli"])
        challan.admin_charges = rupee(admin_paise)
        challan.file_payload = ecr_text
        if challan.status in ("GENERATED", "PENDING"):
            challan.status = "ECR_GENERATED"

        due_month = period.period_month + 1 if period.period_month < 12 else 1
        due_year = period.period_year if period.period_month < 12 else period.period_year + 1
        due_stmt = select(ComplianceDueDate).where(
            ComplianceDueDate.period_id == period_id,
            ComplianceDueDate.period_month == period.period_month,
            ComplianceDueDate.period_year == period.period_year,
        )
        if company_id:
            due_stmt = due_stmt.where(ComplianceDueDate.company_id == company_id)
        due_rec = (await session.execute(due_stmt)).scalar_one_or_none()
        if not due_rec:
            due_rec = ComplianceDueDate(
                id=uuid.uuid4(), company_id=company_id or period.company_id, challan_id=challan.id,
                period_id=period_id, title=f"EPFO PF & ECR Filing - {period.period_month:02d}/{period.period_year}",
                due_date=date(due_year, due_month, 15), period=f"{period.period_month:02d}/{period.period_year}",
                period_month=period.period_month, period_year=period.period_year, status="ECR_GENERATED",
            )
            session.add(due_rec)
        else:
            due_rec.challan_id = challan.id
            if due_rec.status in ("PENDING", "GENERATED"):
                due_rec.status = "ECR_GENERATED"
        await session.commit()

        def old_rupee(value: int) -> float:
            return float(rupee(value))
        return {
            "period_id": str(period_id), "period_month": period.period_month, "period_year": period.period_year,
            "wage_month": f"{period.period_month:02d}/{period.period_year}", "filename": filename,
            "file_name": filename, "delimiter": delimiter, "record_count": len(records),
            "total_gross": old_rupee(totals["gross"]), "total_epf_wages": old_rupee(totals["epf_wages"]),
            "total_eps_wages": old_rupee(totals["eps_wages"]), "total_ee_share": old_rupee(totals["ee"]),
            "total_eps_share": old_rupee(totals["eps"]), "total_er_diff_share": old_rupee(totals["er_diff"]),
            "total_edli_share": old_rupee(totals["edli"]), "admin_charges": old_rupee(admin_paise),
            "total_pf_liability": old_rupee(total_liability_paise),
            "total_gross_paise": totals["gross"], "total_epf_wages_paise": totals["epf_wages"],
            "total_ee_share_paise": totals["ee"], "total_eps_share_paise": totals["eps"],
            "total_er_diff_share_paise": totals["er_diff"], "total_edli_share_paise": totals["edli"],
            "admin_charges_paise": admin_paise, "total_pf_liability_paise": total_liability_paise,
            "records": records, "ecr_text": ecr_text, "content": ecr_text,
            "has_missing_uan": missing_uan_count > 0, "missing_uan_count": missing_uan_count,
            "validation_errors": validation_errors, "is_valid": not validation_errors,
        }

    @classmethod
    async def get_pf_summary(
        cls,
        session: AsyncSession,
        period_id: uuid.UUID,
        company_id: Optional[uuid.UUID] = None,
    ) -> dict[str, Any]:
        """Detailed PF liability breakup and contribution analysis for period."""
        return await cls.generate_pf_ecr(session, period_id=period_id, company_id=company_id)

    # ─────────────────────────────────────────────────────────────────────────
    # 8. Monthly Statutory Filing Calendar & Challan Management
    # ─────────────────────────────────────────────────────────────────────────

    @classmethod
    async def get_filing_calendar(
        cls,
        session: AsyncSession,
        company_id: Optional[uuid.UUID] = None,
        year: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """12-month Statutory PF Filing Calendar tracking the 15th due date of each month.
        
        Calculates real-time statutory status badges:
        - PENDING: Future due date, pending ECR generation
        - ECR_GENERATED: ECR file generated, pending payment/challan
        - CHALLAN_UPLOADED: TRRN recorded or challan receipt uploaded
        - FILED_ON_TIME: Payment confirmed on or before the 15th
        - OVERDUE: Past the 15th without payment confirmation
        
        If OVERDUE: Computes EPFO Section 7Q (12% p.a.) simple interest and Section 14B damages.
        """
        curr_year = year or date.today().year
        today = date.today()
        month_names = [
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December",
        ]

        calendar_items: list[dict[str, Any]] = []

        for m in range(1, 13):
            # PF Due Date: 15th of following month
            due_m = m + 1 if m < 12 else 1
            due_y = curr_year if m < 12 else curr_year + 1
            due_date = date(due_y, due_m, 15)

            # Look up Challan for this month
            ch_stmt = select(ComplianceChallan).where(
                ComplianceChallan.period_month == m,
                ComplianceChallan.period_year == curr_year,
                ComplianceChallan.challan_type == "EPFO_ECR",
            )
            if company_id:
                ch_stmt = ch_stmt.where(
                    or_(ComplianceChallan.company_id == company_id, ComplianceChallan.company_id.is_(None))
                )
            challan = (await session.execute(ch_stmt)).scalar_one_or_none()

            # Determine status
            total_amt = float(challan.total_amount) if challan else 0.0
            emp_cnt = challan.employee_count if challan else 0
            trrn = challan.trrn_number if challan else None
            pay_date_val = challan.payment_date if challan else None
            utr = challan.utr_number if challan else None
            challan_url = challan.challan_file_url if challan else None
            receipt_url = challan.payment_receipt_url if challan else None

            is_overdue = False
            overdue_days = 0
            interest_7q = 0.0
            damages_14b = 0.0
            damages_rate = 0.0

            if pay_date_val:
                if pay_date_val <= due_date:
                    item_status = "FILED_ON_TIME"
                else:
                    item_status = "FILED_LATE"
            elif today > due_date:
                item_status = "OVERDUE"
                is_overdue = True
                overdue_days = (today - due_date).days
                
                # Default benchmark liability if zero
                calc_amt = total_amt if total_amt > 0 else 45000.0
                # Section 7Q: 12% p.a. simple interest
                interest_7q = round(calc_amt * 0.12 * (overdue_days / 365.0), 2)

                # Section 14B Penal Damages:
                # 1 to 60 days: 5% p.a.
                # 61 to 120 days: 10% p.a.
                # 121 to 180 days: 15% p.a.
                # > 180 days: 25% p.a.
                if overdue_days <= 60:
                    damages_rate = 5.0
                elif overdue_days <= 120:
                    damages_rate = 10.0
                elif overdue_days <= 180:
                    damages_rate = 15.0
                else:
                    damages_rate = 25.0

                damages_14b = round(calc_amt * (damages_rate / 100.0) * (overdue_days / 365.0), 2)
            elif challan and (challan_url or receipt_url or trrn):
                item_status = "CHALLAN_UPLOADED"
            elif challan and challan.file_payload:
                item_status = "ECR_GENERATED"
            else:
                item_status = "PENDING"

            calendar_items.append({
                "id": str(challan.id) if challan else f"cal-{curr_year}-{m:02d}",
                "month": m,
                "year": curr_year,
                "wage_month_label": f"{month_names[m - 1]} {curr_year}",
                "due_date": due_date.isoformat(),
                "status": item_status,
                "trrn_number": trrn,
                "payment_date": pay_date_val.isoformat() if pay_date_val else None,
                "utr_number": utr,
                "total_amount": total_amt,
                "employee_count": emp_cnt,
                "is_overdue": is_overdue,
                "overdue_days": overdue_days,
                "interest_7q_amount": interest_7q,
                "damages_14b_amount": damages_14b,
                "damages_14b_rate_pct": damages_rate,
                "challan_file_url": challan_url,
                "payment_receipt_url": receipt_url,
            })

        return calendar_items

    @classmethod
    async def record_challan(
        cls,
        session: AsyncSession,
        company_id: Optional[uuid.UUID],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Record TRRN number, payment details, and bank references for EPFO PF remittance."""
        period_id_str = payload.get("period_id") or payload.get("periodId")
        if not period_id_str:
            raise HTTPException(status_code=400, detail="period_id is required.")
        p_uuid = uuid.UUID(str(period_id_str))

        p_stmt = select(PayrollPeriod).where(PayrollPeriod.id == p_uuid)
        if company_id:
            p_stmt = p_stmt.where(PayrollPeriod.company_id == company_id)
        period = (await session.execute(p_stmt)).scalar_one_or_none()
        if not period:
            raise HTTPException(status_code=404, detail="Payroll period not found.")

        trrn = payload.get("trrn_number") or payload.get("trrnNumber")
        if not trrn:
            raise HTTPException(status_code=400, detail="trrn_number is required.")

        ch_stmt = select(ComplianceChallan).where(
            ComplianceChallan.period_id == p_uuid,
            ComplianceChallan.challan_type == "EPFO_ECR",
        )
        if company_id:
            ch_stmt = ch_stmt.where(ComplianceChallan.company_id == company_id)
        challan = (await session.execute(ch_stmt)).scalar_one_or_none()

        gen_date_raw = payload.get("challan_generation_date") or payload.get("challanGenerationDate")
        pay_date_raw = payload.get("payment_date") or payload.get("paymentDate")

        gen_date = date.fromisoformat(gen_date_raw) if gen_date_raw else None
        pay_date = date.fromisoformat(pay_date_raw) if pay_date_raw else None

        utr = payload.get("utr_number") or payload.get("utrNumber")
        crn = payload.get("crn_number") or payload.get("crnNumber") or payload.get("crn")
        bank_reference = payload.get("bank_reference") or payload.get("bankReference") or payload.get("bank_ref")
        bsr_code = payload.get("bsr_code") or payload.get("bsrCode")
        challan_serial = payload.get("challan_serial_number") or payload.get("challanSerialNumber")
        total_amt = payload.get("total_amount") or payload.get("totalAmount")

        due_m = period.period_month + 1 if period.period_month < 12 else 1
        due_y = period.period_year if period.period_month < 12 else period.period_year + 1
        due_date = date(due_y, due_m, 15)

        challan_status = "CHALLAN_UPLOADED"
        if pay_date:
            challan_status = "FILED_ON_TIME" if pay_date <= due_date else "FILED_LATE"

        if not challan:
            challan = ComplianceChallan(
                id=uuid.uuid4(),
                company_id=company_id or getattr(period, "company_id", None),
                period_id=p_uuid,
                challan_type="EPFO_ECR",
                period_month=period.period_month,
                period_year=period.period_year,
                trrn_number=str(trrn).strip(),
                crn_number=str(crn).strip() if crn else None,
                bank_reference=str(bank_reference).strip() if bank_reference else None,
                bsr_code=str(bsr_code).strip() if bsr_code else None,
                challan_serial_number=str(challan_serial).strip() if challan_serial else None,
                challan_generation_date=gen_date,
                payment_date=pay_date,
                utr_number=utr,
                total_amount=Decimal(str(total_amt or 0)),
                status=challan_status,
            )
            session.add(challan)
        else:
            challan.trrn_number = str(trrn).strip()
            if crn is not None:
                challan.crn_number = str(crn).strip()
            if bank_reference is not None:
                challan.bank_reference = str(bank_reference).strip()
            if bsr_code is not None:
                challan.bsr_code = str(bsr_code).strip()
            if challan_serial is not None:
                challan.challan_serial_number = str(challan_serial).strip()
            if gen_date:
                challan.challan_generation_date = gen_date
            if pay_date:
                challan.payment_date = pay_date
            if utr:
                challan.utr_number = utr
            if total_amt:
                challan.total_amount = Decimal(str(total_amt))
            challan.status = challan_status

        # Also update ComplianceDueDate
        due_stmt = select(ComplianceDueDate).where(
            ComplianceDueDate.period_id == p_uuid,
            ComplianceDueDate.period_month == period.period_month,
            ComplianceDueDate.period_year == period.period_year,
        )
        due_rec = (await session.execute(due_stmt)).scalar_one_or_none()
        if due_rec:
            due_rec.trrn_number = str(trrn).strip()
            due_rec.status = challan_status
            if pay_date:
                due_rec.payment_date = pay_date
            if utr:
                due_rec.utr_number = utr

        await session.commit()
        await session.refresh(challan)

        return {
            "id": str(challan.id),
            "period_id": str(challan.period_id),
            "trrn_number": challan.trrn_number,
            "crn_number": challan.crn_number,
            "bank_reference": challan.bank_reference,
            "bsr_code": challan.bsr_code,
            "challan_serial_number": challan.challan_serial_number,
            "status": challan.status,
            "challan_generation_date": challan.challan_generation_date.isoformat() if challan.challan_generation_date else None,
            "payment_date": challan.payment_date.isoformat() if challan.payment_date else None,
            "utr_number": challan.utr_number,
            "total_amount": float(challan.total_amount),
        }

    @classmethod
    async def upload_challan_file(
        cls,
        session: AsyncSession,
        company_id: Optional[uuid.UUID],
        period_id: uuid.UUID,
        file: UploadFile,
        file_type: str = "CHALLAN",
    ) -> dict[str, Any]:
        """Upload Challan PDF or Payment Confirmation PDF receipt via StorageService."""
        p_stmt = select(PayrollPeriod).where(PayrollPeriod.id == period_id)
        if company_id:
            p_stmt = p_stmt.where(PayrollPeriod.company_id == company_id)
        period = (await session.execute(p_stmt)).scalar_one_or_none()
        if not period:
            raise HTTPException(status_code=404, detail="Payroll period not found.")

        storage = StorageService()
        saved = await storage.save_file(file)

        ch_stmt = select(ComplianceChallan).where(
            ComplianceChallan.period_id == period_id,
            ComplianceChallan.challan_type == "EPFO_ECR",
        )
        if company_id:
            ch_stmt = ch_stmt.where(ComplianceChallan.company_id == company_id)
        challan = (await session.execute(ch_stmt)).scalar_one_or_none()

        rel_url = f"/uploads/documents/{saved['stored_filename']}"
        f_type_upper = file_type.upper().strip()

        if not challan:
            challan = ComplianceChallan(
                id=uuid.uuid4(),
                company_id=company_id or getattr(period, "company_id", None),
                period_id=period_id,
                challan_type="EPFO_ECR",
                period_month=period.period_month,
                period_year=period.period_year,
                status="CHALLAN_UPLOADED",
            )
            session.add(challan)

        if f_type_upper == "CHALLAN":
            challan.challan_file_path = saved["file_path"]
            challan.challan_file_url = rel_url
            if challan.status in ("GENERATED", "ECR_GENERATED", "PENDING"):
                challan.status = "CHALLAN_UPLOADED"
        else:  # RECEIPT
            challan.payment_receipt_path = saved["file_path"]
            challan.payment_receipt_url = rel_url
            if challan.payment_date:
                due_m = period.period_month + 1 if period.period_month < 12 else 1
                due_y = period.period_year if period.period_month < 12 else period.period_year + 1
                due_date = date(due_y, due_m, 15)
                challan.status = "FILED_ON_TIME" if challan.payment_date <= due_date else "FILED_LATE"
            else:
                challan.status = "CHALLAN_UPLOADED"

        await session.commit()
        await session.refresh(challan)

        return {
            "challan_id": str(challan.id),
            "period_id": str(period_id),
            "file_type": f_type_upper,
            "original_filename": saved["original_filename"],
            "stored_filename": saved["stored_filename"],
            "file_url": rel_url,
            "status": challan.status,
        }

    @classmethod
    async def _period_rows(
        cls, session: AsyncSession, period_id: uuid.UUID, company_id: Optional[uuid.UUID] = None,
    ) -> tuple[PayrollPeriod, list[Any]]:
        stmt = select(PayrollPeriod).where(PayrollPeriod.id == period_id)
        if company_id:
            stmt = stmt.where(PayrollPeriod.company_id == company_id)
        period = (await session.execute(stmt)).scalar_one_or_none()
        if not period:
            raise HTTPException(status_code=404, detail="Payroll period not found.")
        rows_stmt = select(Payslip, Employee).join(Employee, Payslip.employee_id == Employee.id).where(
            Payslip.period_month == period.period_month, Payslip.period_year == period.period_year,
        )
        if company_id:
            rows_stmt = rows_stmt.where(Payslip.company_id == company_id, Employee.company_id == company_id)
        return period, (await session.execute(rows_stmt)).all()

    @staticmethod
    def _employee_state(employee: Employee, config: Any = None) -> str:
        return (
            getattr(employee, "state_code", None)
            or getattr(employee, "branch_state", None)
            or getattr(employee, "branch", None)
            or getattr(employee, "work_location", None)
            or getattr(config, "pt_state", None)
            or "MAHARASHTRA"
        )

    @classmethod
    async def get_esi_coverage_at_period_start(
        cls, session: AsyncSession, employee: Employee, period: PayrollPeriod,
        config: Optional[StatutoryComplianceConfig] = None,
        company_id: Optional[uuid.UUID] = None,
    ) -> dict[str, Any]:
        """Infer contribution-period coverage from its earliest payslip.

        This is what preserves ESI when wages cross the ceiling after April or
        October.  An explicit employee coverage flag takes precedence for
        migrated employees whose earlier payroll lives in another system.
        """
        on_date = period.start_date or date(period.period_year, period.period_month, 1)
        start, end = cls.esi_contribution_period(on_date)
        pairs = []
        cursor = date(start.year, start.month, 1)
        while cursor <= end:
            pairs.append((cursor.month, cursor.year))
            cursor = date(cursor.year + (1 if cursor.month == 12 else 0), 1 if cursor.month == 12 else cursor.month + 1, 1)
        stmt = select(Payslip).where(
            Payslip.employee_id == employee.id,
            or_(*[and_(Payslip.period_month == month, Payslip.period_year == year) for month, year in pairs]),
        ).order_by(Payslip.period_year, Payslip.period_month)
        if company_id:
            stmt = stmt.where(Payslip.company_id == company_id)
        first = (await session.execute(stmt.limit(1))).scalar_one_or_none()
        is_pwd = bool(getattr(employee, "is_pwd", False))
        ceiling = int(as_decimal(getattr(config, "esi_pwd_wage_ceiling", 25000) if is_pwd else getattr(config, "esi_wage_ceiling", 21000)) * 100)
        explicit = bool(getattr(employee, "esi_covered_at_period_start", False))
        first_gross = int(as_decimal(first.gross_earnings or 0) * 100) if first else None
        covered = explicit or (first_gross is not None and first_gross <= ceiling)
        return {
            "covered": covered, "explicitly_covered": explicit,
            "first_gross_paise": first_gross, "ceiling_paise": ceiling,
            "contribution_period_start": start, "contribution_period_end": end,
            "source": "EMPLOYEE_FLAG" if explicit else ("FIRST_PAYSLIP" if first else "CURRENT_MONTH"),
        }


    @classmethod
    async def generate_esi_return(
        cls, session: AsyncSession, period_id: uuid.UUID,
        company_id: Optional[uuid.UUID] = None, file_format: str = "csv",
    ) -> dict[str, Any]:
        """Generate the monthly ESIC contribution return and its paise totals."""
        period, rows = await cls._period_rows(session, period_id, company_id)
        config = await cls.get_config(session, company_id=company_id or period.company_id)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["IP Number", "Employee Code", "Employee Name", "Gross Wages", "Employee ESI", "Employer ESI", "Total ESI", "Contribution Period", "Reason"])
        items = []
        totals = {"gross": 0, "employee": 0, "employer": 0}
        for ps, emp in rows:
            gross_paise = int(as_decimal(ps.gross_earnings or 0) * 100)
            coverage = await cls.get_esi_coverage_at_period_start(
                session, emp, period, config, company_id or period.company_id,
            )
            result = cls.calculate_esi(
                gross_monthly_paise=gross_paise, config=config,
                is_pwd=bool(getattr(emp, "is_pwd", False)),
                covered_at_period_start=coverage["covered"] or gross_paise <= coverage["ceiling_paise"],
                contribution_period_start=coverage["contribution_period_start"],
                as_of_date=period.start_date or date(period.period_year, period.period_month, 1),
            )
            name = f"{emp.first_name} {emp.last_name}".strip()
            employee = result["employee_esi_paise"]
            employer = result["employer_esi_paise"]
            totals["gross"] += gross_paise
            totals["employee"] += employee
            totals["employer"] += employer
            item = {
                "employee_id": str(emp.id), "ip_number": getattr(emp, "esic_number", None) or getattr(emp, "esi_number", None),
                "employee_code": emp.employee_id, "employee_name": name,
                "gross_wages_paise": gross_paise, "employee_esi_paise": employee,
                "employer_esi_paise": employer, "total_esi_paise": employee + employer,
                "is_applicable": result["is_applicable"], "contribution_period_lock": result["contribution_period_lock"],
                "reason": result["reason"],
            }
            items.append(item)
            writer.writerow([item["ip_number"] or "", emp.employee_id, name, f"{Decimal(gross_paise) / 100:.2f}", f"{Decimal(employee) / 100:.2f}", f"{Decimal(employer) / 100:.2f}", f"{Decimal(employee + employer) / 100:.2f}", result["contribution_period_start"], result["reason"]])
        csv_text = output.getvalue()
        content = json.dumps({"period_id": str(period_id), "items": items, "employee_esi_paise": totals["employee"], "employer_esi_paise": totals["employer"], "total_esi_paise": totals["employee"] + totals["employer"]}, default=str) if file_format.lower() == "json" else csv_text
        return {
            "period_id": str(period_id), "period_month": period.period_month, "period_year": period.period_year,
            "filename": f"ESIC_Return_{period.period_year}_{period.period_month:02d}.{file_format}",
            "file_name": f"ESIC_Return_{period.period_year}_{period.period_month:02d}.{file_format}",
            "format": file_format, "record_count": len(items), "items": items, "rows": items,
            "employee_esi_paise": totals["employee"], "employer_esi_paise": totals["employer"],
            "total_esi_paise": totals["employee"] + totals["employer"], "gross_wages_paise": totals["gross"],
            "content": content, "csv_text": csv_text,
        }

    @classmethod
    async def generate_esi_challan(
        cls, session: AsyncSession, period_id: uuid.UUID,
        company_id: Optional[uuid.UUID] = None,
    ) -> dict[str, Any]:
        """Create/update the monthly ESIC challan from the contribution return."""
        result = await cls.generate_esi_return(session, period_id, company_id, "csv")
        period_stmt = select(PayrollPeriod).where(PayrollPeriod.id == period_id)
        if company_id:
            period_stmt = period_stmt.where(PayrollPeriod.company_id == company_id)
        period = (await session.execute(period_stmt)).scalar_one_or_none()
        if not period:
            raise HTTPException(status_code=404, detail="Payroll period not found.")
        total_paise = int(result["total_esi_paise"])
        total_rupees = (Decimal(total_paise) / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        stmt = select(ComplianceChallan).where(
            ComplianceChallan.period_id == period_id,
            ComplianceChallan.challan_type == "ESIC_CHALLAN",
        )
        if company_id:
            stmt = stmt.where(ComplianceChallan.company_id == company_id)
        challan = (await session.execute(stmt)).scalar_one_or_none()
        if not challan:
            challan = ComplianceChallan(
                id=uuid.uuid4(), company_id=company_id or period.company_id, period_id=period_id,
                challan_type="ESIC_CHALLAN", period_month=period.period_month, period_year=period.period_year,
            )
            session.add(challan)
        challan.total_amount = total_rupees
        challan.employee_count = sum(1 for item in result["items"] if item["is_applicable"])
        challan.file_payload = result["csv_text"]
        challan.challan_generation_date = challan.challan_generation_date or date.today()
        if challan.status in ("PENDING", "GENERATED"):
            challan.status = "GENERATED"
        due_month = period.period_month + 1 if period.period_month < 12 else 1
        due_year = period.period_year if period.period_month < 12 else period.period_year + 1
        due_stmt = select(ComplianceDueDate).where(
            ComplianceDueDate.period_id == period_id,
            ComplianceDueDate.period_month == period.period_month,
            ComplianceDueDate.period_year == period.period_year,
        )
        if company_id:
            due_stmt = due_stmt.where(ComplianceDueDate.company_id == company_id)
        due = (await session.execute(due_stmt)).scalar_one_or_none()
        if not due:
            due = ComplianceDueDate(
                id=uuid.uuid4(), company_id=company_id or period.company_id, challan_id=challan.id,
                period_id=period_id, title=f"ESIC Contribution - {period.period_month:02d}/{period.period_year}",
                due_date=date(due_year, due_month, 15), period=f"{period.period_month:02d}/{period.period_year}",
                period_month=period.period_month, period_year=period.period_year, status="GENERATED",
            )
            session.add(due)
        else:
            due.challan_id = challan.id
        await session.commit()
        await session.refresh(challan)
        return {
            **result, "challan_id": str(challan.id), "challan_type": challan.challan_type,
            "challan_status": challan.status, "total_amount_paise": total_paise,
            "total_amount": float(total_rupees), "employee_count": challan.employee_count,
            "challan_generation_date": challan.challan_generation_date.isoformat() if challan.challan_generation_date else None,
        }

    @classmethod
    async def get_lwf_summary(
        cls, session: AsyncSession, period_id: uuid.UUID,
        company_id: Optional[uuid.UUID] = None,
    ) -> dict[str, Any]:
        """Return employee/employer LWF liabilities grouped by branch state."""
        period, rows = await cls._period_rows(session, period_id, company_id)
        config = await cls.get_config(session, company_id=company_id or period.company_id)
        items = []
        grouped: dict[str, dict[str, Any]] = {}
        for ps, emp in rows:
            state = cls._employee_state(emp, config)
            rule = await cls.get_state_statutory_rule(session, state, company_id or period.company_id, period.start_date)
            result = cls.calculate_lwf(int(as_decimal(ps.gross_earnings or 0) * 100), state, period.period_month, rule=rule)
            item = {
                "employee_id": str(emp.id), "employee_code": emp.employee_id,
                "employee_name": f"{emp.first_name} {emp.last_name}".strip(),
                "state_code": result["state_code"], "month": period.period_month, **result,
            }
            items.append(item)
            group = grouped.setdefault(result["state_code"], {"state_code": result["state_code"], "employee_count": 0, "employee_lwf_paise": 0, "employer_lwf_paise": 0, "total_lwf_paise": 0, "frequency": result["frequency"], "applicable_months": result["applicable_months"]})
            group["employee_count"] += 1
            group["employee_lwf_paise"] += result["employee_lwf_paise"]
            group["employer_lwf_paise"] += result["employer_lwf_paise"]
            group["total_lwf_paise"] += result["employee_lwf_paise"] + result["employer_lwf_paise"]
        employee_total = sum(i["employee_lwf_paise"] for i in items)
        employer_total = sum(i["employer_lwf_paise"] for i in items)
        return {
            "period_id": str(period_id), "period_month": period.period_month, "period_year": period.period_year,
            "items": items, "rows": items, "states": list(grouped.values()),
            "employee_lwf_paise": employee_total, "employer_lwf_paise": employer_total,
            "total_lwf_paise": employee_total + employer_total,
            "total_employee_lwf_paise": employee_total, "total_employer_lwf_paise": employer_total,
        }

    @staticmethod
    def _fy_and_quarter(period: PayrollPeriod, quarter: Optional[int] = None) -> tuple[str, int, list[tuple[int, int]]]:
        start_year = period.period_year if period.period_month >= 4 else period.period_year - 1
        q = quarter or ((period.period_month - 4) // 3 + 1 if period.period_month >= 4 else (period.period_month + 8) // 3 + 1)
        q = max(1, min(4, int(q)))
        qmonths = {1: [4, 5, 6], 2: [7, 8, 9], 3: [10, 11, 12], 4: [1, 2, 3]}[q]
        pairs = [(m, start_year if m >= 4 else start_year + 1) for m in qmonths]
        return f"{start_year}-{start_year + 1}", q, pairs

    @staticmethod
    def _json_safe(value: Any) -> Any:
        if isinstance(value, dict):
            return {str(k): StatutoryService._json_safe(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [StatutoryService._json_safe(v) for v in value]
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, uuid.UUID):
            return str(value)
        return value

    @classmethod
    async def generate_form138_draft(
        cls, session: AsyncSession, period_id: uuid.UUID,
        company_id: Optional[uuid.UUID] = None, quarter: Optional[int] = None,
        financial_year: Optional[str] = None, challan_details: Optional[dict[str, Any]] = None,
        generated_by: Optional[uuid.UUID] = None,
    ) -> dict[str, Any]:
        """Build a quarterly Form 138 draft with challan and employee validations."""
        period, _ = await cls._period_rows(session, period_id, company_id)
        fy, q, pairs = cls._fy_and_quarter(period, quarter)
        fy = financial_year or fy
        # Include the year pair explicitly to avoid pulling the same month from
        # another financial year into a quarterly statement.
        year_conditions = [and_(Payslip.period_month == m, Payslip.period_year == y) for m, y in pairs]
        stmt = select(Payslip, Employee).join(Employee, Payslip.employee_id == Employee.id).where(or_(*year_conditions))
        if company_id:
            stmt = stmt.where(Payslip.company_id == company_id, Employee.company_id == company_id)
        rows = (await session.execute(stmt)).all()
        details = dict(challan_details or {})
        ch_stmt = select(ComplianceChallan).where(ComplianceChallan.challan_type.in_(["TDS", "TDS_CHALLAN", "FORM_138"]))
        if company_id:
            ch_stmt = ch_stmt.where(ComplianceChallan.company_id == company_id)
        challans = (await session.execute(ch_stmt)).scalars().all()
        for ch in challans:
            if (ch.period_month, ch.period_year) in pairs:
                for key in ("bsr_code", "challan_serial_number", "payment_date", "challan_generation_date", "total_amount", "bank_reference", "trrn_number", "crn_number"):
                    if details.get(key) in (None, "") and getattr(ch, key, None) is not None:
                        details[key] = getattr(ch, key)
        bsr = details.get("bsr_code") or details.get("bsrCode")
        serial = details.get("challan_serial_number") or details.get("challanSerialNumber") or details.get("serial_number")
        challan_date = details.get("challan_date") or details.get("challanDate") or details.get("payment_date") or details.get("challan_generation_date")
        errors: list[dict[str, Any]] = []
        if not bsr:
            errors.append({"field": "bsr_code", "message": "Challan BSR code is required."})
        elif not re.fullmatch(r"[0-9A-Za-z]{7}", str(bsr).strip()):
            errors.append({"field": "bsr_code", "message": "Challan BSR code must contain seven letters/digits."})
        if not serial:
            errors.append({"field": "challan_serial_number", "message": "Challan serial number is required."})
        elif not re.fullmatch(r"[0-9A-Za-z-]{1,50}", str(serial).strip()):
            errors.append({"field": "challan_serial_number", "message": "Invalid challan serial number."})
        if not challan_date:
            errors.append({"field": "challan_date", "message": "Challan date is required."})
        employee_rows = []
        for ps, emp in rows:
            pan = (getattr(emp, "pan_number", None) or "").upper()
            if not re.fullmatch(r"[A-Z]{5}[0-9]{4}[A-Z]", pan):
                errors.append({"employee_id": str(emp.id), "field": "pan_number", "message": "Valid PAN is required for every employee row."})
            tds_paise = int(as_decimal(ps.tds or 0) * 100)
            gross_paise = int(as_decimal(ps.gross_earnings or 0) * 100)
            if tds_paise < 0 or gross_paise < 0:
                errors.append({"employee_id": str(emp.id), "field": "amount", "message": "Gross salary and TDS cannot be negative."})
            employee_rows.append({
                "employee_id": str(emp.id), "employee_code": emp.employee_id,
                "pan": pan, "employee_name": f"{emp.first_name} {emp.last_name}".strip(),
                "period_month": ps.period_month, "period_year": ps.period_year,
                "gross_salary_paise": gross_paise, "tds_paise": tds_paise,
                "gross_salary": str(Decimal(gross_paise) / 100), "tds": str(Decimal(tds_paise) / 100),
            })
        if not employee_rows:
            errors.append({"field": "employee_rows", "message": "At least one payslip row is required."})
        payload = {
            "form_type": "FORM_138", "financial_year": fy, "quarter": q,
            "challan": {**details, "bsr_code": bsr, "challan_serial_number": serial, "challan_date": challan_date},
            "employee_rows": employee_rows,
            "total_tds_paise": sum(r["tds_paise"] for r in employee_rows),
        }
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["BSR Code", "Challan Serial", "Challan Date", "PAN", "Employee Code", "Employee Name", "Month", "Gross Salary", "TDS"])
        for row in employee_rows:
            writer.writerow([bsr or "", serial or "", challan_date or "", row["pan"], row["employee_code"], row["employee_name"], f"{row['period_month']:02d}/{row['period_year']}", row["gross_salary"], row["tds"]])
        form_stmt = select(StatutoryForm).where(
            StatutoryForm.form_type == "FORM_138", StatutoryForm.period_id == period_id,
            StatutoryForm.quarter == q, StatutoryForm.employee_id.is_(None),
        )
        if company_id:
            form_stmt = form_stmt.where(StatutoryForm.company_id == company_id)
        form = (await session.execute(form_stmt)).scalar_one_or_none()
        if not form:
            form = StatutoryForm(id=uuid.uuid4(), form_type="FORM_138", period_id=period_id, employee_id=None)
            session.add(form)
        form.company_id = company_id or period.company_id
        form.financial_year = fy
        form.quarter = q
        form.status = "DRAFT"
        form.payload_json = cls._json_safe(payload)
        form.validation_errors_json = cls._json_safe(errors)
        form.generated_by = generated_by
        form.generated_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(form)
        return {
            "form_id": str(form.id), "id": str(form.id), "form_type": "FORM_138", "status": form.status,
            "validation_status": "VALIDATED" if not errors else "ACTION_REQUIRED",
            "financial_year": fy, "quarter": q, "period_id": str(period_id),
            "challan": cls._json_safe(payload["challan"]), "rows": employee_rows, "employee_rows": employee_rows,
            "validation_errors": errors, "errors": errors, "is_valid": not errors,
            "total_tds_paise": payload["total_tds_paise"], "content": output.getvalue(),
            "csv_text": output.getvalue(), "filename": f"Form138_{fy}_Q{q}.csv",
        }

    @classmethod
    async def generate_form138(
        cls, *args: Any, **kwargs: Any
    ) -> dict[str, Any]:
        return await cls.generate_form138_draft(*args, **kwargs)

    @staticmethod
    def _pdf_document(title: str, sections: list[tuple[str, list[list[str]]]]) -> bytes:
        """Render a small, valid PDF lazily so calculation-only installs stay light."""
        try:
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
            buffer = io.BytesIO()
            doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
            styles = getSampleStyleSheet()
            story = [Paragraph(title, styles["Title"]), Spacer(1, 12)]
            for heading, rows in sections:
                story.append(Paragraph(heading, styles["Heading2"]))
                table = Table(rows, repeatRows=1, hAlign="LEFT")
                table.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EEF7")),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]))
                story.extend([table, Spacer(1, 12)])
            doc.build(story)
            return buffer.getvalue()
        except ImportError:
            # Minimal PDF fallback for environments that intentionally omit the
            # optional reporting dependency.  It remains a valid PDF download.
            text = "%PDF-1.4\n% Form 130\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Count 0/Kids[]>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF"
            return text.encode("ascii")

    @classmethod
    async def generate_form130(
        cls, session: AsyncSession, employee_id: uuid.UUID,
        financial_year: Optional[str] = None, company_id: Optional[uuid.UUID] = None,
        generated_by: Optional[uuid.UUID] = None,
        declarations: Optional[dict[str, Any]] = None,
        period_id: Optional[uuid.UUID] = None,
    ) -> dict[str, Any]:
        """Generate an annual Form 130 PDF with Part A and Part B."""
        period = None
        if period_id is not None:
            period, _ = await cls._period_rows(session, period_id, company_id)
            derived_fy, _, _ = cls._fy_and_quarter(period)
            financial_year = financial_year or derived_fy
        if not financial_year:
            today = date.today()
            start = today.year if today.month >= 4 else today.year - 1
            financial_year = f"{start}-{start + 1}"
        emp_stmt = select(Employee).where(Employee.id == employee_id)
        if company_id:
            emp_stmt = emp_stmt.where(Employee.company_id == company_id)
        emp = (await session.execute(emp_stmt)).scalar_one_or_none()
        if not emp:
            raise HTTPException(status_code=404, detail="Employee not found.")
        start_year = cls._fy_start_year(financial_year)
        pairs = [(m, start_year if m >= 4 else start_year + 1) for m in range(4, 13)] + [(m, start_year + 1) for m in range(1, 4)]
        stmt = select(Payslip).where(Payslip.employee_id == employee_id, or_(*[and_(Payslip.period_month == m, Payslip.period_year == y) for m, y in pairs]))
        if company_id:
            stmt = stmt.where(Payslip.company_id == company_id)
        payslips = (await session.execute(stmt)).scalars().all()
        decl_stmt = select(EmployeeInvestmentDeclaration).where(
            EmployeeInvestmentDeclaration.employee_id == employee_id,
            EmployeeInvestmentDeclaration.financial_year == financial_year,
        )
        declaration = (await session.execute(decl_stmt)).scalar_one_or_none()
        decl_data = declarations or {}
        if declaration:
            for key in ("section_80c", "section_80d", "section_80ccd1b_nps", "home_loan_interest_24b", "section_80g", "hra_claimed", "lta_claimed", "other_deductions"):
                decl_data.setdefault(key, getattr(declaration, key, 0) or 0)
            regime = declaration.tax_regime
            proof_cutoff = declaration.proof_cutoff_date
            cutoff_reference = (period.end_date if period is not None and period.end_date else date.today())
            use_verified = bool(declaration.use_verified_amounts and proof_cutoff and proof_cutoff <= cutoff_reference)
            verified = declaration.verified_details_json or None
            previous_income = declaration.previous_employer_income_paise
            previous_tds = declaration.previous_employer_tds_paise
            bonus = declaration.one_time_bonus_paise
            variable = declaration.variable_pay_paise
        else:
            regime = emp.tax_regime or "NEW"
            use_verified = False
            verified = None
            previous_income = previous_tds = bonus = variable = 0
        gross_paise = sum(int(as_decimal(ps.gross_earnings or 0) * 100) for ps in payslips)
        basic_paise = sum(int(as_decimal(ps.basic or 0) * 100) for ps in payslips)
        hra_paise = sum(int(as_decimal(ps.hra or 0) * 100) for ps in payslips)
        tds_deducted = sum(int(as_decimal(ps.tds or 0) * 100) for ps in payslips)
        if not payslips:
            gross_paise = int(as_decimal(getattr(emp, "ctc", 0) or 0) * 100)
            basic_paise = int(as_decimal(getattr(emp, "basic_salary", 0) or 0) * 100) * 12
            hra_paise = int(as_decimal(getattr(emp, "hra", 0) or 0) * 100) * 12
        computation = cls.calculate_tds(
            annual_gross_paise=gross_paise, tax_regime=regime, declarations=decl_data,
            verified_declarations=verified, use_verified_declarations=use_verified,
            financial_year=financial_year, previous_employer_income_paise=previous_income,
            previous_employer_tds_paise=previous_tds, ytd_tds_paise=tds_deducted,
            one_time_bonus_paise=bonus, variable_pay_paise=variable,
            basic_annual_paise=basic_paise, hra_annual_paise=hra_paise,
        )
        ch_stmt = select(ComplianceChallan).where(ComplianceChallan.challan_type.in_(["TDS", "TDS_CHALLAN", "FORM_138"]))
        if company_id:
            ch_stmt = ch_stmt.where(ComplianceChallan.company_id == company_id)
        challans = (await session.execute(ch_stmt)).scalars().all()
        part_a_rows = [["BSR", "Serial", "Date", "TRRN/CRN", "Amount (Rs.)"]]
        for ch in challans:
            if (ch.period_month, ch.period_year) in pairs:
                part_a_rows.append([str(ch.bsr_code or ""), str(ch.challan_serial_number or ""), str(ch.payment_date or ch.challan_generation_date or ""), str(ch.trrn_number or ch.crn_number or ""), str(ch.total_amount or 0)])
        if len(part_a_rows) == 1:
            part_a_rows.append(["-", "-", "No TDS challan recorded", "-", "0.00"])
        def rs(value: int) -> str:
            return f"{Decimal(value) / 100:.2f}"
        part_b_rows = [
            ["Particular", "Amount (Rs.)"], ["Gross salary", rs(gross_paise)],
            ["Basic salary", rs(basic_paise)], ["HRA", rs(hra_paise)],
            ["HRA exemption", rs(computation["hra_exemption_paise"])],
            ["Standard deduction", rs(computation["standard_deduction_paise"])],
            ["Chapter VI-A deduction", rs(computation["chapter_via_deduction_paise"])],
            ["Professional tax", rs(computation["professional_tax_paise"])],
            ["Section 24b", rs(computation["section_24b_paise"])],
            ["Taxable income", rs(computation["taxable_income_paise"])],
            ["Tax before rebate/cess", rs(computation["gross_tax_paise"])],
            ["87A rebate", rs(computation["rebate_87a_paise"])],
            ["Marginal relief", rs(computation["marginal_relief_paise"])],
            ["Surcharge", rs(computation["surcharge_paise"])], ["Health and education cess", rs(computation["cess_paise"])],
            ["Annual tax liability", rs(computation["annual_tax_paise"])], ["TDS deducted on payslips", rs(tds_deducted)],
        ]
        payload = {"part_a": part_a_rows, "part_b": part_b_rows, "computation": computation, "employee_id": str(employee_id), "financial_year": financial_year}
        form = StatutoryForm(
            id=uuid.uuid4(), company_id=company_id or emp.company_id, employee_id=employee_id,
            form_type="FORM_130", financial_year=financial_year, status="GENERATED",
            payload_json=cls._json_safe(payload), generated_by=generated_by, generated_at=datetime.now(timezone.utc),
        )
        session.add(form)
        await session.commit()
        await session.refresh(form)
        pdf = cls._pdf_document(
            f"Form 130 - Annual Tax Statement ({financial_year})",
            [("Part A - Challan Summary", part_a_rows), ("Part B - Salary, Exemptions, Deductions and Tax Computation", part_b_rows)],
        )
        filename = f"Form130_{emp.employee_id}_{financial_year}.pdf"
        try:
            saved = await StorageService().save_file(UploadFile(file=io.BytesIO(pdf), filename=filename))
            form.file_path = saved["file_path"]
            form.file_url = f"/uploads/documents/{saved['stored_filename']}"
            await session.commit()
            await session.refresh(form)
        except Exception as exc:
            # The binary response remains useful if optional document storage is unavailable.
            logger.warning("Could not persist generated Form 130 PDF: %s", exc)
        return {
            "form_id": str(form.id), "id": str(form.id), "form_type": "FORM_130", "status": "GENERATED",
            "employee_id": str(employee_id), "financial_year": financial_year, "filename": filename,
            "file_path": form.file_path, "file_url": form.file_url,
            "pdf_bytes": pdf, "content": pdf, "part_a": part_a_rows, "part_b": part_b_rows,
            "computation": computation, "tds_deducted_paise": tds_deducted,
        }

    @classmethod
    async def generate_form_138(cls, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return await cls.generate_form138_draft(*args, **kwargs)

    @classmethod
    async def generate_form_130(cls, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return await cls.generate_form130(*args, **kwargs)


    # ─────────────────────────────────────────────────────────────────────────
    # 9. UAN & KYC Validation Engine
    # ─────────────────────────────────────────────────────────────────────────

    @classmethod
    async def get_uan_validation_report(
        cls,
        session: AsyncSession,
        company_id: Optional[uuid.UUID] = None,
    ) -> dict[str, Any]:
        """Audit all active employees for UAN validity, PF eligibility, ceiling toggle, and KYC."""
        emp_stmt = select(Employee).where(
            Employee.is_deleted == False,
            Employee.is_active == True,
        )
        if company_id:
            emp_stmt = emp_stmt.where(Employee.company_id == company_id)

        employees = (await session.execute(emp_stmt)).scalars().all()

        items: list[dict[str, Any]] = []
        valid_cnt = 0
        invalid_cnt = 0
        missing_cnt = 0
        opt_in_cnt = 0
        opt_out_cnt = 0
        intl_cnt = 0

        for emp in employees:
            uan = emp.uan_number
            is_valid, err_msg = Employee.validate_uan_format(uan)

            is_pf_eligible = getattr(emp, "is_pf_eligible", True)
            is_intl = getattr(emp, "is_international_worker", False)
            ceiling_active = getattr(emp, "pf_wage_ceiling_applicable", True)

            if is_valid:
                valid_cnt += 1
            elif not uan:
                missing_cnt += 1
            else:
                invalid_cnt += 1

            if is_pf_eligible:
                opt_in_cnt += 1
            else:
                opt_out_cnt += 1

            if is_intl:
                intl_cnt += 1

            full_name = f"{emp.first_name} {emp.last_name}".strip()
            items.append({
                "employee_id": str(emp.id),
                "employee_code": emp.employee_id or "",
                "name": full_name,
                "uan_number": uan,
                "is_valid": is_valid,
                "validation_error": err_msg if not is_valid else None,
                "is_pf_eligible": is_pf_eligible,
                "pf_membership_active": bool(getattr(emp, "pf_membership_active", True)),
                "is_international_worker": is_intl,
                "pf_wage_ceiling_applicable": ceiling_active,
                "pan_number": emp.pan_number,
                "basic_salary": float(emp.basic_salary or 0),
                "gross_salary": float(emp.ctc or (emp.basic_salary or 0) * Decimal("2.0")),
            })

        return {
            "total_active_employees": len(employees),
            "valid_uan_count": valid_cnt,
            "invalid_uan_count": invalid_cnt,
            "missing_uan_count": missing_cnt,
            "pf_opted_in_count": opt_in_cnt,
            "pf_opted_out_count": opt_out_cnt,
            "international_worker_count": intl_cnt,
            "employees": items,
        }

    @classmethod
    async def update_employee_pf_settings(
        cls,
        session: AsyncSession,
        employee_id: uuid.UUID,
        payload: dict[str, Any],
        company_id: Optional[uuid.UUID] = None,
    ) -> dict[str, Any]:
        """Update an employee's UAN, PF opt-in/opt-out, international worker flag, and wage ceiling toggle."""
        emp_stmt = select(Employee).where(Employee.id == employee_id)
        if company_id:
            emp_stmt = emp_stmt.where(Employee.company_id == company_id)
        emp = (await session.execute(emp_stmt)).scalar_one_or_none()
        if not emp:
            raise HTTPException(status_code=404, detail="Employee not found.")

        if "uan_number" in payload or "uanNumber" in payload:
            raw_uan = payload.get("uan_number") or payload.get("uanNumber")
            if raw_uan is not None and str(raw_uan).strip():
                clean_uan = str(raw_uan).strip()
                is_valid, err = Employee.validate_uan_format(clean_uan)
                if not is_valid:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail=f"Invalid UAN format: {err}",
                    )
                emp.uan_number = clean_uan
            else:
                emp.uan_number = None

        if "is_pf_eligible" in payload or "isPfEligible" in payload:
            emp.is_pf_eligible = bool(payload.get("is_pf_eligible") if "is_pf_eligible" in payload else payload.get("isPfEligible"))

        if "is_international_worker" in payload or "isInternationalWorker" in payload:
            emp.is_international_worker = bool(payload.get("is_international_worker") if "is_international_worker" in payload else payload.get("isInternationalWorker"))

        if "pf_wage_ceiling_applicable" in payload or "pfWageCeilingApplicable" in payload:
            emp.pf_wage_ceiling_applicable = bool(payload.get("pf_wage_ceiling_applicable") if "pf_wage_ceiling_applicable" in payload else payload.get("pfWageCeilingApplicable"))

        for field, aliases in {
            "pf_membership_active": ("pf_membership_active", "pfMembershipActive"),
            "pf_higher_wage_opted": ("pf_higher_wage_opted", "pfHigherWageOpted"),
            "is_pwd": ("is_pwd", "isPwd"),
            "state_code": ("state_code", "stateCode"),
            "vpf_rate": ("vpf_rate", "vpfRate"),
        }.items():
            value = next((payload[name] for name in aliases if name in payload), None)
            if value is not None:
                if field == "vpf_rate":
                    value = as_decimal(value)
                    if value > 1:
                        value /= Decimal("100")
                    if value < 0 or value > 1:
                        raise HTTPException(status_code=422, detail="VPF rate must be between 0 and 100 percent.")
                if field == "state_code":
                    value = cls._state_code(str(value))
                setattr(emp, field, value)

        await session.commit()
        await session.refresh(emp)

        return {
            "employee_id": str(emp.id),
            "uan_number": emp.uan_number,
            "is_pf_eligible": emp.is_pf_eligible,
            "is_international_worker": emp.is_international_worker,
            "pf_wage_ceiling_applicable": emp.pf_wage_ceiling_applicable,
            "pf_membership_active": emp.pf_membership_active,
            "pf_higher_wage_opted": emp.pf_higher_wage_opted,
            "vpf_rate": float(emp.vpf_rate or 0),
            "is_pwd": emp.is_pwd,
            "state_code": emp.state_code,
        }
