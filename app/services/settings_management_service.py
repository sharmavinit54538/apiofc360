"""Settings Management Service for OFC360 enterprise multi-tenant platform.

Handles persistence, tenant scoping, validation, audit logging, and defaults for:
- Company Logo
- Employee Settings
- Leave Settings
- Document Settings
- Asset Settings
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Optional
from datetime import datetime, timezone

from fastapi import UploadFile, status, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.models.company import Company
from app.models.audit_log import AuditLog
from app.models.settings_models import (
    EmployeeSettings,
    LeaveSettings,
    DocumentSettings,
    AssetSettings,
)
from app.schemas.settings_schemas import (
    EmployeeSettingsUpdate,
    LeaveSettingsUpdate,
    DocumentSettingsUpdate,
    AssetSettingsUpdate,
)
from app.services.company_logo_service import CompanyLogoService

logger = logging.getLogger(__name__)


async def _create_audit_entry(
    session: AsyncSession,
    company_id: Optional[uuid.UUID],
    user_id: Optional[uuid.UUID],
    claims: Optional[dict],
    action: str,
    details: str,
) -> None:
    """Helper to record audit log entry for settings changes."""
    email = claims.get("email") if claims else None
    ip_address = claims.get("ip_address", "127.0.0.1") if claims else "127.0.0.1"
    audit = AuditLog(
        user_id=user_id,
        company_id=company_id,
        action=action,
        email=email,
        ip_address=ip_address,
        user_agent="FastAPI Backend Settings Module",
        details=details,
    )
    session.add(audit)


class SettingsManagementService:
    """Enterprise multi-tenant settings management service."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── 1. Company Logo ─────────────────────────────────────────────────────────

    async def upload_company_logo(
        self,
        company_id: uuid.UUID,
        file: UploadFile,
        user_id: Optional[uuid.UUID] = None,
        claims: Optional[dict] = None,
    ) -> Dict[str, Any]:
        """Upload and associate logo with company profile and branding."""
        stmt = select(Company).where(Company.id == company_id)
        res = await self.session.execute(stmt)
        company = res.scalar_one_or_none()
        if not company:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Company not found.",
            )

        logo_service = CompanyLogoService(self.session)
        result = await logo_service.upload_company_logo(company, file)

        # Also populate brand_logo_url for whitelabel branding consistency
        if hasattr(company, "brand_logo_url"):
            company.brand_logo_url = result.get("logo_url")
            flag_modified(company, "brand_logo_url")
            await self.session.commit()

        # Audit log
        await _create_audit_entry(
            self.session,
            company_id=company_id,
            user_id=user_id,
            claims=claims,
            action="UPDATE_COMPANY_LOGO",
            details=f"Uploaded new corporate logo for company {company.name} ({company_id}).",
        )
        await self.session.commit()

        return result

    # ── 2. Employee Settings ───────────────────────────────────────────────────

    async def get_or_create_employee_settings(self, company_id: uuid.UUID) -> EmployeeSettings:
        """Retrieve existing employee settings or instantiate default organization settings."""
        stmt = select(EmployeeSettings).where(EmployeeSettings.company_id == company_id)
        res = await self.session.execute(stmt)
        obj = res.scalar_one_or_none()
        if not obj:
            obj = EmployeeSettings(
                id=uuid.uuid4(),
                company_id=company_id,
                employee_id_prefix="EMP",
                employee_id_start_number=1001,
                probation_period_days=90,
                default_employment_type="full_time",
                default_employee_status="active",
                allow_employee_profile_edit=True,
                require_manager_assignment=False,
            )
            self.session.add(obj)
            await self.session.commit()
            await self.session.refresh(obj)
        return obj

    async def update_employee_settings(
        self,
        company_id: uuid.UUID,
        payload: EmployeeSettingsUpdate,
        user_id: Optional[uuid.UUID] = None,
        claims: Optional[dict] = None,
    ) -> EmployeeSettings:
        """Update employee configuration for the organization."""
        settings_obj = await self.get_or_create_employee_settings(company_id)
        update_data = payload.model_dump(exclude_unset=True)

        for key, value in update_data.items():
            if hasattr(settings_obj, key):
                setattr(settings_obj, key, value)

        settings_obj.updated_by = user_id
        settings_obj.updated_at = datetime.now(timezone.utc)

        await _create_audit_entry(
            self.session,
            company_id=company_id,
            user_id=user_id,
            claims=claims,
            action="UPDATE_EMPLOYEE_SETTINGS",
            details=f"Updated employee settings: {list(update_data.keys())}",
        )

        await self.session.commit()
        await self.session.refresh(settings_obj)
        return settings_obj

    # ── 3. Leave Settings ──────────────────────────────────────────────────────

    async def get_or_create_leave_settings(self, company_id: uuid.UUID) -> LeaveSettings:
        """Retrieve existing leave settings or instantiate default organization settings."""
        stmt = select(LeaveSettings).where(LeaveSettings.company_id == company_id)
        res = await self.session.execute(stmt)
        obj = res.scalar_one_or_none()
        if not obj:
            obj = LeaveSettings(
                id=uuid.uuid4(),
                company_id=company_id,
                leave_year_start_month=1,
                allow_half_day_leave=True,
                allow_negative_balance=False,
                require_manager_approval=True,
                max_consecutive_leave_days=30,
                carry_forward_enabled=True,
                carry_forward_limit=10,
                leave_encashment_enabled=False,
            )
            self.session.add(obj)
            await self.session.commit()
            await self.session.refresh(obj)
        return obj

    async def update_leave_settings(
        self,
        company_id: uuid.UUID,
        payload: LeaveSettingsUpdate,
        user_id: Optional[uuid.UUID] = None,
        claims: Optional[dict] = None,
    ) -> LeaveSettings:
        """Update leave configuration without touching employee balances or historical approvals."""
        settings_obj = await self.get_or_create_leave_settings(company_id)
        update_data = payload.model_dump(exclude_unset=True)

        for key, value in update_data.items():
            if hasattr(settings_obj, key):
                setattr(settings_obj, key, value)

        settings_obj.updated_by = user_id
        settings_obj.updated_at = datetime.now(timezone.utc)

        await _create_audit_entry(
            self.session,
            company_id=company_id,
            user_id=user_id,
            claims=claims,
            action="UPDATE_LEAVE_SETTINGS",
            details=f"Updated leave settings: {list(update_data.keys())}",
        )

        await self.session.commit()
        await self.session.refresh(settings_obj)
        return settings_obj

    # ── 4. Document Settings ───────────────────────────────────────────────────

    async def get_or_create_document_settings(self, company_id: uuid.UUID) -> DocumentSettings:
        """Retrieve existing document settings or instantiate default organization settings."""
        stmt = select(DocumentSettings).where(DocumentSettings.company_id == company_id)
        res = await self.session.execute(stmt)
        obj = res.scalar_one_or_none()
        if not obj:
            obj = DocumentSettings(
                id=uuid.uuid4(),
                company_id=company_id,
                allowed_file_types=["pdf", "jpg", "jpeg", "png"],
                max_file_size_mb=10,
                require_document_verification=True,
                document_expiry_alert_days=30,
                employee_can_upload_documents=True,
                manager_can_view_documents=False,
            )
            self.session.add(obj)
            await self.session.commit()
            await self.session.refresh(obj)
        return obj

    async def update_document_settings(
        self,
        company_id: uuid.UUID,
        payload: DocumentSettingsUpdate,
        user_id: Optional[uuid.UUID] = None,
        claims: Optional[dict] = None,
    ) -> DocumentSettings:
        """Update document configuration safely without affecting employee files."""
        settings_obj = await self.get_or_create_document_settings(company_id)
        update_data = payload.model_dump(exclude_unset=True)

        for key, value in update_data.items():
            if hasattr(settings_obj, key):
                setattr(settings_obj, key, value)

        settings_obj.updated_by = user_id
        settings_obj.updated_at = datetime.now(timezone.utc)

        await _create_audit_entry(
            self.session,
            company_id=company_id,
            user_id=user_id,
            claims=claims,
            action="UPDATE_DOCUMENT_SETTINGS",
            details=f"Updated document settings: {list(update_data.keys())}",
        )

        await self.session.commit()
        await self.session.refresh(settings_obj)
        return settings_obj

    # ── 5. Asset Settings ──────────────────────────────────────────────────────

    async def get_or_create_asset_settings(self, company_id: uuid.UUID) -> AssetSettings:
        """Retrieve existing asset settings or instantiate default organization settings."""
        stmt = select(AssetSettings).where(AssetSettings.company_id == company_id)
        res = await self.session.execute(stmt)
        obj = res.scalar_one_or_none()
        if not obj:
            obj = AssetSettings(
                id=uuid.uuid4(),
                company_id=company_id,
                asset_id_prefix="AST",
                require_assignment_approval=True,
                enable_asset_return_tracking=True,
                enable_asset_condition_tracking=True,
                enable_warranty_reminders=True,
                warranty_reminder_days=30,
                enable_asset_depreciation=False,
            )
            self.session.add(obj)
            await self.session.commit()
            await self.session.refresh(obj)
        return obj

    async def update_asset_settings(
        self,
        company_id: uuid.UUID,
        payload: AssetSettingsUpdate,
        user_id: Optional[uuid.UUID] = None,
        claims: Optional[dict] = None,
    ) -> AssetSettings:
        """Update asset configuration without touching existing hardware records."""
        settings_obj = await self.get_or_create_asset_settings(company_id)
        update_data = payload.model_dump(exclude_unset=True)

        for key, value in update_data.items():
            if hasattr(settings_obj, key):
                setattr(settings_obj, key, value)

        settings_obj.updated_by = user_id
        settings_obj.updated_at = datetime.now(timezone.utc)

        await _create_audit_entry(
            self.session,
            company_id=company_id,
            user_id=user_id,
            claims=claims,
            action="UPDATE_ASSET_SETTINGS",
            details=f"Updated asset settings: {list(update_data.keys())}",
        )

        await self.session.commit()
        await self.session.refresh(settings_obj)
        return settings_obj
