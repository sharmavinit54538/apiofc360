"""Service for Indian Statutory Compliance calculation engine and government filing reports.

Implements deterministic calculations for:
1. PF (Provident Fund):
   - Employee: 12% of Basic (+ DA).
   - Employer: 3.67% EPF + 8.33% EPS (capped at ₹1,250/mo on ₹15,000 wage ceiling) + 0.5% EDLI + 0.5% Admin charges.
   - Configurable toggle for "Wage Ceiling (₹15,000)" vs "Actual Basic".
2. ESI (Employee State Insurance):
   - Applicable only if Gross Monthly Salary <= ₹21,000.
   - Employee: 0.75% of Gross (rounded up to next rupee).
   - Employer: 3.25% of Gross (rounded up to next rupee).
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
import logging
import math
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employee import Employee
from app.models.payroll import Payslip, StatutoryComplianceConfig
from app.models.payroll_compliance import (
    ComplianceChallan,
    ComplianceDueDate,
    PayrollCompliance,
)
from app.models.payroll_models import PayrollPeriod
from app.services.storage_service import StorageService

logger = logging.getLogger(__name__)


class StatutoryService:
    """Business logic for Indian statutory calculations, compliance config, and filing reports."""

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
    ) -> dict[str, Any]:
        """Calculates Indian PF contributions for Employee and Employer.
        
        Rules:
        - Employee PF: 12% of PF Wages (Basic + DA)
        - Statutory Wage Ceiling: ₹15,000 (15,00,000 paise)
        - Opt-out / Opt-in: If is_pf_eligible is False, contribution is 0
        - International Workers: Wage ceiling toggle does not apply (uncapped)
        - Statutory wage ceiling toggle: if False or pf_on_full_basic is True, PF is calculated on full basic
        - Employer breakdown:
            * EPS (Pension): 8.33% capped at ₹1,250/mo (125,000 paise) if ceiling applies. 0 if age >= 58.
            * EPF (Provident Fund): Balance of 12% employer share (3.67% or 12% - EPS)
            * EDLI: 0.5% capped at ₹75/mo (7,500 paise)
            * Admin charges: 0.5% (minimum ₹500/month establishment rule)
        """
        pf_enabled = config.pf_enabled if config else True
        if not pf_enabled or not is_pf_eligible or (basic_paise + da_paise) <= 0:
            return {
                "pf_wage_paise": 0,
                "employee_pf_paise": 0,
                "employer_epf_paise": 0,
                "employer_eps_paise": 0,
                "employer_edli_paise": 0,
                "employer_admin_paise": 0,
                "total_employer_pf_paise": 0,
                "total_pf_liability_paise": 0,
                "wage_ceiling_applied": False,
            }

        full_basic = (
            pf_on_full_basic
            if pf_on_full_basic is not None
            else (config.pf_on_full_basic if config else False)
        )
        wage_ceiling_paise = int(
            (config.pf_wage_ceiling * 100)
            if (config and config.pf_wage_ceiling)
            else (15000 * 100)
        )
        wages_paise = basic_paise + da_paise

        if is_international_worker:
            # International workers: uncapped PF and EPS under EPFO statutory provisions
            pf_wage_paise = wages_paise
            eps_wage_paise = wages_paise
            edli_wage_paise = min(wages_paise, wage_ceiling_paise)
            ceiling_applied = False
        elif not pf_wage_ceiling_applicable or full_basic:
            pf_wage_paise = wages_paise
            eps_wage_paise = min(wages_paise, wage_ceiling_paise)
            edli_wage_paise = min(wages_paise, wage_ceiling_paise)
            ceiling_applied = False
        else:
            pf_wage_paise = min(wages_paise, wage_ceiling_paise)
            eps_wage_paise = pf_wage_paise
            edli_wage_paise = pf_wage_paise
            ceiling_applied = wages_paise > wage_ceiling_paise

        emp_rate = float(config.employee_pf_rate) if (config and config.employee_pf_rate is not None) else 0.12
        employee_pf_paise = round(pf_wage_paise * emp_rate)

        # EPS (Pension): 8.33% capped at ₹1,250/month (125,000 paise).
        # Under EPFO rules, EPS contributions cease at age 58; full 12% goes to EPF.
        if age is not None and age >= 58:
            employer_eps_paise = 0
        elif is_international_worker:
            employer_eps_paise = round(eps_wage_paise * 0.0833)
        else:
            employer_eps_paise = min(125000, round(eps_wage_paise * 0.0833))

        # EPF: Remaining portion of employer's 12% share
        total_employer_12_paise = round(pf_wage_paise * 0.12)
        employer_epf_paise = max(0, total_employer_12_paise - employer_eps_paise)

        # EDLI: 0.5% on EDLI wage (capped at ₹75/mo = 7,500 paise)
        employer_edli_paise = min(7500, round(edli_wage_paise * 0.005))

        # Admin charges: 0.5% of PF wage
        employer_admin_paise = round(pf_wage_paise * 0.005)

        total_employer_pf_paise = employer_epf_paise + employer_eps_paise
        total_pf_liability_paise = (
            employee_pf_paise + total_employer_pf_paise + employer_edli_paise + employer_admin_paise
        )

        return {
            "pf_wage_paise": pf_wage_paise,
            "employee_pf_paise": employee_pf_paise,
            "employer_epf_paise": employer_epf_paise,
            "employer_eps_paise": employer_eps_paise,
            "employer_edli_paise": employer_edli_paise,
            "employer_admin_paise": employer_admin_paise,
            "total_employer_pf_paise": total_employer_pf_paise,
            "total_pf_liability_paise": total_pf_liability_paise,
            "wage_ceiling_applied": ceiling_applied,
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

    @classmethod
    def calculate_esi(
        cls,
        gross_monthly_paise: int,
        config: Optional[StatutoryComplianceConfig] = None,
        contribution_wage_paise: Optional[int] = None,
    ) -> dict[str, Any]:
        """Calculates ESI for eligible employees.
        
        Rules:
        - Applicable only if Gross Monthly Salary <= ₹21,000 (2,100,000 paise).
        - Employee share: 0.75% of Gross (rounded UP to the next rupee / 100 paise).
        - Employer share: 3.25% of Gross (rounded UP to the next rupee / 100 paise).
        - When the Code on Wages "wages" definition is in force, the caller passes
          ``contribution_wage_paise`` (the statutory wage base after the 50% rule)
          and contributions are computed on that base instead of gross.  Eligibility
          itself is still tested against the ₹21,000 *gross* ceiling.
        """
        esi_enabled = config.esi_enabled if config else True
        ceiling_paise = int(
            (config.esi_wage_ceiling * 100)
            if (config and config.esi_wage_ceiling)
            else (21000 * 100)
        )

        if not esi_enabled or gross_monthly_paise <= 0 or gross_monthly_paise > ceiling_paise:
            return {
                "is_applicable": False,
                "gross_paise": gross_monthly_paise,
                "contribution_wage_paise": int(contribution_wage_paise or gross_monthly_paise),
                "employee_esi_paise": 0,
                "employer_esi_paise": 0,
                "total_esi_liability_paise": 0,
                "reason": "Exceeds ₹21,000 ceiling" if gross_monthly_paise > ceiling_paise else "ESI disabled or zero gross",
            }

        emp_rate = float(config.employee_esi_rate) if (config and config.employee_esi_rate is not None) else 0.0075
        empr_rate = float(config.employer_esi_rate) if (config and config.employer_esi_rate is not None) else 0.0325

        wage_base_paise = (
            int(contribution_wage_paise) if contribution_wage_paise is not None else int(gross_monthly_paise)
        )
        wage_base_paise = max(0, wage_base_paise)

        # Statutory rule: round UP to next whole rupee (ceiling to nearest 100 paise)
        employee_esi_paise = int(math.ceil((wage_base_paise * emp_rate) / 100.0) * 100)
        employer_esi_paise = int(math.ceil((wage_base_paise * empr_rate) / 100.0) * 100)

        return {
            "is_applicable": True,
            "gross_paise": gross_monthly_paise,
            "contribution_wage_paise": wage_base_paise,
            "employee_esi_paise": employee_esi_paise,
            "employer_esi_paise": employer_esi_paise,
            "total_esi_liability_paise": employee_esi_paise + employer_esi_paise,
            "reason": "Eligible under ₹21,000 gross wage ceiling",
        }

    # ─────────────────────────────────────────────────────────────────────────
    # 4. Professional Tax (PT) State-Wise Slab Engine
    # ─────────────────────────────────────────────────────────────────────────

    @classmethod
    def calculate_pt(
        cls,
        gross_monthly_paise: int,
        state: str = "MAHARASHTRA",
        month: int = 3,
        gender: str = "MALE",
    ) -> dict[str, Any]:
        """Calculates Professional Tax (PT) based on employee work state and monthly gross earnings."""
        st = (state or "MAHARASHTRA").upper().strip()
        gross_inr = gross_monthly_paise / 100.0
        pt_inr = 0

        if st in ("MAHARASHTRA", "MH"):
            if gross_inr <= 7500:
                pt_inr = 0
            elif gross_inr <= 10000:
                pt_inr = 175
            else:
                # Maharashtra: ₹300 in February (month 2), ₹200 for remaining months
                pt_inr = 300 if month == 2 else 200

        elif st in ("KARNATAKA", "KA"):
            pt_inr = 200 if gross_inr >= 15000 else 0

        elif st in ("GUJARAT", "GJ"):
            if gross_inr <= 12000:
                pt_inr = 0
            else:
                pt_inr = 200

        elif st in ("ANDHRA PRADESH", "AP", "TELANGANA", "TS", "TG"):
            if gross_inr <= 15000:
                pt_inr = 0
            elif gross_inr <= 20000:
                pt_inr = 150
            else:
                pt_inr = 200

        elif st in ("WEST BENGAL", "WB"):
            if gross_inr <= 10000:
                pt_inr = 0
            elif gross_inr <= 15000:
                pt_inr = 110
            elif gross_inr <= 25000:
                pt_inr = 130
            elif gross_inr <= 40000:
                pt_inr = 150
            else:
                pt_inr = 200

        elif st in ("TAMIL NADU", "TN"):
            if gross_inr <= 21000:
                pt_inr = 0
            elif gross_inr <= 30000:
                pt_inr = 100
            elif gross_inr <= 45000:
                pt_inr = 235
            elif gross_inr <= 60000:
                pt_inr = 510
            elif gross_inr <= 75000:
                pt_inr = 760
            else:
                pt_inr = 1025

        elif st in ("MADHYA PRADESH", "MP"):
            if gross_inr <= 18750:
                pt_inr = 0
            elif gross_inr <= 25000:
                pt_inr = 125
            elif gross_inr <= 33333:
                pt_inr = 167
            else:
                pt_inr = 212 if month == 3 else 208

        elif st in (
            "RAJASTHAN", "RJ",
            "DELHI", "DL",
            "HARYANA", "HR",
            "UTTAR PRADESH", "UP",
            "PUNJAB", "PB",
            "HIMACHAL PRADESH", "HP",
            "UTTARAKHAND", "UK",
        ):
            # No Professional Tax in these states/UTs
            pt_inr = 0

        else:
            # General fallback for states with ₹200 standard deduction
            pt_inr = 200 if gross_inr > 10000 else 0

        pt_paise = int(pt_inr * 100)
        return {
            "state": st,
            "gross_paise": gross_monthly_paise,
            "pt_paise": pt_paise,
            "pt_inr": pt_inr,
            "month": month,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # 5. Labour Welfare Fund (LWF) Engine
    # ─────────────────────────────────────────────────────────────────────────

    @classmethod
    def calculate_lwf(
        cls,
        gross_monthly_paise: int,
        state: str = "MAHARASHTRA",
        month: int = 6,
    ) -> dict[str, Any]:
        """Calculates Labour Welfare Fund (LWF) for employee and employer."""
        st = (state or "MAHARASHTRA").upper().strip()
        gross_inr = gross_monthly_paise / 100.0
        emp_lwf_inr = 0
        empr_lwf_inr = 0

        if gross_inr <= 0:
            return {"employee_lwf_paise": 0, "employer_lwf_paise": 0, "is_applicable": False}

        if st in ("MAHARASHTRA", "MH"):
            # Semi-annual: June & December
            if month in (6, 12):
                if gross_inr <= 3000:
                    emp_lwf_inr, empr_lwf_inr = 6, 18
                else:
                    emp_lwf_inr, empr_lwf_inr = 12, 36
        elif st in ("KARNATAKA", "KA"):
            # Annual: December
            if month == 12:
                emp_lwf_inr, empr_lwf_inr = 20, 40
        elif st in ("GUJARAT", "GJ"):
            # Semi-annual: June & December
            if month in (6, 12):
                emp_lwf_inr, empr_lwf_inr = 6, 12
        elif st in ("HARYANA", "HR"):
            # Monthly: 0.2% max ₹25 / ₹50
            emp_lwf_inr = min(25, round(gross_inr * 0.002))
            empr_lwf_inr = emp_lwf_inr * 2
        elif st in ("DELHI", "DL"):
            # Semi-annual: June & December
            if month in (6, 12):
                emp_lwf_inr, empr_lwf_inr = 1, 3
        else:
            # Baseline standard monthly default
            emp_lwf_inr, empr_lwf_inr = 10, 20

        return {
            "employee_lwf_paise": int(emp_lwf_inr * 100),
            "employer_lwf_paise": int(empr_lwf_inr * 100),
            "is_applicable": (emp_lwf_inr + empr_lwf_inr) > 0,
            "state": st,
            "month": month,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # 6. TDS (Income Tax - Old vs New Regime) Projection Engine
    # ─────────────────────────────────────────────────────────────────────────

    @classmethod
    def calculate_tds(
        cls,
        annual_gross_paise: int,
        tax_regime: str = "NEW",
        declarations: Optional[dict[str, Any]] = None,
        remaining_months: int = 12,
    ) -> dict[str, Any]:
        """Calculates Annual Income Tax and Monthly TDS for Old vs New Regime."""
        regime = (tax_regime or "NEW").upper().strip()
        decl = declarations or {}
        annual_gross_inr = annual_gross_paise / 100.0

        if regime == "NEW":
            # New Regime (FY 2024-25 / 2025-26 under Budget Sec 115BAC):
            # Standard Deduction: ₹75,000
            standard_deduction = 75000.0
            taxable_income = max(0.0, annual_gross_inr - standard_deduction)

            # Slabs:
            # 0 - 3,00,000: Nil
            # 3,00,001 - 7,00,000: 5% (₹20,000)
            # 7,00,001 - 10,00,000: 10% (₹30,000)
            # 10,00,001 - 12,00,000: 15% (₹30,000)
            # 12,00,001 - 15,00,000: 20% (₹60,000)
            # > 15,00,000: 30%
            tax = 0.0
            if taxable_income > 1500000:
                tax += (taxable_income - 1500000) * 0.30
                tax += 300000 * 0.20
                tax += 200000 * 0.15
                tax += 300000 * 0.10
                tax += 400000 * 0.05
            elif taxable_income > 1200000:
                tax += (taxable_income - 1200000) * 0.20
                tax += 200000 * 0.15
                tax += 300000 * 0.10
                tax += 400000 * 0.05
            elif taxable_income > 1000000:
                tax += (taxable_income - 1000000) * 0.15
                tax += 300000 * 0.10
                tax += 400000 * 0.05
            elif taxable_income > 700000:
                tax += (taxable_income - 700000) * 0.10
                tax += 400000 * 0.05
            elif taxable_income > 300000:
                tax += (taxable_income - 300000) * 0.05

            # Section 87A rebate: Taxable Income <= ₹7,00,000 pays ZERO tax
            rebate_87a = 0.0
            if taxable_income <= 700000:
                rebate_87a = tax
                tax = 0.0

            cess = tax * 0.04
            total_annual_tax = tax + cess
            exemptions_total = standard_deduction

        else:
            # Old Tax Regime:
            # Standard Deduction: ₹50,000
            standard_deduction = 50000.0
            sec_80c = min(150000.0, float(decl.get("section_80c", 0) or 0))
            sec_80d = min(50000.0, float(decl.get("section_80d", 0) or 0))
            sec_80ccd1b = min(50000.0, float(decl.get("section_80ccd1b_nps", 0) or 0))
            sec_24b = min(200000.0, float(decl.get("home_loan_interest_24b", 0) or 0))
            hra_exemption = float(decl.get("hra_claimed", 0) or 0)
            other_ded = float(decl.get("other_deductions", 0) or 0)

            total_deductions = (
                standard_deduction
                + sec_80c
                + sec_80d
                + sec_80ccd1b
                + sec_24b
                + hra_exemption
                + other_ded
            )
            taxable_income = max(0.0, annual_gross_inr - total_deductions)

            # Slabs:
            # 0 - 2,50,000: Nil
            # 2,50,001 - 5,00,000: 5% (₹12,500)
            # 5,00,001 - 10,00,000: 20% (₹1,00,000)
            # > 10,00,000: 30%
            tax = 0.0
            if taxable_income > 1000000:
                tax += (taxable_income - 1000000) * 0.30
                tax += 500000 * 0.20
                tax += 250000 * 0.05
            elif taxable_income > 500000:
                tax += (taxable_income - 500000) * 0.20
                tax += 250000 * 0.05
            elif taxable_income > 250000:
                tax += (taxable_income - 250000) * 0.05

            # Section 87A rebate: Taxable Income <= ₹5,00,000 gets up to ₹12,500 rebate
            rebate_87a = 0.0
            if taxable_income <= 500000:
                rebate_87a = min(12500.0, tax)
                tax = max(0.0, tax - rebate_87a)

            cess = tax * 0.04
            total_annual_tax = tax + cess
            exemptions_total = total_deductions

        rem_months = max(1, min(12, remaining_months))
        monthly_tds_paise = int(round((total_annual_tax / rem_months) * 100))

        return {
            "tax_regime": regime,
            "annual_gross_paise": annual_gross_paise,
            "standard_deduction_paise": int(standard_deduction * 100),
            "total_exemptions_paise": int(exemptions_total * 100),
            "taxable_income_paise": int(taxable_income * 100),
            "tax_before_cess_paise": int(tax * 100),
            "rebate_87a_paise": int(rebate_87a * 100),
            "cess_paise": int(cess * 100),
            "annual_tax_paise": int(total_annual_tax * 100),
            "remaining_months": rem_months,
            "monthly_tds_paise": monthly_tds_paise,
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
            ecr_res = await cls.generate_pf_ecr(session, period_id=period_id)
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
    ) -> dict[str, Any]:
        """Generate official EPFO Electronic Challan Return (ECR) v2.0 text file.
        
        Exact 11-column EPFO ECR standard format (#|~|# separated):
        1. UAN (12 numeric digits)
        2. Member Name (uppercase, alphanumeric & spaces only, max 80 chars)
        3. Gross Wages (in Rs, integer/rounded)
        4. EPF Wages (capped at ₹15,000 unless ceiling toggle disabled / international worker)
        5. EPS Wages (capped at ₹15,000, 0 if employee age >= 58 or opted out)
        6. EDLI Wages (capped at ₹15,000)
        7. EPF Contri Remitted (Employee share 12% rounded to nearest rupee)
        8. EPS Contri Remitted (Employer share EPS 8.33% capped at ₹1,250)
        9. EPF-EPS Diff Remitted (Employer share EPF 12% - EPS Contri)
        10. NCP Days (Non-Contributing Period / LOP days)
        11. Refund of Advances (0)
        """
        p_stmt = select(PayrollPeriod).where(PayrollPeriod.id == period_id)
        period = (await session.execute(p_stmt)).scalar_one_or_none()
        if not period:
            raise HTTPException(status_code=404, detail="Payroll period not found.")

        config = await cls.get_config(session, company_id=company_id)

        ps_stmt = (
            select(Payslip)
            .where(
                Payslip.period_month == period.period_month,
                Payslip.period_year == period.period_year,
            )
        )
        if company_id:
            ps_stmt = ps_stmt.where(Payslip.company_id == company_id)

        payslips = (await session.execute(ps_stmt)).scalars().all()

        records: list[dict[str, Any]] = []
        raw_lines: list[str] = []

        total_gross = 0.0
        total_epf_wages = 0.0
        total_eps_wages = 0.0
        total_ee_share = 0.0
        total_eps_share = 0.0
        total_er_diff_share = 0.0
        total_edli_share = 0.0
        missing_uan_count = 0

        for ps in payslips:
            emp_info = (
                await session.execute(select(Employee).where(Employee.id == ps.employee_id))
            ).scalar_one_or_none()

            uan_raw = (getattr(emp_info, "uan_number", "") or "").strip() if emp_info else ""
            is_valid_uan = len(uan_raw) == 12 and uan_raw.isdigit()
            if not is_valid_uan:
                missing_uan_count += 1
                uan_formatted = uan_raw if uan_raw else "000000000000"
            else:
                uan_formatted = uan_raw

            raw_name = (
                f"{emp_info.first_name} {emp_info.last_name}".strip()
                if emp_info
                else "MEMBER"
            )
            # EPFO standard: uppercase, alphanumeric & spaces only, max 80 chars
            clean_name = re.sub(r"[^A-Za-z0-9 ]", "", raw_name).strip().upper()[:80]
            if not clean_name:
                clean_name = "MEMBER"

            is_pf_eligible = getattr(emp_info, "is_pf_eligible", True)
            is_intl = getattr(emp_info, "is_international_worker", False)
            ceiling_active = getattr(emp_info, "pf_wage_ceiling_applicable", True)

            gross_w = round(float(ps.gross_earnings or 0))
            basic_w = round(float(ps.basic or 0))

            if not is_pf_eligible:
                epf_w = 0
                eps_w = 0
                edli_w = 0
                ee_c = 0
                eps_c = 0
                er_diff_c = 0
                edli_c = 0
            else:
                if is_intl:
                    epf_w = basic_w
                    eps_w = basic_w
                    edli_w = min(basic_w, 15000)
                elif not ceiling_active or config.pf_on_full_basic:
                    epf_w = basic_w
                    eps_w = min(basic_w, 15000)
                    edli_w = min(basic_w, 15000)
                else:
                    epf_w = min(basic_w, 15000)
                    eps_w = min(basic_w, 15000)
                    edli_w = min(basic_w, 15000)

                # Employee PF (12%)
                if ps.employee_pf and ps.employee_pf > 0:
                    ee_c = round(float(ps.employee_pf))
                else:
                    ee_c = round(epf_w * 0.12)

                # Employee age check for EPS capping
                age: Optional[int] = None
                if emp_info and emp_info.date_of_birth:
                    today = date.today()
                    age = today.year - emp_info.date_of_birth.year - (
                        (today.month, today.day) < (emp_info.date_of_birth.month, emp_info.date_of_birth.day)
                    )

                # Employer EPS: 8.33% capped at ₹1,250 (0 if age >= 58)
                if age is not None and age >= 58:
                    eps_c = 0
                elif is_intl:
                    eps_c = round(eps_w * 0.0833)
                else:
                    eps_c = min(1250, round(eps_w * 0.0833))

                # Employer EPF Difference (12% Total - EPS)
                total_er_12 = round(epf_w * 0.12)
                er_diff_c = max(0, total_er_12 - eps_c)

                # EDLI: 0.5% capped at ₹75
                edli_c = min(75, round(edli_w * 0.005))

            ncp_d = int(float(ps.lop_days or 0))
            refund = 0

            # EPFO ECR v2.0 exact row layout (#|~|# delimiter)
            line = f"{uan_formatted}#|~|#{clean_name}#|~|#{gross_w}#|~|#{epf_w}#|~|#{eps_w}#|~|#{edli_w}#|~|#{ee_c}#|~|#{eps_c}#|~|#{er_diff_c}#|~|#{ncp_d}#|~|#{refund}"
            raw_lines.append(line)

            records.append({
                "uan": uan_formatted,
                "member_name": clean_name,
                "gross_wages": float(gross_w),
                "epf_wages": float(epf_w),
                "eps_wages": float(eps_w),
                "edli_wages": float(edli_w),
                "ee_remitted": float(ee_c),
                "eps_remitted": float(eps_c),
                "er_diff_remitted": float(er_diff_c),
                "ncp_days": ncp_d,
                "refund_advances": float(refund),
            })

            total_gross += gross_w
            total_epf_wages += epf_w
            total_eps_wages += eps_w
            total_ee_share += ee_c
            total_eps_share += eps_c
            total_er_diff_share += er_diff_c
            total_edli_share += edli_c

        # Admin charges: 0.5% of EPF wages, establishment minimum ₹500
        admin_charges = max(500.0, round(total_epf_wages * 0.005)) if total_epf_wages > 0 else 0.0
        total_pf_liability = (
            total_ee_share + total_eps_share + total_er_diff_share + total_edli_share + admin_charges
        )

        ecr_text_content = "\r\n".join(raw_lines) + ("\r\n" if raw_lines else "")
        file_name = f"EPFO_ECR_{period.period_year}_{period.period_month:02d}.txt"

        # Update or record ComplianceChallan for this period
        challan_stmt = select(ComplianceChallan).where(
            ComplianceChallan.period_id == period_id,
            ComplianceChallan.challan_type == "EPFO_ECR",
        )
        challan = (await session.execute(challan_stmt)).scalar_one_or_none()
        if not challan:
            challan = ComplianceChallan(
                id=uuid.uuid4(),
                company_id=company_id or getattr(period, "company_id", None),
                period_id=period_id,
                challan_type="EPFO_ECR",
                period_month=period.period_month,
                period_year=period.period_year,
                total_amount=Decimal(str(total_pf_liability)),
                employee_count=len(payslips),
                epf_employee_amount=Decimal(str(total_ee_share)),
                epf_employer_amount=Decimal(str(total_er_diff_share)),
                eps_amount=Decimal(str(total_eps_share)),
                edli_amount=Decimal(str(total_edli_share)),
                admin_charges=Decimal(str(admin_charges)),
                file_payload=ecr_text_content,
                status="ECR_GENERATED",
            )
            session.add(challan)
        else:
            challan.total_amount = Decimal(str(total_pf_liability))
            challan.employee_count = len(payslips)
            challan.epf_employee_amount = Decimal(str(total_ee_share))
            challan.epf_employer_amount = Decimal(str(total_er_diff_share))
            challan.eps_amount = Decimal(str(total_eps_share))
            challan.edli_amount = Decimal(str(total_edli_share))
            challan.admin_charges = Decimal(str(admin_charges))
            challan.file_payload = ecr_text_content
            if challan.status in ("GENERATED", "PENDING"):
                challan.status = "ECR_GENERATED"

        # Update or create ComplianceDueDate record
        due_month = period.period_month + 1 if period.period_month < 12 else 1
        due_year = period.period_year if period.period_month < 12 else period.period_year + 1
        due_date = date(due_year, due_month, 15)

        due_stmt = select(ComplianceDueDate).where(
            ComplianceDueDate.period_id == period_id,
            ComplianceDueDate.period_month == period.period_month,
            ComplianceDueDate.period_year == period.period_year,
        )
        due_rec = (await session.execute(due_stmt)).scalar_one_or_none()
        if not due_rec:
            month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
            due_rec = ComplianceDueDate(
                id=uuid.uuid4(),
                company_id=company_id or getattr(period, "company_id", None),
                compliance_id=None,
                challan_id=challan.id,
                period_id=period_id,
                title=f"EPFO PF & ECR Filing - {month_names[period.period_month - 1]} {period.period_year}",
                due_date=due_date,
                period=f"{month_names[period.period_month - 1]} {period.period_year}",
                period_month=period.period_month,
                period_year=period.period_year,
                status="ECR_GENERATED",
            )
            session.add(due_rec)
        elif due_rec.status in ("PENDING", "GENERATED"):
            due_rec.status = "ECR_GENERATED"
            due_rec.challan_id = challan.id

        await session.commit()

        month_names = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
        wage_month_str = f"{month_names[period.period_month - 1]} {period.period_year}"

        return {
            "period_id": str(period_id),
            "period_month": period.period_month,
            "period_year": period.period_year,
            "wage_month": wage_month_str,
            "filename": file_name,
            "record_count": len(records),
            "total_gross": total_gross,
            "total_epf_wages": total_epf_wages,
            "total_eps_wages": total_eps_wages,
            "total_ee_share": total_ee_share,
            "total_eps_share": total_eps_share,
            "total_er_diff_share": total_er_diff_share,
            "total_edli_share": total_edli_share,
            "admin_charges": admin_charges,
            "total_pf_liability": total_pf_liability,
            "records": records,
            "ecr_text": ecr_text_content,
            "has_missing_uan": missing_uan_count > 0,
            "missing_uan_count": missing_uan_count,
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
        challan = (await session.execute(ch_stmt)).scalar_one_or_none()

        gen_date_raw = payload.get("challan_generation_date") or payload.get("challanGenerationDate")
        pay_date_raw = payload.get("payment_date") or payload.get("paymentDate")

        gen_date = date.fromisoformat(gen_date_raw) if gen_date_raw else None
        pay_date = date.fromisoformat(pay_date_raw) if pay_date_raw else None

        utr = payload.get("utr_number") or payload.get("utrNumber")
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
                challan_generation_date=gen_date,
                payment_date=pay_date,
                utr_number=utr,
                total_amount=Decimal(str(total_amt or 0)),
                status=challan_status,
            )
            session.add(challan)
        else:
            challan.trrn_number = str(trrn).strip()
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
        period = (await session.execute(p_stmt)).scalar_one_or_none()
        if not period:
            raise HTTPException(status_code=404, detail="Payroll period not found.")

        storage = StorageService()
        saved = await storage.save_file(file)

        ch_stmt = select(ComplianceChallan).where(
            ComplianceChallan.period_id == period_id,
            ComplianceChallan.challan_type == "EPFO_ECR",
        )
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
    ) -> dict[str, Any]:
        """Update an employee's UAN, PF opt-in/opt-out, international worker flag, and wage ceiling toggle."""
        emp = (
            await session.execute(select(Employee).where(Employee.id == employee_id))
        ).scalar_one_or_none()
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

        await session.commit()
        await session.refresh(emp)

        return {
            "employee_id": str(emp.id),
            "uan_number": emp.uan_number,
            "is_pf_eligible": emp.is_pf_eligible,
            "is_international_worker": emp.is_international_worker,
            "pf_wage_ceiling_applicable": emp.pf_wage_ceiling_applicable,
        }
