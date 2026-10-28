"""Tenant white-label settings and branded document helpers."""
from __future__ import annotations

import re
import uuid
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import Company

_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
_EMAIL = re.compile(r"^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+$")
_DOMAIN_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")


class WhiteLabelService:
    EDITABLE_FIELDS = {
        "custom_domain", "whitelabel_enabled", "brand_display_name",
        "brand_primary_color", "brand_secondary_color", "brand_logo_url",
        "brand_favicon_url", "email_sender_name", "email_sender_address",
        "email_reply_to", "branded_pdf_header_text",
    }

    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def branding_for(company: Company) -> dict[str, Any]:
        return {
            "enabled": bool(company.whitelabel_enabled),
            "display_name": company.brand_display_name or company.name,
            "custom_domain": company.custom_domain,
            "theme": {
                "primary_color": company.brand_primary_color,
                "secondary_color": company.brand_secondary_color,
                "logo_url": company.brand_logo_url,
                "favicon_url": company.brand_favicon_url,
            },
            "email_sender": {
                "name": company.email_sender_name or company.brand_display_name or company.name,
                "address": company.email_sender_address,
                "reply_to": company.email_reply_to,
            },
            "pdf_header": {
                "text": company.branded_pdf_header_text,
                "primary_color": company.brand_primary_color,
                "secondary_color": company.brand_secondary_color,
                "logo_url": company.brand_logo_url,
            },
        }

    async def get(self, company_id: uuid.UUID) -> dict[str, Any]:
        company = await self.session.get(Company, company_id)
        if company is None:
            raise LookupError("Company not found in the current tenant.")
        return {"company_id": str(company.id), **self.branding_for(company)}

    @staticmethod
    def normalize_domain(value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        value = value.strip().lower().rstrip(".")
        if "://" in value or any(character in value for character in "/@?# "):
            raise ValueError("custom_domain must be a hostname only, without scheme, port, path or credentials.")
        try:
            ascii_domain = value.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise ValueError("custom_domain is not a valid IDN hostname.") from exc
        labels = ascii_domain.split(".")
        if len(labels) < 2 or len(ascii_domain) > 253 or any(not _DOMAIN_LABEL.fullmatch(label) for label in labels):
            raise ValueError("custom_domain must be a valid fully qualified hostname.")
        return ascii_domain

    @staticmethod
    def validate_url(value: str | None, field_name: str) -> str | None:
        if value is None or not value.strip():
            return None
        value = value.strip()
        if value.startswith("/") and not value.startswith("//"):
            return value
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError(f"{field_name} must be an HTTPS URL or an application-relative path.")
        return value

    async def update(self, company_id: uuid.UUID, values: dict[str, Any]) -> dict[str, Any]:
        company = await self.session.get(Company, company_id)
        if company is None:
            raise LookupError("Company not found in the current tenant.")
        unknown = set(values) - self.EDITABLE_FIELDS
        if unknown:
            raise ValueError(f"Unsupported white-label fields: {', '.join(sorted(unknown))}.")
        values = dict(values)
        if "custom_domain" in values:
            domain = self.normalize_domain(values["custom_domain"])
            if domain:
                duplicate = (await self.session.execute(select(Company).where(
                    Company.custom_domain == domain, Company.id != company_id,
                ))).scalar_one_or_none()
                if duplicate is not None:
                    raise ValueError("custom_domain is already registered to another company.")
            values["custom_domain"] = domain
        for field in ("brand_primary_color", "brand_secondary_color"):
            if field in values and values[field] is not None:
                if not _COLOR.fullmatch(str(values[field])):
                    raise ValueError(f"{field} must be a six-digit hex color such as #17365D.")
                values[field] = str(values[field]).upper()
        for field in ("brand_logo_url", "brand_favicon_url"):
            if field in values:
                values[field] = self.validate_url(values[field], field)
        for field in ("email_sender_address", "email_reply_to"):
            if field in values and values[field]:
                values[field] = str(values[field]).strip()
                if not _EMAIL.fullmatch(values[field]):
                    raise ValueError(f"{field} must be a valid email address.")
            elif field in values:
                values[field] = None
        for field in ("brand_display_name", "email_sender_name", "branded_pdf_header_text"):
            if field in values and values[field] is not None:
                values[field] = str(values[field]).strip() or None
        for key, value in values.items():
            setattr(company, key, value)
        await self.session.commit()
        await self.session.refresh(company)
        return {"company_id": str(company.id), **self.branding_for(company)}

    async def preview_pdf(self, company_id: uuid.UUID) -> bytes:
        company = await self.session.get(Company, company_id)
        if company is None:
            raise LookupError("Company not found in the current tenant.")
        from app.services.document_service import DocumentService
        content = (
            "This preview verifies the tenant document header.\n\n"
            f"Display name: {company.brand_display_name or company.name}\n"
            f"Primary colour: {company.brand_primary_color}\n"
            "Payslips and canonical HR letters use the same tenant branding resolver."
        )
        return DocumentService._render_text_to_pdf(
            "White-label document preview", content, branding=self.branding_for(company),
        )
