"""AI Insights API — Workforce Intelligence Dashboard (Production).

Tenant-isolated, role-scoped workforce analytics powered by real PostgreSQL data.
No fabricated, random, or hardcoded sample data:
- When the database has no data, returns empty arrays, null/0 values, and 'has_data: false'.
- Dynamic resilience: /dashboard runs individual sub-aggregations in isolation;
  if one section encounters an issue, the remaining sections are returned with 'partial: true'
  and error details.
"""

from __future__ import annotations

import asyncio
import calendar
import logging
import uuid
from datetime import date, datetime
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import and_, case, desc, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

try:
    from cachetools import TTLCache
    HAS_CACHETOOLS = True
except ImportError:
    HAS_CACHETOOLS = False

from app.db.database import get_db_session
from app.models.employee import Employee
from app.models.recruitment import Application, Job
from app.models.leave import LeaveRequest
from app.models.payroll import OvertimeEntry, PayCycle, Payslip
from app.models.performance import PerformanceReview
from app.schemas.auth import APIResponse
from app.services.analytics_access import AnalyticsContext, require_analytics_access

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai-insights", tags=["AI Insights"])

# ── Module Constants ───────────────────────────────────────────────────────────
LOW_SALARY_THRESHOLD = 15000
MID_SALARY_THRESHOLD = 35000
EARLY_TENURE_DAYS = 180
MID_TENURE_DAYS = 365
LONG_TENURE_DAYS = 730
OVERTIME_BURNOUT_HOURS = 8
CACHE_TTL_SECONDS = 60

VALID_ICONS = {
    "Users", "Target", "Briefcase", "HeartPulse", "TrendingUp",
    "Zap", "Sparkles", "Banknote", "Gauge", "Brain",
    "BarChart3", "UserMinus", "CheckCircle2"
}

def _valid_icon(icon: str) -> str:
    """Return icon if valid, else default to 'Gauge'."""
    return icon if icon in VALID_ICONS else "Gauge"

def _stable_id(*parts: str) -> str:
    """Generate deterministic UUID5 from parts."""
    namespace = uuid.NAMESPACE_DNS
    name = "|".join(str(p) for p in parts)
    return str(uuid.uuid5(namespace, name))

def _month_label(d: date) -> str:
    return d.strftime("%b")

# ── Simple In-Memory TTL Cache ─────────────────────────────────────────────────
if HAS_CACHETOOLS:
    _section_cache: TTLCache = TTLCache(maxsize=256, ttl=CACHE_TTL_SECONDS)
else:
    # Fallback: simple dict with manual expiry tracking
    _section_cache: Dict[tuple, tuple] = {}  # key -> (expiry_ts, value)

async def _get_cached(company_id: uuid.UUID, section: str, refresh: bool = False) -> Optional[Any]:
    """Get cached section data if available and not stale."""
    if refresh:
        return None
    key = (str(company_id), section)
    if HAS_CACHETOOLS:
        return _section_cache.get(key)
    else:
        entry = _section_cache.get(key)
        if entry and entry[0] > datetime.now().timestamp():
            return entry[1]
        elif entry:
            _section_cache.pop(key, None)
    return None

async def _set_cached(company_id: uuid.UUID, section: str, value: Any) -> None:
    """Set cached section data."""
    key = (str(company_id), section)
    if HAS_CACHETOOLS:
        _section_cache[key] = value
    else:
        _section_cache[key] = (datetime.now().timestamp() + CACHE_TTL_SECONDS, value)

