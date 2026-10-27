"""Service for Payroll Runs (v1 & v2).

Handles payroll execution, calculations in integer paise, validation checks,
and state machine transitions (approve, finalize, reject, cancel, send-back).
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import selectinload

from app.models.employee import Employee
from app.models.payroll import (
    AdvanceLoan,
    AdvanceLoanInstallment,
    EmployeeInvestmentDeclaration,
    PayrollAttendanceInput,
    PayrollRun,
    Payslip,
    SalaryStructure,
    StatutoryComplianceConfig,
)
from app.models.payroll_models import (
    ArrearLedger,
    Compensation,
    PayComponent,
    PayrollPeriod,
    PayrollRunEmployee,
    VariableInput,
)
from app.services.payroll.audit_service import PayrollAuditService
from app.services.payroll.arrear_service import ArrearService
from app.services.payroll.formula_evaluator import SafeFormulaEvaluator
from app.services.payroll.money import as_decimal, paise_to_rupees, round_paise, round_to_rupee_paise
from app.services.payroll.statutory_service import StatutoryService

logger = logging.getLogger(__name__)

#: Maps a VariableInput.type to the pay-component code used by the Labour Codes
#: "excluded allowances" configuration.
_VARIABLE_TYPE_TO_COMPONENT = {
    "overtime": "OVERTIME",
    "bonus": "STATUTORY_BONUS",
    "commission": "COMMISSION",
    "incentive": "INCENTIVE",
    "reimbursement": "REIMBURSEMENT",
    "shift_allowance": "SHIFT_ALLOWANCE",
    "comp_off_encashment": "COMP_OFF_ENCASHMENT",
    "lta": "LTA",
    "statutory_bonus": "STATUTORY_BONUS",
}


class PayrollRunService:
    """Core domain logic for payroll runs."""

    @classmethod
    async def get_run(
        cls, session: AsyncSession, run_id: uuid.UUID,
        company_id: Optional[uuid.UUID] = None,
    ) -> PayrollRun:
        stmt = (
            select(PayrollRun)
            .options(selectinload(PayrollRun.period))
            .where(PayrollRun.id == run_id)
        )
        if company_id is not None:
            stmt = stmt.where(PayrollRun.company_id == company_id)
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
        user_role: Optional[str] = None,
    ) -> PayrollRun:
        # Verify period exists
        period_stmt = select(PayrollPeriod).where(PayrollPeriod.id == period_id)
        period = (await session.execute(period_stmt)).scalar_one_or_none()
        if not period or (company_id is not None and period.company_id != company_id):
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
            created_by=user_id,
            run_at=datetime.now(),
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)

        await PayrollAuditService.log_event(
            session=session,
            entity_type="PayrollRun",
            entity_id=run.id,
            action="CREATE",
            company_id=run.company_id,
            actor_id=user_id,
            actor_role=user_role,
            before_status=None,
            after_status="DRAFT",
            reason="Created payroll run",
        )

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
    @staticmethod
    def maker_ids_for_run(run: PayrollRun) -> list[uuid.UUID]:
        """Every user who initiated or processed this run (the "makers")."""
        makers: list[uuid.UUID] = []
        for attr in ("created_by", "processed_by", "run_by"):
            value = getattr(run, attr, None)
            if value is None:
                continue
            try:
                parsed = value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
            except (ValueError, AttributeError, TypeError):
                continue
            if parsed not in makers:
                makers.append(parsed)
        return makers

    @classmethod
    async def _check_maker_checker(
        cls,
        session: AsyncSession,
        run: PayrollRun,
        user_id: Optional[uuid.UUID],
        user_role: Optional[str],
        action: str = "APPROVE",
    ) -> bool:
        """Enforce strict maker-checker (dual control) on a payroll run action.

        Raises ``ForbiddenException`` with code ``MAKER_CHECKER_VIOLATION`` (HTTP
        403) when the tenant's active ``StatutoryComplianceConfig`` enforces the
        policy and the acting user is also the user who created/processed the run.
        Returns ``True`` when dual control was exercised, ``False`` when the
        tenant has no active policy.
        """
        from app.api.payroll.permissions import enforce_maker_checker

        return await enforce_maker_checker(
            session,
            entity_type="PayrollRun",
            entity_id=run.id,
            company_id=run.company_id,
            maker_ids=cls.maker_ids_for_run(run),
            approver_id=user_id,
            actor_role=user_role,
            action=action,
            before_status=run.status,
        )

    @classmethod
    async def submit_for_approval(
        cls, session: AsyncSession, run_id: uuid.UUID,
        user_id: Optional[uuid.UUID] = None, user_role: Optional[str] = None,
        company_id: Optional[uuid.UUID] = None,
    ) -> PayrollRun:
        """Transition a calculated run from PROCESSED to PENDING_APPROVAL."""
        run = await cls.get_run(session, run_id, company_id=company_id)
        if run.status != "PROCESSED":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Run must be PROCESSED before submission (current: {run.status}).")
        old_status = run.status
        run.status = "PENDING_APPROVAL"
        await PayrollAuditService.log_event(
            session=session, entity_type="PayrollRun", entity_id=run.id, action="SUBMIT_FOR_APPROVAL",
            company_id=run.company_id, actor_id=user_id, actor_role=user_role,
            before_status=old_status, after_status=run.status, reason="Payroll run submitted for approval",
        )
        await session.commit()
        await session.refresh(run)
        return run

    @classmethod
    async def mark_paid(
        cls, session: AsyncSession, run_id: uuid.UUID,
        user_id: Optional[uuid.UUID] = None, user_role: Optional[str] = None,
        company_id: Optional[uuid.UUID] = None,
    ) -> PayrollRun:
        """Close the canonical lifecycle only after a locked run is paid."""
        run = await cls.get_run(session, run_id, company_id=company_id)
        if run.status != "LOCKED":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Run must be LOCKED before payment (current: {run.status}).")
        old_status = run.status
        run.status = "PAID"
        run.paid_at = datetime.now()
        payslips = (await session.execute(select(Payslip).where(Payslip.payroll_run_id == run.id))).scalars().all()
        for payslip in payslips:
            payslip.payment_status = "PAID"
            payslip.payment_date = run.paid_at.date()
        await PayrollAuditService.log_event(
            session=session, entity_type="PayrollRun", entity_id=run.id, action="MARK_PAID",
            company_id=run.company_id, actor_id=user_id, actor_role=user_role,
            before_status=old_status, after_status=run.status, reason="Payroll run marked as paid",
        )
        await session.commit()
        await session.refresh(run)
        return run

    @classmethod
    async def lock_run(cls, session: AsyncSession, run_id: uuid.UUID, **kwargs) -> PayrollRun:
        kwargs["lock"] = True
        return await cls.finalize_run(session, run_id, **kwargs)

    @classmethod
    async def approve_run(
        cls,
        session: AsyncSession,
        run_id: uuid.UUID,
        comments: Optional[str] = None,
        user_id: Optional[uuid.UUID] = None,
        user_role: Optional[str] = None,
        allow_legacy: bool = False,
        company_id: Optional[uuid.UUID] = None,
    ) -> PayrollRun:
        run = await cls.get_run(session, run_id, company_id=company_id)
        allowed = {"PENDING_APPROVAL"}
        if allow_legacy:
            allowed.update({"DRAFT", "VALIDATED", "PROCESSED"})
        if run.status not in allowed:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Run must be PENDING_APPROVAL before approval (current: {run.status}).",
            )

        # Enforce strict maker-checker (raises 403 MAKER_CHECKER_VIOLATION).
        await cls._check_maker_checker(session, run, user_id, user_role, action="APPROVE")

        old_status = run.status
        run.status = "APPROVED"
        run.approved_by = user_id
        run.approved_at = datetime.now()
        run.comments = comments

        audit_reason = comments or "Approved payroll run"

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
            reason=audit_reason,
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
        legacy: bool = False,
        company_id: Optional[uuid.UUID] = None,
    ) -> PayrollRun:
        run = await cls.get_run(session, run_id, company_id=company_id)
        allowed = {"APPROVED", "PROCESSED", "DRAFT", "VALIDATED", "PENDING_APPROVAL"} if legacy else {"APPROVED"}
        if run.status not in allowed:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Run must be APPROVED before locking (current: {run.status}).",
            )

        # Enforce strict maker-checker for finalization too.
        await cls._check_maker_checker(session, run, user_id, user_role, action="FINALIZE" if legacy else "LOCK")

        old_status = run.status
        run.status = "FINALIZED" if legacy else ("LOCKED" if lock else "APPROVED")
        run.is_locked = lock
        run.finalized_by = user_id
        run.finalized_at = datetime.now()
        run.notes = notes

        audit_reason = notes or "Finalized payroll run"

        await PayrollAuditService.log_event(
            session=session,
            entity_type="PayrollRun",
            entity_id=run.id,
            action="FINALIZE" if legacy else "LOCK",
            company_id=run.company_id,
            actor_id=user_id,
            actor_role=user_role,
            before_status=old_status,
            after_status=run.status,
            reason=audit_reason,
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
        if run.status in ("FINALIZED", "LOCKED", "PAID"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Finalized, locked, or disbursed runs cannot be rejected.",
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
        if run.status in ("FINALIZED", "LOCKED", "PAID"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Finalized, locked, or disbursed payroll runs cannot be cancelled.",
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
        if run.status in ("FINALIZED", "LOCKED", "PAID"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Finalized or locked runs cannot be sent back.",
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
        run.status = "VALIDATED"

        await PayrollAuditService.log_event(
            session=session,
            entity_type="PayrollRun",
            entity_id=run.id,
            action="RETRY",
            company_id=run.company_id,
            actor_id=user_id,
            actor_role=user_role,
            before_status=old_status,
            after_status="VALIDATED",
        )
        await session.commit()

        # Re-execute calculation engine
        return await cls.execute_run_calculation(session, run_id, user_id=user_id, user_role=user_role)

    @classmethod
    async def delete_run(cls, session: AsyncSession, run_id: uuid.UUID) -> dict[str, str]:
        run = await cls.get_run(session, run_id)
        if run.status in ("FINALIZED", "LOCKED", "PAID"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Finalized, locked, or disbursed payroll runs cannot be deleted.",
            )
        await session.delete(run)
        await session.commit()
        return {"message": f"Payroll run {run_id} deleted successfully."}

    @classmethod
    async def validate_run(cls, session: AsyncSession, run_id: uuid.UUID) -> dict[str, Any]:
        """Perform pre-check validations on all eligible employees for this run."""
        run = await cls.get_run(session, run_id)

        # Fetch active employees.
        # `bank_accounts` is eagerly loaded (selectinload) because it is accessed
        # below for the "Missing primary bank account" pre-check.  Without the
        # eager load SQLAlchemy would emit an implicit lazy-load inside the async
        # session and raise `MissingGreenlet` (surfaced as a 500).
        emp_stmt = (
            select(Employee)
            .options(selectinload(Employee.bank_accounts))
            .where(Employee.is_deleted == False)
        )
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
        # Validation is an explicit lifecycle transition.  Warnings are
        # reviewable and do not prevent a validated run from being processed.
        if run.status == "DRAFT":
            run.status = "VALIDATED"
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
    async def _advance_deduction_for_employee(
        cls, session: AsyncSession, run: PayrollRun, employee_id: uuid.UUID,
    ) -> int:
        """Return and consume the current period's pending advance/loan EMI.

        Installments are created lazily for active loans so a loan does not need
        a separate payroll-specific setup step.  DEDUCTED rows are never charged
        again on a retry, and the loan balance/installment counter is updated in
        the same transaction as the payslip.
        """
        loan_stmt = select(AdvanceLoan).where(
            AdvanceLoan.employee_id == employee_id,
            AdvanceLoan.status == "ACTIVE",
        )
        if run.company_id is not None:
            loan_stmt = loan_stmt.where(
                or_(AdvanceLoan.company_id == run.company_id, AdvanceLoan.company_id.is_(None))
            )
        loans = list((await session.execute(loan_stmt)).scalars().all())
        current = (run.period_year, run.period_month)
        total_paise = 0
        for loan in loans:
            if current < (loan.start_from_year, loan.start_from_month):
                continue
            if int(loan.installments_paid or 0) >= int(loan.total_installments or 0):
                continue
            installment = (await session.execute(
                select(AdvanceLoanInstallment).where(
                    AdvanceLoanInstallment.loan_id == loan.id,
                    AdvanceLoanInstallment.period_month == run.period_month,
                    AdvanceLoanInstallment.period_year == run.period_year,
                )
            )).scalar_one_or_none()
            if installment is not None and str(installment.status).upper() == "DEDUCTED":
                continue
            outstanding = as_decimal(loan.outstanding_balance)
            amount = as_decimal(installment.emi_amount) if installment is not None else min(
                as_decimal(loan.emi_amount), outstanding,
            )
            amount = min(amount, outstanding) if outstanding > 0 else Decimal("0")
            if amount <= 0:
                continue
            balance_after = max(Decimal("0"), outstanding - amount)
            if installment is None:
                installment = AdvanceLoanInstallment(
                    id=uuid.uuid4(), loan_id=loan.id,
                    period_month=run.period_month, period_year=run.period_year,
                    emi_amount=amount, balance_after=balance_after, status="PENDING",
                )
                session.add(installment)
            installment.emi_amount = amount
            installment.balance_after = balance_after
            installment.status = "DEDUCTED"
            loan.outstanding_balance = balance_after
            loan.installments_paid = int(loan.installments_paid or 0) + 1
            if balance_after <= 0 or loan.installments_paid >= int(loan.total_installments or 0):
                loan.status = "CLOSED"
            total_paise += round_paise(amount * 100)
        return total_paise

    @classmethod
    async def execute_run_calculation(
        cls,
        session: AsyncSession,
        run_id: uuid.UUID,
        user_id: Optional[uuid.UUID] = None,
        user_role: Optional[str] = None,
        company_id: Optional[uuid.UUID] = None,
    ) -> PayrollRun:
        """Core Payroll Calculation Engine in integer paise.

        ``user_id`` (when supplied) is recorded as ``processed_by`` so strict
        maker-checker can prove the approver is not the user who processed the
        run.  Runs triggered by the async worker keep whatever attribution they
        already have.
        """
        run = await cls.get_run(session, run_id, company_id=company_id)
        if run.status != "VALIDATED":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Run must be VALIDATED before processing (current: {run.status}).",
            )
        run.status = "PROCESSING"
        if user_id is not None:
            run.processed_by = user_id
            if run.created_by is None:
                run.created_by = user_id
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
        period_record = await session.get(PayrollPeriod, run.period_id) if run.period_id else None

        # Fetch all active employees (bank_accounts eagerly loaded so downstream
        # disbursement / validation code never triggers an async lazy-load).
        emp_stmt = (
            select(Employee)
            .options(selectinload(Employee.bank_accounts))
            .where(Employee.is_deleted == False)
        )
        if run.company_id:
            emp_stmt = emp_stmt.where(Employee.company_id == run.company_id)
        employees = (await session.execute(emp_stmt)).scalars().all()

        component_stmt = select(PayComponent).where(PayComponent.is_active == True)  # noqa: E712
        if run.company_id:
            component_stmt = component_stmt.where(
                or_(PayComponent.company_id == run.company_id, PayComponent.company_id.is_(None))
            )
        pay_components = list((await session.execute(component_stmt)).scalars().all())

        pending_arrears = await ArrearService.pending_for_run(session, run)
        arrears_by_employee: dict[uuid.UUID, list[ArrearLedger]] = {}
        for arrear in pending_arrears:
            arrears_by_employee.setdefault(arrear.employee_id, []).append(arrear)

        total_gross_paise = 0
        total_deductions_paise = 0
        total_net_paise = 0
        processed_count = 0

        for emp in employees:
            # 1. Fetch compensation and the versioned salary structure.  The
            # latter supplies the additional Indian salary heads (LTA, bonus,
            # conveyance, reimbursements and custom fixed allowances).
            comp_stmt = select(Compensation).where(
                Compensation.employee_id == emp.id, Compensation.status == "ACTIVE"
            )
            comp = (await session.execute(comp_stmt)).scalar_one_or_none()
            sal_stmt = select(SalaryStructure).where(
                SalaryStructure.employee_id == emp.id, SalaryStructure.is_active == True
            )
            sal = (await session.execute(sal_stmt)).scalar_one_or_none()

            basic_monthly_paise = 0
            hra_monthly_paise = 0
            special_monthly_paise = 0
            conveyance_monthly_paise = 0
            lta_monthly_paise = 0
            statutory_bonus_monthly_paise = 0
            reimbursement_monthly_paise = 0
            other_fixed_allowances_paise: dict[str, int] = {}
            other_allowances = (sal.other_allowances if sal and sal.other_allowances else {})

            def _allowance_paise(value) -> int:
                if isinstance(value, dict):
                    value = value.get("monthly", value.get("amount", value.get("value", 0)))
                return round_paise(as_decimal(value) * 100)

            def _allowance_named(*names: str) -> int:
                for key, value in other_allowances.items():
                    normalized = str(key).strip().lower().replace(" ", "_").replace("-", "_")
                    if normalized in names:
                        return _allowance_paise(value)
                return 0

            if comp:
                basic_monthly_paise = int(comp.basic_monthly_paise or round_paise(Decimal(comp.ctc_annual_paise or 0) / 12 * Decimal("0.5")))
                hra_monthly_paise = int(comp.hra_monthly_paise or round_paise(Decimal(basic_monthly_paise) * Decimal("0.4")))
                special_monthly_paise = int(comp.special_allowance_monthly_paise or max(0, round_paise(Decimal(comp.ctc_annual_paise or 0) / 12) - basic_monthly_paise - hra_monthly_paise))
            elif sal:
                basic_monthly_paise = round_paise(as_decimal(sal.basic_monthly) * 100)
                hra_monthly_paise = round_paise(as_decimal(sal.hra_monthly) * 100)
                special_monthly_paise = round_paise(as_decimal(sal.special_allowance_monthly) * 100)
                conveyance_monthly_paise = round_paise(as_decimal(getattr(sal, "conveyance_monthly", 0)) * 100)
            else:
                # Deterministic minimum-wage fallback retained for legacy runs.
                basic_monthly_paise = 25000 * 100
                hra_monthly_paise = 10000 * 100
                special_monthly_paise = 5000 * 100

            conveyance_monthly_paise = conveyance_monthly_paise or _allowance_named("conveyance", "conveyance_allowance")
            lta_monthly_paise = _allowance_named("lta", "leave_travel_allowance", "leave_travel_concession")
            statutory_bonus_monthly_paise = _allowance_named("statutory_bonus", "bonus")
            if not statutory_bonus_monthly_paise and sal and sal.annual_bonus:
                statutory_bonus_monthly_paise = round_paise(as_decimal(sal.annual_bonus) * 100 / 12)
            reimbursement_monthly_paise = _allowance_named("reimbursement", "reimbursements")
            known_allowance_names = {
                "conveyance", "conveyance_allowance", "lta", "leave_travel_allowance",
                "leave_travel_concession", "statutory_bonus", "bonus", "reimbursement", "reimbursements",
            }
            for key, value in other_allowances.items():
                normalized = str(key).strip().lower().replace(" ", "_").replace("-", "_")
                if normalized not in known_allowance_names:
                    other_fixed_allowances_paise[str(key)] = _allowance_paise(value)

            # 2. Check LOP & Attendance
            att_stmt = select(PayrollAttendanceInput).where(
                PayrollAttendanceInput.employee_id == emp.id,
                PayrollAttendanceInput.period_month == run.period_month,
                PayrollAttendanceInput.period_year == run.period_year,
            )
            att = (await session.execute(att_stmt)).scalar_one_or_none()
            paid_days = Decimal("30.0") if not att else att.paid_days
            lop_days = Decimal("0.0") if not att else att.lop_days
            attendance_arrear_paise = round_paise(as_decimal(att.arrears if att else 0) * 100)
            one_time_bonus_paise = round_paise(as_decimal(att.one_time_bonus if att else 0) * 100)

            # 3. Variable inputs and pending arrears.  Types are normalized so
            # legacy lower-case inputs and the new upper-case attendance inputs
            # share exactly the same integer-paise path.
            var_stmt = select(VariableInput).where(
                VariableInput.employee_id == emp.id,
                VariableInput.period_id == run.period_id,
                VariableInput.status.in_(("APPROVED", "PENDING")),
            )
            var_inputs = (await session.execute(var_stmt)).scalars().all()
            deduction_types = {"deduction", "advance_recovery", "advance", "loan_emi", "loan_recovery", "recovery", "lop"}
            earning_types = {
                "overtime", "bonus", "one_time_bonus", "incentive", "commission", "reimbursement",
                "shift_allowance", "shift", "comp_off_encashment", "comp_off", "lta", "statutory_bonus", "other",
            }
            variable_earnings_paise = sum(
                int(v.amount_paise or 0) for v in var_inputs
                if str(v.type).lower() in earning_types
            )
            variable_deductions_paise = sum(
                int(v.amount_paise or 0) for v in var_inputs
                if str(v.type).lower() in deduction_types
            )
            advance_deduction_paise = await cls._advance_deduction_for_employee(session, run, emp.id)
            employee_arrears = arrears_by_employee.get(emp.id, [])
            arrear_paise = sum(int(a.amount_paise or 0) for a in employee_arrears)
            total_arrear_paise = arrear_paise + attendance_arrear_paise

            # LOP pro-ration is applied to fixed salary heads, not to actual
            # reimbursements or already-computed variable inputs.  If HR supplies
            # only LOP days, derive paid days from the 30-day payroll policy.
            paid_days = as_decimal(paid_days)
            lop_days = as_decimal(lop_days)
            if lop_days > 0:
                paid_days = min(paid_days, max(Decimal("0"), Decimal("30") - lop_days))
            day_ratio = max(Decimal("0"), min(Decimal("1"), paid_days / Decimal("30")))

            def _prorated(value: int) -> int:
                return round_paise(Decimal(int(value)) * day_ratio)

            emp_basic_paise = _prorated(basic_monthly_paise)
            emp_hra_paise = _prorated(hra_monthly_paise)
            emp_special_paise = _prorated(special_monthly_paise)
            emp_conveyance_paise = _prorated(conveyance_monthly_paise)
            emp_lta_paise = _prorated(lta_monthly_paise)
            emp_statutory_bonus_paise = _prorated(statutory_bonus_monthly_paise)
            emp_reimbursement_paise = int(reimbursement_monthly_paise)
            emp_other_fixed_paise = {key: _prorated(value) for key, value in other_fixed_allowances_paise.items()}

            # Per-component variable earnings feed the Labour Codes wage rule.
            var_component_paise: dict[str, int] = {}
            for v in var_inputs:
                normalized_type = str(v.type).lower()
                if normalized_type not in earning_types:
                    continue
                code = _VARIABLE_TYPE_TO_COMPONENT.get(normalized_type, normalized_type.upper())
                var_component_paise[code] = var_component_paise.get(code, 0) + int(v.amount_paise or 0)

            annual_ctc_paise = (
                int(comp.ctc_annual_paise or 0) if comp else round_paise(as_decimal(sal.annual_ctc) * 100) if sal else 0
            )
            monthly_ctc_paise = round_paise(Decimal(annual_ctc_paise) / 12) if annual_ctc_paise else (
                basic_monthly_paise + hra_monthly_paise + special_monthly_paise + conveyance_monthly_paise
            )
            base_gross_paise = (
                emp_basic_paise + emp_hra_paise + emp_special_paise + emp_conveyance_paise
                + emp_lta_paise + emp_statutory_bonus_paise + emp_reimbursement_paise
                + sum(emp_other_fixed_paise.values()) + variable_earnings_paise
                + total_arrear_paise + one_time_bonus_paise
            )

            # Custom company pay components are evaluated in paise.  Core and
            # statutory codes are owned by their dedicated engines and skipped
            # here to prevent double counting when the default catalog exists.
            custom_earning_breakup: dict[str, int] = {}
            custom_deduction_breakup: dict[str, int] = {}
            custom_employer_paise = 0
            custom_earnings_paise = 0
            custom_deductions_paise = 0
            core_codes = {
                "BASIC", "HRA", "SPECIAL_ALLOWANCE", "CONVEYANCE", "LTA",
                "STATUTORY_BONUS", "REIMBURSEMENT", "PF", "ESI", "PT", "LWF", "TDS",
                "PF_EMPLOYEE", "PF_EMPLOYER", "ESI_EMPLOYEE", "ESI_EMPLOYER",
            }
            formula_context = {
                "basic": emp_basic_paise, "hra": emp_hra_paise, "special": emp_special_paise,
                "special_allowance": emp_special_paise,
                "conveyance": emp_conveyance_paise, "lta": emp_lta_paise,
                "gross": base_gross_paise, "ctc": annual_ctc_paise,
                "monthly_ctc": monthly_ctc_paise, "paid_days": paid_days,
                "lop_days": lop_days, "total_days": Decimal("30"),
                "arrears": total_arrear_paise, "one_time_bonus": one_time_bonus_paise,
            }
            for component in pay_components:
                code = str(component.code).upper()
                if code in core_codes:
                    continue
                method = str(component.calculation_method or "flat").lower()
                try:
                    if method == "formula" and component.formula_expr:
                        value_paise = SafeFormulaEvaluator.evaluate_paise(component.formula_expr, formula_context)
                    elif method == "percentage_of_basic" and component.default_percentage is not None:
                        value_paise = round_paise(Decimal(emp_basic_paise) * as_decimal(component.default_percentage))
                    elif method == "percentage_of_ctc" and component.default_percentage is not None:
                        value_paise = round_paise(Decimal(monthly_ctc_paise) * day_ratio * as_decimal(component.default_percentage))
                    else:
                        # Flat catalogue entries have no amount field; actual
                        # flat values belong in salary structure/variable input.
                        continue
                except ValueError as exc:
                    raise HTTPException(status_code=422, detail=f"Invalid formula for pay component {code}: {exc}") from exc
                if str(component.type).lower() == "earning":
                    custom_earning_breakup[code] = custom_earning_breakup.get(code, 0) + value_paise
                    custom_earnings_paise += value_paise
                    formula_context[code.lower()] = value_paise
                    formula_context["gross"] = base_gross_paise + custom_earnings_paise
                elif str(component.type).lower() == "deduction":
                    custom_deduction_breakup[code] = custom_deduction_breakup.get(code, 0) + value_paise
                    custom_deductions_paise += value_paise
                elif str(component.type).lower() == "employer_contribution":
                    custom_employer_paise += value_paise

            gross_paise = max(0, base_gross_paise + custom_earnings_paise)

            # 3b. Labour Codes (Code on Wages, 2019) — 50% Wage Definition Rule.
            # If the excluded allowances exceed (1 - min_basic_wage_ratio) of gross
            # remuneration, the excess is folded back into the statutory wage base
            # used for PF, ESI and Gratuity.
            wage_rule = StatutoryService.apply_labour_code_wage_rule(
                gross_remuneration_paise=gross_paise,
                basic_paise=emp_basic_paise,
                allowances={
                    "HRA": emp_hra_paise,
                    "CONVEYANCE": emp_conveyance_paise,
                    "SPECIAL_ALLOWANCE": emp_special_paise,
                    **var_component_paise,
                },
                config=config,
            )
            statutory_wages_paise = wage_rule["statutory_wages_paise"]

            # 4. Indian Statutory Deductions Engine
            employee_age = None
            if getattr(emp, "date_of_birth", None):
                on_date = getattr(run, "end_date", None) or date(run.period_year, run.period_month, 1)
                employee_age = on_date.year - emp.date_of_birth.year - ((on_date.month, on_date.day) < (emp.date_of_birth.month, emp.date_of_birth.day))
            pf_res = StatutoryService.calculate_pf(
                basic_paise=statutory_wages_paise,
                config=config,
                is_pf_eligible=bool(getattr(emp, "is_pf_eligible", True)),
                pf_membership_active=bool(getattr(emp, "pf_membership_active", True)),
                is_international_worker=bool(getattr(emp, "is_international_worker", False)),
                pf_wage_ceiling_applicable=bool(getattr(emp, "pf_wage_ceiling_applicable", True)),
                pf_higher_wage_opted=bool(getattr(emp, "pf_higher_wage_opted", False)),
                vpf_rate=getattr(emp, "vpf_rate", 0),
                age=employee_age,
            )
            employee_pf_paise = pf_res["employee_pf_paise"]

            coverage = None
            if period_record is not None:
                coverage = await StatutoryService.get_esi_coverage_at_period_start(
                    session, emp, period_record, config, run.company_id,
                )
            current_esi_ceiling = int(coverage["ceiling_paise"]) if coverage else int(as_decimal(getattr(config, "esi_pwd_wage_ceiling", 25000) if getattr(emp, "is_pwd", False) else getattr(config, "esi_wage_ceiling", 21000)) * 100)
            esi_res = StatutoryService.calculate_esi(
                gross_monthly_paise=gross_paise,
                config=config,
                contribution_wage_paise=statutory_wages_paise,
                is_pwd=bool(getattr(emp, "is_pwd", False)),
                covered_at_period_start=(coverage["covered"] if coverage else bool(getattr(emp, "esi_covered_at_period_start", False))) or gross_paise <= current_esi_ceiling,
                contribution_period_start=coverage["contribution_period_start"] if coverage else None,
                as_of_date=getattr(run, "start_date", None) or date(run.period_year, run.period_month, 1),
            )
            employee_esi_paise = esi_res["employee_esi_paise"]

            emp_state = getattr(emp, "state_code", None) or getattr(emp, "state", None) or getattr(emp, "branch", None) or getattr(emp, "work_location", None) or config.pt_state or "MAHARASHTRA"
            try:
                state_rule = await StatutoryService.get_state_statutory_rule(
                    session, emp_state, run.company_id,
                    (period_record.start_date if period_record is not None and period_record.start_date else date(run.period_year, run.period_month, 1)),
                )
            except OperationalError as exc:
                # Older SQLite test/embedded schemas may predate this additive
                # table. PostgreSQL migration/schema errors remain fatal.
                if session.bind is None or session.bind.dialect.name != "sqlite" or "no such table" not in str(exc).lower():
                    raise
                state_rule = None
            pt_res = StatutoryService.calculate_pt(
                gross_monthly_paise=gross_paise,
                state=emp_state,
                month=run.period_month,
                gender=getattr(emp, "gender", "MALE") or "MALE",
                rule=state_rule,
            )
            pt_paise = pt_res["pt_paise"]

            lwf_res = StatutoryService.calculate_lwf(
                gross_monthly_paise=gross_paise,
                state=emp_state,
                month=run.period_month,
                rule=state_rule,
            )
            employee_lwf_paise = lwf_res["employee_lwf_paise"]

            # Query tax investment declaration for TDS calculation
            fy_label = f"{run.period_year}-{run.period_year+1}" if run.period_month >= 4 else f"{run.period_year-1}-{run.period_year}"
            decl_stmt = select(EmployeeInvestmentDeclaration).where(
                EmployeeInvestmentDeclaration.employee_id == emp.id,
                EmployeeInvestmentDeclaration.financial_year == fy_label,
            )
            decl = (await session.execute(decl_stmt)).scalar_one_or_none()
            decl_dict = {
                "section_80c": float(decl.section_80c) if decl else 0,
                "section_80d": float(decl.section_80d) if decl else 0,
                "section_80ccd1b_nps": float(decl.section_80ccd1b_nps) if decl else 0,
                "home_loan_interest_24b": float(decl.home_loan_interest_24b) if decl else 0,
                "section_80g": float(getattr(decl, "section_80g", 0) or 0) if decl else 0,
                "hra_claimed": float(decl.hra_claimed) if decl else 0,
                "lta_claimed": float(getattr(decl, "lta_claimed", 0) or 0) if decl else 0,
                "professional_tax": float(getattr(emp, "professional_tax", 0) or 0) * 12,
                "other_deductions": float(decl.other_deductions) if decl else 0,
            } if decl else {"professional_tax": float(getattr(emp, "professional_tax", 0) or 0) * 12}
            emp_regime = (decl.tax_regime if decl else None) or config.default_tax_regime or "NEW"
            rem_months = 12 - run.period_month + 1 if run.period_month >= 4 else 4 - run.period_month
            verified_declarations = (decl.verified_details_json if decl else None) or None
            cutoff_passed = bool(decl and decl.proof_cutoff_date and decl.proof_cutoff_date <= (getattr(run, "end_date", None) or date.today()))
            current_one_time_variable_paise = sum(
                int(v.amount_paise or 0) for v in var_inputs
                if str(v.type).lower() in {"bonus", "one_time_bonus", "incentive", "commission"}
            )
            current_one_time_paise = one_time_bonus_paise + current_one_time_variable_paise
            recurring_annual_gross_paise = max(0, gross_paise - current_one_time_paise) * 12
            fy_start_year = run.period_year if run.period_month >= 4 else run.period_year - 1
            fy_pairs = [(m, fy_start_year if m >= 4 else fy_start_year + 1) for m in range(4, 13)] + [(m, fy_start_year + 1) for m in range(1, 4)]
            prior_tds_stmt = select(func.coalesce(func.sum(Payslip.tds), 0)).where(
                Payslip.employee_id == emp.id,
                Payslip.company_id == run.company_id,
                or_(*[and_(Payslip.period_month == month, Payslip.period_year == year) for month, year in fy_pairs]),
                or_(Payslip.period_month != run.period_month, Payslip.period_year != run.period_year),
            )
            prior_tds_rupees = (await session.execute(prior_tds_stmt)).scalar() or 0
            prior_tds_paise = int(as_decimal(prior_tds_rupees) * 100)
            declared_ytd_paise = int(getattr(decl, "ytd_tds_paise", 0) or 0) if decl else 0
            ytd_for_projection = max(declared_ytd_paise, prior_tds_paise)
            tds_res = StatutoryService.calculate_tds(
                annual_gross_paise=recurring_annual_gross_paise,
                tax_regime=emp_regime,
                declarations=decl_dict,
                verified_declarations=verified_declarations,
                use_verified_declarations=bool(decl and decl.use_verified_amounts and cutoff_passed),
                proof_cutoff_passed=cutoff_passed,
                financial_year=fy_label,
                current_month=run.period_month,
                remaining_months=rem_months,
                ytd_tds_paise=ytd_for_projection,
                previous_employer_tds_paise=int(getattr(decl, "previous_employer_tds_paise", 0) or 0) if decl else 0,
                previous_employer_income_paise=int(getattr(decl, "previous_employer_income_paise", 0) or 0) if decl else 0,
                one_time_bonus_paise=current_one_time_paise + (int(getattr(decl, "one_time_bonus_paise", 0) or 0) if decl else 0),
                variable_pay_paise=int(getattr(decl, "variable_pay_paise", 0) or 0) if decl else 0,
                basic_annual_paise=emp_basic_paise * 12,
                hra_annual_paise=emp_hra_paise * 12,
            )
            tds_paise = tds_res["current_month_tds_paise"]
            if decl is not None:
                decl.ytd_tds_paise = max(declared_ytd_paise, prior_tds_paise + tds_paise)

            grat_res = StatutoryService.calculate_gratuity(
                emp_basic_paise, statutory_wage_paise=statutory_wages_paise
            )

            emp_deductions_paise = (
                employee_pf_paise
                + employee_esi_paise
                + pt_paise
                + employee_lwf_paise
                + tds_paise
                + variable_deductions_paise
                + advance_deduction_paise
                + custom_deductions_paise
            )
            # Final Net Pay is always a whole-rupee, half-up integer-paise
            # value.  Do not replace this with Python's banker-rounding round().
            net_paise = max(0, round_to_rupee_paise(gross_paise - emp_deductions_paise))

            employer_cost_paise = (
                gross_paise
                + pf_res["total_employer_pf_paise"]
                + pf_res["employer_edli_paise"]
                + pf_res["employer_admin_paise"]
                + esi_res["employer_esi_paise"]
                + lwf_res["employer_lwf_paise"]
                + grat_res["monthly_gratuity_provision_paise"]
                + custom_employer_paise
            )

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
                "basic": float(paise_to_rupees(emp_basic_paise)),
                "hra": float(paise_to_rupees(emp_hra_paise)),
                "special": float(paise_to_rupees(emp_special_paise)),
                "conveyance": float(paise_to_rupees(emp_conveyance_paise)),
                "lta": float(paise_to_rupees(emp_lta_paise)),
                "statutory_bonus": float(paise_to_rupees(emp_statutory_bonus_paise)),
                "reimbursement": float(paise_to_rupees(emp_reimbursement_paise)),
                "other_fixed": {k: float(paise_to_rupees(v)) for k, v in emp_other_fixed_paise.items()},
                "custom": {k: float(paise_to_rupees(v)) for k, v in custom_earning_breakup.items()},
                "variable": float(paise_to_rupees(variable_earnings_paise)),
                "arrears": float(paise_to_rupees(total_arrear_paise)),
                "one_time_bonus": float(paise_to_rupees(one_time_bonus_paise)),
                "gross": float(paise_to_rupees(gross_paise)),
                # Exact integer mirrors are consumed by parallel comparison and
                # prevent a JSON float round-trip from becoming the source of truth.
                "basic_paise": emp_basic_paise,
                "hra_paise": emp_hra_paise,
                "special_paise": emp_special_paise,
                "conveyance_paise": emp_conveyance_paise,
                "lta_paise": emp_lta_paise,
                "statutory_bonus_paise": emp_statutory_bonus_paise,
                "reimbursement_paise": emp_reimbursement_paise,
                "variable_paise": variable_earnings_paise,
                "arrears_paise": total_arrear_paise,
                "ledger_arrears_paise": arrear_paise,
                "attendance_arrears_paise": attendance_arrear_paise,
                "one_time_bonus_paise": one_time_bonus_paise,
                "gross_paise": gross_paise,
            }
            run_emp.deductions_breakup = {
                "pf": float(paise_to_rupees(employee_pf_paise)),
                "esi": float(paise_to_rupees(employee_esi_paise)),
                "pt": float(paise_to_rupees(pt_paise)),
                "lwf": float(paise_to_rupees(employee_lwf_paise)),
                "tds": float(paise_to_rupees(tds_paise)),
                "variable": float(paise_to_rupees(variable_deductions_paise)),
                "advance_recovery": float(paise_to_rupees(advance_deduction_paise)),
                "custom": {k: float(paise_to_rupees(v)) for k, v in custom_deduction_breakup.items()},
                "total_deductions": float(paise_to_rupees(emp_deductions_paise)),
                "employer_pf": float(paise_to_rupees(pf_res["total_employer_pf_paise"])),
                "employer_esi": float(paise_to_rupees(esi_res["employer_esi_paise"])),
                "employer_lwf": float(paise_to_rupees(lwf_res["employer_lwf_paise"])),
                "gratuity_provision": float(paise_to_rupees(grat_res["monthly_gratuity_provision_paise"])),
                "employer_custom": float(paise_to_rupees(custom_employer_paise)),
                "employer_ctc_monthly": float(paise_to_rupees(employer_cost_paise)),
                "pf_paise": employee_pf_paise,
                "esi_paise": employee_esi_paise,
                "pt_paise": pt_paise,
                "lwf_paise": employee_lwf_paise,
                "tds_paise": tds_paise,
                "advance_recovery_paise": advance_deduction_paise,
                "variable_deductions_paise": variable_deductions_paise,
                "custom_deductions_paise": custom_deductions_paise,
                "tax_regime": emp_regime,
                "total_deductions_paise": emp_deductions_paise,
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

            payslip.basic = paise_to_rupees(emp_basic_paise)
            payslip.hra = paise_to_rupees(emp_hra_paise)
            payslip.special_allowance = paise_to_rupees(emp_special_paise)
            payslip.conveyance = paise_to_rupees(emp_conveyance_paise)
            payslip.other_allowances_total = paise_to_rupees(emp_lta_paise + sum(emp_other_fixed_paise.values()) + emp_reimbursement_paise + custom_earnings_paise)
            payslip.arrears = paise_to_rupees(total_arrear_paise)
            payslip.bonus = paise_to_rupees(emp_statutory_bonus_paise + one_time_bonus_paise)
            payslip.lop_deduction = paise_to_rupees(max(0, (basic_monthly_paise + hra_monthly_paise + special_monthly_paise + conveyance_monthly_paise) - (emp_basic_paise + emp_hra_paise + emp_special_paise + emp_conveyance_paise)))
            payslip.other_deductions = paise_to_rupees(variable_deductions_paise + advance_deduction_paise + custom_deductions_paise)
            if sal:
                payslip.salary_structure_id = sal.id
            payslip.gross_earnings = paise_to_rupees(gross_paise)
            payslip.employee_pf = paise_to_rupees(employee_pf_paise)
            payslip.employer_pf = paise_to_rupees(pf_res["total_employer_pf_paise"])
            payslip.employee_esi = paise_to_rupees(employee_esi_paise)
            payslip.employer_esi = paise_to_rupees(esi_res["employer_esi_paise"])
            payslip.professional_tax = paise_to_rupees(pt_paise)
            payslip.tds = paise_to_rupees(tds_paise)
            payslip.total_deductions = paise_to_rupees(emp_deductions_paise)
            payslip.net_pay = paise_to_rupees(net_paise)
            payslip.payment_status = "PENDING"

            total_gross_paise += gross_paise
            total_deductions_paise += emp_deductions_paise
            total_net_paise += net_paise
            processed_count += 1

        ArrearService.mark_applied(pending_arrears, run.id)
        run.total_employees = processed_count
        run.total_gross_paise = total_gross_paise
        run.total_deductions_paise = total_deductions_paise
        run.total_net_paise = total_net_paise
        run.total_gross = paise_to_rupees(total_gross_paise)
        run.total_deductions = paise_to_rupees(total_deductions_paise)
        run.total_net = paise_to_rupees(total_net_paise)
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
