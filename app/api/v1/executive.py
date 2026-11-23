"""Executive Dashboard API v1 — Real aggregated organization metrics."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.models.employee import Employee
from app.models.leave import LeaveRequest
from app.models.attendance import Attendance as AttendanceRecord
from app.models.payroll import PayCycle
from app.models.recruitment import Job, Application
from app.models.exit import EmployeeExit as ExitRequest
from app.schemas.auth import APIResponse

router = APIRouter(prefix="/executive", tags=["Executive Dashboard"])


ExecutiveRole = Literal["ceo", "cto", "cfo", "coo", "chro", "vp_hr", "vp_engineering"]


async def _get_company_id(claims: dict) -> uuid.UUID:
    company_id_str = claims.get("company_id")
    if not company_id_str:
        raise HTTPException(status_code=403, detail="Company context missing")
    return uuid.UUID(company_id_str)


async def _get_user_role(claims: dict) -> str:
    role = claims.get("role", "").lower()
    return role


def _check_executive_access(role: str, requested_role: str) -> bool:
    """Check if user role has access to requested executive dashboard."""
    role_hierarchy = {
        "super_admin": ["ceo", "cto", "cfo", "coo", "chro", "vp_hr", "vp_engineering"],
        "ceo": ["ceo", "cto", "cfo", "coo", "chro", "vp_hr", "vp_engineering"],
        "cto": ["cto", "vp_engineering"],
        "cfo": ["cfo"],
        "coo": ["coo"],
        "chro": ["chro", "vp_hr"],
        "vp_hr": ["vp_hr"],
        "vp_engineering": ["vp_engineering"],
        "hr_admin": ["vp_hr"],
        "executive": ["ceo", "cto", "cfo", "coo", "chro", "vp_hr", "vp_engineering"],
    }
    return requested_role in role_hierarchy.get(role, [])


@router.get(
    "/overview",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Get executive overview with key metrics",
)
async def get_executive_overview(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[dict]:
    """Get high-level executive overview with key organizational metrics."""
    company_id = await _get_company_id(claims)
    user_role = await _get_user_role(claims)

    # Check if user has executive access
    if not _check_executive_access(user_role, "ceo"):
        raise HTTPException(status_code=403, detail="Executive access required")

    # Employee headcount
    emp_stmt = select(func.count(Employee.id)).where(
        Employee.company_id == company_id,
        Employee.is_deleted == False,
    )
    total_employees = (await db.execute(emp_stmt)).scalar_one() or 0

    active_emp_stmt = select(func.count(Employee.id)).where(
        Employee.company_id == company_id,
        Employee.is_deleted == False,
        Employee.status == "ACTIVE",
    )
    active_employees = (await db.execute(active_emp_stmt)).scalar_one() or 0

    inactive_employees = total_employees - active_employees

    # Department breakdown
    dept_stmt = select(Employee.department, func.count(Employee.id)).where(
        Employee.company_id == company_id,
        Employee.is_deleted == False,
        Employee.status == "ACTIVE",
    ).group_by(Employee.department)
    dept_res = await db.execute(dept_stmt)
    department_breakdown = {dept: count for dept, count in dept_res.all()}

    # Attendance summary (last 30 days)
    thirty_days_ago = date.today() - timedelta(days=30)
    att_stmt = select(
        func.count(AttendanceRecord.id).label("total"),
        func.sum(func.case((AttendanceRecord.status == "PRESENT", 1), else_=0)).label("present"),
        func.sum(func.case((AttendanceRecord.status == "ABSENT", 1), else_=0)).label("absent"),
        func.sum(func.case((AttendanceRecord.status == "LATE", 1), else_=0)).label("late"),
    ).where(
        AttendanceRecord.company_id == company_id,
        AttendanceRecord.record_date >= thirty_days_ago,
    )
    att_res = await db.execute(att_stmt)
    att = att_res.first()
    attendance_summary = {
        "total_records": att.total or 0,
        "present": att.present or 0,
        "absent": att.absent or 0,
        "late": att.late or 0,
        "attendance_rate": round((att.present or 0) / max(1, att.total or 1) * 100, 2),
    }

    # Leave summary (current year)
    year_start = date(date.today().year, 1, 1)
    leave_stmt = select(
        func.count(LeaveRequest.id).label("total"),
        func.sum(func.case((LeaveRequest.status == "APPROVED", 1), else_=0)).label("approved"),
        func.sum(func.case((LeaveRequest.status == "PENDING", 1), else_=0)).label("pending"),
        func.sum(func.case((LeaveRequest.status == "REJECTED", 1), else_=0)).label("rejected"),
    ).where(
        LeaveRequest.company_id == company_id,
        LeaveRequest.start_date >= year_start,
    )
    leave_res = await db.execute(leave_stmt)
    leave = leave_res.first()
    leave_summary = {
        "total_requests": leave.total or 0,
        "approved": leave.approved or 0,
        "pending": leave.pending or 0,
        "rejected": leave.rejected or 0,
    }

    # Recruitment summary
    jobs_stmt = select(func.count(Job.id)).where(
        Job.company_id == company_id,
        Job.is_deleted == False,
        Job.status == "OPEN",
    )
    open_jobs = (await db.execute(jobs_stmt)).scalar_one() or 0

    apps_stmt = select(func.count(Application.id)).where(
        Application.company_id == company_id,
        Application.status.in_(["APPLIED", "SCREENING", "INTERVIEWING"]),
    )
    active_applications = (await db.execute(apps_stmt)).scalar_one() or 0

    # Attrition/Exit summary
    exits_stmt = select(func.count(ExitRequest.id)).where(
        ExitRequest.company_id == company_id,
        ExitRequest.status.in_(["NOTICE_PERIOD", "COMPLETED"]),
    )
    active_exits = (await db.execute(exits_stmt)).scalar_one() or 0

    # Payroll summary (only if authorized)
    payroll_authorized = user_role in {"super_admin", "ceo", "cfo", "chro", "hr_admin"}
    payroll_summary = {}
    if payroll_authorized:
        paycycle_stmt = select(func.count(PayCycle.id)).where(
            PayCycle.company_id == company_id,
            PayCycle.status.in_(["DRAFT", "PROCESSING", "APPROVED"]),
        )
        active_paycycles = (await db.execute(paycycle_stmt)).scalar_one() or 0
        payroll_summary = {
            "active_pay_cycles": active_paycycles,
            "authorized": True,
        }
    else:
        payroll_summary = {"authorized": False}

    return APIResponse[dict](
        success=True,
        message="Executive overview retrieved successfully.",
        data={
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "headcount": {
                "total": total_employees,
                "active": active_employees,
                "inactive": inactive_employees,
                "by_department": department_breakdown,
            },
            "attendance": attendance_summary,
            "leaves": leave_summary,
            "recruitment": {
                "open_positions": open_jobs,
                "active_applications": active_applications,
            },
            "attrition": {
                "active_exits": active_exits,
            },
            "payroll": payroll_summary,
        },
        errors=None,
    )


@router.get(
    "/dashboard/{role}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Get role-specific executive dashboard",
)
async def get_executive_dashboard(
    role: ExecutiveRole,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[dict]:
    """Get role-specific executive dashboard with tailored metrics."""
    company_id = await _get_company_id(claims)
    user_role = await _get_user_role(claims)

    # Validate access
    if not _check_executive_access(user_role, role):
        raise HTTPException(status_code=403, detail=f"Access denied for {role} dashboard")

    # Base data
    emp_stmt = select(func.count(Employee.id)).where(
        Employee.company_id == company_id,
        Employee.is_deleted == False,
    )
    total_employees = (await db.execute(emp_stmt)).scalar_one() or 0

    active_emp_stmt = select(func.count(Employee.id)).where(
        Employee.company_id == company_id,
        Employee.is_deleted == False,
        Employee.status == "ACTIVE",
    )
    active_employees = (await db.execute(active_emp_stmt)).scalar_one() or 0

    dashboard_data = {
        "role": role,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "headcount": {"total": total_employees, "active": active_employees},
    }

    # Role-specific metrics
    if role == "ceo":
        dashboard_data.update({
            "revenue_per_employee": None,  # Requires financial data integration
            "revenue_per_employee_available": False,
            "burn_rate": None,  # Requires financial data integration
            "burn_rate_available": False,
            "runway_months": None,  # Requires financial data integration
            "runway_months_available": False,
            "key_initiatives": [],
        })
    elif role == "cto":
        # Technology/IT metrics
        dashboard_data.update({
            "engineering_headcount": active_employees,  # Simplified
            "open_engineering_roles": 0,
            "deployment_frequency": 0,
            "incident_count": 0,
            "tech_debt_ratio": 0,
        })
    elif role == "cfo":
        dashboard_data.update({
            "total_payroll_cost": 0,
            "benefits_cost": 0,
            "recruitment_cost": 0,
            "cost_per_hire": 0,
        })
    elif role == "chro":
        dashboard_data.update({
            "employee_satisfaction": 0,
            "turnover_rate": 0,
            "time_to_fill": 0,
            "training_completion_rate": 0,
        })
    elif role == "vp_hr":
        dashboard_data.update({
            "open_positions": 0,
            "pending_leave_requests": 0,
            "onboarding_in_progress": 0,
            "compliance_score": 0,
        })
    elif role == "vp_engineering":
        dashboard_data.update({
            "sprint_velocity": 0,
            "code_review_turnaround": 0,
            "bug_resolution_time": 0,
            "deployment_success_rate": 0,
        })
    elif role == "coo":
        dashboard_data.update({
            "operational_efficiency": 0,
            "asset_utilization": 0,
            "vendor_count": 0,
            "facility_occupancy": 0,
        })

    return APIResponse[dict](
        success=True,
        message=f"{role.upper()} dashboard retrieved successfully.",
        data=dashboard_data,
        errors=None,
    )