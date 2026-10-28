"""Integration marketplace catalog, credential vault and sync health services."""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.marketplace import IntegrationSyncLog, MarketplaceIntegration


CONNECTOR_CATALOG: dict[str, dict[str, Any]] = {
    "SLACK": {
        "name": "Slack", "category": "COLLABORATION", "sync_mode": "PUSH",
        "description": "HR notifications and employee-assistant messages.",
        "required_credentials": ["bot_token", "signing_secret"],
    },
    "TEAMS": {
        "name": "Microsoft Teams", "category": "COLLABORATION", "sync_mode": "PUSH",
        "description": "Teams notifications and approval messages.",
        "required_credentials": ["tenant_id", "client_id", "client_secret"],
    },
    "BIOMETRIC_PUSH": {
        "name": "Biometric Push", "category": "ATTENDANCE", "sync_mode": "PUSH",
        "description": "Signed attendance-event ingestion from biometric devices.",
        "required_credentials": ["webhook_url", "secret"],
    },
    "RAZORPAYX": {
        "name": "RazorpayX", "category": "BANKING", "sync_mode": "PULL",
        "description": "Payout status and bank-transaction reconciliation input.",
        "required_credentials": ["key_id", "key_secret", "account_number"],
    },
    "TALLY": {
        "name": "Tally", "category": "ACCOUNTING", "sync_mode": "PUSH",
        "description": "Balanced payroll journal-line export adapter.",
        "required_credentials": ["api_url", "auth_token"],
    },
    "ZOHO": {
        "name": "Zoho", "category": "ACCOUNTING", "sync_mode": "PUSH",
        "description": "Zoho Books payroll journal synchronization.",
        "required_credentials": ["client_id", "client_secret", "refresh_token"],
    },
    "GOOGLE_CALENDAR": {
        "name": "Google Calendar", "category": "PRODUCTIVITY", "sync_mode": "PUSH",
        "description": "Interview, leave and HR event calendar synchronization.",
        "required_credentials": ["access_token"],
    },
}

_SECRET_WORDS = ("secret", "token", "password", "credential", "private_key", "api_key", "key_secret")


