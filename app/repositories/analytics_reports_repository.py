"""Repository executing tenant-isolated, high-performance PostgreSQL queries for Reports and Analytics."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
import logging
from typing import Any, Dict, List, Optional, Tuple
import uuid

from sqlalchemy import and_, case, delete, desc, distinct, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core_modules import ComplianceRecord
from app.models.employee import Employee
from app.models.exit import EmployeeExit
from app.models.payroll import PayrollRun
from app.models.report import Report

logger = logging.getLogger(__name__)


class AnalyticsReportsRepository:
    """Repository handling SQL aggregate operations for analytics and report builder."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Headcount Growth Analytics ──────────────────────────────────────────

    async def get_headcount_analytics(
        self,
        company_id: uuid.UUID,
        allowed_employee_ids: Optional[List[uuid.UUID]] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        department: Optional[str] = None,
        status_filter: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Compute monthly cumulative headcount growth."""
        stmt = select(Employee.joining_date).where(
            Employee.company_id == company_id,
            Employee.is_deleted == False,
            Employee.joining_date.isnot(None),
        )
        if allowed_employee_ids is not None:
            if not allowed_employee_ids:
                return []
            stmt = stmt.where(Employee.id.in_(allowed_employee_ids))
        if department:
            stmt = stmt.where(Employee.department == department)
        if status_filter and status_filter.lower() != "all":
            stmt = stmt.where(Employee.status == status_filter)

        res = await self.session.execute(stmt)
        dates = [r[0] for r in res if r[0]]
        if not dates:
            return []

        dates.sort()
        today = end_date or date.today()
        year = today.year
        months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

        start_m = start_date.month if (start_date and start_date.year == year) else 1
        end_m = today.month

        result = []
        for i in range(start_m, end_m + 1):
            month_end = date(year, i, 28)
            count = sum(1 for d in dates if d <= month_end)
            result.append({
                "m": months[i - 1],
                "n": count,
            })

        return result

    # ── Department Distribution Analytics ───────────────────────────────────

    async def get_department_analytics(
        self,
        company_id: uuid.UUID,
        allowed_employee_ids: Optional[List[uuid.UUID]] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        department: Optional[str] = None,
        status_filter: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Compute employee distribution across company departments."""
        stmt = (
            select(Employee.department, func.count(Employee.id))
            .where(
                Employee.company_id == company_id,
                Employee.is_deleted == False,
                Employee.department.isnot(None),
            )
            .group_by(Employee.department)
        )
        if allowed_employee_ids is not None:
            if not allowed_employee_ids:
                return []
            stmt = stmt.where(Employee.id.in_(allowed_employee_ids))
        if department:
            stmt = stmt.where(Employee.department == department)
        if status_filter and status_filter.lower() != "all":
            stmt = stmt.where(Employee.status == status_filter)
        if start_date:
            stmt = stmt.where(Employee.joining_date >= start_date)
        if end_date:
            stmt = stmt.where(Employee.joining_date <= end_date)

        res = await self.session.execute(stmt)
        by_dept = []
        for dept_name, count in res:
            if dept_name:
                by_dept.append({
                    "name": dept_name,
                    "value": count,
                })
        return by_dept

    # ── Tenure Range Analytics ──────────────────────────────────────────────

    async def get_tenure_analytics(
        self,
        company_id: uuid.UUID,
        allowed_employee_ids: Optional[List[uuid.UUID]] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        department: Optional[str] = None,
        status_filter: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Compute tenure bracket distribution."""
        stmt = select(Employee.joining_date).where(
            Employee.company_id == company_id,
            Employee.is_deleted == False,
            Employee.joining_date.isnot(None),
        )
        if allowed_employee_ids is not None:
            if not allowed_employee_ids:
                return []
            stmt = stmt.where(Employee.id.in_(allowed_employee_ids))
        if department:
            stmt = stmt.where(Employee.department == department)
        if status_filter and status_filter.lower() != "all":
            stmt = stmt.where(Employee.status == status_filter)
        if start_date:
            stmt = stmt.where(Employee.joining_date >= start_date)
        if end_date:
            stmt = stmt.where(Employee.joining_date <= end_date)

        res = await self.session.execute(stmt)
        dates = [r[0] for r in res if r[0]]
        if not dates:
            return []

        today = date.today()
        tenure_counts = {"0–1y": 0, "1–2y": 0, "2–3y": 0, "3–5y": 0, "5y+": 0}
        for d in dates:
            years = (today - d).days / 365.25
            if years < 1:
                tenure_counts["0–1y"] += 1
            elif years < 2:
                tenure_counts["1–2y"] += 1
            elif years < 3:
                tenure_counts["2–3y"] += 1
            elif years < 5:
                tenure_counts["3–5y"] += 1
            else:
                tenure_counts["5y+"] += 1

        return [{"range": k, "n": v} for k, v in tenure_counts.items()]

    # ── Turnover Analytics ──────────────────────────────────────────────────

    async def get_turnover_analytics(
        self,
        company_id: uuid.UUID,
        allowed_employee_ids: Optional[List[uuid.UUID]] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        department: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Compute monthly separations and turnover rate."""
        # Query total active headcount as denominator
        headcount_stmt = select(func.count(Employee.id)).where(
            Employee.company_id == company_id,
            Employee.is_deleted == False,
        )
        if allowed_employee_ids is not None:
            if not allowed_employee_ids:
                return []
            headcount_stmt = headcount_stmt.where(Employee.id.in_(allowed_employee_ids))
        if department:
            headcount_stmt = headcount_stmt.where(Employee.department == department)

        base_headcount = (await self.session.execute(headcount_stmt)).scalar() or 0

        # Query separations from EmployeeExit
        exit_stmt = select(
            EmployeeExit.last_working_date,
            EmployeeExit.employee_id,
        ).where(
            EmployeeExit.company_id == company_id,
            EmployeeExit.is_deleted == False,
            EmployeeExit.last_working_date.isnot(None),
        )
        if allowed_employee_ids is not None:
            exit_stmt = exit_stmt.where(EmployeeExit.employee_id.in_(allowed_employee_ids))
        if start_date:
            exit_stmt = exit_stmt.where(EmployeeExit.last_working_date >= start_date)
        if end_date:
            exit_stmt = exit_stmt.where(EmployeeExit.last_working_date <= end_date)

        exit_res = await self.session.execute(exit_stmt)
        exits = list(exit_res.all())
        if not exits and base_headcount == 0:
            return []

        # Group exits by month (YYYY-MM)
        month_map: Dict[str, int] = {}
        for row in exits:
            lwd = row[0]
            if lwd:
                m_key = lwd.strftime("%Y-%m")
                month_map[m_key] = month_map.get(m_key, 0) + 1

        if not month_map:
            return []

        result = []
        for m_key in sorted(month_map.keys()):
            sep_count = month_map[m_key]
            denom = max(base_headcount, sep_count)
            rate = round((sep_count / denom) * 100.0, 2) if denom > 0 else 0.0
            result.append({
                "period": m_key,
                "separations": sep_count,
                "headcount": base_headcount,
                "rate": rate,
            })
        return result

    # ── Payroll Cost Analytics ──────────────────────────────────────────────

    async def get_payroll_cost_analytics(
        self,
        company_id: uuid.UUID,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> List[Dict[str, Any]]:
        """Compute monthly payroll cost totals."""
        run_stmt = (
            select(
                PayrollRun.period_year,
                PayrollRun.period_month,
                func.sum(PayrollRun.total_gross),
                func.sum(PayrollRun.total_net),
                func.sum(PayrollRun.total_employees),
            )
            .where(
                PayrollRun.company_id == company_id,
                PayrollRun.status.notin_(["VOID", "FAILED", "CANCELLED", "REJECTED"]),
            )
            .group_by(PayrollRun.period_year, PayrollRun.period_month)
            .order_by(PayrollRun.period_year.asc(), PayrollRun.period_month.asc())
        )
        if start_date:
            run_stmt = run_stmt.where(
                or_(
                    PayrollRun.period_year > start_date.year,
                    and_(
                        PayrollRun.period_year == start_date.year,
                        PayrollRun.period_month >= start_date.month,
                    ),
                )
            )
        if end_date:
            run_stmt = run_stmt.where(
                or_(
                    PayrollRun.period_year < end_date.year,
                    and_(
                        PayrollRun.period_year == end_date.year,
                        PayrollRun.period_month <= end_date.month,
                    ),
                )
            )

        runs = (await self.session.execute(run_stmt)).all()
        if runs:
            return [
                {
                    "period": f"{r[0]}-{r[1]:02d}",
                    "total_gross": float(r[2] or 0),
                    "total_net": float(r[3] or 0),
                    "total_employees": int(r[4] or 0),
                }
                for r in runs
            ]

        # Fallback to employee base salary pool if no finalized PayrollRuns exist
        emp_stmt = select(
            func.sum(Employee.basic_salary),
            func.count(Employee.id),
        ).where(
            Employee.company_id == company_id,
            Employee.is_deleted == False,
            Employee.status == "ACTIVE",
        )
        emp_res = (await self.session.execute(emp_stmt)).one_or_none()
        total_sal = float(emp_res[0] or 0) if emp_res else 0.0
        emp_cnt = int(emp_res[1] or 0) if emp_res else 0

        if emp_cnt == 0 or total_sal == 0:
            return []

        cur_period = date.today().strftime("%Y-%m")
        return [{
            "period": cur_period,
            "total_gross": total_sal,
            "total_net": total_sal,
            "total_employees": emp_cnt,
        }]

    # ── Compliance Analytics ────────────────────────────────────────────────

    async def get_compliance_analytics(
        self,
        company_id: uuid.UUID,
        allowed_employee_ids: Optional[List[uuid.UUID]] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> Dict[str, Any]:
        """Compute counts and distribution of compliance obligations."""
        stmt = select(
            ComplianceRecord.status,
            ComplianceRecord.compliance_type,
            func.count(ComplianceRecord.id),
        ).where(
            ComplianceRecord.company_id == company_id,
        )
        if allowed_employee_ids is not None:
            if not allowed_employee_ids:
                return {"total": 0, "compliant": 0, "pending": 0, "overdue": 0, "by_type": []}
            stmt = stmt.where(ComplianceRecord.employee_id.in_(allowed_employee_ids))
        if start_date:
            stmt = stmt.where(ComplianceRecord.created_at >= datetime.combine(start_date, datetime.min.time()))
        if end_date:
            stmt = stmt.where(ComplianceRecord.created_at <= datetime.combine(end_date, datetime.max.time()))

        stmt = stmt.group_by(ComplianceRecord.status, ComplianceRecord.compliance_type)
        rows = (await self.session.execute(stmt)).all()

        if not rows:
            return {
                "total": 0,
                "compliant": 0,
                "pending": 0,
                "overdue": 0,
                "by_type": [],
            }

        total = 0
        compliant_cnt = 0
        pending_cnt = 0
        overdue_cnt = 0
        type_map: Dict[str, int] = {}

        for st, ctype, cnt in rows:
            total += cnt
            type_map[ctype] = type_map.get(ctype, 0) + cnt
            st_clean = (st or "").lower()
            if "compliant" in st_clean:
                compliant_cnt += cnt
            elif "pending" in st_clean:
                pending_cnt += cnt
            elif "overdue" in st_clean:
                overdue_cnt += cnt

        by_type = [{"type": k, "count": v} for k, v in type_map.items()]
        return {
            "total": total,
            "compliant": compliant_cnt,
            "pending": pending_cnt,
            "overdue": overdue_cnt,
            "by_type": by_type,
        }

    # ── Report Management & Stats ───────────────────────────────────────────

    async def get_report_stats(self, company_id: uuid.UUID) -> Dict[str, Any]:
        """Compute aggregate stats for reports generated within this company."""
        base_where = [Report.company_id == company_id]

        total = (await self.session.execute(select(func.count(Report.id)).where(*base_where))).scalar() or 0
        today_start = datetime.combine(date.today(), datetime.min.time())

        generated_today = (
            await self.session.execute(
                select(func.count(Report.id)).where(*base_where, Report.created_at >= today_start)
            )
        ).scalar() or 0

        scheduled = (
            await self.session.execute(
                select(func.count(Report.id)).where(
                    *base_where,
                    Report.schedule.isnot(None),
                    Report.schedule != "none",
                )
            )
        ).scalar() or 0

        pending = (
            await self.session.execute(
                select(func.count(Report.id)).where(
                    *base_where,
                    Report.status.in_(["pending", "running"]),
                )
            )
        ).scalar() or 0

        successful_exports = (
            await self.session.execute(
                select(func.count(Report.id)).where(*base_where, Report.status == "completed")
            )
        ).scalar() or 0

        failed = (
            await self.session.execute(
                select(func.count(Report.id)).where(*base_where, Report.status == "failed")
            )
        ).scalar() or 0

        total_kb = float(
            (await self.session.execute(select(func.sum(Report.file_size_kb)).where(*base_where))).scalar() or 0.0
        )
        storage_usage_mb = round(total_kb / 1024.0, 2)

        active_dashboards = (
            await self.session.execute(select(func.count(distinct(Report.type))).where(*base_where))
        ).scalar() or 0

        return {
            "total": total,
            "generated_today": generated_today,
            "scheduled": scheduled,
            "pending": pending,
            "successful_exports": successful_exports,
            "failed": failed,
            "active_dashboards": active_dashboards,
            "storage_usage_mb": storage_usage_mb,
        }

    async def list_reports(
        self,
        company_id: uuid.UUID,
        type_filter: Optional[str] = None,
        status_filter: Optional[str] = None,
        search: Optional[str] = None,
        page: int = 1,
        limit: int = 100,
    ) -> Tuple[List[Report], int]:
        """List tenant-scoped reports."""
        conditions = [Report.company_id == company_id]
        if type_filter and type_filter != "all":
            conditions.append(Report.type == type_filter)
        if status_filter and status_filter != "all":
            conditions.append(Report.status == status_filter)
        if search:
            s_term = f"%{search.lower()}%"
            conditions.append(
                or_(
                    func.lower(Report.name).like(s_term),
                    func.lower(Report.description).like(s_term),
                )
            )

        count_stmt = select(func.count(Report.id)).where(*conditions)
        total = (await self.session.execute(count_stmt)).scalar() or 0

        stmt = (
            select(Report)
            .where(*conditions)
            .order_by(Report.created_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all()), total

    async def get_report_by_id(self, company_id: uuid.UUID, report_id: uuid.UUID) -> Optional[Report]:
        """Fetch report ensuring tenant scoping."""
        stmt = select(Report).where(Report.id == report_id, Report.company_id == company_id)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()