# ── Base Metrics ───────────────────────────────────────────────────────────────
async def _fetch_base_metrics(
    session: AsyncSession,
    ctx: AnalyticsContext,
) -> Dict[str, Any]:
    """Fetch core counts and employee records respecting tenant and manager hierarchy scoping."""
    # 1. Total ACTIVE employees (status=ACTIVE, is_active=True, not deleted)
    emp_stmt = select(func.count(Employee.id)).where(
        Employee.company_id == ctx.company_id,
        Employee.is_deleted == False,
        Employee.status == "ACTIVE",
        Employee.is_active == True,
    )
    if ctx.allowed_employee_ids is not None:
        emp_stmt = emp_stmt.where(Employee.id.in_(ctx.allowed_employee_ids))
    total_emp = (await session.execute(emp_stmt)).scalar() or 0

    # 2. Total non-deleted employees (for active ratio)
    total_emp_all = select(func.count(Employee.id)).where(
        Employee.company_id == ctx.company_id,
        Employee.is_deleted == False,
    )
    if ctx.allowed_employee_ids is not None:
        total_emp_all = total_emp_all.where(Employee.id.in_(ctx.allowed_employee_ids))
    total_emp_all_val = (await session.execute(total_emp_all)).scalar() or 0

    # 3. Departments (only from active employees)
    dept_stmt = (
        select(Employee.department, func.count(Employee.id))
        .where(
            Employee.company_id == ctx.company_id,
            Employee.is_deleted == False,
            Employee.status == "ACTIVE",
            Employee.is_active == True,
            Employee.department.isnot(None),
        )
    )
    if ctx.allowed_employee_ids is not None:
        dept_stmt = dept_stmt.where(Employee.id.in_(ctx.allowed_employee_ids))
    dept_stmt = dept_stmt.group_by(Employee.department)
    dept_rows = list((await session.execute(dept_stmt)).fetchall())
    total_dept = len([d for d in dept_rows if d[0]])

    # 4. Open Jobs (PUBLISHED status, not deleted) — SUM of vacancies
    open_jobs_stmt = select(
        func.count(Job.id),
        func.coalesce(func.sum(Job.vacancies), 0)
    ).where(
        Job.company_id == ctx.company_id,
        Job.is_deleted == False,
        Job.status == "PUBLISHED",
    )
    open_jobs_res = await session.execute(open_jobs_stmt)
    open_jobs_count, open_vacancies = open_jobs_res.one_or_none() or (0, 0)

    # 5. Total requisitions (all non-deleted jobs for hint text)
    total_req_stmt = select(func.count(Job.id)).where(
        Job.company_id == ctx.company_id,
        Job.is_deleted == False,
    )
    total_requisitions = (await session.execute(total_req_stmt)).scalar() or 0

    # 6. Open jobs list (for department matching) — no arbitrary limit
    open_jobs_list_stmt = (
        select(Job.title, Job.department, Job.vacancies)
        .where(
            Job.company_id == ctx.company_id,
            Job.is_deleted == False,
            Job.status == "PUBLISHED",
        )
        .order_by(Job.created_at.desc())
    )
    open_jobs_list = list((await session.execute(open_jobs_list_stmt)).fetchall())

    # 7. Applications for open jobs
    try:
        app_count_stmt = (
            select(func.count(Application.id))
            .join(Job, Application.job_id == Job.id)
            .where(
                Job.company_id == ctx.company_id,
                Job.is_deleted == False,
                Job.status == "PUBLISHED",
            )
        )
        total_applications = (await session.execute(app_count_stmt)).scalar() or 0
    except Exception as e:
        logger.warning("Failed querying applications: %s", e)
        total_applications = 0

    # 8. Payroll base: SUM of basic_salary over ALL active employees
    can_see_salary = ctx.role in {"super_admin", "company_admin", "admin", "hr_admin", "executive"}
    total_payroll_base = 0.0
    if can_see_salary:
        payroll_stmt = select(func.coalesce(func.sum(Employee.basic_salary), 0)).where(
            Employee.company_id == ctx.company_id,
            Employee.is_deleted == False,
            Employee.status == "ACTIVE",
            Employee.is_active == True,
            Employee.basic_salary.isnot(None),
        )
        if ctx.allowed_employee_ids is not None:
            payroll_stmt = payroll_stmt.where(Employee.id.in_(ctx.allowed_employee_ids))
        total_payroll_base = float((await session.execute(payroll_stmt)).scalar() or 0)

    # 9. Previous month headcount for trend
    first_day_this_month = date.today().replace(day=1)
    prev_month_end = first_day_this_month - timedelta(days=1)
    prev_first_day = prev_month_end.replace(day=1)

    prev_headcount_stmt = select(func.count(Employee.id)).where(
        Employee.company_id == ctx.company_id,
        Employee.is_deleted == False,
        Employee.status == "ACTIVE",
        Employee.is_active == True,
        Employee.joining_date <= prev_month_end,
    )
    if ctx.allowed_employee_ids is not None:
        prev_headcount_stmt = prev_headcount_stmt.where(Employee.id.in_(ctx.allowed_employee_ids))
    prev_headcount = (await session.execute(prev_headcount_stmt)).scalar() or 0

    # 10. Latest payroll cycle vs previous for payroll trend
    latest_cycle_stmt = select(PayCycle).where(
        PayCycle.company_id == ctx.company_id,
    ).order_by(PayCycle.period_year.desc(), PayCycle.period_month.desc()).limit(2)
    cycles = list((await session.execute(latest_cycle_stmt)).scalars().all())
    latest_cycle = cycles[0] if cycles else None
    prev_cycle = cycles[1] if len(cycles) > 1 else None

    latest_payroll_gross = 0.0
    prev_payroll_gross = 0.0
    if latest_cycle:
        gross_stmt = select(func.coalesce(func.sum(Payslip.gross_earnings), 0)).where(
            Payslip.payroll_run_id == latest_cycle.id,
        )
        if ctx.allowed_employee_ids is not None:
            gross_stmt = gross_stmt.join(Employee, Payslip.employee_id == Employee.id).where(
                Employee.id.in_(ctx.allowed_employee_ids)
            )
        latest_payroll_gross = float((await session.execute(gross_stmt)).scalar() or 0)

    if prev_cycle:
        prev_gross_stmt = select(func.coalesce(func.sum(Payslip.gross_earnings), 0)).where(
            Payslip.payroll_run_id == prev_cycle.id,
        )
        if ctx.allowed_employee_ids is not None:
            prev_gross_stmt = prev_gross_stmt.join(Employee, Payslip.employee_id == Employee.id).where(
                Employee.id.in_(ctx.allowed_employee_ids)
            )
        prev_payroll_gross = float((await session.execute(prev_gross_stmt)).scalar() or 0)

    return {
        "total_emp": total_emp,
        "total_emp_all": total_emp_all_val,
        "total_dept": total_dept,
        "dept_rows": dept_rows,
        "total_requisitions": total_requisitions,
        "open_jobs_count": open_jobs_count,
        "open_vacancies": open_vacancies,
        "open_jobs": open_jobs_list,
        "total_applications": total_applications,
        "total_payroll_base": total_payroll_base,
        "can_see_salary": can_see_salary,
        "prev_headcount": prev_headcount,
        "latest_payroll_gross": latest_payroll_gross,
        "prev_payroll_gross": prev_payroll_gross,
        "latest_cycle": latest_cycle,
        "prev_cycle": prev_cycle,
    }

