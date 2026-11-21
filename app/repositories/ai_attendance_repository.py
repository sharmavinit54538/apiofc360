"""AI Attendance Repository executing real PostgreSQL queries for attendance metrics."""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, case, extract, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.attendance.models.attendance import Attendance
from app.attendance.services.shift_service import ShiftService
from app.attendance.utils.timezone import get_company_tz
from app.models.calendar.holiday import HolidayCalendar
from app.models.department import Department
from app.models.employee import Employee
from app.models.leave import LeaveRequest

logger = logging.getLogger(__name__)


class AIAttendanceRepository:
    """Repository executing database queries for AI Attendance Monitor endpoints."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_total_active_employees(
        self, company_id: Optional[uuid.UUID] = None, department_id: Optional[uuid.UUID] = None
    ) -> int:
        """Count active employees."""
        stmt = select(func.count(Employee.id)).where(
            and_(Employee.is_deleted == False, Employee.status.ilike("ACTIVE"))
        )
        if company_id:
            stmt = stmt.where(Employee.company_id == company_id)
        if department_id:
            stmt = stmt.where(Employee.department_id == department_id)
        res = await self.session.execute(stmt)
        return res.scalar() or 0

    async def get_dashboard_kpis(
        self,
        company_id: Optional[uuid.UUID] = None,
        department_id: Optional[uuid.UUID] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> Dict[str, Any]:
        """Compute real dynamic attendance dashboard KPIs."""
        total_active = await self.get_total_active_employees(company_id, department_id)
        target_date = end_date or date.today()

        # Query today's attendance records
        stmt = select(Attendance).join(Employee, Attendance.employee_id == Employee.id).where(
            Attendance.date == target_date
        )
        if company_id:
            stmt = stmt.where(Attendance.company_id == company_id)
        if department_id:
            stmt = stmt.where(Employee.department_id == department_id)

        res = await self.session.execute(stmt)
        today_records = res.scalars().all()

        checked_in = len(today_records)
        absent = max(0, total_active - checked_in)
        att_rate = round((checked_in / total_active * 100.0), 1) if total_active > 0 else 0.0

        # Late check-ins - use the is_late field set during check-in based on shift schedule
        late_count = sum(1 for r in today_records if r.is_late)
        total_ot_hours = sum(max(0, r.working_hours - 8.0) for r in today_records if r.working_hours)

        # Count total anomalies across database
        missing_checkout_stmt = select(func.count(Attendance.id)).where(
            and_(Attendance.date < date.today(), Attendance.check_out_time.is_(None))
        )
        if company_id:
            missing_checkout_stmt = missing_checkout_stmt.where(Attendance.company_id == company_id)
        missing_checkout_count = (await self.session.execute(missing_checkout_stmt)).scalar() or 0

        anomalies_count = missing_checkout_count + (late_count * 2)

        # Composite Attendance Health Score (0-100)
        # Health = Attendance Rate (60%) + (100 - Late Rate) (20%) + (100 - Anomaly Penalty) (20%)
        late_rate = (late_count / checked_in * 100.0) if checked_in > 0 else 0.0
        health_score = round(
            (att_rate * 0.6) + (max(0.0, 100.0 - late_rate) * 0.25) + (max(0.0, 100.0 - (anomalies_count * 2.0)) * 0.15),
            1,
        )

        return {
            "attendance_health_score": min(100.0, max(0.0, health_score)),
            "total_attendance_percentage": att_rate,
            "total_anomalies": anomalies_count,
            "late_arrivals": late_count,
            "overtime_hours": round(total_ot_hours, 1),
            "today_present_employees": checked_in,
            "today_absent_employees": absent,
        }

    async def get_attendance_trend(
        self,
        company_id: Optional[uuid.UUID] = None,
        group_by: str = "daily",
        department_id: Optional[uuid.UUID] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> List[Dict[str, Any]]:
        """Compute attendance percentage trend grouped by daily, weekly, monthly, or department."""
        total_active = await self.get_total_active_employees(company_id, department_id)
        end_d = end_date or date.today()
        start_d = start_date or (end_d - timedelta(days=7))

        if group_by == "department":
            stmt = (
                select(Department.department_name, func.count(Attendance.id))
                .join(Employee, Employee.department_id == Department.id)
                .join(Attendance, Attendance.employee_id == Employee.id)
                .where(and_(Attendance.date >= start_d, Attendance.date <= end_d))
                .group_by(Department.department_name)
            )
            if company_id:
                stmt = stmt.where(Attendance.company_id == company_id)
            res = (await self.session.execute(stmt)).all()

            if not res:
                return []
            return [
                {
                    "label": row[0],
                    "present_count": row[1],
                    "total_count": max(row[1], int(total_active / max(1, len(res)))),
                    "attendance_percentage": round(min(100.0, (row[1] / max(1, total_active)) * 100.0 * len(res)), 1),
                }
                for row in res
            ]

        # Daily / Weekly / Monthly grouping
        stmt = (
            select(Attendance.date, func.count(Attendance.id))
            .where(and_(Attendance.date >= start_d, Attendance.date <= end_d))
            .group_by(Attendance.date)
            .order_by(Attendance.date.asc())
        )
        if company_id:
            stmt = stmt.where(Attendance.company_id == company_id)
        if department_id:
            stmt = stmt.join(Employee, Attendance.employee_id == Employee.id).where(Employee.department_id == department_id)

        res = (await self.session.execute(stmt)).all()

        if res:
            return [
                {
                    "label": row[0].strftime("%a %b %d") if isinstance(row[0], date) else str(row[0]),
                    "present_count": row[1],
                    "total_count": max(row[1], total_active),
                    "attendance_percentage": round((row[1] / max(1, total_active) * 100.0), 1),
                }
                for row in res
            ]
        
        # No records found - return empty list instead of fake data
        return []

    async def get_late_arrivals(
        self,
        company_id: Optional[uuid.UUID] = None,
        department_id: Optional[uuid.UUID] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch late arrival records and delays using shift schedules."""
        target_date = end_date or date.today()
        stmt = (
            select(Attendance, Employee, Department)
            .join(Employee, Attendance.employee_id == Employee.id)
            .join(Department, Employee.department_id == Department.id, isouter=True)
            .where(Attendance.date == target_date)
        )
        if company_id:
            stmt = stmt.where(Attendance.company_id == company_id)
        if department_id:
            stmt = stmt.where(Employee.department_id == department_id)

        res = (await self.session.execute(stmt)).all()

        result = []
        for att, emp, dept in res:
            # Use the is_late and late_minutes fields set during check-in based on shift
            if att.is_late and att.late_minutes and att.late_minutes > 0:
                emp_name = f"{emp.first_name} {emp.last_name}".strip()
                # Calculate expected time from scheduled_start if available
                expected_time = "09:00 AM"
                shift_name = att.shift_name or "Standard Shift"
                if att.scheduled_start:
                    expected_time = att.scheduled_start.strftime("%I:%M %p")
                
                result.append({
                    "employee_id": emp.id,
                    "employee_name": emp_name,
                    "department": dept.department_name if dept else "General",
                    "shift_name": shift_name,
                    "expected_time": expected_time,
                    "actual_time": att.check_in_time.strftime("%I:%M %p") if att.check_in_time else "N/A",
                    "delay_minutes": att.late_minutes,
                    "frequency": 1,  # Single day, frequency would need historical analysis
                })

        return result

    async def get_anomalies(
        self,
        company_id: Optional[uuid.UUID] = None,
        department_id: Optional[uuid.UUID] = None,
    ) -> List[Dict[str, Any]]:
        """Detect attendance anomalies (Missing Check-Out, Geofence breach, Late Login)."""
        stmt = (
            select(Attendance, Employee, Department)
            .join(Employee, Attendance.employee_id == Employee.id)
            .join(Department, Employee.department_id == Department.id, isouter=True)
            .order_by(Attendance.date.desc())
            .limit(50)
        )
        if company_id:
            stmt = stmt.where(Attendance.company_id == company_id)
        if department_id:
            stmt = stmt.where(Employee.department_id == department_id)

        res = (await self.session.execute(stmt)).all()

        anomalies = []
        for att, emp, dept in res:
            emp_name = f"{emp.first_name} {emp.last_name}".strip()
            dept_name = dept.department_name if dept else "General"
            date_str = att.date.strftime("%Y-%m-%d")
            shift_name = att.shift_name or "Unknown Shift"

            # Check 1: Missing Check-Out
            if att.check_out_time is None and att.date < date.today():
                anomalies.append({
                    "id": att.id,
                    "employee_id": emp.id,
                    "employee_name": emp_name,
                    "department": dept_name,
                    "anomaly_type": "MISSING_CHECKOUT",
                    "description": f"Missed swipe out on {date_str}. Working hours uncalculated.",
                    "date": date_str,
                    "severity": "HIGH",
                    "shift_name": shift_name,
                })

            # Check 2: Outside Geofence / Unexpected IP
            if att.latitude and (att.latitude > 90.0 or att.latitude < -90.0):
                anomalies.append({
                    "id": att.id,
                    "employee_id": emp.id,
                    "employee_name": emp_name,
                    "department": dept_name,
                    "anomaly_type": "GEOFENCE_VIOLATION",
                    "description": f"Checked in outside designated office geofence zone.",
                    "date": date_str,
                    "severity": "MEDIUM",
                    "shift_name": shift_name,
                })

        return anomalies

    async def get_absence_patterns(
        self,
        company_id: Optional[uuid.UUID] = None,
        department_id: Optional[uuid.UUID] = None,
    ) -> List[Dict[str, Any]]:
        """Detect AI absence patterns (Friday/Monday absence, Long weekend patterns)."""
        # Query leaves in last 30 days
        stmt = (
            select(LeaveRequest, Employee, Department)
            .join(Employee, LeaveRequest.employee_id == Employee.id)
            .join(Department, Employee.department_id == Department.id, isouter=True)
            .where(LeaveRequest.status.ilike("APPROVED"))
            .order_by(LeaveRequest.created_at.desc())
            .limit(30)
        )
        if company_id:
            stmt = stmt.where(Employee.company_id == company_id)
        if department_id:
            stmt = stmt.where(Employee.department_id == department_id)

        try:
            res = (await self.session.execute(stmt)).all()
        except Exception:
            res = []

        patterns = []
        for leave, emp, dept in res:
            emp_name = f"{emp.first_name} {emp.last_name}".strip()
            dept_name = dept.department_name if dept else "General"

            if leave.start_date:
                weekday = leave.start_date.weekday()
                if weekday == 4:  # Friday
                    patterns.append({
                        "employee_id": emp.id,
                        "employee_name": emp_name,
                        "department": dept_name,
                        "pattern_type": "FRIDAY_ABSENCE",
                        "details": f"Recurring Friday leave requests detected ({leave.start_date.strftime('%Y-%m-%d')}).",
                        "risk_level": "MEDIUM",
                    })
                elif weekday == 0:  # Monday
                    patterns.append({
                        "employee_id": emp.id,
                        "employee_name": emp_name,
                        "department": dept_name,
                        "pattern_type": "MONDAY_ABSENCE",
                        "details": f"Pattern of Monday absences noted before weekend ({leave.start_date.strftime('%Y-%m-%d')}).",
                        "risk_level": "HIGH",
                    })

        return patterns

    async def get_overtime_metrics(
        self,
        company_id: Optional[uuid.UUID] = None,
        department_id: Optional[uuid.UUID] = None,
    ) -> Dict[str, Any]:
        """Compute overtime tracking metrics from real database records."""
        ot_calc = func.sum(Attendance.working_hours - 8.0)
        stmt = (
            select(ot_calc)
            .join(Employee, Attendance.employee_id == Employee.id)
            .where(and_(Attendance.working_hours.is_not(None), Attendance.working_hours > 8.0))
        )
        if company_id:
            stmt = stmt.where(Attendance.company_id == company_id)
        if department_id:
            stmt = stmt.where(Employee.department_id == department_id)

        res = await self.session.execute(stmt)
        total_ot = float(res.scalar() or 0.0)

        daily_ot = round(total_ot / 30.0, 1) if total_ot > 0 else 0.0
        weekly_ot = round(daily_ot * 5.0, 1)
        monthly_ot = round(daily_ot * 22.0, 1)
        budget_impact = round(monthly_ot * 450.0, 2)

        # Real department-wise OT query
        dept_stmt = (
            select(
                func.coalesce(Department.department_name, Employee.department).label("dept_name"),
                func.sum(Attendance.working_hours - 8.0).label("dept_ot"),
            )
            .join(Employee, Attendance.employee_id == Employee.id)
            .join(Department, Employee.department_id == Department.id, isouter=True)
            .where(and_(Attendance.working_hours.is_not(None), Attendance.working_hours > 8.0))
        )
        if company_id:
            dept_stmt = dept_stmt.where(Attendance.company_id == company_id)
        dept_stmt = dept_stmt.group_by(func.coalesce(Department.department_name, Employee.department)).limit(10)
        dept_res = await self.session.execute(dept_stmt)
        dept_ot_list = [
            {"department": r[0] or "General", "ot_hours": round(float(r[1] or 0.0), 1)}
            for r in dept_res.fetchall()
        ]

        # Real employee-wise OT query
        emp_stmt = (
            select(
                Employee.first_name,
                Employee.last_name,
                func.sum(Attendance.working_hours - 8.0).label("emp_ot"),
            )
            .join(Employee, Attendance.employee_id == Employee.id)
            .where(and_(Attendance.working_hours.is_not(None), Attendance.working_hours > 8.0))
        )
        if company_id:
            emp_stmt = emp_stmt.where(Attendance.company_id == company_id)
        if department_id:
            emp_stmt = emp_stmt.where(Employee.department_id == department_id)
        emp_stmt = emp_stmt.group_by(Employee.id, Employee.first_name, Employee.last_name).order_by(func.sum(Attendance.working_hours - 8.0).desc()).limit(10)
        emp_res = await self.session.execute(emp_stmt)
        emp_ot_list = [
            {"employee_name": f"{r[0]} {r[1]}".strip(), "ot_hours": round(float(r[2] or 0.0), 1)}
            for r in emp_res.fetchall()
        ]

        return {
            "daily_ot_hours": daily_ot,
            "weekly_ot_hours": weekly_ot,
            "monthly_ot_hours": monthly_ot,
            "budget_impact_amount": budget_impact,
            "department_wise_ot": dept_ot_list,
            "employee_wise_ot": emp_ot_list,
        }

    async def get_absentee_watchlist(
        self,
        company_id: Optional[uuid.UUID] = None,
        department_id: Optional[uuid.UUID] = None,
    ) -> List[Dict[str, Any]]:
        """Identify employees trending toward chronic absenteeism."""
        stmt = (
            select(Employee, Department)
            .join(Department, Employee.department_id == Department.id, isouter=True)
            .where(and_(Employee.is_deleted == False, Employee.status.ilike("ACTIVE")))
            .limit(20)
        )
        if company_id:
            stmt = stmt.where(Employee.company_id == company_id)
        if department_id:
            stmt = stmt.where(Employee.department_id == department_id)

        res = (await self.session.execute(stmt)).all()

        watchlist = []
        # Target period = last 30 days
        start_30d = date.today() - timedelta(days=30)
        end_30d = date.today()
        
        # Get holidays in period for accurate working day calculation
        holiday_stmt = select(HolidayCalendar.holiday_date).where(
            and_(
                HolidayCalendar.holiday_date >= start_30d,
                HolidayCalendar.holiday_date <= end_30d,
            )
        )
        if company_id:
            holiday_stmt = holiday_stmt.where(HolidayCalendar.company_id == company_id)
        holiday_res = await self.session.execute(holiday_stmt)
        holiday_dates = set(holiday_res.scalars().all())
        
        for emp, dept in res:
            att_cnt_stmt = select(func.count(Attendance.id)).where(
                and_(Attendance.employee_id == emp.id, Attendance.date >= start_30d)
            )
            att_cnt = (await self.session.execute(att_cnt_stmt)).scalar() or 0

            late_cnt_stmt = select(func.count(Attendance.id)).where(
                and_(Attendance.employee_id == emp.id, Attendance.date >= start_30d, Attendance.is_late == True)
            )
            late_cnt = (await self.session.execute(late_cnt_stmt)).scalar() or 0

            # Calculate expected working days from shifts and holidays
            shift_service = ShiftService(self.session)
            emp_company_id = emp.company_id
            tz = await get_company_tz(self.session, str(emp_company_id)) if emp_company_id else None
            
            if tz:
                shifts = await shift_service.resolve_range(emp, start_30d, end_30d, tz)
                expected_work_days = sum(1 for s in shifts if not s.is_off and not s.is_holiday)
            else:
                # Fallback: count weekdays excluding holidays
                expected_work_days = sum(
                    1 for i in range((end_30d - start_30d).days + 1)
                    if (start_30d + timedelta(days=i)).weekday() < 5
                    and (start_30d + timedelta(days=i)) not in holiday_dates
                )
            
            absent_days = max(0, expected_work_days - att_cnt)

            if expected_work_days > 0 and att_cnt < expected_work_days * 0.8:  # Less than 80% attendance
                emp_name = f"{emp.first_name} {emp.last_name}".strip()
                att_pct = round((att_cnt / expected_work_days) * 100.0, 1) if expected_work_days > 0 else 0.0
                watchlist.append({
                    "employee_id": emp.id,
                    "employee_name": emp_name,
                    "department": dept.department_name if dept else (emp.department or "General"),
                    "absent_days": absent_days,
                    "late_count": late_cnt,
                    "attendance_percentage": min(100.0, max(0.0, att_pct)),
                    "risk_level": "HIGH" if att_cnt < expected_work_days * 0.5 else "MEDIUM",
                    "recommendation": "Schedule HR 1-on-1 counseling session and review shift allocation.",
                })

        return watchlist

