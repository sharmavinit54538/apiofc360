"""Departments router for OFC360 / Aurix HRMS Core Modules."""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payroll.permissions import _require_admin
from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.core_modules.departments import DepartmentCreateRequest, DepartmentUpdateRequest
from app.services.core_modules.department_service import DepartmentCoreService

router = APIRouter(prefix="/departments", tags=["Core - Departments"])


def _ok(data: Any, message: str = "Operation successful") -> Dict[str, Any]:
    return {"success": True, "data": data, "message": message}


def _get_cid(claims: dict) -> Optional[uuid.UUID]:
    cid = claims.get("company_id")
    try:
        return uuid.UUID(str(cid)) if cid else None
    except (ValueError, TypeError):
        return None


@router.get("")
@router.get("/")
async def list_departments(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
    parent_id: Optional[uuid.UUID] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
):
    cid = _get_cid(claims)
    srv = DepartmentCoreService(session)
    res = await srv.list_departments(company_id=cid, parent_id=parent_id, page=page, limit=limit)
    return _ok(res)


@router.post("")
@router.post("/")
async def create_department(
    payload: DepartmentCreateRequest,
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    _require_admin(claims)
    cid = _get_cid(claims)
    srv = DepartmentCoreService(session)
    dept = await srv.create_department(cid, payload)
    return _ok({
        "id": str(dept.id),
        "department_name": dept.department_name,
        "department_code": dept.department_code,
    })


@router.get("/{id}")
async def get_department(
    id: uuid.UUID,
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    srv = DepartmentCoreService(session)
    dept = await srv.get_department(id)
    if not dept:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Department not found")
    return _ok({
        "id": str(dept.id),
        "department_name": dept.department_name,
        "department_code": dept.department_code,
        "description": dept.description,
        "parent_department_id": str(dept.parent_department_id) if dept.parent_department_id else None,
        "location": dept.location,
        "status": dept.status,
    })


@router.put("/{id}")
@router.patch("/{id}")
async def update_department(
    id: uuid.UUID,
    payload: DepartmentUpdateRequest,
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    _require_admin(claims)
    srv = DepartmentCoreService(session)
    dept = await srv.update_department(id, payload)
    return _ok({
        "id": str(dept.id),
        "department_name": dept.department_name,
        "status": dept.status,
        "updated": True,
    })


@router.delete("/{id}")
async def delete_department(
    id: uuid.UUID,
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    _require_admin(claims)
    srv = DepartmentCoreService(session)
    deleted = await srv.delete_department(id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Department not found")
    return _ok({"id": str(id), "deleted": True, "message": "Department soft-deleted successfully"})


@router.get("/{id}/employees")
async def get_department_employees(
    id: uuid.UUID,
    includeSubDepartments: bool = Query(False),
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
):
    srv = DepartmentCoreService(session)
    res = await srv.get_department_employees(
        department_id=id, include_sub_departments=includeSubDepartments, page=page, limit=limit
    )
    return _ok(res)
