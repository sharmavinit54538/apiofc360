"""Multi-tenant Company Branding, HR Contact, Signatory, and Payslip Display Settings Service."""
from __future__ import annotations

import logging
import os
import re
import uuid
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import settings as app_settings
from app.models.company import Company, LegalEntity
from app.models.payroll import StatutoryComplianceConfig
from app.services.payroll.audit_service import PayrollAuditService

logger = logging.getLogger(__name__)

_HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
_EMAIL_RE = re.compile(r"^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+$")
_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
_CONFIGURED_UPLOAD_DIR = str(getattr(app_settings, "UPLOAD_DIR", "uploads") or "uploads")
_UPLOAD_ROOT_ABS = (
    os.path.abspath(_CONFIGURED_UPLOAD_DIR)
    if os.path.isabs(_CONFIGURED_UPLOAD_DIR)
    else os.path.abspath(os.path.join(_PROJECT_ROOT, _CONFIGURED_UPLOAD_DIR))
)

DEFAULT_PAYSLIP_SETTINGS: dict[str, Any] = {
    "primary_color": "#182C43",
    "secondary_color": "#F5F7FA",
    "accent_color": "#0B665C",
    "company_legal_name": None,
    "registered_address": None,
    "city": None,
    "state": None,
    "postal_code": None,
    "country": "India",
    "official_email": None,
    "official_phone": None,
    "website": None,
    "cin_number": None,
    "gstin": None,
    "pf_establishment_code": None,
    "esic_registration_number": None,
    "company_logo_url": None,
    "hr_contact_name": None,
    "hr_designation": None,
    "hr_department": "Human Resources & Payroll",
    "hr_email": None,
    "hr_phone": None,
    "payroll_support_email": None,
    "office_extension": None,
    "signatory_name": None,
    "signatory_designation": None,
    "signatory_department": "Human Resources / Finance",
    "signature_image_url": None,
    "company_seal_url": None,
    "unsigned_declaration": "This is a computer-generated salary slip and does not require a physical signature.",
    "footer_declaration": "This is a confidential payroll document intended solely for the authorized employee.",
    "show_zero_components": False,
    "show_ytd_summary": True,
    "show_employer_contributions": True,
    "enable_qr_verification": True,
    "show_ofc360_footer": True,
    "mask_pf_number": True,
    "allow_draft_preview": True,
    "default_payment_mode": "NEFT",
}

ALLOWED_SETTING_KEYS = set(DEFAULT_PAYSLIP_SETTINGS.keys())


def resolve_safe_local_image_path(path_or_url: str | None) -> Optional[str]:
    """Resolve an uploaded asset URL/path strictly within local UPLOAD_DIR; never fetch remote HTTP/HTTPS."""
    if not path_or_url:
        return None
    raw = str(path_or_url).strip()
    if not raw:
        return None
    if raw.lower().startswith(("http://", "https://", "javascript:", "data:", "file://", "//")):
        return None

    # Support app-relative '/uploads/logos/...' or Windows 'uploads\logos\...'
    normalized = raw.replace("\\", "/").lstrip("/")
    if normalized.startswith("uploads/"):
        rel = normalized[len("uploads/"):].replace("/", os.sep)
        candidate = os.path.abspath(os.path.join(_UPLOAD_ROOT_ABS, rel))
    elif not os.path.isabs(raw):
        candidate = os.path.abspath(os.path.join(_UPLOAD_ROOT_ABS, raw.replace("/", os.sep)))
    else:
        candidate = os.path.abspath(raw)

    real_root = os.path.realpath(_UPLOAD_ROOT_ABS)
    real_candidate = os.path.realpath(candidate)
    try:
        is_inside = os.path.commonpath([os.path.normcase(real_root), os.path.normcase(real_candidate)]) == os.path.normcase(real_root)
    except ValueError:
        is_inside = False
    if not is_inside:
        return None
    if not os.path.isfile(real_candidate):
        return None
    return real_candidate


