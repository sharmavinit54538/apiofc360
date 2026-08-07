"""Route handlers for high-level payroll dashboard metrics."""
from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Query

from app.api.payroll.dependencies import DB, Claims
from app.api.payroll.permissions import _require_admin_or_manager
from app.api.payroll.responses import success_response
from app.api.payroll.services.dashboard_service import DashboardService
from app.schemas.auth import APIResponse

router = APIRouter()


@router.get("/dashboard", response_model=APIResponse[dict], summary="Get main payroll dashboard data")
async def get_payroll_dashboard(
    month: Optional[int] = Query(None),
    year: Optional[int] = Query(None),
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    service = DashboardService(db)
    metrics = await service.get_hero_card_metrics(month, year)
    return success_response({"summary": metrics}, "Dashboard metrics retrieved.")
