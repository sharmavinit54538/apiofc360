"""Daily Face Attendance personal and filtered history router."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.attendance.schemas.response import AttendanceResponse
from app.attendance.schemas.history import AttendanceHistoryResponse
from app.attendance.services.history_service import AttendanceHistoryService

router = APIRouter()


def _get_user_id(claims: dict) -> uuid.UUID:
    return uuid.UUID(claims.get("sub"))


def _get_company_id(claims: dict) -> Optional[uuid.UUID]:
    cid = claims.get("company_id")
    return uuid.UUID(str(cid)) if cid else None


def _get_user_role(claims: dict) -> str:
    return str(claims.get("role", "")).upper()


@router.get(
    "/face/history",
    status_code=status.HTTP_200_OK,
    summary="Retrieve paginated daily attendance logs history with date and employee filtering",
)
async def get_attendance_history(
    start_date: Optional[date] = Query(None, description="Start date filter (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, description="End date filter (YYYY-MM-DD)"),
    employee_id: Optional[uuid.UUID] = Query(None, description="Employee ID filter (Admins/Managers only)"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Records limit per page"),
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> dict:
    """Retrieve historical daily check-in log records with date range and employee filters."""
    user_id = _get_user_id(claims)
    company_id = _get_company_id(claims)
    user_role = _get_user_role(claims)
    service = AttendanceHistoryService(db)

    # If employee_id is requested, verify the caller has permissions to view other employees
    if employee_id:
        is_admin_or_mgr = any(r in user_role for r in ("ADMIN", "HR_ADMIN", "MANAGER", "SUPER_ADMIN"))
        if not is_admin_or_mgr:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "FORBIDDEN", "message": "You are not authorized to view other employees' attendance."},
            )
        if not company_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "COMPANY_CONTEXT_MISSING", "message": "Company context is required."},
            )
        items, total = await service.get_company_attendance(
            company_id=company_id,
            employee_id=employee_id,
            start_date=start_date,
            end_date=end_date,
            page=page,
            limit=limit,
        )
    else:
        items, total = await service.get_own_history(
            user_id,
            page=page,
            limit=limit,
            start_date=start_date,
            end_date=end_date,
        )

    serialized = [AttendanceResponse.model_validate(item).model_dump(mode="json") for item in items]
    data = {
        "page": page,
        "limit": limit,
        "total": total,
        "items": serialized,
    }

    return {
        "success": True,
        "message": "Attendance history logs retrieved.",
        "data": data,
        "error": None,
    }
