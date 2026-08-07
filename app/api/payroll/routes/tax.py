"""Route handlers for Tax Management (TDS 192, 80C Declarations, Regimes, Form 16) — Fully Database Powered."""
from __future__ import annotations

from typing import Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Query
from sqlalchemy import select, func, or_, and_

from app.api.payroll.dependencies import DB, Claims
from app.api.payroll.permissions import _require_admin_or_manager
from app.api.payroll.responses import success_response
from app.schemas.auth import APIResponse
from app.models.employee import Employee
from app.models.payroll import EmployeeInvestmentDeclaration, SalaryStructure, Payslip

router = APIRouter()


@router.get("/admin/tax", response_model=APIResponse[dict], summary="Get tax management list for admin")
@router.get("/tax", response_model=APIResponse[dict], summary="Get tax management list")
@router.head("/admin/tax")
@router.head("/tax")
async def get_tax_management_records(
    claims: Claims,
    db: DB,
    financial_year: Optional[str] = Query("2026-2027"),
    department: Optional[str] = Query(None),
    designation: Optional[str] = Query(None),
    location: Optional[str] = Query(None),
    tax_regime: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    sort_by: Optional[str] = Query("name"),
    sort_dir: Optional[str] = Query("asc"),
    search: Optional[str] = Query(None),
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    fy = financial_year or "2026-2027"

    stmt = select(Employee).where(Employee.is_deleted == False)

    if claims and isinstance(claims, dict) and claims.get("company_id"):
        stmt = stmt.where(Employee.company_id == claims.get("company_id"))

    if search and search.strip():
        s = f"%{search.strip().lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Employee.first_name).like(s),
                func.lower(Employee.last_name).like(s),
                func.lower(Employee.employee_id).like(s),
                func.lower(Employee.pan_number).like(s),
                func.lower(Employee.company_email).like(s),
                func.lower(Employee.personal_email).like(s),
            )
        )

    if department and department != "all":
        stmt = stmt.where(func.lower(Employee.department) == department.lower())

    if designation and designation != "all":
        stmt = stmt.where(func.lower(Employee.designation) == designation.lower())

    if location and location != "all":
        stmt = stmt.where(
            or_(
                func.lower(Employee.work_location) == location.lower(),
                func.lower(Employee.branch) == location.lower(),
            )
        )

    res = await db.execute(stmt)
    employees = res.scalars().all()

    tax_items = []
    for emp in employees:
        decl_stmt = select(EmployeeInvestmentDeclaration).where(
            and_(
                EmployeeInvestmentDeclaration.employee_id == emp.id,
                EmployeeInvestmentDeclaration.financial_year == fy,
            )
        )
        decl_res = await db.execute(decl_stmt)
        decl = decl_res.scalars().first()

        sal_stmt = select(SalaryStructure).where(
            and_(
                SalaryStructure.employee_id == emp.id,
                SalaryStructure.is_active == True,
            )
        )
        sal_res = await db.execute(sal_stmt)
        sal = sal_res.scalars().first()

        gross_salary = float(sal.annual_ctc) if sal and sal.annual_ctc else (float(emp.ctc) if emp.ctc else 0.0)
        chosen_regime = (decl.tax_regime if decl and decl.tax_regime else (sal.tax_regime if sal and sal.tax_regime else (emp.tax_regime or "NEW"))).upper()

        if tax_regime and tax_regime != "all":
            if tax_regime.upper() not in chosen_regime:
                continue

        decl_status = (decl.status if decl and decl.status else "PENDING").upper()
        if status and status != "all":
            if status.upper() not in decl_status:
                continue

        sec_80c = float(decl.section_80c) if decl and decl.section_80c else 0.0
        sec_80d = float(decl.section_80d) if decl and decl.section_80d else 0.0
        nps = float(decl.section_80ccd1b_nps) if decl and decl.section_80ccd1b_nps else 0.0
        home_loan = float(decl.home_loan_interest_24b) if decl and decl.home_loan_interest_24b else 0.0
        hra_claimed = float(decl.hra_claimed) if decl and decl.hra_claimed else 0.0
        other_ded = float(decl.other_deductions) if decl and decl.other_deductions else 0.0

        if "OLD" in chosen_regime:
            total_deductions = min(sec_80c, 150000.0) + sec_80d + min(nps, 50000.0) + min(home_loan, 200000.0) + hra_claimed + other_ded + 50000.0
            exemptions = 50000.0
        else:
            total_deductions = 75000.0
            exemptions = 75000.0

        taxable_income = max(0.0, gross_salary - total_deductions)

        net_tax = 0.0
        if "OLD" in chosen_regime:
            if taxable_income > 1000000:
                net_tax = 112500 + (taxable_income - 1000000) * 0.30
            elif taxable_income > 500000:
                net_tax = 12500 + (taxable_income - 500000) * 0.20
            elif taxable_income > 250000:
                net_tax = (taxable_income - 250000) * 0.05
        else:
            if taxable_income > 1500000:
                net_tax = 150000 + (taxable_income - 1500000) * 0.30
            elif taxable_income > 1200000:
                net_tax = 90000 + (taxable_income - 1200000) * 0.20
            elif taxable_income > 900000:
                net_tax = 45000 + (taxable_income - 900000) * 0.15
            elif taxable_income > 600000:
                net_tax = 15000 + (taxable_income - 600000) * 0.10
            elif taxable_income > 300000:
                net_tax = (taxable_income - 300000) * 0.05

        monthly_tds = round(net_tax / 12.0, 2)

        start_year = int(fy.split("-")[0]) if "-" in fy else 2026
        payslip_stmt = select(func.sum(Payslip.tds), func.sum(Payslip.professional_tax)).where(
            and_(
                Payslip.employee_id == emp.id,
                Payslip.period_year == start_year,
            )
        )
        tds_res = await db.execute(payslip_stmt)
        tds_row = tds_res.first()
        tds_collected_ytd = float(tds_row[0]) if tds_row and tds_row[0] else 0.0
        pt_collected_ytd = float(tds_row[1]) if tds_row and tds_row[1] else (float(emp.professional_tax or 0.0) * 12)

        emp_name = f"{emp.first_name} {emp.last_name}".strip()
        item = {
            "id": str(decl.id) if decl else f"tax-{str(emp.id)}",
            "employee_id": str(emp.id),
            "employee_code": emp.employee_id,
            "employee_name": emp_name,
            "avatar": emp.profile_photo_url,
            "email": emp.company_email or emp.personal_email,
            "department": emp.department or "General",
            "designation": emp.designation or "Employee",
            "location": emp.work_location or emp.branch or "Main Office",
            "pan_number": emp.pan_number or "N/A",
            "financial_year": fy,
            "tax_regime": "NEW" if "NEW" in chosen_regime else "OLD",
            "regime": "NEW_REGIME" if "NEW" in chosen_regime else "OLD_REGIME",
            "gross_salary": gross_salary,
            "taxable_income": taxable_income,
            "exemptions": exemptions,
            "deductions": total_deductions,
            "professional_tax": pt_collected_ytd,
            "verified_investments": float(decl.verified_amount) if decl and decl.verified_amount else total_deductions,
            "declared_investments": total_deductions,
            "estimated_annual_tax": net_tax,
            "net_tax": net_tax,
            "tds_deducted_ytd": tds_collected_ytd,
            "remaining_tds": max(0.0, net_tax - tds_collected_ytd),
            "monthly_tds": monthly_tds,
            "tds": monthly_tds,
            "refund": 0.0,
            "declaration_status": decl_status,
            "status": "VERIFIED" if decl_status == "APPROVED" else decl_status,
            "declaration_id": str(decl.id) if decl else None,
            "rejection_reason": decl.rejection_reason if decl else None,
            "verified_by_hr": decl.verified_by_hr if decl else False,
            "form16_generated": False,
            "last_updated": decl.updated_at.isoformat() if decl and decl.updated_at else (emp.updated_at.isoformat() if emp.updated_at else datetime.now(timezone.utc).isoformat()),
        }
        tax_items.append(item)

    reverse = (sort_dir or "asc").lower() == "desc"
    if sort_by == "name":
        tax_items.sort(key=lambda x: x["employee_name"].lower(), reverse=reverse)
    elif sort_by == "taxable_income":
        tax_items.sort(key=lambda x: x["taxable_income"], reverse=reverse)
    elif sort_by == "net_tax":
        tax_items.sort(key=lambda x: x["net_tax"], reverse=reverse)

    total = len(tax_items)
    pages = max(1, (total + limit - 1) // limit)
    offset = (page - 1) * limit
    paginated_items = tax_items[offset : offset + limit]

    total_emp = len(tax_items)
    taxable_emp_count = len([i for i in tax_items if i["taxable_income"] > 0])
    filed_count = len([i for i in tax_items if i["declaration_status"] in ["APPROVED", "VERIFIED"]])
    pending_count = len([i for i in tax_items if i["declaration_status"] in ["PENDING", "SUBMITTED"]])
    tot_tds = sum(i["net_tax"] for i in tax_items)
    tot_collected = sum(i["tds_deducted_ytd"] for i in tax_items)
    tot_pt = sum(i["professional_tax"] for i in tax_items)
    tot_exemptions = sum(i["exemptions"] for i in tax_items)
    avg_tax = round(tot_tds / total_emp, 2) if total_emp > 0 else 0.0
    compliance_score = round((filed_count / total_emp) * 100) if total_emp > 0 else 0

    new_regime_count = len([i for i in tax_items if i["tax_regime"] == "NEW"])
    old_regime_count = len([i for i in tax_items if i["tax_regime"] == "OLD"])

    summary = {
        "financial_year": fy,
        "total_employees": total_emp,
        "taxable_employees": taxable_emp_count,
        "tax_filed": filed_count,
        "pending_declaration": pending_count,
        "pending_tax_filings": pending_count,
        "total_tax": tot_tds,
        "total_tds": tot_tds,
        "tax_collected": tot_collected,
        "tds_collected": tot_collected,
        "professional_tax": tot_pt,
        "exemptions": tot_exemptions,
        "tax_refund": 0.0,
        "average_tax": avg_tax,
        "compliance_score": compliance_score,
        "total_taxable_payroll": sum(i["taxable_income"] for i in tax_items),
        "total_estimated_tds": tot_tds,
        "tds_collected_ytd": tot_collected,
        "pending_declarations": pending_count,
        "verified_declarations": filed_count,
        "new_regime_count": new_regime_count,
        "old_regime_count": old_regime_count,
        "regime_breakdown": {
            "new_regime": new_regime_count,
            "old_regime": old_regime_count,
        },
    }

    pagination = {
        "total": total,
        "page": page,
        "limit": limit,
        "pages": pages,
        "totalPages": pages,
    }

    return success_response(
        {
            "items": paginated_items,
            "summary": summary,
            "pagination": pagination,
        },
        "Tax records retrieved successfully.",
    )
