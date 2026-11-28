"""Employee Payroll router for Payroll v2."""

from __future__ import annotations

import uuid
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.api.payroll.dependencies import Claims
from app.api.payroll.permissions import _require_admin_or_manager, _role, _uid
from app.db.database import get_db_session
from app.models.employee import Employee
from app.schemas.payroll_v2.compensation import EmployeeCompensationRevisionCreateRequest
from app.schemas.payroll_v2.employee_payroll import RevealBankAccountRequest
from app.services.payroll.compensation_service import CompensationService
from app.services.payroll.employee_payroll_service import EmployeePayrollService
from app.services.payroll.payslip_service import PayslipService

router = APIRouter(tags=["Payroll v2 - Employee Payroll"])


_PAYROLL_SCOPE_EMPLOYEE_COLUMNS = (
    Employee.id,
    Employee.company_id,
    Employee.user_id,
    Employee.is_deleted,
)


def _ok(data: Any, message: str = "Operation successful") -> dict[str, Any]:
    return {"success": True, "data": data, "message": message}


async def _resolve_current_employee(session: AsyncSession, claims: Claims) -> Optional[Employee]:
    user_id = _uid(claims)
    if not user_id:
        return None
    company_id_str = claims.get("company_id") if isinstance(claims, dict) else None
    c_uuid = uuid.UUID(str(company_id_str)) if company_id_str else None
    stmt = (
        select(Employee)
        .options(load_only(*_PAYROLL_SCOPE_EMPLOYEE_COLUMNS))
        .where(Employee.user_id == user_id, Employee.is_deleted == False)  # noqa: E712
    )
    if c_uuid is not None:
        stmt = stmt.where(Employee.company_id == c_uuid)
    emp = (await session.execute(stmt)).scalar_one_or_none()
    if not emp:
        stmt2 = (
            select(Employee)
            .options(load_only(*_PAYROLL_SCOPE_EMPLOYEE_COLUMNS))
            .where(Employee.id == user_id, Employee.is_deleted == False)  # noqa: E712
        )
        if c_uuid is not None:
            stmt2 = stmt2.where(Employee.company_id == c_uuid)
        emp = (await session.execute(stmt2)).scalar_one_or_none()
    return emp


async def _authorize_employee_scope(
    session: AsyncSession, employee_id: uuid.UUID, claims: Claims, *, action_label: str = "records"
) -> Employee:
    from app.api.payroll.permissions import _is_admin_or_manager, _require_tenant_id

    c_uuid = _require_tenant_id(claims, allow_super_admin_global=True)
    if not _is_admin_or_manager(claims):
        caller_emp = await _resolve_current_employee(session, claims)
        if not caller_emp or caller_emp.id != employee_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Forbidden: You can only view your own {action_label}.",
            )
        return caller_emp

    emp_stmt = (
        select(Employee)
        .options(load_only(*_PAYROLL_SCOPE_EMPLOYEE_COLUMNS))
        .where(Employee.id == employee_id, Employee.is_deleted == False)  # noqa: E712
    )
    if c_uuid is not None:
        emp_stmt = emp_stmt.where(Employee.company_id == c_uuid)
    emp = (await session.execute(emp_stmt)).scalar_one_or_none()
    if not emp:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee not found in your organization.",
        )
    return emp


# GET /api/v2/payroll/employee/dashboard
@router.get("/employee/dashboard", summary="Get dashboard summary for current employee")
async def get_current_employee_dashboard(
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    emp = await _resolve_current_employee(db, claims)
    if not emp:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No employee profile linked to the authenticated account.",
        )

    company_id_str = claims.get("company_id") if isinstance(claims, dict) else None
    c_uuid = uuid.UUID(str(company_id_str)) if company_id_str else None
    if c_uuid is not None and emp.company_id != c_uuid:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-organization access denied.")

    data = await EmployeePayrollService.get_dashboard(
        session=db, employee_id=emp.id, company_id=c_uuid or emp.company_id
    )
    return _ok(data, "Employee dashboard retrieved successfully")


