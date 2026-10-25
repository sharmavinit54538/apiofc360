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
import uuid
from decimal import Decimal
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employee import Employee
from app.models.payroll import Payslip, StatutoryComplianceConfig
from app.models.payroll_models import PayrollPeriod

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
            cfg = StatutoryComplianceConfig(is_active=True)
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
    ) -> dict[str, Any]:
        """Calculates Indian PF contributions for Employee and Employer.
        
        Rules:
        - Employee: 12% of (Basic + DA)
        - Wage Ceiling: ₹15,000 (15,00,000 paise).
        - If pf_on_full_basic is False (default): PF wage is capped at ₹15,000.
        - Employer breakdown:
            * EPS (Pension): 8.33% capped at ₹1,250/mo (125,000 paise)
            * EPF (Provident Fund): 3.67% (Balance of 12% employer share)
            * EDLI: 0.5% capped at ₹75/mo (7,500 paise)
            * Admin charges: 0.5% (5,000 paise base)
        """
        pf_enabled = config.pf_enabled if config else True
        if not pf_enabled or (basic_paise + da_paise) <= 0:
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

        if full_basic:
            pf_wage_paise = wages_paise
            eps_wage_paise = min(wages_paise, wage_ceiling_paise)
            ceiling_applied = False
        else:
            pf_wage_paise = min(wages_paise, wage_ceiling_paise)
            eps_wage_paise = pf_wage_paise
            ceiling_applied = wages_paise > wage_ceiling_paise

        emp_rate = float(config.employee_pf_rate) if (config and config.employee_pf_rate is not None) else 0.12
        employee_pf_paise = round(pf_wage_paise * emp_rate)

        # EPS capped at ₹1,250/month (125,000 paise) when wage ceiling is enabled
        employer_eps_paise = min(125000, round(eps_wage_paise * 0.0833))
        # EPF: Remaining portion of employer's 12%
        employer_epf_paise = max(0, round(pf_wage_paise * 0.12) - employer_eps_paise)

        # EDLI: 0.5% on EPS wage (capped at ₹75/mo = 7,500 paise)
        employer_edli_paise = min(7500, round(eps_wage_paise * 0.005))
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
    # 3. Employee State Insurance (ESI) Calculation Engine
    # ─────────────────────────────────────────────────────────────────────────

    @classmethod
    def calculate_esi(
        cls,
        gross_monthly_paise: int,
        config: Optional[StatutoryComplianceConfig] = None,
    ) -> dict[str, Any]:
        """Calculates ESI for eligible employees.
        
        Rules:
        - Applicable only if Gross Monthly Salary <= ₹21,000 (2,100,000 paise).
        - Employee share: 0.75% of Gross (rounded UP to the next rupee / 100 paise).
        - Employer share: 3.25% of Gross (rounded UP to the next rupee / 100 paise).
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
                "employee_esi_paise": 0,
                "employer_esi_paise": 0,
                "total_esi_liability_paise": 0,
                "reason": "Exceeds ₹21,000 ceiling" if gross_monthly_paise > ceiling_paise else "ESI disabled or zero gross",
            }

        emp_rate = float(config.employee_esi_rate) if (config and config.employee_esi_rate is not None) else 0.0075
        empr_rate = float(config.employer_esi_rate) if (config and config.employer_esi_rate is not None) else 0.0325

        # Statutory rule: round UP to next whole rupee (ceiling to nearest 100 paise)
        employee_esi_paise = int(math.ceil((gross_monthly_paise * emp_rate) / 100.0) * 100)
        employer_esi_paise = int(math.ceil((gross_monthly_paise * empr_rate) / 100.0) * 100)

        return {
            "is_applicable": True,
            "gross_paise": gross_monthly_paise,
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
    def calculate_gratuity(cls, basic_monthly_paise: int) -> dict[str, Any]:
        """Calculates Gratuity provision: (15 / 26) * monthly_basic / 12 (~4.81% of basic)."""
        provision_paise = int(round((15.0 / 26.0) * basic_monthly_paise / 12.0))
        return {
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
            # EPFO Electronic Challan Return (ECR) format
            for ps in payslips:
                emp_info = (
                    await session.execute(select(Employee).where(Employee.id == ps.employee_id))
                ).scalar_one_or_none()
                uan = getattr(emp_info, "pf_number", "") or "100000000000"
                name = f"{emp_info.first_name} {emp_info.last_name}".strip() if emp_info else "MEMBER"
                output.write(
                    f"{uan}#~#{name}#~#{ps.gross_earnings:.2f}#~#{ps.basic:.2f}#~#{ps.basic:.2f}#~#{ps.basic:.2f}#~#{ps.employee_pf:.2f}#~#{ps.employer_pf:.2f}#~#0.00#~#{ps.lop_days:.0f}#~#0\n"
                )
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
