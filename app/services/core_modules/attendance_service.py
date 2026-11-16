"""Attendance service implementing full business logic for all attendance endpoints."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import Query
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance.models.attendance import Attendance, AttendanceState
from app.models.core_modules import AttendanceRegularizationRequest
from app.models.employee import Employee
from app.attendance.services.shift_service import ShiftService
from app.attendance.services.validation_service import (
    assert_attendance_period_editable, attendance_period_block_reason,
)
from app.attendance.utils.timezone import get_company_tz
from app.attendance.utils.helpers import write_audit_log
from app.schemas.core_modules.attendance import (
    AttendanceCheckInRequest,
    AttendanceCheckOutRequest,
    AttendanceManualUpdateRequest,
    AttendanceRegularizationCreateRequest,
)

logger = logging.getLogger(__name__)


class AttendanceCoreService:
    """Service handling check-in, check-out, face punch, regularization, and analytics."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_employee_by_user_id(self, user_id: uuid.UUID) -> Employee | None:
        stmt = select(Employee).where(Employee.user_id == user_id, Employee.is_deleted == False)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_today_record(self, employee_id: uuid.UUID, target_date: date | None = None) -> Attendance | None:
        t_date = target_date or date.today()
        stmt = select(Attendance).where(
            Attendance.employee_id == employee_id,
            Attendance.date == t_date,
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def check_in(
        self,
        employee_id: uuid.UUID,
        company_id: uuid.UUID | None,
        payload: AttendanceCheckInRequest,
        source: str = "app",
    ) -> Attendance:
        now = datetime.now(UTC)
        
        # Get employee to access company_id and shift
        emp = await self.session.get(Employee, employee_id)
        if not emp:
            raise ValueError("Employee not found")
        
        actual_company_id = company_id or emp.company_id
        if not actual_company_id:
            raise ValueError("Company context required")
        
        # Use shift service for proper shift handling (including night shifts)
        shift_service = ShiftService(self.session)
        tz = await get_company_tz(self.session, str(actual_company_id))
        resolved, business_date = await shift_service.resolve_for_timestamp(emp, now, tz)
        eval_result = shift_service.evaluate_checkin(resolved, now)
        
        # Check for existing record on business date
        record = await self.get_today_record(employee_id, business_date)
        if record:
            return record

        record = Attendance(
            id=uuid.uuid4(),
            employee_id=employee_id,
            company_id=actual_company_id,
            date=business_date,
            check_in_time=now,
            status="Present" if not eval_result.is_late else "Late",
            punch_type="IN",
            verified=True,
            punch_verified_by=source.upper(),
            attendance_state=AttendanceState.CHECKED_IN,
            latitude=payload.latitude,
            longitude=payload.longitude,
            ip_address=payload.ip_address,
            device_info=payload.device_info,
            notes=payload.notes,
            is_late=eval_result.is_late,
            late_minutes=eval_result.late_minutes,
            shift_id=resolved.shift_id,
            shift_name=resolved.shift_name,
            shift_source=resolved.source,
            scheduled_start=resolved.start_dt,
            scheduled_end=resolved.end_dt,
            is_off_day_work=eval_result.is_off_day_work,
            is_holiday_work=eval_result.is_holiday_work,
        )
        self.session.add(record)

        if eval_result.is_late:
            try:
                from app.services import notification_service
                recipients = []
                if emp.user_id:
                    recipients.append(emp.user_id)
                if emp.reporting_manager_id or emp.manager_id:
                    mgr = await self.session.get(Employee, emp.reporting_manager_id or emp.manager_id)
                    if mgr and mgr.user_id:
                        recipients.append(mgr.user_id)
                if recipients:
                    await notification_service.notify(
                        self.session,
                        company_id=actual_company_id,
                        recipient_ids=recipients,
                        type="attendance.late_arrival",
                        category="attendance",
                        module="attendance",
                        title="Late Arrival Recorded",
                        body=f"{emp.first_name if emp else 'Employee'} checked in {eval_result.late_minutes} min late on {business_date.isoformat()}.",
                        link="/dashboard/attendance",
                        priority="normal",
                        entity={"type": "attendance", "id": str(record.id)},
                        dedupe_key=f"attendance:{record.id}:late",
                    )
            except Exception as e:
                logger.warning("Failed to emit late attendance notification: %s", e)

        await self.session.commit()
        await self.session.refresh(record)
        
        # Audit log
        try:
            await write_audit_log(
                self.session, emp.user_id, "CHECK_IN", payload.ip_address,
                f"Check-In: Date={business_date} | Source={source} | Late={eval_result.is_late} ({eval_result.late_minutes}m) | GPS={payload.latitude},{payload.longitude}",
                company_id=actual_company_id
            )
        except Exception:
            pass
        
        return record

    async def notify_missed_checkout(self, attendance_id: uuid.UUID) -> None:
        """Emit notification for missed check-out."""
        from app.models.employee import Employee
        from app.services import notification_service
        record = await self.session.get(Attendance, attendance_id)
        if not record or not record.company_id:
            return
        emp = await self.session.get(Employee, record.employee_id)
        recipients = []
        if emp and emp.user_id:
            recipients.append(emp.user_id)
        if emp and (emp.reporting_manager_id or emp.manager_id):
            mgr = await self.session.get(Employee, emp.reporting_manager_id or emp.manager_id)
            if mgr and mgr.user_id:
                recipients.append(mgr.user_id)
        if recipients:
            await notification_service.notify(
                self.session,
                company_id=record.company_id,
                recipient_ids=recipients,
                type="attendance.missed_checkout",
                category="attendance",
                module="attendance",
                title="Missed Check-Out Detected",
                body=f"Missed check-out recorded for {record.date.isoformat()}.",
                link="/dashboard/attendance",
                priority="normal",
                entity={"type": "attendance", "id": str(record.id)},
                dedupe_key=f"attendance:{record.id}:missed_checkout",
            )
            await self.session.commit()

    async def check_out(
        self,
        employee_id: uuid.UUID,
        company_id: uuid.UUID | None,
        payload: AttendanceCheckOutRequest,
    ) -> Attendance:
        now = datetime.now(UTC)
        
        # Get employee to access company_id and shift
        emp = await self.session.get(Employee, employee_id)
        if not emp:
            raise ValueError("Employee not found")
        
        actual_company_id = company_id or emp.company_id
        if not actual_company_id:
            raise ValueError("Company context required")
        
        # Find the active record (might be from previous day for night shifts)
        # Check today and yesterday
        tz = await get_company_tz(self.session, str(actual_company_id))
        today = now.astimezone(tz).date()
        yesterday = today - timedelta(days=1)
        
        record = await self.get_today_record(employee_id, today)
        if not record:
            record = await self.get_today_record(employee_id, yesterday)
        
        # Use shift service for proper checkout evaluation
        shift_service = ShiftService(self.session)
        
        if not record:
            # No check-in record - create one with check-in = check-out = now (0 hours)
            resolved, business_date = await shift_service.resolve_for_timestamp(emp, now, tz)
            record = Attendance(
                id=uuid.uuid4(),
                employee_id=employee_id,
                company_id=actual_company_id,
                date=business_date,
                check_in_time=now,
                check_out_time=now,
                status="Present",
                punch_type="OUT",
                verified=True,
                punch_verified_by="MANUAL",
                attendance_state=AttendanceState.CHECKED_OUT,
                latitude=payload.latitude,
                longitude=payload.longitude,
                ip_address=payload.ip_address,
                device_info=payload.device_info,
                notes=payload.notes,
                working_hours=0.0,
                shift_id=resolved.shift_id,
                shift_name=resolved.shift_name,
                shift_source=resolved.source,
                scheduled_start=resolved.start_dt,
                scheduled_end=resolved.end_dt,
                is_off_day_work=resolved.is_off,
                is_holiday_work=resolved.is_holiday,
            )
            self.session.add(record)
        else:
            # Evaluate checkout using shift snapshot from check-in
            logged_break_hours = record.break_duration or 0.0
            if record.scheduled_start and record.scheduled_end:
                from app.attendance.services.shift_service import ResolvedShift
                resolved = ResolvedShift(
                    shift_id=record.shift_id,
                    shift_name=record.shift_name or "Unknown",
                    source=record.shift_source or "unknown",
                    business_date=record.date,
                    start_dt=record.scheduled_start,
                    end_dt=record.scheduled_end,
                    is_overnight=record.scheduled_end.date() > record.scheduled_start.date(),
                    grace_period_mins=15,
                    break_duration_mins=int((record.break_duration or 0) * 60),
                    scheduled_gross_hours=round((record.scheduled_end - record.scheduled_start).total_seconds() / 3600.0, 2),
                    scheduled_net_hours=round(max(0, ((record.scheduled_end - record.scheduled_start).total_seconds() / 3600.0) - (record.break_duration or 0)), 2),
                    is_off=record.is_off_day_work,
                    off_reason=None,
                    is_holiday=record.is_holiday_work,
                    holiday_name=None,
                    night_shift=False,
                    night_premium_percent=0.0,
                    working_days=[],
                )
            else:
                # Re-resolve if no snapshot
                resolved, _ = await shift_service.resolve_for_timestamp(emp, record.check_in_time, tz)
            
            eval_result = shift_service.evaluate_checkout(resolved, record.check_in_time, now, logged_break_hours)
            
            record.check_out_time = now
            record.punch_type = "OUT"
            record.attendance_state = AttendanceState.CHECKED_OUT
            record.working_hours = eval_result.working_hours
            record.is_early_checkout = eval_result.is_early_checkout
            record.early_minutes = eval_result.early_minutes
            record.overtime_hours = eval_result.overtime_hours
            if payload.latitude is not None:
                record.latitude = payload.latitude
            if payload.longitude is not None:
                record.longitude = payload.longitude
            if payload.notes:
                record.notes = f"{record.notes or ''}; Out: {payload.notes}"

        await self.session.commit()
        await self.session.refresh(record)
        
        # Audit log
        try:
            user_id_for_audit = emp.user_id if emp else None
            await write_audit_log(
                self.session, user_id_for_audit, "CHECK_OUT", payload.ip_address,
                f"Check-Out: Date={record.date} | NetHours={eval_result.working_hours} | Overtime={eval_result.overtime_hours}h | Early={eval_result.is_early_checkout} ({eval_result.early_minutes}m) | GPS={payload.latitude},{payload.longitude}",
                company_id=actual_company_id
            )
        except Exception:
            pass
        
        return record

    async def update_attendance(
        self,
        attendance_id: uuid.UUID,
        payload: AttendanceManualUpdateRequest,
        editor_id: uuid.UUID | None = None,
        requester_company_id: uuid.UUID | None = None,
    ) -> Attendance:
        stmt = select(Attendance).where(Attendance.id == attendance_id)
        res = await self.session.execute(stmt)
        record = res.scalar_one_or_none()
        if not record:
            raise ValueError("Attendance record not found")
        
        # Validate company ownership
        if requester_company_id is not None and record.company_id != requester_company_id:
            raise ValueError("Attendance record not found")
        
        await assert_attendance_period_editable(
            self.session, record.company_id, record.date, action="modify locked attendance"
        )

        if payload.check_in_time is not None:
            record.check_in_time = payload.check_in_time
        if payload.check_out_time is not None:
            record.check_out_time = payload.check_out_time
            if record.check_in_time:
                record.working_hours = round(
                    (record.check_out_time - record.check_in_time).total_seconds() / 3600.0, 2
                )
        if payload.status is not None:
            record.status = payload.status

        record.notes = f"{record.notes or ''}; Edited by {editor_id or 'admin'}: {payload.audit_reason}"
        await self.session.commit()
        await self.session.refresh(record)
        
        # Audit log
        try:
            await write_audit_log(
                self.session, editor_id, "ATTENDANCE_UPDATE", None,
                f"Attendance updated: ID={attendance_id} | Reason={payload.audit_reason}",
                company_id=record.company_id
            )
        except Exception:
            pass
        
        return record

    async def delete_attendance(
        self, 
        attendance_id: uuid.UUID, 
        requester_company_id: uuid.UUID | None = None
    ) -> bool:
        stmt = select(Attendance).where(Attendance.id == attendance_id)
        res = await self.session.execute(stmt)
        record = res.scalar_one_or_none()
        if not record:
            return False
        
        # Validate company ownership
        if requester_company_id is not None and record.company_id != requester_company_id:
            return False
        
        await assert_attendance_period_editable(
            self.session, record.company_id, record.date, action="delete locked attendance"
        )
        company_id = record.company_id
        await self.session.delete(record)
        await self.session.commit()
        
        # Audit log
        try:
            await write_audit_log(
                self.session, None, "ATTENDANCE_DELETE", None,
                f"Attendance deleted: ID={attendance_id}",
                company_id=company_id
            )
        except Exception:
            pass
        
        return True

    async def list_records(
        self,
        company_id: uuid.UUID | None = None,
        employee_id: uuid.UUID | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
        status: str | None = None,
        page: int = 1,
        limit: int = 20,
    ) -> dict[str, Any]:
        stmt = select(Attendance)
        if company_id:
            stmt = stmt.where(Attendance.company_id == company_id)
        if employee_id:
            stmt = stmt.where(Attendance.employee_id == employee_id)
        if from_date:
            stmt = stmt.where(Attendance.date >= from_date)
        if to_date:
            stmt = stmt.where(Attendance.date <= to_date)
        if status:
            stmt = stmt.where(Attendance.status.ilike(status))

        total_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.execute(total_stmt)).scalar() or 0

        stmt = stmt.order_by(desc(Attendance.date)).offset((page - 1) * limit).limit(limit)
        items = (await self.session.execute(stmt)).scalars().all()

        return {
            "total": total,
            "page": page,
            "limit": limit,
            "items": [
                {
                    "id": str(i.id),
                    "employee_id": str(i.employee_id),
                    "date": i.date.isoformat(),
                    "check_in_time": i.check_in_time.isoformat() if i.check_in_time else None,
                    "check_out_time": i.check_out_time.isoformat() if i.check_out_time else None,
                    "status": i.status,
                    "is_late": i.is_late or False,
                    "late_minutes": i.late_minutes or 0,
                    "working_hours": float(i.working_hours or 0.0),
                    "notes": i.notes,
                }
                for i in items
            ],
        }

    async def get_analytics(self, company_id: uuid.UUID | None, target_date: date | None = None) -> dict[str, Any]:
        t_date = target_date or date.today()
        
        # Get total active employees for the company
        from app.models.employee import Employee
        from sqlalchemy import and_
        emp_stmt = select(func.count(Employee.id)).where(
            and_(Employee.company_id == company_id, Employee.is_deleted == False, Employee.status == "ACTIVE")
        ) if company_id else select(func.count(Employee.id))
        emp_res = await self.session.execute(emp_stmt)
        total_active = emp_res.scalar() or 0
        
        # Get attendance records for the date
        stmt = select(Attendance).where(Attendance.date == t_date)
        if company_id:
            stmt = stmt.where(Attendance.company_id == company_id)
        records = (await self.session.execute(stmt)).scalars().all()

        total_marked = len(records)
        present = sum(1 for r in records if (r.status or "").lower() in ("present", "late"))
        late = sum(1 for r in records if r.is_late or (r.status or "").lower() == "late")
        avg_hours = sum(float(r.working_hours or 0) for r in records) / total_marked if total_marked > 0 else 0.0
        
        # Attendance rate should be based on total active employees, not just marked
        attendance_rate = round((present / total_active) * 100, 2) if total_active > 0 else 0.0
        
        # Calculate absent employees
        absent = max(0, total_active - present)

        return {
            "date": t_date.isoformat(),
            "total_active_employees": total_active,
            "total_marked": total_marked,
            "present": present,
            "absent": absent,
            "late": late,
            "average_working_hours": round(avg_hours, 2),
            "attendance_rate": attendance_rate,
        }

    async def create_regularization(
        self,
        employee_id: uuid.UUID,
        company_id: uuid.UUID | None,
        payload: AttendanceRegularizationCreateRequest,
    ) -> AttendanceRegularizationRequest:
        await assert_attendance_period_editable(
            self.session, company_id, payload.request_date, action="submit attendance regularisation"
        )
        req = AttendanceRegularizationRequest(
            id=uuid.uuid4(),
            attendance_id=payload.attendance_id,
            employee_id=employee_id,
            company_id=company_id,
            request_date=payload.request_date,
            requested_check_in=payload.requested_check_in,
            requested_check_out=payload.requested_check_out,
            reason=payload.reason,
            status="PENDING",
        )
        self.session.add(req)
        
        # Update attendance record state to CORRECTION_PENDING
        if payload.attendance_id:
            record = await self.session.get(Attendance, payload.attendance_id)
            if record is not None:
                record.attendance_state = AttendanceState.CORRECTION_PENDING
        
        await self.session.commit()
        await self.session.refresh(req)
        return req

    async def review_regularization(
        self,
        regularization_id: uuid.UUID,
        *,
        decision: str,
        reviewer_id: uuid.UUID | None = None,
        reviewer_role: str = "hr_admin",
        reviewer_company_id: uuid.UUID | None = None,
        remarks: str | None = None,
        delta_days=1,
        amount_paise: int | None = None,
    ) -> AttendanceRegularizationRequest:
        """Approve/reject a correction, creating arrears for a closed period."""
        from app.models.payroll_models import PayrollPeriod
        from app.services.payroll.arrear_service import ArrearService

        req = await self.session.get(AttendanceRegularizationRequest, regularization_id)
        if req is None:
            raise ValueError("Regularisation request not found")
        if reviewer_company_id is not None and req.company_id != reviewer_company_id:
            raise ValueError("Regularisation request not found")
        if req.status != "PENDING":
            raise ValueError("Regularisation request is not pending")
        decision = decision.upper()
        if decision not in {"APPROVED", "REJECTED"}:
            raise ValueError("Decision must be APPROVED or REJECTED")
        period = await assert_attendance_period_editable(
            self.session, req.company_id, req.request_date,
            action="review retroactive attendance regularisation",
            allow_retroactive=True, actor_role=reviewer_role,
        )
        was_closed = attendance_period_block_reason(period) is not None
        req.status = decision
        req.approver_id = reviewer_id
        req.approved_at = datetime.now(UTC)
        req.remarks = remarks
        if decision == "APPROVED":
            if req.attendance_id:
                record = await self.session.get(Attendance, req.attendance_id)
                if record is not None:
                    if req.requested_check_in is not None:
                        record.check_in_time = req.requested_check_in
                    if req.requested_check_out is not None:
                        record.check_out_time = req.requested_check_out
                    # Update state to CORRECTED
                    record.attendance_state = AttendanceState.CORRECTED
                    # Recalculate working hours if both times present
                    if record.check_in_time and record.check_out_time:
                        delta = record.check_out_time - record.check_in_time
                        record.working_hours = round(delta.total_seconds() / 3600.0, 2)
            if was_closed:
                source_id = period.id if isinstance(period, PayrollPeriod) else None
                await ArrearService.create_arrear(
                    self.session, employee_id=req.employee_id, company_id=req.company_id,
                    source_period_id=source_id, arrear_type="ATTENDANCE_RETRO",
                    delta_days=delta_days, amount_paise=amount_paise,
                    calculation_json={"regularisation_id": str(req.id), "request_date": req.request_date.isoformat()},
                    created_by=reviewer_id,
                )
        await self.session.commit()
        await self.session.refresh(req)
        return req

    async def list_regularizations(
        self,
        company_id: uuid.UUID | None = None,
        employee_id: uuid.UUID | None = None,
        status: str | None = None,
        page: int = 1,
        limit: int = 20,
    ) -> dict[str, Any]:
        stmt = select(AttendanceRegularizationRequest)
        if company_id:
            stmt = stmt.where(AttendanceRegularizationRequest.company_id == company_id)
        if employee_id:
            stmt = stmt.where(AttendanceRegularizationRequest.employee_id == employee_id)
        if status:
            stmt = stmt.where(AttendanceRegularizationRequest.status == status)

        total_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.execute(total_stmt)).scalar() or 0

        stmt = stmt.order_by(desc(AttendanceRegularizationRequest.created_at)).offset((page - 1) * limit).limit(limit)
        items = (await self.session.execute(stmt)).scalars().all()

        return {
            "total": total,
            "page": page,
            "limit": limit,
            "items": [
                {
                    "id": str(i.id),
                    "employee_id": str(i.employee_id),
                    "request_date": i.request_date.isoformat(),
                    "requested_check_in": i.requested_check_in.isoformat() if i.requested_check_in else None,
                    "requested_check_out": i.requested_check_out.isoformat() if i.requested_check_out else None,
                    "reason": i.reason,
                    "status": i.status,
                    "created_at": i.created_at.isoformat(),
                }
                for i in items
            ],
        }

    async def get_analytics_trends(
        self,
        company_id: uuid.UUID | None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> dict[str, Any]:
        """Get attendance trends over a date range (daily attendance rates)."""
        to_d = to_date or date.today()
        from_d = from_date or (to_d - timedelta(days=29))
        stmt = select(Attendance).where(Attendance.date >= from_d, Attendance.date <= to_d)
        if company_id:
            stmt = stmt.where(Attendance.company_id == company_id)
        records = (await self.session.execute(stmt)).scalars().all()

        # Group by date
        from collections import defaultdict
        daily_data = defaultdict(lambda: {"total": 0, "present": 0, "late": 0, "hours": 0.0})
        for r in records:
            d = r.date.isoformat()
            daily_data[d]["total"] += 1
            if (r.status or "").lower() in ("present", "late"):
                daily_data[d]["present"] += 1
            if r.is_late or (r.status or "").lower() == "late":
                daily_data[d]["late"] += 1
            daily_data[d]["hours"] += float(r.working_hours or 0)

        trends = []
        for d in sorted(daily_data.keys()):
            data = daily_data[d]
            rate = round((data["present"] / data["total"]) * 100, 2) if data["total"] > 0 else 0.0
            trends.append({
                "date": d,
                "total_marked": data["total"],
                "present": data["present"],
                "late": data["late"],
                "attendance_rate": rate,
                "average_working_hours": round(data["hours"] / data["total"], 2) if data["total"] > 0 else 0.0,
            })

        return {
            "from_date": from_d.isoformat(),
            "to_date": to_d.isoformat(),
            "trends": trends,
        }

    async def get_analytics_rate(
        self,
        company_id: uuid.UUID | None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> dict[str, Any]:
        """Get overall attendance rate for a date range."""
        to_d = to_date or date.today()
        from_d = from_date or (to_d - timedelta(days=29))
        stmt = select(Attendance).where(Attendance.date >= from_d, Attendance.date <= to_d)
        if company_id:
            stmt = stmt.where(Attendance.company_id == company_id)
        records = (await self.session.execute(stmt)).scalars().all()

        total = len(records)
        present = sum(1 for r in records if (r.status or "").lower() in ("present", "late"))
        late = sum(1 for r in records if r.is_late or (r.status or "").lower() == "late")
        avg_hours = sum(float(r.working_hours or 0) for r in records) / total if total > 0 else 0.0

        return {
            "from_date": from_d.isoformat(),
            "to_date": to_d.isoformat(),
            "total_records": total,
            "present": present,
            "late": late,
            "absent": total - present,
            "attendance_rate": round((present / total) * 100, 2) if total > 0 else 0.0,
            "average_working_hours": round(avg_hours, 2),
        }

    async def get_analytics_weekly(
        self,
        company_id: uuid.UUID | None,
        weeks: int = Query(4, ge=1, le=12),
    ) -> dict[str, Any]:
        """Get weekly aggregated attendance data."""
        to_d = date.today()
        from_d = to_d - timedelta(weeks=weeks)
        stmt = select(Attendance).where(Attendance.date >= from_d, Attendance.date <= to_d)
        if company_id:
            stmt = stmt.where(Attendance.company_id == company_id)
        records = (await self.session.execute(stmt)).scalars().all()

        # Group by ISO week
        from collections import defaultdict
        weekly_data = defaultdict(lambda: {"total": 0, "present": 0, "late": 0, "hours": 0.0, "days": set()})
        for r in records:
            iso_week = r.date.isocalendar()
            week_key = f"{iso_week.year}-W{iso_week.week:02d}"
            weekly_data[week_key]["total"] += 1
            weekly_data[week_key]["days"].add(r.date)
            if (r.status or "").lower() in ("present", "late"):
                weekly_data[week_key]["present"] += 1
            if r.is_late or (r.status or "").lower() == "late":
                weekly_data[week_key]["late"] += 1
            weekly_data[week_key]["hours"] += float(r.working_hours or 0)

        weekly = []
        for wk in sorted(weekly_data.keys()):
            data = weekly_data[wk]
            working_days = len(data["days"])
            rate = round((data["present"] / data["total"]) * 100, 2) if data["total"] > 0 else 0.0
            weekly.append({
                "week": wk,
                "working_days": working_days,
                "total_records": data["total"],
                "present": data["present"],
                "late": data["late"],
                "attendance_rate": rate,
                "average_working_hours": round(data["hours"] / data["total"], 2) if data["total"] > 0 else 0.0,
            })

        return {
            "weeks": weeks,
            "from_date": from_d.isoformat(),
            "to_date": to_d.isoformat(),
            "weekly": weekly,
        }

    async def get_calendar(
        self,
        company_id: uuid.UUID,
        month: int,
        year: int,
    ) -> dict[str, Any]:
        """Calculate actual calendar data for a given month/year."""
        from calendar import monthrange
        from datetime import date, timedelta
        from sqlalchemy import select, and_
        from app.models.calendar.holiday import HolidayCalendar
        from app.models.employee import Employee
        from app.models.shift import Shift
        from app.attendance.models.attendance import Attendance
        from app.attendance.services.shift_service import ShiftService
        from app.attendance.utils.timezone import get_company_tz
        
        # Get company timezone
        tz = await get_company_tz(self.session, str(company_id))
        
        # Calculate date range for the month
        first_day = date(year, month, 1)
        last_day_num = monthrange(year, month)[1]
        last_day = date(year, month, last_day_num)
        
        # Get holidays for this company/month
        holiday_stmt = select(HolidayCalendar).where(
            and_(
                HolidayCalendar.company_id == company_id,
                HolidayCalendar.holiday_date >= first_day,
                HolidayCalendar.holiday_date <= last_day,
            )
        )
        holiday_res = await self.session.execute(holiday_stmt)
        holidays = holiday_res.scalars().all()
        holiday_dates = {h.holiday_date for h in holidays}
        holiday_names = {h.holiday_date: h.holiday_name for h in holidays}
        
        # Get default shift for company to determine working days
        shift_service = ShiftService(self.session)
        default_shift = await shift_service._get_default_shift(company_id)
        
        working_days = 0
        holiday_count = len(holiday_dates)
        daily_data = []
        
        current = first_day
        while current <= last_day:
            is_weekend = current.weekday() >= 5  # Sat=5, Sun=6
            is_holiday = current in holiday_dates
            
            # Determine if it's a working day
            is_working_day = False
            if default_shift:
                weekday_abbr = current.strftime("%a")
                is_working_day = weekday_abbr in default_shift.working_days and not is_holiday
            else:
                # Fallback: Mon-Fri, not holiday
                is_working_day = not is_weekend and not is_holiday
            
            if is_working_day:
                working_days += 1
            
            daily_data.append({
                "date": current.isoformat(),
                "day": current.strftime("%a"),
                "is_working_day": is_working_day,
                "is_holiday": is_holiday,
                "holiday_name": holiday_names.get(current),
                "is_weekend": is_weekend,
            })
            
            current += timedelta(days=1)
        
        return {
            "month": month,
            "year": year,
            "working_days": working_days,
            "holidays": holiday_count,
            "total_days": last_day_num,
            "daily": daily_data,
            "calendar_summary": f"Calculated from company shifts and {holiday_count} holidays",
        }
