"""Shift Management API Routes."""

from __future__ import annotations

import uuid
from datetime import datetime, time, timezone
from typing import Annotated, Any, List, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance.services.shift_management_service import ShiftManagementService
from app.core.exceptions import AppException
from app.core.rbac import require_admin, require_admin_or_manager
from app.db.database import get_db_session
from app.models.employee import Employee
from app.models.shift import Shift
from app.schemas.auth import APIResponse

router = APIRouter()


def _get_company_id(claims: dict) -> uuid.UUID:
    company_id_str = claims.get("company_id")
    if not company_id_str:
        raise AppException(
            message="Company context missing in user authentication claims.",
            status_code=status.HTTP_403_FORBIDDEN,
        )
    return uuid.UUID(company_id_str)


def _to_time(val: Any) -> Optional[time]:
    """Safely convert value to datetime.time, or return None."""
    if val is None:
        return None
    if isinstance(val, time):
        return val
    if isinstance(val, datetime):
        return val.time()
    if isinstance(val, str):
        val_str = val.strip()
        if not val_str:
            return None
        for fmt in ("%H:%M:%S", "%H:%M", "%I:%M %p", "%I:%M%p"):
            try:
                return datetime.strptime(val_str, fmt).time()
            except ValueError:
                continue
        try:
            return time.fromisoformat(val_str)
        except (ValueError, TypeError):
            pass
        return None
    return None


def _parse_time_str(time_str: str) -> time:
    """Parse time string in HH:MM, H:MM, or HH:MM AM/PM format and return time object."""
    parsed = _to_time(time_str)
    if parsed is not None:
        return parsed
    raise ValueError(f"Invalid time format: {time_str}. Use HH:MM (24-hour) format.")


def _format_time(time_obj: Any) -> str:
    """Format time object or string as HH:MM string."""
    if time_obj is None:
        return ""
    if isinstance(time_obj, time):
        return time_obj.strftime("%H:%M")
    parsed = _to_time(time_obj)
    if parsed is not None:
        return parsed.strftime("%H:%M")
    if isinstance(time_obj, str):
        val_str = time_obj.strip()
        return val_str[:5] if len(val_str) >= 5 else val_str
    return ""


def _calculate_duration_hours(start_time: Any, end_time: Any) -> float:
    """Calculate shift duration in hours."""
    st = _to_time(start_time)
    et = _to_time(end_time)
    if st is None or et is None:
        return 0.0
    start_minutes = st.hour * 60 + st.minute
    end_minutes = et.hour * 60 + et.minute
    if end_minutes <= start_minutes:
        end_minutes += 24 * 60
    return round((end_minutes - start_minutes) / 60.0, 2)


# Static routes MUST come before /{shift_id} to avoid path capture

