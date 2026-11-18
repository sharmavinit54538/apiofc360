"""HR Operations, Analytics, Reports & AI API v1."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone, timedelta
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import case, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.models.employee import Employee
from app.models.leave import LeaveRequest
from app.models.attendance import Attendance as AttendanceRecord
from app.models.payroll import PayCycle
from app.models.recruitment import Job, Application
from app.models.exit import EmployeeExit as ExitRequest
from app.models.timesheet import TimesheetEntry
from app.models.document import DocumentTemplate, EmployeeDocument
from app.models.connect import ConnectChannel as Channel, ConnectChannelMember as ChannelMember
from app.schemas.auth import APIResponse

router = APIRouter(prefix="/hr-ops", tags=["HR Operations & Analytics"])


async def _get_company_id(claims: dict) -> uuid.UUID:
    company_id_str = claims.get("company_id")
    if not company_id_str:
        raise HTTPException(status_code=403, detail="Company context missing")
    return uuid.UUID(company_id_str)


async def _get_user_id(claims: dict) -> uuid.UUID:
    user_id_str = claims.get("sub")
    if not user_id_str:
        raise HTTPException(status_code=401, detail="Invalid user claims")
    return uuid.UUID(user_id_str)


# ── HR Operations Overview ──────────────────────────────────────────────────

@router.get(
    "/overview",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Get HR operations overview",
)
async def get_hr_ops_overview(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[dict]:
    """Get HR operational metrics and pending approvals."""
    company_id = await _get_company_id(claims)
    user_role = claims.get("role", "").lower()

    if user_role not in {"super_admin", "hr_admin", "hr_manager", "executive", "ceo", "chro"}:
        raise HTTPException(status_code=403, detail="HR admin access required")

    # Pending approvals
    pending_leaves = (await db.execute(
        select(func.count(LeaveRequest.id)).where(
            LeaveRequest.company_id == company_id,
            LeaveRequest.status == "PENDING",
        )
    )).scalar_one() or 0

    pending_exits = (await db.execute(
        select(func.count(ExitRequest.id)).where(
            ExitRequest.company_id == company_id,
            ExitRequest.status.in_(["PENDING", "NOTICE_PERIOD"]),
        )
    )).scalar_one() or 0

    # Active employees
    active_employees = (await db.execute(
        select(func.count(Employee.id)).where(
            Employee.company_id == company_id,
            Employee.is_deleted == False,
            Employee.status == "ACTIVE",
        )
    )).scalar_one() or 0

    # Onboarding in progress
    onboarding_stmt = select(func.count(Employee.id)).where(
        Employee.company_id == company_id,
        Employee.is_deleted == False,
        Employee.status == "ONBOARDING",
    )
    onboarding_count = (await db.execute(onboarding_stmt)).scalar_one() or 0

    # Birthdays this week
    today = date.today()
    week_end = today + timedelta(days=7)
    birthdays_stmt = select(func.count(Employee.id)).where(
        Employee.company_id == company_id,
        Employee.is_deleted == False,
        Employee.status == "ACTIVE",
        func.extract("month", Employee.date_of_birth) == today.month,
        func.extract("day", Employee.date_of_birth) >= today.day,
        func.extract("day", Employee.date_of_birth) <= week_end.day,
    )
    birthdays_this_week = (await db.execute(birthdays_stmt)).scalar_one() or 0

    # Work anniversaries this week
    anniversaries_stmt = select(func.count(Employee.id)).where(
        Employee.company_id == company_id,
        Employee.is_deleted == False,
        Employee.status == "ACTIVE",
        func.extract("month", Employee.date_of_joining) == today.month,
        func.extract("day", Employee.date_of_joining) >= today.day,
        func.extract("day", Employee.date_of_joining) <= week_end.day,
    )
    anniversaries_this_week = (await db.execute(anniversaries_stmt)).scalar_one() or 0

    return APIResponse[dict](
        success=True,
        message="HR operations overview retrieved successfully.",
        data={
            "pending_approvals": {
                "leave_requests": pending_leaves,
                "exit_requests": pending_exits,
            },
            "workforce": {
                "active_employees": active_employees,
                "onboarding_in_progress": onboarding_count,
            },
            "upcoming_events": {
                "birthdays_this_week": birthdays_this_week,
                "anniversaries_this_week": anniversaries_this_week,
            },
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
        errors=None,
    )


# ── CTO Dashboard (alias) ───────────────────────────────────────────────────

@router.get(
    "/cto/dashboard",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Get CTO dashboard (alias)",
)
async def get_cto_dashboard_alias(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[dict]:
    """Alias for /cto/dashboard endpoint."""
    # Reuse the existing CTO dashboard logic
    from app.api.cto.dashboard import get_cto_dashboard_metrics
    return await get_cto_dashboard_metrics(claims, db)


# ── Analytics Metrics ───────────────────────────────────────────────────────

class AnalyticsMetricsQuery(BaseModel):
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    department: Optional[str] = None
    metric_type: Optional[str] = Field(default=None, pattern="^(headcount|attendance|leaves|recruitment|attrition|performance|all)$")


@router.get(
    "/analytics/metrics",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Get analytics metrics with filters",
)
async def get_analytics_metrics(
    date_from: Optional[date] = Query(None, description="Start date (YYYY-MM-DD)"),
    date_to: Optional[date] = Query(None, description="End date (YYYY-MM-DD)"),
    department: Optional[str] = Query(None, description="Filter by department"),
    metric_type: Optional[str] = Query("all", description="Metric type filter"),
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Get analytics metrics with date range and department filters."""
    company_id = await _get_company_id(claims)
    user_role = claims.get("role", "").lower()

    if user_role not in {"super_admin", "hr_admin", "hr_manager", "executive", "ceo", "chro", "cto", "cfo", "coo"}:
        raise HTTPException(status_code=403, detail="Analytics access required")

    if date_from is None:
        date_from = date.today() - timedelta(days=90)
    if date_to is None:
        date_to = date.today()

    # Headcount trend
    headcount_stmt = select(
        func.date_trunc("month", Employee.date_of_joining).label("month"),
        func.count(Employee.id).label("count"),
    ).where(
        Employee.company_id == company_id,
        Employee.is_deleted == False,
        Employee.date_of_joining >= date_from,
        Employee.date_of_joining <= date_to,
    ).group_by(func.date_trunc("month", Employee.date_of_joining)).order_by("month")
    hc_res = await db.execute(headcount_stmt)
    headcount_trend = [{"month": str(r.month)[:10], "count": r.count} for r in hc_res.all()]

    # Attendance rate
    att_stmt = select(
        func.count(AttendanceRecord.id).label("total"),
        func.sum(case((AttendanceRecord.status == "PRESENT", 1), else_=0)).label("present"),
    ).where(
        AttendanceRecord.company_id == company_id,
        AttendanceRecord.record_date >= date_from,
        AttendanceRecord.record_date <= date_to,
    )
    if department:
        att_stmt = att_stmt.join(Employee).where(Employee.department == department)
    att_res = await db.execute(att_stmt)
    att = att_res.first()
    attendance_rate = round((att.present or 0) / max(1, att.total or 1) * 100, 2)

    # Leave utilization
    leave_stmt = select(
        LeaveRequest.leave_type,
        func.count(LeaveRequest.id).label("count"),
        func.sum(LeaveRequest.days_requested).label("days"),
    ).where(
        LeaveRequest.company_id == company_id,
        LeaveRequest.status == "APPROVED",
        LeaveRequest.start_date >= date_from,
        LeaveRequest.start_date <= date_to,
    ).group_by(LeaveRequest.leave_type)
    leave_res = await db.execute(leave_stmt)
    leave_by_type = [{"leave_type": r.leave_type, "count": r.count, "days": float(r.days or 0)} for r in leave_res.all()]

    # Attrition rate
    total_exits = (await db.execute(
        select(func.count(ExitRequest.id)).where(
            ExitRequest.company_id == company_id,
            ExitRequest.status == "COMPLETED",
            ExitRequest.last_working_date >= date_from,
            ExitRequest.last_working_date <= date_to,
        )
    )).scalar_one() or 0
    attrition_rate = round(total_exits / max(1, active_employees) * 100, 2) if (active_employees := (await db.execute(
        select(func.count(Employee.id)).where(
            Employee.company_id == company_id,
            Employee.is_deleted == False,
            Employee.status == "ACTIVE",
        )
    )).scalar_one() or 0) else 0

    return APIResponse[dict](
        success=True,
        message="Analytics metrics retrieved successfully.",
        data={
            "date_range": {"from": date_from.isoformat(), "to": date_to.isoformat()},
            "department_filter": department,
            "headcount_trend": headcount_trend,
            "attendance_rate": attendance_rate,
            "leave_utilization": leave_by_type,
            "attrition_rate": attrition_rate,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
        errors=None,
    )


# ── Analytics Export ────────────────────────────────────────────────────────

class AnalyticsExportRequest(BaseModel):
    date_from: date
    date_to: date
    department: Optional[str] = None
    metrics: list[str] = Field(default_factory=lambda: ["headcount", "attendance", "leaves", "attrition"])
    format: Literal["csv", "xlsx", "json"] = "csv"


@router.get(
    "/reports/analytics/export",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Export analytics report",
)
async def export_analytics_report(
    date_from: date = Query(..., description="Start date (YYYY-MM-DD)"),
    date_to: date = Query(..., description="End date (YYYY-MM-DD)"),
    department: Optional[str] = Query(None, description="Filter by department"),
    metrics: str = Query("headcount,attendance,leaves,attrition", description="Comma-separated metrics"),
    format: str = Query("csv", description="Export format: csv, xlsx, json"),
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Export analytics report in CSV/XLSX/JSON format."""
    company_id = await _get_company_id(claims)
    user_role = claims.get("role", "").lower()

    if user_role not in {"super_admin", "hr_admin", "hr_manager", "executive", "ceo", "chro"}:
        raise HTTPException(status_code=403, detail="Report export access required")

    # For now, return the data as JSON (CSV/XLSX would require file generation)
    metric_list = [m.strip() for m in metrics.split(",")]

    # Reuse the metrics endpoint logic
    # This is a simplified version - in production, use a proper export service
    from io import StringIO
    import csv

    output = StringIO()
    writer = csv.writer(output)

    if "headcount" in metric_list:
        writer.writerow(["Metric", "Department", "Count", "Date"])
        hc_stmt = select(
            Employee.department,
            func.count(Employee.id).label("count"),
        ).where(
            Employee.company_id == company_id,
            Employee.is_deleted == False,
            Employee.date_of_joining >= date_from,
            Employee.date_of_joining <= date_to,
        ).group_by(Employee.department)
        hc_res = await db.execute(hc_stmt)
        writer.writerow(["Headcount", "", "", ""])
        for r in hc_res.all():
            writer.writerow(["", r.department or "Unknown", r.count, date.today().isoformat()])

    if "attendance" in metric_list:
        att_stmt = select(
            Employee.department,
            func.count(AttendanceRecord.id).label("total"),
            func.sum(case((AttendanceRecord.status == "PRESENT", 1), else_=0)).label("present"),
        ).where(
            AttendanceRecord.company_id == company_id,
            AttendanceRecord.record_date >= date_from,
            AttendanceRecord.record_date <= date_to,
        ).join(Employee).group_by(Employee.department)
        att_res = await db.execute(att_stmt)
        writer.writerow(["Attendance", "", "", ""])
        for r in att_res.all():
            rate = round((r.present or 0) / max(1, r.total or 1) * 100, 2)
            writer.writerow(["", r.department or "Unknown", rate, ""])

    csv_content = output.getvalue()

    return APIResponse[dict](
        success=True,
        message="Analytics report generated successfully.",
        data={
            "format": format,
            "date_range": {"from": date_from.isoformat(), "to": date_to.isoformat()},
            "metrics": metric_list,
            "content_base64": __import__("base64").b64encode(csv_content.encode("utf-8")).decode("ascii"),  # Simplified encoding
            "filename": f"analytics_report_{date_from}_{date_to}.csv",
        },
        errors=None,
    )


# ── Document Generation ─────────────────────────────────────────────────────

class DocumentGenerateRequest(BaseModel):
    template_id: uuid.UUID
    employee_id: uuid.UUID
    variables: dict = Field(default_factory=dict)


@router.post(
    "/documents/generate",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[dict],
    summary="Generate document from template",
)
async def generate_document(
    payload: DocumentGenerateRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[dict]:
    """Generate a document using a template and employee data."""
    company_id = await _get_company_id(claims)
    user_role = claims.get("role", "").lower()

    if user_role not in {"super_admin", "hr_admin", "hr_manager", "executive"}:
        raise HTTPException(status_code=403, detail="Document generation access required")

    # Validate template
    template_stmt = select(DocumentTemplate).where(
        DocumentTemplate.id == payload.template_id,
        DocumentTemplate.company_id == company_id,
    )
    template_res = await db.execute(template_stmt)
    template = template_res.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    # Validate employee
    emp_stmt = select(Employee).where(
        Employee.id == payload.employee_id,
        Employee.company_id == company_id,
        Employee.is_deleted == False,
    )
    emp_res = await db.execute(emp_stmt)
    employee = emp_res.scalar_one_or_none()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    from app.services.letter_service import LetterService
    from app.services.document_service import DocumentService
    from app.services.ai_hub.document_generator_service import DocumentGeneratorService
    variables = dict(payload.variables)
    variables.update(employee_name=f"{employee.first_name} {employee.last_name}".strip(),
                     employee_id=str(employee.id))
    missing = set(DocumentGeneratorService.extract_placeholders(template.template_body)) - variables.keys()
    if missing:
        raise HTTPException(422, "Missing template variables: " + ", ".join(sorted(missing)))
    text = LetterService.substitute(template.template_body, variables)
    pdf = DocumentService._render_text_to_pdf(template.name, text)
    document = await LetterService(db).save_employee_pdf(
        employee=employee, title=template.name, document_type="GENERATED",
        pdf_bytes=pdf, actor_id=await _get_user_id(claims), commit=True)
    document_id = document.id

    return APIResponse[dict](
        success=True,
        message="Document generated successfully.",
        data={
            "document_id": str(document_id),
            "template_id": str(template.id),
            "template_name": template.name,
            "employee_id": str(employee.id),
            "employee_name": f"{employee.first_name} {employee.last_name}".strip(),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "download_url": f"/api/v1/documents/{document_id}/download",
        },
        errors=None,
    )


# ── AI Timesheet Suggestions ────────────────────────────────────────────────

@router.get(
    "/timesheets/ai-suggest",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Get AI timesheet suggestions",
)
async def get_ai_timesheet_suggestions(
    employee_id: Optional[uuid.UUID] = Query(None, description="Target employee (defaults to current user)"),
    date_from: Optional[date] = Query(None, description="Start date"),
    date_to: Optional[date] = Query(None, description="End date"),
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Get AI-powered timesheet suggestions based on historical data."""
    company_id = await _get_company_id(claims)
    current_user_id = await _get_user_id(claims)

    # Determine target employee
    target_employee_id = employee_id
    if target_employee_id is None:
        emp_stmt = select(Employee).where(
            Employee.user_id == current_user_id,
            Employee.company_id == company_id,
            Employee.is_deleted == False,
        )
        emp_res = await db.execute(emp_stmt)
        employee = emp_res.scalar_one_or_none()
        if not employee:
            raise HTTPException(status_code=404, detail="Employee profile not found")
        target_employee_id = employee.id
    else:
        # Verify access
        if claims.get("role", "").lower() not in {"super_admin", "hr_admin", "hr_manager", "manager"}:
            emp_stmt = select(Employee).where(
                Employee.user_id == current_user_id,
                Employee.company_id == company_id,
            )
            emp_res = await db.execute(emp_stmt)
            current_emp = emp_res.scalar_one_or_none()
            if not current_emp or current_emp.id != target_employee_id:
                raise HTTPException(status_code=403, detail="Access denied")

    if date_from is None:
        date_from = date.today() - timedelta(days=7)
    if date_to is None:
        date_to = date.today()

    # Get existing timesheets for pattern analysis
    ts_stmt = select(TimesheetEntry).where(
        TimesheetEntry.employee_id == target_employee_id,
        TimesheetEntry.entry_date >= date_from,
        TimesheetEntry.entry_date <= date_to,
    )
    ts_res = await db.execute(ts_stmt)
    existing_entries = ts_res.scalars().all()

    # Simple pattern-based suggestions (in production, use ML model)
    suggestions = []
    for entry in existing_entries:
        suggestions.append({
            "date": entry.entry_date.isoformat(),
            "project_id": entry.project_id,
            "task_description": entry.task_description,
            "hours": float(entry.hours_worked),
            "confidence": 0.85,
            "source": "historical_pattern",
        })

    # Add default suggestions for missing days
    existing_dates = {e.entry_date for e in existing_entries}
    current = date_from
    while current <= date_to:
        if current not in existing_dates and current.weekday() < 5:  # Weekdays only
            suggestions.append({
                "date": current.isoformat(),
                "project_id": existing_entries[0].project_id if existing_entries else None,
                "task_description": "Regular work",
                "hours": 8.0,
                "confidence": 0.6,
                "source": "default_workday",
            })
        current += timedelta(days=1)

    return APIResponse[dict](
        success=True,
        message="AI timesheet suggestions generated.",
        data={
            "employee_id": str(target_employee_id),
            "date_range": {"from": date_from.isoformat(), "to": date_to.isoformat()},
            "suggestions": suggestions,
            "disclaimer": "Suggestions are AI-generated and require review before submission.",
        },
        errors=None,
    )


# ── Policy Assistant Search ─────────────────────────────────────────────────

@router.get(
    "/policy-assistant/search",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Search organization policies",
)
async def search_policies(
    q: str = Query(..., min_length=2, description="Search query"),
    category: Optional[str] = Query(None, description="Policy category filter"),
    limit: int = Query(10, ge=1, le=50),
    page: int = Query(1, ge=1),
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Search organization-specific approved policies."""
    company_id = await _get_company_id(claims)

    from app.models.policy import CompanyPolicyDocument
    from app.services.policy_service import PolicyService
    stmt = select(CompanyPolicyDocument).where(
        CompanyPolicyDocument.company_id == company_id,
        CompanyPolicyDocument.status == "PUBLISHED",
        (CompanyPolicyDocument.title.ilike(f"%{q}%")) | (CompanyPolicyDocument.raw_content.ilike(f"%{q}%")),
    )
    if category:
        stmt = stmt.where(func.lower(CompanyPolicyDocument.category) == category.lower())
    policies = (await db.scalars(stmt.order_by(CompanyPolicyDocument.updated_at.desc()))).all()
    if claims.get("role") not in {"hr_admin", "super_admin"}:
        employee = await db.scalar(select(Employee).where(Employee.user_id == await _get_user_id(claims), Employee.company_id == company_id))
        policies = [p for p in policies if employee and PolicyService.employee_matches(p, employee)]
    filtered = [{"id": str(p.id), "title": p.title, "category": p.category,
                 "snippet": p.raw_content[:350], "document_url": None,
                 "last_updated": p.updated_at.isoformat(), "relevance_score": None} for p in policies]

    return APIResponse[dict](
        success=True,
        message="Policy search completed.",
        data={
            "query": q,
            "category_filter": category,
            "results": filtered[(page - 1) * limit:page * limit],
            "total_found": len(filtered),
        },
        errors=None,
    )


# ── Connect Channel Members ─────────────────────────────────────────────────

@router.get(
    "/connect/channels/{channel_id}/members",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Get channel members",
)
async def get_channel_members(
    channel_id: uuid.UUID,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Get members of a Connect channel."""
    company_id = await _get_company_id(claims)

    # Verify channel exists and user has access
    channel_stmt = select(Channel).where(
        Channel.id == channel_id,
        Channel.company_id == company_id,
    )
    channel_res = await db.execute(channel_stmt)
    channel = channel_res.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    # Check if user is member or admin
    member_stmt = select(ChannelMember).where(
        ChannelMember.channel_id == channel_id,
        ChannelMember.user_id == await _get_user_id(claims),
    )
    member_res = await db.execute(member_stmt)
    if not member_res.scalar_one_or_none() and claims.get("role", "").lower() not in {"super_admin", "hr_admin", "it_admin"}:
        raise HTTPException(status_code=403, detail="Not a member of this channel")

    # Get members with pagination
    members_stmt = select(ChannelMember, Employee).join(
        Employee, ChannelMember.user_id == Employee.user_id
    ).where(ChannelMember.channel_id == channel_id).offset((page - 1) * limit).limit(limit)
    members_res = await db.execute(members_stmt)
    members = members_res.all()

    items = []
    for member, emp in members:
        items.append({
            "user_id": str(member.user_id),
            "employee_id": str(emp.id) if emp else None,
            "name": f"{emp.first_name} {emp.last_name}".strip() if emp else "Unknown",
            "role": member.role,
            "joined_at": member.joined_at.isoformat() if member.joined_at else None,
        })

    total_stmt = select(func.count(ChannelMember.id)).where(ChannelMember.channel_id == channel_id)
    total = (await db.execute(total_stmt)).scalar_one() or 0

    return APIResponse[dict](
        success=True,
        message="Channel members retrieved successfully.",
        data={
            "channel_id": str(channel_id),
            "channel_name": channel.name,
            "members": items,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total,
                "pages": (total + limit - 1) // limit,
            },
        },
        errors=None,
    )


# ── Employee Promotion ──────────────────────────────────────────────────────

class EmployeePromoteRequest(BaseModel):
    new_designation: str = Field(min_length=1, max_length=100)
    new_department: Optional[str] = Field(default=None, max_length=100)
    new_manager_id: Optional[uuid.UUID] = None
    effective_date: date
    salary_change_percentage: Optional[float] = Field(default=None, ge=-100, le=1000)
    reason: str = Field(min_length=10, max_length=2000)


@router.patch(
    "/employees/{employee_id}/promote",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Promote employee",
)
async def promote_employee(
    employee_id: uuid.UUID,
    payload: EmployeePromoteRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[dict]:
    """Promote an employee with new designation, department, manager, and effective date."""
    company_id = await _get_company_id(claims)
    user_role = claims.get("role", "").lower()

    if user_role not in {"super_admin", "hr_admin", "hr_manager"}:
        raise HTTPException(status_code=403, detail="HR admin access required for promotions")

    # Validate employee exists
    emp_stmt = select(Employee).where(
        Employee.id == employee_id,
        Employee.company_id == company_id,
        Employee.is_deleted == False,
    )
    emp_res = await db.execute(emp_stmt)
    employee = emp_res.scalar_one_or_none()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    # Validate new manager if provided
    if payload.new_manager_id:
        mgr_stmt = select(Employee).where(
            Employee.id == payload.new_manager_id,
            Employee.company_id == company_id,
            Employee.is_deleted == False,
        )
        mgr_res = await db.execute(mgr_stmt)
        if not mgr_res.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="New manager not found")

    # Store old values for history
    old_designation = employee.designation
    old_department = employee.department
    old_manager_id = employee.manager_id

    # Apply promotion
    employee.designation = payload.new_designation
    if payload.new_department:
        employee.department = payload.new_department
    if payload.new_manager_id:
        employee.manager_id = payload.new_manager_id
    employee.updated_at = datetime.now(timezone.utc)

    # Record promotion history in onboarding_steps or a dedicated promotion table
    # For now, we'll add to employee's role_metadata
    role_meta = employee.role_metadata or {}
    if "promotion_history" not in role_meta:
        role_meta["promotion_history"] = []
    role_meta["promotion_history"].append({
        "date": payload.effective_date.isoformat(),
        "old_designation": old_designation,
        "new_designation": payload.new_designation,
        "old_department": old_department,
        "new_department": payload.new_department or old_department,
        "old_manager_id": str(old_manager_id) if old_manager_id else None,
        "new_manager_id": str(payload.new_manager_id) if payload.new_manager_id else None,
        "salary_change_percentage": payload.salary_change_percentage,
        "reason": payload.reason,
        "promoted_by": str(claims.get("sub")),
        "promoted_at": datetime.now(timezone.utc).isoformat(),
    })
    employee.role_metadata = role_meta

    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(employee, "role_metadata")

    await db.commit()
    await db.refresh(employee)

    return APIResponse[dict](
        success=True,
        message="Employee promoted successfully.",
        data={
            "employee_id": str(employee.id),
            "employee_name": f"{employee.first_name} {employee.last_name}".strip(),
            "old_designation": old_designation,
            "new_designation": employee.designation,
            "old_department": old_department,
            "new_department": employee.department,
            "effective_date": payload.effective_date.isoformat(),
            "salary_change_percentage": payload.salary_change_percentage,
        },
        errors=None,
    )