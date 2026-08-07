"""Serializer functions converting ORM models to dictionaries."""
from __future__ import annotations

from typing import Any
from app.models.payroll import (
    EmployeeInvestmentDeclaration,
    PayrollAttendanceInput,
    Payslip,
    SalaryStructure,
    StatutoryComplianceConfig,
)
from app.api.payroll.helpers import safe_float, safe_isoformat, safe_uuid_str


def _run_dict(run: Any) -> dict:
    """Serialize PayCycle / PayrollRun ORM object to dictionary."""
    return {
        "id": safe_uuid_str(run.id),
        "company_id": safe_uuid_str(run.company_id),
        "period_month": run.period_month,
        "period_year": run.period_year,
        "status": run.status,
        "total_employees": run.total_employees,
        "total_gross": safe_float(run.total_gross),
        "total_deductions": safe_float(run.total_deductions),
        "total_net": safe_float(run.total_net),
        "run_by": safe_uuid_str(getattr(run, "run_by", None)),
        "run_at": safe_isoformat(getattr(run, "run_at", None)),
        "approved_by": safe_uuid_str(run.approved_by),
        "approved_at": safe_isoformat(run.approved_at),
        "paid_at": safe_isoformat(getattr(run, "paid_at", None)),
        "remarks": getattr(run, "remarks", None),
        "created_at": safe_isoformat(run.created_at),
    }


def _payslip_dict(p: Payslip) -> dict:
    """Serialize Payslip ORM object to dictionary."""
    emp = p.employee if hasattr(p, "employee") and p.employee else None
    emp_name = f"{emp.first_name} {emp.last_name}" if emp else None
    return {
        "id": safe_uuid_str(p.id),
        "payslip_number": p.payslip_number,
        "employee_id": safe_uuid_str(p.employee_id),
        "employee_code": emp.employee_id if emp else safe_uuid_str(p.employee_id),
        "employee_name": emp_name,
        "department": emp.department if emp else "General",
        "designation": emp.designation if emp else "Team Member",
        "location": getattr(emp, "work_location", None) or getattr(emp, "branch", None) or getattr(emp, "location", None) or "Headquarters",
        "email": (getattr(emp, "company_email", None) or getattr(emp, "personal_email", None) or getattr(emp, "email", None) or "") if emp else "",
        "company_id": safe_uuid_str(p.company_id),
        "payroll_run_id": safe_uuid_str(p.payroll_run_id),
        "period_month": p.period_month,
        "period_year": p.period_year,
        "total_days_in_month": p.total_days_in_month,
        "paid_days": safe_float(p.paid_days),
        "lop_days": safe_float(p.lop_days),
        "earnings": {
            "basic": safe_float(p.basic),
            "hra": safe_float(p.hra),
            "conveyance": safe_float(p.conveyance),
            "special_allowance": safe_float(p.special_allowance),
            "other_allowances_total": safe_float(p.other_allowances_total),
            "arrears": safe_float(p.arrears),
            "bonus": safe_float(p.bonus),
            "lop_deduction": safe_float(p.lop_deduction),
            "gross_earnings": safe_float(p.gross_earnings),
        },
        "deductions": {
            "employee_pf": safe_float(p.employee_pf),
            "employer_pf": safe_float(p.employer_pf),
            "employee_esi": safe_float(p.employee_esi),
            "employer_esi": safe_float(p.employer_esi),
            "professional_tax": safe_float(p.professional_tax),
            "tds": safe_float(p.tds),
            "other_deductions": safe_float(p.other_deductions),
            "total_deductions": safe_float(p.total_deductions),
        },
        "net_pay": safe_float(p.net_pay),
        "net_pay_words": p.net_pay_words,
        "status": "GENERATED" if p.generated_at else "PENDING",
        "payment_status": p.payment_status,
        "payment_date": safe_isoformat(p.payment_date),
        "payment_reference": p.payment_reference,
        "email_status": getattr(p, "email_status", "NOT_SENT") or "NOT_SENT",
        "email_sent_at": safe_isoformat(getattr(p, "email_sent_at", None)),
        "download_count": getattr(p, "download_count", 0) or 0,
        "view_count": getattr(p, "view_count", 0) or 0,
        "generated_at": safe_isoformat(p.generated_at),
        "created_at": safe_isoformat(p.created_at),
    }


def _salary_dict(s: SalaryStructure) -> dict:
    """Serialize SalaryStructure ORM object to dictionary."""
    return {
        "id": safe_uuid_str(s.id),
        "employee_id": safe_uuid_str(s.employee_id),
        "company_id": safe_uuid_str(s.company_id),
        "annual_ctc": safe_float(s.annual_ctc),
        "basic_monthly": safe_float(s.basic_monthly),
        "hra_monthly": safe_float(s.hra_monthly),
        "conveyance_monthly": safe_float(s.conveyance_monthly),
        "special_allowance_monthly": safe_float(s.special_allowance_monthly),
        "other_allowances": s.other_allowances,
        "annual_bonus": safe_float(s.annual_bonus),
        "is_metro_city": s.is_metro_city,
        "rent_paid_monthly": safe_float(s.rent_paid_monthly) if s.rent_paid_monthly else None,
        "tax_regime": s.tax_regime,
        "effective_from": safe_isoformat(s.effective_from),
        "effective_to": safe_isoformat(s.effective_to),
        "is_active": s.is_active,
        "created_at": safe_isoformat(s.created_at),
    }