# ── KPI Section ────────────────────────────────────────────────────────────────
async def _build_kpi_section(
    session: AsyncSession,
    ctx: AnalyticsContext,
    base: Dict[str, Any],
) -> List[Dict[str, Any]]:
    total_emp = base["total_emp"]
    total_emp_all = base["total_emp_all"]
    total_dept = base["total_dept"]
    open_vacancies = base["open_vacancies"]
    open_jobs_count = base["open_jobs_count"]
    total_applications = base["total_applications"]
    total_payroll_base = base["total_payroll_base"]
    can_see_salary = base["can_see_salary"]
    prev_headcount = base["prev_headcount"]
    latest_payroll_gross = base["latest_payroll_gross"]
    prev_payroll_gross = base["prev_payroll_gross"]

    if total_emp == 0 and open_jobs_count == 0:
        return []

    # Active ratio for workforce health
    active_ratio = (total_emp / total_emp_all * 100) if total_emp_all > 0 else 0

    # Employee trend: percent change vs previous month
    emp_trend = None
    if prev_headcount > 0:
        emp_trend = round(((total_emp - prev_headcount) / prev_headcount) * 100, 1)

    # Payroll trend: percent change vs previous cycle
    payroll_trend = None
    if prev_payroll_gross > 0:
        payroll_trend = round(((latest_payroll_gross - prev_payroll_gross) / prev_payroll_gross) * 100, 1)

    # Hiring pipeline: applications received / open vacancies (capped at 100)
    hiring_pipeline = None
    if open_vacancies > 0:
        hiring_pipeline = min(100, round((total_applications / open_vacancies) * 100))

    kpis = [
        {
            "label": "Total Employees",
            "score": total_emp,
            "trend": emp_trend,
            "hint": f"{total_emp} active employees ({total_emp_all} total non-deleted).",
            "icon": _valid_icon("Users"),
            "unit": "count",
        },
        {
            "label": "Departments",
            "score": total_dept,
            "trend": None,
            "hint": f"{total_dept} active departments with staff.",
            "icon": _valid_icon("Target"),
            "unit": "count",
        },
        {
            "label": "Open Positions",
            "score": open_vacancies,
            "trend": None,
            "hint": f"{open_jobs_count} active requisitions, {open_vacancies} total vacancies.",
            "icon": _valid_icon("Briefcase"),
            "unit": "count",
        },
        {
            "label": "Workforce Health",
            "score": round(active_ratio),
            "trend": None,
            "hint": f"{total_emp}/{total_emp_all} employees active ({active_ratio:.0f}%)." if total_emp_all > 0 else "Not enough data",
            "icon": _valid_icon("HeartPulse"),
            "unit": "percent",
        },
        {
            "label": "Hiring Pipeline",
            "score": hiring_pipeline if hiring_pipeline is not None else 0,
            "trend": None,
            "hint": f"{total_applications} applications for {open_vacancies} vacancies ({hiring_pipeline:.0f}%)." if hiring_pipeline is not None else "No open vacancies",
            "icon": _valid_icon("TrendingUp"),
            "unit": "percent",
        },
    ]

    if can_see_salary and total_payroll_base > 0:
        kpis.append({
            "label": "Payroll Base",
            "score": int(total_payroll_base),
            "trend": payroll_trend,
            "hint": f"Total base salary of {total_emp} active employees: ₹{total_payroll_base:,.0f}." + (f" ({payroll_trend:+.1f}% vs prev cycle)" if payroll_trend is not None else " (no previous cycle data)"),
            "icon": _valid_icon("Banknote"),
            "unit": "currency",
        })

    return kpis

# ── Attrition Section ──────────────────────────────────────────────────────────
async def _build_attrition_section(
    session: AsyncSession,
    ctx: AnalyticsContext,
    base: Dict[str, Any],
    today: date,
) -> List[Dict[str, Any]]:
    """Compute attrition risk over ALL active employees using SQL-level risk scoring."""
    # Use a single query with CASE expression for risk scoring
    risk_stmt = select(
        Employee.id,
        Employee.first_name,
        Employee.last_name,
        Employee.department,
        Employee.designation,
        Employee.basic_salary,
        Employee.joining_date,
    ).where(
        Employee.company_id == ctx.company_id,
        Employee.is_deleted == False,
        Employee.status == "ACTIVE",
        Employee.is_active == True,
    )
    if ctx.allowed_employee_ids is not None:
        risk_stmt = risk_stmt.where(Employee.id.in_(ctx.allowed_employee_ids))

    result = await session.execute(risk_stmt)
    all_emps = result.fetchall()

    if not all_emps:
        return []

    attrition = []
    for e in all_emps:
        emp_id, first_name, last_name, dept, designation, basic_salary, joining = e
        full_name = f"{first_name or ''} {last_name or ''}".strip()
        if not full_name:
            continue

        dept_name = designation or dept or "General"
        salary = float(basic_salary or 0)
        joining_date = joining

        tenure_days = (today - joining_date).days if joining_date else 0
        risk_score = 0
        reasons = []

        # Salary-based risk
        if salary > 0 and salary < LOW_SALARY_THRESHOLD:
            risk_score += 30
            reasons.append(f"Below ₹{LOW_SALARY_THRESHOLD:,} salary band")
        elif salary > 0 and salary < MID_SALARY_THRESHOLD:
            risk_score += 15
            reasons.append(f"Below ₹{MID_SALARY_THRESHOLD:,} salary band")

        # Tenure-based risk
        if tenure_days < EARLY_TENURE_DAYS:
            risk_score += 25
            reasons.append("Early tenure — high churn window")
        elif tenure_days < MID_TENURE_DAYS:
            risk_score += 10
            reasons.append("Within first year")

        # Missing designation
        if not designation:
            risk_score += 15
            reasons.append("Missing designation — role clarity needed")

        if not reasons:
            reasons.append("Stable — low risk factors detected")

        risk_score = min(99, max(10, risk_score))
        attrition.append({
            "id": _stable_id(str(ctx.company_id), "attrition", str(emp_id)),
            "name": full_name,
            "dept": dept_name,
            "risk": risk_score,
            "reason": "; ".join(reasons),
            "action": "Compensation review" if (salary > 0 and salary < LOW_SALARY_THRESHOLD) else "Regular check-in",
        })

    # Sort by risk descending, return top 6
    attrition.sort(key=lambda x: x["risk"], reverse=True)
    return attrition[:6]

