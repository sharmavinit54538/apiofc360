"""FastAPI router for Reports and Analytics Management."""

import uuid
from datetime import date, datetime, timedelta
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, Query, status, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, or_, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims, get_current_user_claims_optional
from app.models.employee import Employee
from app.models.report import Report
from app.schemas.auth import APIResponse

router = APIRouter(prefix="/reports", tags=["Reports Management"])

# ---------------- Pydantic Schemas ----------------
class ReportCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    description: Optional[str] = None
    type: str = Field("employee", description="employee | payroll | attendance | leave | recruitment | travel | compliance | audit | ai-insights")
    format: str = Field("pdf", description="pdf | csv | excel")
    filters: Optional[Dict[str, Any]] = None
    schedule: Optional[str] = Field("none", description="none | daily | weekly | monthly")

class ReportResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: Optional[str]
    type: str
    status: str
    format: str
    filters: Optional[Dict[str, Any]]
    schedule: Optional[str]
    file_path: Optional[str]
    file_size_kb: float
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class ReportStatsResponse(BaseModel):
    total: int
    generated_today: int
    scheduled: int
    pending: int
    successful_exports: int
    failed: int
    active_dashboards: int
    storage_usage_mb: float

# ---------------- Database Self-Cleaning ----------------
async def clean_seeded_reports(db: AsyncSession) -> None:
    """Deletes previously seeded initial report paths to ensure only user-generated reports show up."""
    legacy_seed_paths = [
        "/exports/employee_directory.pdf",
        "/exports/payroll_summary_q2.xlsx",
        "/exports/attendance_june.csv",
        "/exports/compliance_audit_2026.pdf",
        "/exports/system_audit_logs.csv",
        "/exports/travel_budget_variance.pdf",
        "/exports/recruitment_pipeline.pdf",
        "/exports/ai_skill_gap.pdf"
    ]
    stmt = delete(Report).where(Report.file_path.in_(legacy_seed_paths))
    await db.execute(stmt)
    await db.commit()

# ---------------- API Endpoints ----------------

@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[List[ReportResponse]],
    summary="List generated and scheduled reports"
)
async def list_reports(
    type_filter: Optional[str] = Query(None, alias="type"),
    status_filter: Optional[str] = Query(None, alias="status"),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(100, ge=1, le=100),
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session)
) -> APIResponse[List[ReportResponse]]:
    await clean_seeded_reports(db)
    
    stmt = select(Report)
    
    if type_filter and type_filter != "all":
        stmt = stmt.where(Report.type == type_filter)
        
    if status_filter and status_filter != "all":
        stmt = stmt.where(Report.status == status_filter)
        
    if search:
        search_term = f"%{search.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Report.name).like(search_term),
                func.lower(Report.description).like(search_term)
            )
        )
        
    # Sort by created_at desc
    stmt = stmt.order_by(Report.created_at.desc())
    stmt = stmt.offset((page - 1) * limit).limit(limit)
    
    result = await db.execute(stmt)
    reports = result.scalars().all()
    
    return APIResponse[List[ReportResponse]](
        success=True,
        message="Reports retrieved successfully.",
        data=[ReportResponse.from_orm(r) for r in reports]
    )

@router.get(
    "/stats",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ReportStatsResponse],
    summary="Get report stats dashboard overview"
)
async def get_report_stats(
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session)
) -> APIResponse[ReportStatsResponse]:
    await clean_seeded_reports(db)
    
    # Total count
    total_stmt = select(func.count(Report.id))
    total_res = await db.execute(total_stmt)
    total = total_res.scalar() or 0
    
    # Generated Today
    today_start = datetime.combine(date.today(), datetime.min.time())
    today_stmt = select(func.count(Report.id)).where(Report.created_at >= today_start)
    today_res = await db.execute(today_stmt)
    generated_today = today_res.scalar() or 0
    
    # Scheduled reports (schedule not none)
    sched_stmt = select(func.count(Report.id)).where(
        or_(Report.schedule.isnot(None), Report.schedule != "none")
    )
    sched_res = await db.execute(sched_stmt)
    scheduled = sched_res.scalar() or 0
    
    # Pending reports
    pending_stmt = select(func.count(Report.id)).where(Report.status.in_(["pending", "running"]))
    pending_res = await db.execute(pending_stmt)
    pending = pending_res.scalar() or 0
    
    # Successful exports
    success_stmt = select(func.count(Report.id)).where(Report.status == "completed")
    success_res = await db.execute(success_stmt)
    successful_exports = success_res.scalar() or 0
    
    # Failed
    failed_stmt = select(func.count(Report.id)).where(Report.status == "failed")
    failed_res = await db.execute(failed_stmt)
    failed = failed_res.scalar() or 0
    
    # Storage Usage MB
    storage_stmt = select(func.sum(Report.file_size_kb))
    storage_res = await db.execute(storage_stmt)
    total_kb = float(storage_res.scalar() or 0.0)
    storage_usage_mb = round(total_kb / 1024.0, 2)
    
    # Active dashboards calculated from distinct report categories in DB
    dash_stmt = select(func.count(func.distinct(Report.type)))
    dash_res = await db.execute(dash_stmt)
    active_dashboards = dash_res.scalar() or 0

    data = ReportStatsResponse(
        total=total,
        generated_today=generated_today,
        scheduled=scheduled,
        pending=pending,
        successful_exports=successful_exports,
        failed=failed,
        active_dashboards=active_dashboards,
        storage_usage_mb=storage_usage_mb
    )
    return APIResponse[ReportStatsResponse](
        success=True,
        message="Report statistics calculated.",
        data=data
    )

