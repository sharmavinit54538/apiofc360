"""Settings router for OFC360 / Aurix HRMS Core Modules."""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payroll.permissions import _require_admin, _require_admin_or_manager
from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.core_modules.settings import (
    CompanyConfigSectionUpdate,
    DesignationCreateRequest,
    EmploymentTypeCreateRequest,
    HolidayCreateRequest,
)
from app.services.core_modules.settings_service import SettingsService

router = APIRouter(prefix="/settings", tags=["Core - Settings"])


def _ok(data: Any, message: str = "Operation successful") -> Dict[str, Any]:
    return {"success": True, "data": data, "message": message}


def _get_cid(claims: dict) -> Optional[uuid.UUID]:
    cid = claims.get("company_id")
    try:
        return uuid.UUID(str(cid)) if cid else None
    except (ValueError, TypeError):
        return None


@router.get("/")
async def get_settings(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    cid = _get_cid(claims)
    srv = SettingsService(session)
    res = await srv.get_all_settings(cid)
    return _ok(res)


@router.put("/")
async def update_settings(
    payload: CompanyConfigSectionUpdate,
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    _require_admin(claims)
    cid = _get_cid(claims)
    srv = SettingsService(session)
    res = await srv.update_settings_section(cid, "general", payload)
    return _ok(res)


@router.get("/company")
@router.get("/profile")
@router.get("/attendance")
@router.get("/leave")
@router.get("/payroll")
@router.get("/security")
@router.get("/workflow")
async def get_settings_section(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    cid = _get_cid(claims)
    srv = SettingsService(session)
    res = await srv.get_all_settings(cid)
    return _ok(res)


@router.put("/company")
@router.put("/profile")
@router.put("/attendance")
@router.put("/leave")
@router.put("/payroll")
@router.put("/security")
@router.put("/workflow")
async def update_settings_section_endpoint(
    payload: CompanyConfigSectionUpdate,
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    _require_admin(claims)
    cid = _get_cid(claims)
    srv = SettingsService(session)
    res = await srv.update_settings_section(cid, "section", payload)
    return _ok(res)


# ── Master Data: Employment Types ──────────────────────────────────────────

@router.get("/employment-types")
async def list_employment_types(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    cid = _get_cid(claims)
    srv = SettingsService(session)
    items = await srv.list_employment_types(cid)
    return _ok(items)


@router.post("/employment-types")
async def create_employment_type(
    payload: EmploymentTypeCreateRequest,
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    _require_admin(claims)
    cid = _get_cid(claims)
    srv = SettingsService(session)
    res = await srv.create_employment_type(cid, payload)
    return _ok({"id": str(res.id), "name": res.name, "code": res.code})


# ── Master Data: Designations ──────────────────────────────────────────────

@router.get("/designations")
async def list_designations(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    cid = _get_cid(claims)
    srv = SettingsService(session)
    items = await srv.list_designations(cid)
    return _ok(items)


@router.post("/designations")
async def create_designation(
    payload: DesignationCreateRequest,
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    _require_admin(claims)
    cid = _get_cid(claims)
    srv = SettingsService(session)
    res = await srv.create_designation(cid, payload)
    return _ok(res)


# ── Master Data: Holidays ──────────────────────────────────────────────────

@router.get("/holidays")
async def list_holidays(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    cid = _get_cid(claims)
    srv = SettingsService(session)
    items = await srv.list_holidays(cid)
    return _ok(items)


@router.post("/holidays")
async def create_holiday(
    payload: HolidayCreateRequest,
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    _require_admin(claims)
    cid = _get_cid(claims)
    srv = SettingsService(session)
    res = await srv.create_holiday(cid, payload)
    return _ok({"id": str(res.id), "name": res.name, "holiday_date": res.holiday_date.isoformat()})
