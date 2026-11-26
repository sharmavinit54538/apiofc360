"""Database repository layer for Payroll Dashboard metrics & aggregations."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional

from sqlalchemy import and_, desc, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payroll.exceptions import NotFoundException
from app.models.company import Company
from app.models.core_modules import AttendanceRegularizationRequest
from app.models.employee import Employee
from app.models.employee_bank_account import EmployeeBankAccount
from app.models.leave import LeaveRequest
from app.models.payroll import (
    BankAdviceFile,
    BankDisbursementRecord,
    ComplianceObligation,
    PayCycle,
    PayrollRun,
    Payslip,
    SalaryStructure,
    StatutoryComplianceConfig,
)
from app.models.payroll_compliance import ComplianceDueDate
from app.models.payroll_models import (
    Compensation,
    CompensationRevision,
    PaymentBatch,
    PaymentBatchItem,
    PayrollPeriod,
    PayrollRunEmployee,
    VariableInput,
)

MONTH_ABBR = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)
INACTIVE_EMP_STATUSES = (
    "DISABLED", "INACTIVE", "DEACTIVATED", "ARCHIVED", "TERMINATED", "EXITED", "DELETED",
)
EXCLUDED_RUN_STATUSES = ("CANCELLED", "VOID", "REJECTED", "FAILED")


def _dec(val: Any) -> Decimal:
    if val is None or val == "":
        return Decimal("0")
    if isinstance(val, Decimal):
        return val
    try:
        return Decimal(str(val))
    except Exception:
        return Decimal("0")


def _to_paise(val: Any) -> int:
    d = _dec(val)
    return int((d * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _paise_to_float(paise: int) -> float:
    return float((Decimal(paise) / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _format_month_label(month: int, year: int) -> str:
    idx = max(1, min(12, month)) - 1
    return f"{MONTH_ABBR[idx]} {year}"


class PayrollRepository:
    """Strictly read-only, tenant-scoped SQL repository for Payroll Dashboard."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_company_currency(self, company_id: Optional[uuid.UUID]) -> str:
        if not company_id:
            return "INR"
        stmt = select(Company.currency).where(Company.id == company_id)
        currency = (await self.db.execute(stmt)).scalar_one_or_none()
        return (currency or "INR").upper()

    async def resolve_period(
        self,
        *,
        company_id: Optional[uuid.UUID],
        cycle_id: Optional[uuid.UUID] = None,
        month: Optional[int] = None,
        year: Optional[int] = None,
    ) -> tuple[Optional[PayrollPeriod], int, int]:
        """Resolve canonical period + target (month, year) cleanly for the tenant."""
        if cycle_id is not None:
            stmt = select(PayrollPeriod).where(PayrollPeriod.id == cycle_id)
            if company_id is not None:
                stmt = stmt.where(PayrollPeriod.company_id == company_id)
            period = (await self.db.execute(stmt)).scalar_one_or_none()
            if not period:
                raise NotFoundException(f"Payroll period '{cycle_id}' not found.")
            return period, int(period.period_month), int(period.period_year)

        now = datetime.now(timezone.utc)
        if month is not None or year is not None:
            target_month = int(month or now.month)
            target_year = int(year or now.year)
            stmt = (
                select(PayrollPeriod)
                .where(
                    PayrollPeriod.period_month == target_month,
                    PayrollPeriod.period_year == target_year,
                    PayrollPeriod.status != "VOID",
                )
                .order_by(desc(PayrollPeriod.updated_at), desc(PayrollPeriod.created_at))
                .limit(1)
            )
            if company_id is not None:
                stmt = stmt.where(PayrollPeriod.company_id == company_id)
            period = (await self.db.execute(stmt)).scalar_one_or_none()
            return period, target_month, target_year

        # Unspecified period -> prefer current calendar period, else most recent active period
        curr_stmt = (
            select(PayrollPeriod)
            .where(
                PayrollPeriod.period_month == now.month,
                PayrollPeriod.period_year == now.year,
                PayrollPeriod.status != "VOID",
            )
            .order_by(desc(PayrollPeriod.updated_at))
            .limit(1)
        )
        if company_id is not None:
            curr_stmt = curr_stmt.where(PayrollPeriod.company_id == company_id)
        period = (await self.db.execute(curr_stmt)).scalar_one_or_none()
        if period:
            return period, int(period.period_month), int(period.period_year)

        latest_stmt = (
            select(PayrollPeriod)
            .where(PayrollPeriod.status != "VOID")
            .order_by(
                desc(PayrollPeriod.period_year),
                desc(PayrollPeriod.period_month),
                desc(PayrollPeriod.created_at),
            )
            .limit(1)
        )
        if company_id is not None:
            latest_stmt = latest_stmt.where(PayrollPeriod.company_id == company_id)
        period = (await self.db.execute(latest_stmt)).scalar_one_or_none()
        if period:
            return period, int(period.period_month), int(period.period_year)

        return None, int(now.month), int(now.year)

    async def get_period_runs(
        self,
        *,
        company_id: Optional[uuid.UUID],
        period: Optional[PayrollPeriod],
        month: int,
        year: int,
    ) -> list[PayrollRun]:
        """Fetch all runs linked to the resolved period or calendar month."""
        stmt = select(PayrollRun)
        if company_id is not None:
            stmt = stmt.where(PayrollRun.company_id == company_id)

        if period is not None:
            month_cond = and_(
                PayrollRun.period_month == period.period_month,
                PayrollRun.period_year == period.period_year,
            )
            if period.legal_entity_id is not None:
                month_cond = and_(month_cond, PayrollRun.legal_entity_id == period.legal_entity_id)
            else:
                month_cond = and_(month_cond, PayrollRun.legal_entity_id.is_(None))
            stmt = stmt.where(or_(PayrollRun.period_id == period.id, and_(PayrollRun.period_id.is_(None), month_cond)))
        else:
            stmt = stmt.where(PayrollRun.period_month == month, PayrollRun.period_year == year)

        stmt = stmt.order_by(desc(PayrollRun.updated_at), desc(PayrollRun.created_at))
        return list((await self.db.execute(stmt)).scalars().all())

    async def get_recent_runs(
        self,
        *,
        company_id: Optional[uuid.UUID],
        legal_entity_id: Optional[uuid.UUID] = None,
        limit: int = 10,
    ) -> list[PayrollRun]:
        stmt = select(PayrollRun)
        if company_id is not None:
            stmt = stmt.where(PayrollRun.company_id == company_id)
        if legal_entity_id is not None:
            stmt = stmt.where(PayrollRun.legal_entity_id == legal_entity_id)
        stmt = stmt.order_by(
            desc(PayrollRun.period_year),
            desc(PayrollRun.period_month),
            desc(PayrollRun.created_at),
        ).limit(limit)
        return list((await self.db.execute(stmt)).scalars().all())

    async def get_bulk_run_enrichments(
        self,
        *,
        company_id: Optional[uuid.UUID],
        run_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, dict[str, Any]]:
        """Bulk aggregate payslips, employer contributions, and payment counts per run_id (zero N+1)."""
        result: dict[uuid.UUID, dict[str, Any]] = {
            rid: {
                "employee_ids": set(),
                "gross_paise": 0,
                "deductions_paise": 0,
                "net_paise": 0,
                "employer_contrib_paise": None,
                "paid_count": 0,
                "failed_payment_count": 0,
            }
            for rid in run_ids
        }
        if not run_ids:
            return result

        # 1. Payslips grouped by run
        ps_stmt = select(
            Payslip.payroll_run_id,
            Payslip.employee_id,
            Payslip.gross_earnings,
            Payslip.total_deductions,
            Payslip.net_pay,
            Payslip.employer_pf,
            Payslip.employer_esi,
            Payslip.payment_status,
        ).where(Payslip.payroll_run_id.in_(run_ids))
        if company_id is not None:
            ps_stmt = ps_stmt.where(Payslip.company_id == company_id)

        ps_rows = (await self.db.execute(ps_stmt)).all()
        ps_employer_by_run_emp: dict[tuple[uuid.UUID, uuid.UUID], int] = {}
        ps_paid_by_run: dict[uuid.UUID, set[uuid.UUID]] = {rid: set() for rid in run_ids}
        ps_failed_by_run: dict[uuid.UUID, set[uuid.UUID]] = {rid: set() for rid in run_ids}

        for row in ps_rows:
            rid, emp_id = row[0], row[1]
            info = result[rid]
            if emp_id in info["employee_ids"]:
                continue
            info["employee_ids"].add(emp_id)
            info["gross_paise"] += _to_paise(row[2])
            info["deductions_paise"] += _to_paise(row[3])
            info["net_paise"] += _to_paise(row[4])
            ps_empr = _to_paise(row[5]) + _to_paise(row[6])
            ps_employer_by_run_emp[(rid, emp_id)] = ps_empr
            p_status = str(row[7] or "").upper()
            if p_status == "PAID":
                ps_paid_by_run[rid].add(emp_id)
            elif p_status == "FAILED":
                ps_failed_by_run[rid].add(emp_id)

        # 2. PayrollRunEmployee breakdowns (adds LWF/EDLI/admin/gratuity/custom without double-counting)
        pre_stmt = select(
            PayrollRunEmployee.run_id,
            PayrollRunEmployee.employee_id,
            PayrollRunEmployee.gross_earnings_paise,
            PayrollRunEmployee.deductions_breakup,
        ).where(PayrollRunEmployee.run_id.in_(run_ids))
        if company_id is not None:
            pre_stmt = pre_stmt.where(PayrollRunEmployee.company_id == company_id)

        pre_rows = (await self.db.execute(pre_stmt)).all()
        empr_sum_by_run: dict[uuid.UUID, Optional[int]] = {}
        seen_pre: set[tuple[uuid.UUID, uuid.UUID]] = set()
        for rid, emp_id, gross_p, breakup in pre_rows:
            if (rid, emp_id) in seen_pre:
                continue
            seen_pre.add((rid, emp_id))
            if isinstance(breakup, dict) and breakup.get("employer_ctc_monthly") is not None:
                empr_total = max(0, _to_paise(breakup["employer_ctc_monthly"]) - int(gross_p or 0))
            elif isinstance(breakup, dict) and any(
                k in breakup
                for k in (
                    "employer_pf",
                    "employer_esi",
                    "employer_lwf",
                    "gratuity_provision",
                    "employer_custom",
                    "country_employer_contributions_paise",
                )
            ):
                empr_total = (
                    _to_paise(breakup.get("employer_pf"))
                    + _to_paise(breakup.get("employer_esi"))
                    + _to_paise(breakup.get("employer_lwf"))
                    + _to_paise(breakup.get("gratuity_provision"))
                    + _to_paise(breakup.get("employer_custom"))
                    + int(breakup.get("country_employer_contributions_paise") or 0)
                )
            elif (rid, emp_id) in ps_employer_by_run_emp:
                empr_total = ps_employer_by_run_emp[(rid, emp_id)]
            else:
                empr_total = None

            if empr_total is not None:
                empr_sum_by_run[rid] = (empr_sum_by_run.get(rid) or 0) + empr_total

        for (rid, emp_id), ps_empr in ps_employer_by_run_emp.items():
            if (rid, emp_id) not in seen_pre:
                empr_sum_by_run[rid] = (empr_sum_by_run.get(rid) or 0) + ps_empr

        # 3. Active PaymentBatchItem stats per run (excluding RETRIED / REJECTED batches)
        item_stmt = (
            select(
                PaymentBatch.run_id,
                PaymentBatchItem.employee_id,
                PaymentBatchItem.status,
            )
            .join(PaymentBatch, PaymentBatchItem.batch_id == PaymentBatch.id)
            .where(
                PaymentBatch.run_id.in_(run_ids),
                PaymentBatch.status != "REJECTED",
                PaymentBatchItem.status != "RETRIED",
                PaymentBatchItem.repayout_batch_id.is_(None),
            )
        )
        if company_id is not None:
            item_stmt = item_stmt.where(PaymentBatch.company_id == company_id)

        batch_paid_by_run: dict[uuid.UUID, set[uuid.UUID]] = {}
        batch_failed_by_run: dict[uuid.UUID, set[uuid.UUID]] = {}
        for rid, emp_id, b_status in (await self.db.execute(item_stmt)).all():
            st = str(b_status or "").upper()
            if st == "SUCCESS":
                batch_paid_by_run.setdefault(rid, set()).add(emp_id)
            elif st == "FAILED":
                batch_failed_by_run.setdefault(rid, set()).add(emp_id)

        for rid, info in result.items():
            info["employer_contrib_paise"] = empr_sum_by_run.get(rid)
            if rid in batch_paid_by_run or rid in batch_failed_by_run:
                paid_set = batch_paid_by_run.get(rid, set()) | ps_paid_by_run.get(rid, set())
                failed_set = batch_failed_by_run.get(rid, set())
            else:
                paid_set = ps_paid_by_run.get(rid, set())
                failed_set = ps_failed_by_run.get(rid, set())
            info["paid_count"] = len(paid_set)
            info["failed_payment_count"] = len(failed_set)

        return result

    async def get_period_financial_and_payment_data(
        self,
        *,
        company_id: Optional[uuid.UUID],
        effective_runs: list[PayrollRun],
        month: int,
        year: int,
    ) -> dict[str, Any]:
        """Compute exact distinct-employee financials, statutory totals, employer contribs & payment summary."""
        effective_ids = [r.id for r in effective_runs]

        # Resolve payslips for effective runs (or standalone payslips if no PayrollRun rows in legacy flows)
        ps_stmt = select(Payslip)
        if company_id is not None:
            ps_stmt = ps_stmt.where(Payslip.company_id == company_id)
        if effective_ids:
            ps_stmt = ps_stmt.where(Payslip.payroll_run_id.in_(effective_ids))
        else:
            # Exclude payslips owned by cancelled/void/rejected/failed runs
            ps_stmt = ps_stmt.join(PayrollRun, Payslip.payroll_run_id == PayrollRun.id).where(
                Payslip.period_month == month,
                Payslip.period_year == year,
                PayrollRun.status.notin_(EXCLUDED_RUN_STATUSES),
            )
            if company_id is not None:
                ps_stmt = ps_stmt.where(PayrollRun.company_id == company_id)

        payslips = list((await self.db.execute(ps_stmt)).scalars().all())
        dedup_payslips: dict[uuid.UUID, Payslip] = {}
        for p in payslips:
            existing = dedup_payslips.get(p.employee_id)
            if existing is None or (p.updated_at or p.created_at) >= (existing.updated_at or existing.created_at):
                dedup_payslips[p.employee_id] = p

        # Load PayrollRunEmployee breakdowns if effective_ids exist
        pre_map: dict[uuid.UUID, PayrollRunEmployee] = {}
        if effective_ids:
            pre_stmt = select(PayrollRunEmployee).where(PayrollRunEmployee.run_id.in_(effective_ids))
            if company_id is not None:
                pre_stmt = pre_stmt.where(PayrollRunEmployee.company_id == company_id)
            for item in (await self.db.execute(pre_stmt)).scalars().all():
                prev = pre_map.get(item.employee_id)
                if prev is None or (item.updated_at or item.created_at) >= (prev.updated_at or prev.created_at):
                    pre_map[item.employee_id] = item

        # Statutory & contribution accumulators in exact integer paise
        gross_p = 0
        ded_p = 0
        net_p = 0
        pf_emp_p = 0
        pf_empr_p = 0
        esi_emp_p = 0
        esi_empr_p = 0
        pt_p = 0
        tds_p = 0
        lwf_emp_p = 0
        lwf_empr_p = 0
        gratuity_p = 0
        edli_admin_p = 0
        other_empr_p = 0
        has_any_employer_record = False

        employee_net_by_emp: dict[uuid.UUID, int] = {}
        payslip_status_by_emp: dict[uuid.UUID, str] = {}

        if dedup_payslips:
            for emp_id, ps in dedup_payslips.items():
                has_any_employer_record = True
                emp_gross_p = _to_paise(ps.gross_earnings)
                emp_ded_p = _to_paise(ps.total_deductions)
                emp_net_p = _to_paise(ps.net_pay)

                gross_p += emp_gross_p
                ded_p += emp_ded_p
                net_p += emp_net_p
                employee_net_by_emp[emp_id] = emp_net_p
                payslip_status_by_emp[emp_id] = str(ps.payment_status or "PENDING").upper()

                ps_pf_emp = _to_paise(ps.employee_pf)
                ps_pf_empr = _to_paise(ps.employer_pf)
                ps_esi_emp = _to_paise(ps.employee_esi)
                ps_esi_empr = _to_paise(ps.employer_esi)
                ps_pt = _to_paise(ps.professional_tax)
                ps_tds = _to_paise(ps.tds)

                pf_emp_p += ps_pf_emp
                pf_empr_p += ps_pf_empr
                esi_emp_p += ps_esi_emp
                esi_empr_p += ps_esi_empr
                pt_p += ps_pt
                tds_p += ps_tds

                pre = pre_map.get(emp_id)
                if pre and isinstance(pre.deductions_breakup, dict):
                    bk = pre.deductions_breakup
                    lwf_emp_p += int(bk.get("lwf_paise") or _to_paise(bk.get("lwf")))
                    emp_lwf = _to_paise(bk.get("employer_lwf"))
                    emp_grat = _to_paise(bk.get("gratuity_provision"))
                    emp_cust = _to_paise(bk.get("employer_custom")) + int(bk.get("country_employer_contributions_paise") or 0)
                    lwf_empr_p += emp_lwf
                    gratuity_p += emp_grat
                    other_empr_p += emp_cust
                    if bk.get("employer_ctc_monthly") is not None:
                        ctc_minus_gross = max(0, _to_paise(bk["employer_ctc_monthly"]) - int(pre.gross_earnings_paise or emp_gross_p))
                        remainder = max(0, ctc_minus_gross - (ps_pf_empr + ps_esi_empr + emp_lwf + emp_grat + emp_cust))
                        edli_admin_p += remainder

            processed_emp_ids = set(dedup_payslips.keys())
        elif pre_map:
            for emp_id, pre in pre_map.items():
                has_any_employer_record = True
                gross_p += int(pre.gross_earnings_paise or 0)
                ded_p += int(pre.total_deductions_paise or 0)
                net_p += int(pre.net_pay_paise or 0)
                employee_net_by_emp[emp_id] = int(pre.net_pay_paise or 0)
                payslip_status_by_emp[emp_id] = "PENDING"
                if isinstance(pre.deductions_breakup, dict):
                    bk = pre.deductions_breakup
                    pf_emp_p += int(bk.get("pf_paise") or _to_paise(bk.get("pf")))
                    esi_emp_p += int(bk.get("esi_paise") or _to_paise(bk.get("esi")))
                    pt_p += int(bk.get("pt_paise") or _to_paise(bk.get("pt")))
                    tds_p += int(bk.get("tds_paise") or _to_paise(bk.get("tds")))
                    lwf_emp_p += int(bk.get("lwf_paise") or _to_paise(bk.get("lwf")))
                    emp_pf = _to_paise(bk.get("employer_pf"))
                    emp_esi = _to_paise(bk.get("employer_esi"))
                    emp_lwf = _to_paise(bk.get("employer_lwf"))
                    emp_grat = _to_paise(bk.get("gratuity_provision"))
                    emp_cust = _to_paise(bk.get("employer_custom")) + int(bk.get("country_employer_contributions_paise") or 0)
                    pf_empr_p += emp_pf
                    esi_empr_p += emp_esi
                    lwf_empr_p += emp_lwf
                    gratuity_p += emp_grat
                    other_empr_p += emp_cust
                    if bk.get("employer_ctc_monthly") is not None:
                        ctc_minus_gross = max(0, _to_paise(bk["employer_ctc_monthly"]) - int(pre.gross_earnings_paise or 0))
                        edli_admin_p += max(0, ctc_minus_gross - (emp_pf + emp_esi + emp_lwf + emp_grat + emp_cust))
            processed_emp_ids = set(pre_map.keys())
        else:
            processed_emp_ids = set()

        processed_count = len(processed_emp_ids)
        run_fallback_count = 0
        if processed_count == 0 and effective_runs:
            primary = effective_runs[0]
            run_fallback_count = int(primary.total_employees or 0)
            gross_p = int(primary.total_gross_paise or 0) or _to_paise(primary.total_gross)
            ded_p = int(primary.total_deductions_paise or 0) or _to_paise(primary.total_deductions)
            net_p = int(primary.total_net_paise or 0) or _to_paise(primary.total_net)

        # If a processed run has positive gross/employees from summary columns only (no payslip/PRE lines),
        # employer contribution records are genuinely unavailable -> mark None rather than fabricating 0!
        if has_any_employer_record:
            empr_total_p: Optional[int] = pf_empr_p + esi_empr_p + lwf_empr_p + edli_admin_p + gratuity_p + other_empr_p
        elif processed_count == 0 and run_fallback_count == 0 and gross_p == 0:
            empr_total_p = 0
        else:
            empr_total_p = None

        # Payment summary from PaymentBatch / PaymentBatchItem -> BankDisbursementRecord -> Payslip.payment_status
        batches: list[PaymentBatch] = []
        batch_items: list[PaymentBatchItem] = []
        if effective_ids:
            b_stmt = (
                select(PaymentBatch)
                .where(PaymentBatch.run_id.in_(effective_ids), PaymentBatch.status != "REJECTED")
                .order_by(desc(PaymentBatch.created_at))
            )
            if company_id is not None:
                b_stmt = b_stmt.where(PaymentBatch.company_id == company_id)
            batches = list((await self.db.execute(b_stmt)).scalars().all())
            batch_ids = [b.id for b in batches]
            if batch_ids:
                bi_stmt = select(PaymentBatchItem).where(
                    PaymentBatchItem.batch_id.in_(batch_ids),
                    PaymentBatchItem.status != "RETRIED",
                    PaymentBatchItem.repayout_batch_id.is_(None),
                )
                if company_id is not None:
                    bi_stmt = bi_stmt.where(PaymentBatchItem.company_id == company_id)
                batch_items = list((await self.db.execute(bi_stmt)).scalars().all())

        paid_emp_ids: set[uuid.UUID] = set()
        held_emp_ids: set[uuid.UUID] = set()
        failed_emp_ids: set[uuid.UUID] = set()
        pending_emp_ids: set[uuid.UUID] = set()
        paid_amt_p = 0
        held_amt_p = 0
        failed_amt_p = 0
        pending_amt_p = 0

        if batch_items:
            latest_item_by_emp: dict[uuid.UUID, PaymentBatchItem] = {}
            for item in batch_items:
                prev = latest_item_by_emp.get(item.employee_id)
                if prev is None or (item.updated_at or item.created_at) >= (prev.updated_at or prev.created_at):
                    latest_item_by_emp[item.employee_id] = item
            for emp_id, item in latest_item_by_emp.items():
                st = str(item.status or "PENDING").upper()
                amt = int(item.amount_paise or 0)
                if st == "SUCCESS":
                    paid_emp_ids.add(emp_id)
                    paid_amt_p += amt
                elif st == "HELD":
                    held_emp_ids.add(emp_id)
                    held_amt_p += amt
                elif st == "FAILED":
                    failed_emp_ids.add(emp_id)
                    failed_amt_p += amt
                else:
                    pending_emp_ids.add(emp_id)
                    pending_amt_p += amt
            # Account for processed employees not yet included in any batch item
            for emp_id, emp_net_p in employee_net_by_emp.items():
                if emp_id not in latest_item_by_emp:
                    ps_st = payslip_status_by_emp.get(emp_id, "PENDING")
                    if ps_st == "PAID":
                        paid_emp_ids.add(emp_id)
                        paid_amt_p += emp_net_p
                    elif ps_st == "HOLD":
                        held_emp_ids.add(emp_id)
                        held_amt_p += emp_net_p
                    elif ps_st == "FAILED":
                        failed_emp_ids.add(emp_id)
                        failed_amt_p += emp_net_p
                    else:
                        pending_emp_ids.add(emp_id)
                        pending_amt_p += emp_net_p
        else:
            # Check legacy BankDisbursementRecord via PayCycle for this period
            pc_stmt = select(PayCycle.id).where(PayCycle.period_month == month, PayCycle.period_year == year)
            if company_id is not None:
                pc_stmt = pc_stmt.where(PayCycle.company_id == company_id)
            pay_cycle_ids = list((await self.db.execute(pc_stmt)).scalars().all())
            disb_records: list[BankDisbursementRecord] = []
            if pay_cycle_ids:
                bd_stmt = select(BankDisbursementRecord).where(
                    BankDisbursementRecord.pay_cycle_id.in_(pay_cycle_ids)
                )
                if company_id is not None:
                    bd_stmt = bd_stmt.join(
                        BankAdviceFile, BankDisbursementRecord.advice_file_id == BankAdviceFile.id
                    ).where(BankAdviceFile.company_id == company_id)
                disb_records = list((await self.db.execute(bd_stmt)).scalars().all())

            if disb_records:
                disb_by_emp: dict[uuid.UUID, BankDisbursementRecord] = {}
                for rec in disb_records:
                    prev = disb_by_emp.get(rec.employee_id)
                    if prev is None or (rec.updated_at or rec.created_at) >= (prev.updated_at or prev.created_at):
                        disb_by_emp[rec.employee_id] = rec
                for emp_id, rec in disb_by_emp.items():
                    st = str(rec.status or "PENDING").upper()
                    amt = _to_paise(rec.amount)
                    if st == "SUCCESS":
                        paid_emp_ids.add(emp_id)
                        paid_amt_p += amt
                    elif st == "FAILED":
                        failed_emp_ids.add(emp_id)
                        failed_amt_p += amt
                    else:
                        pending_emp_ids.add(emp_id)
                        pending_amt_p += amt
                for emp_id, emp_net_p in employee_net_by_emp.items():
                    if emp_id not in disb_by_emp:
                        ps_st = payslip_status_by_emp.get(emp_id, "PENDING")
                        if ps_st == "PAID":
                            paid_emp_ids.add(emp_id)
                            paid_amt_p += emp_net_p
                        elif ps_st == "HOLD":
                            held_emp_ids.add(emp_id)
                            held_amt_p += emp_net_p
                        elif ps_st == "FAILED":
                            failed_emp_ids.add(emp_id)
                            failed_amt_p += emp_net_p
                        else:
                            pending_emp_ids.add(emp_id)
                            pending_amt_p += emp_net_p
            elif employee_net_by_emp:
                for emp_id, emp_net_p in employee_net_by_emp.items():
                    ps_st = payslip_status_by_emp.get(emp_id, "PENDING")
                    if ps_st == "PAID":
                        paid_emp_ids.add(emp_id)
                        paid_amt_p += emp_net_p
                    elif ps_st == "HOLD":
                        held_emp_ids.add(emp_id)
                        held_amt_p += emp_net_p
                    elif ps_st == "FAILED":
                        failed_emp_ids.add(emp_id)
                        failed_amt_p += emp_net_p
                    else:
                        pending_emp_ids.add(emp_id)
                        pending_amt_p += emp_net_p
            elif effective_runs and effective_runs[0].status == "PAID":
                paid_amt_p = net_p
                paid_count_fallback = run_fallback_count
            elif effective_runs and run_fallback_count > 0:
                pending_amt_p = net_p

        total_unpaid_p = max(0, net_p - paid_amt_p) if (employee_net_by_emp or net_p > 0) else 0
        paid_count = len(paid_emp_ids) if (batch_items or employee_net_by_emp) else (
            run_fallback_count if (effective_runs and effective_runs[0].status == "PAID") else 0
        )
        pending_count = len(pending_emp_ids) if (batch_items or employee_net_by_emp) else (
            0 if (effective_runs and effective_runs[0].status == "PAID") else run_fallback_count
        )

        # Compliance obligations / due dates for period
        pending_filings = 0
        overdue_filings = 0
        remitted_p = 0
        pending_liab_p = 0

        due_stmt = select(ComplianceDueDate).where(
            ComplianceDueDate.period_month == month,
            ComplianceDueDate.period_year == year,
        )
        if company_id is not None:
            due_stmt = due_stmt.where(ComplianceDueDate.company_id == company_id)
        due_rows = list((await self.db.execute(due_stmt)).scalars().all())
        for drow in due_rows:
            dst = str(drow.status or "PENDING").upper()
            if drow.amount_paid:
                remitted_p += _to_paise(drow.amount_paid)
            if dst in ("PENDING", "ECR_GENERATED"):
                pending_filings += 1
            elif dst == "OVERDUE" or drow.is_overdue:
                overdue_filings += 1

        ob_stmt = select(ComplianceObligation)
        if company_id is not None:
            ob_stmt = ob_stmt.where(ComplianceObligation.company_id == company_id)
        ob_stmt = ob_stmt.where(ComplianceObligation.period_label == f"{MONTH_ABBR[month - 1]}-{year}")
        ob_rows = list((await self.db.execute(ob_stmt)).scalars().all())
        for ob in ob_rows:
            ost = str(ob.status or "PENDING").upper()
            amt = _to_paise(ob.amount_due)
            if ost in ("FILED", "PAID"):
                remitted_p += amt
            elif ost in ("PENDING", "OVERDUE"):
                pending_liab_p += amt
                if not due_rows:
                    pending_filings += 1
                    if ost == "OVERDUE":
                        overdue_filings += 1

        if pending_liab_p == 0 and empr_total_p is not None:
            stat_total_p = (
                pf_emp_p + esi_emp_p + pt_p + tds_p + lwf_emp_p
                + pf_empr_p + esi_empr_p + lwf_empr_p + edli_admin_p
            )
            pending_liab_p = max(0, stat_total_p - remitted_p)

        return {
            "processed_count": processed_count if processed_count > 0 else run_fallback_count,
            "has_employee_lines": bool(dedup_payslips or pre_map),
            "gross_paise": gross_p,
            "deductions_paise": ded_p,
            "net_paise": net_p,
            "employer_contrib_paise": empr_total_p,
            "pf_emp_paise": pf_emp_p,
            "pf_empr_paise": pf_empr_p,
            "esi_emp_paise": esi_emp_p,
            "esi_empr_paise": esi_empr_p,
            "pt_paise": pt_p,
            "tds_paise": tds_p,
            "lwf_emp_paise": lwf_emp_p,
            "lwf_empr_paise": lwf_empr_p,
            "edli_admin_paise": edli_admin_p,
            "gratuity_paise": gratuity_p,
            "other_empr_paise": other_empr_p,
            "has_employer_record": has_any_employer_record,
            "paid_count": paid_count,
            "pending_payment_count": pending_count,
            "held_count": len(held_emp_ids),
            "failed_payment_count": len(failed_emp_ids),
            "paid_amount_paise": paid_amt_p,
            "pending_amount_paise": total_unpaid_p,
            "held_amount_paise": held_amt_p,
            "failed_amount_paise": failed_amt_p,
            "batch_count": len(batches),
            "latest_batch_status": batches[0].status if batches else None,
            "remitted_paise": remitted_p,
            "pending_liabilities_paise": pending_liab_p,
            "pending_filings_count": pending_filings,
            "overdue_filings_count": overdue_filings,
        }

    async def get_readiness_and_approvals(
        self,
        *,
        company_id: Optional[uuid.UUID],
        period: Optional[PayrollPeriod],
        month: int,
        year: int,
        runs: list[PayrollRun],
    ) -> dict[str, Any]:
        """Execute read-only SQL checks for eligible employees, prerequisites, exceptions & approvals."""
        has_bank_expr = exists(
            select(EmployeeBankAccount.id).where(EmployeeBankAccount.employee_id == Employee.id)
        )
        has_comp_expr = exists(
            select(Compensation.id).where(
                Compensation.employee_id == Employee.id,
                Compensation.status == "ACTIVE",
            )
        )
        has_sal_expr = exists(
            select(SalaryStructure.id).where(
                SalaryStructure.employee_id == Employee.id,
                SalaryStructure.is_active == True,  # noqa: E712
            )
        )
        emp_stmt = select(
            Employee.id,
            Employee.first_name,
            Employee.last_name,
            Employee.pan_number,
            has_bank_expr.label("has_bank"),
            has_comp_expr.label("has_comp"),
            has_sal_expr.label("has_sal"),
        ).where(
            Employee.is_deleted == False,  # noqa: E712
            Employee.is_active == True,  # noqa: E712
            Employee.status.notin_(INACTIVE_EMP_STATUSES),
            Employee.employment_status.notin_(("EXITED", "TERMINATED")),
        )
        if company_id is not None:
            emp_stmt = emp_stmt.where(Employee.company_id == company_id)
        if period is not None and period.legal_entity_id is not None:
            emp_stmt = emp_stmt.where(Employee.legal_entity_id == period.legal_entity_id)

        employees = (await self.db.execute(emp_stmt)).all()
        eligible_count = len(employees)
        missing_pan = []
        missing_bank = []
        missing_comp = []

        for eid, fname, lname, pan, has_bank, has_comp, has_sal in employees:
            full_name = f"{fname or ''} {lname or ''}".strip() or "Employee"
            if not pan:
                missing_pan.append((str(eid), full_name))
            if not has_bank:
                missing_bank.append((str(eid), full_name))
            if not has_comp and not has_sal:
                missing_comp.append((str(eid), full_name))

        # Pending approvals across queues (exact SQL counts)
        runs_pending_stmt = select(func.count(PayrollRun.id)).where(
            PayrollRun.status.in_(("PENDING_APPROVAL", "UNDER_REVIEW"))
        )
        if company_id is not None:
            runs_pending_stmt = runs_pending_stmt.where(PayrollRun.company_id == company_id)
        runs_pending_approval = int((await self.db.execute(runs_pending_stmt)).scalar() or 0)

        var_stmt = select(func.count(VariableInput.id)).where(VariableInput.status == "PENDING")
        if company_id is not None:
            var_stmt = var_stmt.where(VariableInput.company_id == company_id)
        if period is not None:
            var_stmt = var_stmt.where(VariableInput.period_id == period.id)
        variable_inputs_pending = int((await self.db.execute(var_stmt)).scalar() or 0)

        rev_stmt = select(func.count(CompensationRevision.id)).where(CompensationRevision.status == "PENDING")
        if company_id is not None:
            rev_stmt = rev_stmt.where(CompensationRevision.company_id == company_id)
        compensation_revisions_pending = int((await self.db.execute(rev_stmt)).scalar() or 0)

        att_reg_stmt = select(func.count(AttendanceRegularizationRequest.id)).where(
            AttendanceRegularizationRequest.status == "PENDING"
        )
        if company_id is not None:
            att_reg_stmt = att_reg_stmt.where(AttendanceRegularizationRequest.company_id == company_id)
        attendance_regularizations_pending = int((await self.db.execute(att_reg_stmt)).scalar() or 0)

        leave_stmt = (
            select(func.count(LeaveRequest.id))
            .join(Employee, LeaveRequest.employee_id == Employee.id)
            .where(LeaveRequest.status == "PENDING", Employee.is_deleted == False)  # noqa: E712
        )
        if company_id is not None:
            leave_stmt = leave_stmt.where(Employee.company_id == company_id)
        if period is not None and period.start_date and period.end_date:
            leave_stmt = leave_stmt.where(
                LeaveRequest.start_date <= period.end_date,
                LeaveRequest.end_date >= period.start_date,
            )
        leave_requests_pending = int((await self.db.execute(leave_stmt)).scalar() or 0)

        # Active statutory configuration check
        cfg_stmt = select(StatutoryComplianceConfig).where(StatutoryComplianceConfig.is_active == True)  # noqa: E712
        if company_id is not None:
            cfg_stmt = cfg_stmt.where(
                or_(
                    StatutoryComplianceConfig.company_id == company_id,
                    StatutoryComplianceConfig.company_id.is_(None),
                )
            )
        cfg = (
            await self.db.execute(
                cfg_stmt.order_by(StatutoryComplianceConfig.company_id.desc().nulls_last()).limit(1)
            )
        ).scalar_one_or_none()

        # Run-level persisted validation errors / issues (deduplicated)
        errors_list: list[dict[str, Any]] = []
        warnings_list: list[dict[str, Any]] = []
        affected_emp_ids: set[str] = set()
        seen_issue_keys: set[tuple[str, str]] = set()

        effective_runs = [r for r in runs if r.status not in EXCLUDED_RUN_STATUSES]
        active_run = effective_runs[0] if effective_runs else (runs[0] if runs else None)
        if active_run:
            # Check PayrollRunEmployee validation errors/warnings first
            pre_issues = (
                await self.db.execute(
                    select(
                        PayrollRunEmployee.employee_id,
                        Employee.first_name,
                        Employee.last_name,
                        PayrollRunEmployee.validation_status,
                        PayrollRunEmployee.validation_messages,
                    )
                    .join(Employee, PayrollRunEmployee.employee_id == Employee.id)
                    .where(
                        PayrollRunEmployee.run_id == active_run.id,
                        PayrollRunEmployee.validation_status.in_(("ERROR", "WARNING")),
                    )
                )
            ).all()
            for emp_id, fname, lname, vst, msgs in pre_issues:
                ename = f"{fname or ''} {lname or ''}".strip() or "Employee"
                affected_emp_ids.add(str(emp_id))
                is_err = vst == "ERROR"
                for idx, m in enumerate(msgs or ["Validation check failed"]):
                    key = (str(emp_id), str(m))
                    if key in seen_issue_keys:
                        continue
                    seen_issue_keys.add(key)
                    item = {
                        "id": f"pre-{emp_id}-{idx}",
                        "type": "error" if is_err else "warning",
                        "category": "Payroll Calculation Validation",
                        "message": str(m),
                        "employee_id": str(emp_id),
                        "employee_name": ename,
                        "blocking": is_err,
                    }
                    (errors_list if is_err else warnings_list).append(item)

            if active_run.validation_errors and isinstance(active_run.validation_errors, list):
                for idx, entry in enumerate(active_run.validation_errors):
                    if isinstance(entry, dict) and entry.get("employee_id") and isinstance(entry.get("issues"), list):
                        emp_id_str = str(entry["employee_id"])
                        ename = str(entry.get("name") or "Employee")
                        for j, msg in enumerate(entry["issues"]):
                            key = (emp_id_str, str(msg))
                            if key in seen_issue_keys:
                                continue
                            seen_issue_keys.add(key)
                            affected_emp_ids.add(emp_id_str)
                            is_blocking = "compensation" in str(msg).lower() or "salary" in str(msg).lower()
                            target = errors_list if is_blocking else warnings_list
                            target.append({
                                "id": f"val-{emp_id_str}-{j}",
                                "type": "error" if is_blocking else "warning",
                                "category": "Pre-Run Validation",
                                "message": f"{ename}: {msg}",
                                "employee_id": emp_id_str,
                                "employee_name": ename,
                                "blocking": is_blocking,
                            })
                    elif isinstance(entry, dict) and (entry.get("detail") or entry.get("message")):
                        msg = str(entry.get("detail") or entry.get("message"))
                        key = ("run", msg)
                        if key not in seen_issue_keys:
                            seen_issue_keys.add(key)
                            errors_list.append({
                                "id": f"run-err-{idx}",
                                "type": "error",
                                "category": str(entry.get("code") or "Run Processing"),
                                "message": msg,
                                "blocking": True,
                            })

        # Add live missing salary structure & missing bank/PAN readiness gaps if not already captured
        for eid, ename in missing_comp:
            key = (eid, "No active Compensation or Salary Structure defined")
            if key not in seen_issue_keys:
                seen_issue_keys.add(key)
                affected_emp_ids.add(eid)
                errors_list.append({
                    "id": f"comp-{eid}",
                    "type": "error",
                    "category": "Salary Structures",
                    "message": f"{ename}: No active Compensation or Salary Structure defined",
                    "employee_id": eid,
                    "employee_name": ename,
                    "blocking": True,
                })
        for eid, ename in missing_bank:
            key = (eid, "Missing primary bank account")
            if key not in seen_issue_keys:
                seen_issue_keys.add(key)
                affected_emp_ids.add(eid)
                warnings_list.append({
                    "id": f"bank-{eid}",
                    "type": "warning",
                    "category": "Employee Data",
                    "message": f"{ename}: Missing primary bank account",
                    "employee_id": eid,
                    "employee_name": ename,
                    "blocking": False,
                })
        for eid, ename in missing_pan:
            key = (eid, "Missing PAN number")
            if key not in seen_issue_keys:
                seen_issue_keys.add(key)
                affected_emp_ids.add(eid)
                warnings_list.append({
                    "id": f"pan-{eid}",
                    "type": "warning",
                    "category": "Employee Data",
                    "message": f"{ename}: Missing PAN number",
                    "employee_id": eid,
                    "employee_name": ename,
                    "blocking": False,
                })

        readiness_items = [
            {
                "area": "Employee Data",
                "status": "Error" if eligible_count == 0 else ("Warning" if (missing_pan or missing_bank) else "Ready"),
                "details": (
                    "No active eligible employees found"
                    if eligible_count == 0
                    else (
                        f"{len(missing_bank)} missing bank account, {len(missing_pan)} missing PAN"
                        if (missing_bank or missing_pan)
                        else f"{eligible_count} active employees verified"
                    )
                ),
            },
            {
                "area": "Salary Structures",
                "status": "Error" if missing_comp else ("Warning" if eligible_count == 0 else "Ready"),
                "details": (
                    f"{len(missing_comp)} active employees lack Compensation or Salary Structure"
                    if missing_comp
                    else "All active employees have compensation assigned"
                ),
            },
            {
                "area": "Attendance",
                "status": (
                    "Warning"
                    if (period is not None and period.attendance_locked_at is None) or attendance_regularizations_pending > 0
                    else "Ready"
                ),
                "details": (
                    f"{attendance_regularizations_pending} pending regularization(s)"
                    if attendance_regularizations_pending > 0
                    else ("Attendance unlocked" if period and period.attendance_locked_at is None else "Attendance synchronized")
                ),
            },
            {
                "area": "Leave Data",
                "status": "Warning" if leave_requests_pending > 0 else "Ready",
                "details": (
                    f"{leave_requests_pending} pending leave request(s) in cycle"
                    if leave_requests_pending > 0
                    else "No pending leave approvals in cycle"
                ),
            },
            {
                "area": "Tax / Statutory Configuration",
                "status": "Warning" if cfg is None else "Ready",
                "details": "Active statutory rates configured" if cfg else "Using default statutory rules (company config not saved)",
            },
        ]

        approved_runs_count = sum(1 for r in runs if r.status in ("APPROVED", "FINALIZED", "LOCKED", "PAID"))
        rejected_runs_count = sum(1 for r in runs if r.status == "REJECTED")
        total_pending_approvals = (
            runs_pending_approval
            + variable_inputs_pending
            + compensation_revisions_pending
        )

        approval_status = "NOT_SUBMITTED"
        if runs_pending_approval > 0:
            approval_status = "PENDING_APPROVAL"
        elif approved_runs_count > 0:
            approval_status = "APPROVED"
        elif rejected_runs_count > 0:
            approval_status = "REJECTED"

        blocking_count = sum(1 for item in readiness_items if item["status"] == "Error")
        warning_count = sum(1 for item in readiness_items if item["status"] == "Warning")

        return {
            "eligible_employees": eligible_count,
            "readiness": {
                "items": readiness_items,
                "is_ready": blocking_count == 0 and eligible_count > 0,
                "blocking_count": blocking_count,
                "warning_count": warning_count,
            },
            "issues": {
                "errors": errors_list[:50],
                "warnings": warnings_list[:50],
                "unique_employee_count": len(affected_emp_ids),
                "total_error_count": len(errors_list),
                "total_warning_count": len(warnings_list),
            },
            "approval_summary": {
                "pending_count": total_pending_approvals,
                "runs_pending_approval": runs_pending_approval,
                "variable_inputs_pending": variable_inputs_pending,
                "compensation_revisions_pending": compensation_revisions_pending,
                "attendance_regularizations_pending": attendance_regularizations_pending,
                "leave_requests_pending": leave_requests_pending,
                "approved_runs_count": approved_runs_count,
                "rejected_runs_count": rejected_runs_count,
                "status": approval_status,
            },
        }

    async def get_monthly_trends(
        self,
        *,
        company_id: Optional[uuid.UUID],
        legal_entity_id: Optional[uuid.UUID] = None,
        limit: int = 12,
    ) -> list[dict[str, Any]]:
        """Build chronological monthly trend series from real non-cancelled payroll runs (oldest -> newest)."""
        stmt = select(PayrollRun).where(PayrollRun.status.notin_(EXCLUDED_RUN_STATUSES))
        if company_id is not None:
            stmt = stmt.where(PayrollRun.company_id == company_id)
        if legal_entity_id is not None:
            stmt = stmt.where(PayrollRun.legal_entity_id == legal_entity_id)
        stmt = stmt.order_by(
            desc(PayrollRun.period_year),
            desc(PayrollRun.period_month),
            desc(PayrollRun.created_at),
        ).limit(limit * 3)

        all_runs = list((await self.db.execute(stmt)).scalars().all())
        if not all_runs:
            return []

        # Deduplicate to authoritative run per (year, month) if multiple entities weren't filtered,
        # OR aggregate across distinct entities within a month cleanly via bulk enrichment
        enrichments = await self.get_bulk_run_enrichments(
            company_id=company_id, run_ids=[r.id for r in all_runs]
        )

        by_month: dict[tuple[int, int], dict[str, Any]] = {}
        for r in all_runs:
            key = (int(r.period_year), int(r.period_month))
            enr = enrichments[r.id]
            emp_count = len(enr["employee_ids"]) or int(r.total_employees or 0)
            gross_p = enr["gross_paise"] if enr["employee_ids"] else (int(r.total_gross_paise or 0) or _to_paise(r.total_gross))
            ded_p = enr["deductions_paise"] if enr["employee_ids"] else (int(r.total_deductions_paise or 0) or _to_paise(r.total_deductions))
            net_p = enr["net_paise"] if enr["employee_ids"] else (int(r.total_net_paise or 0) or _to_paise(r.total_net))
            empr_p = enr["employer_contrib_paise"]

            if key not in by_month:
                by_month[key] = {
                    "period_id": str(r.period_id) if r.period_id else None,
                    "label": _format_month_label(r.period_month, r.period_year),
                    "month": int(r.period_month),
                    "year": int(r.period_year),
                    "employee_count": emp_count,
                    "gross_paise": gross_p,
                    "deductions_paise": ded_p,
                    "net_paise": net_p,
                    "employer_contrib_paise": empr_p,
                    "status": r.status,
                }
            else:
                bucket = by_month[key]
                bucket["employee_count"] += emp_count
                bucket["gross_paise"] += gross_p
                bucket["deductions_paise"] += ded_p
                bucket["net_paise"] += net_p
                if bucket["employer_contrib_paise"] is not None and empr_p is not None:
                    bucket["employer_contrib_paise"] += empr_p
                else:
                    bucket["employer_contrib_paise"] = None

        sorted_keys = sorted(by_month.keys())[-limit:]
        trends: list[dict[str, Any]] = []
        for k in sorted_keys:
            b = by_month[k]
            empr = b["employer_contrib_paise"]
            cost_p = (b["gross_paise"] + empr) if empr is not None else None
            trends.append({
                "period_id": b["period_id"],
                "label": b["label"],
                "month": b["month"],
                "year": b["year"],
                "employee_count": b["employee_count"],
                "gross_payroll": _paise_to_float(b["gross_paise"]),
                "total_deductions": _paise_to_float(b["deductions_paise"]),
                "net_payroll": _paise_to_float(b["net_paise"]),
                "employer_contributions": _paise_to_float(empr) if empr is not None else None,
                "total_payroll_cost": _paise_to_float(cost_p) if cost_p is not None else None,
                "status": b["status"],
            })
        return trends

    async def get_hero_metrics(
        self,
        month: Optional[int] = None,
        year: Optional[int] = None,
        *,
        company_id: Optional[uuid.UUID] = None,
    ) -> dict:
        """Backward-compatible helper returning verified tenant-scoped summary metrics."""
        period, target_m, target_y = await self.resolve_period(
            company_id=company_id, month=month, year=year
        )
        runs = await self.get_period_runs(
            company_id=company_id, period=period, month=target_m, year=target_y
        )
        effective_runs = [r for r in runs if r.status not in EXCLUDED_RUN_STATUSES]
        fin = await self.get_period_financial_and_payment_data(
            company_id=company_id, effective_runs=effective_runs, month=target_m, year=target_y
        )
        total_emp = fin["processed_count"]
        paid_count = fin["paid_count"]
        if total_emp == 0:
            dash_status = "NOT_STARTED"
        elif paid_count == total_emp and fin["pending_payment_count"] == 0:
            dash_status = "COMPLETED"
        else:
            dash_status = "IN_PROGRESS"

        return {
            "cycle_month": f"{target_y}-{target_m:02d}",
            "total_employees": total_emp,
            "total_gross": _paise_to_float(fin["gross_paise"]),
            "total_deductions": _paise_to_float(fin["deductions_paise"]),
            "total_net": _paise_to_float(fin["net_paise"]),
            "processed_count": total_emp,
            "paid_count": paid_count,
            "pending_count": fin["pending_payment_count"],
            "status": dash_status,
        }
