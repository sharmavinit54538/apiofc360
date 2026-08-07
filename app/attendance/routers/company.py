"""Daily Face Attendance admin company view router."""

from __future__ import annotations

from typing import Annotated, Optional
import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.db.database import get_db_session
from app.core.rbac import require_admin
from app.schemas.auth import APIResponse
from app.attendance.schemas.response import AttendanceResponse
from app.attendance.schemas.history import AttendanceHistoryResponse
from app.attendance.services.history_service import AttendanceHistoryService

router = APIRouter()


def _get_company_id(claims: dict) -> uuid.UUID:
    company_id_str = claims.get("company_id")
    if not company_id_str:
        raise AppException(
            message="Company context missing in user authentication claims.",
            status_code=status.HTTP_403_FORBIDDEN,
        )
    return uuid.UUID(company_id_str)


@router.get(
    "/face/company",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[AttendanceHistoryResponse],
    summary="Retrieve company-wide paginated daily attendance logs history",
)
async def get_company_attendance_history(
    branch: Optional[str] = Query(None, description="Filter by employee branch"),
    department: Optional[str] = Query(None, description="Filter by employee department"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Records limit per page"),
    claims: Annotated[dict, Depends(require_admin)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[AttendanceHistoryResponse]:
    """Retrieve check-in logs for all employees across the company (Admin only)."""
    company_id = _get_company_id(claims)
    
    service = AttendanceHistoryService(db)
    items, total = await service.get_company_attendance(
        company_id=company_id,
        branch=branch,
        department=department,
        page=page,
        limit=limit,
    )
    
    serialized = [AttendanceResponse.model_validate(item) for item in items]
    data = AttendanceHistoryResponse(page=page, limit=limit, total=total, items=serialized)
    return APIResponse[AttendanceHistoryResponse](
        success=True,
        message="Company-wide attendance history logs retrieved.",
        data=data,
        errors=None,
    )
