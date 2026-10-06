"""Service for Payroll Runs (v1 & v2).

Handles payroll execution, calculations in integer paise, validation checks,
and state machine transitions (approve, finalize, reject, cancel, send-back).
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.employee import Employee
from app.models.payroll import (
    PayrollAttendanceInput,
    PayrollRun,
    Payslip,
    SalaryStructure,
    StatutoryComplianceConfig,
)
from app.models.payroll_models import (
    Compensation,
    PayrollPeriod,
    PayrollRunEmployee,
    VariableInput,
)
from app.services.payroll.audit_service import PayrollAuditService

logger = logging.getLogger(__name__)


class PayrollRunService:
    """Core domain logic for payroll runs."""

    @classmethod
    async def get_run(cls, session: AsyncSession, run_id: uuid.UUID) -> PayrollRun:
        stmt = (
            select(PayrollRun)
            .options(selectinload(PayrollRun.period))
            .where(PayrollRun.id == run_id)
        )
        res = await session.execute(stmt)
        run = res.scalar_one_or_none()
        if not run:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Payroll run '{run_id}' not found.",
            )
        return run

    @classmethod
    async def create_run(
        cls,
        session: AsyncSession,
        period_id: uuid.UUID,
        company_id: Optional[uuid.UUID] = None,
        user_id: Optional[uuid.UUID] = None,
    ) -> PayrollRun:
        # Verify period exists
        period_stmt = select(PayrollPeriod).where(PayrollPeriod.id == period_id)
        period = (await session.execute(period_stmt)).scalar_one_or_none()
        if not period:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Payroll period '{period_id}' not found.",
            )

        target_company_id = company_id or period.company_id
        run_number = f"PR-{period.period_year}{period.period_month:02d}-{uuid.uuid4().hex[:4].upper()}"

        run = PayrollRun(
            id=uuid.uuid4(),
            company_id=target_company_id,
            period_id=period.id,
            period_month=period.period_month,
            period_year=period.period_year,
            run_number=run_number,
            status="DRAFT",
            total_employees=0,
            total_gross=Decimal("0.00"),
            total_deductions=Decimal("0.00"),
            total_net=Decimal("0.00"),
            total_gross_paise=0,
            total_deductions_paise=0,
            total_net_paise=0,
            validation_status="PENDING",
            is_locked=False,
            run_by=user_id,
            run_at=datetime.now(),
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)

        # Trigger automatic initial validation
        await cls.validate_run(session, run.id)
        return run

    @classmethod
    async def list_run_employees(
        cls,
        session: AsyncSession,
        run_id: uuid.UUID,
        page: int = 1,
        limit: int = 50,
        search: Optional[str] = None,
        department: Optional[str] = None,
        validation_status: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_dir: Optional[str] = "asc",
    ) -> dict[str, Any]:
        stmt = (
            select(PayrollRunEmployee)
            .join(Employee, PayrollRunEmployee.employee_id == Employee.id)
            .where(PayrollRunEmployee.run_id == run_id)
        )

        if search:
            stmt = stmt.where(
                or_(
                    Employee.first_name.ilike(f"%{search}%"),
                    Employee.last_name.ilike(f"%{search}%"),
                    Employee.employee_id.ilike(f"%{search}%"),
                )
            )
        if department:
            stmt = stmt.where(Employee.department == department)
        if validation_status:
            stmt = stmt.where(PayrollRunEmployee.validation_status == validation_status.upper())

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await session.execute(count_stmt)).scalar() or 0

        # Sorting
        order_col = PayrollRunEmployee.created_at
        if sort_by == "netPay":
            order_col = PayrollRunEmployee.net_pay_paise
        elif sort_by == "name":
            order_col = Employee.first_name

        if (sort_dir or "").lower() == "desc":
            stmt = stmt.order_by(desc(order_col))
        else:
            stmt = stmt.order_by(order_col)

        offset = max(0, (page - 1) * limit)
        stmt = stmt.offset(offset).limit(limit)

        result = await session.execute(stmt)
        items = result.scalars().all()

        return {
            "items": items,
            "total": total,
            "page": page,
            "limit": limit,
        }

    @classmethod
    async def get_run_employee(
        cls, session: AsyncSession, run_id: uuid.UUID, employee_id: uuid.UUID
    ) -> PayrollRunEmployee:
        stmt = select(PayrollRunEmployee).where(
            PayrollRunEmployee.run_id == run_id,
            PayrollRunEmployee.employee_id == employee_id,
        )
        res = await session.execute(stmt)
        item = res.scalar_one_or_none()
        if not item:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Employee payroll record not found for this run.",
            )
        return item

    @classmethod
    async def approve_run(
        cls,
        session: AsyncSession,
        run_id: uuid.UUID,
        comments: Optional[str] = None,
        user_id: Optional[uuid.UUID] = None,
        user_role: Optional[str] = None,
    ) -> PayrollRun:
        run = await cls.get_run(session, run_id)
        if run.status in ("APPROVED", "FINALIZED", "PAID"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Run cannot be approved in '{run.status}' status.",
            )

        old_status = run.status
        run.status = "APPROVED"
        run.approved_by = user_id
        run.approved_at = datetime.now()
        run.comments = comments

        await PayrollAuditService.log_event(
            session=session,
            entity_type="PayrollRun",
            entity_id=run.id,
            action="APPROVE",
            company_id=run.company_id,
            actor_id=user_id,
            actor_role=user_role,
            before_status=old_status,
            after_status="APPROVED",
            reason=comments or "Approved payroll run",
        )
        await session.commit()
        await session.refresh(run)
        return run

    @classmethod
    async def finalize_run(
        cls,
        session: AsyncSession,
        run_id: uuid.UUID,
        notes: Optional[str] = None,
        lock: bool = True,
        user_id: Optional[uuid.UUID] = None,
        user_role: Optional[str] = None,
    ) -> PayrollRun:
        run = await cls.get_run(session, run_id)
        if run.status not in ("APPROVED", "PROCESSED", "DRAFT"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Run in '{run.status}' state cannot be finalized.",
            )

        old_status = run.status
        run.status = "FINALIZED"
        run.is_locked = lock
        run.finalized_by = user_id
        run.finalized_at = datetime.now()
        run.notes = notes

        await PayrollAuditService.log_event(
            session=session,
            entity_type="PayrollRun",
            entity_id=run.id,
            action="FINALIZE",
            company_id=run.company_id,
            actor_id=user_id,
            actor_role=user_role,
            before_status=old_status,
            after_status="FINALIZED",
            reason=notes or "Finalized payroll run",
        )
        await session.commit()
        await session.refresh(run)
        return run

    @classmethod
    async def reject_run(
        cls,
        session: AsyncSession,
        run_id: uuid.UUID,
        reason: str,
        comments: Optional[str] = None,
        user_id: Optional[uuid.UUID] = None,
        user_role: Optional[str] = None,
    ) -> PayrollRun:
        run = await cls.get_run(session, run_id)
        if run.status in ("FINALIZED", "PAID"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Finalized or disbursed runs cannot be rejected.",
            )

        old_status = run.status
        run.status = "REJECTED"
        run.rejected_by = user_id
        run.rejected_at = datetime.now()
        run.rejection_reason = reason
        run.comments = comments

        await PayrollAuditService.log_event(
            session=session,
            entity_type="PayrollRun",
            entity_id=run.id,
            action="REJECT",
            company_id=run.company_id,
            actor_id=user_id,
            actor_role=user_role,
            before_status=old_status,
            after_status="REJECTED",
            reason=reason,
        )
        await session.commit()
        await session.refresh(run)
        return run

    @classmethod
    async def cancel_run(
        cls,
        session: AsyncSession,
        run_id: uuid.UUID,
        user_id: Optional[uuid.UUID] = None,
        user_role: Optional[str] = None,
    ) -> PayrollRun:
        run = await cls.get_run(session, run_id)
        if run.status in ("FINALIZED", "PAID"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Finalized or disbursed payroll runs cannot be cancelled.",
            )

        old_status = run.status
        run.status = "CANCELLED"

        await PayrollAuditService.log_event(
            session=session,
            entity_type="PayrollRun",
            entity_id=run.id,
            action="CANCEL",
            company_id=run.company_id,
            actor_id=user_id,
            actor_role=user_role,
            before_status=old_status,
            after_status="CANCELLED",
        )
        await session.commit()
        await session.refresh(run)
        return run

    @classmethod
    async def send_back_run(
        cls,
        session: AsyncSession,
        run_id: uuid.UUID,
        reason: Optional[str] = None,
        comments: Optional[str] = None,
        user_id: Optional[uuid.UUID] = None,
        user_role: Optional[str] = None,
    ) -> PayrollRun:
        run = await cls.get_run(session, run_id)
        if run.status in ("FINALIZED", "PAID"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Finalized runs cannot be sent back.",
            )

        old_status = run.status
        run.status = "DRAFT"
        run.sent_back_by = user_id
        run.sent_back_at = datetime.now()
        run.sent_back_reason = reason
        run.comments = comments

        await PayrollAuditService.log_event(
            session=session,
            entity_type="PayrollRun",
            entity_id=run.id,
            action="SEND_BACK",
            company_id=run.company_id,
            actor_id=user_id,
            actor_role=user_role,
            before_status=old_status,
            after_status="DRAFT",
            reason=reason,
        )
        await session.commit()
        await session.refresh(run)
        return run

    @classmethod
    async def retry_run(
        cls,
        session: AsyncSession,
        run_id: uuid.UUID,
        user_id: Optional[uuid.UUID] = None,
        user_role: Optional[str] = None,
    ) -> PayrollRun:
        run = await cls.get_run(session, run_id)
        old_status = run.status
        run.status = "PROCESSING"

        await PayrollAuditService.log_event(
            session=session,
            entity_type="PayrollRun",
            entity_id=run.id,
            action="RETRY",
            company_id=run.company_id,
            actor_id=user_id,
            actor_role=user_role,
            before_status=old_status,
            after_status="PROCESSING",
        )
        await session.commit()

        # Re-execute calculation engine
        return await cls.execute_run_calculation(session, run_id)

    @classmethod
    async def delete_run(cls, session: AsyncSession, run_id: uuid.UUID) -> dict[str, str]:
        run = await cls.get_run(session, run_id)
        if run.status in ("FINALIZED", "PAID"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Finalized or disubursed payroll runs cannot be deleted.",
            )
        await session.delete(run)
        await session.commit()
        return {"message": f"Payroll run {run_id} deleted successfully."}

    @classmethod
    async def validate_run(cls, session: AsyncSession, run_id: uuid.UUID) -> dict[str, Any]:
        """Perform pre-check validations on all eligible employees for this run."""
        run = await cls.get_run(session, run_id)

        # Fetch active employees
        emp_stmt = select(Employee).where(Employee.is_deleted == False)
        if run.company_id:
            emp_stmt = emp_stmt.where(Employee.company_id == run.company_id)
        employees = (await session.execute(emp_stmt)).scalars().all()

        issues: list[dict[str, Any]] = []
        for emp in employees:
            emp_issues = []
            if not emp.pan_number:
                emp_issues.append("Missing PAN number")
            if not emp.bank_accounts and not getattr(emp, "bank_account_number", None):
                emp_issues.append("Missing primary bank account")

            # Check if compensation or salary structure exists
            comp_stmt = select(Compensation).where(
                Compensation.employee_id == emp.id, Compensation.status == "ACTIVE"
            )
            has_comp = (await session.execute(comp_stmt)).scalar_one_or_none()
            if not has_comp:
                # Fallback check salary structure
                sal_stmt = select(SalaryStructure).where(
                    SalaryStructure.employee_id == emp.id, SalaryStructure.is_active == True
                )
                has_sal = (await session.execute(sal_stmt)).scalar_one_or_none()
                if not has_sal:
                    emp_issues.append("No active Compensation or Salary Structure defined")

            if emp_issues:
                issues.append({
                    "employee_id": str(emp.id),
                    "name": f"{emp.first_name} {emp.last_name}".strip(),
                    "issues": emp_issues,
                })

        run.validation_status = "WARNING" if issues else "VALID"
        run.validation_errors = issues
        await session.commit()

        return {
            "run_id": str(run_id),
            "validation_status": run.validation_status,
            "total_employees": len(employees),
            "issues_count": len(issues),
            "issues": issues,
        }

    @classmethod
    async def revalidate_run(cls, session: AsyncSession, run_id: uuid.UUID) -> dict[str, Any]:
        return await cls.validate_run(session, run_id)

    @classmethod
    async def execute_run_calculation(cls, session: AsyncSession, run_id: uuid.UUID) -> PayrollRun:
        """Core Payroll Calculation Engine in integer paise."""
        run = await cls.get_run(session, run_id)
        run.status = "PROCESSING"
        await session.commit()

        # Fetch active config
        cfg_stmt = select(StatutoryComplianceConfig).where(StatutoryComplianceConfig.is_active == True)
        if run.company_id:
            cfg_stmt = cfg_stmt.where(
                or_(
                    StatutoryComplianceConfig.company_id == run.company_id,
                    StatutoryComplianceConfig.company_id.is_(None),
                )
            )
        config = (await session.execute(cfg_stmt)).scalar_one_or_none() or StatutoryComplianceConfig()

        # Fetch all active employees
        emp_stmt = select(Employee).where(Employee.is_deleted == False)
        if run.company_id:
            emp_stmt = emp_stmt.where(Employee.company_id == run.company_id)
        employees = (await session.execute(emp_stmt)).scalars().all()

        total_gross_paise = 0
        total_deductions_paise = 0
        total_net_paise = 0
        processed_count = 0

        for emp in employees:
            # 1. Fetch Compensation (Paise) or Salary Structure
            comp_stmt = select(Compensation).where(
                Compensation.employee_id == emp.id, Compensation.status == "ACTIVE"
            )
            comp = (await session.execute(comp_stmt)).scalar_one_or_none()

            basic_monthly_paise = 0
            hra_monthly_paise = 0
            special_monthly_paise = 0

            if comp:
                basic_monthly_paise = comp.basic_monthly_paise or int((comp.ctc_annual_paise // 12) * 0.5)
                hra_monthly_paise = comp.hra_monthly_paise or int(basic_monthly_paise * 0.4)
                special_monthly_paise = comp.special_allowance_monthly_paise or max(0, (comp.ctc_annual_paise // 12) - (basic_monthly_paise + hra_monthly_paise))
            else:
                sal_stmt = select(SalaryStructure).where(
                    SalaryStructure.employee_id == emp.id, SalaryStructure.is_active == True
                )
                sal = (await session.execute(sal_stmt)).scalar_one_or_none()
                if sal:
                    basic_monthly_paise = int(sal.basic_monthly * 100)
                    hra_monthly_paise = int(sal.hra_monthly * 100)
                    special_monthly_paise = int(sal.special_allowance_monthly * 100)
                else:
                    # Default minimum wage if no structure set
                    basic_monthly_paise = 25000 * 100
                    hra_monthly_paise = 10000 * 100
                    special_monthly_paise = 5000 * 100

            # 2. Check LOP & Attendance
            att_stmt = select(PayrollAttendanceInput).where(
                PayrollAttendanceInput.employee_id == emp.id,
                PayrollAttendanceInput.period_month == run.period_month,
                PayrollAttendanceInput.period_year == run.period_year,
            )
            att = (await session.execute(att_stmt)).scalar_one_or_none()
            paid_days = Decimal("30.0") if not att else att.paid_days
            lop_days = Decimal("0.0") if not att else att.lop_days

            # 3. Check Variable Inputs
            var_stmt = select(VariableInput).where(
                VariableInput.employee_id == emp.id,
                VariableInput.period_id == run.period_id,
                VariableInput.status.in_(("APPROVED", "PENDING")),
            )
            var_inputs = (await session.execute(var_stmt)).scalars().all()
            variable_earnings_paise = sum(v.amount_paise for v in var_inputs if v.type in ("overtime", "bonus", "incentive", "commission", "reimbursement"))
            variable_deductions_paise = sum(v.amount_paise for v in var_inputs if v.type in ("deduction", "advance_recovery", "lop"))

            # Prorate by paid_days / 30.0
            day_ratio = float(paid_days) / 30.0
            emp_basic_paise = int(basic_monthly_paise * day_ratio)
            emp_hra_paise = int(hra_monthly_paise * day_ratio)
            emp_special_paise = int(special_monthly_paise * day_ratio)

            gross_paise = emp_basic_paise + emp_hra_paise + emp_special_paise + variable_earnings_paise

            # 4. Statutory Deductions
            # PF: 12% of basic (capped at ceiling 15000 if pf_on_full_basic is False)
            pf_wage = min(emp_basic_paise, 15000 * 100) if not config.pf_on_full_basic else emp_basic_paise
            employee_pf_paise = int(pf_wage * 0.12) if config.pf_enabled else 0

            # ESI: 0.75% of gross if gross <= 21000 INR
            employee_esi_paise = int(gross_paise * 0.0075) if (config.esi_enabled and (gross_paise <= 21000 * 100)) else 0

            # PT: flat 200 INR (20000 paise)
            pt_paise = 200 * 100

            # Simple TDS estimate
            tds_paise = 0

            emp_deductions_paise = employee_pf_paise + employee_esi_paise + pt_paise + tds_paise + variable_deductions_paise
            net_paise = max(0, gross_paise - emp_deductions_paise)

            # 5. Create or Update PayrollRunEmployee
            run_emp_stmt = select(PayrollRunEmployee).where(
                PayrollRunEmployee.run_id == run.id,
                PayrollRunEmployee.employee_id == emp.id,
            )
            run_emp = (await session.execute(run_emp_stmt)).scalar_one_or_none()
            if not run_emp:
                run_emp = PayrollRunEmployee(
                    id=uuid.uuid4(),
                    run_id=run.id,
                    employee_id=emp.id,
                    company_id=run.company_id,
                )
                session.add(run_emp)

            run_emp.gross_earnings_paise = gross_paise
            run_emp.total_deductions_paise = emp_deductions_paise
            run_emp.net_pay_paise = net_paise
            run_emp.paid_days = paid_days
            run_emp.lop_days = lop_days
            run_emp.status = "PROCESSED"
            run_emp.validation_status = "VALID"
            run_emp.earnings_breakup = {
                "basic": emp_basic_paise / 100.0,
                "hra": emp_hra_paise / 100.0,
                "special": emp_special_paise / 100.0,
                "variable": variable_earnings_paise / 100.0,
            }
            run_emp.deductions_breakup = {
                "pf": employee_pf_paise / 100.0,
                "esi": employee_esi_paise / 100.0,
                "pt": pt_paise / 100.0,
                "variable": variable_deductions_paise / 100.0,
            }

            # 6. Create/update Payslip
            ps_stmt = select(Payslip).where(
                Payslip.payroll_run_id == run.id, Payslip.employee_id == emp.id
            )
            payslip = (await session.execute(ps_stmt)).scalar_one_or_none()
            if not payslip:
                ps_num = f"PAY-{run.period_year}{run.period_month:02d}-{uuid.uuid4().hex[:6].upper()}"
                payslip = Payslip(
                    id=uuid.uuid4(),
                    company_id=run.company_id,
                    payroll_run_id=run.id,
                    employee_id=emp.id,
                    payslip_number=ps_num,
                    period_month=run.period_month,
                    period_year=run.period_year,
                    total_days_in_month=30,
                    paid_days=paid_days,
                    lop_days=lop_days,
                )
                session.add(payslip)

            payslip.basic = Decimal(str(emp_basic_paise / 100.0))
            payslip.hra = Decimal(str(emp_hra_paise / 100.0))
            payslip.special_allowance = Decimal(str(emp_special_paise / 100.0))
            payslip.gross_earnings = Decimal(str(gross_paise / 100.0))
            payslip.employee_pf = Decimal(str(employee_pf_paise / 100.0))
            payslip.employee_esi = Decimal(str(employee_esi_paise / 100.0))
            payslip.professional_tax = Decimal(str(pt_paise / 100.0))
            payslip.total_deductions = Decimal(str(emp_deductions_paise / 100.0))
            payslip.net_pay = Decimal(str(net_paise / 100.0))
            payslip.payment_status = "PENDING"

            total_gross_paise += gross_paise
            total_deductions_paise += emp_deductions_paise
            total_net_paise += net_paise
            processed_count += 1

        run.total_employees = processed_count
        run.total_gross_paise = total_gross_paise
        run.total_deductions_paise = total_deductions_paise
        run.total_net_paise = total_net_paise
        run.total_gross = Decimal(str(total_gross_paise / 100.0))
        run.total_deductions = Decimal(str(total_deductions_paise / 100.0))
        run.total_net = Decimal(str(total_net_paise / 100.0))
        run.status = "PROCESSED"
        run.validation_status = "VALID"

        if run.company_id:
            try:
                from app.models.user import User
                from app.services import notification_service
                admins_res = await session.execute(
                    select(User.id).where(
                        User.company_id == run.company_id,
                        User.role.in_(["hr_admin", "super_admin", "admin", "cfo", "ceo"]),
                    ).limit(10)
                )
                admin_ids = list(admins_res.scalars().all())
                if admin_ids:
                    await notification_service.notify(
                        session,
                        company_id=run.company_id,
                        recipient_ids=admin_ids,
                        type="payroll.run_needs_approval",
                        category="payroll",
                        module="payroll",
                        title="Payroll Run Requires Approval",
                        body=f"Payroll run #{run.run_number} for {run.total_employees} employees requires review and approval.",
                        link=f"/dashboard/payroll/runs/{run.id}/review",
                        priority="high",
                        entity={"type": "payroll_run", "id": str(run.id)},
                        dedupe_key=f"payroll:run:{run.id}:approval",
                        mandatory=True,
                    )
            except Exception as e:
                logger.warning("Failed to emit payroll approval notification: %s", e)

        await session.commit()
        await session.refresh(run)
        return run

    @classmethod
    async def get_preview(cls, session: AsyncSession, run_id: uuid.UUID) -> dict[str, Any]:
        run = await cls.get_run(session, run_id)
        return {
            "run_id": str(run.id),
            "status": run.status,
            "period_month": run.period_month,
            "period_year": run.period_year,
            "total_employees": run.total_employees,
            "total_gross_paise": run.total_gross_paise,
            "total_deductions_paise": run.total_deductions_paise,
            "total_net_paise": run.total_net_paise,
            "total_gross": float(run.total_gross),
            "total_deductions": float(run.total_deductions),
            "total_net": float(run.total_net),
            "is_locked": run.is_locked,
        }
