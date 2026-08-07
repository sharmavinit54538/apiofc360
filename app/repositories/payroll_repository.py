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

    async def get_cycle(self, cycle_id: uuid.UUID) -> Optional[PayCycle]:
        res = await self.session.execute(select(PayCycle).where(PayCycle.id == cycle_id))
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

        import asyncio
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

    async def get_ot_policy(self, policy_id: uuid.UUID) -> Optional[OvertimePolicy]:
        res = await self.session.execute(
            select(OvertimePolicy).where(OvertimePolicy.id == policy_id)
        )
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

    async def get_ot_entry(self, entry_id: uuid.UUID) -> Optional[OvertimeEntry]:
        res = await self.session.execute(
            select(OvertimeEntry).where(OvertimeEntry.id == entry_id)
        )
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

    async def get_bonus_plan(self, plan_id: uuid.UUID) -> Optional[BonusPlan]:
        res = await self.session.execute(select(BonusPlan).where(BonusPlan.id == plan_id))
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

    async def get_bonus_award(self, award_id: uuid.UUID) -> Optional[BonusAward]:
        res = await self.session.execute(select(BonusAward).where(BonusAward.id == award_id))
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

    async def get_deduction(self, deduction_id: uuid.UUID) -> Optional[DeductionComponent]:
        res = await self.session.execute(
            select(DeductionComponent).where(DeductionComponent.id == deduction_id)
        )
        return res.scalar_one_or_none()

    async def create_deduction(self, ded: DeductionComponent) -> DeductionComponent:
        self.session.add(ded)
        await self.session.flush()
        return ded

    async def delete_deduction(self, deduction_id: uuid.UUID) -> bool:
        ded = await self.get_deduction(deduction_id)
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

    async def get_loan(self, loan_id: uuid.UUID) -> Optional[AdvanceLoan]:
        res = await self.session.execute(
            select(AdvanceLoan)
            .options(selectinload(AdvanceLoan.installments))
            .where(AdvanceLoan.id == loan_id)
        )
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

    async def get_reimbursement(self, claim_id: uuid.UUID) -> Optional[ReimbursementClaim]:
        res = await self.session.execute(
            select(ReimbursementClaim).where(ReimbursementClaim.id == claim_id)
        )
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

    async def get_advice_file(self, file_id: uuid.UUID) -> Optional[BankAdviceFile]:
        res = await self.session.execute(
            select(BankAdviceFile)
            .options(selectinload(BankAdviceFile.disbursements))
            .where(BankAdviceFile.id == file_id)
        )
        return res.scalar_one_or_none()

    async def list_disbursements(
        self,
        advice_file_id: Optional[uuid.UUID] = None,
        pay_cycle_id: Optional[uuid.UUID] = None,
        employee_id: Optional[uuid.UUID] = None,
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
        if status:
            stmt = stmt.where(BankDisbursementRecord.status == status.upper())
        stmt = stmt.offset((page - 1) * limit).limit(limit)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def get_disbursement(self, disbursement_id: uuid.UUID) -> Optional[BankDisbursementRecord]:
        res = await self.session.execute(
            select(BankDisbursementRecord).where(BankDisbursementRecord.id == disbursement_id)
        )
        return res.scalar_one_or_none()

    # ------------------------------------------------------------------
    # PAYSLIPS (read-only — write side is payroll_service)
    # ------------------------------------------------------------------

    async def list_payslips(
        self,
        pay_cycle_id: Optional[uuid.UUID] = None,
        employee_id: Optional[uuid.UUID] = None,
        year: Optional[int] = None,
        page: int = 1,
        limit: int = 50,
    ) -> list[Payslip]:
        from sqlalchemy.orm import selectinload as sl
        stmt = select(Payslip).options(sl(Payslip.employee))
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

    async def get_payslip(self, payslip_id: uuid.UUID) -> Optional[Payslip]:
        from sqlalchemy.orm import selectinload as sl
        res = await self.session.execute(
            select(Payslip).options(sl(Payslip.employee)).where(Payslip.id == payslip_id)
        )
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

    async def get_obligation(self, obligation_id: uuid.UUID) -> Optional[ComplianceObligation]:
        res = await self.session.execute(
            select(ComplianceObligation)
            .options(selectinload(ComplianceObligation.documents))
            .where(ComplianceObligation.id == obligation_id)
        )
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
        self, employee_id: uuid.UUID, financial_year: str
    ) -> Optional[EmployeeInvestmentDeclaration]:
        res = await self.session.execute(
            select(EmployeeInvestmentDeclaration).where(
                EmployeeInvestmentDeclaration.employee_id == employee_id,
                EmployeeInvestmentDeclaration.financial_year == financial_year,
            )
        )
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

    async def get_payslips_for_cycle(self, pay_cycle_id: uuid.UUID) -> list[Payslip]:
        """Used for salary register export."""
        from sqlalchemy.orm import selectinload as sl
        res = await self.session.execute(
            select(Payslip)
            .options(sl(Payslip.employee))
            .where(Payslip.payroll_run_id == pay_cycle_id)
            .order_by(Payslip.employee_id)
        )
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
        self, pay_cycle_id: uuid.UUID
    ) -> list[dict]:
        """Return [{department, headcount, total_net}] for a pay cycle."""
        from sqlalchemy import text as sa_text
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
            .group_by(Employee.department)
        )
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