# GET /api/v2/payroll/employee/provision-slips
@router.get("/employee/provision-slips", summary="Get provision slips for current employee")
async def get_current_employee_provision_slips(
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    emp = await _resolve_current_employee(db, claims)
    if not emp:
        return _ok([], "No provision slips found")

    slips = await PayslipService.list_provision_slips(session=db, employee_id=emp.id)
    res = [
        {
            "id": str(s.id),
            "slip_number": s.slip_number,
            "employee_id": str(s.employee_id),
            "period_month": s.period_month,
            "period_year": s.period_year,
            "gross_earnings_paise": s.gross_earnings_paise,
            "total_deductions_paise": s.total_deductions_paise,
            "net_pay_paise": s.net_pay_paise,
            "status": s.status,
            "pdf_path": s.pdf_path,
            "breakup": s.breakup,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s in slips
    ]
    return _ok(res, "Provision slips retrieved successfully")


# GET /api/v2/payroll/employees/{employeeId}/compensation
@router.get("/employees/{employeeId}/compensation", summary="Get compensation details for an employee")
async def get_employee_compensation(
    employeeId: uuid.UUID,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    await _authorize_employee_scope(db, employeeId, claims, action_label="compensation details")
    comp = await CompensationService.get_employee_compensation(db, employee_id=employeeId)
    return _ok({
        "id": str(comp.id),
        "employee_id": str(comp.employee_id),
        "company_id": str(comp.company_id) if comp.company_id else None,
        "ctc_annual_paise": comp.ctc_annual_paise,
        "basic_monthly_paise": comp.basic_monthly_paise,
        "hra_monthly_paise": comp.hra_monthly_paise,
        "special_allowance_monthly_paise": comp.special_allowance_monthly_paise,
        "effective_date": str(comp.effective_date),
        "status": comp.status,
        "remarks": comp.remarks,
    }, "Employee compensation retrieved successfully")


# POST /api/v2/payroll/employees/{employeeId}/compensation/revisions
@router.post(
    "/employees/{employeeId}/compensation/revisions",
    status_code=status.HTTP_201_CREATED,
    summary="Create a pending compensation revision for an employee",
)
async def create_employee_compensation_revision(
    employeeId: uuid.UUID,
    payload: EmployeeCompensationRevisionCreateRequest,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    await _authorize_employee_scope(db, employeeId, claims, action_label="compensation revisions")
    user_id = _uid(claims)
    rev = await CompensationService.create_compensation_revision(
        session=db,
        employee_id=employeeId,
        new_ctc_annual_paise=payload.new_ctc_annual_paise,
        effective_date=payload.effective_date,
        reason=payload.reason,
        notes=payload.notes,
        user_id=user_id,
    )
    return _ok({
        "id": str(rev.id),
        "employee_id": str(rev.employee_id),
        "current_ctc_annual_paise": rev.current_ctc_annual_paise,
        "new_ctc_annual_paise": rev.new_ctc_annual_paise,
        "effective_date": str(rev.effective_date),
        "reason": rev.reason,
        "notes": rev.notes,
        "status": rev.status,
    }, "Compensation revision created successfully")


# GET /api/v2/payroll/employees/{employeeId}/payslips
@router.get("/employees/{employeeId}/payslips", summary="Get payslips for an employee")
async def get_employee_payslips_v2(
    employeeId: uuid.UUID,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    from app.api.payroll.permissions import _is_payslip_admin_authorized, _require_tenant_id

    c_uuid = _require_tenant_id(claims)
    if not await _is_payslip_admin_authorized(db, claims, c_uuid):
        caller_emp = await _resolve_current_employee(db, claims)
        if not caller_emp or caller_emp.id != employeeId:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: You can only view your own payslips.",
            )
    else:
        await _authorize_employee_scope(db, employeeId, claims, action_label="payslips")
    res = await PayslipService.get_employee_payslips(db, employee_id=employeeId, page=page, limit=limit)
    items_data = [
        {
            "id": str(p.id),
            "run_id": str(p.payroll_run_id),
            "payroll_run_id": str(p.payroll_run_id),
            "employee_id": str(p.employee_id),
            "payslip_number": p.payslip_number,
            "period": f"{p.period_month:02d}/{p.period_year}",
            "period_month": p.period_month,
            "period_year": p.period_year,
            "paid_days": float(p.paid_days),
            "lop_days": float(p.lop_days),
            "gross_earnings": float(p.gross_earnings),
            "total_deductions": float(p.total_deductions),
            "net_pay": float(p.net_pay),
            "gross_earnings_paise": int(p.gross_earnings * 100),
            "total_deductions_paise": int(p.total_deductions * 100),
            "net_pay_paise": int(p.net_pay * 100),
            "payment_status": p.payment_status,
            "pdf_path": p.pdf_path,
        }
        for p in res["items"]
    ]
    return _ok({
        "items": items_data,
        "total": res["total"],
        "page": res["page"],
        "limit": res["limit"],
    }, "Employee payslips retrieved successfully")


# POST /api/v2/payroll/employees/{employeeId}/reveal-bank-account
@router.post("/employees/{employeeId}/reveal-bank-account", summary="Reveal sensitive bank account details")
async def reveal_employee_bank_account(
    employeeId: uuid.UUID,
    payload: RevealBankAccountRequest,
    claims: Claims = None,
    db: AsyncSession = Depends(get_db_session),
):
    from app.api.payroll.permissions import _require_tenant_id

    _require_admin_or_manager(claims)
    user_id = _uid(claims)
    user_role = _role(claims)
    c_uuid = _require_tenant_id(claims, allow_super_admin_global=True)

    revealed = await EmployeePayrollService.reveal_bank_account(
        session=db,
        employee_id=employeeId,
        reason=payload.reason,
        user_id=user_id,
        user_role=user_role,
        company_id=c_uuid,
    )
    return _ok(revealed, "Bank account details revealed successfully")
