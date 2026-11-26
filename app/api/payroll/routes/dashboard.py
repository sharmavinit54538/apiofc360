"""Route handlers for high-level payroll dashboard metrics."""
from __future__ import annotations

import uuid
from typing import Optional
from fastapi import APIRouter, Query

from app.api.payroll.dependencies import DB, Claims
from app.api.payroll.permissions import _require_admin_or_manager, _require_tenant_id
from app.api.payroll.responses import success_response
from app.api.payroll.services.dashboard_service import DashboardService
from app.schemas.auth import APIResponse
from app.schemas.payroll_dashboard import PayrollDashboardResponse

router = APIRouter()


@router.get("/dashboard", response_model=APIResponse[PayrollDashboardResponse], summary="Get main payroll dashboard data")
@router.head("/dashboard")
async def get_payroll_dashboard(
    month: Optional[int] = Query(None, ge=1, le=12),
    year: Optional[int] = Query(None, ge=2000, le=2100),
    cycle_id: Optional[uuid.UUID] = Query(None),
    period_id: Optional[uuid.UUID] = Query(None, alias="periodId"),
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[PayrollDashboardResponse]:
    _require_admin_or_manager(claims)
    company_id = _require_tenant_id(claims, allow_super_admin_global=True)
    target_cycle_id = cycle_id or period_id
    service = DashboardService(db)
    dashboard = await service.get_full_dashboard(
        company_id=company_id,
        cycle_id=target_cycle_id,
        month=month,
        year=year,
    )
    return success_response(dashboard, "Dashboard metrics retrieved.")