def _validate_asset_ref(value: str | None, field_name: str) -> str | None:
    if value is None or not str(value).strip():
        return None
    clean = str(value).strip()
    lowered = clean.lower()
    if lowered.startswith(("javascript:", "vbscript:", "data:text/html", "//")):
        raise ValueError(f"{field_name} contains a forbidden scheme.")
    if ".." in clean.replace("\\", "/").split("/"):
        raise ValueError(f"{field_name} cannot contain path traversal segments.")
    if len(clean) > 500:
        raise ValueError(f"{field_name} exceeds maximum length of 500 characters.")
    if not (clean.startswith("/uploads/") or clean.startswith("uploads/") or clean.startswith("/assets/")):
        raise ValueError(f"{field_name} must reference an application upload path under /uploads/ or /assets/.")
    return clean


class PayslipSettingsService:
    """Resolves and persists per-tenant enterprise payslip settings from existing tenant models."""

    @staticmethod
    def resolve_effective_settings(
        company: Company | None,
        config: StatutoryComplianceConfig | None = None,
        legal_entity: LegalEntity | None = None,
    ) -> dict[str, Any]:
        """Compose effective company-specific payslip settings strictly within one tenant."""
        merged = dict(DEFAULT_PAYSLIP_SETTINGS)
        if company is None:
            return merged

        profile = company.company_profile if isinstance(company.company_profile, dict) else {}
        hr_cfg = company.hr_settings if isinstance(company.hr_settings, dict) else {}
        custom_ps = company.payslip_settings if isinstance(company.payslip_settings, dict) else {}

        # Company identity (prefer LegalEntity if run belongs to one, else Company profile / Company row)
        merged["company_name"] = (
            (legal_entity.name if legal_entity else None)
            or (company.brand_display_name if company.whitelabel_enabled and company.brand_display_name else None)
            or profile.get("companyName")
            or company.name
        )
        merged["company_legal_name"] = (
            custom_ps.get("company_legal_name")
            or (legal_entity.legal_name if legal_entity else None)
            or profile.get("legal_name")
            or (config.legal_business_name if config and config.legal_business_name else None)
        )
        merged["registered_address"] = (
            custom_ps.get("registered_address")
            or (legal_entity.address if legal_entity and legal_entity.address else None)
            or profile.get("address")
            or profile.get("registered_address")
        )
        merged["city"] = custom_ps.get("city") or profile.get("city")
        merged["state"] = custom_ps.get("state") or profile.get("state") or (config.state if config else None)
        merged["postal_code"] = custom_ps.get("postal_code") or profile.get("postal_code") or profile.get("pincode")
        merged["country"] = custom_ps.get("country") or profile.get("country") or (config.country if config else "India")
        merged["official_email"] = (
            custom_ps.get("official_email")
            or profile.get("email")
            or company.email_sender_address
        )
        merged["official_phone"] = custom_ps.get("official_phone") or profile.get("phone")
        merged["website"] = custom_ps.get("website") or profile.get("website")
        merged["cin_number"] = (
            custom_ps.get("cin_number")
            or profile.get("registrationNumber")
            or (config.cin_number if config else None)
        )
        merged["gstin"] = (
            custom_ps.get("gstin")
            or (legal_entity.gstin if legal_entity and legal_entity.gstin else None)
            or profile.get("taxId")
            or (config.gst_number if config else None)
        )
        merged["pf_establishment_code"] = (
            custom_ps.get("pf_establishment_code")
            or (legal_entity.pf_code if legal_entity and legal_entity.pf_code else None)
            or profile.get("pf_code")
        )
        merged["esic_registration_number"] = (
            custom_ps.get("esic_registration_number")
            or (legal_entity.esi_code if legal_entity and legal_entity.esi_code else None)
            or profile.get("esi_code")
        )

        # Branding colors & logo
        if company.whitelabel_enabled:
            merged["primary_color"] = company.brand_primary_color or merged["primary_color"]
            merged["secondary_color"] = company.brand_secondary_color or merged["secondary_color"]
        merged["company_logo_url"] = (
            custom_ps.get("company_logo_url")
            or company.brand_logo_url
            or profile.get("company_logo")
            or (config.company_logo_url if config else None)
        )
        merged["signature_image_url"] = (
            custom_ps.get("signature_image_url")
            or (config.digital_signature_url if config else None)
        )

        # Explicit HR contact & support (never pick personal emails or random HR users)
        hr_official = hr_cfg.get("hr_contact") if isinstance(hr_cfg.get("hr_contact"), dict) else {}
        for k in (
            "hr_contact_name", "hr_designation", "hr_department",
            "hr_email", "hr_phone", "payroll_support_email", "office_extension",
        ):
            val = custom_ps.get(k) or hr_official.get(k)
            if val:
                merged[k] = val

        # Config footer fallback if custom not set
        if not custom_ps.get("footer_declaration") and config and config.payslip_footer:
            merged["footer_declaration"] = config.payslip_footer

        if not custom_ps.get("default_payment_mode") and config and config.salary_transfer_format:
            merged["default_payment_mode"] = config.salary_transfer_format

        # Apply explicit payslip_settings overrides cleanly
        for key in ALLOWED_SETTING_KEYS:
            if key in custom_ps and custom_ps[key] is not None:
                merged[key] = custom_ps[key]

        merged["company_id"] = str(company.id)
        return merged

    @classmethod
    async def get_settings(
        cls,
        session: AsyncSession,
        company_id: uuid.UUID,
    ) -> dict[str, Any]:
        company = await session.get(Company, company_id)
        if company is None:
            raise LookupError(f"Company '{company_id}' not found.")
        cfg = (
            await session.execute(
                select(StatutoryComplianceConfig)
                .where(StatutoryComplianceConfig.company_id == company_id, StatutoryComplianceConfig.is_active == True)  # noqa: E712
                .limit(1)
            )
        ).scalar_one_or_none()
        return cls.resolve_effective_settings(company, cfg)

    @classmethod
    async def update_settings(
        cls,
        session: AsyncSession,
        company_id: uuid.UUID,
        payload: dict[str, Any],
        *,
        actor_id: Optional[uuid.UUID] = None,
        actor_role: Optional[str] = None,
    ) -> dict[str, Any]:
        company = await session.get(Company, company_id)
        if company is None:
            raise LookupError(f"Company '{company_id}' not found.")

        unknown = set(payload.keys()) - ALLOWED_SETTING_KEYS
        if unknown:
            raise ValueError(f"Unsupported payslip setting fields: {', '.join(sorted(unknown))}")

        current = dict(company.payslip_settings) if isinstance(company.payslip_settings, dict) else {}
        validated: dict[str, Any] = {}

        for key, value in payload.items():
            if key in {"primary_color", "secondary_color", "accent_color"}:
                if value is not None:
                    text_val = str(value).strip().upper()
                    if not _HEX_COLOR_RE.fullmatch(text_val):
                        raise ValueError(f"{key} must be a 6-digit hex color code (e.g. #182C43).")
                    validated[key] = text_val
                else:
                    validated[key] = DEFAULT_PAYSLIP_SETTINGS[key]
            elif key in {"official_email", "hr_email", "payroll_support_email"}:
                if value is not None and str(value).strip():
                    email_val = str(value).strip()
                    if not _EMAIL_RE.fullmatch(email_val):
                        raise ValueError(f"{key} must be a valid email address.")
                    validated[key] = email_val
                else:
                    validated[key] = None
            elif key in {"company_logo_url", "signature_image_url", "company_seal_url"}:
                validated[key] = _validate_asset_ref(value, key)
            elif key in {
                "show_zero_components", "show_ytd_summary", "show_employer_contributions",
                "enable_qr_verification", "show_ofc360_footer", "mask_pf_number", "allow_draft_preview",
            }:
                validated[key] = bool(value)
            else:
                validated[key] = str(value).strip() if isinstance(value, str) else value

        current.update(validated)
        company.payslip_settings = current
        flag_modified(company, "payslip_settings")

        # Keep Company whitelabel logo & colors in sync when explicitly configured through payslip settings
        if "company_logo_url" in validated and validated["company_logo_url"]:
            company.brand_logo_url = validated["company_logo_url"]
        if "primary_color" in validated and company.whitelabel_enabled:
            company.brand_primary_color = validated["primary_color"]

        await PayrollAuditService.log_event(
            session=session,
            entity_type="CompanyPayslipSettings",
            entity_id=company.id,
            action="UPDATE_PAYSLIP_SETTINGS",
            company_id=company.id,
            actor_id=actor_id,
            actor_role=actor_role,
            reason="Updated company payslip branding, HR contact, signatory, and visibility settings",
            extra_data={"updated_keys": sorted(validated.keys())},
        )
        await session.commit()
        await session.refresh(company)
        return await cls.get_settings(session, company_id)