# ── Burnout Section ────────────────────────────────────────────────────────────
async def _build_burnout_section(
    session: AsyncSession,
    ctx: AnalyticsContext,
    base: Dict[str, Any],
    today: date,
) -> List[Dict[str, Any]]:
    """Compute burnout risk using real overtime and leave data (last 90 days)."""
    # Fetch overtime hours per employee (last 90 days)
    ninety_days_ago = today.replace(day=1)
    # Approximate 3 months back
    if ninety_days_ago.month <= 3:
        ot_start = date(ninety_days_ago.year - 1, ninety_days_ago.month + 9, 1)
    else:
        ot_start = date(ninety_days_ago.year, ninety_days_ago.month - 3, 1)

    # Overtime data
    ot_stmt = select(
        OvertimeEntry.employee_id,
        func.coalesce(func.sum(OvertimeEntry.ot_hours), 0),
    ).where(
        OvertimeEntry.company_id == ctx.company_id,
        OvertimeEntry.period_year > ot_start.year,
        (OvertimeEntry.period_year > ot_start.year) |
        (OvertimeEntry.period_month >= ot_start.month),
        OvertimeEntry.status.in_(["APPROVED", "PUSHED"]),
    ).group_by(OvertimeEntry.employee_id)

    if ctx.allowed_employee_ids is not None:
        ot_stmt = ot_stmt.where(OvertimeEntry.employee_id.in_(ctx.allowed_employee_ids))

    ot_result = await session.execute(ot_stmt)
    ot_by_emp = {str(r[0]): float(r[1] or 0) for r in ot_result.fetchall()}

    # Leave data (approved days last 90 days)
    leave_stmt = select(
        LeaveRequest.employee_id,
        func.coalesce(func.sum(LeaveRequest.total_days), 0),
    ).join(Employee, LeaveRequest.employee_id == Employee.id).where(
        Employee.company_id == ctx.company_id,
        Employee.is_deleted == False,
        Employee.status == "ACTIVE",
        Employee.is_active == True,
        LeaveRequest.status == "APPROVED",
        LeaveRequest.start_date >= ot_start,
    ).group_by(LeaveRequest.employee_id)

    if ctx.allowed_employee_ids is not None:
        leave_stmt = leave_stmt.where(LeaveRequest.employee_id.in_(ctx.allowed_employee_ids))

    leave_result = await session.execute(leave_stmt)
    leave_by_emp = {str(r[0]): float(r[1] or 0) for r in leave_result.fetchall()}

    if not ot_by_emp and not leave_by_emp:
        return []

    # Get employee details for those with signals
    emp_ids = set(list(ot_by_emp.keys()) + list(leave_by_emp.keys()))
    if not emp_ids:
        return []

    emp_stmt = select(
        Employee.id,
        Employee.first_name,
        Employee.last_name,
    ).where(
        Employee.id.in_([uuid.UUID(eid) for eid in emp_ids]),
    )
    emp_result = await session.execute(emp_stmt)
    emp_names = {str(r[0]): f"{r[1] or ''} {r[2] or ''}".strip() for r in emp_result.fetchall()}

    burnout = []
    for emp_id in emp_ids:
        name = emp_names.get(emp_id, "Unknown")
        if not name or name == "Unknown":
            continue

        ot_hours = ot_by_emp.get(emp_id, 0)
        leave_days = leave_by_emp.get(emp_id, 0)

        # Burnout score: based on overtime hours and leave usage
        score = 10
        if ot_hours > OVERTIME_BURNOUT_HOURS:
            score += min(40, int(ot_hours * 2))  # cap at 50 from OT
        if leave_days > 10:
            score += min(20, int(leave_days))  # cap at 30 from leave

        burnout.append({
            "id": _stable_id(str(ctx.company_id), "burnout", emp_id),
            "name": name,
            "score": min(99, max(10, score)),
            "overtime": round(ot_hours, 1),
            "leave": round(leave_days, 1),
        })

    # Sort by score descending, return top 6
    burnout.sort(key=lambda x: x["score"], reverse=True)
    return burnout[:6]

# ── Attendance Section ─────────────────────────────────────────────────────────
def _build_attendance_section(base: Dict[str, Any]) -> List[Dict[str, Any]]:
    total_emp = base["total_emp"]
    total_dept = base["total_dept"]
    if total_emp == 0:
        return []

    return [
        {
            "id": _stable_id("attendance", "active"),
            "title": "Active Employees",
            "count": total_emp,
            "tone": "info",
            "note": "Total active employees",
        },
        {
            "id": _stable_id("attendance", "departments"),
            "title": "Departments Tracked",
            "count": total_dept,
            "tone": "info",
            "note": "Departments with active staff",
        },
    ]

# ── Recruitment Section ────────────────────────────────────────────────────────
async def _build_recruitment_section(
    session: AsyncSession,
    ctx: AnalyticsContext,
    base: Dict[str, Any],
) -> Dict[str, Any]:
    open_jobs_count = base["open_jobs_count"]
    open_vacancies = base["open_vacancies"]
    total_applications = base["total_applications"]
    candidates_list = []

    if open_jobs_count > 0:
        try:
            cand_stmt = (
                select(
                    Application.first_name,
                    Application.last_name,
                    Application.email,
                    Job.title,
                )
                .join(Job, Application.job_id == Job.id)
                .where(
                    Job.company_id == ctx.company_id,
                    Job.is_deleted == False,
                    Job.status == "PUBLISHED",
                )
                .order_by(Application.created_at.desc())
                .limit(5)
            )
            cand_rows = list((await session.execute(cand_stmt)).fetchall())
            for c in cand_rows:
                cname = f"{c[0] or ''} {c[1] or ''}".strip() or c[2] or "Applicant"
                candidates_list.append({
                    "id": _stable_id(str(ctx.company_id), "candidate", cname),
                    "name": cname,
                    "role": c[3] or "Open Role",
                })
        except Exception as e:
            logger.warning("Failed querying candidates: %s", e)

    return {
        "openPositions": open_vacancies,
        "activeRequisitions": open_jobs_count,
        "recommendedCandidatesCount": total_applications,
        "pipelineHealth": "Active" if open_jobs_count > 0 else "No open positions",
        "candidates": candidates_list,
    }

# ── Performance Section ────────────────────────────────────────────────────────
async def _build_performance_section(
    session: AsyncSession,
    ctx: AnalyticsContext,
    base: Dict[str, Any],
) -> Dict[str, Any]:
    """Use real PerformanceReview data if available, else return empty."""
    top_performers = []
    support_performers = []
    skill_gap = []

    # Check if PerformanceReview table has data
    try:
        perf_stmt = (
            select(
                Employee.id,
                Employee.first_name,
                Employee.last_name,
                Employee.department,
                Employee.designation,
                func.avg(PerformanceReview.self_rating).label("avg_rating"),
            )
            .join(PerformanceReview, PerformanceReview.employee_id == Employee.id)
            .where(
                Employee.company_id == ctx.company_id,
                Employee.is_deleted == False,
                Employee.status == "ACTIVE",
                Employee.is_active == True,
                PerformanceReview.status == "COMPLETED",
                PerformanceReview.self_rating.isnot(None),
            )
            .group_by(Employee.id, Employee.first_name, Employee.last_name, Employee.department, Employee.designation)
            .order_by(desc("avg_rating"))
            .limit(10)
        )
        if ctx.allowed_employee_ids is not None:
            perf_stmt = perf_stmt.where(Employee.id.in_(ctx.allowed_employee_ids))

        perf_result = await session.execute(perf_stmt)
        perf_rows = perf_result.fetchall()

        if perf_rows:
            # Top 3 by rating
            for idx, r in enumerate(perf_rows):
                emp_id, fn, ln, dept, desig, avg_rating = r
                full_name = f"{fn or ''} {ln or ''}".strip()
                if not full_name:
                    continue
                dept_name = desig or dept or "General"
                if idx < 3:
                    top_performers.append({
                        "id": _stable_id(str(ctx.company_id), "top_perf", str(emp_id)),
                        "name": full_name,
                        "dept": dept_name,
                        "rating": round(float(avg_rating), 1),
                    })
                else:
                    support_performers.append({
                        "id": _stable_id(str(ctx.company_id), "support_perf", str(emp_id)),
                        "name": full_name,
                        "dept": dept_name,
                        "rating": round(float(avg_rating), 1),
                        "coach": "Performance review completed",
                    })
    except Exception as e:
        logger.warning("Failed querying performance reviews: %s", e)

    # Skill gap: check if JobSkill exists and has data
    try:
        from app.models.recruitment import JobSkill
        skill_stmt = (
            select(JobSkill.skill_name, func.count(JobSkill.id))
            .join(Job, JobSkill.job_id == Job.id)
            .where(
                Job.company_id == ctx.company_id,
                Job.is_deleted == False,
                Job.status == "PUBLISHED",
            )
            .group_by(JobSkill.skill_name)
            .order_by(func.count(JobSkill.id).desc())
            .limit(5)
        )
        skill_result = await session.execute(skill_stmt)
        skill_rows = skill_result.fetchall()

        if skill_rows:
            # For "have", we'd need employee skills table which may not exist
            # Return empty list since we can't compute real "have" vs "need"
            skill_gap = []
    except Exception as e:
        logger.debug("JobSkill table not available or query failed: %s", e)

    return {
        "topPerformers": top_performers,
        "supportPerformers": support_performers,
        "skillGap": skill_gap,
    }

