"""Admin-only integration marketplace APIs; secret values are write-only."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.v2.enterprise_dependencies import Claims, Session, company_id, ok, require_admin
from app.services.marketplace_service import MarketplaceService

router = APIRouter(prefix="/marketplace", tags=["Integration Marketplace v2"])


class IntegrationConfigureRequest(BaseModel):
    credentials: dict[str, Any] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool | None = None


class IntegrationSyncRequest(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)
    trigger_type: str = Field("MANUAL", pattern=r"^(MANUAL|SCHEDULED|WEBHOOK)$")


def _translate(exc: Exception) -> None:
    if isinstance(exc, LookupError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, PermissionError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/catalog")
async def marketplace_catalog(claims: Claims, db: Session):
    require_admin(claims)
    return ok(await MarketplaceService(db).catalog(company_id(claims)), "Marketplace catalog retrieved.")


@router.get("/integrations")
async def list_marketplace_integrations(claims: Claims, db: Session):
    require_admin(claims)
    return ok(await MarketplaceService(db).list_integrations(company_id(claims)), "Tenant integrations retrieved.")


@router.put("/integrations/{connector_code}")
async def configure_marketplace_integration(connector_code: str, body: IntegrationConfigureRequest, claims: Claims, db: Session):
    require_admin(claims)
    try:
        data = await MarketplaceService(db).configure(
            company_id=company_id(claims), connector_code=connector_code, **body.model_dump(),
        )
    except (LookupError, ValueError) as exc:
        _translate(exc)
    return ok(data, "Integration configuration saved; credentials are write-only.")


@router.post("/integrations/{connector_code}/enable")
async def enable_marketplace_integration(connector_code: str, claims: Claims, db: Session):
    require_admin(claims)
    try:
        data = await MarketplaceService(db).set_enabled(company_id=company_id(claims), connector_code=connector_code, enabled=True)
    except (LookupError, ValueError) as exc:
        _translate(exc)
    return ok(data, "Integration enabled.")


@router.post("/integrations/{connector_code}/disable")
async def disable_marketplace_integration(connector_code: str, claims: Claims, db: Session):
    require_admin(claims)
    try:
        data = await MarketplaceService(db).set_enabled(company_id=company_id(claims), connector_code=connector_code, enabled=False)
    except (LookupError, ValueError) as exc:
        _translate(exc)
    return ok(data, "Integration disabled.")


@router.post("/integrations/{connector_code}/sync")
async def sync_marketplace_integration(connector_code: str, body: IntegrationSyncRequest, claims: Claims, db: Session):
    require_admin(claims)
    try:
        data = await MarketplaceService(db).sync(
            company_id=company_id(claims), connector_code=connector_code,
            payload=body.payload, trigger_type=body.trigger_type,
        )
    except (LookupError, ValueError, PermissionError) as exc:
        _translate(exc)
    return ok(data, "Sync accepted and health logged; external acknowledgement is reported separately.")


@router.get("/integrations/{connector_code}/sync-logs")
async def marketplace_sync_logs(connector_code: str, claims: Claims, db: Session, limit: int = Query(50, ge=1, le=200)):
    require_admin(claims)
    try:
        data = await MarketplaceService(db).sync_logs(company_id=company_id(claims), connector_code=connector_code, limit=limit)
    except LookupError as exc:
        _translate(exc)
    return ok(data, "Integration sync health retrieved.")
