"""Payroll repository — all async DB operations, zero business logic.

Pattern matches `employee_repository.py` and `manager_repository.py`.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, List, Optional

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.payroll import (
    AdvanceLoan,
    AdvanceLoanInstallment,
    BankAdviceFile,
    BankDisbursementRecord,
    BonusAward,
    BonusPlan,
    ComplianceDocument,
    ComplianceObligation,
    DeductionComponent,
    EmployeeInvestmentDeclaration,
    OvertimeEntry,
    OvertimePolicy,
    PayCycle,
    PayrollAttendanceInput,
    PayrollAuditLog,
    Payslip,
    ReimbursementClaim,
    SalaryStructure,
    TaxDeclarationProof,
)

logger = logging.getLogger(__name__)


class PayrollRepository:
    """Data access layer for all payroll-related tables."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # AUDIT LOG helpers (used across all sub-modules)
    # ------------------------------------------------------------------

    async def log_action(
        self,
        *,
        entity_type: str,
        action: str,
        actor_id: Optional[uuid.UUID] = None,
        actor_role: Optional[str] = None,
        pay_cycle_id: Optional[uuid.UUID] = None,
        entity_id: Optional[uuid.UUID] = None,
        company_id: Optional[uuid.UUID] = None,
        old_status: Optional[str] = None,
        new_status: Optional[str] = None,
        reason: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> PayrollAuditLog:
        log = PayrollAuditLog(
            id=uuid.uuid4(),
            pay_cycle_id=pay_cycle_id,
            company_id=company_id,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            actor_id=actor_id,
            actor_role=actor_role,
            old_status=old_status,
            new_status=new_status,
            reason=reason,
            extra_data=metadata,
        )
        self.session.add(log)
        return log

    # ------------------------------------------------------------------
    # PAY CYCLE
    # ------------------------------------------------------------------

    async def get_cycle(self, cycle_id: uuid.UUID, company_id: Optional[uuid.UUID] = None) -> Optional[PayCycle]:
        stmt = select(PayCycle).where(PayCycle.id == cycle_id)
        if company_id:
            stmt = stmt.where(PayCycle.company_id == company_id)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_cycle_by_period(
        self, company_id: Optional[uuid.UUID], month: int, year: int
    ) -> Optional[PayCycle]:
        stmt = select(PayCycle).where(
            PayCycle.period_month == month,
            PayCycle.period_year == year,
        )
        if company_id:
            stmt = stmt.where(PayCycle.company_id == company_id)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def list_cycles(
        self,
        company_id: Optional[uuid.UUID] = None,
        year: Optional[int] = None,
        month: Optional[int] = None,
        status: Optional[str] = None,
        page: int = 1,
        limit: int = 20,
    ) -> tuple[list[PayCycle], int]:
        stmt = select(PayCycle)
        count_stmt = select(func.count()).select_from(PayCycle)

        filters = []
        if company_id:
            filters.append(PayCycle.company_id == company_id)
        if year:
            filters.append(PayCycle.period_year == year)
        if month:
            filters.append(PayCycle.period_month == month)
        if status:
            filters.append(PayCycle.status == status.upper())

        if filters:
            stmt = stmt.where(*filters)
            count_stmt = count_stmt.where(*filters)

        stmt = stmt.order_by(PayCycle.period_year.desc(), PayCycle.period_month.desc())
        stmt = stmt.offset((page - 1) * limit).limit(limit)

        count_res = await self.session.execute(count_stmt)
        data_res = await self.session.execute(stmt)
        total = count_res.scalar() or 0
        return list(data_res.scalars().all()), total

    async def create_cycle(self, cycle: PayCycle) -> PayCycle:
        self.session.add(cycle)
        await self.session.flush()
        return cycle

    async def get_cycle_audit_logs(self, cycle_id: uuid.UUID) -> list[PayrollAuditLog]:
        stmt = (
            select(PayrollAuditLog)
            .where(PayrollAuditLog.pay_cycle_id == cycle_id)
            .order_by(PayrollAuditLog.created_at.desc())
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    # ------------------------------------------------------------------
    # OVERTIME POLICY
    # ------------------------------------------------------------------

    async def list_ot_policies(
        self, company_id: Optional[uuid.UUID] = None, active_only: bool = True
    ) -> list[OvertimePolicy]:
        stmt = select(OvertimePolicy)
        if company_id:
            stmt = stmt.where(OvertimePolicy.company_id == company_id)
        if active_only:
            stmt = stmt.where(OvertimePolicy.is_active == True)  # noqa: E712
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def get_ot_policy(self, policy_id: uuid.UUID, company_id: Optional[uuid.UUID] = None) -> Optional[OvertimePolicy]:
        stmt = select(OvertimePolicy).where(OvertimePolicy.id == policy_id)
        if company_id:
            stmt = stmt.where(OvertimePolicy.company_id == company_id)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def create_ot_policy(self, policy: OvertimePolicy) -> OvertimePolicy:
        self.session.add(policy)
        await self.session.flush()
        return policy

    # ------------------------------------------------------------------
    # OVERTIME ENTRY
    # ------------------------------------------------------------------

    async def list_ot_entries(
        self,
        company_id: Optional[uuid.UUID] = None,
        employee_id: Optional[uuid.UUID] = None,
        period_month: Optional[int] = None,
        period_year: Optional[int] = None,
        status: Optional[str] = None,
        page: int = 1,
        limit: int = 50,
    ) -> list[OvertimeEntry]:
        stmt = select(OvertimeEntry)
        if company_id:
            stmt = stmt.where(OvertimeEntry.company_id == company_id)
        if employee_id:
            stmt = stmt.where(OvertimeEntry.employee_id == employee_id)
        if period_month:
            stmt = stmt.where(OvertimeEntry.period_month == period_month)
        if period_year:
            stmt = stmt.where(OvertimeEntry.period_year == period_year)
        if status:
            stmt = stmt.where(OvertimeEntry.status == status.upper())
        stmt = stmt.offset((page - 1) * limit).limit(limit)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def get_ot_entry(self, entry_id: uuid.UUID, company_id: Optional[uuid.UUID] = None) -> Optional[OvertimeEntry]:
        stmt = select(OvertimeEntry).where(OvertimeEntry.id == entry_id)
        if company_id:
            stmt = stmt.where(OvertimeEntry.company_id == company_id)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_ot_entry_by_employee_period(
        self, employee_id: uuid.UUID, month: int, year: int
    ) -> Optional[OvertimeEntry]:
        res = await self.session.execute(
            select(OvertimeEntry).where(
                OvertimeEntry.employee_id == employee_id,
                OvertimeEntry.period_month == month,
                OvertimeEntry.period_year == year,
            )
        )
        return res.scalar_one_or_none()

    async def upsert_ot_entry(self, entry: OvertimeEntry) -> OvertimeEntry:
        self.session.add(entry)
        await self.session.flush()
        return entry

    # ------------------------------------------------------------------
    # BONUS PLANS & AWARDS
    # ------------------------------------------------------------------

    async def list_bonus_plans(
        self, company_id: Optional[uuid.UUID] = None, active_only: bool = True
    ) -> list[BonusPlan]:
        stmt = select(BonusPlan)
        if company_id:
            stmt = stmt.where(BonusPlan.company_id == company_id)
        if active_only:
            stmt = stmt.where(BonusPlan.is_active == True)  # noqa: E712
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def get_bonus_plan(self, plan_id: uuid.UUID, company_id: Optional[uuid.UUID] = None) -> Optional[BonusPlan]:
        stmt = select(BonusPlan).where(BonusPlan.id == plan_id)
        if company_id:
            stmt = stmt.where(BonusPlan.company_id == company_id)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def create_bonus_plan(self, plan: BonusPlan) -> BonusPlan:
        self.session.add(plan)
        await self.session.flush()
        return plan

    async def list_bonus_awards(
        self,
        company_id: Optional[uuid.UUID] = None,
        employee_id: Optional[uuid.UUID] = None,
        pay_cycle_id: Optional[uuid.UUID] = None,
        status: Optional[str] = None,
        page: int = 1,
        limit: int = 50,
    ) -> list[BonusAward]:
        stmt = select(BonusAward)
        if company_id:
            stmt = stmt.where(BonusAward.company_id == company_id)
        if employee_id:
            stmt = stmt.where(BonusAward.employee_id == employee_id)
        if pay_cycle_id:
            stmt = stmt.where(BonusAward.pay_cycle_id == pay_cycle_id)
        if status:
            stmt = stmt.where(BonusAward.status == status.upper())
        stmt = stmt.offset((page - 1) * limit).limit(limit)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def get_bonus_award(self, award_id: uuid.UUID, company_id: Optional[uuid.UUID] = None) -> Optional[BonusAward]:
        stmt = select(BonusAward).where(BonusAward.id == award_id)
        if company_id:
            stmt = stmt.where(BonusAward.company_id == company_id)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def create_bonus_award(self, award: BonusAward) -> BonusAward:
        self.session.add(award)
        await self.session.flush()
        return award

    # ------------------------------------------------------------------
    # DEDUCTIONS
    # ------------------------------------------------------------------

    async def list_deductions(
        self,
        employee_id: Optional[uuid.UUID] = None,
        pay_cycle_id: Optional[uuid.UUID] = None,
        deduction_type: Optional[str] = None,
        company_id: Optional[uuid.UUID] = None,
        page: int = 1,
        limit: int = 50,
    ) -> list[DeductionComponent]:
        stmt = select(DeductionComponent)
        if employee_id:
            stmt = stmt.where(DeductionComponent.employee_id == employee_id)
        if pay_cycle_id:
            stmt = stmt.where(DeductionComponent.pay_cycle_id == pay_cycle_id)
        if deduction_type:
            stmt = stmt.where(DeductionComponent.deduction_type == deduction_type.upper())
        if company_id:
            stmt = stmt.where(DeductionComponent.company_id == company_id)
        stmt = stmt.offset((page - 1) * limit).limit(limit)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def get_deduction(self, deduction_id: uuid.UUID, company_id: Optional[uuid.UUID] = None) -> Optional[DeductionComponent]:
        stmt = select(DeductionComponent).where(DeductionComponent.id == deduction_id)
        if company_id:
            stmt = stmt.where(DeductionComponent.company_id == company_id)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def create_deduction(self, ded: DeductionComponent) -> DeductionComponent:
        self.session.add(ded)
        await self.session.flush()
        return ded

    async def delete_deduction(self, deduction_id: uuid.UUID, company_id: Optional[uuid.UUID] = None) -> bool:
        ded = await self.get_deduction(deduction_id, company_id=company_id)
        if not ded:
            return False
        await self.session.delete(ded)
        return True

    # ------------------------------------------------------------------
    # ADVANCES & LOANS
    # ------------------------------------------------------------------

    async def list_loans(
        self,
        employee_id: Optional[uuid.UUID] = None,
        company_id: Optional[uuid.UUID] = None,
        status: Optional[str] = None,
        page: int = 1,
        limit: int = 20,
    ) -> list[AdvanceLoan]:
        stmt = select(AdvanceLoan)
        if employee_id:
            stmt = stmt.where(AdvanceLoan.employee_id == employee_id)
        if company_id:
            stmt = stmt.where(AdvanceLoan.company_id == company_id)
        if status:
            stmt = stmt.where(AdvanceLoan.status == status.upper())
        stmt = stmt.offset((page - 1) * limit).limit(limit)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def get_loan(self, loan_id: uuid.UUID, company_id: Optional[uuid.UUID] = None) -> Optional[AdvanceLoan]:
        stmt = select(AdvanceLoan).options(selectinload(AdvanceLoan.installments)).where(AdvanceLoan.id == loan_id)
        if company_id:
            stmt = stmt.where(AdvanceLoan.company_id == company_id)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def create_loan(self, loan: AdvanceLoan) -> AdvanceLoan:
        self.session.add(loan)
        await self.session.flush()
        return loan

    async def get_active_loans_for_period(
        self, month: int, year: int, company_id: Optional[uuid.UUID] = None
    ) -> list[AdvanceLoan]:
        """Return ACTIVE loans that should generate an EMI this period."""
        stmt = select(AdvanceLoan).where(
            AdvanceLoan.status == "ACTIVE",
            or_(
                AdvanceLoan.start_from_year < year,
                and_(
                    AdvanceLoan.start_from_year == year,
                    AdvanceLoan.start_from_month <= month,
                ),
            ),
        )
        if company_id:
            stmt = stmt.where(AdvanceLoan.company_id == company_id)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def get_installment_for_period(
        self, loan_id: uuid.UUID, month: int, year: int
    ) -> Optional[AdvanceLoanInstallment]:
        res = await self.session.execute(
            select(AdvanceLoanInstallment).where(
                AdvanceLoanInstallment.loan_id == loan_id,
                AdvanceLoanInstallment.period_month == month,
                AdvanceLoanInstallment.period_year == year,
            )
        )
        return res.scalar_one_or_none()

    # ------------------------------------------------------------------
    # REIMBURSEMENTS
    # ------------------------------------------------------------------

    async def list_reimbursements(
        self,
        employee_id: Optional[uuid.UUID] = None,
        pay_cycle_id: Optional[uuid.UUID] = None,
        status: Optional[str] = None,
        company_id: Optional[uuid.UUID] = None,
        page: int = 1,
        limit: int = 50,
    ) -> list[ReimbursementClaim]:
        stmt = select(ReimbursementClaim)
        if employee_id:
            stmt = stmt.where(ReimbursementClaim.employee_id == employee_id)
        if pay_cycle_id:
            stmt = stmt.where(ReimbursementClaim.pay_cycle_id == pay_cycle_id)
        if status:
            stmt = stmt.where(ReimbursementClaim.status == status.upper())
        if company_id:
            stmt = stmt.where(ReimbursementClaim.company_id == company_id)
        stmt = stmt.offset((page - 1) * limit).limit(limit)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def get_reimbursement(self, claim_id: uuid.UUID, company_id: Optional[uuid.UUID] = None) -> Optional[ReimbursementClaim]:
        stmt = select(ReimbursementClaim).where(ReimbursementClaim.id == claim_id)
        if company_id:
            stmt = stmt.where(ReimbursementClaim.company_id == company_id)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def create_reimbursement(self, claim: ReimbursementClaim) -> ReimbursementClaim:
        self.session.add(claim)
        await self.session.flush()
        return claim

    # ------------------------------------------------------------------
    # BANK TRANSFERS
    # ------------------------------------------------------------------

    async def create_advice_file(self, f: BankAdviceFile) -> BankAdviceFile:
        self.session.add(f)
        await self.session.flush()
        return f

    async def get_advice_file(self, file_id: uuid.UUID, company_id: Optional[uuid.UUID] = None) -> Optional[BankAdviceFile]:
        stmt = select(BankAdviceFile).options(selectinload(BankAdviceFile.disbursements)).where(BankAdviceFile.id == file_id)
        if company_id:
            stmt = stmt.where(BankAdviceFile.company_id == company_id)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def list_disbursements(
        self,
        advice_file_id: Optional[uuid.UUID] = None,
        pay_cycle_id: Optional[uuid.UUID] = None,
        employee_id: Optional[uuid.UUID] = None,
        company_id: Optional[uuid.UUID] = None,
        status: Optional[str] = None,
        page: int = 1,
        limit: int = 100,
    ) -> list[BankDisbursementRecord]:
        stmt = select(BankDisbursementRecord)
        if advice_file_id:
            stmt = stmt.where(BankDisbursementRecord.advice_file_id == advice_file_id)
        if pay_cycle_id:
            stmt = stmt.where(BankDisbursementRecord.pay_cycle_id == pay_cycle_id)
        if employee_id:
            stmt = stmt.where(BankDisbursementRecord.employee_id == employee_id)
        if company_id:
            stmt = stmt.where(BankDisbursementRecord.company_id == company_id)
        if status:
            stmt = stmt.where(BankDisbursementRecord.status == status.upper())
        stmt = stmt.offset((page - 1) * limit).limit(limit)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def get_disbursement(self, disbursement_id: uuid.UUID, company_id: Optional[uuid.UUID] = None) -> Optional[BankDisbursementRecord]:
        stmt = select(BankDisbursementRecord).where(BankDisbursementRecord.id == disbursement_id)
        if company_id:
            stmt = stmt.where(BankDisbursementRecord.company_id == company_id)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    # ------------------------------------------------------------------
    # PAYSLIPS (read-only — write side is payroll_service)
    # ------------------------------------------------------------------

    async def list_payslips(
        self,
        pay_cycle_id: Optional[uuid.UUID] = None,
        employee_id: Optional[uuid.UUID] = None,
        company_id: Optional[uuid.UUID] = None,
        year: Optional[int] = None,
        page: int = 1,
        limit: int = 50,
    ) -> list[Payslip]:
        from app.models.employee import Employee
        from sqlalchemy.orm import selectinload as sl
        stmt = select(Payslip).options(sl(Payslip.employee))
        if company_id:
            stmt = stmt.join(Employee, Payslip.employee_id == Employee.id).where(Employee.company_id == company_id)
        if pay_cycle_id:
            stmt = stmt.where(Payslip.payroll_run_id == pay_cycle_id)
        if employee_id:
            stmt = stmt.where(Payslip.employee_id == employee_id)
        if year:
            stmt = stmt.where(Payslip.period_year == year)
        stmt = stmt.order_by(Payslip.period_year.desc(), Payslip.period_month.desc())
        stmt = stmt.offset((page - 1) * limit).limit(limit)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def get_payslip(self, payslip_id: uuid.UUID, company_id: Optional[uuid.UUID] = None) -> Optional[Payslip]:
        from app.models.employee import Employee
        from sqlalchemy.orm import selectinload as sl
        stmt = select(Payslip).options(sl(Payslip.employee)).where(Payslip.id == payslip_id)
        if company_id:
            stmt = stmt.join(Employee, Payslip.employee_id == Employee.id).where(Employee.company_id == company_id)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    # ------------------------------------------------------------------
    # COMPLIANCE
    # ------------------------------------------------------------------

    async def list_obligations(
        self,
        company_id: Optional[uuid.UUID] = None,
        status: Optional[str] = None,
        obligation_type: Optional[str] = None,
        due_soon_days: Optional[int] = None,
        page: int = 1,
        limit: int = 50,
    ) -> list[ComplianceObligation]:
        stmt = select(ComplianceObligation)
        if company_id:
            stmt = stmt.where(ComplianceObligation.company_id == company_id)
        if status:
            stmt = stmt.where(ComplianceObligation.status == status.upper())
        if obligation_type:
            stmt = stmt.where(ComplianceObligation.obligation_type == obligation_type.upper())
        if due_soon_days is not None:
            from datetime import timedelta
            cutoff = date.today() + timedelta(days=due_soon_days)
            stmt = stmt.where(
                ComplianceObligation.due_date <= cutoff,
                ComplianceObligation.status == "PENDING",
            )
        stmt = stmt.order_by(ComplianceObligation.due_date.asc())
        stmt = stmt.offset((page - 1) * limit).limit(limit)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def get_obligation(self, obligation_id: uuid.UUID, company_id: Optional[uuid.UUID] = None) -> Optional[ComplianceObligation]:
        stmt = (
            select(ComplianceObligation)
            .options(selectinload(ComplianceObligation.documents))
            .where(ComplianceObligation.id == obligation_id)
        )
        if company_id:
            stmt = stmt.where(ComplianceObligation.company_id == company_id)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def create_obligation(self, o: ComplianceObligation) -> ComplianceObligation:
        self.session.add(o)
        await self.session.flush()
        return o

    async def create_compliance_document(self, doc: ComplianceDocument) -> ComplianceDocument:
        self.session.add(doc)
        await self.session.flush()
        return doc

    # ------------------------------------------------------------------
    # TAX MANAGEMENT
    # ------------------------------------------------------------------

    async def get_declaration(
        self, employee_id: uuid.UUID, financial_year: str, company_id: Optional[uuid.UUID] = None
    ) -> Optional[EmployeeInvestmentDeclaration]:
        from app.models.employee import Employee
        stmt = select(EmployeeInvestmentDeclaration).where(
            EmployeeInvestmentDeclaration.employee_id == employee_id,
            EmployeeInvestmentDeclaration.financial_year == financial_year,
        )
        if company_id:
            stmt = stmt.join(Employee, EmployeeInvestmentDeclaration.employee_id == Employee.id).where(Employee.company_id == company_id)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def list_declaration_proofs(self, declaration_id: uuid.UUID) -> list[TaxDeclarationProof]:
        res = await self.session.execute(
            select(TaxDeclarationProof).where(TaxDeclarationProof.declaration_id == declaration_id)
        )
        return list(res.scalars().all())

    async def create_declaration_proof(self, proof: TaxDeclarationProof) -> TaxDeclarationProof:
        self.session.add(proof)
        await self.session.flush()
        return proof

    async def get_payslips_for_year_by_employee(
        self, employee_id: uuid.UUID, year: int
    ) -> list[Payslip]:
        res = await self.session.execute(
            select(Payslip).where(
                Payslip.employee_id == employee_id,
                Payslip.period_year == year,
            ).order_by(Payslip.period_month)
        )
        return list(res.scalars().all())

    # ------------------------------------------------------------------
    # REPORTS / ANALYTICS
    # ------------------------------------------------------------------

    async def get_payslips_for_cycle(self, pay_cycle_id: uuid.UUID, company_id: Optional[uuid.UUID] = None) -> list[Payslip]:
        """Used for salary register export."""
        from app.models.employee import Employee
        from sqlalchemy.orm import selectinload as sl
        stmt = (
            select(Payslip)
            .options(sl(Payslip.employee))
            .where(Payslip.payroll_run_id == pay_cycle_id)
        )
        if company_id:
            stmt = stmt.join(Employee, Payslip.employee_id == Employee.id).where(Employee.company_id == company_id)
        stmt = stmt.order_by(Payslip.employee_id)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def get_pay_cycles_for_analytics(
        self,
        company_id: Optional[uuid.UUID] = None,
        limit: int = 12,
    ) -> list[PayCycle]:
        """Last N closed/disbursed cycles for trend analytics."""
        stmt = (
            select(PayCycle)
            .where(PayCycle.status.in_(["DISBURSED", "CLOSED", "APPROVED"]))
            .order_by(PayCycle.period_year.desc(), PayCycle.period_month.desc())
            .limit(limit)
        )
        if company_id:
            stmt = stmt.where(PayCycle.company_id == company_id)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def get_department_payroll_breakdown(
        self, pay_cycle_id: uuid.UUID, company_id: Optional[uuid.UUID] = None
    ) -> list[dict]:
        """Return [{department, headcount, total_net}] for a pay cycle."""
        from app.models.employee import Employee
        stmt = (
            select(
                Employee.department,
                func.count(Payslip.id).label("headcount"),
                func.sum(Payslip.gross_earnings).label("total_gross"),
                func.sum(Payslip.net_pay).label("total_net"),
            )
            .join(Employee, Payslip.employee_id == Employee.id)
            .where(Payslip.payroll_run_id == pay_cycle_id)
        )
        if company_id:
            stmt = stmt.where(Employee.company_id == company_id)
        stmt = stmt.group_by(Employee.department)
        res = await self.session.execute(stmt)
        rows = res.all()
        return [
            {
                "department": r.department or "Unassigned",
                "headcount": r.headcount,
                "total_gross": float(r.total_gross or 0),
                "total_net": float(r.total_net or 0),
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # BATCH LOADING METHODS FOR PAYROLL PROCESSING OPTIMIZATION
    # ------------------------------------------------------------------

    async def batch_get_salary_structures(
        self, employee_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, SalaryStructure]:
        """Batch load salary structures for multiple employees."""
        if not employee_ids:
            return {}
        stmt = select(SalaryStructure).where(
            and_(
                SalaryStructure.employee_id.in_(employee_ids),
                SalaryStructure.is_active == True,  # noqa: E712
            )
        )
        res = await self.session.execute(stmt)
        structures = res.scalars().all()
        return {s.employee_id: s for s in structures}

    async def batch_get_attendance_inputs(
        self, employee_ids: list[uuid.UUID], period_month: int, period_year: int
    ) -> dict[uuid.UUID, PayrollAttendanceInput]:
        """Batch load attendance inputs for multiple employees."""
        if not employee_ids:
            return {}
        stmt = select(PayrollAttendanceInput).where(
            and_(
                PayrollAttendanceInput.employee_id.in_(employee_ids),
                PayrollAttendanceInput.period_month == period_month,
                PayrollAttendanceInput.period_year == period_year,
            )
        )
        res = await self.session.execute(stmt)
        inputs = res.scalars().all()
        return {i.employee_id: i for i in inputs}

    async def batch_get_overtime_entries(
        self, employee_ids: list[uuid.UUID], period_month: int, period_year: int
    ) -> dict[uuid.UUID, OvertimeEntry]:
        """Batch load overtime entries for multiple employees."""
        if not employee_ids:
            return {}
        stmt = select(OvertimeEntry).where(
            and_(
                OvertimeEntry.employee_id.in_(employee_ids),
                OvertimeEntry.period_month == period_month,
                OvertimeEntry.period_year == period_year,
                OvertimeEntry.status.in_(["APPROVED", "PUSHED"]),
            )
        )
        res = await self.session.execute(stmt)
        entries = res.scalars().all()
        return {e.employee_id: e for e in entries}

    async def batch_get_bonus_awards(
        self, employee_ids: list[uuid.UUID], pay_cycle_id: uuid.UUID
    ) -> dict[uuid.UUID, Decimal]:
        """Batch load bonus awards for multiple employees."""
        if not employee_ids:
            return {}
        stmt = select(BonusAward.employee_id, BonusAward.amount).where(
            and_(
                BonusAward.employee_id.in_(employee_ids),
                BonusAward.pay_cycle_id == pay_cycle_id,
                BonusAward.status == "QUEUED",
            )
        )
        res = await self.session.execute(stmt)
        results = res.fetchall()
        # Sum amounts per employee
        result = {}
        for emp_id, amount in results:
            if emp_id in result:
                result[emp_id] += Decimal(str(amount))
            else:
                result[emp_id] = Decimal(str(amount))
        return result

    async def batch_get_reimbursement_claims(
        self, employee_ids: list[uuid.UUID], pay_cycle_id: uuid.UUID
    ) -> dict[uuid.UUID, Decimal]:
        """Batch load reimbursement claims for multiple employees."""
        if not employee_ids:
            return {}
        stmt = select(ReimbursementClaim.employee_id, ReimbursementClaim.amount).where(
            and_(
                ReimbursementClaim.employee_id.in_(employee_ids),
                ReimbursementClaim.pay_cycle_id == pay_cycle_id,
                ReimbursementClaim.status == "QUEUED",
            )
        )
        res = await self.session.execute(stmt)
        results = res.fetchall()
        result = {}
        for emp_id, amount in results:
            if emp_id in result:
                result[emp_id] += Decimal(str(amount))
            else:
                result[emp_id] = Decimal(str(amount))
        return result

    async def batch_get_voluntary_deductions(
        self, employee_ids: list[uuid.UUID], pay_cycle_id: uuid.UUID
    ) -> dict[uuid.UUID, Decimal]:
        """Batch load voluntary deductions for multiple employees."""
        if not employee_ids:
            return {}
        stmt = select(DeductionComponent.employee_id, DeductionComponent.amount).where(
            and_(
                DeductionComponent.employee_id.in_(employee_ids),
                DeductionComponent.pay_cycle_id == pay_cycle_id,
                DeductionComponent.deduction_type.notin_(["PF", "ESI", "PT", "TDS"]),
            )
        )
        res = await self.session.execute(stmt)
        results = res.fetchall()
        result = {}
        for emp_id, amount in results:
            if emp_id in result:
                result[emp_id] += Decimal(str(amount))
            else:
                result[emp_id] = Decimal(str(amount))
        return result

    async def batch_get_active_loans(
        self, employee_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, list[AdvanceLoan]]:
        """Batch load active loans for multiple employees."""
        if not employee_ids:
            return {}
        stmt = select(AdvanceLoan).where(
            and_(
                AdvanceLoan.employee_id.in_(employee_ids),
                AdvanceLoan.status == "ACTIVE",
            )
        )
        res = await self.session.execute(stmt)
        loans = res.scalars().all()
        result = {}
        for loan in loans:
            if loan.employee_id not in result:
                result[loan.employee_id] = []
            result[loan.employee_id].append(loan)
        return result

    async def batch_get_investment_declarations(
        self, employee_ids: list[uuid.UUID], financial_year: str
    ) -> dict[uuid.UUID, EmployeeInvestmentDeclaration]:
        """Batch load investment declarations for multiple employees."""
        if not employee_ids:
            return {}
        stmt = select(EmployeeInvestmentDeclaration).where(
            and_(
                EmployeeInvestmentDeclaration.employee_id.in_(employee_ids),
                EmployeeInvestmentDeclaration.financial_year == financial_year,
            )
        )
        res = await self.session.execute(stmt)
        declarations = res.scalars().all()
        return {d.employee_id: d for d in declarations}

    async def batch_get_bank_accounts(
        self, employee_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, EmployeeBankAccount]:
        """Batch load primary bank accounts for multiple employees."""
        if not employee_ids:
            return {}
        from sqlalchemy import select
        from app.models.employee_bank_account import EmployeeBankAccount
        stmt = select(EmployeeBankAccount).where(
            and_(
                EmployeeBankAccount.employee_id.in_(employee_ids),
                EmployeeBankAccount.is_primary == True,  # noqa: E712
            )
        )
        res = await self.session.execute(stmt)
        accounts = res.scalars().all()
        return {a.employee_id: a for a in accounts}

    async def batch_create_payslips(self, payslips: list[Payslip]) -> None:
        """Batch insert payslips using add_all."""
        if not payslips:
            return
        self.session.add_all(payslips)
        await self.session.flush()

    async def batch_create_loan_installments(self, installments: list[AdvanceLoanInstallment]) -> None:
        """Batch insert loan installments using add_all."""
        if not installments:
            return
        self.session.add_all(installments)
        await self.session.flush()

    async def batch_get_payroll_attendance_inputs(
        self, employee_ids: list[uuid.UUID], period_month: int, period_year: int
    ) -> dict[uuid.UUID, PayrollAttendanceInput]:
        """Batch load payroll attendance inputs for multiple employees."""
        if not employee_ids:
            return {}
        stmt = select(PayrollAttendanceInput).where(
            and_(
                PayrollAttendanceInput.employee_id.in_(employee_ids),
                PayrollAttendanceInput.period_month == period_month,
                PayrollAttendanceInput.period_year == period_year,
            )
        )
        res = await self.session.execute(stmt)
        inputs = res.scalars().all()
        return {i.employee_id: i for i in inputs}

    async def batch_get_overtime_entries_for_period(
        self, employee_ids: list[uuid.UUID], period_month: int, period_year: int
    ) -> dict[uuid.UUID, OvertimeEntry]:
        """Batch load overtime entries for multiple employees."""
        if not employee_ids:
            return {}
        stmt = select(OvertimeEntry).where(
            and_(
                OvertimeEntry.employee_id.in_(employee_ids),
                OvertimeEntry.period_month == period_month,
                OvertimeEntry.period_year == period_year,
                OvertimeEntry.status.in_(["APPROVED", "PUSHED"]),
            )
        )
        res = await self.session.execute(stmt)
        entries = res.scalars().all()
        return {e.employee_id: e for e in entries}

    async def batch_get_bonus_awards_for_cycle(
        self, employee_ids: list[uuid.UUID], pay_cycle_id: uuid.UUID
    ) -> dict[uuid.UUID, Decimal]:
        """Batch load bonus awards for multiple employees for a specific cycle."""
        if not employee_ids:
            return {}
        stmt = select(BonusAward.employee_id, BonusAward.amount).where(
            and_(
                BonusAward.employee_id.in_(employee_ids),
                BonusAward.pay_cycle_id == pay_cycle_id,
                BonusAward.status == "QUEUED",
            )
        )
        res = await self.session.execute(stmt)
        results = res.fetchall()
        result = {}
        for emp_id, amount in results:
            if emp_id in result:
                result[emp_id] += Decimal(str(amount))
            else:
                result[emp_id] = Decimal(str(amount))
        return result

    async def batch_get_reimbursement_claims_for_cycle(
        self, employee_ids: list[uuid.UUID], pay_cycle_id: uuid.UUID
    ) -> dict[uuid.UUID, Decimal]:
        """Batch load reimbursement claims for multiple employees for a specific cycle."""
        if not employee_ids:
            return {}
        stmt = select(ReimbursementClaim.employee_id, ReimbursementClaim.amount).where(
            and_(
                ReimbursementClaim.employee_id.in_(employee_ids),
                ReimbursementClaim.pay_cycle_id == pay_cycle_id,
                ReimbursementClaim.status == "QUEUED",
            )
        )
        res = await self.session.execute(stmt)
        results = res.fetchall()
        result = {}
        for emp_id, amount in results:
            if emp_id in result:
                result[emp_id] += Decimal(str(amount))
            else:
                result[emp_id] = Decimal(str(amount))
        return result

    async def batch_get_voluntary_deductions(
        self, employee_ids: list[uuid.UUID], pay_cycle_id: uuid.UUID
    ) -> dict[uuid.UUID, Decimal]:
        """Batch load voluntary deductions for multiple employees."""
        if not employee_ids:
            return {}
        stmt = select(DeductionComponent.employee_id, DeductionComponent.amount).where(
            and_(
                DeductionComponent.employee_id.in_(employee_ids),
                DeductionComponent.pay_cycle_id == pay_cycle_id,
                DeductionComponent.deduction_type.notin_(["PF", "ESI", "PT", "TDS"]),
            )
        )
        res = await self.session.execute(stmt)
        results = res.fetchall()
        result = {}
        for emp_id, amount in results:
            if emp_id in result:
                result[emp_id] += Decimal(str(amount))
            else:
                result[emp_id] = Decimal(str(amount))
        return result

    async def batch_get_active_loans(
        self, employee_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, list[AdvanceLoan]]:
        """Batch load active loans for multiple employees."""
        if not employee_ids:
            return {}
        stmt = select(AdvanceLoan).where(
            and_(
                AdvanceLoan.employee_id.in_(employee_ids),
                AdvanceLoan.status == "ACTIVE",
            )
        )
        res = await self.session.execute(stmt)
        loans = res.scalars().all()
        result = {}
        for loan in loans:
            if loan.employee_id not in result:
                result[loan.employee_id] = []
            result[loan.employee_id].append(loan)
        return result

    async def batch_get_investment_declarations(
        self, employee_ids: list[uuid.UUID], financial_year: str
    ) -> dict[uuid.UUID, EmployeeInvestmentDeclaration]:
        """Batch load investment declarations for multiple employees."""
        if not employee_ids:
            return {}
        stmt = select(EmployeeInvestmentDeclaration).where(
            and_(
                EmployeeInvestmentDeclaration.employee_id.in_(employee_ids),
                EmployeeInvestmentDeclaration.financial_year == financial_year,
            )
        )
        res = await self.session.execute(stmt)
        declarations = res.scalars().all()
        return {d.employee_id: d for d in declarations}

    async def batch_get_primary_bank_accounts(
        self, employee_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, EmployeeBankAccount]:
        """Batch load primary bank accounts for multiple employees."""
        if not employee_ids:
            return {}
        from app.models.employee_bank_account import EmployeeBankAccount
        stmt = select(EmployeeBankAccount).where(
            and_(
                EmployeeBankAccount.employee_id.in_(employee_ids),
                EmployeeBankAccount.is_primary == True,  # noqa: E712
            )
        )
        res = await self.session.execute(stmt)
        accounts = res.scalars().all()
        return {a.employee_id: a for a in accounts}
