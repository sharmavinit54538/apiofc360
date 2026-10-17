"""Roster API Routes."""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta
from typing import Annotated, Any, List, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.attendance.services.roster_service import RosterService
from app.core.exceptions import AppException
from app.core.rbac import require_admin, require_admin_or_manager
from app.db.database import get_db_session
from app.models.employee import Employee
from app.models.shift import Shift
from app.models.shift_plan import EntryApprovalStatus, ShiftPlan, ShiftPlanEntry, ShiftPlanSource, ShiftPlanStatus, ShiftType
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


def _parse_time_str(time_str: str) -> time:
    """Parse time string in HH:MM format and return time object."""
    time_str = time_str.strip()
    try:
        return datetime.strptime(time_str, "%H:%M").time()
    except ValueError:
        raise ValueError(f"Invalid time format: {time_str}. Use HH:MM (24-hour) format.")


def _format_time(time_obj: Optional[time]) -> Optional[str]:
    """Format time object as HH:MM string."""
    if time_obj is None:
        return None
    return time_obj.strftime("%H:%M")


def _normalize_shift_type(shift_type: Optional[str]) -> ShiftType:
    """Normalize shift_type to upper snake case."""
    if not shift_type:
        return ShiftType.DAY
    normalized = shift_type.upper().replace(" ", "_").replace("-", "_")
    try:
        return ShiftType(normalized)
    except ValueError:
        # Default to DAY for unknown types
        return ShiftType.DAY


async def _get_or_create_manual_plan(
    db: AsyncSession, company_id: uuid.UUID, entry_date: date
) -> ShiftPlan:
    """Get or create the MANUAL plan for a company/month."""
    month_start = date(entry_date.year, entry_date.month, 1)
    if entry_date.month == 12:
        month_end = date(entry_date.year + 1, 1, 1) - timedelta(days=1)
    else:
        month_end = date(entry_date.year, entry_date.month + 1, 1) - timedelta(days=1)

    stmt = select(ShiftPlan).where(
        and_(
            ShiftPlan.company_id == company_id,
            ShiftPlan.source == ShiftPlanSource.MANUAL,
            ShiftPlan.period_start <= month_end,
            ShiftPlan.period_end >= month_start,
        )
    )
    result = await db.execute(stmt)
    plan = result.scalars().first()

    if plan:
        return plan

    plan = ShiftPlan(
        company_id=company_id,
        plan_type="MONTHLY",
        period_start=month_start,
        period_end=month_end,
        source=ShiftPlanSource.MANUAL,
        status=ShiftPlanStatus.PUBLISHED,
        created_by=None,
    )
    db.add(plan)
    await db.flush()
    return plan


# Static routes MUST come before /{roster_id} to avoid path capture

