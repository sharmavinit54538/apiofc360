"""Route handlers for statutory compliance."""
from __future__ import annotations

from fastapi import APIRouter

from app.api.payroll.dependencies import DB, Claims
from app.api.payroll.permissions import _require_admin_or_manager
from app.api.payroll.responses import success_response
from app.api.payroll.services.compliance_service import ComplianceService
from app.schemas.auth import APIResponse

router = APIRouter()


@router.get("/compliance/config", response_model=APIResponse[dict], summary="Get statutory compliance configuration")
@router.head("/compliance/config")
async def get_statutory_config(
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    service = ComplianceService(db)
    config = await service.get_statutory_config()
    return success_response(config, "Statutory config retrieved.")


@router.get("/compliance/dashboard", response_model=APIResponse[dict], summary="Get statutory compliance dashboard")
@router.get("/compliance", response_model=APIResponse[dict], summary="Get statutory compliance dashboard")
@router.head("/compliance/dashboard")
@router.head("/compliance")
async def get_compliance_dashboard(
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    service = ComplianceService(db)
    dashboard_data = await service.get_compliance_dashboard()
    return success_response(dashboard_data, "Statutory compliance dashboard retrieved.")
