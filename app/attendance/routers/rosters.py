"""Roster API Routes."""

from __future__ import annotations

import uuid
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance.schemas.shift import (
    RosterEntryCreate,
    RosterEntryResponse,
    RosterEntryUpdate,
    RosterListResponse,
)
from app.attendance.services.roster_service import RosterService
from app.core.rbac import require_admin_or_manager
from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.auth import APIResponse

router = APIRouter()


@router.get(
    "/rosters",
    response_model=APIResponse[RosterListResponse],
    summary="List roster entries (admin/manager)",
    dependencies=[Depends(require_admin_or_manager)],
)
async def list_rosters(
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    department: Optional[str] = Query(None),
    employee_id: Optional[uuid.UUID] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
):
    company_id = uuid.UUID(claims["company_id"])
    service = RosterService(db)
    items, total = await service.list_entries(
        company_id,
        date_from=date_from,
        date_to=date_to,
        department=department,
        employee_id=employee_id,
        page=page,
        limit=limit,
    )
    return APIResponse(
        success=True,
        message="Roster entries retrieved.",
        data=RosterListResponse(items=items, total=total, page=page, limit=limit),
    )


@router.post(
    "/rosters",
    response_model=APIResponse[RosterEntryResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Create roster entry (admin/manager)",
    dependencies=[Depends(require_admin_or_manager)],
)
async def create_roster_entry(
    body: RosterEntryCreate,
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
):
    company_id = uuid.UUID(claims["company_id"])
    service = RosterService(db)
    try:
        entry = await service.create_entry(
            company_id=company_id,
            employee_id=body.employee_id,
            entry_date=body.date,
            shift_id=body.shift_id,
            shift_type=body.shift_type,
            start_time=body.start_time,
            end_time=body.end_time,
            working_hours=body.working_hours,
            break_time=body.break_time,
            location=body.location,
            status=body.status,
            notes=body.notes,
        )
    except ValueError as e:
        if "already exists" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "DUPLICATE_ENTRY", "message": "Roster entry already exists for this employee on this date."},
            )
        if "not found" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "NOT_FOUND", "message": str(e)},
            )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"code": "INVALID_REQUEST", "message": str(e)})

    # Build response with derived fields
    # For now return minimal response
    return APIResponse(
        success=True,
        message="Roster entry created.",
        data=RosterEntryResponse(
            id=entry.id,
            employee_id=entry.employee_id,
            employee_name="",  # Would need to fetch
            department="",
            designation="",
            date=entry.shift_date,
            shift="",
            shift_id=entry.shift_id,
            start_time=entry.start_time.strftime("%H:%M") if entry.start_time else None,
            end_time=entry.end_time.strftime("%H:%M") if entry.end_time else None,
            working_hours=None,
            break_time=None,
            location=None,
            manager=None,
            status=entry.approval_status.value.title(),
            created_at=entry.created_at if hasattr(entry, 'created_at') else None,
            updated_at=entry.updated_at if hasattr(entry, 'updated_at') else None,
        ),
    )


