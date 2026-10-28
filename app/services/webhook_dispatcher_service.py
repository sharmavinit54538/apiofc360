"""Scoped API keys and reliable HMAC-signed tenant webhook delivery."""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import secrets
import socket
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.webhooks import TenantAPIKey, WebhookDelivery, WebhookDeliveryAttempt, WebhookSubscription

SUPPORTED_EVENTS = {"employee.created", "employee.updated", "leave.approved", "payroll.completed", "candidate.moved"}
Transport = Callable[[str, bytes, dict[str, str]], Awaitable[tuple[int, str]]]


def _now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


async def _http_transport(url: str, content: bytes, headers: dict[str, str]) -> tuple[int, str]:
    async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
        response = await client.post(url, content=content, headers=headers)
        return response.status_code, response.text[:1000]


class WebhookDispatcherService:
    def __init__(self, session: AsyncSession, transport: Transport | None = None) -> None:
        self.session = session
        self.transport = transport or _http_transport

    async def create_api_key(
        self, *, company_id: uuid.UUID, name: str, scopes: list[str],
        created_by: uuid.UUID | None = None, expires_at: datetime | None = None,
    ) -> tuple[TenantAPIKey, str]:
        normalized = sorted({scope.strip() for scope in scopes if scope.strip()})
        if not normalized:
            raise ValueError("At least one API key scope is required.")
        prefix = secrets.token_hex(4)
        raw_key = f"ofc_{prefix}_{secrets.token_urlsafe(32)}"
        key = TenantAPIKey(
            id=uuid.uuid4(), company_id=company_id, name=name.strip(), prefix=prefix,
            key_hash=_hash(raw_key), scopes=normalized, created_by=created_by, expires_at=expires_at,
        )
        self.session.add(key)
        await self.session.commit()
        return key, raw_key

    async def authenticate_api_key(self, raw_key: str | None, required_scope: str) -> TenantAPIKey:
        if not raw_key:
            raise PermissionError("X-API-Key is required.")
        key = (await self.session.execute(select(TenantAPIKey).where(
            TenantAPIKey.key_hash == _hash(raw_key.strip()),
        ))).scalar_one_or_none()
        now = _now()
        if (
            key is None or not key.is_active or key.revoked_at is not None
            or (key.expires_at and _as_utc(key.expires_at) <= now)
            or ("*" not in key.scopes and required_scope not in key.scopes)
        ):
            raise PermissionError("Invalid, expired, revoked, or insufficiently scoped API key.")
        key.last_used_at = now
        await self.session.commit()
        return key

    async def revoke_api_key(self, key_id: uuid.UUID, *, company_id: uuid.UUID) -> TenantAPIKey:
        key = (await self.session.execute(select(TenantAPIKey).where(
            TenantAPIKey.id == key_id, TenantAPIKey.company_id == company_id,
        ))).scalar_one_or_none()
        if key is None:
            raise LookupError("Tenant API key not found.")
        key.is_active = False
        key.revoked_at = _now()
        await self.session.commit()
        return key

    async def list_api_keys(self, *, company_id: uuid.UUID) -> list[TenantAPIKey]:
        return (await self.session.execute(select(TenantAPIKey).where(
            TenantAPIKey.company_id == company_id,
        ).order_by(TenantAPIKey.created_at.desc()))).scalars().all()

    @staticmethod
    def validate_target_url(url: str) -> str:
        parsed = urlparse(url.strip())
        if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Webhook target must be an HTTP(S) URL without embedded credentials.")
        if settings.is_production and parsed.scheme != "https":
            raise ValueError("Production webhook targets must use HTTPS.")
        host = parsed.hostname.lower()
        if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
            raise ValueError("Webhook target host is not allowed.")
        try:
            addresses = [ipaddress.ip_address(host)]
        except ValueError:
            if not settings.is_production:
                addresses = []
            else:
                try:
                    addresses = [ipaddress.ip_address(item[4][0]) for item in socket.getaddrinfo(host, parsed.port or 443)]
                except (socket.gaierror, ValueError) as exc:
                    raise ValueError("Webhook target host cannot be resolved safely.") from exc
        if any(address.is_private or address.is_loopback or address.is_link_local or address.is_reserved or address.is_multicast or address.is_unspecified for address in addresses):
            raise ValueError("Webhook target cannot resolve to a private or local address.")
        return url.strip()

    async def create_subscription(
        self, *, company_id: uuid.UUID, target_url: str, events: list[str],
        created_by: uuid.UUID | None = None, description: str | None = None,
    ) -> tuple[WebhookSubscription, str]:
        normalized = sorted({event.strip() for event in events})
        if not normalized or any(event != "*" and event not in SUPPORTED_EVENTS for event in normalized):
            raise ValueError("Webhook subscription contains an unsupported event.")
        secret = f"whsec_{secrets.token_urlsafe(32)}"
        subscription = WebhookSubscription(
            id=uuid.uuid4(), company_id=company_id, target_url=self.validate_target_url(target_url),
            secret_encrypted=secret, events=normalized, created_by=created_by, description=description,
        )
        self.session.add(subscription)
        await self.session.commit()
        return subscription, secret

    async def list_subscriptions(self, *, company_id: uuid.UUID) -> list[WebhookSubscription]:
        return (await self.session.execute(select(WebhookSubscription).where(
            WebhookSubscription.company_id == company_id,
        ).order_by(WebhookSubscription.created_at.desc()))).scalars().all()

    async def deactivate_subscription(self, subscription_id: uuid.UUID, *, company_id: uuid.UUID) -> WebhookSubscription:
        subscription = (await self.session.execute(select(WebhookSubscription).where(
            WebhookSubscription.id == subscription_id, WebhookSubscription.company_id == company_id,
        ))).scalar_one_or_none()
        if subscription is None:
            raise LookupError("Webhook subscription not found.")
        subscription.is_active = False
        await self.session.commit()
        return subscription

    async def publish(
        self, *, company_id: uuid.UUID, event_type: str, data: dict,
        event_id: str | None = None,
    ) -> list[WebhookDelivery]:
        if event_type not in SUPPORTED_EVENTS:
            raise ValueError("Unsupported webhook event type.")
        event_id = event_id or str(uuid.uuid4())
        payload = {
            "id": event_id, "type": event_type, "company_id": str(company_id),
            "created_at": _now().isoformat(), "data": data,
        }
        json.dumps(payload)  # Validate serializability before creating queue rows.
        subscriptions = (await self.session.execute(select(WebhookSubscription).where(
            WebhookSubscription.company_id == company_id, WebhookSubscription.is_active.is_(True),
        ))).scalars().all()
        deliveries = []
        for subscription in subscriptions:
            if event_type not in subscription.events and "*" not in subscription.events:
                continue
            existing = (await self.session.execute(select(WebhookDelivery).where(
                WebhookDelivery.subscription_id == subscription.id, WebhookDelivery.event_id == event_id,
            ))).scalar_one_or_none()
            if existing:
                deliveries.append(existing)
                continue
            delivery = WebhookDelivery(
                id=uuid.uuid4(), company_id=company_id, subscription_id=subscription.id,
                event_id=event_id, event_type=event_type, payload_json=payload,
                next_attempt_at=_now(),
            )
            self.session.add(delivery)
            deliveries.append(delivery)
        await self.session.commit()
        return deliveries

    @staticmethod
    def signature(secret: str, body: bytes, timestamp: int) -> str:
        digest = hmac.new(secret.encode(), str(timestamp).encode() + b"." + body, hashlib.sha256).hexdigest()
        return f"t={timestamp},v1={digest}"

    async def deliver(self, delivery_id: uuid.UUID, *, company_id: uuid.UUID | None = None) -> WebhookDelivery:
        stmt = select(WebhookDelivery).options(selectinload(WebhookDelivery.subscription)).where(WebhookDelivery.id == delivery_id)
        if company_id is not None:
            stmt = stmt.where(WebhookDelivery.company_id == company_id)
        delivery = (await self.session.execute(stmt)).scalar_one_or_none()
        if delivery is None:
            raise LookupError("Webhook delivery not found.")
        if delivery.status == "DELIVERED":
            return delivery
        body = json.dumps(delivery.payload_json, separators=(",", ":"), sort_keys=True).encode()
        timestamp = int(time.time())
        signature = self.signature(delivery.subscription.secret_encrypted, body, timestamp)
        headers = {
            "Content-Type": "application/json", "User-Agent": "OFC360-Webhooks/1.0",
            "X-OFC360-Event": delivery.event_type, "X-OFC360-Delivery": str(delivery.id),
            "X-OFC360-Signature": signature,
        }
        started = time.monotonic()
        response_code, response_body, error = None, None, None
        try:
            response_code, response_body = await self.transport(delivery.subscription.target_url, body, headers)
            if not 200 <= response_code < 300:
                error = f"Receiver returned HTTP {response_code}."
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"[:1000]
        latency = max(0, round((time.monotonic() - started) * 1000))
        delivery.attempt_count += 1
        delivery.last_attempt_at = _now()
        delivery.response_code = response_code
        delivery.response_body = (response_body or "")[:1000] or None
        delivery.last_error = error
        if error is None:
            delivery.status = "DELIVERED"
            delivery.completed_at = delivery.last_attempt_at
            delivery.next_attempt_at = delivery.last_attempt_at
        elif delivery.attempt_count >= delivery.max_attempts:
            delivery.status = "DEAD"
            delivery.completed_at = delivery.last_attempt_at
            delivery.next_attempt_at = delivery.last_attempt_at
        else:
            delivery.status = "RETRY"
            delivery.next_attempt_at = delivery.last_attempt_at + timedelta(seconds=60 * (2 ** (delivery.attempt_count - 1)))
        self.session.add(WebhookDeliveryAttempt(
            id=uuid.uuid4(), company_id=delivery.company_id, delivery_id=delivery.id,
            attempt_number=delivery.attempt_count, request_timestamp=delivery.last_attempt_at,
            signature=signature, response_code=response_code, response_body=delivery.response_body,
            error_message=error, latency_ms=latency,
        ))
        await self.session.commit()
        return delivery

    async def retry_delivery(self, delivery_id: uuid.UUID, *, company_id: uuid.UUID) -> WebhookDelivery:
        delivery = (await self.session.execute(select(WebhookDelivery).where(
            WebhookDelivery.id == delivery_id, WebhookDelivery.company_id == company_id,
        ))).scalar_one_or_none()
        if delivery is None:
            raise LookupError("Webhook delivery not found.")
        if delivery.status == "DELIVERED":
            raise ValueError("A delivered webhook does not require a retry.")
        delivery.status = "PENDING"
        delivery.completed_at = None
        delivery.next_attempt_at = _now()
        delivery.max_attempts = max(delivery.max_attempts, delivery.attempt_count + 1)
        await self.session.commit()
        return await self.deliver(delivery.id, company_id=company_id)

    async def deliver_due(self, *, company_id: uuid.UUID | None = None, now: datetime | None = None, limit: int = 100) -> list[WebhookDelivery]:
        now = now or _now()
        stmt = select(WebhookDelivery).where(
            WebhookDelivery.status.in_(["PENDING", "RETRY"]),
            WebhookDelivery.next_attempt_at <= now,
        ).order_by(WebhookDelivery.next_attempt_at).limit(max(1, min(limit, 500)))
        if company_id is not None:
            stmt = stmt.where(WebhookDelivery.company_id == company_id)
        rows = (await self.session.execute(stmt)).scalars().all()
        return [await self.deliver(row.id, company_id=row.company_id) for row in rows]
