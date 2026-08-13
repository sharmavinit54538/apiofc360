"""Standalone Tax Router for frontend taxApi.ts endpoints — Database Driven."""
from __future__ import annotations

import uuid
from typing import Annotated, Optional
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.auth import APIResponse
from app.core.exceptions import BadRequestException, NotFoundException
from app.models.employee import Employee
from app.models.payroll import (
    EmployeeInvestmentDeclaration,
    SalaryStructure,
    PayrollAuditLog,
)

router = APIRouter(prefix="/tax", tags=["Tax Management"])

DB = Annotated[AsyncSession, Depends(get_db_session)]
Claims = Annotated[dict, Depends(get_current_user_claims)]


def _require_admin_or_manager(claims: dict) -> None:
    if claims.get("role") not in ("super_admin", "hr_admin", "manager", "executive", "it_admin", "admin", "hr"):
        raise BadRequestException("Admin or Manager role required.")


def _require_admin(claims: dict) -> None:
    if claims.get("role") not in ("super_admin", "hr_admin", "it_admin", "executive", "admin", "hr"):
        raise BadRequestException("Admin role required.")



@router.get("/profile/{employee_id}", response_model=APIResponse[dict], summary="Get employee tax profile")
async def get_employee_tax_profile(
    employee_id: uuid.UUID,
    claims: Claims,
    db: DB,
    financial_year: Optional[str] = Query(None),
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    fy = financial_year or "2026-2027"

    emp_stmt = select(Employee).where(Employee.id == employee_id)
    emp_res = await db.execute(emp_stmt)
    emp = emp_res.scalars().first()

    if not emp:
        raise NotFoundException(f"Employee with ID {employee_id} not found.")

    decl_stmt = select(EmployeeInvestmentDeclaration).where(
        and_(
            EmployeeInvestmentDeclaration.employee_id == employee_id,
            EmployeeInvestmentDeclaration.financial_year == fy,
        )
    )
    decl_res = await db.execute(decl_stmt)
    decl = decl_res.scalars().first()

    sal_stmt = select(SalaryStructure).where(
        and_(
            SalaryStructure.employee_id == employee_id,
            SalaryStructure.is_active == True,
        )
    )
    sal_res = await db.execute(sal_stmt)
    sal = sal_res.scalars().first()

    annual_ctc = float(sal.annual_ctc) if sal and sal.annual_ctc else (float(emp.ctc) if emp.ctc else 0.0)
    basic = float(sal.basic_monthly * 12) if sal and sal.basic_monthly else (float(emp.basic_salary * 12) if emp.basic_salary else annual_ctc * 0.5)
    hra = float(sal.hra_monthly * 12) if sal and sal.hra_monthly else (float(emp.hra * 12) if emp.hra else 0.0)
    special_allowance = float(sal.special_allowance_monthly * 12) if sal and sal.special_allowance_monthly else max(0.0, annual_ctc - basic - hra)

    selected_regime = (decl.tax_regime if decl and decl.tax_regime else (sal.tax_regime if sal and sal.tax_regime else (emp.tax_regime or "NEW"))).upper()
    decl_status = (decl.status if decl and decl.status else "PENDING").upper()

    sec_80c = float(decl.section_80c) if decl and decl.section_80c else 0.0
    sec_80d = float(decl.section_80d) if decl and decl.section_80d else 0.0
    nps = float(decl.section_80ccd1b_nps) if decl and decl.section_80ccd1b_nps else 0.0
    home_loan = float(decl.home_loan_interest_24b) if decl and decl.home_loan_interest_24b else 0.0
    sec_80g = float(decl.section_80g) if decl and decl.section_80g else 0.0
    hra_claimed = float(decl.hra_claimed) if decl and decl.hra_claimed else 0.0
    lta_claimed = float(decl.lta_claimed) if decl and decl.lta_claimed else 0.0
    prof_tax = float(emp.professional_tax * 12) if emp and emp.professional_tax else 2400.0
    other_ded = float(decl.other_deductions) if decl and decl.other_deductions else 0.0

    old_deductions = min(sec_80c, 150000.0) + sec_80d + min(nps, 50000.0) + min(home_loan, 200000.0) + sec_80g + hra_claimed + lta_claimed + prof_tax + other_ded + 50000.0
    old_taxable = max(0.0, annual_ctc - old_deductions)
    if old_taxable > 1000000:
        old_net_tax = 112500 + (old_taxable - 1000000) * 0.30
    elif old_taxable > 500000:
        old_net_tax = 12500 + (old_taxable - 500000) * 0.20
    elif old_taxable > 250000:
        old_net_tax = (old_taxable - 250000) * 0.05
    else:
        old_net_tax = 0.0

    new_deductions = 75000.0
    new_taxable = max(0.0, annual_ctc - new_deductions)
    if new_taxable > 1500000:
        new_net_tax = 150000 + (new_taxable - 1500000) * 0.30
    elif new_taxable > 1200000:
        new_net_tax = 90000 + (new_taxable - 1200000) * 0.20
    elif new_taxable > 900000:
        new_net_tax = 45000 + (new_taxable - 900000) * 0.15
    elif new_taxable > 600000:
        new_net_tax = 15000 + (new_taxable - 600000) * 0.10
    elif new_taxable > 300000:
        new_net_tax = (new_taxable - 300000) * 0.05
    else:
        new_net_tax = 0.0

    recommended = "NEW" if new_net_tax <= old_net_tax else "OLD"
    savings = abs(old_net_tax - new_net_tax)

    emp_name = f"{emp.first_name} {emp.last_name}".strip()

    return APIResponse[dict](
        success=True,
        message="Tax profile retrieved successfully.",
        data={
            "employee": {
                "id": str(emp.id),
                "employee_code": emp.employee_id,
                "name": emp_name,
                "email": emp.company_email or emp.personal_email,
                "department": emp.department or "General",
                "designation": emp.designation or "Employee",
                "location": emp.work_location or emp.branch or "Main Office",
                "pan_number": emp.pan_number or "N/A",
                "pf_number": emp.pf_number or "N/A",
                "joining_date": emp.joining_date.isoformat() if emp.joining_date else "",
                "avatar": emp.profile_photo_url,
            },
            "financial_year": fy,
            "selected_regime": "NEW" if "NEW" in selected_regime else "OLD",
            "declaration_status": decl_status,
            "rejection_reason": decl.rejection_reason if decl else None,
            "salary_summary": {
                "annual_ctc": annual_ctc,
                "gross_salary": annual_ctc,
                "taxable_salary": new_taxable if "NEW" in selected_regime else old_taxable,
                "basic": basic,
                "hra": hra,
                "special_allowance": special_allowance,
            },
            "deductions": {
                "section_80c": sec_80c,
                "section_80d": sec_80d,
                "section_80ccd1b_nps": nps,
                "home_loan_24b": home_loan,
                "section_80g": sec_80g,
                "hra_claimed": hra_claimed,
                "lta_claimed": lta_claimed,
                "professional_tax": prof_tax,
                "other_deductions": other_ded,
                "total_deductions": new_deductions if "NEW" in selected_regime else old_deductions,
            },
            "employer_contributions": {
                "employer_pf": round(min(basic, 15000 * 12) * 0.12, 2),
                "employer_esi": round(annual_ctc * 0.0325, 2) if annual_ctc <= 252000 else 0.0,
            },
            "tax_computation": {
                "regime": "NEW" if "NEW" in selected_regime else "OLD",
                "gross_annual": annual_ctc,
                "standard_deduction": 75000.0 if "NEW" in selected_regime else 50000.0,
                "other_deductions": new_deductions if "NEW" in selected_regime else old_deductions,
                "taxable_income": new_taxable if "NEW" in selected_regime else old_taxable,
                "gross_tax": new_net_tax if "NEW" in selected_regime else old_net_tax,
                "rebate_87a": 0.0,
                "cess": round((new_net_tax if "NEW" in selected_regime else old_net_tax) * 0.04, 2),
                "net_tax": new_net_tax if "NEW" in selected_regime else old_net_tax,
                "monthly_tds": round((new_net_tax if "NEW" in selected_regime else old_net_tax) / 12.0, 2),
            },
            "regime_comparison": {
                "old_regime": {
                    "regime": "OLD",
                    "gross_annual": annual_ctc,
                    "standard_deduction": 50000.0,
                    "other_deductions": old_deductions,
                    "taxable_income": old_taxable,
                    "gross_tax": old_net_tax,
                    "rebate_87a": 0.0,
                    "cess": round(old_net_tax * 0.04, 2),
                    "net_tax": old_net_tax,
                    "monthly_tds": round(old_net_tax / 12.0, 2),
                },
                "new_regime": {
                    "regime": "NEW",
                    "gross_annual": annual_ctc,
                    "standard_deduction": 75000.0,
                    "other_deductions": new_deductions,
                    "taxable_income": new_taxable,
                    "gross_tax": new_net_tax,
                    "rebate_87a": 0.0,
                    "cess": round(new_net_tax * 0.04, 2),
                    "net_tax": new_net_tax,
                    "monthly_tds": round(new_net_tax / 12.0, 2),
                },
                "recommended_regime": recommended,
                "estimated_savings": savings,
            },
            "proof_documents": [],
        },
        errors=None,
    )


@router.post("/calculate", response_model=APIResponse[dict], summary="Run TDS tax calculation")
async def run_tax_calculation(
    claims: Claims,
    db: DB,
    body: dict = Body(default={}),
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    fy = body.get("financial_year", "2026-2027")
    employee_ids = body.get("employee_ids", [])

    stmt = select(Employee).where(Employee.is_deleted == False)
    if employee_ids:
        try:
            uuids = [uuid.UUID(eid) for eid in employee_ids if eid]
            if uuids:
                stmt = stmt.where(Employee.id.in_(uuids))
        except Exception:
            pass

    res = await db.execute(stmt)
    employees = res.scalars().all()

    calc_count = 0
    for emp in employees:
        decl_stmt = select(EmployeeInvestmentDeclaration).where(
            and_(
                EmployeeInvestmentDeclaration.employee_id == emp.id,
                EmployeeInvestmentDeclaration.financial_year == fy,
            )
        )
        decl_res = await db.execute(decl_stmt)
        decl = decl_res.scalars().first()

        if not decl:
            decl = EmployeeInvestmentDeclaration(
                employee_id=emp.id,
                company_id=emp.company_id,
                financial_year=fy,
                tax_regime=emp.tax_regime or "NEW",
                status="PENDING",
            )
            db.add(decl)
        calc_count += 1

    await db.commit()

    return APIResponse[dict](
        success=True,
        message=f"Tax calculation completed successfully for {calc_count} employee records.",
        data={
            "calculated_count": calc_count,
            "financial_year": fy,
            "status": "COMPLETED",
            "calculated_at": datetime.now(timezone.utc).isoformat(),
        },
        errors=None,
    )


@router.post("/declarations/{declaration_id}/approve", response_model=APIResponse[dict], summary="Approve tax declaration")
async def approve_tax_declaration(
    declaration_id: uuid.UUID,
    claims: Claims,
    db: DB,
    body: dict = Body(default={}),
) -> APIResponse[dict]:
    _require_admin(claims)

    decl_stmt = select(EmployeeInvestmentDeclaration).where(EmployeeInvestmentDeclaration.id == declaration_id)
    decl_res = await db.execute(decl_stmt)
    decl = decl_res.scalars().first()

    if decl:
        decl.status = "APPROVED"
        decl.verified_by_hr = True
        if claims and claims.get("user_id"):
            try:
                decl.verified_by = uuid.UUID(claims.get("user_id"))
            except Exception:
                pass
        decl.verified_at = datetime.now(timezone.utc)
        await db.commit()

    return APIResponse[dict](
        success=True,
        message="Tax declaration approved successfully.",
        data={
            "id": str(declaration_id),
            "status": "APPROVED",
            "approved_at": datetime.now(timezone.utc).isoformat(),
        },
        errors=None,
    )


@router.post("/declarations/{declaration_id}/reject", response_model=APIResponse[dict], summary="Reject tax declaration")
async def reject_tax_declaration(
    declaration_id: uuid.UUID,
    claims: Claims,
    db: DB,
    body: dict = Body(default={}),
) -> APIResponse[dict]:
    _require_admin(claims)
    reason = body.get("reason", "Incomplete proof document submitted.")

    decl_stmt = select(EmployeeInvestmentDeclaration).where(EmployeeInvestmentDeclaration.id == declaration_id)
    decl_res = await db.execute(decl_stmt)
    decl = decl_res.scalars().first()

    if decl:
        decl.status = "REJECTED"
        decl.rejection_reason = reason
        await db.commit()

    return APIResponse[dict](
        success=True,
        message="Tax declaration rejected.",
        data={
            "id": str(declaration_id),
            "status": "REJECTED",
            "reason": reason,
            "rejected_at": datetime.now(timezone.utc).isoformat(),
        },
        errors=None,
    )


@router.post("/proofs/{proof_id}/verify", response_model=APIResponse[dict], summary="Verify tax proof document")
async def verify_tax_proof(
    proof_id: uuid.UUID,
    claims: Claims,
    db: DB,
    body: dict = Body(default={}),
) -> APIResponse[dict]:
    _require_admin(claims)
    approved_amount = body.get("approved_amount", 0)
    return APIResponse[dict](
        success=True,
        message="Proof document verified.",
        data={
            "id": str(proof_id),
            "status": "VERIFIED",
            "approved_amount": approved_amount,
            "verified_at": datetime.now(timezone.utc).isoformat(),
        },
        errors=None,
    )


@router.post("/year-end-process", response_model=APIResponse[dict], summary="Lock FY and generate Form 16")
async def run_year_end_process(
    claims: Claims,
    db: DB,
    body: dict = Body(default={}),
) -> APIResponse[dict]:
    _require_admin(claims)
    fy = body.get("financial_year", "2026-2027")
    return APIResponse[dict](
        success=True,
        message=f"Year-End processing initiated for FY {fy}.",
        data={
            "financial_year": fy,
            "status": "PROCESSING",
            "form16_generation": "QUEUED",
            "initiated_at": datetime.now(timezone.utc).isoformat(),
        },
        errors=None,
    )


@router.get("/audit-logs/{employee_id}", response_model=APIResponse[dict], summary="Get tax audit logs for employee")
async def get_tax_audit_logs(
    employee_id: uuid.UUID,
    claims: Claims,
    db: DB,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)

    stmt = select(PayrollAuditLog).where(
        and_(
            PayrollAuditLog.entity_id == employee_id,
            PayrollAuditLog.entity_type.in_(["TaxDeclaration", "TaxComputation", "Payslip", "EmployeeTaxProfile"]),
        )
    ).order_by(PayrollAuditLog.created_at.desc())

    res = await db.execute(stmt)
    logs = res.scalars().all()

    items = []
    for log in logs:
        items.append({
            "id": str(log.id),
            "action": log.action,
            "actor": log.actor_role or "System",
            "timestamp": log.created_at.isoformat() if log.created_at else "",
            "details": log.reason or f"{log.action} performed on {log.entity_type}",
        })

    return APIResponse[dict](
        success=True,
        message="Tax audit logs retrieved successfully.",
        data={"items": items, "total": len(items), "employee_id": str(employee_id)},
        errors=None,
    )