class MarketplaceService:
    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def _code(connector_code: str) -> str:
        code = connector_code.strip().upper().replace("-", "_").replace(" ", "_")
        if code not in CONNECTOR_CATALOG:
            raise LookupError(f"Unknown marketplace connector '{connector_code}'.")
        return code

    @staticmethod
    def _public_connector(code: str) -> dict[str, Any]:
        connector = CONNECTOR_CATALOG[code]
        return {
            "connector_code": code, "name": connector["name"],
            "category": connector["category"], "sync_mode": connector["sync_mode"],
            "description": connector["description"],
            "required_credential_fields": connector["required_credentials"],
        }

    @staticmethod
    def _public_integration(row: MarketplaceIntegration) -> dict[str, Any]:
        return {
            "id": str(row.id), "company_id": str(row.company_id),
            "connector_code": row.connector_code, "status": row.status,
            "credentials_configured": bool(row.credentials_encrypted),
            "config": row.config_json or {},
            "enabled_at": row.enabled_at, "disabled_at": row.disabled_at,
            "last_sync_at": row.last_sync_at, "last_sync_status": row.last_sync_status,
            "created_at": row.created_at, "updated_at": row.updated_at,
        }

    async def _get(self, company_id: uuid.UUID, code: str) -> MarketplaceIntegration | None:
        return (await self.session.execute(select(MarketplaceIntegration).where(
            MarketplaceIntegration.company_id == company_id,
            MarketplaceIntegration.connector_code == code,
        ))).scalar_one_or_none()

    async def catalog(self, company_id: uuid.UUID) -> list[dict[str, Any]]:
        rows = (await self.session.execute(select(MarketplaceIntegration).where(
            MarketplaceIntegration.company_id == company_id,
        ))).scalars().all()
        by_code = {row.connector_code: row for row in rows}
        result = []
        for code in CONNECTOR_CATALOG:
            item = self._public_connector(code)
            row = by_code.get(code)
            item.update({
                "installed": row is not None,
                "status": row.status if row else "NOT_INSTALLED",
                "credentials_configured": bool(row and row.credentials_encrypted),
                "last_sync_status": row.last_sync_status if row else None,
            })
            result.append(item)
        return result

    async def list_integrations(self, company_id: uuid.UUID) -> list[dict[str, Any]]:
        rows = (await self.session.execute(select(MarketplaceIntegration).where(
            MarketplaceIntegration.company_id == company_id,
        ).order_by(MarketplaceIntegration.connector_code))).scalars().all()
        return [self._public_integration(row) for row in rows]

    @staticmethod
    def _decrypt_credentials(row: MarketplaceIntegration | None) -> dict[str, Any]:
        if row is None or not row.credentials_encrypted:
            return {}
        try:
            value = json.loads(row.credentials_encrypted)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("Stored connector credentials are invalid; reconfigure the integration.") from exc
        if not isinstance(value, dict):
            raise ValueError("Stored connector credentials are invalid; reconfigure the integration.")
        return value

    @staticmethod
    def _validate_config(config: dict[str, Any]) -> None:
        for key in config:
            normalized = key.lower()
            if any(word in normalized for word in _SECRET_WORDS):
                raise ValueError(f"Credential-like field '{key}' must be supplied in credentials, not config.")

    def _validate_credentials(self, code: str, credentials: dict[str, Any], *, complete: bool) -> None:
        if complete:
            missing = [key for key in CONNECTOR_CATALOG[code]["required_credentials"] if not str(credentials.get(key) or "").strip()]
            if missing:
                raise ValueError(f"Missing required credential fields: {', '.join(missing)}.")
        for key, value in credentials.items():
            if not isinstance(key, str) or not key.strip():
                raise ValueError("Credential field names must be non-empty strings.")
            if isinstance(value, (dict, list)):
                # Structured service-account credentials are serialized safely;
                # all other values remain JSON values inside the encrypted blob.
                continue
            if value is not None and not str(value).strip():
                raise ValueError(f"Credential field '{key}' cannot be empty.")

    async def configure(
        self, *, company_id: uuid.UUID, connector_code: str,
        credentials: dict[str, Any] | None = None,
        config: dict[str, Any] | None = None,
        enabled: bool | None = None,
    ) -> dict[str, Any]:
        code = self._code(connector_code)
        config = config or {}
        credentials = credentials or {}
        if not isinstance(config, dict) or not isinstance(credentials, dict):
            raise ValueError("config and credentials must be objects.")
        self._validate_config(config)
        row = await self._get(company_id, code)
        merged = self._decrypt_credentials(row)
        merged.update(credentials)
        self._validate_credentials(code, merged, complete=bool(enabled))
        now = datetime.now(UTC)
        if row is None:
            row = MarketplaceIntegration(
                id=uuid.uuid4(), company_id=company_id, connector_code=code,
                status="DISABLED", config_json={},
            )
            self.session.add(row)
        if credentials:
            row.credentials_encrypted = json.dumps(merged, separators=(",", ":"))
        if config:
            # Non-secret config is replace-by-request, making removals explicit.
            row.config_json = config
        if enabled is True:
            row.status = "ENABLED"
            row.enabled_at = now
            row.disabled_at = None
        elif enabled is False:
            row.status = "DISABLED"
            row.disabled_at = now
        await self.session.commit()
        await self.session.refresh(row)
        return self._public_integration(row)

    async def set_enabled(self, *, company_id: uuid.UUID, connector_code: str, enabled: bool) -> dict[str, Any]:
        code = self._code(connector_code)
        row = await self._get(company_id, code)
        if row is None:
            raise LookupError("Integration is not configured for the current tenant.")
        if enabled:
            self._validate_credentials(code, self._decrypt_credentials(row), complete=True)
        now = datetime.now(UTC)
        row.status = "ENABLED" if enabled else "DISABLED"
        if enabled:
            row.enabled_at = now
            row.disabled_at = None
        else:
            row.disabled_at = now
        await self.session.commit()
        await self.session.refresh(row)
        return self._public_integration(row)

    @staticmethod
    def _validate_sync_payload(code: str, payload: dict[str, Any]) -> tuple[int, int, dict[str, Any]]:
        if not isinstance(payload, dict):
            raise ValueError("Sync payload must be an object.")
        collection_names = {
            "BIOMETRIC_PUSH": "events", "RAZORPAYX": "transactions",
            "TALLY": "journal_entries", "ZOHO": "journal_entries",
        }
        collection = collection_names.get(code, "records")
        records = payload.get(collection, [])
        if not isinstance(records, list):
            raise ValueError(f"{collection} must be a list.")
        if len(records) > 10000:
            raise ValueError("A sync batch cannot exceed 10,000 records.")
        if code == "BIOMETRIC_PUSH":
            if any(not isinstance(record, dict) or not record.get("event_id") or not record.get("employee_id") for record in records):
                raise ValueError("Every biometric event requires event_id and employee_id.")
        elif code == "RAZORPAYX":
            if any(not isinstance(record, dict) or not record.get("transaction_id") or not isinstance(record.get("amount_paise"), int) for record in records):
                raise ValueError("Every bank transaction requires transaction_id and integer amount_paise.")
        elif code in {"TALLY", "ZOHO"}:
            for entry in records:
                if not isinstance(entry, dict) or not isinstance(entry.get("debit_paise"), int) or not isinstance(entry.get("credit_paise"), int):
                    raise ValueError("Every journal entry requires integer debit_paise and credit_paise.")
                if entry["debit_paise"] < 0 or entry["credit_paise"] < 0 or entry["debit_paise"] != entry["credit_paise"]:
                    raise ValueError("Journal entries must be balanced and non-negative.")
        return len(records), len(records), {
            "adapter": code, "payload_collection": collection,
            "external_acknowledgement": False,
            "processing_state": "ACCEPTED_FOR_ADAPTER_PROCESSING" if records else "HEALTH_CHECK_OK",
        }

    async def sync(
        self, *, company_id: uuid.UUID, connector_code: str,
        payload: dict[str, Any], trigger_type: str = "MANUAL",
    ) -> dict[str, Any]:
        code = self._code(connector_code)
        row = await self._get(company_id, code)
        if row is None:
            raise LookupError("Integration is not configured for the current tenant.")
        if row.status != "ENABLED":
            raise PermissionError("Enable the integration before starting a sync.")
        started = datetime.now(UTC)
        try:
            received, accepted, health = self._validate_sync_payload(code, payload)
            status_value = "ACCEPTED"
            error_message = None
            rejected = 0
        except ValueError as exc:
            received = len(payload.get("events", payload.get("records", []))) if isinstance(payload, dict) and isinstance(payload.get("events", payload.get("records", [])), list) else 0
            accepted = 0
            rejected = received
            health = {"adapter": code, "processing_state": "VALIDATION_FAILED"}
            status_value = "FAILED"
            error_message = str(exc)[:500]
        log = IntegrationSyncLog(
            id=uuid.uuid4(), company_id=company_id, integration_id=row.id,
            connector_code=code, status=status_value, trigger_type=trigger_type.upper()[:20],
            records_received=received, records_accepted=accepted, records_rejected=rejected,
            health_json=health, error_message=error_message,
            started_at=started, completed_at=datetime.now(UTC),
        )
        self.session.add(log)
        row.last_sync_at = log.completed_at
        row.last_sync_status = status_value
        await self.session.commit()
        await self.session.refresh(log)
        if error_message:
            raise ValueError(error_message)
        return {
            "sync_log_id": str(log.id), "connector_code": code,
            "status": log.status, "records_received": received,
            "records_accepted": accepted, "records_rejected": rejected,
            "health": health, "started_at": log.started_at, "completed_at": log.completed_at,
        }

    async def sync_logs(self, *, company_id: uuid.UUID, connector_code: str, limit: int = 50) -> list[dict[str, Any]]:
        code = self._code(connector_code)
        rows = (await self.session.execute(select(IntegrationSyncLog).where(
            IntegrationSyncLog.company_id == company_id,
            IntegrationSyncLog.connector_code == code,
        ).order_by(IntegrationSyncLog.created_at.desc()).limit(limit))).scalars().all()
        return [{
            "id": str(row.id), "integration_id": str(row.integration_id),
            "connector_code": row.connector_code, "status": row.status,
            "trigger_type": row.trigger_type, "records_received": row.records_received,
            "records_accepted": row.records_accepted, "records_rejected": row.records_rejected,
            "health": row.health_json, "error_message": row.error_message,
            "started_at": row.started_at, "completed_at": row.completed_at,
        } for row in rows]
