"""Developer API keys, signed webhook subscriptions, retries, and SSO setup."""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v2.enterprise_dependencies import Claims, Session, company_id, ok, require_admin, translate, user_id
from app.db.database import get_db_session
from app.models.employee import Employee
from app.services.sso_service import SSOService
from app.services.webhook_dispatcher_service import WebhookDispatcherService as DeveloperPlatformService

router = APIRouter(prefix="/developer", tags=["Developer Platform v2"])


class APIKeyRequest(BaseModel):
    name: str
    scopes: list[str]
    expires_at: datetime | None = None


class SubscriptionRequest(BaseModel):
    name: str
    target_url: str
    events: list[str]


class SSOProviderRequest(BaseModel):
    provider_type: str
    allowed_domains: list[str]
    client_id: str | None = None
    client_secret: str | None = None
    issuer: str | None = None
    authorization_endpoint: str | None = None
    token_endpoint: str | None = None
    jwks_uri: str | None = None
    saml_sso_url: str | None = None
    sp_entity_id: str | None = None
    x509_certificate: str | None = None


@router.post("/api-keys", status_code=201)
async def create_api_key(body: APIKeyRequest, claims: Claims, db: Session):
    require_admin(claims)
    try:
        key, raw = await DeveloperPlatformService(db).create_api_key(company_id=company_id(claims), created_by=user_id(claims), **body.model_dump())
        return ok({"id": str(key.id), "prefix": key.prefix, "scopes": key.scopes, "api_key": raw}, "API key created; copy it now—it will not be shown again")
    except ValueError as exc:
        translate(exc)


@router.get("/api-keys")
async def list_api_keys(claims: Claims, db: Session):
    require_admin(claims)
    keys = await DeveloperPlatformService(db).list_api_keys(company_id=company_id(claims))
    return ok([{"id": str(key.id), "name": key.name, "prefix": key.prefix, "scopes": key.scopes, "is_active": key.is_active, "last_used_at": key.last_used_at} for key in keys])


@router.delete("/api-keys/{key_id}")
async def revoke_api_key(key_id: uuid.UUID, claims: Claims, db: Session):
    require_admin(claims)
    try:
        key = await DeveloperPlatformService(db).revoke_api_key(key_id, company_id=company_id(claims))
        return ok({"id": str(key.id), "is_active": key.is_active}, "API key revoked")
    except LookupError as exc:
        translate(exc)


@router.post("/webhook-subscriptions", status_code=201)
async def create_webhook_subscription(body: SubscriptionRequest, claims: Claims, db: Session):
    require_admin(claims)
    try:
        sub, secret = await DeveloperPlatformService(db).create_subscription(
            company_id=company_id(claims), description=body.name, target_url=body.target_url,
            events=body.events, created_by=user_id(claims),
        )
        return ok({"id": str(sub.id), "events": sub.events, "target_url": sub.target_url, "secret": secret}, "Webhook subscription created; copy the signing secret now")
    except ValueError as exc:
        translate(exc)


@router.get("/webhook-subscriptions")
async def list_webhook_subscriptions(claims: Claims, db: Session):
    require_admin(claims)
    rows = await DeveloperPlatformService(db).list_subscriptions(company_id=company_id(claims))
    return ok([{"id": str(row.id), "name": row.description, "target_url": row.target_url, "events": row.events, "is_active": row.is_active} for row in rows])


@router.delete("/webhook-subscriptions/{subscription_id}")
async def delete_webhook_subscription(subscription_id: uuid.UUID, claims: Claims, db: Session):
    require_admin(claims)
    try:
        row = await DeveloperPlatformService(db).deactivate_subscription(subscription_id, company_id=company_id(claims))
        return ok({"id": str(row.id), "is_active": row.is_active})
    except LookupError as exc:
        translate(exc)


@router.post("/deliveries/{delivery_id}/retry")
async def retry_webhook_delivery(delivery_id: uuid.UUID, claims: Claims, db: Session):
    require_admin(claims)
    try:
        delivery = await DeveloperPlatformService(db).retry_delivery(delivery_id, company_id=company_id(claims))
        return ok({"id": str(delivery.id), "status": delivery.status, "attempts": delivery.attempt_count})
    except (ValueError, LookupError) as exc:
        translate(exc)


@router.get("/api/employees")
async def developer_employee_feed(
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    db: AsyncSession = Depends(get_db_session),
):
    """Example tenant-scoped API-key endpoint for external employee integrations."""
    try:
        key = await DeveloperPlatformService(db).authenticate_api_key(x_api_key, "employee:read")
        rows = (await db.execute(select(Employee).where(
            Employee.company_id == key.company_id, Employee.is_deleted.is_(False),
        ).order_by(Employee.created_at).limit(500))).scalars().all()
        return ok([{"id": str(row.id), "employee_id": row.employee_id, "designation": row.designation, "department": row.department} for row in rows])
    except PermissionError as exc:
        translate(exc)


@router.post("/identity-providers", status_code=201)
async def configure_identity_provider(body: SSOProviderRequest, claims: Claims, db: Session):
    require_admin(claims)
    try:
        provider = await SSOService(db).configure_provider(company_id=company_id(claims), **body.model_dump())
        return ok({"id": str(provider.id), "provider_type": provider.provider_type, "issuer": provider.issuer, "allowed_domains": provider.allowed_domains, "is_active": provider.is_active})
    except ValueError as exc:
        translate(exc)
