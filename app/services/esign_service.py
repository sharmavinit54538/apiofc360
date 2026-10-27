"""Built-in and provider e-signing with tamper evidence and audit certificates."""
from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import DocumentAuditLog, DocumentSignature
from app.models.employee import Employee
from app.models.employee_document import EmployeeDocument
from app.models.user import User
from app.services.document_service import DocumentService
from app.services.storage_service import DOCUMENTS_DIR_ABSOLUTE

PROVIDERS = {"BUILT_IN", "DOCUSIGN", "LEEGALITY"}
SIGNATURE_METHODS = {"OTP", "SIGNATURE_PAD", "PROVIDER"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _otp_hash(signature_id: uuid.UUID, otp: str) -> str:
    return hashlib.sha256(f"{signature_id}:{otp}".encode("utf-8")).hexdigest()


class ESignProviderAdapter:
    provider = "BUILT_IN"

    async def create_envelope(self, **kwargs: Any) -> dict[str, Any]:
        return {"envelope_id": f"builtin-{uuid.uuid4()}", "status": "sent"}


class DocuSignAdapter(ESignProviderAdapter):
    provider = "DOCUSIGN"

    def __init__(self) -> None:
        self.base_url = os.getenv("DOCUSIGN_BASE_URL", "").rstrip("/")
        self.account_id = os.getenv("DOCUSIGN_ACCOUNT_ID", "")
        self.token = os.getenv("DOCUSIGN_ACCESS_TOKEN", "")

    async def create_envelope(self, **kwargs: Any) -> dict[str, Any]:
        if not all((self.base_url, self.account_id, self.token)):
            raise ValueError("DocuSign is not configured (base URL, account ID and access token are required).")
        signer: User = kwargs["signer"]
        payload = {
            "emailSubject": kwargs["document"].title or "Document for signature",
            "status": "sent",
            "documents": [{
                "documentBase64": base64.b64encode(kwargs["pdf_bytes"]).decode("ascii"),
                "name": kwargs["document"].file_name or "document.pdf", "fileExtension": "pdf", "documentId": "1",
            }],
            "recipients": {"signers": [{
                "email": signer.email, "name": signer.name, "recipientId": str(signer.id),
                "routingOrder": "1", "clientUserId": str(signer.id),
                "tabs": {"signHereTabs": [{"documentId": "1", "pageNumber": "1", "recipientId": str(signer.id), "xPosition": "100", "yPosition": "650"}]},
            }]},
        }
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{self.base_url}/v2.1/accounts/{self.account_id}/envelopes",
                json=payload, headers={"Authorization": f"Bearer {self.token}"},
            )
            response.raise_for_status()
            data = response.json()
        return {"envelope_id": data.get("envelopeId"), "status": data.get("status"), "raw": data}


class LeegalityAdapter(ESignProviderAdapter):
    provider = "LEEGALITY"

    def __init__(self) -> None:
        self.base_url = os.getenv("LEEGALITY_BASE_URL", "").rstrip("/")
        self.token = os.getenv("LEEGALITY_API_TOKEN", "")

    async def create_envelope(self, **kwargs: Any) -> dict[str, Any]:
        if not all((self.base_url, self.token)):
            raise ValueError("Leegality is not configured (base URL and API token are required).")
        signer: User = kwargs["signer"]
        document: EmployeeDocument = kwargs["document"]
        payload = {
            "name": document.title or "Employee document",
            "file": base64.b64encode(kwargs["pdf_bytes"]).decode("ascii"),
            "signers": [{"name": signer.name, "email": signer.email, "identifier": str(signer.id)}],
            "callbackUrl": kwargs.get("callback_url"),
        }
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{self.base_url}/api/v1/documents", json=payload,
                headers={"Authorization": f"Bearer {self.token}"},
            )
            response.raise_for_status()
            data = response.json()
        return {"envelope_id": data.get("documentId") or data.get("id"), "status": data.get("status"), "raw": data}


ADAPTERS = {"BUILT_IN": ESignProviderAdapter, "DOCUSIGN": DocuSignAdapter, "LEEGALITY": LeegalityAdapter}


