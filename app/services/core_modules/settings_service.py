"""Settings service managing company configurations and master data."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core_modules import EmploymentType, Holiday
from app.models.onboarding import CompanySettings
from app.models.company import Company
from app.schemas.core_modules.settings import (
    CompanyConfigSectionUpdate,
    DesignationCreateRequest,
    EmploymentTypeCreateRequest,
    HolidayCreateRequest,
)

logger = logging.getLogger(__name__)


class SettingsService:
    """Service handling company settings sections and master data entities."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_or_create_company_settings(self, company_id: Optional[uuid.UUID]) -> CompanySettings:
        if not company_id:
            # Fallback mock/default settings instance
            stmt = select(CompanySettings).limit(1)
            res = await self.session.execute(stmt)
            inst = res.scalar_one_or_none()
            if inst:
                return inst
            inst = CompanySettings(
                id=uuid.uuid4(),
                timezone="Asia/Kolkata",
                currency="INR",
                date_format="DD/MM/YYYY",
                time_format="12h",
                financial_year="April-March",
                week_start_day="Monday",
                working_days=["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
                office_timing={"start": "09:30", "end": "18:30"},
            )
            self.session.add(inst)
            await self.session.commit()
            return inst

        stmt = select(CompanySettings).where(CompanySettings.company_id == company_id)
        res = await self.session.execute(stmt)
        settings_obj = res.scalar_one_or_none()
        if not settings_obj:
            settings_obj = CompanySettings(
                id=uuid.uuid4(),
                company_id=company_id,
                timezone="Asia/Kolkata",
                currency="INR",
                date_format="DD/MM/YYYY",
                time_format="12h",
                financial_year="April-March",
                week_start_day="Monday",
                working_days=["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
                office_timing={"start": "09:30", "end": "18:30"},
            )
            self.session.add(settings_obj)
            await self.session.commit()
            await self.session.refresh(settings_obj)
        return settings_obj

    async def get_all_settings(self, company_id: Optional[uuid.UUID]) -> Dict[str, Any]:
        s = await self.get_or_create_company_settings(company_id)
        return {
            "company_id": str(s.company_id) if s.company_id else None,
            "timezone": s.timezone,
            "currency": s.currency,
            "date_format": s.date_format,
            "time_format": s.time_format,
            "financial_year": s.financial_year,
            "week_start_day": s.week_start_day,
            "working_days": s.working_days,
            "office_timing": s.office_timing,
            "default_shift": s.default_shift,
            "leave_policy_template": s.leave_policy_template,
        }

    async def update_settings_section(
        self, company_id: Optional[uuid.UUID], section_name: str, payload: CompanyConfigSectionUpdate
    ) -> Dict[str, Any]:
        s = await self.get_or_create_company_settings(company_id)
        cfg = payload.config

        # Update specific fields if recognized, otherwise store generic
        if "timezone" in cfg:
            s.timezone = cfg["timezone"]
        if "currency" in cfg:
            s.currency = cfg["currency"]
        if "working_days" in cfg:
            s.working_days = cfg["working_days"]
        if "office_timing" in cfg:
            s.office_timing = cfg["office_timing"]

        await self.session.commit()
        return {"section": section_name, "updated": True, "config": cfg}

    # ── Master Data: Employment Types ──────────────────────────────────────────

    async def list_employment_types(self, company_id: Optional[uuid.UUID]) -> List[Dict[str, Any]]:
        stmt = select(EmploymentType)
        if company_id:
            stmt = stmt.where(EmploymentType.company_id == company_id)
        types = (await self.session.execute(stmt)).scalars().all()
        return [
            {
                "id": str(t.id),
                "name": t.name,
                "code": t.code,
                "description": t.description,
                "is_active": t.is_active,
            }
            for t in types
        ]

    async def create_employment_type(
        self, company_id: Optional[uuid.UUID], payload: EmploymentTypeCreateRequest
    ) -> EmploymentType:
        item = EmploymentType(
            id=uuid.uuid4(),
            company_id=company_id,
            name=payload.name,
            code=payload.code,
            description=payload.description,
            is_active=payload.is_active,
        )
        self.session.add(item)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    # ── Master Data: Designations ──────────────────────────────────────────────

    async def list_designations(
        self,
        company_id: Optional[uuid.UUID],
        *,
        search: Optional[str] = None,
        department_id: Optional[str] = None,
        page: int = 1,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        data = await self.list_designations_paginated(
            company_id,
            search=search,
            department_id=department_id,
            page=page,
            limit=limit,
        )
        return data["items"]

    async def list_designations_paginated(
        self,
        company_id: Optional[uuid.UUID],
        *,
        search: Optional[str] = None,
        department_id: Optional[str] = None,
        page: int = 1,
        limit: int = 100,
    ) -> Dict[str, Any]:
        from app.models.onboarding import Designation
        from sqlalchemy import or_

        stmt = select(Designation)
        if company_id is not None:
            stmt = stmt.where(or_(Designation.company_id == company_id, Designation.company_id.is_(None)))
        else:
            stmt = stmt.where(Designation.company_id.is_(None))
        if search and search.strip():
            escaped = search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            term = f"%{escaped}%"
            stmt = stmt.where(Designation.name.ilike(term, escape="\\"))

        total = int((await self.session.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0)
        offset = max(0, (page - 1) * limit)
        rows = (
            await self.session.execute(
                stmt.order_by(Designation.name.asc(), Designation.created_at.desc()).offset(offset).limit(limit)
            )
        ).scalars().all()
        items = [
            {
                "id": str(d.id),
                "name": d.name,
                "description": d.description,
                "department_id": department_id,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in rows
        ]
        return {"items": items, "total": total, "page": page, "limit": limit}

    async def get_designation(
        self, company_id: Optional[uuid.UUID], designation_id: uuid.UUID
    ) -> Optional[Dict[str, Any]]:
        from app.models.onboarding import Designation
        from sqlalchemy import or_

        stmt = select(Designation).where(Designation.id == designation_id)
        if company_id is not None:
            stmt = stmt.where(or_(Designation.company_id == company_id, Designation.company_id.is_(None)))
        d = (await self.session.execute(stmt)).scalar_one_or_none()
        if not d:
            return None
        return {
            "id": str(d.id),
            "name": d.name,
            "description": d.description,
            "created_at": d.created_at.isoformat() if d.created_at else None,
        }

    async def create_designation(
        self, company_id: Optional[uuid.UUID], payload: DesignationCreateRequest
    ) -> Dict[str, Any]:
        from app.models.onboarding import Designation

        clean_name = payload.name.strip()
        normalized = clean_name.lower()
        existing = (
            await self.session.execute(
                select(Designation).where(
                    Designation.company_id == company_id,
                    func.lower(Designation.name) == normalized,
                )
            )
        ).scalar_one_or_none()
        if existing:
            return {
                "id": str(existing.id),
                "name": existing.name,
                "description": existing.description,
                "created_at": existing.created_at.isoformat() if existing.created_at else None,
            }

        item = Designation(
            id=uuid.uuid4(),
            company_id=company_id,
            name=clean_name,
            normalized_name=normalized,
            description=payload.description,
        )
        self.session.add(item)
        await self.session.commit()
        await self.session.refresh(item)
        return {
            "id": str(item.id),
            "name": item.name,
            "description": item.description,
            "created_at": item.created_at.isoformat() if item.created_at else None,
        }

    # ── Master Data: Holidays ──────────────────────────────────────────────────

    async def list_holidays(self, company_id: Optional[uuid.UUID]) -> List[Dict[str, Any]]:
        stmt = select(Holiday)
        if company_id:
            stmt = stmt.where(Holiday.company_id == company_id)
        holidays = (await self.session.execute(stmt)).scalars().all()
        return [
            {
                "id": str(h.id),
                "name": h.name,
                "holiday_date": h.holiday_date.isoformat(),
                "type": h.type,
                "is_recurring": h.is_recurring,
                "description": h.description,
            }
            for h in holidays
        ]

    async def create_holiday(self, company_id: Optional[uuid.UUID], payload: HolidayCreateRequest) -> Holiday:
        item = Holiday(
            id=uuid.uuid4(),
            company_id=company_id,
            name=payload.name,
            holiday_date=payload.holiday_date,
            type=payload.type,
            is_recurring=payload.is_recurring,
            description=payload.description,
        )
        self.session.add(item)
        await self.session.commit()
        await self.session.refresh(item)
        return item