# ── Charts Section ─────────────────────────────────────────────────────────────
async def _build_charts_section(
    session: AsyncSession,
    ctx: AnalyticsContext,
    base: Dict[str, Any],
    today: date,
) -> Dict[str, Any]:
    total_emp = base["total_emp"]
    dept_rows = base["dept_rows"]
    open_jobs = base["open_jobs"]

    if total_emp == 0:
        return {
            "skillGap": [],
            "payrollTrend": [],
            "headcountForecast": [],
            "hiringDemand": [],
            "satisfactionTrend": [],
        }

    # 1. Skill Gap - empty since no real competency data
    skill_gap = []

    # 2. Payroll Trend - reuse logic from analytics_center_repository (last 6 months)
    payroll_trend = []
    try:
        current_year = today.year
        current_month = today.month
        for i in range(5, -1, -1):  # Last 6 months
            month = current_month - i
            year = current_year
            while month <= 0:
                month += 12
                year -= 1

            cycle_stmt = select(PayCycle.id).where(
                PayCycle.company_id == ctx.company_id,
                PayCycle.period_year == year,
                PayCycle.period_month == month,
            ).limit(1)
            cycle_res = await session.execute(cycle_stmt)
            cycle = cycle_res.scalar_one_or_none()

            gross = 0.0
            if cycle:
                gross_stmt = select(func.coalesce(func.sum(Payslip.gross_earnings), 0)).where(
                    Payslip.payroll_run_id == cycle.id,
                )
                if ctx.allowed_employee_ids is not None:
                    gross_stmt = gross_stmt.join(Employee, Payslip.employee_id == Employee.id).where(
                        Employee.id.in_(ctx.allowed_employee_ids)
                    )
                gross = float((await session.execute(gross_stmt)).scalar() or 0)

            if gross > 0:  # Skip months with 0 payslips
                payroll_trend.append({
                    "m": date(year, month, 1).strftime("%b"),
                    "cost": gross,
                })
    except Exception as e:
        logger.warning("Failed computing payroll trend: %s", e)

    # 3. Headcount Forecast - past 6 months (rolling) + future 3 months
    headcount_forecast = []
    try:
        # Get joining dates of all active employees
        joining_stmt = select(Employee.joining_date, Employee.deactivated_at).where(
            Employee.company_id == ctx.company_id,
            Employee.is_deleted == False,
            Employee.status == "ACTIVE",
            Employee.is_active == True,
            Employee.joining_date.isnot(None),
        )
        if ctx.allowed_employee_ids is not None:
            joining_stmt = joining_stmt.where(Employee.id.in_(ctx.allowed_employee_ids))
        joining_res = await session.execute(joining_stmt)
        joining_data = [(r[0], r[1]) for r in joining_res if r[0]]

        months_list = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

        # Past 6 months (including current)
        past_months = []
        for i in range(5, -1, -1):
            month = today.month - i
            year = today.year
            while month <= 0:
                month += 12
                year -= 1
            past_months.append((year, month))

        # Future 3 months
        future_months = []
        for i in range(1, 4):
            month = today.month + i
            year = today.year
            while month > 12:
                month -= 12
                year += 1
            future_months.append((year, month))

        all_months = past_months + future_months

        for year, month in all_months:
            _, last_day = calendar.monthrange(year, month)
            month_end = date(year, month, last_day)

            # Count employees who joined on or before month_end and haven't left by then
            count = 0
            for join_date, deactivated_at in joining_data:
                if join_date <= month_end:
                    if deactivated_at is None or deactivated_at.date() > month_end:
                        count += 1

            is_future = (year, month) in future_months
            is_current = (year == today.year and month == today.month)

            entry = {
                "month": months_list[month - 1],
                "current": count if not is_future else None,
                "forecast": count if not is_future else None,
            }

            if is_future:
                # Forecast = last_count + avg net monthly change
                if past_months:
                    # Compute average net change over past 6 months
                    past_counts = []
                    for py, pm in past_months:
                        _, p_last_day = calendar.monthrange(py, pm)
                        p_end = date(py, pm, p_last_day)
                        c = sum(1 for jd, dd in joining_data if jd <= p_end and (dd is None or dd.date() > p_end))
                        past_counts.append(c)
                    if len(past_counts) >= 2:
                        changes = [past_counts[i] - past_counts[i-1] for i in range(1, len(past_counts))]
                        avg_change = sum(changes) / len(changes) if changes else 0
                        forecast_val = max(0, round(count + avg_change))
                        entry["forecast"] = forecast_val
            elif is_current:
                entry["forecast"] = count  # Connect lines

            headcount_forecast.append(entry)

    except Exception as e:
        logger.warning("Failed computing headcount forecast: %s", e)

    # 4. Hiring Demand - open vacancies per department
    hiring_demand = []
    try:
        demand_stmt = (
            select(Job.department, func.coalesce(func.sum(Job.vacancies), 0))
            .where(
                Job.company_id == ctx.company_id,
                Job.is_deleted == False,
                Job.status == "PUBLISHED",
            )
            .group_by(Job.department)
        )
        demand_result = await session.execute(demand_stmt)
        demand_rows = demand_result.fetchall()

        # Also include departments from jobs that have no employees (case-insensitive)
        for dept, open_count in demand_rows:
            if dept and open_count > 0:
                hiring_demand.append({
                    "dept": dept.strip(),
                    "open": int(open_count),
                    "demand": int(open_count),  # No separate demand column, use open
                })
    except Exception as e:
        logger.warning("Failed computing hiring demand: %s", e)

    # 5. Satisfaction Trend - no real survey data
    satisfaction_trend = []

    return {
        "skillGap": skill_gap,
        "payrollTrend": payroll_trend,
        "headcountForecast": headcount_forecast,
        "hiringDemand": hiring_demand,
        "satisfactionTrend": satisfaction_trend,
    }

