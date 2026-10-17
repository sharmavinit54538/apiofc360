"""FastAPI router for Reports and Analytics Management (API v2).

Provides canonical production endpoints for:
- Headcount, Department, and Tenure Analytics
- Turnover & Attrition Rate Analytics
- Payroll Cost Trend Analytics (Restricted to HR Admin & Executive)
- Statutory & POSH Compliance Analytics
- CSV Report Export Engine
- Tenant-Scoped Report Log & Statistics Management
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Dict, List, Optional
import uuid

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.schemas.auth import APIResponse
from app.services.analytics_access import AnalyticsContext, require_analytics_access
from app.services.analytics_reports_service import AnalyticsReportsService

router = APIRouter(
    prefix="/reports",
    tags=["Reports Management"],
)


# ---------------- Pydantic Schemas ----------------

class ReportCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    description: Optional[str] = None
    type: str = Field(
        "employee",
        description="employee | payroll | attendance | leave | recruitment | travel | compliance | audit | ai-insights",
    )
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


class HeadcountAnalyticsItem(BaseModel):
    m: str
    n: int


class DepartmentAnalyticsItem(BaseModel):
    name: str
    value: int


class TenureAnalyticsItem(BaseModel):
    range: str
    n: int


class TurnoverAnalyticsItem(BaseModel):
    period: str
    separations: int
    headcount: int
    rate: float


class PayrollCostAnalyticsItem(BaseModel):
    period: str
    total_gross: float
    total_net: float
    total_employees: int


class ComplianceAnalyticsResponse(BaseModel):
    total: int
    compliant: int
    pending: int
    overdue: int
    by_type: List[Dict[str, Any]]


# ---------------- Dependency Provider ----------------

def get_analytics_service(session: AsyncSession = Depends(get_db_session)) -> AnalyticsReportsService:
    return AnalyticsReportsService(session)


# ---------------- Report Log Endpoints ----------------

@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[List[ReportResponse]],
    summary="List generated and scheduled reports",
)
async def list_reports(
    ctx: Annotated[AnalyticsContext, Depends(require_analytics_access)],
    service: Annotated[AnalyticsReportsService, Depends(get_analytics_service)],
    type_filter: Optional[str] = Query(None, alias="type"),
    status_filter: Optional[str] = Query(None, alias="status"),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(100, ge=1, le=100),
) -> APIResponse[List[ReportResponse]]:
    reports, _ = await service.list_reports(
        ctx,
        type_filter=type_filter,
        status_filter=status_filter,
        search=search,
        page=page,
        limit=limit,
    )
    return APIResponse[List[ReportResponse]](
        success=True,
        message="Reports retrieved successfully.",
        data=[ReportResponse.model_validate(r) for r in reports],
    )


@router.get(
    "/stats",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ReportStatsResponse],
    summary="Get report stats dashboard overview",
)
async def get_report_stats(
    ctx: Annotated[AnalyticsContext, Depends(require_analytics_access)],
    service: Annotated[AnalyticsReportsService, Depends(get_analytics_service)],
) -> APIResponse[ReportStatsResponse]:
    data = await service.get_report_stats(ctx)
    return APIResponse[ReportStatsResponse](
        success=True,
        message="Report statistics calculated.",
        data=ReportStatsResponse(**data),
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[ReportResponse],
    summary="Generate or schedule a new report",
)
async def create_report(
    body: ReportCreate,
    ctx: Annotated[AnalyticsContext, Depends(require_analytics_access)],
    service: Annotated[AnalyticsReportsService, Depends(get_analytics_service)],
) -> APIResponse[ReportResponse]:
    db_report = await service.create_report(
        ctx,
        name=body.name,
        description=body.description,
        report_type=body.type,
        file_format=body.format,
        filters=body.filters,
        schedule=body.schedule,
    )
    return APIResponse[ReportResponse](
        success=True,
        message="Report generated successfully.",
        data=ReportResponse.model_validate(db_report),
    )


@router.post(
    "/{id}/refresh",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ReportResponse],
    summary="Refresh report compilation data",
)
async def refresh_report(
    id: uuid.UUID,
    ctx: Annotated[AnalyticsContext, Depends(require_analytics_access)],
    service: Annotated[AnalyticsReportsService, Depends(get_analytics_service)],
) -> APIResponse[ReportResponse]:
    report = await service.refresh_report(ctx, id)
    return APIResponse[ReportResponse](
        success=True,
        message="Report refreshed and re-compiled.",
        data=ReportResponse.model_validate(report),
    )


@router.delete(
    "/{id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[None],
    summary="Delete a report log entry",
)
async def delete_report(
    id: uuid.UUID,
    ctx: Annotated[AnalyticsContext, Depends(require_analytics_access)],
    service: Annotated[AnalyticsReportsService, Depends(get_analytics_service)],
) -> APIResponse[None]:
    await service.delete_report(ctx, id)
    return APIResponse[None](
        success=True,
        message="Report entry deleted successfully.",
        data=None,
    )


# ---------------- Dynamic Analytics Aggregates ----------------

@router.api_route(
    "/analytics/headcount",
    methods=["GET", "HEAD"],
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[List[HeadcountAnalyticsItem]],
    summary="Get headcount growth analytics",
)
async def get_headcount_analytics(
    ctx: Annotated[AnalyticsContext, Depends(require_analytics_access)],
    service: Annotated[AnalyticsReportsService, Depends(get_analytics_service)],
    start_date: Optional[date] = Query(None, description="Start date filter (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, description="End date filter (YYYY-MM-DD)"),
    department: Optional[str] = Query(None, alias="department_id", description="Department filter"),
    status_filter: Optional[str] = Query(None, alias="status", description="Employee status filter"),
) -> APIResponse[List[HeadcountAnalyticsItem]]:
    data = await service.get_headcount_analytics(
        ctx,
        start_date=start_date,
        end_date=end_date,
        department=department,
        status_filter=status_filter,
    )
    return APIResponse[List[HeadcountAnalyticsItem]](
        success=True,
        message="Headcount analytics compiled.",
        data=[HeadcountAnalyticsItem(**item) for item in data],
    )


@router.api_route(
    "/analytics/department",
    methods=["GET", "HEAD"],
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[List[DepartmentAnalyticsItem]],
    summary="Get department-wise employee distribution",
)
async def get_department_analytics(
    ctx: Annotated[AnalyticsContext, Depends(require_analytics_access)],
    service: Annotated[AnalyticsReportsService, Depends(get_analytics_service)],
    start_date: Optional[date] = Query(None, description="Start date filter"),
    end_date: Optional[date] = Query(None, description="End date filter"),
    department: Optional[str] = Query(None, alias="department_id", description="Department filter"),
    status_filter: Optional[str] = Query(None, alias="status", description="Employee status filter"),
) -> APIResponse[List[DepartmentAnalyticsItem]]:
    data = await service.get_department_analytics(
        ctx,
        start_date=start_date,
        end_date=end_date,
        department=department,
        status_filter=status_filter,
    )
    return APIResponse[List[DepartmentAnalyticsItem]](
        success=True,
        message="Department analytics compiled.",
        data=[DepartmentAnalyticsItem(**item) for item in data],
    )


@router.api_route(
    "/analytics/tenure",
    methods=["GET", "HEAD"],
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[List[TenureAnalyticsItem]],
    summary="Get tenure ranges distribution",
)
async def get_tenure_analytics(
    ctx: Annotated[AnalyticsContext, Depends(require_analytics_access)],
    service: Annotated[AnalyticsReportsService, Depends(get_analytics_service)],
    start_date: Optional[date] = Query(None, description="Start date filter"),
    end_date: Optional[date] = Query(None, description="End date filter"),
    department: Optional[str] = Query(None, alias="department_id", description="Department filter"),
    status_filter: Optional[str] = Query(None, alias="status", description="Employee status filter"),
) -> APIResponse[List[TenureAnalyticsItem]]:
    data = await service.get_tenure_analytics(
        ctx,
        start_date=start_date,
        end_date=end_date,
        department=department,
        status_filter=status_filter,
    )
    return APIResponse[List[TenureAnalyticsItem]](
        success=True,
        message="Tenure analytics compiled.",
        data=[TenureAnalyticsItem(**item) for item in data],
    )


@router.api_route(
    "/analytics/turnover",
    methods=["GET", "HEAD"],
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[List[TurnoverAnalyticsItem]],
    summary="Get monthly employee turnover and separations",
)
async def get_turnover_analytics(
    ctx: Annotated[AnalyticsContext, Depends(require_analytics_access)],
    service: Annotated[AnalyticsReportsService, Depends(get_analytics_service)],
    start_date: Optional[date] = Query(None, description="Start date filter"),
    end_date: Optional[date] = Query(None, description="End date filter"),
    department: Optional[str] = Query(None, alias="department_id", description="Department filter"),
) -> APIResponse[List[TurnoverAnalyticsItem]]:
    data = await service.get_turnover_analytics(
        ctx,
        start_date=start_date,
        end_date=end_date,
        department=department,
    )
    return APIResponse[List[TurnoverAnalyticsItem]](
        success=True,
        message="Turnover analytics compiled.",
        data=[TurnoverAnalyticsItem(**item) for item in data],
    )


@router.api_route(
    "/analytics/payroll-cost",
    methods=["GET", "HEAD"],
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[List[PayrollCostAnalyticsItem]],
    summary="Get monthly payroll cost totals (Restricted to HR Admin & Executive)",
)
async def get_payroll_cost_analytics(
    ctx: Annotated[AnalyticsContext, Depends(require_analytics_access)],
    service: Annotated[AnalyticsReportsService, Depends(get_analytics_service)],
    start_date: Optional[date] = Query(None, description="Start date filter"),
    end_date: Optional[date] = Query(None, description="End date filter"),
) -> APIResponse[List[PayrollCostAnalyticsItem]]:
    data = await service.get_payroll_cost_analytics(
        ctx,
        start_date=start_date,
        end_date=end_date,
    )
    return APIResponse[List[PayrollCostAnalyticsItem]](
        success=True,
        message="Payroll cost analytics compiled.",
        data=[PayrollCostAnalyticsItem(**item) for item in data],
    )


@router.api_route(
    "/analytics/compliance",
    methods=["GET", "HEAD"],
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ComplianceAnalyticsResponse],
    summary="Get statutory compliance obligations and status counts",
)
async def get_compliance_analytics(
    ctx: Annotated[AnalyticsContext, Depends(require_analytics_access)],
    service: Annotated[AnalyticsReportsService, Depends(get_analytics_service)],
    start_date: Optional[date] = Query(None, description="Start date filter"),
    end_date: Optional[date] = Query(None, description="End date filter"),
) -> APIResponse[ComplianceAnalyticsResponse]:
    data = await service.get_compliance_analytics(
        ctx,
        start_date=start_date,
        end_date=end_date,
    )
    return APIResponse[ComplianceAnalyticsResponse](
        success=True,
        message="Compliance analytics compiled.",
        data=ComplianceAnalyticsResponse(**data),
    )


# ---------------- CSV Export Engine ----------------

@router.get(
    "/export",
    summary="Export analytics dataset as CSV",
)
async def export_analytics_dataset(
    ctx: Annotated[AnalyticsContext, Depends(require_analytics_access)],
    service: Annotated[AnalyticsReportsService, Depends(get_analytics_service)],
    dataset: str = Query(
        "headcount",
        description="Dataset to export: headcount | department | tenure | turnover | payroll-cost | compliance",
    ),
    start_date: Optional[date] = Query(None, description="Start date filter"),
    end_date: Optional[date] = Query(None, description="End date filter"),
    department: Optional[str] = Query(None, alias="department_id", description="Department filter"),
    status_filter: Optional[str] = Query(None, alias="status", description="Status filter"),
) -> Response:
    csv_content = await service.export_dataset_csv(
        ctx,
        dataset=dataset,
        start_date=start_date,
        end_date=end_date,
        department=department,
        status_filter=status_filter,
    )
    clean_ds = dataset.lower().replace("-", "_")
    filename = f"report_{clean_ds}_{date.today().isoformat()}.csv"
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Content-Type": "text/csv; charset=utf-8",
        "X-Content-Type-Options": "nosniff",
    }
    return Response(content=csv_content, media_type="text/csv", headers=headers)
