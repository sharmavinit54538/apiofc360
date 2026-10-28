"""Tenant-scoped background verification workflows and vendor adapter."""
from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.bgv import BGVCase, BGVCheck, BGVVendor, BGVWebhookEvent
from app.models.employee import Employee
from app.models.recruitment import Application, Candidate

CHECK_TYPES = {"IDENTITY", "CRIMINAL", "EDUCATION", "EMPLOYMENT"}
FINAL_CHECK_STATUSES = {"CLEAR", "VERIFIED", "DISCREPANCY", "FAILED"}


def _now() -> datetime:
    return datetime.now(UTC)


def make_consent_token(case: BGVCase) -> str:
    from itsdangerous import URLSafeTimedSerializer
    from app.core.config import settings
    serializer = URLSafeTimedSerializer(settings.SECRET_KEY.get_secret_value(), salt="bgv-candidate-consent-v1")
    return serializer.dumps({"case_id": str(case.id), "company_id": str(case.company_id)})


def parse_consent_token(token: str) -> tuple[uuid.UUID, uuid.UUID]:
    from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
    from app.core.config import settings
    serializer = URLSafeTimedSerializer(settings.SECRET_KEY.get_secret_value(), salt="bgv-candidate-consent-v1")
    try:
        data = serializer.loads(token, max_age=7 * 24 * 3600)
        return uuid.UUID(data["case_id"]), uuid.UUID(data["company_id"])
    except (BadSignature, SignatureExpired, ValueError, KeyError, TypeError) as exc:
        raise PermissionError("BGV consent link is invalid or expired.") from exc


class BGVAdapter(Protocol):
    async def submit(self, vendor: BGVVendor, case: BGVCase, checks: list[BGVCheck]) -> dict[str, Any]: ...