@router.get(
    "/rosters",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="List roster entries (Admin and Managers)",
    dependencies=[Depends(require_admin_or_manager)],
)
async def list_rosters(
    start_date: Optional[date] = Query(None, description="Start date (defaults to first day of current month)"),
    end_date: Optional[date] = Query(None, description="End date (defaults to last day of current month)"),
    employee_id: Optional[uuid.UUID] = Query(None),
    department: Optional[str] = Query(None),
    shift_type: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(100, ge=1, le=100),
    claims: Annotated[dict, Depends(require_admin_or_manager)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """List roster entries with pagination. Dates default to current month."""
    company_id = _get_company_id(claims)

    # Default to current month
    today = date.today()
    if start_date is None:
        start_date = date(today.year, today.month, 1)
    if end_date is None:
        if today.month == 12:
            end_date = date(today.year + 1, 1, 1) - timedelta(days=1)
        else:
            end_date = date(today.year, today.month + 1, 1) - timedelta(days=1)

    if start_date > end_date:
        start_date, end_date = end_date, start_date

    # Build query
    stmt = (
        select(ShiftPlanEntry, Employee, ShiftPlan)
        .join(Employee, ShiftPlanEntry.employee_id == Employee.id)
        .join(ShiftPlan, ShiftPlanEntry.plan_id == ShiftPlan.id)
        .where(
            and_(
                ShiftPlanEntry.company_id == company_id,
                ShiftPlanEntry.shift_date >= start_date,
                ShiftPlanEntry.shift_date <= end_date,
            )
        )
    )

    if employee_id:
        stmt = stmt.where(ShiftPlanEntry.employee_id == employee_id)
    if department:
        stmt = stmt.where(Employee.department == department)
    if shift_type:
        stmt = stmt.where(ShiftPlanEntry.shift_type == _normalize_shift_type(shift_type))

    # Only approved entries from published plans
    stmt = stmt.where(
        and_(
            ShiftPlanEntry.approval_status == EntryApprovalStatus.APPROVED,
            ShiftPlan.status == ShiftPlanStatus.PUBLISHED,
        )
    )

    # Total count
    count_stmt = select(func.count(ShiftPlanEntry.id)).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    # Paginated
    stmt = stmt.order_by(ShiftPlanEntry.shift_date, Employee.first_name).offset((page - 1) * limit).limit(limit)
    result = await db.execute(stmt)
    rows = result.all()

    items = []
    for entry, employee, plan in rows:
        # Determine shift name
        shift_name = entry.shift_type.value
        if entry.shift_id:
            shift_stmt = select(Shift).where(Shift.id == entry.shift_id)
            shift_result = await db.execute(shift_stmt)
            shift = shift_result.scalars().first()
            if shift:
                shift_name = shift.name

        # Check if off type
        is_off = entry.shift_type in (ShiftType.OFF, ShiftType.WEEKLY_OFF, ShiftType.HOLIDAY)

        items.append({
            "id": str(entry.id),
            "plan_id": str(entry.plan_id),
            "employee_id": str(employee.id),
            "employee_code": employee.employee_id,
            "employee_name": f"{employee.first_name} {employee.last_name}",
            "department": employee.department,
            "shift_date": entry.shift_date.isoformat(),
            "shift_type": entry.shift_type.value,
            "start_time": _format_time(entry.start_time),
            "end_time": _format_time(entry.end_time),
            "is_off": is_off,
            "notes": entry.notes,
        })

    return APIResponse[dict](
        success=True,
        message="Roster entries retrieved.",
        data={
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "page": page,
            "limit": limit,
            "total": total,
            "items": items,
        },
        errors=None,
    )


@router.post(
    "/rosters",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[dict],
    summary="Create or update roster entry (Admin) - Upsert",
    dependencies=[Depends(require_admin)],
)
async def create_roster_entry(
    body: dict,
    claims: Annotated[dict, Depends(require_admin)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Create or update roster entry. Upserts on (employee_id, shift_date)."""
    company_id = _get_company_id(claims)

    employee_id = body.get("employee_id")
    shift_date = body.get("shift_date")
    shift_type = body.get("shift_type")
    shift_id = body.get("shift_id")
    start_time_str = body.get("start_time")
    end_time_str = body.get("end_time")
    notes = body.get("notes")

    if not employee_id or not shift_date:
        raise AppException(message="employee_id and shift_date are required.", status_code=status.HTTP_400_BAD_REQUEST)

    if isinstance(employee_id, str):
        employee_id = uuid.UUID(employee_id)
    if isinstance(shift_date, str):
        shift_date = date.fromisoformat(shift_date)

    # Validate employee
    emp_stmt = select(Employee).where(
        and_(Employee.id == employee_id, Employee.company_id == company_id, Employee.is_deleted == False)
    )
    emp_result = await db.execute(emp_stmt)
    employee = emp_result.scalars().first()
    if not employee:
        raise AppException(message="Employee not found in this company.", status_code=status.HTTP_404_NOT_FOUND)

    # Get or create manual plan
    plan = await _get_or_create_manual_plan(db, company_id, shift_date)

    # Check for existing entry
    existing_stmt = select(ShiftPlanEntry).where(
        and_(
            ShiftPlanEntry.plan_id == plan.id,
            ShiftPlanEntry.employee_id == employee_id,
            ShiftPlanEntry.shift_date == shift_date,
        )
    )
    existing_result = await db.execute(existing_stmt)
    existing_entry = existing_result.scalars().first()

    # Parse shift_type
    shift_type_enum = _normalize_shift_type(shift_type)

    # If shift_id provided, copy times from shift
    if shift_id:
        if isinstance(shift_id, str):
            shift_id = uuid.UUID(shift_id)
        shift_stmt = select(Shift).where(
            and_(Shift.id == shift_id, Shift.company_id == company_id, Shift.deleted_at.is_(None))
        )
        shift_result = await db.execute(shift_stmt)
        shift = shift_result.scalars().first()
        if not shift:
            raise AppException(message="Shift not found in this company.", status_code=status.HTTP_404_NOT_FOUND)
        if start_time_str is None:
            start_time_str = _format_time(shift.start_time)
        if end_time_str is None:
            end_time_str = _format_time(shift.end_time)
        # If shift_type not provided, infer from times
        if shift_type is None:
            if shift.end_time < shift.start_time:
                shift_type_enum = ShiftType.NIGHT
            else:
                shift_type_enum = ShiftType.DAY

    # For OFF types, start_time and end_time must be None
    is_off_type = shift_type_enum in (ShiftType.OFF, ShiftType.WEEKLY_OFF, ShiftType.HOLIDAY)
    if is_off_type:
        start_time_str = None
        end_time_str = None

    # For non-OFF types, start_time and end_time must be provided together or both omitted
    if not is_off_type:
        has_start = start_time_str is not None and start_time_str != ""
        has_end = end_time_str is not None and end_time_str != ""
        if has_start != has_end:
            raise AppException(
                message="For non-OFF types, start_time and end_time must be provided together or both omitted.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

    start_time = _parse_time_str(start_time_str) if start_time_str else None
    end_time = _parse_time_str(end_time_str) if end_time_str else None

    if existing_entry:
        # Update existing (upsert)
        existing_entry.shift_type = shift_type_enum
        existing_entry.shift_id = shift_id
        existing_entry.start_time = start_time
        existing_entry.end_time = end_time
        existing_entry.notes = notes
        existing_entry.approval_status = EntryApprovalStatus.APPROVED
        await db.commit()
        await db.refresh(existing_entry)
        entry = existing_entry
        action = "updated"
    else:
        # Create new
        entry = ShiftPlanEntry(
            plan_id=plan.id,
            company_id=company_id,
            employee_id=employee_id,
            shift_date=shift_date,
            shift_type=shift_type_enum,
            shift_id=shift_id,
            start_time=start_time,
            end_time=end_time,
            approval_status=EntryApprovalStatus.APPROVED,
            notes=notes,
        )
        db.add(entry)
        await db.commit()
        await db.refresh(entry)
        action = "created"

    return APIResponse[dict](
        success=True,
        message=f"Roster entry {action}.",
        data={
            "id": str(entry.id),
            "plan_id": str(entry.plan_id),
            "employee_id": str(entry.employee_id),
            "employee_code": employee.employee_id,
            "employee_name": f"{employee.first_name} {employee.last_name}",
            "department": employee.department,
            "shift_date": entry.shift_date.isoformat(),
            "shift_type": entry.shift_type.value,
            "start_time": _format_time(entry.start_time),
            "end_time": _format_time(entry.end_time),
            "is_off": entry.shift_type in (ShiftType.OFF, ShiftType.WEEKLY_OFF, ShiftType.HOLIDAY),
            "notes": entry.notes,
        },
        errors=None,
    )


@router.post(
    "/rosters/bulk",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[dict],
    summary="Bulk create/update roster entries (Admin) - Upsert",
    dependencies=[Depends(require_admin)],
)
async def bulk_create_rosters(
    body: dict,
    claims: Annotated[dict, Depends(require_admin)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Bulk upsert roster entries. Body: employee_ids[], dates[] or start_date+end_date, optional shift fields. Max 2000 rows."""
    company_id = _get_company_id(claims)

    employee_ids = body.get("employee_ids", [])
    dates = body.get("dates", [])
    start_date = body.get("start_date")
    end_date = body.get("end_date")
    shift_type = body.get("shift_type")
    shift_id = body.get("shift_id")
    start_time_str = body.get("start_time")
    end_time_str = body.get("end_time")
    notes = body.get("notes")

    if not employee_ids or len(employee_ids) == 0:
        raise AppException(message="employee_ids must contain at least one employee.", status_code=status.HTTP_400_BAD_REQUEST)

    # Build date list
    date_list: List[date] = []
    if dates:
        for d in dates:
            if isinstance(d, str):
                date_list.append(date.fromisoformat(d))
            elif isinstance(d, date):
                date_list.append(d)
    elif start_date and end_date:
        if isinstance(start_date, str):
            start_date = date.fromisoformat(start_date)
        if isinstance(end_date, str):
            end_date = date.fromisoformat(end_date)
        if start_date > end_date:
            start_date, end_date = end_date, start_date
        current = start_date
        while current <= end_date:
            date_list.append(current)
            current += timedelta(days=1)
    else:
        raise AppException(message="Either dates[] or start_date+end_date must be provided.", status_code=status.HTTP_400_BAD_REQUEST)

    total_rows = len(employee_ids) * len(date_list)
    if total_rows > 2000:
        raise AppException(message=f"Bulk operation limited to 2000 rows. Requested: {total_rows}.", status_code=status.HTTP_400_BAD_REQUEST)

    # Parse shift_type once
    shift_type_enum = _normalize_shift_type(shift_type)

    # If shift_id provided, validate and get times
    shift_obj = None
    if shift_id:
        if isinstance(shift_id, str):
            shift_id = uuid.UUID(shift_id)
        shift_stmt = select(Shift).where(
            and_(Shift.id == shift_id, Shift.company_id == company_id, Shift.deleted_at.is_(None))
        )
        shift_result = await db.execute(shift_stmt)
        shift_obj = shift_result.scalars().first()
        if not shift_obj:
            raise AppException(message="Shift not found in this company.", status_code=status.HTTP_404_NOT_FOUND)
        if start_time_str is None:
            start_time_str = _format_time(shift_obj.start_time)
        if end_time_str is None:
            end_time_str = _format_time(shift_obj.end_time)
        if shift_type is None:
            if shift_obj.end_time < shift_obj.start_time:
                shift_type_enum = ShiftType.NIGHT
            else:
                shift_type_enum = ShiftType.DAY

    is_off_type = shift_type_enum in (ShiftType.OFF, ShiftType.WEEKLY_OFF, ShiftType.HOLIDAY)
    if is_off_type:
        start_time_str = None
        end_time_str = None
    else:
        has_start = start_time_str is not None and start_time_str != ""
        has_end = end_time_str is not None and end_time_str != ""
        if has_start != has_end:
            raise AppException(
                message="For non-OFF types, start_time and end_time must be provided together or both omitted.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

    start_time = _parse_time_str(start_time_str) if start_time_str else None
    end_time = _parse_time_str(end_time_str) if end_time_str else None

    # Validate all employees belong to company
    emp_stmt = select(Employee).where(
        and_(Employee.id.in_(employee_ids), Employee.company_id == company_id, Employee.is_deleted == False)
    )
    emp_result = await db.execute(emp_stmt)
    valid_employees = {e.id: e for e in emp_result.scalars().all()}

    if len(valid_employees) != len(employee_ids):
        invalid = set(employee_ids) - set(valid_employees.keys())
        raise AppException(
            message=f"Some employees not found in this company: {[str(i) for i in invalid]}",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    created = 0
    updated = 0

    for emp_id in employee_ids:
        employee = valid_employees[emp_id]
        for entry_date in date_list:
            plan = await _get_or_create_manual_plan(db, company_id, entry_date)

            existing_stmt = select(ShiftPlanEntry).where(
                and_(
                    ShiftPlanEntry.plan_id == plan.id,
                    ShiftPlanEntry.employee_id == emp_id,
                    ShiftPlanEntry.shift_date == entry_date,
                )
            )
            existing_result = await db.execute(existing_stmt)
            existing_entry = existing_result.scalars().first()

            if existing_entry:
                existing_entry.shift_type = shift_type_enum
                existing_entry.shift_id = shift_id
                existing_entry.start_time = start_time
                existing_entry.end_time = end_time
                existing_entry.notes = notes
                existing_entry.approval_status = EntryApprovalStatus.APPROVED
                updated += 1
            else:
                entry = ShiftPlanEntry(
                    plan_id=plan.id,
                    company_id=company_id,
                    employee_id=emp_id,
                    shift_date=entry_date,
                    shift_type=shift_type_enum,
                    shift_id=shift_id,
                    start_time=start_time,
                    end_time=end_time,
                    approval_status=EntryApprovalStatus.APPROVED,
                    notes=notes,
                )
                db.add(entry)
                created += 1

    await db.commit()

    return APIResponse[dict](
        success=True,
        message=f"Bulk roster operation completed: {created} created, {updated} updated.",
        data={"created": created, "updated": updated, "total": created + updated},
        errors=None,
    )


@router.get(
    "/rosters/{roster_id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Get roster entry by ID (Admin and Managers)",
    dependencies=[Depends(require_admin_or_manager)],
)
async def get_roster_entry(
    roster_id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin_or_manager)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Get roster entry by ID."""
    company_id = _get_company_id(claims)

    stmt = (
        select(ShiftPlanEntry, Employee, ShiftPlan)
        .join(Employee, ShiftPlanEntry.employee_id == Employee.id)
        .join(ShiftPlan, ShiftPlanEntry.plan_id == ShiftPlan.id)
        .where(
            and_(
                ShiftPlanEntry.id == roster_id,
                ShiftPlanEntry.company_id == company_id,
            )
        )
    )
    result = await db.execute(stmt)
    row = result.first()

    if not row:
        raise AppException(message="Roster entry not found.", status_code=status.HTTP_404_NOT_FOUND)

    entry, employee, plan = row

    shift_name = entry.shift_type.value
    if entry.shift_id:
        shift_stmt = select(Shift).where(Shift.id == entry.shift_id)
        shift_result = await db.execute(shift_stmt)
        shift = shift_result.scalars().first()
        if shift:
            shift_name = shift.name

    is_off = entry.shift_type in (ShiftType.OFF, ShiftType.WEEKLY_OFF, ShiftType.HOLIDAY)

    return APIResponse[dict](
        success=True,
        message="Roster entry retrieved.",
        data={
            "id": str(entry.id),
            "plan_id": str(entry.plan_id),
            "employee_id": str(employee.id),
            "employee_code": employee.employee_id,
            "employee_name": f"{employee.first_name} {employee.last_name}",
            "department": employee.department,
            "shift_date": entry.shift_date.isoformat(),
            "shift_type": entry.shift_type.value,
            "start_time": _format_time(entry.start_time),
            "end_time": _format_time(entry.end_time),
            "is_off": is_off,
            "notes": entry.notes,
        },
        errors=None,
    )


@router.put(
    "/rosters/{roster_id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Update roster entry (Admin and Managers)",
    dependencies=[Depends(require_admin_or_manager)],
)
async def update_roster_entry(
    roster_id: uuid.UUID,
    body: dict,
    claims: Annotated[dict, Depends(require_admin_or_manager)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Update roster entry. Reject moving to date where employee already has entry."""
    company_id = _get_company_id(claims)

    stmt = select(ShiftPlanEntry).where(
        and_(ShiftPlanEntry.id == roster_id, ShiftPlanEntry.company_id == company_id)
    )
    result = await db.execute(stmt)
    entry = result.scalars().first()
    if not entry:
        raise AppException(message="Roster entry not found.", status_code=status.HTTP_404_NOT_FOUND)

    # Handle shift_date change
    new_shift_date = body.get("shift_date")
    if new_shift_date is not None:
        if isinstance(new_shift_date, str):
            new_shift_date = date.fromisoformat(new_shift_date)
        if new_shift_date != entry.shift_date:
            # Check if employee already has entry on new date
            plan = await _get_or_create_manual_plan(db, company_id, new_shift_date)
            existing_check = await db.execute(
                select(ShiftPlanEntry).where(
                    and_(
                        ShiftPlanEntry.plan_id == plan.id,
                        ShiftPlanEntry.employee_id == entry.employee_id,
                        ShiftPlanEntry.shift_date == new_shift_date,
                    )
                )
            )
            if existing_check.scalars().first():
                raise AppException(
                    message="Employee already has a roster entry on that date.",
                    status_code=status.HTTP_409_CONFLICT,
                )
            entry.shift_date = new_shift_date
            entry.plan_id = plan.id

    if "shift_type" in body and body["shift_type"] is not None:
        entry.shift_type = _normalize_shift_type(body["shift_type"])

    if "shift_id" in body and body["shift_id"] is not None:
        shift_id_val = body["shift_id"]
        if isinstance(shift_id_val, str):
            shift_id_val = uuid.UUID(shift_id_val)
        shift_stmt = select(Shift).where(
            and_(Shift.id == shift_id_val, Shift.company_id == company_id, Shift.deleted_at.is_(None))
        )
        shift_result = await db.execute(shift_stmt)
        shift = shift_result.scalars().first()
        if not shift:
            raise AppException(message="Shift not found in this company.", status_code=status.HTTP_404_NOT_FOUND)
        entry.shift_id = shift_id_val
        # Copy times from shift if not explicitly provided
        if "start_time" not in body or body["start_time"] is None:
            body["start_time"] = _format_time(shift.start_time)
        if "end_time" not in body or body["end_time"] is None:
            body["end_time"] = _format_time(shift.end_time)
        if "shift_type" not in body or body["shift_type"] is None:
            if shift.end_time < shift.start_time:
                entry.shift_type = ShiftType.NIGHT
            else:
                entry.shift_type = ShiftType.DAY

    if "start_time" in body and body["start_time"] is not None:
        entry.start_time = _parse_time_str(body["start_time"])
    elif "start_time" in body and body["start_time"] == "":
        entry.start_time = None

    if "end_time" in body and body["end_time"] is not None:
        entry.end_time = _parse_time_str(body["end_time"])
    elif "end_time" in body and body["end_time"] == "":
        entry.end_time = None

    # Validate OFF type constraints
    is_off_type = entry.shift_type in (ShiftType.OFF, ShiftType.WEEKLY_OFF, ShiftType.HOLIDAY)
    if is_off_type:
        entry.start_time = None
        entry.end_time = None
    else:
        has_start = entry.start_time is not None
        has_end = entry.end_time is not None
        if has_start != has_end:
            raise AppException(
                message="For non-OFF types, start_time and end_time must be provided together or both omitted.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

    if "notes" in body:
        entry.notes = body["notes"]

    await db.commit()
    await db.refresh(entry)

    # Fetch employee for response
    emp_stmt = select(Employee).where(Employee.id == entry.employee_id)
    emp_result = await db.execute(emp_stmt)
    employee = emp_result.scalars().first()

    shift_name = entry.shift_type.value
    if entry.shift_id:
        shift_stmt = select(Shift).where(Shift.id == entry.shift_id)
        shift_result = await db.execute(shift_stmt)
        shift = shift_result.scalars().first()
        if shift:
            shift_name = shift.name

    return APIResponse[dict](
        success=True,
        message="Roster entry updated.",
        data={
            "id": str(entry.id),
            "plan_id": str(entry.plan_id),
            "employee_id": str(employee.id) if employee else str(entry.employee_id),
            "employee_code": employee.employee_id if employee else "",
            "employee_name": f"{employee.first_name} {employee.last_name}" if employee else "",
            "department": employee.department if employee else "",
            "shift_date": entry.shift_date.isoformat(),
            "shift_type": entry.shift_type.value,
            "start_time": _format_time(entry.start_time),
            "end_time": _format_time(entry.end_time),
            "is_off": is_off_type,
            "notes": entry.notes,
        },
        errors=None,
    )


@router.patch(
    "/rosters/{roster_id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Partially update roster entry (Admin and Managers)",
    dependencies=[Depends(require_admin_or_manager)],
)
async def patch_roster_entry(
    roster_id: uuid.UUID,
    body: dict,
    claims: Annotated[dict, Depends(require_admin_or_manager)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Partially update roster entry. Same as PUT."""
    return await update_roster_entry(roster_id, body, claims, db)


@router.delete(
    "/rosters/{roster_id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Delete roster entry (Admin and Managers)",
    dependencies=[Depends(require_admin_or_manager)],
)
async def delete_roster_entry(
    roster_id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin_or_manager)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Delete roster entry."""
    company_id = _get_company_id(claims)

    stmt = select(ShiftPlanEntry).where(
        and_(ShiftPlanEntry.id == roster_id, ShiftPlanEntry.company_id == company_id)
    )
    result = await db.execute(stmt)
    entry = result.scalars().first()
    if not entry:
        raise AppException(message="Roster entry not found.", status_code=status.HTTP_404_NOT_FOUND)

    await db.delete(entry)
    await db.commit()

    return APIResponse[dict](
        success=True,
        message="Roster entry deleted.",
        data={"deleted": True},
        errors=None,
    )