@router.get(
    "/shifts/options",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Get active shifts for dropdown (Admin and Managers)",
    dependencies=[Depends(require_admin_or_manager)],
)
async def get_shifts_options(
    claims: Annotated[dict, Depends(require_admin_or_manager)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Get active shifts formatted for dropdown selection."""
    company_id = _get_company_id(claims)
    service = ShiftManagementService(db)
    shifts = await service.get_active_shifts_options(company_id)

    options = []
    for s in shifts:
        label = f"{s.name} ({_format_time(s.start_time)} - {_format_time(s.end_time)})"
        options.append({
            "id": str(s.id),
            "value": s.name,
            "label": label,
            "name": s.name,
            "start_time": _format_time(s.start_time),
            "end_time": _format_time(s.end_time),
        })

    return APIResponse[dict](
        success=True,
        message="Active shifts retrieved.",
        data={"options": options},
        errors=None,
    )


@router.get(
    "/shifts",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="List shifts with pagination and filters (Admin and Managers)",
    dependencies=[Depends(require_admin_or_manager)],
)
async def list_shifts(
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    claims: Annotated[dict, Depends(require_admin_or_manager)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """List shifts with pagination. employee_count computed via single grouped query."""
    company_id = _get_company_id(claims)
    service = ShiftManagementService(db)
    shifts, total = await service.list_shifts(company_id, search=search, page=page, limit=limit)

    # Get employee counts for all shifts in one query
    shift_ids = [s.id for s in shifts]
    employee_counts = {}
    if shift_ids:
        # Count active, non-deleted employees per shift name (case-insensitive)
        stmt = (
            select(Employee.shift, func.count(Employee.id))
            .where(
                and_(
                    Employee.company_id == company_id,
                    Employee.is_deleted == False,
                    Employee.status == "ACTIVE",
                    Employee.shift.isnot(None),
                )
            )
            .group_by(Employee.shift)
        )
        result = await db.execute(stmt)
        for shift_name, count in result.all():
            employee_counts[shift_name.lower()] = count

    items = []
    for s in shifts:
        emp_count = employee_counts.get(s.name.lower(), 0)
        duration_hours = _calculate_duration_hours(s.start_time, s.end_time)
        items.append({
            "id": str(s.id),
            "name": s.name,
            "start_time": _format_time(s.start_time),
            "end_time": _format_time(s.end_time),
            "is_overnight": s.is_overnight,
            "duration_hours": duration_hours,
            "employee_count": emp_count,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        })

    return APIResponse[dict](
        success=True,
        message="Shifts retrieved.",
        data={"page": page, "limit": limit, "total": total, "items": items},
        errors=None,
    )


@router.post(
    "/shifts",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[dict],
    summary="Create a new shift (Admin)",
    dependencies=[Depends(require_admin)],
)
async def create_shift(
    body: dict,
    claims: Annotated[dict, Depends(require_admin)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Create a new shift. Body: name (1-50 chars), start_time, end_time (HH:MM)."""
    company_id = _get_company_id(claims)
    user_id = uuid.UUID(claims["sub"])

    name = (body.get("name") or "").strip()
    start_time_str = body.get("start_time")
    end_time_str = body.get("end_time")

    if not name or len(name) > 50:
        raise AppException(
            message="Shift name must be 1-50 characters.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    if not start_time_str or not end_time_str:
        raise AppException(
            message="start_time and end_time are required (HH:MM format).",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        start_time = _parse_time_str(start_time_str)
        end_time = _parse_time_str(end_time_str)
    except ValueError as e:
        raise AppException(message=str(e), status_code=status.HTTP_400_BAD_REQUEST)

    if start_time == end_time:
        raise AppException(
            message="start_time must be different from end_time.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    service = ShiftManagementService(db)

    # Check for duplicate name (case-insensitive)
    existing = await db.execute(
        select(Shift).where(
            and_(
                Shift.company_id == company_id,
                Shift.deleted_at.is_(None),
                func.lower(Shift.name) == name.lower(),
            )
        )
    )
    if existing.scalars().first():
        raise AppException(
            message="A shift with this name already exists.",
            status_code=status.HTTP_409_CONFLICT,
        )

    # Generate code from name
    code = name.upper().replace(" ", "_")[:20]
    code_base = code
    counter = 1
    while True:
        code_check = await db.execute(
            select(Shift).where(
                and_(Shift.company_id == company_id, Shift.code == code, Shift.deleted_at.is_(None))
            )
        )
        if not code_check.scalars().first():
            break
        code = f"{code_base}_{counter}"
        counter += 1

    is_overnight = end_time < start_time
    duration_minutes = (24 * 60 - start_time.hour * 60 - start_time.minute + end_time.hour * 60 + end_time.minute) if is_overnight else (end_time.hour * 60 + end_time.minute - start_time.hour * 60 - start_time.minute)
    work_hours = round(max(0, duration_minutes - 60) / 60.0, 2)  # minus default break

    shift = Shift(
        company_id=company_id,
        name=name,
        code=code,
        start_time=start_time,
        end_time=end_time,
        is_overnight=is_overnight,
        duration_minutes=duration_minutes,
        work_hours=work_hours,
        is_active=True,
    )
    db.add(shift)
    await db.commit()
    await db.refresh(shift)

    return APIResponse[dict](
        success=True,
        message="Shift created.",
        data={
            "id": str(shift.id),
            "name": shift.name,
            "start_time": _format_time(shift.start_time),
            "end_time": _format_time(shift.end_time),
            "is_overnight": shift.is_overnight,
            "duration_hours": _calculate_duration_hours(shift.start_time, shift.end_time),
            "employee_count": 0,
            "created_at": shift.created_at.isoformat() if shift.created_at else None,
        },
        errors=None,
    )


@router.get(
    "/shifts/{shift_id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Get shift by ID (Admin and Managers)",
    dependencies=[Depends(require_admin_or_manager)],
)
async def get_shift(
    shift_id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin_or_manager)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Get shift by ID."""
    company_id = _get_company_id(claims)
    service = ShiftManagementService(db)
    shift = await service.get_shift(shift_id, company_id)
    if not shift:
        raise AppException(message="Shift not found.", status_code=status.HTTP_404_NOT_FOUND)

    # Get employee count
    emp_count_result = await db.execute(
        select(func.count(Employee.id)).where(
            and_(
                Employee.company_id == company_id,
                Employee.is_deleted == False,
                Employee.status == "ACTIVE",
                func.lower(Employee.shift) == shift.name.lower(),
            )
        )
    )
    emp_count = emp_count_result.scalar() or 0

    return APIResponse[dict](
        success=True,
        message="Shift retrieved.",
        data={
            "id": str(shift.id),
            "name": shift.name,
            "start_time": _format_time(shift.start_time),
            "end_time": _format_time(shift.end_time),
            "is_overnight": shift.is_overnight,
            "duration_hours": _calculate_duration_hours(shift.start_time, shift.end_time),
            "employee_count": emp_count,
            "created_at": shift.created_at.isoformat() if shift.created_at else None,
        },
        errors=None,
    )


@router.put(
    "/shifts/{shift_id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Update shift (Admin)",
    dependencies=[Depends(require_admin)],
)
async def update_shift(
    shift_id: uuid.UUID,
    body: dict,
    claims: Annotated[dict, Depends(require_admin)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Update shift (partial). On rename, also update Employee.shift for employees with old name."""
    company_id = _get_company_id(claims)
    service = ShiftManagementService(db)
    shift = await service.get_shift(shift_id, company_id)
    if not shift:
        raise AppException(message="Shift not found.", status_code=status.HTTP_404_NOT_FOUND)

    old_name = shift.name
    name_changed = False

    if "name" in body and body["name"] is not None:
        new_name = body["name"].strip()
        if not new_name or len(new_name) > 50:
            raise AppException(message="Shift name must be 1-50 characters.", status_code=status.HTTP_400_BAD_REQUEST)
        if new_name.lower() != old_name.lower():
            # Check duplicate
            existing = await db.execute(
                select(Shift).where(
                    and_(
                        Shift.company_id == company_id,
                        Shift.deleted_at.is_(None),
                        Shift.id != shift_id,
                        func.lower(Shift.name) == new_name.lower(),
                    )
                )
            )
            if existing.scalars().first():
                raise AppException(message="A shift with this name already exists.", status_code=status.HTTP_409_CONFLICT)
            shift.name = new_name
            name_changed = True

    if "start_time" in body and body["start_time"] is not None:
        try:
            shift.start_time = _parse_time_str(body["start_time"])
        except ValueError as e:
            raise AppException(message=str(e), status_code=status.HTTP_400_BAD_REQUEST)

    if "end_time" in body and body["end_time"] is not None:
        try:
            shift.end_time = _parse_time_str(body["end_time"])
        except ValueError as e:
            raise AppException(message=str(e), status_code=status.HTTP_400_BAD_REQUEST)

    # Recalculate derived fields if times changed
    if "start_time" in body or "end_time" in body:
        st = _to_time(shift.start_time)
        et = _to_time(shift.end_time)
        if st and et:
            shift.is_overnight = et < st
            start_min = st.hour * 60 + st.minute
            end_min = et.hour * 60 + et.minute
            if end_min <= start_min:
                end_min += 24 * 60
            shift.duration_minutes = end_min - start_min
            shift.work_hours = round(max(0, shift.duration_minutes - shift.break_duration_minutes) / 60.0, 2)

    shift.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(shift)

    # If name changed, update Employee.shift for employees with old name
    if name_changed:
        await db.execute(
            Employee.__table__.update()
            .where(
                and_(
                    Employee.company_id == company_id,
                    Employee.is_deleted == False,
                    func.lower(Employee.shift) == old_name.lower(),
                )
            )
            .values(shift=shift.name)
        )
        await db.commit()

    # Get updated employee count
    emp_count_result = await db.execute(
        select(func.count(Employee.id)).where(
            and_(
                Employee.company_id == company_id,
                Employee.is_deleted == False,
                Employee.status == "ACTIVE",
                func.lower(Employee.shift) == shift.name.lower(),
            )
        )
    )
    emp_count = emp_count_result.scalar() or 0

    return APIResponse[dict](
        success=True,
        message="Shift updated.",
        data={
            "id": str(shift.id),
            "name": shift.name,
            "start_time": _format_time(shift.start_time),
            "end_time": _format_time(shift.end_time),
            "is_overnight": shift.is_overnight,
            "duration_hours": _calculate_duration_hours(shift.start_time, shift.end_time),
            "employee_count": emp_count,
            "created_at": shift.created_at.isoformat() if shift.created_at else None,
        },
        errors=None,
    )


@router.patch(
    "/shifts/{shift_id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Partially update shift (Admin)",
    dependencies=[Depends(require_admin)],
)
async def patch_shift(
    shift_id: uuid.UUID,
    body: dict,
    claims: Annotated[dict, Depends(require_admin)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Partially update shift. Same as PUT."""
    return await update_shift(shift_id, body, claims, db)


@router.delete(
    "/shifts/{shift_id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Delete shift (Admin)",
    dependencies=[Depends(require_admin)],
)
async def delete_shift(
    shift_id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Soft delete shift. Returns 409 if any employee is assigned."""
    company_id = _get_company_id(claims)
    service = ShiftManagementService(db)
    shift = await service.get_shift(shift_id, company_id)
    if not shift:
        raise AppException(message="Shift not found.", status_code=status.HTTP_404_NOT_FOUND)

    # Check for assigned employees
    emp_count_result = await db.execute(
        select(func.count(Employee.id)).where(
            and_(
                Employee.company_id == company_id,
                Employee.is_deleted == False,
                Employee.status == "ACTIVE",
                func.lower(Employee.shift) == shift.name.lower(),
            )
        )
    )
    emp_count = emp_count_result.scalar() or 0

    if emp_count > 0:
        raise AppException(
            message=f"Shift has {emp_count} assigned employees. Reassign them first before deleting.",
            status_code=status.HTTP_409_CONFLICT,
        )

    shift.deleted_at = datetime.now(timezone.utc)
    shift.is_active = False
    await db.commit()

    return APIResponse[dict](
        success=True,
        message="Shift deleted.",
        data={"deleted": True},
        errors=None,
    )