@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[ReportResponse],
    summary="Generate or schedule a new report"
)
async def create_report(
    body: ReportCreate,
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session)
) -> APIResponse[ReportResponse]:
    ext = "pdf" if body.format == "pdf" else "xlsx" if body.format == "excel" else "csv"
    slug = body.name.lower().replace(" ", "_")
    file_path = f"/exports/{slug}.{ext}"
    
    import random
    file_size_kb = round(random.uniform(100.0, 3000.0), 2)
    
    db_report = Report(
        id=uuid.uuid4(),
        name=body.name,
        description=body.description,
        type=body.type,
        status="completed",
        format=body.format,
        filters=body.filters or {},
        schedule=body.schedule or "none",
        file_path=file_path,
        file_size_kb=file_size_kb
    )
    
    db.add(db_report)
    await db.commit()
    await db.refresh(db_report)
    
    return APIResponse[ReportResponse](
        success=True,
        message="Report generated successfully.",
        data=ReportResponse.from_orm(db_report)
    )

@router.post(
    "/{id}/refresh",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ReportResponse],
    summary="Refresh report compilation data"
)
async def refresh_report(
    id: uuid.UUID,
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session)
) -> APIResponse[ReportResponse]:
    stmt = select(Report).where(Report.id == id)
    res = await db.execute(stmt)
    report = res.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="Report log entry not found.")
        
    report.status = "completed"
    report.created_at = datetime.now()
    await db.commit()
    await db.refresh(report)
    
    return APIResponse[ReportResponse](
        success=True,
        message="Report refreshed and re-compiled.",
        data=ReportResponse.from_orm(report)
    )

@router.delete(
    "/{id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[None],
    summary="Delete a report log entry"
)
async def delete_report(
    id: uuid.UUID,
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session)
) -> APIResponse[None]:
    stmt = select(Report).where(Report.id == id)
    res = await db.execute(stmt)
    report = res.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="Report log entry not found.")
        
    await db.delete(report)
    await db.commit()
    
    return APIResponse[None](
        success=True,
        message="Report entry deleted successfully.",
        data=None
    )

# ---------------- Dynamic Analytics Aggregates ----------------

@router.api_route(
    "/analytics/headcount",
    methods=["GET", "HEAD"],
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[List[dict]],
    summary="Get headcount growth analytics"
)
async def get_headcount_analytics(
    claims: dict = Depends(get_current_user_claims_optional),
    db: AsyncSession = Depends(get_db_session)
) -> APIResponse[List[dict]]:
    result = await db.execute(select(Employee.joining_date))
    dates = [r[0] for r in result if r[0]]
    dates.sort()
    
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    headcount_data = []
    
    today = date.today()
    year = today.year
    
    for i in range(1, 13):
        if year == today.year and i > today.month:
            break
        month_end = date(year, i, 28)
        count = sum(1 for d in dates if d <= month_end)
        
        # If database has zero active employees, return empty or zero count
        headcount_data.append({
            "m": months[i - 1],
            "n": count
        })
        
    return APIResponse[List[dict]](
        success=True,
        message="Headcount analytics compiled.",
        data=headcount_data
    )

@router.api_route(
    "/analytics/department",
    methods=["GET", "HEAD"],
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[List[dict]],
    summary="Get department-wise employee distribution"
)
async def get_department_analytics(
    claims: dict = Depends(get_current_user_claims_optional),
    db: AsyncSession = Depends(get_db_session)
) -> APIResponse[List[dict]]:
    stmt = select(Employee.department, func.count(Employee.id)).group_by(Employee.department)
    result = await db.execute(stmt)
    by_dept = []
    
    for dept, count in result:
        if dept:
            by_dept.append({
                "name": dept,
                "value": count
            })
            
    return APIResponse[List[dict]](
        success=True,
        message="Department analytics compiled.",
        data=by_dept
    )

@router.api_route(
    "/analytics/tenure",
    methods=["GET", "HEAD"],
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[List[dict]],
    summary="Get tenure ranges distribution"
)
async def get_tenure_analytics(
    claims: dict = Depends(get_current_user_claims_optional),
    db: AsyncSession = Depends(get_db_session)
) -> APIResponse[List[dict]]:
    result = await db.execute(select(Employee.joining_date))
    dates = [r[0] for r in result if r[0]]
    
    tenure_counts = {"0–1y": 0, "1–2y": 0, "2–3y": 0, "3–5y": 0, "5y+": 0}
    today = date.today()
    
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
            
    tenure_data = [{"range": k, "n": v} for k, v in tenure_counts.items()]
    
    return APIResponse[List[dict]](
        success=True,
        message="Tenure analytics compiled.",
        data=tenure_data
    )