class ESignService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def _document(self, document_id: uuid.UUID) -> EmployeeDocument:
        doc = (await self.session.execute(select(EmployeeDocument).where(
            EmployeeDocument.id == document_id, EmployeeDocument.is_deleted == False  # noqa: E712
        ))).scalar_one_or_none()
        if doc is None:
            raise ValueError("Document not found.")
        employee = await self.session.get(Employee, doc.employee_id)
        if employee is None:
            raise ValueError("Document employee not found.")
        doc._tenant_company_id = employee.company_id
        return doc

    @staticmethod
    def _read_pdf(doc: EmployeeDocument) -> bytes:
        if not doc.file_path or not os.path.isfile(doc.file_path):
            raise ValueError("Document PDF is not available in secure storage.")
        with open(doc.file_path, "rb") as handle:
            content = handle.read()
        if not content.startswith(b"%PDF"):
            raise ValueError("E-signing requires a PDF document.")
        return content

    async def request_esign(
        self, document_id: uuid.UUID, signer_user_id: uuid.UUID, *, requested_by: uuid.UUID,
        company_id: uuid.UUID | None = None, provider: str = "BUILT_IN", method: str = "OTP",
        request_ip: str | None = None, user_agent: str | None = None, callback_url: str | None = None,
    ) -> dict[str, Any]:
        provider = provider.upper()
        method = method.upper()
        if provider not in PROVIDERS or method not in SIGNATURE_METHODS:
            raise ValueError("Unsupported e-sign provider or signature method.")
        if provider != "BUILT_IN":
            method = "PROVIDER"
        if method == "PROVIDER" and provider == "BUILT_IN":
            raise ValueError("PROVIDER method requires DocuSign or Leegality.")
        doc = await self._document(document_id)
        tenant_id = doc._tenant_company_id
        if company_id is not None and tenant_id != company_id:
            raise ValueError("Document not found in the current tenant.")
        signer = await self.session.get(User, signer_user_id)
        if signer is None or signer.is_deleted or not signer.is_active or signer.company_id != tenant_id:
            raise ValueError("Signer must be an active user in the document tenant.")
        existing = (await self.session.execute(select(DocumentSignature).where(
            DocumentSignature.employee_doc_id == document_id,
            DocumentSignature.signer_user_id == signer_user_id,
            DocumentSignature.status == "PENDING",
        ))).scalar_one_or_none()
        if existing:
            raise ValueError("A pending e-sign request already exists for this signer.")
        pdf_bytes = self._read_pdf(doc)
        digest = hashlib.sha256(pdf_bytes).hexdigest()
        if doc.document_hash and doc.document_hash != digest:
            raise ValueError("Stored document hash does not match the PDF; e-sign request rejected.")
        signature = DocumentSignature(
            employee_doc_id=document_id, signer_user_id=signer_user_id, requested_by=requested_by,
            status="PENDING", provider=provider, signature_method=method,
            document_hash=digest, request_ip=request_ip, user_agent=user_agent,
        )
        self.session.add(signature)
        await self.session.flush()
        otp = None
        if provider == "BUILT_IN" and method == "OTP":
            otp = f"{secrets.randbelow(900000) + 100000:06d}"
            signature.otp_hash = _otp_hash(signature.id, otp)
            signature.otp_expires_at = _utcnow() + timedelta(minutes=10)
        envelope = await ADAPTERS[provider]().create_envelope(
            document=doc, signer=signer, pdf_bytes=pdf_bytes, callback_url=callback_url,
        )
        signature.provider_envelope_id = envelope.get("envelope_id")
        doc.status = "REQUIRES_SIGNATURE"
        doc.is_verified = False
        self.session.add(DocumentAuditLog(
            company_id=tenant_id, user_id=requested_by, action="SIGNATURE_REQUESTED",
            target_type="EMPLOYEE_DOC", target_id=document_id,
            details=f"E-sign requested via {provider}/{method} for {signer.email}", ip_address=request_ip,
        ))
        result = self._serialize(signature)
        result["otp"] = otp  # returned to the service caller for delivery; never exposed by the API
        await self.session.commit()
        if otp:
            try:
                from app.services.email_service import send_email
                await send_email(signer.email, "Your OFC360 e-sign OTP",
                                 f"<p>Your one-time signing code is <strong>{otp}</strong>. It expires in 10 minutes.</p>")
                result["otp_delivery"] = "EMAIL"
            except Exception:
                result["otp_delivery"] = "FAILED"
        return result

    async def sign_document(
        self, document_id: uuid.UUID, signer_user_id: uuid.UUID, *, otp: str | None = None,
        signature_data: str | None = None, signer_ip: str | None = None,
        user_agent: str | None = None, device_info: str | None = None,
    ) -> dict[str, Any]:
        doc = await self._document(document_id)
        signature = (await self.session.execute(select(DocumentSignature).where(
            DocumentSignature.employee_doc_id == document_id,
            DocumentSignature.signer_user_id == signer_user_id,
            DocumentSignature.status == "PENDING",
        ).order_by(DocumentSignature.created_at.desc()).limit(1))).scalar_one_or_none()
        if signature is None:
            raise ValueError("No pending e-sign request found for this signer.")
        if signature.provider != "BUILT_IN":
            raise ValueError("Provider signatures must be completed through the provider webhook.")
        pdf_bytes = self._read_pdf(doc)
        if hashlib.sha256(pdf_bytes).hexdigest() != signature.document_hash:
            raise ValueError("Document changed after the e-sign request; signing rejected.")
        if signature.signature_method == "OTP":
            if (signature.otp_attempts or 0) >= 5:
                raise ValueError("OTP attempt limit exceeded; request a new e-sign invitation.")
            if not otp or not signature.otp_hash or not hmac.compare_digest(_otp_hash(signature.id, otp), signature.otp_hash):
                signature.otp_attempts = (signature.otp_attempts or 0) + 1
                await self.session.commit()
                raise ValueError("Invalid signing OTP.")
            if signature.otp_expires_at is None or _aware(signature.otp_expires_at) <= _utcnow():
                raise ValueError("Signing OTP has expired; request a new e-sign invitation.")
        elif signature.signature_method == "SIGNATURE_PAD":
            if not signature_data or not signature_data.strip():
                raise ValueError("Signature-pad data is required.")
            if len(signature_data) > 2_000_000:
                raise ValueError("Signature-pad data exceeds the 2 MB limit.")
        else:
            raise ValueError("Unsupported built-in signature method.")
        signature.signature_data = signature_data
        signature.signature_method = signature.signature_method or "OTP"
        result = await self._finalize_signature(
            signature, doc, pdf_bytes, signer_ip=signer_ip,
            user_agent=user_agent, device_info=device_info,
        )
        await self.session.commit()
        return result

    async def _finalize_signature(
        self, signature: DocumentSignature, doc: EmployeeDocument, original_pdf: bytes, *,
        signer_ip: str | None, user_agent: str | None, device_info: str | None = None,
        signed_pdf: bytes | None = None, webhook_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if signature.status == "SIGNED":
            return self._serialize(signature)
        signed_at = _utcnow()
        signer = await self.session.get(User, signature.signer_user_id)
        tenant_id = doc._tenant_company_id
        audit_certificate = {
            "certificate_id": str(uuid.uuid4()), "document_id": str(doc.id),
            "signature_id": str(signature.id), "original_pdf_sha256": signature.document_hash,
            "signer_user_id": str(signature.signer_user_id), "signer_name": signer.name if signer else "",
            "signer_email": signer.email if signer else "", "signed_at": signed_at.isoformat(),
            "signer_ip": signer_ip, "user_agent": user_agent, "device_info": device_info,
            "provider": signature.provider, "provider_envelope_id": signature.provider_envelope_id,
            "signature_method": signature.signature_method,
            "signature_data_sha256": hashlib.sha256(signature.signature_data.encode("utf-8")).hexdigest() if signature.signature_data else None,
        }
        if signed_pdf is None:
            signed_pdf = self._append_audit_page(original_pdf, audit_certificate)
        if not signed_pdf.startswith(b"%PDF"):
            raise ValueError("Provider returned an invalid signed PDF.")
        signed_hash = hashlib.sha256(signed_pdf).hexdigest()
        audit_certificate["signed_pdf_sha256"] = signed_hash
        os.makedirs(DOCUMENTS_DIR_ABSOLUTE, exist_ok=True)
        path = os.path.join(DOCUMENTS_DIR_ABSOLUTE, f"signed_{signature.id.hex}.pdf")
        with open(path, "wb") as handle:
            handle.write(signed_pdf)
        audit_certificate["signed_file_name"] = os.path.basename(path)
        signature.status = "SIGNED"
        signature.signed_at = signed_at
        signature.ip_address = signer_ip
        signature.user_agent = user_agent
        signature.device_info = device_info
        signature.signed_pdf_hash = signed_hash
        signature.signed_file_path = path
        signature.webhook_payload_json = webhook_payload
        signature.audit_certificate_json = audit_certificate
        signature.otp_hash = None
        signature.otp_expires_at = None
        # Preserve any prior HR verification while recording signature completion.
        doc.status = "VERIFIED" if doc.is_verified else "PENDING"
        self.session.add(DocumentAuditLog(
            company_id=tenant_id, user_id=signature.signer_user_id, action="SIGN",
            target_type="EMPLOYEE_DOC", target_id=doc.id,
            details=f"Document signed via {signature.provider}/{signature.signature_method}; SHA256={signed_hash}",
            ip_address=signer_ip,
        ))
        await self.session.flush()
        result = self._serialize(signature)
        result["audit_certificate"] = audit_certificate
        return result

    @staticmethod
    def _append_audit_page(pdf_bytes: bytes, certificate: dict[str, Any]) -> bytes:
        from pypdf import PdfReader, PdfWriter
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas
        try:
            reader = PdfReader(io.BytesIO(pdf_bytes))
            writer = PdfWriter()
            for page in reader.pages:
                writer.add_page(page)
            packet = io.BytesIO()
            pdf = canvas.Canvas(packet, pagesize=letter)
            pdf.setTitle("OFC360 E-sign Audit")
            text = pdf.beginText(48, 750)
            text.setFont("Helvetica", 9)
            for line in [
                "OFC360 E-SIGN AUDIT", f"Certificate: {certificate['certificate_id']}",
                f"Document: {certificate['document_id']}", f"Signer: {certificate['signer_name']}",
                f"Signer ID: {certificate['signer_user_id']}", f"Signed at: {certificate['signed_at']}",
                f"Method: {certificate['signature_method']}", f"Provider: {certificate['provider']}",
                f"Original SHA256: {certificate['original_pdf_sha256']}",
                f"Signer IP: {certificate.get('signer_ip') or ''}",
            ]:
                text.textLine(line)
            pdf.drawText(text)
            pdf.save()
            packet.seek(0)
            writer.add_page(PdfReader(packet).pages[0])
            writer.add_metadata({"/OFCSignatureCertificate": certificate["certificate_id"]})
            output = io.BytesIO()
            writer.write(output)
            return output.getvalue()
        except Exception as exc:
            raise ValueError(f"Unable to render signed PDF: {exc}") from exc

    async def process_provider_webhook(
        self, provider: str, payload: dict[str, Any], *, raw_body: bytes = b"", webhook_secret: str | None = None,
    ) -> dict[str, Any]:
        provider = provider.upper()
        if provider not in {"DOCUSIGN", "LEEGALITY"}:
            raise ValueError("Unsupported webhook provider.")
        configured_secret = os.getenv(f"{provider}_WEBHOOK_SECRET")
        # A completion webhook changes legal document state.  Fail closed when
        # the provider secret is absent rather than accepting forged callbacks.
        if not configured_secret:
            raise PermissionError(f"{provider} webhook signing is not configured.")
        supplied = (webhook_secret or "").strip()
        expected_bytes = hmac.new(configured_secret.encode("utf-8"), raw_body, hashlib.sha256).digest()
        expected_hex = expected_bytes.hex()
        expected_base64 = base64.b64encode(expected_bytes).decode("ascii")
        accepted_signatures = {
            expected_hex, f"sha256={expected_hex}", expected_base64, f"sha256={expected_base64}",
        }
        if not any(hmac.compare_digest(supplied, candidate) for candidate in accepted_signatures):
            raise PermissionError("Invalid provider webhook signature.")
        envelope_id = str(payload.get("envelope_id") or payload.get("envelopeId") or payload.get("documentId") or payload.get("id") or "")
        status = str(payload.get("status") or payload.get("event") or "").upper().replace("-", "_").replace(" ", "_")
        signature = (await self.session.execute(select(DocumentSignature).where(
            DocumentSignature.provider == provider,
            DocumentSignature.provider_envelope_id == envelope_id,
        ).order_by(DocumentSignature.created_at.desc()).limit(1))).scalar_one_or_none()
        if signature is None:
            raise ValueError("E-sign envelope not found.")
        if signature.status == "SIGNED":
            return self._serialize(signature)
        if status not in {"COMPLETED", "SIGNED", "SIGNATURE_COMPLETED", "DOCUMENT_SIGNED", "ENVELOPE_COMPLETED"}:
            signature.webhook_payload_json = payload
            await self.session.commit()
            return self._serialize(signature)
        doc = await self._document(signature.employee_doc_id)
        original_pdf = self._read_pdf(doc)
        signed_pdf = None
        encoded = payload.get("signed_pdf_base64") or payload.get("signedPdfBase64")
        if encoded:
            try:
                signed_pdf = base64.b64decode(encoded, validate=True)
            except Exception as exc:
                raise ValueError("Invalid signed PDF base64 in webhook.") from exc
        result = await self._finalize_signature(
            signature, doc, original_pdf,
            signer_ip=payload.get("signer_ip") or payload.get("ip_address"),
            user_agent=payload.get("user_agent"), webhook_payload=payload, signed_pdf=signed_pdf,
        )
        await self.session.commit()
        return result

    async def get_audit_certificate(
        self, document_id: uuid.UUID, *, company_id: uuid.UUID | None = None,
        signer_user_id: uuid.UUID | None = None,
    ) -> tuple[dict[str, Any], bytes]:
        doc = await self._document(document_id)
        if company_id is not None and doc._tenant_company_id != company_id:
            raise ValueError("Document not found in the current tenant.")
        stmt = select(DocumentSignature).where(
            DocumentSignature.employee_doc_id == document_id, DocumentSignature.status == "SIGNED"
        )
        if signer_user_id:
            stmt = stmt.where(DocumentSignature.signer_user_id == signer_user_id)
        signature = (await self.session.execute(stmt.order_by(DocumentSignature.signed_at.desc()).limit(1))).scalar_one_or_none()
        if signature is None or not signature.audit_certificate_json:
            raise ValueError("No completed e-sign audit certificate found.")
        certificate = dict(signature.audit_certificate_json)
        if signature.signed_file_path and os.path.isfile(signature.signed_file_path):
            with open(signature.signed_file_path, "rb") as handle:
                current_hash = hashlib.sha256(handle.read()).hexdigest()
            certificate["signed_pdf_intact"] = current_hash == signature.signed_pdf_hash
        else:
            certificate["signed_pdf_intact"] = False
        lines = ["OFC360 E-SIGN AUDIT CERTIFICATE", ""]
        lines.extend(f"{key}: {json.dumps(value, default=str) if isinstance(value, (dict, list)) else value}" for key, value in certificate.items())
        pdf = DocumentService._render_text_to_pdf("E-sign Audit Certificate", "\n".join(lines))
        return certificate, pdf

    @staticmethod
    def _serialize(signature: DocumentSignature) -> dict[str, Any]:
        return {
            "id": str(signature.id), "document_id": str(signature.employee_doc_id),
            "signer_user_id": str(signature.signer_user_id), "status": signature.status,
            "provider": signature.provider, "provider_envelope_id": signature.provider_envelope_id,
            "signature_method": signature.signature_method, "document_hash": signature.document_hash,
            "signed_pdf_hash": signature.signed_pdf_hash,
            "signed_at": signature.signed_at.isoformat() if signature.signed_at else None,
            "signer_ip": signature.ip_address, "user_agent": signature.user_agent,
            "otp_attempts": signature.otp_attempts,
        }


__all__ = [
    "ESignService", "ESignProviderAdapter", "DocuSignAdapter", "LeegalityAdapter",
    "PROVIDERS", "SIGNATURE_METHODS",
]