@router.get(
    "/rosters/{roster_id}",
    response_model=APIResponse[RosterEntryResponse],
    summary="Get roster entry by ID (admin/manager)",
    dependencies=[Depends(require_admin_or_manager)],
)
async def get_roster_entry(
    roster_id: uuid.UUID,
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
):
    company_id = uuid.UUID(claims["company_id"])
    from app.models.shift_plan import ShiftPlanEntry
    from sqlalchemy import select

    stmt = select(ShiftPlanEntry).where(
        and_(ShiftPlanEntry.id == roster_id, ShiftPlanEntry.company_id == company_id)
    )
    result = await db.execute(stmt)
    entry = result.scalars().first()
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "Roster entry not found."},
        )

    # Fetch employee for derived fields
    from app.models.employee import Employee
    emp_stmt = select(Employee).where(Employee.id == entry.employee_id)
    emp_result = await db.execute(emp_stmt)
    employee = emp_result.scalars().first()

    # Get shift name
    shift_name = entry.shift_type.value
    if entry.shift_id:
        from app.models.shift import Shift
        shift_stmt = select(Shift).where(Shift.id == entry.shift_id)
        shift_result = await db.execute(shift_stmt)
        shift = shift_result.scalars().first()
        if shift:
            shift_name = shift.name

    # Get manager
    manager_name = None
    if employee and employee.manager_id:
        mgr_stmt = select(Employee).where(Employee.id == employee.manager_id)
        mgr_result = await db.execute(mgr_stmt)
        mgr = mgr_result.scalars().first()
        if mgr:
            manager_name = f"{mgr.first_name} {mgr.last_name}"

    return APIResponse(
        success=True,
        message="Roster entry retrieved.",
        data=RosterEntryResponse(
            id=entry.id,
            employee_id=entry.employee_id,
            employee_name=f"{employee.first_name} {employee.last_name}" if employee else "",
            department=employee.department if employee else "",
            designation=employee.designation if employee else "",
            date=entry.shift_date,
            shift=shift_name,
            shift_id=entry.shift_id,
            start_time=entry.start_time.strftime("%H:%M") if entry.start_time else None,
            end_time=entry.end_time.strftime("%H:%M") if entry.end_time else None,
            working_hours=None,
            break_time=None,
            location=None,
            manager=manager_name,
            status=entry.approval_status.value.title(),
            created_at=entry.created_at if hasattr(entry, 'created_at') else None,
            updated_at=entry.updated_at if hasattr(entry, 'updated_at') else None,
        ),
    )


@router.put(
    "/rosters/{roster_id}",
    response_model=APIResponse[RosterEntryResponse],
    summary="Update roster entry (admin/manager)",
    dependencies=[Depends(require_admin_or_manager)],
)
async def update_roster_entry(
    roster_id: uuid.UUID,
    body: RosterEntryUpdate,
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
):
    company_id = uuid.UUID(claims["company_id"])
    service = RosterService(db)
    try:
        entry = await service.update_entry(
            entry_id=roster_id,
            company_id=company_id,
            shift_id=body.shift_id,
            shift_type=body.shift_type,
            start_time=body.start_time,
            end_time=body.end_time,
            working_hours=body.working_hours,
            break_time=body.break_time,
            location=body.location,
            status=body.status,
            notes=body.notes,
        )
    except ValueError as e:
        if "not found" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "NOT_FOUND", "message": "Roster entry not found."},
            )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"code": "INVALID_REQUEST", "message": str(e)})

    return APIResponse(
        success=True,
        message="Roster entry updated.",
        data=RosterEntryResponse(
            id=entry.id,
            employee_id=entry.employee_id,
            employee_name="",
            department="",
            designation="",
            date=entry.shift_date,
            shift="",
            shift_id=entry.shift_id,
            start_time=entry.start_time.strftime("%H:%M") if entry.start_time else None,
            end_time=entry.end_time.strftime("%H:%M") if entry.end_time else None,
            working_hours=None,
            break_time=None,
            location=None,
            manager=None,
            status=entry.approval_status.value.title(),
            created_at=entry.created_at if hasattr(entry, 'created_at') else None,
            updated_at=entry.updated_at if hasattr(entry, 'updated_at') else None,
        ),
    )


@router.delete(
    "/rosters/{roster_id}",
    response_model=APIResponse[dict],
    summary="Delete roster entry (admin/manager)",
    dependencies=[Depends(require_admin_or_manager)],
)
async def delete_roster_entry(
    roster_id: uuid.UUID,
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session),
):
    company_id = uuid.UUID(claims["company_id"])
    service = RosterService(db)
    try:
        await service.delete_entry(roster_id, company_id)
    except ValueError as e:
        if "not found" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "NOT_FOUND", "message": "Roster entry not found."},
            )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"code": "INVALID_REQUEST", "message": str(e)})

    return APIResponse(
        success=True,
        message="Roster entry deleted.",
        data={"deleted": True},
    )