"""Offline-safe mobile attendance and push/document helpers."""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance.services.checkin_service import AttendanceCheckInService
from app.attendance.services.checkout_service import AttendanceCheckOutService
from app.models.employee_document import EmployeeDocument
from app.models.mobile_pwa import MobileIdempotencyRecord, PushSubscription


class MobilePWAService:
    def __init__(self, session: AsyncSession, *, checkin_service=None, checkout_service=None) -> None:
        self.session = session
        self.checkin_service = checkin_service or AttendanceCheckInService(session)
        self.checkout_service = checkout_service or AttendanceCheckOutService(session)

    @staticmethod
    def _request_hash(value: dict[str, Any]) -> str:
        canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _attendance_dict(record: Any, captured_at: str | None = None) -> dict[str, Any]:
        def iso(name: str) -> str | None:
            value = getattr(record, name, None)
            return value.isoformat() if value else None
        return {
            "attendance_id": str(record.id), "date": iso("date"),
            "check_in_time": iso("check_in_time"), "check_out_time": iso("check_out_time"),
            "status": getattr(record, "status", None), "verified": getattr(record, "verified", None),
            "punch_verified_by": getattr(record, "punch_verified_by", None),
            "latitude": getattr(record, "latitude", None), "longitude": getattr(record, "longitude", None),
            "location_accuracy": getattr(record, "location_accuracy", None),
            "liveness_score": getattr(record, "liveness_score", None),
            "face_distance": getattr(record, "face_distance", None),
            "working_hours": getattr(record, "working_hours", None),
            "client_captured_at": captured_at,
        }

    async def mark_attendance(
        self, *, user_id: uuid.UUID, company_id: uuid.UUID, operation: str,
        idempotency_key: str, image_base64: str, latitude: float, longitude: float,
        accuracy: float | None = None, notes: str | None = None,
        device_info: str | None = None, ip_address: str | None = None,
        client_captured_at: str | None = None,
    ) -> dict[str, Any]:
        operation = operation.upper()
        if operation not in {"CHECK_IN", "CHECK_OUT"}:
            raise ValueError("Attendance operation must be CHECK_IN or CHECK_OUT")
        if not (8 <= len(idempotency_key) <= 128):
            raise ValueError("Idempotency-Key must contain 8 to 128 characters")
        payload = {
            "company_id": str(company_id), "user_id": str(user_id), "operation": operation,
            "image_base64": image_base64, "latitude": latitude, "longitude": longitude,
            "accuracy": accuracy, "notes": notes, "device_info": device_info,
            "client_captured_at": client_captured_at,
        }
        request_hash = self._request_hash(payload)
        stmt = select(MobileIdempotencyRecord).where(
            MobileIdempotencyRecord.user_id == user_id,
            MobileIdempotencyRecord.operation == operation,
            MobileIdempotencyRecord.idempotency_key == idempotency_key,
        )
        existing = (await self.session.execute(stmt)).scalar_one_or_none()
        if existing:
            if existing.company_id != company_id or existing.request_hash != request_hash:
                raise HTTPException(status_code=409, detail={"code": "IDEMPOTENCY_KEY_REUSED", "message": "This idempotency key was used for a different request."})
            if existing.status == "COMPLETED" and existing.response_json is not None:
                return {**existing.response_json, "idempotent_replay": True}
            if existing.status == "PROCESSING":
                raise HTTPException(status_code=409, detail={"code": "REQUEST_IN_PROGRESS", "message": "The original request is still being processed; retry shortly."})
            existing.status = "PROCESSING"
            existing.error_code = None
            record = existing
        else:
            record = MobileIdempotencyRecord(
                id=uuid.uuid4(), company_id=company_id, user_id=user_id, operation=operation,
                idempotency_key=idempotency_key, request_hash=request_hash, status="PROCESSING",
            )
            self.session.add(record)
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            existing = (await self.session.execute(stmt)).scalar_one_or_none()
            if existing and existing.status == "COMPLETED" and existing.request_hash == request_hash:
                return {**existing.response_json, "idempotent_replay": True}
            raise HTTPException(status_code=409, detail={"code": "REQUEST_IN_PROGRESS", "message": "A concurrent request is using this idempotency key."}) from exc

        location = {"latitude": latitude, "longitude": longitude, "accuracy": accuracy}
        try:
            if operation == "CHECK_IN":
                attendance = await self.checkin_service.check_in_with_face_base64(
                    user_id=user_id, company_id=company_id, image_base64=image_base64,
                    location=location, notes=notes, device_info=device_info,
                    ip_address=ip_address, idempotency_key=idempotency_key,
                )
            else:
                attendance = await self.checkout_service.check_out_with_face_base64(
                    user_id=user_id, company_id=company_id, image_base64=image_base64,
                    location=location, notes=notes, device_info=device_info, ip_address=ip_address,
                )
            response = self._attendance_dict(attendance, client_captured_at)
            response["idempotent_replay"] = False
            # The underlying attendance service commits.  Re-read the ledger row
            # so a failed biometric/geofence attempt cannot poison the session.
            ledger = await self.session.get(MobileIdempotencyRecord, record.id)
            if ledger is None:
                raise RuntimeError("Attendance idempotency ledger row disappeared")
            ledger.status = "COMPLETED"
            ledger.resource_id = attendance.id
            ledger.response_json = response
            await self.session.commit()
            return response
        except Exception as exc:
            await self.session.rollback()
            ledger = await self.session.get(MobileIdempotencyRecord, record.id)
            if ledger:
                ledger.status = "FAILED"
                detail = getattr(exc, "detail", None)
                ledger.error_code = str((detail or {}).get("code") if isinstance(detail, dict) else "ATTENDANCE_FAILED")[:100]
                await self.session.commit()
            raise

    async def subscribe_push(
        self, *, user_id: uuid.UUID, company_id: uuid.UUID, provider: str,
        endpoint_or_token: str, keys: dict | None = None, device_id: str | None = None,
        user_agent: str | None = None,
    ) -> PushSubscription:
        provider = provider.upper()
        if provider not in {"WEBPUSH", "FCM"}:
            raise ValueError("Push provider must be WEBPUSH or FCM")
        if not endpoint_or_token.strip():
            raise ValueError("A push endpoint or FCM token is required")
        subscription_hash = hashlib.sha256(endpoint_or_token.strip().encode()).hexdigest()
        subscription = (await self.session.execute(select(PushSubscription).where(
            PushSubscription.subscription_hash == subscription_hash,
        ))).scalar_one_or_none()
        if subscription is None:
            subscription = PushSubscription(id=uuid.uuid4(), subscription_hash=subscription_hash)
            self.session.add(subscription)
        elif subscription.user_id != user_id or subscription.company_id != company_id:
            raise HTTPException(status_code=409, detail={
                "code": "PUSH_SUBSCRIPTION_OWNED_BY_ANOTHER_USER",
                "message": "This push endpoint is already registered to another user or tenant.",
            })
        subscription.company_id = company_id
        subscription.user_id = user_id
        subscription.provider = provider
        subscription.endpoint_or_token = endpoint_or_token.strip()
        subscription.keys_json = keys or None
        subscription.device_id = device_id
        subscription.user_agent = (user_agent or "")[:500] or None
        subscription.is_active = True
        await self.session.commit()
        return subscription

    async def save_camera_document(
        self, *, employee_id: uuid.UUID, user_id: uuid.UUID, document_type: str,
        file_name: str, content_type: str, content: bytes, captured_at: str | None = None,
    ) -> EmployeeDocument:
        if not content:
            raise ValueError("Document content is empty")
        if len(content) > 10 * 1024 * 1024:
            raise ValueError("Document exceeds the 10 MB limit")
        allowed = {"image/jpeg": ".jpg", "image/png": ".png", "application/pdf": ".pdf"}
        if content_type not in allowed:
            raise ValueError("Only JPEG, PNG and PDF camera documents are supported")
        root = Path(os.getenv("MOBILE_UPLOAD_DIR", "uploads/mobile-documents")).resolve()
        root.mkdir(parents=True, exist_ok=True)
        stored_name = f"{uuid.uuid4().hex}{allowed[content_type]}"
        destination = (root / stored_name).resolve()
        if destination.parent != root:
            raise ValueError("Invalid document destination")
        destination.write_bytes(content)
        document = EmployeeDocument(
            id=uuid.uuid4(), employee_id=employee_id, uploaded_by=user_id,
            title=file_name[:150], description=f"Mobile camera capture: {captured_at or 'server receipt'}",
            document_type=document_type.upper(), file_path=str(destination), file_name=stored_name,
            file_size=len(content), document_hash=hashlib.sha256(content).hexdigest(),
            status="PENDING", visibility="PRIVATE", tags="MOBILE_CAMERA",
        )
        self.session.add(document)
        await self.session.commit()
        return document