def _att_dict(a: PayrollAttendanceInput) -> dict:
    """Serialize PayrollAttendanceInput ORM object to dictionary."""
    return {
        "id": safe_uuid_str(a.id),
        "employee_id": safe_uuid_str(a.employee_id),
        "company_id": safe_uuid_str(a.company_id),
        "period_month": a.period_month,
        "period_year": a.period_year,
        "paid_days": safe_float(a.paid_days),
        "lop_days": safe_float(a.lop_days),
        "arrears": safe_float(a.arrears),
        "one_time_bonus": safe_float(a.one_time_bonus),
        "remarks": a.remarks,
        "entered_by": safe_uuid_str(a.entered_by),
        "created_at": safe_isoformat(a.created_at),
    }


def _statutory_dict(c: StatutoryComplianceConfig) -> dict:
    """Serialize StatutoryComplianceConfig ORM object to dictionary."""
    return {
        "id": safe_uuid_str(c.id),
        "company_id": safe_uuid_str(c.company_id),
        "company_name": getattr(c, "company_name", "OFC HR Enterprise") or "OFC HR Enterprise",
        "currency": getattr(c, "currency", "INR") or "INR",
        "country": getattr(c, "country", "India") or "India",
        "timezone": getattr(c, "timezone", "Asia/Kolkata") or "Asia/Kolkata",
        "financial_year_start": getattr(c, "financial_year_start", "04-01") or "04-01",
        "payroll_start_day": getattr(c, "payroll_start_day", 1) or 1,
        "payroll_end_day": getattr(c, "payroll_end_day", 30) or 30,
        "salary_payment_date": getattr(c, "salary_payment_date", 1) or 1,
        "auto_lock_payroll": getattr(c, "auto_lock_payroll", True),
        "enable_draft_payroll": getattr(c, "enable_draft_payroll", True),
        "enable_retro_payroll": getattr(c, "enable_retro_payroll", True),
        "pay_cycle_type": getattr(c, "pay_cycle_type", "MONTHLY") or "MONTHLY",
        "grace_period_days": getattr(c, "grace_period_days", 3) or 3,
        "cutoff_date": getattr(c, "cutoff_date", 25) or 25,
        "preview_days": getattr(c, "preview_days", 5) or 5,
        "pf_enabled": c.pf_enabled,
        "employee_pf_rate": safe_float(c.employee_pf_rate),
        "employer_pf_rate": safe_float(c.employer_pf_rate),
        "pf_wage_ceiling": safe_float(c.pf_wage_ceiling),
        "pf_on_full_basic": c.pf_on_full_basic,
        "esi_enabled": c.esi_enabled,
        "employee_esi_rate": safe_float(c.employee_esi_rate),
        "employer_esi_rate": safe_float(c.employer_esi_rate),
        "esi_wage_ceiling": safe_float(c.esi_wage_ceiling),
        "pt_state": c.pt_state,
        "pt_slabs": c.pt_slabs,
        "default_tax_regime": c.default_tax_regime,
        "lop_basis": c.lop_basis,
        "overtime_enabled": getattr(c, "overtime_enabled", True),
        "overtime_multiplier_holiday": safe_float(getattr(c, "overtime_multiplier_holiday", 2.0), 2.0),
        "overtime_multiplier_weekend": safe_float(getattr(c, "overtime_multiplier_weekend", 1.5), 1.5),
        "overtime_multiplier_night": safe_float(getattr(c, "overtime_multiplier_night", 1.25), 1.25),
        "bank_name": getattr(c, "bank_name", "HDFC Bank") or "HDFC Bank",
        "bank_ifsc": getattr(c, "bank_ifsc", "HDFC0001234") or "HDFC0001234",
        "salary_transfer_format": getattr(c, "salary_transfer_format", "NEFT") or "NEFT",
        "auto_email_payslips": getattr(c, "auto_email_payslips", True),
        "auto_backup_payroll": getattr(c, "auto_backup_payroll", True),
        "settings_data": getattr(c, "settings_data", {}) or {},
        "effective_from": safe_isoformat(c.effective_from),
        "is_active": c.is_active,
        "created_at": safe_isoformat(c.created_at),
    }


def _decl_dict(d: EmployeeInvestmentDeclaration) -> dict:
    """Serialize EmployeeInvestmentDeclaration ORM object to dictionary."""
    return {
        "id": safe_uuid_str(d.id),
        "employee_id": safe_uuid_str(d.employee_id),
        "company_id": safe_uuid_str(d.company_id),
        "financial_year": d.financial_year,
        "section_80c": safe_float(d.section_80c),
        "section_80d": safe_float(d.section_80d),
        "section_80ccd1b_nps": safe_float(d.section_80ccd1b_nps),
        "home_loan_interest_24b": safe_float(d.home_loan_interest_24b),
        "other_deductions": safe_float(d.other_deductions),
        "verified_by_hr": d.verified_by_hr,
        "created_at": safe_isoformat(d.created_at),
    }
