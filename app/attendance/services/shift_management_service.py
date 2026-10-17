"""Shift Management Service - CRUD, assignments, and business logic."""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance.utils.time_parse import InvalidTimeFormatError, parse_time_str
from app.attendance.utils.timezone import get_company_tz
from app.models.employee import Employee
from app.models.shift import EmployeeShiftAssignment, Shift, ShiftChangeRequest
from app.models.shift_plan import EntryApprovalStatus, ShiftPlan, ShiftPlanEntry, ShiftType

logger = logging.getLogger(__name__)


class ShiftManagementService:
    """Service for shift CRUD and assignment operations."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ─────────────────────────────────────────────────────────────────────────
    # Shift CRUD
    # ─────────────────────────────────────────────────────────────────────────

    async def create_shift(
        self,
        company_id: uuid.UUID,
        created_by: uuid.UUID,
        name: str,
        code: str,
        start_time: str,
        end_time: str,
        grace_period_minutes: int = 15,
        break_duration_minutes: int = 60,
        is_night_shift: bool = False,
        night_premium_percent: float = 0.0,
        working_days: Optional[List[str]] = None,
        is_active: bool = True,
        is_default: bool = False,
        color: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Shift:
        """Create a new shift."""
        # Normalize code
        code = code.upper()

        # Validate times
        start = parse_time_str(start_time)
        end = parse_time_str(end_time)
        if start == end:
            raise ValueError("start_time must be different from end_time.")

        is_overnight = end < start
        duration = self._calculate_duration(start, end, is_overnight)
        work_hours = round(max(0, duration - break_duration_minutes) / 60.0, 2)

        # Check duplicates
        await self._check_duplicate_shift(company_id, name, code)

        # If setting as default, unset current default
        if is_default:
            await self._unset_current_default(company_id)

        shift = Shift(
            company_id=company_id,
            name=name,
            code=code,
            start_time=start,
            end_time=end,
            is_overnight=is_overnight,
            duration_minutes=duration,
            grace_period_minutes=grace_period_minutes,
            break_duration_minutes=break_duration_minutes,
            work_hours=work_hours,
            is_night_shift=is_night_shift,
            night_premium_percent=night_premium_percent,
            working_days=working_days or ["Mon", "Tue", "Wed", "Thu", "Fri"],
            is_active=is_active,
            is_default=is_default,
            color=color,
            description=description,
        )
        self.db.add(shift)
        await self.db.commit()
        await self.db.refresh(shift)
        return shift

    async def update_shift(
        self,
        shift_id: uuid.UUID,
        company_id: uuid.UUID,
        **updates,
    ) -> Shift:
        """Update shift (partial update)."""
        stmt = select(Shift).where(
            and_(Shift.id == shift_id, Shift.company_id == company_id, Shift.deleted_at.is_(None))
        )
        result = await self.db.execute(stmt)
        shift = result.scalars().first()
        if not shift:
            raise ValueError("Shift not found.")

        # Handle is_default change
        if updates.get("is_default") is True and not shift.is_default:
            await self._unset_current_default(company_id)

        # Validate times if provided
        if "start_time" in updates or "end_time" in updates:
            new_start = parse_time_str(updates.get("start_time", shift.start_time.strftime("%H:%M")))
            new_end = parse_time_str(updates.get("end_time", shift.end_time.strftime("%H:%M")))
            if new_start == new_end:
                raise ValueError("start_time must be different from end_time.")
            updates["start_time"] = new_start
            updates["end_time"] = new_end
            updates["is_overnight"] = new_end < new_start
            updates["duration_minutes"] = self._calculate_duration(new_start, new_end, updates["is_overnight"])
            updates["work_hours"] = round(max(0, updates["duration_minutes"] - updates.get("break_duration_minutes", shift.break_duration_minutes)) / 60.0, 2)

        # Handle night_premium with is_night_shift
        if updates.get("is_night_shift") is False:
            updates["night_premium_percent"] = 0.0

        # Check duplicate name/code if changed
        if "name" in updates and updates["name"] != shift.name:
            await self._check_duplicate_shift(company_id, updates["name"], shift.code, exclude_id=shift_id)
        if "code" in updates and updates["code"] != shift.code:
            await self._check_duplicate_shift(company_id, shift.name, updates["code"].upper(), exclude_id=shift_id)

        for key, value in updates.items():
            if value is not None:
                setattr(shift, key, value)

        shift.updated_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(shift)
        return shift

    async def delete_shift(
        self,
        shift_id: uuid.UUID,
        company_id: uuid.UUID,
        reassign_to: Optional[uuid.UUID] = None,
    ) -> Dict[str, Any]:
        """Soft delete a shift, optionally reassigning current assignees."""
        stmt = select(Shift).where(
            and_(Shift.id == shift_id, Shift.company_id == company_id, Shift.deleted_at.is_(None))
        )
        result = await self.db.execute(stmt)
        shift = result.scalars().first()
        if not shift:
            raise ValueError("Shift not found.")

        if shift.is_default:
            raise ValueError("Cannot delete default shift.")

        # Count current assignees
        current_assignees = await self._get_current_assignees(shift_id, company_id)
        assignee_count = len(current_assignees)

        if assignee_count > 0 and not reassign_to:
            raise ValueError(f"Shift has {assignee_count} current assignees. Use reassign_to parameter.")

        if reassign_to:
            # Validate reassign_to shift
            reassign_stmt = select(Shift).where(
                and_(Shift.id == reassign_to, Shift.company_id == company_id, Shift.is_active.is_(True), Shift.deleted_at.is_(None))
            )
            reassign_result = await self.db.execute(reassign_stmt)
            reassign_shift = reassign_result.scalars().first()
            if not reassign_shift:
                raise ValueError("Reassign target shift not found or inactive.")
            if reassign_shift.id == shift_id:
                raise ValueError("Cannot reassign to the same shift.")

            # Reassign all current assignees
            await self._reassign_employees(current_assignees, reassign_to, date.today())

        # Soft delete
        shift.deleted_at = datetime.now(timezone.utc)
        shift.is_active = False
        await self.db.commit()

        return {"deleted": True, "reassigned_count": assignee_count if reassign_to else 0}

    async def get_shift(self, shift_id: uuid.UUID, company_id: uuid.UUID) -> Optional[Shift]:
        stmt = select(Shift).where(
            and_(Shift.id == shift_id, Shift.company_id == company_id, Shift.deleted_at.is_(None))
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def list_shifts(
        self,
        company_id: uuid.UUID,
        search: Optional[str] = None,
        is_active: Optional[bool] = None,
        night_shift: Optional[bool] = None,
        page: int = 1,
        limit: int = 20,
    ) -> Tuple[List[Shift], int]:
        stmt = select(Shift).where(and_(Shift.company_id == company_id, Shift.deleted_at.is_(None)))

        if search:
            stmt = stmt.where(
                or_(
                    Shift.name.ilike(f"%{search}%"),
                    Shift.code.ilike(f"%{search}%"),
                )
            )
        if is_active is not None:
            stmt = stmt.where(Shift.is_active == is_active)
        if night_shift is not None:
            stmt = stmt.where(Shift.is_night_shift == night_shift)

        # Total count
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.db.execute(count_stmt)).scalar() or 0

        # Paginated results
        stmt = stmt.order_by(Shift.is_default.desc(), Shift.name).offset((page - 1) * limit).limit(limit)
        result = await self.db.execute(stmt)
        shifts = list(result.scalars().all())

        # Add assigned count for each shift
        for s in shifts:
            s._assigned_employees_count = await self._get_assigned_count(s.id, company_id)

        return shifts, total

    async def get_active_shifts_options(self, company_id: uuid.UUID) -> List[Shift]:
        stmt = select(Shift).where(
            and_(
                Shift.company_id == company_id,
                Shift.is_active.is_(True),
                Shift.deleted_at.is_(None),
            )
        ).order_by(Shift.is_default.desc(), Shift.name)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    # ─────────────────────────────────────────────────────────────────────────
    # Shift Assignment
    # ─────────────────────────────────────────────────────────────────────────

    async def assign_shift(
        self,
        company_id: uuid.UUID,
        shift_id: uuid.UUID,
        employee_ids: List[uuid.UUID],
        effective_date: date,
        assigned_by: uuid.UUID,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Assign shift to multiple employees effective from a date."""
        # Validate shift
        shift = await self.get_shift(shift_id, company_id)
        if not shift:
            raise ValueError("Shift not found.")

        # Validate employees belong to company
        emp_stmt = select(Employee).where(
            and_(
                Employee.id.in_(employee_ids),
                Employee.company_id == company_id,
                Employee.is_deleted == False,
            )
        )
        emp_result = await self.db.execute(emp_stmt)
        valid_employees = list(emp_result.scalars().all())
        valid_ids = {e.id for e in valid_employees}

        skipped = []
        assigned_count = 0

        for emp_id in employee_ids:
            if emp_id not in valid_ids:
                skipped.append({"employee_id": emp_id, "reason": "INVALID_EMPLOYEE"})
                continue

            # Check if already assigned to this shift on effective_date
            existing = await self._get_effective_assignment(emp_id, effective_date, company_id)
            if existing and existing.shift_id == shift_id:
                skipped.append({"employee_id": emp_id, "reason": "ALREADY_ASSIGNED"})
                continue

            # Check for conflict with current open assignment
            current = await self._get_current_assignment(emp_id, company_id)
            if current and effective_date <= current.effective_from:
                skipped.append({"employee_id": emp_id, "reason": "ASSIGNMENT_CONFLICT"})
                continue

            # Close current assignment if exists
            if current:
                current.effective_to = effective_date - timedelta(days=1)
                current.updated_at = datetime.now(timezone.utc)

            # Create new assignment
            assignment = EmployeeShiftAssignment(
                company_id=company_id,
                employee_id=emp_id,
                shift_id=shift_id,
                effective_from=effective_date,
                assigned_by=assigned_by,
                notes=notes,
            )
            self.db.add(assignment)

            # Update employee's current shift pointer if effective today or past
            today = date.today()
            if effective_date <= today:
                emp = next(e for e in valid_employees if e.id == emp_id)
                emp.shift_id = shift_id
                emp.shift = shift.name

            assigned_count += 1

        await self.db.commit()
        return {
            "assigned_count": assigned_count,
            "skipped": skipped,
            "effective_date": effective_date,
        }

    async def get_assigned_employees(
        self,
        shift_id: uuid.UUID,
        company_id: uuid.UUID,
        page: int = 1,
        limit: int = 20,
    ) -> Tuple[List[EmployeeShiftAssignment], int]:
        stmt = select(EmployeeShiftAssignment).where(
            and_(
                EmployeeShiftAssignment.shift_id == shift_id,
                EmployeeShiftAssignment.company_id == company_id,
                EmployeeShiftAssignment.effective_to.is_(None),
            )
        ).order_by(EmployeeShiftAssignment.effective_from.desc())

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.db.execute(count_stmt)).scalar() or 0

        stmt = stmt.offset((page - 1) * limit).limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all()), total

    # ─────────────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _calculate_duration(self, start: time, end: time, is_overnight: bool) -> int:
        if is_overnight:
            return (24 - start.hour) * 60 - start.minute + end.hour * 60 + end.minute
        return (end.hour - start.hour) * 60 + (end.minute - start.minute)

    async def _check_duplicate_shift(
        self, company_id: uuid.UUID, name: str, code: str, exclude_id: Optional[uuid.UUID] = None
    ) -> None:
        stmt = select(Shift).where(
            and_(
                Shift.company_id == company_id,
                Shift.deleted_at.is_(None),
                or_(
                    func.lower(Shift.name) == name.lower(),
                    Shift.code == code.upper(),
                ),
            )
        )
        if exclude_id:
            stmt = stmt.where(Shift.id != exclude_id)
        result = await self.db.execute(stmt)
        existing = result.scalars().first()
        if existing:
            if existing.name.lower() == name.lower():
                raise ValueError("DUPLICATE_SHIFT_NAME")
            raise ValueError("DUPLICATE_SHIFT_CODE")

    async def _unset_current_default(self, company_id: uuid.UUID) -> None:
        stmt = select(Shift).where(
            and_(Shift.company_id == company_id, Shift.is_default.is_(True), Shift.deleted_at.is_(None))
        )
        result = await self.db.execute(stmt)
        current = result.scalars().first()
        if current:
            current.is_default = False
            current.updated_at = datetime.now(timezone.utc)

    async def _get_current_assignees(self, shift_id: uuid.UUID, company_id: uuid.UUID) -> List[EmployeeShiftAssignment]:
        stmt = select(EmployeeShiftAssignment).where(
            and_(
                EmployeeShiftAssignment.shift_id == shift_id,
                EmployeeShiftAssignment.company_id == company_id,
                EmployeeShiftAssignment.effective_to.is_(None),
            )
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def _get_assigned_count(self, shift_id: uuid.UUID, company_id: uuid.UUID) -> int:
        stmt = select(func.count(EmployeeShiftAssignment.id)).where(
            and_(
                EmployeeShiftAssignment.shift_id == shift_id,
                EmployeeShiftAssignment.company_id == company_id,
                EmployeeShiftAssignment.effective_to.is_(None),
            )
        )
        result = await self.db.execute(stmt)
        return result.scalar() or 0

    async def _get_effective_assignment(
        self, employee_id: uuid.UUID, business_date: date, company_id: uuid.UUID
    ) -> Optional[EmployeeShiftAssignment]:
        stmt = select(EmployeeShiftAssignment).where(
            and_(
                EmployeeShiftAssignment.employee_id == employee_id,
                EmployeeShiftAssignment.company_id == company_id,
                EmployeeShiftAssignment.effective_from <= business_date,
                or_(
                    EmployeeShiftAssignment.effective_to.is_(None),
                    EmployeeShiftAssignment.effective_to >= business_date,
                ),
            )
        ).order_by(EmployeeShiftAssignment.effective_from.desc())
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def _get_current_assignment(
        self, employee_id: uuid.UUID, company_id: uuid.UUID
    ) -> Optional[EmployeeShiftAssignment]:
        stmt = select(EmployeeShiftAssignment).where(
            and_(
                EmployeeShiftAssignment.employee_id == employee_id,
                EmployeeShiftAssignment.company_id == company_id,
                EmployeeShiftAssignment.effective_to.is_(None),
            )
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def _reassign_employees(
        self, assignments: List[EmployeeShiftAssignment], new_shift_id: uuid.UUID, effective_date: date
    ) -> None:
        for a in assignments:
            a.effective_to = effective_date - timedelta(days=1)
            a.updated_at = datetime.now(timezone.utc)
            new_assignment = EmployeeShiftAssignment(
                company_id=a.company_id,
                employee_id=a.employee_id,
                shift_id=new_shift_id,
                effective_from=effective_date,
                assigned_by=a.assigned_by,
                notes=f"Reassigned from shift {a.shift_id}",
            )
            self.db.add(new_assignment)

    # ─────────────────────────────────────────────────────────────────────────
    # Shift Change Requests
    # ─────────────────────────────────────────────────────────────────────────

    async def create_change_request(
        self,
        company_id: uuid.UUID,
        employee_id: uuid.UUID,
        requested_shift_id: uuid.UUID,
        effective_date: date,
        reason: str,
    ) -> ShiftChangeRequest:
        # Validate requested shift
        shift = await self.get_shift(requested_shift_id, company_id)
        if not shift or not shift.is_active:
            raise ValueError("Requested shift not found or inactive.")

        # Check for existing pending request
        existing = await self.db.execute(
            select(ShiftChangeRequest).where(
                and_(
                    ShiftChangeRequest.employee_id == employee_id,
                    ShiftChangeRequest.status == "PENDING",
                )
            )
        )
        if existing.scalars().first():
            raise ValueError("Employee already has a pending change request.")

        # Get current shift
        current = await self._get_effective_assignment(employee_id, effective_date, company_id)

        request = ShiftChangeRequest(
            company_id=company_id,
            employee_id=employee_id,
            current_shift_id=current.shift_id if current else None,
            requested_shift_id=requested_shift_id,
            effective_date=effective_date,
            reason=reason,
            status="PENDING",
        )
        self.db.add(request)
        await self.db.commit()
        await self.db.refresh(request)
        return request

    async def approve_change_request(
        self,
        request_id: uuid.UUID,
        company_id: uuid.UUID,
        reviewed_by: uuid.UUID,
        note: Optional[str] = None,
    ) -> ShiftChangeRequest:
        stmt = select(ShiftChangeRequest).where(
            and_(ShiftChangeRequest.id == request_id, ShiftChangeRequest.company_id == company_id)
        )
        result = await self.db.execute(stmt)
        request = result.scalars().first()
        if not request:
            raise ValueError("Change request not found.")
        if request.status != "PENDING":
            raise ValueError("CHANGE_REQUEST_INVALID_STATE")

        # Create assignment
        await self.assign_shift(
            company_id=company_id,
            shift_id=request.requested_shift_id,
            employee_ids=[request.employee_id],
            effective_date=request.effective_date,
            assigned_by=reviewed_by,
            notes=f"Approved change request: {note or 'No note'}",
        )

        request.status = "APPROVED"
        request.reviewed_by = reviewed_by
        request.reviewed_at = datetime.now(timezone.utc)
        request.review_note = note
        await self.db.commit()
        await self.db.refresh(request)
        return request

    async def reject_change_request(
        self,
        request_id: uuid.UUID,
        company_id: uuid.UUID,
        reviewed_by: uuid.UUID,
        note: str,
    ) -> ShiftChangeRequest:
        stmt = select(ShiftChangeRequest).where(
            and_(ShiftChangeRequest.id == request_id, ShiftChangeRequest.company_id == company_id)
        )
        result = await self.db.execute(stmt)
        request = result.scalars().first()
        if not request:
            raise ValueError("Change request not found.")
        if request.status != "PENDING":
            raise ValueError("CHANGE_REQUEST_INVALID_STATE")

        request.status = "REJECTED"
        request.reviewed_by = reviewed_by
        request.reviewed_at = datetime.now(timezone.utc)
        request.review_note = note
        await self.db.commit()
        await self.db.refresh(request)
        return request

    async def cancel_change_request(
        self, request_id: uuid.UUID, employee_id: uuid.UUID
    ) -> ShiftChangeRequest:
        stmt = select(ShiftChangeRequest).where(
            and_(
                ShiftChangeRequest.id == request_id,
                ShiftChangeRequest.employee_id == employee_id,
            )
        )
        result = await self.db.execute(stmt)
        request = result.scalars().first()
        if not request:
            raise ValueError("Change request not found.")
        if request.status != "PENDING":
            raise ValueError("CHANGE_REQUEST_INVALID_STATE")

        request.status = "CANCELLED"
        await self.db.commit()
        await self.db.refresh(request)
        return request

    async def list_change_requests(
        self,
        company_id: uuid.UUID,
        status: Optional[str] = None,
        page: int = 1,
        limit: int = 20,
    ) -> Tuple[List[ShiftChangeRequest], int]:
        stmt = select(ShiftChangeRequest).where(ShiftChangeRequest.company_id == company_id)
        if status:
            stmt = stmt.where(ShiftChangeRequest.status == status)
        stmt = stmt.order_by(ShiftChangeRequest.created_at.desc())

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.db.execute(count_stmt)).scalar() or 0

        stmt = stmt.offset((page - 1) * limit).limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all()), total

    async def list_my_change_requests(
        self, employee_id: uuid.UUID, company_id: uuid.UUID, page: int = 1, limit: int = 20
    ) -> Tuple[List[ShiftChangeRequest], int]:
        stmt = select(ShiftChangeRequest).where(
            and_(
                ShiftChangeRequest.employee_id == employee_id,
                ShiftChangeRequest.company_id == company_id,
            )
        ).order_by(ShiftChangeRequest.created_at.desc())

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.db.execute(count_stmt)).scalar() or 0

        stmt = stmt.offset((page - 1) * limit).limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all()), total


# Need to import time and timezone
from datetime import time, timezone