class HttpBGVAdapter:
    """Generic vendor REST adapter; vendor-specific field mapping stays at this boundary."""

    async def submit(self, vendor: BGVVendor, case: BGVCase, checks: list[BGVCheck]) -> dict[str, Any]:
        if not vendor.api_base_url.lower().startswith("https://"):
            raise ValueError("BGV vendor API must use HTTPS.")
        headers = {"Content-Type": "application/json"}
        if vendor.api_token:
            headers["Authorization"] = f"Bearer {vendor.api_token}"
        payload = {
            "reference": str(case.id),
            "candidate_id": str(case.candidate_id) if case.candidate_id else None,
            "application_id": str(case.application_id) if case.application_id else None,
            "employee_id": str(case.employee_id) if case.employee_id else None,
            "consent": {"captured_at": case.consent_at.isoformat() if case.consent_at else None, "proof": case.consent_text_hash},
            "checks": [{"type": check.check_type, "reference": str(check.id)} for check in checks],
        }
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
            response = await client.post(f"{vendor.api_base_url.rstrip('/')}/v1/verifications", json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
        if not isinstance(data, dict):
            raise ValueError("BGV vendor returned an invalid response.")
        return data


class BGVService:
    def __init__(self, session: AsyncSession, adapter: BGVAdapter | None = None) -> None:
        self.session = session
        self.adapter = adapter or HttpBGVAdapter()

    async def _vendor(self, vendor_id: uuid.UUID, company_id: uuid.UUID) -> BGVVendor:
        vendor = (await self.session.execute(select(BGVVendor).where(
            BGVVendor.id == vendor_id, BGVVendor.company_id == company_id,
        ))).scalar_one_or_none()
        if vendor is None or not vendor.is_active:
            raise LookupError("BGV vendor not found or inactive.")
        return vendor

    async def _case(self, case_id: uuid.UUID, company_id: uuid.UUID) -> BGVCase:
        case = (await self.session.execute(select(BGVCase).options(selectinload(BGVCase.checks)).where(
            BGVCase.id == case_id, BGVCase.company_id == company_id,
        ))).scalar_one_or_none()
        if case is None:
            raise LookupError("BGV case not found.")
        return case

    async def create_vendor(
        self, *, company_id: uuid.UUID, name: str, api_base_url: str,
        webhook_secret: str, api_token: str | None = None,
    ) -> BGVVendor:
        if len(webhook_secret) < 16:
            raise ValueError("BGV webhook secret must contain at least 16 characters.")
        vendor = BGVVendor(
            id=uuid.uuid4(), company_id=company_id, name=name.strip().upper(),
            api_base_url=api_base_url.strip(), api_token=api_token, webhook_secret=webhook_secret,
        )
        self.session.add(vendor)
        await self.session.commit()
        return vendor

    async def create_case(
        self, *, company_id: uuid.UUID, vendor_id: uuid.UUID, actor_id: uuid.UUID,
        candidate_id: uuid.UUID | None = None, application_id: uuid.UUID | None = None,
        employee_id: uuid.UUID | None = None, check_types: list[str] | None = None,
    ) -> BGVCase:
        await self._vendor(vendor_id, company_id)
        anchors = [value for value in (candidate_id, application_id, employee_id) if value is not None]
        if len(anchors) != 1:
            raise ValueError("Exactly one candidate, application, or employee anchor is required.")
        if candidate_id:
            anchor = await self.session.get(Candidate, candidate_id)
            if anchor is None:
                raise LookupError("Candidate not found.")
            if application_id is None:
                application = (await self.session.execute(select(Application).where(
                    Application.candidate_id == candidate_id, Application.company_id == company_id,
                ))).scalar_one_or_none()
                if application is None:
                    raise ValueError("Candidate has no application in this tenant.")
        if application_id:
            application = (await self.session.execute(select(Application).where(
                Application.id == application_id, Application.company_id == company_id,
            ))).scalar_one_or_none()
            if application is None:
                raise LookupError("Application not found in this tenant.")
            if candidate_id and application.candidate_id != candidate_id:
                raise ValueError("Application and candidate do not match.")
        if employee_id:
            employee = (await self.session.execute(select(Employee).where(
                Employee.id == employee_id, Employee.company_id == company_id, Employee.is_deleted.is_(False),
            ))).scalar_one_or_none()
            if employee is None:
                raise LookupError("Employee not found in this tenant.")
        normalized = list(dict.fromkeys((value.upper() for value in (check_types or sorted(CHECK_TYPES)))))
        if not normalized or any(value not in CHECK_TYPES for value in normalized):
            raise ValueError("BGV checks must be IDENTITY, CRIMINAL, EDUCATION, or EMPLOYMENT.")
        case = BGVCase(
            id=uuid.uuid4(), company_id=company_id, vendor_id=vendor_id,
            candidate_id=candidate_id, application_id=application_id, employee_id=employee_id,
            created_by=actor_id, status="PENDING_CONSENT",
        )
        self.session.add(case)
        await self.session.flush()
        for check_type in normalized:
            self.session.add(BGVCheck(
                id=uuid.uuid4(), company_id=company_id, case_id=case.id, check_type=check_type,
            ))
        await self.session.commit()
        return await self._case(case.id, company_id)

    async def capture_consent(
        self, case_id: uuid.UUID, *, company_id: uuid.UUID, consent_text: str,
        accepted: bool, ip_address: str | None, user_agent: str | None,
        consent_reference: str | None = None,
    ) -> BGVCase:
        case = await self._case(case_id, company_id)
        if not accepted or len(consent_text.strip()) < 20:
            raise ValueError("Explicit acceptance of the complete consent text is required.")
        if case.status != "PENDING_CONSENT":
            raise ValueError("Consent has already been captured for this case.")
        case.consent_at = _now()
        case.consent_ip_address = ip_address
        case.consent_user_agent = (user_agent or "")[:500] or None
        case.consent_text_hash = hashlib.sha256(consent_text.strip().encode()).hexdigest()
        case.consent_reference = consent_reference
        case.status = "CONSENT_CAPTURED"
        await self.session.commit()
        return case

    async def submit_case(self, case_id: uuid.UUID, *, company_id: uuid.UUID) -> BGVCase:
        case = await self._case(case_id, company_id)
        if case.consent_at is None:
            raise ValueError("Digital candidate consent is required before vendor submission.")
        if case.status not in {"CONSENT_CAPTURED", "SUBMISSION_FAILED"}:
            raise ValueError("BGV case is not awaiting submission.")
        vendor = await self._vendor(case.vendor_id, company_id)
        try:
            response = await self.adapter.submit(vendor, case, list(case.checks))
            case.vendor_reference = str(response.get("reference") or response.get("id") or case.id)
            for check in case.checks:
                references = response.get("checks", {})
                if isinstance(references, dict):
                    check.vendor_reference = references.get(check.check_type)
                check.status = "IN_PROGRESS"
            case.status = "IN_PROGRESS"
            case.submitted_at = _now()
        except Exception:
            case.status = "SUBMISSION_FAILED"
            await self.session.commit()
            raise
        await self.session.commit()
        return case

    @staticmethod
    def verify_signature(vendor: BGVVendor, raw_body: bytes, signature: str | None) -> None:
        expected = "sha256=" + hmac.new(vendor.webhook_secret.encode(), raw_body, hashlib.sha256).hexdigest()
        if not signature or not hmac.compare_digest(expected, signature.strip()):
            raise PermissionError("Invalid BGV webhook signature.")

    async def handle_webhook(
        self, *, company_id: uuid.UUID, vendor_id: uuid.UUID,
        raw_body: bytes, signature: str | None,
    ) -> dict[str, Any]:
        vendor = await self._vendor(vendor_id, company_id)
        self.verify_signature(vendor, raw_body, signature)
        try:
            payload = json.loads(raw_body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError("Invalid BGV webhook JSON.") from exc
        if not isinstance(payload, dict):
            raise ValueError("BGV webhook payload must be an object.")
        event_id = str(payload.get("event_id") or payload.get("id") or "").strip()
        if not event_id:
            raise ValueError("BGV webhook event_id is required.")
        payload_hash = hashlib.sha256(raw_body).hexdigest()
        existing = (await self.session.execute(select(BGVWebhookEvent).where(
            BGVWebhookEvent.company_id == company_id, BGVWebhookEvent.vendor_id == vendor_id,
            BGVWebhookEvent.external_event_id == event_id,
        ))).scalar_one_or_none()
        if existing:
            if existing.payload_hash != payload_hash:
                raise ValueError("BGV webhook event ID was reused for a different payload.")
            return {"duplicate": True, "event_id": event_id}
        case_reference = str(payload.get("case_reference") or payload.get("reference") or "")
        case = (await self.session.execute(select(BGVCase).options(selectinload(BGVCase.checks)).where(
            BGVCase.company_id == company_id, BGVCase.vendor_id == vendor_id,
            BGVCase.vendor_reference == case_reference,
        ))).scalar_one_or_none()
        if case is None:
            raise LookupError("BGV case reference not found.")
        check_type = str(payload.get("check_type") or "").upper()
        check = next((item for item in case.checks if item.check_type == check_type), None)
        if check is None:
            raise LookupError("BGV check type not found for this case.")
        new_status = str(payload.get("status") or "").upper()
        if new_status not in FINAL_CHECK_STATUSES | {"IN_PROGRESS", "PENDING"}:
            raise ValueError("Unsupported BGV check status.")
        check.status = new_status
        check.vendor_reference = payload.get("check_reference") or check.vendor_reference
        check.result_json = payload.get("result") if isinstance(payload.get("result"), dict) else {}
        check.discrepancy_flag = new_status == "DISCREPANCY" or bool(payload.get("discrepancy"))
        if check.discrepancy_flag:
            check.discrepancy_details = str(payload.get("discrepancy_details") or "Vendor reported a discrepancy.")
            check.resolution_status = "PENDING"
        self.session.add(BGVWebhookEvent(
            id=uuid.uuid4(), company_id=company_id, vendor_id=vendor_id,
            external_event_id=event_id, payload_hash=payload_hash, received_at=_now(),
        ))
        self._refresh_case_status(case)
        await self.session.commit()
        return {"duplicate": False, "event_id": event_id, "case_id": str(case.id), "case_status": case.status}

    @staticmethod
    def _refresh_case_status(case: BGVCase) -> None:
        if case.checks and all(check.status in FINAL_CHECK_STATUSES for check in case.checks):
            unresolved = any(check.discrepancy_flag and check.resolution_status != "RESOLVED" for check in case.checks)
            case.status = "ACTION_REQUIRED" if unresolved else (
                "COMPLETED_WITH_DISCREPANCY" if any(check.discrepancy_flag for check in case.checks) else "COMPLETED"
            )
            if not unresolved:
                case.completed_at = case.completed_at or _now()
        elif any(check.status == "IN_PROGRESS" for check in case.checks):
            case.status = "IN_PROGRESS"

    async def resolve_discrepancy(
        self, check_id: uuid.UUID, *, company_id: uuid.UUID,
        actor_id: uuid.UUID, resolution: str, notes: str,
    ) -> BGVCheck:
        check = (await self.session.execute(select(BGVCheck).options(selectinload(BGVCheck.case).selectinload(BGVCase.checks)).where(
            BGVCheck.id == check_id, BGVCheck.company_id == company_id,
        ))).scalar_one_or_none()
        if check is None:
            raise LookupError("BGV check not found.")
        if not check.discrepancy_flag:
            raise ValueError("This check has no discrepancy to resolve.")
        resolution = resolution.upper()
        if resolution not in {"RESOLVED", "CONFIRMED"}:
            raise ValueError("Resolution must be RESOLVED or CONFIRMED.")
        if len(notes.strip()) < 5:
            raise ValueError("Resolution notes are required.")
        check.resolution_status = "RESOLVED" if resolution == "RESOLVED" else "CONFIRMED"
        check.resolution_notes = notes.strip()
        check.resolved_by = actor_id
        check.resolved_at = _now()
        if resolution == "CONFIRMED":
            # A confirmed discrepancy remains part of the final audit outcome.
            check.resolution_status = "RESOLVED"
        self._refresh_case_status(check.case)
        await self.session.commit()
        return check
