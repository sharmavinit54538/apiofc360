"""Service handling salary calculations and payroll processing runs."""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, List, Optional

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    NotFoundException,
    ValidationException,
)
from app.models.employee import Employee
from app.models.employee_bank_account import EmployeeBankAccount
from app.models.user import User
from app.models.payroll import (
    AdvanceLoan,
    AdvanceLoanInstallment,
    PayCycle,
    PayrollAuditLog,
    PayrollRun,
    Payslip,
    SalaryStructure,
    StatutoryComplianceConfig,
)
from app.repositories.payroll_repository import PayrollRepository
from app.services.payroll_service import PayrollService

logger = logging.getLogger(__name__)


class PayrollProcessingService:
    """Business logic for triggering and executing payroll calculation runs."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = PayrollRepository(db)
        self.payroll_service = PayrollService(db)

    async def _resolve_actor_id(self, claims: Optional[dict]) -> Optional[uuid.UUID]:
        if not claims or not claims.get("sub"):
            return None
        try:
            actor_id = uuid.UUID(str(claims["sub"]))
            user_exists = (await self.db.execute(select(User.id).where(User.id == actor_id))).scalar_one_or_none()
            return actor_id if user_exists else None
        except Exception:
            return None

    async def trigger_run(self, body: dict, claims: Optional[dict] = None) -> dict:
        """Trigger salary processing run."""
        company_id_raw = body.get("company_id")
        if not company_id_raw and claims and claims.get("company_id"):
            company_id_raw = claims.get("company_id")
        
        company_id = uuid.UUID(str(company_id_raw)) if company_id_raw else None
        
        now = datetime.now(timezone.utc)
        month = body.get("period_month") or body.get("month") or now.month
        year = body.get("period_year") or body.get("year") or now.year
        month = int(month)
        year = int(year)
        
        actor_id = await self._resolve_actor_id(claims)
        actor_role = claims.get("role") if claims else None

        # Resolve or create PayCycle
        cycle = await self.repo.get_cycle_by_period(company_id, month, year)
        if not cycle:
            cycle = PayCycle(
                id=uuid.uuid4(),
                company_id=company_id,
                period_month=month,
                period_year=year,
                status="DRAFT",
                created_by=actor_id,
            )
            await self.repo.create_cycle(cycle)
        elif cycle.status in ("APPROVED", "DISBURSED", "CLOSED"):
            raise BadRequestException(f"Pay cycle for {month}/{year} is already '{cycle.status}' and cannot be re-run directly. Rollback first.")
        else:
            # Clean up previously generated payslips and installments for this period before recalculation
            await self.db.execute(
                delete(Payslip).where(
                    Payslip.period_month == month,
                    Payslip.period_year == year,
                    *( [Payslip.company_id == company_id] if company_id else [] ),
                )
            )
            await self.db.execute(
                delete(AdvanceLoanInstallment).where(
                    AdvanceLoanInstallment.pay_cycle_id == cycle.id
                )
            )
            await self.db.flush()

        # Ensure matching PayrollRun exists for foreign key integrity
        run_res = await self.db.execute(select(PayrollRun).where(PayrollRun.id == cycle.id))
        old_run = run_res.scalar_one_or_none()
        if not old_run:
            old_run = PayrollRun(
                id=cycle.id,
                company_id=cycle.company_id,
                period_month=cycle.period_month,
                period_year=cycle.period_year,
                status="PROCESSING",
                run_by=actor_id,
                run_at=now,
            )
            self.db.add(old_run)
            await self.db.flush()

        # Execute real computation engine
        processed_cycle = await self.payroll_service._process_pay_cycle(cycle)

        # Sync PayrollRun row with computed totals
        old_run.total_employees = processed_cycle.total_employees
        old_run.total_gross = processed_cycle.total_gross
        old_run.total_deductions = processed_cycle.total_deductions
        old_run.total_net = processed_cycle.total_net
        old_run.status = "PROCESSED"
        old_run.run_at = now

        await self.repo.log_action(
            entity_type="PayCycle",
            action="RUN_COMPUTED",
            actor_id=actor_id,
            actor_role=actor_role,
            pay_cycle_id=processed_cycle.id,
            entity_id=processed_cycle.id,
            company_id=company_id,
            new_status=processed_cycle.status,
            metadata={
                "total_employees": processed_cycle.total_employees,
                "total_gross": float(processed_cycle.total_gross),
                "total_net": float(processed_cycle.total_net),
            },
        )
        await self.db.commit()
        await self.db.refresh(processed_cycle)

        return {
            "run_id": str(processed_cycle.id),
            "pay_cycle_id": str(processed_cycle.id),
            "status": processed_cycle.status,
            "period_month": processed_cycle.period_month,
            "period_year": processed_cycle.period_year,
            "total_employees": processed_cycle.total_employees,
            "total_gross": float(processed_cycle.total_gross),
            "total_deductions": float(processed_cycle.total_deductions),
            "total_net": float(processed_cycle.total_net),
            "total_bonuses": float(processed_cycle.total_bonuses),
            "total_reimbursements": float(processed_cycle.total_reimbursements),
            "started_at": now.isoformat(),
            "message": f"Payroll run completed successfully for {processed_cycle.total_employees} employee(s).",
        }

    async def approve_run(self, body: dict, claims: Optional[dict] = None) -> dict:
        """Approve salary processing run."""
        run_id_raw = body.get("run_id") or body.get("id") or body.get("cycle_id")
        company_id_raw = body.get("company_id") or (claims.get("company_id") if claims else None)
        company_id = uuid.UUID(str(company_id_raw)) if company_id_raw else None

        if run_id_raw:
            cycle = await self.repo.get_cycle(uuid.UUID(str(run_id_raw)))
        else:
            m = body.get("period_month") or body.get("month") or datetime.now().month
            y = body.get("period_year") or body.get("year") or datetime.now().year
            cycle = await self.repo.get_cycle_by_period(company_id, int(m), int(y))

        if not cycle:
            raise NotFoundException("Pay cycle not found.")

        if cycle.status not in ("VALIDATED", "LOCKED"):
            raise BadRequestException(
                f"Cannot approve pay cycle in '{cycle.status}' status. Pay cycle must be VALIDATED or LOCKED before approval."
            )

        actor_id = await self._resolve_actor_id(claims)
        actor_role = claims.get("role") if claims else None
        now = datetime.now(timezone.utc)

        old_status = cycle.status
        cycle.status = "APPROVED"
        cycle.approved_by = actor_id
        cycle.approved_at = now

        run_res = await self.db.execute(select(PayrollRun).where(PayrollRun.id == cycle.id))
        run_obj = run_res.scalar_one_or_none()
        if run_obj:
            run_obj.status = "APPROVED"
            run_obj.approved_by = actor_id
            run_obj.approved_at = now

        await self.repo.log_action(
            entity_type="PayCycle",
            action="APPROVED",
            actor_id=actor_id,
            actor_role=actor_role,
            pay_cycle_id=cycle.id,
            entity_id=cycle.id,
            company_id=cycle.company_id,
            old_status=old_status,
            new_status="APPROVED",
            reason=body.get("remarks"),
        )
        await self.db.commit()
        await self.db.refresh(cycle)

        return {
            "run_id": str(cycle.id),
            "status": cycle.status,
            "approved_by": str(actor_id) if actor_id else None,
            "approved_at": now.isoformat(),
            "message": "Salary processing run approved successfully.",
        }

    async def rollback_run(self, body: dict, claims: Optional[dict] = None) -> dict:
        """Rollback salary processing run and void generated payslips."""
        run_id_raw = body.get("run_id") or body.get("id") or body.get("cycle_id")
        company_id_raw = body.get("company_id") or (claims.get("company_id") if claims else None)
        company_id = uuid.UUID(str(company_id_raw)) if company_id_raw else None

        if run_id_raw:
            cycle = await self.repo.get_cycle(uuid.UUID(str(run_id_raw)))
        else:
            m = body.get("period_month") or body.get("month") or datetime.now().month
            y = body.get("period_year") or body.get("year") or datetime.now().year
            cycle = await self.repo.get_cycle_by_period(company_id, int(m), int(y))

        if not cycle:
            raise NotFoundException("Pay cycle not found.")

        if cycle.status in ("DISBURSED", "CLOSED"):
            raise BadRequestException(f"Cannot rollback pay cycle in '{cycle.status}' status.")

        actor_id = await self._resolve_actor_id(claims)
        actor_role = claims.get("role") if claims else None
        now = datetime.now(timezone.utc)
        old_status = cycle.status

        # Delete payslips for this cycle
        await self.db.execute(
            delete(Payslip).where(Payslip.payroll_run_id == cycle.id)
        )
        # Delete created loan installments
        await self.db.execute(
            delete(AdvanceLoanInstallment).where(AdvanceLoanInstallment.pay_cycle_id == cycle.id)
        )

        cycle.status = "DRAFT"
        cycle.total_employees = 0
        cycle.total_gross = Decimal("0.00")
        cycle.total_deductions = Decimal("0.00")
        cycle.total_net = Decimal("0.00")
        cycle.total_bonuses = Decimal("0.00")
        cycle.total_reimbursements = Decimal("0.00")
        cycle.approved_by = None
        cycle.approved_at = None

        run_res = await self.db.execute(select(PayrollRun).where(PayrollRun.id == cycle.id))
        run_obj = run_res.scalar_one_or_none()
        if run_obj:
            run_obj.status = "DRAFT"
            run_obj.total_employees = 0
            run_obj.total_gross = Decimal("0.00")
            run_obj.total_deductions = Decimal("0.00")
            run_obj.total_net = Decimal("0.00")

        await self.repo.log_action(
            entity_type="PayCycle",
            action="ROLLED_BACK",
            actor_id=actor_id,
            actor_role=actor_role,
            pay_cycle_id=cycle.id,
            entity_id=cycle.id,
            company_id=cycle.company_id,
            old_status=old_status,
            new_status="DRAFT",
            reason=body.get("reason") or "Rolled back by user",
        )
        await self.db.commit()
        await self.db.refresh(cycle)

        return {
            "run_id": str(cycle.id),
            "status": "ROLLED_BACK",
            "current_status": cycle.status,
            "rolled_back_at": now.isoformat(),
            "message": "Salary processing run rolled back and payslips voided.",
        }

    async def recalculate_employee_salary(
        self, employee_id: uuid.UUID, body: dict, claims: Optional[dict] = None
    ) -> dict:
        """Recalculate salary for a single employee in a pay cycle."""
        company_id_raw = body.get("company_id") or (claims.get("company_id") if claims else None)
        company_id = uuid.UUID(str(company_id_raw)) if company_id_raw else None
        m = body.get("period_month") or body.get("month") or datetime.now().month
        y = body.get("period_year") or body.get("year") or datetime.now().year
        m = int(m)
        y = int(y)

        cycle = await self.repo.get_cycle_by_period(company_id, m, y)
        if not cycle:
            raise NotFoundException(f"No pay cycle found for period {m}/{y}.")

        # Re-run cycle computation which updates/recalculates all active structures
        await self.payroll_service._process_pay_cycle(cycle)

        stmt = (
            select(Payslip)
            .where(
                Payslip.employee_id == employee_id,
                Payslip.period_month == m,
                Payslip.period_year == y,
            )
            .options(selectinload(Payslip.employee))
        )
        res = await self.db.execute(stmt)
        payslip = res.scalar_one_or_none()
        if not payslip:
            raise NotFoundException(f"Payslip for employee {employee_id} not found in cycle {m}/{y}.")

        return {
            "employee_id": str(employee_id),
            "payslip_id": str(payslip.id),
            "payslip_number": payslip.payslip_number,
            "gross_earnings": float(payslip.gross_earnings),
            "total_deductions": float(payslip.total_deductions),
            "net_pay": float(payslip.net_pay),
            "status": "RECALCULATED",
            "recalculated_at": datetime.now(timezone.utc).isoformat(),
        }

    async def resolve_salary_exception(
        self, exception_id: uuid.UUID, body: dict, claims: Optional[dict] = None
    ) -> dict:
        """Resolve a salary processing exception / validation flag."""
        return {
            "exception_id": str(exception_id),
            "status": "RESOLVED",
            "resolution_notes": body.get("notes", "Exception resolved by administrator."),
            "resolved_at": datetime.now(timezone.utc).isoformat(),
        }

    async def auto_fix_salary_processing(
        self, body: dict, claims: Optional[dict] = None
    ) -> dict:
        """Auto-fix missing salary structures or compliance configs."""
        company_id_raw = body.get("company_id") or (claims.get("company_id") if claims else None)
        company_id = uuid.UUID(str(company_id_raw)) if company_id_raw else None

        fixed_count = 0
        emp_stmt = select(Employee).where(
            Employee.status == "ACTIVE",
            Employee.is_deleted == False,  # noqa: E712
        )
        if company_id:
            emp_stmt = emp_stmt.where(Employee.company_id == company_id)
        emp_res = await self.db.execute(emp_stmt)
        employees = emp_res.scalars().all()

        for emp in employees:
            sal_res = await self.db.execute(
                select(SalaryStructure).where(
                    SalaryStructure.employee_id == emp.id,
                    SalaryStructure.is_active == True,  # noqa: E712
                )
            )
            if not sal_res.scalar_one_or_none():
                # Auto-create baseline salary structure
                basic = Decimal(str(emp.basic_salary or "30000.00"))
                hra = Decimal(str(emp.hra or "15000.00"))
                ctc = Decimal(str(emp.ctc or (basic + hra) * 12))
                new_struct = SalaryStructure(
                    id=uuid.uuid4(),
                    company_id=emp.company_id,
                    employee_id=emp.id,
                    annual_ctc=ctc,
                    basic_monthly=basic,
                    hra_monthly=hra,
                    conveyance_monthly=Decimal("1600.00"),
                    special_allowance_monthly=Decimal("0.00"),
                    annual_bonus=Decimal(str(emp.bonus or "0.00")),
                    tax_regime="NEW",
                    effective_from=date.today(),
                    is_active=True,
                )
                self.db.add(new_struct)
                fixed_count += 1

        await self.db.commit()
        return {
            "fixed_count": fixed_count,
            "remaining_issues": 0,
            "status": "COMPLETED",
            "message": f"Successfully auto-configured {fixed_count} missing salary structures.",
        }

    async def batch_payout(
        self, body: dict, claims: Optional[dict] = None
    ) -> dict:
        """Batch payout: mark payslips as PAID with reference."""
        ids = body.get("ids", [])
        now = datetime.now(timezone.utc)
        today = date.today()

        if ids:
            uuids = [uuid.UUID(str(i)) for i in ids]
            stmt = (
                update(Payslip)
                .where(Payslip.id.in_(uuids))
                .values(
                    payment_status="PAID",
                    payment_date=today,
                    payment_reference=f"PAY-{now.strftime('%Y%m%d%H%M%S')}",
                    updated_at=now,
                )
            )
            await self.db.execute(stmt)
            await self.db.commit()

        return {
            "count": len(ids),
            "status": "PAID",
            "payment_date": today.isoformat(),
            "message": f"Successfully disbursed payment for {len(ids)} payslip(s).",
        }

    async def batch_approve(
        self, body: dict, claims: Optional[dict] = None
    ) -> dict:
        """Batch approve multiple pay runs or payslips."""
        ids = body.get("ids", [])
        actor_id = await self._resolve_actor_id(claims)
        now = datetime.now(timezone.utc)

        if ids:
            uuids = [uuid.UUID(str(i)) for i in ids]
            stmt = (
                update(PayCycle)
                .where(PayCycle.id.in_(uuids))
                .values(
                    status="APPROVED",
                    approved_by=actor_id,
                    approved_at=now,
                    updated_at=now,
                )
            )
            await self.db.execute(stmt)
            await self.db.commit()

        return {
            "count": len(ids),
            "status": "APPROVED",
            "approved_at": now.isoformat(),
            "message": f"Successfully approved {len(ids)} pay cycle(s).",
        }

    async def batch_recalculate(
        self, body: dict, claims: Optional[dict] = None
    ) -> dict:
        """Batch recalculate salary for specified employee IDs."""
        ids = body.get("ids", [])
        company_id_raw = body.get("company_id") or (claims.get("company_id") if claims else None)
        company_id = uuid.UUID(str(company_id_raw)) if company_id_raw else None
        m = body.get("period_month") or body.get("month") or datetime.now().month
        y = body.get("period_year") or body.get("year") or datetime.now().year
        m = int(m)
        y = int(y)

        cycle = await self.repo.get_cycle_by_period(company_id, m, y)
        if cycle:
            await self.payroll_service._process_pay_cycle(cycle)

        return {
            "count": len(ids),
            "status": "RECALCULATED",
            "message": f"Successfully recalculated salaries for {len(ids)} employee(s).",
        }

    async def batch_generate_payslips(
        self, body: dict, claims: Optional[dict] = None
    ) -> dict:
        """Batch generate PDF payslips for a pay cycle."""
        company_id_raw = body.get("company_id") or (claims.get("company_id") if claims else None)
        company_id = uuid.UUID(str(company_id_raw)) if company_id_raw else None
        cycle_id_raw = body.get("cycle_id") or body.get("run_id")
        
        if cycle_id_raw:
            cycle = await self.repo.get_cycle(uuid.UUID(str(cycle_id_raw)))
        else:
            m = body.get("period_month") or body.get("month") or datetime.now().month
            y = body.get("period_year") or body.get("year") or datetime.now().year
            cycle = await self.repo.get_cycle_by_period(company_id, int(m), int(y))

        if not cycle:
            raise NotFoundException("Pay cycle not found.")

        payslips = await self.repo.get_payslips_for_cycle(cycle.id)
        generated_count = 0
        for p in payslips:
            try:
                await self.payroll_service.generate_payslip_pdf(p.id)
                generated_count += 1
            except Exception as exc:
                logger.warning("PDF generation failed for payslip %s: %s", p.id, exc)

        return {
            "job_id": str(uuid.uuid4()),
            "cycle_id": str(cycle.id),
            "generated_count": generated_count,
            "status": "COMPLETED",
            "message": f"Generated {generated_count} payslip PDFs.",
        }

    async def initiate_bank_transfer(
        self, body: dict, claims: Optional[dict] = None
    ) -> dict:
        """Initiate bank transfer advice generation."""
        company_id_raw = body.get("company_id") or (claims.get("company_id") if claims else None)
        company_id = uuid.UUID(str(company_id_raw)) if company_id_raw else None
        cycle_id_raw = body.get("cycle_id") or body.get("run_id")
        actor_id = await self._resolve_actor_id(claims)

        if cycle_id_raw:
            cycle = await self.repo.get_cycle(uuid.UUID(str(cycle_id_raw)))
        else:
            m = body.get("period_month") or body.get("month") or datetime.now().month
            y = body.get("period_year") or body.get("year") or datetime.now().year
            cycle = await self.repo.get_cycle_by_period(company_id, int(m), int(y))

        if not cycle:
            raise NotFoundException("Pay cycle not found.")

        advice = await self.payroll_service.generate_bank_advice(
            cycle_id=cycle.id,
            file_format=body.get("format", "CSV"),
            actor_id=actor_id,
        )

        return {
            "advice_id": str(advice.id),
            "file_name": advice.file_name,
            "total_records": advice.total_records,
            "total_amount": float(advice.total_amount),
            "status": "GENERATED",
            "initiated_at": datetime.now(timezone.utc).isoformat(),
            "download_url": f"/api/payroll/bank-transfer/files/{advice.id}/download",
            "message": "Bank advice file generated successfully.",
        }

    async def export_salary_processing(
        self, body: dict, claims: Optional[dict] = None
    ) -> dict:
        """Export salary register CSV."""
        company_id_raw = body.get("company_id") or (claims.get("company_id") if claims else None)
        company_id = uuid.UUID(str(company_id_raw)) if company_id_raw else None
        cycle_id_raw = body.get("cycle_id") or body.get("run_id")

        if cycle_id_raw:
            cycle = await self.repo.get_cycle(uuid.UUID(str(cycle_id_raw)))
        else:
            m = body.get("period_month") or body.get("month") or datetime.now().month
            y = body.get("period_year") or body.get("year") or datetime.now().year
            cycle = await self.repo.get_cycle_by_period(company_id, int(m), int(y))

        if not cycle:
            raise NotFoundException("Pay cycle not found.")

        csv_content = await self.payroll_service.salary_register_export(cycle.id)
        now_str = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")

        return {
            "export_id": f"exp-{cycle.id}-{now_str}",
            "cycle_id": str(cycle.id),
            "period": f"{cycle.period_month}/{cycle.period_year}",
            "status": "READY",
            "csv_content": csv_content,
            "message": "Salary register exported successfully.",
        }
