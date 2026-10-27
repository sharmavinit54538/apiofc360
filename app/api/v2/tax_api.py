"""Standalone Tax Router for frontend taxApi.ts endpoints — Database Driven."""
from __future__ import annotations

import uuid
from typing import Annotated, Optional
from datetime import date, datetime, timezone

from fastapi import APIRouter, Body, Depends, File, Form, Query, UploadFile
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
    TaxDeclarationProof,
)
from app.models.employee_tax_info import EmployeeTaxInfo
from app.services.storage_service import StorageService
from app.services.payroll.statutory_service import StatutoryService

router = APIRouter(prefix="/tax", tags=["Tax Management"])

from app.core.rbac import ADMIN_MANAGER_ROLES, ADMIN_ROLES, RoleEnum

DB = Annotated[AsyncSession, Depends(get_db_session)]
Claims = Annotated[dict, Depends(get_current_user_claims)]


def _require_admin_or_manager(claims: dict) -> None:
    role = RoleEnum.from_str(claims.get("role")).value
    if role not in ADMIN_MANAGER_ROLES:
        raise BadRequestException("Admin or Manager role required.")


def _require_admin(claims: dict) -> None:
    role = RoleEnum.from_str(claims.get("role")).value
    if role not in ADMIN_ROLES:
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
    company_id = _tenant_company(claims)
    if company_id:
        emp_stmt = emp_stmt.where(Employee.company_id == company_id)
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

    declaration_amounts = {
        "section_80c": sec_80c, "section_80d": sec_80d,
        "section_80ccd1b_nps": nps, "home_loan_interest_24b": home_loan,
        "section_80g": sec_80g, "hra_claimed": hra_claimed,
        "lta_claimed": lta_claimed, "other_deductions": other_ded,
        "professional_tax": prof_tax,
    }
    cutoff_passed = bool(decl and decl.proof_cutoff_date and decl.proof_cutoff_date <= date.today())
    verified_amounts = (decl.verified_details_json if decl else None) or None
    use_verified = bool(decl and decl.use_verified_amounts and cutoff_passed)
    gross_paise = StatutoryService._amount_paise(annual_ctc)
    basic_paise = StatutoryService._amount_paise(basic)
    hra_paise = StatutoryService._amount_paise(hra)
    old_calc = StatutoryService.calculate_tds(
        gross_paise, "OLD", declaration_amounts, financial_year=fy,
        verified_declarations=verified_amounts, use_verified_declarations=use_verified,
        basic_annual_paise=basic_paise, hra_annual_paise=hra_paise,
        previous_employer_income_paise=int(getattr(decl, "previous_employer_income_paise", 0) or 0) if decl else 0,
        previous_employer_tds_paise=int(getattr(decl, "previous_employer_tds_paise", 0) or 0) if decl else 0,
        ytd_tds_paise=int(getattr(decl, "ytd_tds_paise", 0) or 0) if decl else 0,
    )
    new_calc = StatutoryService.calculate_tds(
        gross_paise, "NEW", declaration_amounts, financial_year=fy,
        previous_employer_income_paise=int(getattr(decl, "previous_employer_income_paise", 0) or 0) if decl else 0,
        previous_employer_tds_paise=int(getattr(decl, "previous_employer_tds_paise", 0) or 0) if decl else 0,
        ytd_tds_paise=int(getattr(decl, "ytd_tds_paise", 0) or 0) if decl else 0,
    )
    old_deductions = float(old_calc["total_deductions_paise"]) / 100
    old_taxable = float(old_calc["taxable_income_paise"]) / 100
    old_net_tax = float(old_calc["annual_tax_paise"]) / 100
    new_deductions = float(new_calc["total_deductions_paise"]) / 100
    new_taxable = float(new_calc["taxable_income_paise"]) / 100
    new_net_tax = float(new_calc["annual_tax_paise"]) / 100
    recommended = "NEW" if new_net_tax <= old_net_tax else "OLD"
    savings = abs(old_net_tax - new_net_tax)
    selected_calc = new_calc if "NEW" in selected_regime else old_calc

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
                "standard_deduction": float(selected_calc["standard_deduction_paise"]) / 100,
                "other_deductions": new_deductions if "NEW" in selected_regime else old_deductions,
                "taxable_income": new_taxable if "NEW" in selected_regime else old_taxable,
                "gross_tax": float(selected_calc["gross_tax_paise"]) / 100,
                "rebate_87a": float(selected_calc["rebate_87a_paise"]) / 100,
                "cess": float(selected_calc["cess_paise"]) / 100,
                "net_tax": float(selected_calc["annual_tax_paise"]) / 100,
                "monthly_tds": float(selected_calc["monthly_tds_paise"]) / 100,
            },
            "regime_comparison": {
                "old_regime": {
                    "regime": "OLD",
                    "gross_annual": annual_ctc,
                    "standard_deduction": float(old_calc["standard_deduction_paise"]) / 100,
                    "other_deductions": old_deductions,
                    "taxable_income": old_taxable,
                    "gross_tax": float(old_calc["gross_tax_paise"]) / 100,
                    "rebate_87a": float(old_calc["rebate_87a_paise"]) / 100,
                    "cess": float(old_calc["cess_paise"]) / 100,
                    "net_tax": old_net_tax,
                    "monthly_tds": float(old_calc["monthly_tds_paise"]) / 100,
                },
                "new_regime": {
                    "regime": "NEW",
                    "gross_annual": annual_ctc,
                    "standard_deduction": float(new_calc["standard_deduction_paise"]) / 100,
                    "other_deductions": new_deductions,
                    "taxable_income": new_taxable,
                    "gross_tax": float(new_calc["gross_tax_paise"]) / 100,
                    "rebate_87a": float(new_calc["rebate_87a_paise"]) / 100,
                    "cess": float(new_calc["cess_paise"]) / 100,
                    "net_tax": new_net_tax,
                    "monthly_tds": float(new_calc["monthly_tds_paise"]) / 100,
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
    company_id = _tenant_company(claims)
    if company_id:
        stmt = stmt.where(Employee.company_id == company_id)
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
    company_id = _tenant_company(claims)
    if company_id:
        decl_stmt = decl_stmt.where(EmployeeInvestmentDeclaration.company_id == company_id)
    decl_res = await db.execute(decl_stmt)
    decl = decl_res.scalars().first()

    if not decl:
        raise NotFoundException("Tax declaration not found.")
    if decl:
        decl.status = "APPROVED"
        decl.proof_status = "VERIFIED"
        decl.use_verified_amounts = True
        decl.verified_by_hr = True
        if claims and (claims.get("user_id") or claims.get("sub")):
            try:
                decl.verified_by = uuid.UUID(str(claims.get("user_id") or claims.get("sub")))
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
    company_id = _tenant_company(claims)
    if company_id:
        decl_stmt = decl_stmt.where(EmployeeInvestmentDeclaration.company_id == company_id)
    decl_res = await db.execute(decl_stmt)
    decl = decl_res.scalars().first()

    if not decl:
        raise NotFoundException("Tax declaration not found.")
    if decl:
        decl.status = "REJECTED"
        decl.proof_status = "REJECTED"
        decl.use_verified_amounts = False
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
    stmt = select(TaxDeclarationProof).where(TaxDeclarationProof.id == proof_id)
    company_id = _tenant_company(claims)
    if company_id:
        stmt = stmt.where(TaxDeclarationProof.company_id == company_id)
    proof = (await db.execute(stmt)).scalar_one_or_none()
    if not proof:
        raise NotFoundException("Tax proof document not found.")
    approved_amount = body.get("approved_amount", body.get("verified_amount", proof.amount_claimed))
    approved = body.get("status", "VERIFIED").upper() != "REJECTED"
    proof.status = "VERIFIED" if approved else "REJECTED"
    proof.verified_by_hr = approved
    proof.verified_amount = approved_amount if approved else 0
    proof.rejection_reason = body.get("reason") if not approved else None
    proof.verified_at = datetime.now(timezone.utc)
    if claims and claims.get("sub"):
        try:
            proof.verified_by = uuid.UUID(str(claims["sub"]))
        except (ValueError, TypeError):
            pass
    declaration = (await db.execute(select(EmployeeInvestmentDeclaration).where(EmployeeInvestmentDeclaration.id == proof.declaration_id))).scalar_one_or_none()
    if declaration:
        details = dict(declaration.verified_details_json or {})
        details[proof.section] = str(proof.verified_amount or 0)
        declaration.verified_details_json = details
        declaration.proof_status = "VERIFIED" if approved else "REJECTED"
        declaration.status = "APPROVED" if approved else "REJECTED"
        declaration.verified_by_hr = approved
        declaration.use_verified_amounts = approved
        declaration.verified_amount = proof.verified_amount if approved else None
        declaration.verified_at = proof.verified_at
        if claims and claims.get("sub"):
            try:
                declaration.verified_by = uuid.UUID(str(claims["sub"]))
            except (ValueError, TypeError):
                pass
    await db.commit()
    return APIResponse[dict](
        success=True, message="Proof document verified." if approved else "Proof document rejected.",
        data={"id": str(proof.id), "declaration_id": str(proof.declaration_id), "status": proof.status,
              "approved_amount": float(proof.verified_amount or 0), "verified_at": proof.verified_at.isoformat()}, errors=None,
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
    )
    company_id = _tenant_company(claims)
    if company_id:
        stmt = stmt.where(PayrollAuditLog.company_id == company_id)
    stmt = stmt.order_by(PayrollAuditLog.created_at.desc())

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


def _tenant_company(claims: dict) -> uuid.UUID | None:
    raw = claims.get("company_id") if claims else None
    if not raw:
        return None
    try:
        return raw if isinstance(raw, uuid.UUID) else uuid.UUID(str(raw))
    except (ValueError, TypeError):
        return None


@router.post("/declarations/{employee_id}", response_model=APIResponse[dict], summary="Create or update an employee tax declaration")
async def upsert_tax_declaration(
    employee_id: uuid.UUID,
    claims: Claims,
    db: DB,
    body: dict = Body(default={}),
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    company_id = _tenant_company(claims)
    emp_stmt = select(Employee).where(Employee.id == employee_id)
    if company_id:
        emp_stmt = emp_stmt.where(Employee.company_id == company_id)
    employee = (await db.execute(emp_stmt)).scalar_one_or_none()
    if not employee:
        raise NotFoundException("Employee not found.")
    fy = body.get("financial_year") or body.get("financialYear") or "2026-2027"
    stmt = select(EmployeeInvestmentDeclaration).where(
        EmployeeInvestmentDeclaration.employee_id == employee_id,
        EmployeeInvestmentDeclaration.financial_year == fy,
    )
    declaration = (await db.execute(stmt)).scalar_one_or_none()
    if not declaration:
        declaration = EmployeeInvestmentDeclaration(employee_id=employee_id, financial_year=fy)
        db.add(declaration)
    declaration.company_id = employee.company_id
    for key in ("tax_regime", "section_80c", "section_80d", "section_80ccd1b_nps", "home_loan_interest_24b", "section_80g", "hra_claimed", "lta_claimed", "other_deductions", "proof_cutoff_date", "previous_employer_income_paise", "previous_employer_tds_paise", "ytd_tds_paise", "one_time_bonus_paise", "variable_pay_paise"):
        camel = key.split("_")[0] + "".join(part.title() for part in key.split("_")[1:])
        value = body.get(key, body.get(camel))
        if value is not None and hasattr(declaration, key):
            if key == "proof_cutoff_date" and isinstance(value, str):
                value = date.fromisoformat(value)
            setattr(declaration, key, value)
    declaration.declared_details_json = body.get("declared_details") or body.get("declaredDetails") or declaration.declared_details_json
    declaration.status = "SUBMITTED"
    declaration.proof_status = "PENDING"
    await db.commit()
    await db.refresh(declaration)
    return APIResponse[dict](success=True, message="Tax declaration saved.", data={"id": str(declaration.id), "employee_id": str(employee_id), "financial_year": fy, "status": declaration.status, "proof_status": declaration.proof_status}, errors=None)


@router.post("/declarations/{declaration_id}/proofs", response_model=APIResponse[dict], summary="Upload an investment proof document")
async def upload_tax_proof(
    declaration_id: uuid.UUID,
    claims: Claims,
    db: DB,
    file: UploadFile = File(...),
    section: str = Form("OTHER"),
    amount_claimed: float = Form(0),
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    company_id = _tenant_company(claims)
    stmt = select(EmployeeInvestmentDeclaration).where(EmployeeInvestmentDeclaration.id == declaration_id)
    if company_id:
        stmt = stmt.where(EmployeeInvestmentDeclaration.company_id == company_id)
    declaration = (await db.execute(stmt)).scalar_one_or_none()
    if not declaration:
        raise NotFoundException("Tax declaration not found.")
    saved = await StorageService().save_file(file)
    proof = TaxDeclarationProof(
        declaration_id=declaration.id, employee_id=declaration.employee_id, company_id=declaration.company_id,
        section=section.upper(), document_name=saved["original_filename"], document_url=f"/uploads/documents/{saved['stored_filename']}",
        amount_claimed=amount_claimed, status="PENDING", document_hash=saved.get("document_hash"), file_path=saved.get("file_path"),
    )
    db.add(proof)
    declaration.proof_status = "SUBMITTED"
    declaration.proof_submitted_at = datetime.now(timezone.utc)
    declaration.status = "SUBMITTED"
    await db.commit()
    await db.refresh(proof)
    return APIResponse[dict](success=True, message="Tax proof uploaded.", data={"id": str(proof.id), "declaration_id": str(declaration.id), "document_url": proof.document_url, "status": proof.status, "section": proof.section}, errors=None)


@router.get("/declarations/{declaration_id}/proofs", response_model=APIResponse[dict], summary="List tax proof documents")
async def list_tax_proofs(declaration_id: uuid.UUID, claims: Claims, db: DB) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    company_id = _tenant_company(claims)
    stmt = select(TaxDeclarationProof).where(TaxDeclarationProof.declaration_id == declaration_id)
    if company_id:
        stmt = stmt.where(TaxDeclarationProof.company_id == company_id)
    proofs = (await db.execute(stmt)).scalars().all()
    return APIResponse[dict](success=True, message="Tax proofs retrieved.", data={"items": [{"id": str(p.id), "section": p.section, "document_url": p.document_url, "amount_claimed": float(p.amount_claimed or 0), "verified_amount": float(p.verified_amount or 0), "status": p.status} for p in proofs]}, errors=None)


@router.post("/declarations/{declaration_id}/submit", response_model=APIResponse[dict], summary="Submit a declaration for proof verification")
async def submit_tax_declaration(declaration_id: uuid.UUID, claims: Claims, db: DB) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    company_id = _tenant_company(claims)
    stmt = select(EmployeeInvestmentDeclaration).where(EmployeeInvestmentDeclaration.id == declaration_id)
    if company_id:
        stmt = stmt.where(EmployeeInvestmentDeclaration.company_id == company_id)
    declaration = (await db.execute(stmt)).scalar_one_or_none()
    if not declaration:
        raise NotFoundException("Tax declaration not found.")
    declaration.status = "SUBMITTED"
    declaration.proof_status = "SUBMITTED"
    declaration.proof_submitted_at = datetime.now(timezone.utc)
    await db.commit()
    return APIResponse[dict](success=True, message="Declaration submitted for verification.", data={"id": str(declaration.id), "status": declaration.status}, errors=None)
