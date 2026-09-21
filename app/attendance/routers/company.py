"""Daily Face Attendance admin company view router."""

from __future__ import annotations

from datetime import date
import logging
from typing import Annotated, Optional
import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance.schemas.response import AttendanceResponse
from app.attendance.services.history_service import AttendanceHistoryService
from app.core.exceptions import AppException
from app.core.rbac import require_admin
from app.db.database import get_db_session

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_company_id(claims: dict) -> uuid.UUID:
    company_id_val = claims.get("company_id") if isinstance(claims, dict) else None
    if not company_id_val:
        logger.warning(
            "Attendance Face Company: missing company_id in claims | user_id=%s",
            claims.get("sub") if isinstance(claims, dict) else None,
        )
        raise AppException(
            message="Company context missing in user authentication claims.",
            status_code=status.HTTP_403_FORBIDDEN,
        )
    return uuid.UUID(str(company_id_val))


@router.get(
    "/face/company",
    status_code=status.HTTP_200_OK,
    summary="Retrieve company-wide paginated daily attendance logs history",
)
async def get_company_attendance_history(
    branch: Optional[str] = Query(None, description="Filter by employee branch"),
    department: Optional[str] = Query(None, description="Filter by employee department"),
    employee_id: Optional[uuid.UUID] = Query(None, description="Filter by specific employee ID"),
    start_date: Optional[date] = Query(None, description="Start date filter (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, description="End date filter (YYYY-MM-DD)"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Records limit per page"),
    claims: Annotated[dict, Depends(require_admin)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> dict:
    """Retrieve check-in logs for all employees across the company (Admin only)."""
    company_id = _get_company_id(claims)

    service = AttendanceHistoryService(db)
    items, total = await service.get_company_attendance(
        company_id=company_id,
        branch=branch,
        department=department,
        employee_id=employee_id,
        start_date=start_date,
        end_date=end_date,
        page=page,
        limit=limit,
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
        "message": "Company-wide attendance history logs retrieved.",
        "data": data,
        "error": None,
    }
