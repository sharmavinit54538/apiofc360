"""Service orchestrating Payroll Dashboard aggregations."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payroll.repositories.payroll_repository import (
    EXCLUDED_RUN_STATUSES,
    PayrollRepository,
    _format_month_label,
    _paise_to_float,
    _to_paise,
)
from app.schemas.payroll_dashboard import (
    ApprovalSummary,
    DashboardIssueItem,
    DashboardIssuesSummary,
    DashboardPeriodInfo,
    DashboardRunSummary,
    DashboardSummaryMetrics,
    DashboardTrendPoint,
    EmployeeCountsSummary,
    EmployerContributionsBreakdown,
    PaymentStatusSummary,
    PayrollDashboardResponse,
    ReadinessCheckItem,
    ReadinessSummary,
    StatutorySummary,
)


def _derive_dashboard_status(
    *,
    effective_runs: list,
    latest_run,
    processed_count: int,
    paid_count: int,
    pending_payment_count: int,
) -> str:
    if effective_runs:
        active = effective_runs[0]
        st = str(active.status or "").upper()
        if st == "PROCESSING":
            return "IN_PROGRESS"
        if st in ("PAID", "FINALIZED", "LOCKED") and processed_count > 0 and paid_count >= processed_count and pending_payment_count == 0:
            return "COMPLETED"
        if processed_count > 0 or st in ("PROCESSED", "PENDING_APPROVAL", "UNDER_REVIEW", "APPROVED", "FINALIZED", "LOCKED", "VALIDATED", "DRAFT"):
            return "COMPLETED" if st in ("FINALIZED", "LOCKED", "PAID") else "IN_PROGRESS"
    if latest_run and str(latest_run.status or "").upper() == "FAILED":
        return "FAILED"
    if processed_count > 0:
        return "COMPLETED" if (paid_count == processed_count and pending_payment_count == 0) else "IN_PROGRESS"
    return "NOT_STARTED"


class DashboardService:
    """Business logic for payroll overview dashboard KPIs & analytics."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = PayrollRepository(db)

    async def get_hero_card_metrics(
        self,
        month: Optional[int] = None,
        year: Optional[int] = None,
        *,
        company_id: Optional[uuid.UUID] = None,
    ) -> dict:
        """Backward-compatible summary metrics helper scoped by company_id."""
        return await self.repo.get_hero_metrics(month, year, company_id=company_id)

    async def get_full_dashboard(
        self,
        *,
        company_id: Optional[uuid.UUID],
        cycle_id: Optional[uuid.UUID] = None,
        month: Optional[int] = None,
        year: Optional[int] = None,
    ) -> PayrollDashboardResponse:
        now = datetime.now(timezone.utc)
        period, target_m, target_y = await self.repo.resolve_period(
            company_id=company_id, cycle_id=cycle_id, month=month, year=year
        )
        currency = await self.repo.get_company_currency(company_id)
        runs = await self.repo.get_period_runs(
            company_id=company_id, period=period, month=target_m, year=target_y
        )
        effective_runs = [r for r in runs if r.status not in EXCLUDED_RUN_STATUSES]
        latest_run = runs[0] if runs else None
        active_run_orm = effective_runs[0] if effective_runs else latest_run
        if active_run_orm and getattr(active_run_orm, "currency", None):
            currency = str(active_run_orm.currency).upper()

        fin = await self.repo.get_period_financial_and_payment_data(
            company_id=company_id, effective_runs=effective_runs, month=target_m, year=target_y
        )
        ra = await self.repo.get_readiness_and_approvals(
            company_id=company_id, period=period, month=target_m, year=target_y, runs=runs
        )

        # Recent runs + trends (bulk SQL)
        recent_run_orms = await self.repo.get_recent_runs(
            company_id=company_id,
            legal_entity_id=period.legal_entity_id if period else None,
            limit=10,
        )
        enrichments = await self.repo.get_bulk_run_enrichments(
            company_id=company_id, run_ids=[r.id for r in recent_run_orms]
        )
        trend_dicts = await self.repo.get_monthly_trends(
            company_id=company_id,
            legal_entity_id=period.legal_entity_id if period else None,
            limit=12,
        )

        recent_runs: list[DashboardRunSummary] = []
        for r in recent_run_orms:
            enr = enrichments[r.id]
            emp_cnt = len(enr["employee_ids"]) or int(r.total_employees or 0)
            gross_p = enr["gross_paise"] if enr["employee_ids"] else (int(r.total_gross_paise or 0) or _to_paise(r.total_gross))
            ded_p = enr["deductions_paise"] if enr["employee_ids"] else (int(r.total_deductions_paise or 0) or _to_paise(r.total_deductions))
            net_p = enr["net_paise"] if enr["employee_ids"] else (int(r.total_net_paise or 0) or _to_paise(r.total_net))
            empr_p = enr["employer_contrib_paise"]
            cost_p = (gross_p + empr_p) if empr_p is not None else None
            recent_runs.append(
                DashboardRunSummary(
                    id=str(r.id),
                    run_number=r.run_number,
                    period_id=str(r.period_id) if r.period_id else None,
                    period_name=_format_month_label(r.period_month, r.period_year),
                    period_month=int(r.period_month),
                    period_year=int(r.period_year),
                    status=r.status,
                    validation_status=r.validation_status or "PENDING",
                    employee_count=emp_cnt,
                    paid_count=enr["paid_count"],
                    failed_payment_count=enr["failed_payment_count"],
                    gross_payroll=_paise_to_float(gross_p),
                    total_deductions=_paise_to_float(ded_p),
                    net_payroll=_paise_to_float(net_p),
                    employer_contributions=_paise_to_float(empr_p) if empr_p is not None else None,
                    total_payroll_cost=_paise_to_float(cost_p) if cost_p is not None else None,
                    is_locked=bool(r.is_locked),
                    currency=getattr(r, "currency", None) or currency,
                    run_date=r.run_at or r.created_at,
                    created_at=r.created_at,
                )
            )

        active_run_summary: Optional[DashboardRunSummary] = None
        if active_run_orm:
            matched = next((rr for rr in recent_runs if rr.id == str(active_run_orm.id)), None)
            if matched is not None:
                active_run_summary = matched
            else:
                act_enr = await self.repo.get_bulk_run_enrichments(
                    company_id=company_id, run_ids=[active_run_orm.id]
                )
                enr = act_enr[active_run_orm.id]
                emp_cnt = len(enr["employee_ids"]) or int(active_run_orm.total_employees or 0)
                gross_p = enr["gross_paise"] if enr["employee_ids"] else (int(active_run_orm.total_gross_paise or 0) or _to_paise(active_run_orm.total_gross))
                ded_p = enr["deductions_paise"] if enr["employee_ids"] else (int(active_run_orm.total_deductions_paise or 0) or _to_paise(active_run_orm.total_deductions))
                net_p = enr["net_paise"] if enr["employee_ids"] else (int(active_run_orm.total_net_paise or 0) or _to_paise(active_run_orm.total_net))
                empr_p = enr["employer_contrib_paise"]
                cost_p = (gross_p + empr_p) if empr_p is not None else None
                active_run_summary = DashboardRunSummary(
                    id=str(active_run_orm.id),
                    run_number=active_run_orm.run_number,
                    period_id=str(active_run_orm.period_id) if active_run_orm.period_id else None,
                    period_name=_format_month_label(active_run_orm.period_month, active_run_orm.period_year),
                    period_month=int(active_run_orm.period_month),
                    period_year=int(active_run_orm.period_year),
                    status=active_run_orm.status,
                    validation_status=active_run_orm.validation_status or "PENDING",
                    employee_count=emp_cnt,
                    paid_count=enr["paid_count"],
                    failed_payment_count=enr["failed_payment_count"],
                    gross_payroll=_paise_to_float(gross_p),
                    total_deductions=_paise_to_float(ded_p),
                    net_payroll=_paise_to_float(net_p),
                    employer_contributions=_paise_to_float(empr_p) if empr_p is not None else None,
                    total_payroll_cost=_paise_to_float(cost_p) if cost_p is not None else None,
                    is_locked=bool(active_run_orm.is_locked),
                    currency=getattr(active_run_orm, "currency", None) or currency,
                    run_date=active_run_orm.run_at or active_run_orm.created_at,
                    created_at=active_run_orm.created_at,
                )

        processed_count = int(fin["processed_count"])
        eligible_employees = int(ra["eligible_employees"])
        gross_paise = int(fin["gross_paise"])
        ded_paise = int(fin["deductions_paise"])
        net_paise = int(fin["net_paise"])
        empr_paise = fin["employer_contrib_paise"]
        total_cost_paise = (gross_paise + empr_paise) if empr_paise is not None else None

        avg_gross = (
            float((Decimal(gross_paise) / Decimal(processed_count * 100)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
            if processed_count > 0
            else None
        )
        avg_net = (
            float((Decimal(net_paise) / Decimal(processed_count * 100)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
            if processed_count > 0
            else None
        )

        dash_status = _derive_dashboard_status(
            effective_runs=effective_runs,
            latest_run=latest_run,
            processed_count=processed_count,
            paid_count=int(fin["paid_count"]),
            pending_payment_count=int(fin["pending_payment_count"]),
        )

        period_info = None
        if period is not None:
            period_info = DashboardPeriodInfo(
                id=str(period.id),
                company_id=str(period.company_id) if period.company_id else None,
                name=period.name,
                frequency="MONTHLY",
                period_month=int(period.period_month),
                period_year=int(period.period_year),
                start_date=str(period.start_date) if period.start_date else None,
                end_date=str(period.end_date) if period.end_date else None,
                processing_date=str(period.processing_date) if period.processing_date else None,
                payment_date=str(period.payment_date) if period.payment_date else None,
                pay_date=str(period.pay_date) if period.pay_date else None,
                status=period.status,
                is_locked=bool(period.is_locked),
                is_current=(period.period_month == now.month and period.period_year == now.year),
                attendance_locked=period.attendance_locked_at is not None,
                attendance_locked_at=period.attendance_locked_at,
            )

        summary = DashboardSummaryMetrics(
            cycle_month=f"{target_y}-{target_m:02d}",
            period_month=target_m,
            period_year=target_y,
            total_employees=processed_count,
            eligible_employees=eligible_employees,
            included_employees=processed_count,
            processed_count=processed_count,
            paid_count=int(fin["paid_count"]),
            pending_count=int(fin["pending_payment_count"]),
            on_hold_count=int(fin["held_count"]),
            failed_count=int(fin["failed_payment_count"]),
            total_gross=_paise_to_float(gross_paise),
            total_deductions=_paise_to_float(ded_paise),
            total_net=_paise_to_float(net_paise),
            employer_contributions=_paise_to_float(empr_paise) if empr_paise is not None else None,
            total_payroll_cost=_paise_to_float(total_cost_paise) if total_cost_paise is not None else None,
            average_gross_salary=avg_gross,
            average_net_salary=avg_net,
            total_gross_paise=gross_paise,
            total_deductions_paise=ded_paise,
            total_net_paise=net_paise,
            employer_contributions_paise=empr_paise,
            total_payroll_cost_paise=total_cost_paise,
            currency=currency,
            status=dash_status,
        )

        empr_breakdown = EmployerContributionsBreakdown(
            total=_paise_to_float(empr_paise) if empr_paise is not None else None,
            total_paise=empr_paise,
            employer_pf=_paise_to_float(fin["pf_empr_paise"]) if empr_paise is not None else None,
            employer_esi=_paise_to_float(fin["esi_empr_paise"]) if empr_paise is not None else None,
            employer_lwf=_paise_to_float(fin["lwf_empr_paise"]) if empr_paise is not None else None,
            employer_edli_and_admin=_paise_to_float(fin["edli_admin_paise"]) if empr_paise is not None else None,
            gratuity_provision=_paise_to_float(fin["gratuity_paise"]) if empr_paise is not None else None,
            other_employer=_paise_to_float(fin["other_empr_paise"]) if empr_paise is not None else None,
        )

        emp_stat_p = (
            int(fin["pf_emp_paise"])
            + int(fin["esi_emp_paise"])
            + int(fin["pt_paise"])
            + int(fin["tds_paise"])
            + int(fin["lwf_emp_paise"])
        )
        empr_stat_p = (
            (int(fin["pf_empr_paise"]) + int(fin["esi_empr_paise"]) + int(fin["lwf_empr_paise"]) + int(fin["edli_admin_paise"]))
            if empr_paise is not None
            else None
        )
        stat_total_p = (emp_stat_p + empr_stat_p) if empr_stat_p is not None else None

        statutory_summary = StatutorySummary(
            employee_deductions_total=_paise_to_float(emp_stat_p),
            employer_contributions_total=_paise_to_float(empr_stat_p) if empr_stat_p is not None else None,
            total_liability=_paise_to_float(stat_total_p) if stat_total_p is not None else None,
            remitted_amount=_paise_to_float(fin["remitted_paise"]),
            pending_liabilities=_paise_to_float(fin["pending_liabilities_paise"]),
            pf_employee=_paise_to_float(fin["pf_emp_paise"]),
            pf_employer=_paise_to_float(fin["pf_empr_paise"]),
            esi_employee=_paise_to_float(fin["esi_emp_paise"]),
            esi_employer=_paise_to_float(fin["esi_empr_paise"]),
            pt_total=_paise_to_float(fin["pt_paise"]),
            tds_total=_paise_to_float(fin["tds_paise"]),
            lwf_total=_paise_to_float(int(fin["lwf_emp_paise"]) + int(fin["lwf_empr_paise"])),
            pending_filings_count=int(fin["pending_filings_count"]),
            overdue_filings_count=int(fin["overdue_filings_count"]),
        )

        payment_summary = PaymentStatusSummary(
            total_payable=_paise_to_float(net_paise),
            paid_amount=_paise_to_float(fin["paid_amount_paise"]),
            pending_amount=_paise_to_float(fin["pending_amount_paise"]),
            failed_amount=_paise_to_float(fin["failed_amount_paise"]),
            held_amount=_paise_to_float(fin["held_amount_paise"]),
            paid_count=int(fin["paid_count"]),
            pending_count=int(fin["pending_payment_count"]),
            failed_count=int(fin["failed_payment_count"]),
            held_count=int(fin["held_count"]),
            batch_count=int(fin["batch_count"]),
            latest_batch_status=fin["latest_batch_status"],
        )

        readiness_raw = ra["readiness"]
        readiness = ReadinessSummary(
            items=[ReadinessCheckItem(**it) for it in readiness_raw["items"]],
            is_ready=bool(readiness_raw["is_ready"]),
            blocking_count=int(readiness_raw["blocking_count"]),
            warning_count=int(readiness_raw["warning_count"]),
        )

        issues_raw = ra["issues"]
        issues = DashboardIssuesSummary(
            errors=[DashboardIssueItem(**it) for it in issues_raw["errors"]],
            warnings=[DashboardIssueItem(**it) for it in issues_raw["warnings"]],
            unique_employee_count=int(issues_raw["unique_employee_count"]),
            total_error_count=int(issues_raw["total_error_count"]),
            total_warning_count=int(issues_raw["total_warning_count"]),
        )

        return PayrollDashboardResponse(
            period=period_info,
            summary=summary,
            status=dash_status,
            employee_counts=EmployeeCountsSummary(
                eligible=eligible_employees,
                included=processed_count,
                processed=processed_count,
                paid=int(fin["paid_count"]),
                pending=int(fin["pending_payment_count"]),
                on_hold=int(fin["held_count"]),
                failed=int(fin["failed_payment_count"]),
            ),
            employer_contributions=empr_breakdown,
            statutory_summary=statutory_summary,
            payment_summary=payment_summary,
            approval_summary=ApprovalSummary(**ra["approval_summary"]),
            readiness=readiness,
            issues=issues,
            active_run=active_run_summary,
            recent_runs=recent_runs,
            trends=[DashboardTrendPoint(**pt) for pt in trend_dicts],
            currency=currency,
            last_updated_at=now,
        )