# ── Payroll Section ────────────────────────────────────────────────────────────
async def _build_payroll_section(
    session: AsyncSession,
    ctx: AnalyticsContext,
    base: Dict[str, Any],
    payroll_trend: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if not base["can_see_salary"] or base["total_payroll_base"] <= 0:
        return None

    # Compute payroll health from real data
    payroll_health = None
    savings_opportunities = None
    anomalies_detected = None

    if base["latest_payroll_gross"] > 0 and base["total_payroll_base"] > 0:
        # Health: ratio of actual payroll to base salary
        ratio = base["latest_payroll_gross"] / base["total_payroll_base"]
        if ratio > 1.2:
            payroll_health = 60
            savings_opportunities = "Overtime/allowances exceed base by >20%"
            anomalies_detected = 1
        elif ratio > 1.1:
            payroll_health = 75
            savings_opportunities = "Allowances slightly above base"
            anomalies_detected = 0
        else:
            payroll_health = 90
            savings_opportunities = "Payroll within expected range"
            anomalies_detected = 0

    return {
        "payrollHealth": payroll_health,
        "savingsOpportunities": savings_opportunities,
        "anomaliesDetected": anomalies_detected,
        "alerts": [],
        "trend": payroll_trend,
    }

# ── Recommendations Section ────────────────────────────────────────────────────
def _build_recommendations_section(base: Dict[str, Any]) -> List[str]:
    total_emp = base["total_emp"]
    open_jobs_count = base["open_jobs_count"]
    open_vacancies = base["open_vacancies"]
    total_dept = base["total_dept"]
    total_applications = base["total_applications"]

    recommendations = []
    if open_vacancies > 0:
        recommendations.append(f"There are {open_vacancies} open vacancies across {open_jobs_count} requisitions. Prioritize critical roles to reduce time-to-fill.")
    if total_dept > 1:
        recommendations.append(f"Workforce spans {total_dept} active departments. Monitor balanced headcount distribution.")
    if total_applications > 0:
        recommendations.append(f"{total_applications} job applications received. Screen and shortlist top candidates.")
    if total_emp == 0:
        recommendations.append("No active employees found. Verify onboarding and employee status data.")

    return recommendations

# ── Alerts Section ─────────────────────────────────────────────────────────────
def _build_alerts_section(base: Dict[str, Any]) -> List[Dict[str, Any]]:
    alerts = []
    total_emp = base["total_emp"]
    open_vacancies = base["open_vacancies"]
    can_see_salary = base["can_see_salary"]
    total_payroll_base = base["total_payroll_base"]
    latest_payroll_gross = base["latest_payroll_gross"]

    if total_emp == 0:
        alerts.append({
            "id": _stable_id("alert", "no_employees"),
            "title": "No Active Employees",
            "message": "No employees with ACTIVE status found. Check onboarding flow.",
            "severity": "warning",
        })

    if open_vacancies > 10:
        alerts.append({
            "id": _stable_id("alert", "high_vacancies"),
            "title": "High Vacancy Count",
            "message": f"{open_vacancies} open vacancies may indicate hiring urgency.",
            "severity": "info",
        })

    if can_see_salary and total_payroll_base > 0 and latest_payroll_gross > 0:
        ratio = latest_payroll_gross / total_payroll_base
        if ratio > 1.3:
            alerts.append({
                "id": _stable_id("alert", "payroll_overrun"),
                "title": "Payroll Overrun",
                "message": f"Actual payroll (₹{latest_payroll_gross:,.0f}) exceeds base (₹{total_payroll_base:,.0f}) by {((ratio-1)*100):.0f}%.",
                "severity": "critical",
            })

    return alerts

# ── Documents Section ──────────────────────────────────────────────────────────
def _build_documents_section() -> List[Dict[str, Any]]:
    # No documents data available in this context
    return []

# ── Complete Dashboard Assembly with Fault Tolerance ─────────────────────────
async def _build_section_with_error_handling(
    session: AsyncSession,
    ctx: AnalyticsContext,
    base: Dict[str, Any],
    today: date,
    section_name: str,
    builder_func,
    *args,
) -> tuple:
    """Execute a section builder with error handling, return (data, error)."""
    try:
        if asyncio.iscoroutinefunction(builder_func):
            data = await builder_func(session, ctx, base, *args)
        else:
            data = builder_func(base, *args)
        return data, None
    except Exception as e:
        logger.exception("Error computing %s section: %s", section_name, e)
        return None, str(e)

async def build_dashboard_resilient(
    session: AsyncSession,
    ctx: AnalyticsContext,
    refresh: bool = False,
) -> Dict[str, Any]:
    """Assemble complete AI Insights dataset with isolated failure domains and caching."""
    today = date.today()
    errors: Dict[str, str] = {}
    section_data: Dict[str, Any] = {}

    # Check cache for full dashboard
    if not refresh:
        cached = await _get_cached(ctx.company_id, "full_dashboard", refresh)
        if cached:
            return cached

    base = await _fetch_base_metrics(session, ctx)
    has_data = (base["total_emp"] > 0) or (base["open_jobs_count"] > 0)

    # 1. Summary
    summary = {
        "totalInsights": base["total_emp"] + base["open_jobs_count"] + base["total_dept"],
        "actionedCount": base["total_applications"],
        "criticalAlertsCount": 0,  # Will be updated after alerts
        "healthScoreDelta": 0,
    } if has_data else None

    # 2. KPI
    kpi, err = await _build_section_with_error_handling(
        session, ctx, base, today, "kpi", _build_kpi_section
    )
    if err:
        errors["kpi"] = err
        kpi = []
    section_data["kpi"] = kpi

    # 3. Attrition
    attrition, err = await _build_section_with_error_handling(
        session, ctx, base, today, "attrition", _build_attrition_section
    )
    if err:
        errors["attrition"] = err
        attrition = []
    section_data["attrition"] = attrition

    # 4. Burnout
    burnout, err = await _build_section_with_error_handling(
        session, ctx, base, today, "burnout", _build_burnout_section
    )
    if err:
        errors["burnout"] = err
        burnout = []
    section_data["burnout"] = burnout

    # 5. Attendance
    attendance, err = await _build_section_with_error_handling(
        session, ctx, base, today, "attendance", _build_attendance_section
    )
    if err:
        errors["attendance"] = err
        attendance = []
    section_data["attendance"] = attendance

    # 6. Recruitment
    recruitment, err = await _build_section_with_error_handling(
        session, ctx, base, today, "recruitment", _build_recruitment_section
    )
    if err:
        errors["recruitment"] = err
        recruitment = {"openPositions": 0, "activeRequisitions": 0, "recommendedCandidatesCount": 0, "pipelineHealth": "Inactive", "candidates": []}
    section_data["recruitment"] = recruitment

    # 7. Performance
    performance, err = await _build_section_with_error_handling(
        session, ctx, base, today, "performance", _build_performance_section
    )
    if err:
        errors["performance"] = err
        performance = {"topPerformers": [], "supportPerformers": [], "skillGap": []}
    section_data["performance"] = performance

    # 8. Charts
    charts, err = await _build_section_with_error_handling(
        session, ctx, base, today, "charts", _build_charts_section
    )
    if err:
        errors["charts"] = err
        charts = {"skillGap": [], "payrollTrend": [], "headcountForecast": [], "hiringDemand": [], "satisfactionTrend": []}
    section_data["charts"] = charts

    # 9. Payroll (depends on charts payrollTrend)
    payroll, err = await _build_section_with_error_handling(
        session, ctx, base, today, "payroll", _build_payroll_section, charts.get("payrollTrend", [])
    )
    if err:
        errors["payroll"] = err
        payroll = None
    section_data["payroll"] = payroll

    # 10. Recommendations
    recommendations, err = await _build_section_with_error_handling(
        session, ctx, base, today, "recommendations", _build_recommendations_section
    )
    if err:
        errors["recommendations"] = err
        recommendations = []
    section_data["recommendations"] = recommendations

    # 11. Alerts
    alerts, err = await _build_section_with_error_handling(
        session, ctx, base, today, "alerts", _build_alerts_section
    )
    if err:
        errors["alerts"] = err
        alerts = []
    section_data["alerts"] = alerts

    # 12. Documents
    documents, err = await _build_section_with_error_handling(
        session, ctx, base, today, "documents", _build_documents_section
    )
    if err:
        errors["documents"] = err
        documents = []
    section_data["documents"] = documents

    # Update critical alerts count in summary
    if summary:
        summary["criticalAlertsCount"] = sum(1 for a in alerts if a.get("severity") == "critical")

    result = {
        "has_data": has_data,
        "partial": len(errors) > 0,
        "errors": errors if errors else None,
        "summary": summary,
        "kpi": kpi,
        "attrition": attrition,
        "burnout": burnout,
        "attendance": attendance,
        "recruitment": recruitment,
        "performance": performance,
        "payroll": payroll,
        "charts": charts,
        "alerts": alerts,
        "recommendations": recommendations,
        "documents": documents,
    }

    # Cache the result
    await _set_cached(ctx.company_id, "full_dashboard", result)
    return result

# ── Individual Section Builders (for sub-endpoints) ────────────────────────────
async def _get_kpis_only(
    session: AsyncSession,
    ctx: AnalyticsContext,
    refresh: bool = False,
) -> List[Dict[str, Any]]:
    cached = await _get_cached(ctx.company_id, "kpi", refresh)
    if cached:
        return cached
    base = await _fetch_base_metrics(session, ctx)
    kpi = await _build_kpi_section(session, ctx, base)
    await _set_cached(ctx.company_id, "kpi", kpi)
    return kpi

async def _get_attrition_only(
    session: AsyncSession,
    ctx: AnalyticsContext,
    refresh: bool = False,
) -> List[Dict[str, Any]]:
    cached = await _get_cached(ctx.company_id, "attrition", refresh)
    if cached:
        return cached
    base = await _fetch_base_metrics(session, ctx)
    attrition = await _build_attrition_section(session, ctx, base, date.today())
    await _set_cached(ctx.company_id, "attrition", attrition)
    return attrition

async def _get_burnout_only(
    session: AsyncSession,
    ctx: AnalyticsContext,
    refresh: bool = False,
) -> List[Dict[str, Any]]:
    cached = await _get_cached(ctx.company_id, "burnout", refresh)
    if cached:
        return cached
    base = await _fetch_base_metrics(session, ctx)
    burnout = await _build_burnout_section(session, ctx, base, date.today())
    await _set_cached(ctx.company_id, "burnout", burnout)
    return burnout

async def _get_attendance_only(
    session: AsyncSession,
    ctx: AnalyticsContext,
    refresh: bool = False,
) -> List[Dict[str, Any]]:
    cached = await _get_cached(ctx.company_id, "attendance", refresh)
    if cached:
        return cached
    base = await _fetch_base_metrics(session, ctx)
    attendance = _build_attendance_section(base)
    await _set_cached(ctx.company_id, "attendance", attendance)
    return attendance

async def _get_recruitment_only(
    session: AsyncSession,
    ctx: AnalyticsContext,
    refresh: bool = False,
) -> Dict[str, Any]:
    cached = await _get_cached(ctx.company_id, "recruitment", refresh)
    if cached:
        return cached
    base = await _fetch_base_metrics(session, ctx)
    recruitment = await _build_recruitment_section(session, ctx, base)
    await _set_cached(ctx.company_id, "recruitment", recruitment)
    return recruitment

async def _get_performance_only(
    session: AsyncSession,
    ctx: AnalyticsContext,
    refresh: bool = False,
) -> Dict[str, Any]:
    cached = await _get_cached(ctx.company_id, "performance", refresh)
    if cached:
        return cached
    base = await _fetch_base_metrics(session, ctx)
    performance = await _build_performance_section(session, ctx, base)
    await _set_cached(ctx.company_id, "performance", performance)
    return performance

async def _get_charts_only(
    session: AsyncSession,
    ctx: AnalyticsContext,
    refresh: bool = False,
) -> Dict[str, Any]:
    cached = await _get_cached(ctx.company_id, "charts", refresh)
    if cached:
        return cached
    base = await _fetch_base_metrics(session, ctx)
    charts = await _build_charts_section(session, ctx, base, date.today())
    await _set_cached(ctx.company_id, "charts", charts)
    return charts

async def _get_recommendations_only(
    session: AsyncSession,
    ctx: AnalyticsContext,
    refresh: bool = False,
) -> List[str]:
    cached = await _get_cached(ctx.company_id, "recommendations", refresh)
    if cached:
        return cached
    base = await _fetch_base_metrics(session, ctx)
    recommendations = _build_recommendations_section(base)
    await _set_cached(ctx.company_id, "recommendations", recommendations)
    return recommendations

# ── Route Handlers ────────────────────────────────────────────────────────────
@router.get("/dashboard", status_code=status.HTTP_200_OK, summary="Get complete AI Insights dashboard metrics")
async def get_ai_insights_dashboard(
    refresh: Annotated[bool, Query(description="Bypass cache and force fresh computation")] = False,
    ctx: Annotated[AnalyticsContext, Depends(require_analytics_access)] = None,
    session: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[Dict[str, Any]]:
    data = await build_dashboard_resilient(session, ctx, refresh=refresh)
    return APIResponse[Dict[str, Any]](
        success=True,
        message="AI Insights dashboard data retrieved successfully.",
        data=data,
        errors=None,
    )

@router.get("/kpi", status_code=status.HTTP_200_OK)
async def get_kpis(
    refresh: Annotated[bool, Query(description="Bypass cache")] = False,
    ctx: Annotated[AnalyticsContext, Depends(require_analytics_access)] = None,
    session: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[List[Dict[str, Any]]]:
    data = await _get_kpis_only(session, ctx, refresh=refresh)
    return APIResponse[List[Dict[str, Any]]](
        success=True,
        message="KPIs retrieved successfully.",
        data=data,
        errors=None,
    )

@router.get("/attrition", status_code=status.HTTP_200_OK)
async def get_attrition(
    refresh: Annotated[bool, Query(description="Bypass cache")] = False,
    ctx: Annotated[AnalyticsContext, Depends(require_analytics_access)] = None,
    session: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[List[Dict[str, Any]]]:
    data = await _get_attrition_only(session, ctx, refresh=refresh)
    return APIResponse[List[Dict[str, Any]]](
        success=True,
        message="Attrition risk indicators retrieved successfully.",
        data=data,
        errors=None,
    )

@router.get("/burnout", status_code=status.HTTP_200_OK)
async def get_burnout(
    refresh: Annotated[bool, Query(description="Bypass cache")] = False,
    ctx: Annotated[AnalyticsContext, Depends(require_analytics_access)] = None,
    session: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[List[Dict[str, Any]]]:
    data = await _get_burnout_only(session, ctx, refresh=refresh)
    return APIResponse[List[Dict[str, Any]]](
        success=True,
        message="Burnout risk indicators retrieved successfully.",
        data=data,
        errors=None,
    )

@router.get("/attendance", status_code=status.HTTP_200_OK)
async def get_attendance(
    refresh: Annotated[bool, Query(description="Bypass cache")] = False,
    ctx: Annotated[AnalyticsContext, Depends(require_analytics_access)] = None,
    session: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[List[Dict[str, Any]]]:
    data = await _get_attendance_only(session, ctx, refresh=refresh)
    return APIResponse[List[Dict[str, Any]]](
        success=True,
        message="Attendance data retrieved successfully.",
        data=data,
        errors=None,
    )

@router.get("/performance", status_code=status.HTTP_200_OK)
async def get_performance(
    refresh: Annotated[bool, Query(description="Bypass cache")] = False,
    ctx: Annotated[AnalyticsContext, Depends(require_analytics_access)] = None,
    session: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[Dict[str, Any]]:
    data = await _get_performance_only(session, ctx, refresh=refresh)
    return APIResponse[Dict[str, Any]](
        success=True,
        message="Performance data retrieved successfully.",
        data=data,
        errors=None,
    )

@router.get("/recruitment", status_code=status.HTTP_200_OK)
async def get_recruitment(
    refresh: Annotated[bool, Query(description="Bypass cache")] = False,
    ctx: Annotated[AnalyticsContext, Depends(require_analytics_access)] = None,
    session: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[Dict[str, Any]]:
    data = await _get_recruitment_only(session, ctx, refresh=refresh)
    return APIResponse[Dict[str, Any]](
        success=True,
        message="Recruitment data retrieved successfully.",
        data=data,
        errors=None,
    )

@router.get("/charts", status_code=status.HTTP_200_OK)
async def get_charts(
    refresh: Annotated[bool, Query(description="Bypass cache")] = False,
    ctx: Annotated[AnalyticsContext, Depends(require_analytics_access)] = None,
    session: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[Dict[str, Any]]:
    data = await _get_charts_only(session, ctx, refresh=refresh)
    return APIResponse[Dict[str, Any]](
        success=True,
        message="Charts dataset retrieved successfully.",
        data=data,
        errors=None,
    )

@router.get("/recommendations", status_code=status.HTTP_200_OK)
async def get_recommendations(
    refresh: Annotated[bool, Query(description="Bypass cache")] = False,
    ctx: Annotated[AnalyticsContext, Depends(require_analytics_access)] = None,
    session: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[List[str]]:
    data = await _get_recommendations_only(session, ctx, refresh=refresh)
    return APIResponse[List[str]](
        success=True,
        message="Recommendations retrieved successfully.",
        data=data,
        errors=None,
    )

# Missing import
from datetime import timedelta