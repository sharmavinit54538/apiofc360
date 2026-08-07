"""Export API endpoints for different HRMS modules.

Requires authentication, role-based authorization, and company scoping.
"""

from __future__ import annotations

import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response, status, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.services.export_service import ExportService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/exports", tags=["Exports"])


def require_export_permission(
    claims: Annotated[dict, Depends(get_current_user_claims)]
) -> dict:
    """Ensure that only authorized roles can export data (admin, super_admin, hr_manager)."""
    role = claims.get("role", "").lower()
    # Check if user has permission to export
    if role not in {"admin", "super_admin", "hr_manager"}:
        logger.warning("Unauthorized export attempt | role=%s | user_id=%s", role, claims.get("sub"))
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only ADMIN, SUPER_ADMIN, or HR_MANAGER can export reports.",
        )
    return claims


def _get_company_id(claims: dict) -> uuid.UUID:
    """Extract and validate company_id from JWT claims."""
    company_id_str = claims.get("company_id")
    if not company_id_str:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Company scope missing from credentials.",
        )
    try:
        return uuid.UUID(company_id_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid company ID format in credentials.",
        )


def _get_user_id(claims: dict) -> uuid.UUID:
    """Extract and validate user_id from JWT claims."""
    user_id_str = claims.get("sub")
    if not user_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User identity missing from credentials.",
        )
    try:
        return uuid.UUID(user_id_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user ID format in credentials.",
        )


async def _run_export(
    request: Request,
    module: str,
    format: str,
    filters: dict[str, Any],
    claims: dict,
    session: AsyncSession
) -> Response:
    """Helper method to run the export service and format response."""
    user_id = _get_user_id(claims)
    company_id = _get_company_id(claims)
    
    service = ExportService(session)
    content, filename, media_type = await service.export_module(
        user_id=user_id,
        company_id=company_id,
        module=module,
        filters=filters,
        fmt=format,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Access-Control-Expose-Headers": "Content-Disposition"
        }
    )


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.get("/employees")
async def export_employees(
    request: Request,
    format: str = Query("xlsx", description="xlsx, csv, or pdf"),
    search: str | None = Query(None),
    status: str | None = Query(None),
    department: str | None = Query(None),
    designation: str | None = Query(None),
    employee_type: str | None = Query(None),
    claims: Annotated[dict, Depends(require_export_permission)] = None,
    session: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> Response:
    filters = {
        "search": search,
        "status": status,
        "department": department,
        "designation": designation,
        "employee_type": employee_type,
    }
    return await _run_export(request, "employees", format, filters, claims, session)


@router.get("/departments")
async def export_departments(
    request: Request,
    format: str = Query("xlsx", description="xlsx, csv, or pdf"),
    search: str | None = Query(None),
    status: str | None = Query(None),
    claims: Annotated[dict, Depends(require_export_permission)] = None,
    session: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> Response:
    filters = {
        "search": search,
        "status": status,
    }
    return await _run_export(request, "departments", format, filters, claims, session)


@router.get("/managers")
async def export_managers(
    request: Request,
    format: str = Query("xlsx", description="xlsx, csv, or pdf"),
    search: str | None = Query(None),
    status: str | None = Query(None),
    department: str | None = Query(None),
    claims: Annotated[dict, Depends(require_export_permission)] = None,
    session: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> Response:
    filters = {
        "search": search,
        "status": status,
        "department": department,
    }
    return await _run_export(request, "managers", format, filters, claims, session)


@router.get("/attendance")
async def export_attendance(
    request: Request,
    format: str = Query("xlsx", description="xlsx, csv, or pdf"),
    search: str | None = Query(None),
    date_from: str | None = Query(None),
    claims: Annotated[dict, Depends(require_export_permission)] = None,
    session: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> Response:
    filters = {
        "search": search,
        "date_from": date_from,
    }
    return await _run_export(request, "attendance", format, filters, claims, session)


@router.get("/face-attendance")
async def export_face_attendance(
    request: Request,
    format: str = Query("xlsx", description="xlsx, csv, or pdf"),
    search: str | None = Query(None),
    date_from: str | None = Query(None),
    branch: str | None = Query(None),
    department: str | None = Query(None),
    claims: Annotated[dict, Depends(require_export_permission)] = None,
    session: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> Response:
    filters = {
        "search": search,
        "date_from": date_from,
        "branch": branch,
        "department": department,
    }
    return await _run_export(request, "face_attendance", format, filters, claims, session)


@router.get("/leaves")
async def export_leaves(
    request: Request,
    format: str = Query("xlsx", description="xlsx, csv, or pdf"),
    search: str | None = Query(None),
    status: str | None = Query(None, description="Leave type filter"),
    claims: Annotated[dict, Depends(require_export_permission)] = None,
    session: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> Response:
    filters = {
        "search": search,
        "status": status,
    }
    return await _run_export(request, "leaves", format, filters, claims, session)


@router.get("/payroll")
async def export_payroll(
    request: Request,
    format: str = Query("xlsx", description="xlsx, csv, or pdf"),
    search: str | None = Query(None),
    status: str | None = Query(None, description="Payment status filter"),
    claims: Annotated[dict, Depends(require_export_permission)] = None,
    session: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> Response:
    filters = {
        "search": search,
        "status": status,
    }
    return await _run_export(request, "payroll", format, filters, claims, session)


@router.get("/performance")
async def export_performance(
    request: Request,
    format: str = Query("xlsx", description="xlsx, csv, or pdf"),
    search: str | None = Query(None),
    status: str | None = Query(None, description="Review status filter"),
    claims: Annotated[dict, Depends(require_export_permission)] = None,
    session: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> Response:
    filters = {
        "search": search,
        "status": status,
    }
    return await _run_export(request, "performance", format, filters, claims, session)
