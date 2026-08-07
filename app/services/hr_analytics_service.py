"""HR Analytics and Forecasting Engine Service.

Orchestrates demographics computation, diversity distributions, pay bands parity,
attrition risk scoring, and workforce forecasting using local LLM completions.
"""

from __future__ import annotations

import logging
import json
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.llm.client import get_llm_client
from app.llm.prompts import PromptLibrary
from app.llm.response_parser import ResponseParser

# Models
from app.models.employee import Employee
from app.models.payroll import SalaryStructure, PayrollAttendanceInput
from app.models.employee_leave_policy import EmployeeLeavePolicy
from app.models.ai_employee_support import SupportTicket
from app.models.hr_analytics import (
    HRAnalyticsSnapshot,
    HRAttritionRiskPrediction,
    HRForecastingRun,
)

logger = logging.getLogger(__name__)


class HRAnalyticsService:
    """Enterprise HR Analytics intelligence service."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.llm = get_llm_client()

    async def compute_analytics_snapshot(self, company_id: Optional[uuid.UUID] = None) -> HRAnalyticsSnapshot:
        """Query raw database tables to calculate metrics and cache a snapshot."""
        # 1. Basic metrics
        stmt = select(Employee).where(Employee.status == "ACTIVE", Employee.is_deleted == False)
        if company_id:
            stmt = stmt.where(Employee.company_id == company_id)
        emp_res = await self.db.execute(stmt)
        employees = emp_res.scalars().all()
        total_headcount = len(employees)

        total_tenure_days = 0
        now_dt = date.today()
        for emp in employees:
            joining = emp.joining_date or now_dt
            total_tenure_days += (now_dt - joining).days
        
        avg_tenure_months = 0.0
        if total_headcount > 0:
            avg_tenure_months = round((total_tenure_days / 30.4) / total_headcount, 2)

        # Overall attrition rate calculation
        term_stmt = select(Employee).where(Employee.status == "TERMINATED")
        if company_id:
            term_stmt = term_stmt.where(Employee.company_id == company_id)
        term_res = await self.db.execute(term_stmt)
        terminated_count = len(term_res.scalars().all())
        overall_attrition_rate = 0.0
        if total_headcount + terminated_count > 0:
            overall_attrition_rate = round((terminated_count / (total_headcount + terminated_count)) * 100, 2)

        # 2. Diversity Analytics (Gender & Department)
        gender_distribution = {}
        department_distribution = {}
        for emp in employees:
            gender = emp.gender or "UNKNOWN"
            gender_distribution[gender] = gender_distribution.get(gender, 0) + 1
            
            dept = emp.department or "General"
            department_distribution[dept] = department_distribution.get(dept, 0) + 1

        # Calculate actual average age from database
        age_stmt = select(Employee.date_of_birth).where(Employee.is_deleted == False, Employee.date_of_birth.isnot(None))
        if company_id:
            age_stmt = age_stmt.where(Employee.company_id == company_id)
        age_res = await self.db.execute(age_stmt)
        birthdays = age_res.scalars().all()
        avg_age = 0.0
        if birthdays:
            today = date.today()
            ages = [
                today.year - b.year - ((today.month, today.day) < (b.month, b.day))
                for b in birthdays
            ]
            avg_age = round(sum(ages) / len(ages), 1)

        diversity = {
            "gender_ratios": gender_distribution,
            "department_headcounts": department_distribution,
            "average_age": avg_age,
        }

        # 3. Salary Analytics (Parity, bands, budgets)
        sal_stmt = select(SalaryStructure).join(Employee, SalaryStructure.employee_id == Employee.id).where(Employee.is_deleted == False)
        if company_id:
            sal_stmt = sal_stmt.where(Employee.company_id == company_id)
        sal_res = await self.db.execute(sal_stmt)
        salaries = sal_res.scalars().all()
        
        dept_salaries = {}
        total_payroll_budget = 0.0
        for sal in salaries:
            emp_sal_res = await self.db.execute(select(Employee).where(Employee.id == sal.employee_id))
            emp_sal = emp_sal_res.scalar_one_or_none()
            dept_name = emp_sal.department if emp_sal else "General"
            monthly_gross = float(sal.basic_monthly or 0)
            total_payroll_budget += monthly_gross

            if dept_name not in dept_salaries:
                dept_salaries[dept_name] = []
            dept_salaries[dept_name].append(monthly_gross)

        dept_averages = {
            d: round(sum(vals) / len(vals), 2) if vals else 0.0
            for d, vals in dept_salaries.items()
        }

        # Calculate actual gender pay gap ratio from database salaries
        male_salaries = []
        female_salaries = []
        for sal in salaries:
            emp_sal_res = await self.db.execute(select(Employee).where(Employee.id == sal.employee_id))
            emp_sal = emp_sal_res.scalar_one_or_none()
            if emp_sal:
                val = float(sal.basic_monthly or 0)
                g = str(emp_sal.gender or "").upper().strip()
                if g == "MALE":
                    male_salaries.append(val)
                elif g == "FEMALE":
                    female_salaries.append(val)
        avg_m = sum(male_salaries) / len(male_salaries) if male_salaries else 0.0
        avg_f = sum(female_salaries) / len(female_salaries) if female_salaries else 0.0
        gender_pay_gap = round(abs(avg_m - avg_f) / avg_m, 4) if avg_m > 0 else 0.0

        salary_metrics = {
            "monthly_payroll_budget": total_payroll_budget,
            "department_salary_averages": dept_averages,
            "gender_pay_gap_ratio": gender_pay_gap,
        }

        # 4. Leave & Attendance Analytics
        leave_stmt = select(func.sum(EmployeeLeavePolicy.used_days)).join(Employee, EmployeeLeavePolicy.employee_id == Employee.id).where(Employee.is_deleted == False)
        if company_id:
            leave_stmt = leave_stmt.where(Employee.company_id == company_id)
        leave_res = await self.db.execute(leave_stmt)
        unplanned_count = float(leave_res.scalar() or 0.0)

        lop_stmt = select(func.avg(PayrollAttendanceInput.lop_days)).join(Employee, PayrollAttendanceInput.employee_id == Employee.id).where(Employee.is_deleted == False)
        if company_id:
            lop_stmt = lop_stmt.where(Employee.company_id == company_id)
        lop_res = await self.db.execute(lop_stmt)
        avg_lop_days = float(lop_res.scalar() or 0.0)

        # Calculate average working hours from timesheet entries dynamically
        avg_working_hours = 0.0
        try:
            from app.models.timesheet import TimesheetEntry
            ts_stmt = select(TimesheetEntry).join(Employee, TimesheetEntry.employee_id == Employee.id).where(Employee.is_deleted == False)
            if company_id:
                ts_stmt = ts_stmt.where(Employee.company_id == company_id)
            ts_res = await self.db.execute(ts_stmt)
            entries = ts_res.scalars().all()
            t_hours = 0.0
            t_days = 0
            for entry in entries:
                for day in ("monday_hours", "tuesday_hours", "wednesday_hours", "thursday_hours", "friday_hours", "saturday_hours", "sunday_hours"):
                    val = float(getattr(entry, day) or 0.0)
                    if val > 0.0:
                        t_hours += val
                        t_days += 1
            if t_days > 0:
                avg_working_hours = round(t_hours / t_days, 2)
        except Exception:
            pass

        # Calculate punctuality rate based on YTD working days passed
        punctuality_rate = 100.0
        if total_headcount > 0:
            days_passed_ytd = date.today().timetuple().tm_yday
            working_days_ytd = max(1, int(days_passed_ytd * (5 / 7)))
            total_working_days = total_headcount * working_days_ytd
            if total_working_days > 0 and unplanned_count > 0:
                punctuality_rate = max(0.0, round(100.0 * (total_working_days - unplanned_count) / total_working_days, 2))

        leave_attendance = {
            "unplanned_approved_leaves_ytd": int(unplanned_count),
            "average_daily_working_hours": avg_working_hours,
            "average_lop_days_per_month": avg_lop_days,
            "punctuality_rate_pct": punctuality_rate,
        }

        # Save Snapshot
        snapshot = HRAnalyticsSnapshot(
            id=uuid.uuid4(),
            snapshot_date=date.today(),
            total_headcount=total_headcount,
            average_tenure_months=avg_tenure_months,
            overall_attrition_rate=overall_attrition_rate,
            diversity_metrics=diversity,
            salary_metrics=salary_metrics,
            leave_attendance_metrics=leave_attendance,
        )
        self.db.add(snapshot)
        await self.db.commit()
        await self.db.refresh(snapshot)
        logger.info("HR Analytics snapshot generated: %s", snapshot.id)
        return snapshot

    async def predict_employee_attrition(
        self,
        employee_id: uuid.UUID,
        company_id: Optional[uuid.UUID] = None,
        model: Optional[str] = None,
    ) -> HRAttritionRiskPrediction:
        """Run AI classification to predict resignation risk parameters for an employee."""
        # 1. Fetch employee details
        stmt = select(Employee).where(Employee.id == employee_id, Employee.is_deleted == False)
        if company_id:
            stmt = stmt.where(Employee.company_id == company_id)
        res = await self.db.execute(stmt)
        employee = res.scalar_one_or_none()
        if not employee:
            raise ValueError("Employee not found.")

        # 2. Gather context
        profile_data = (
            f"Name: {employee.first_name} {employee.last_name}\n"
            f"Role: {employee.designation}\n"
            f"Department: {employee.department}\n"
            f"Joining Date: {employee.joining_date}\n"
            f"Status: {employee.employment_status}\n"
        )

        # Get leave history count from EmployeeLeavePolicy
        leaves_stmt = select(func.sum(EmployeeLeavePolicy.used_days)).where(
            EmployeeLeavePolicy.employee_id == employee_id
        )
        leaves_res = await self.db.execute(leaves_stmt)
        leaves_count = float(leaves_res.scalar() or 0.0)

        # Get payroll info
        salary_stmt = select(SalaryStructure).where(SalaryStructure.employee_id == employee_id)
        salary_res = await self.db.execute(salary_stmt)
        salary = salary_res.scalar_one_or_none()
        salary_val = float(salary.basic_monthly) if salary else 50000.0

        behavior_context = (
            f"Approved leaves YTD: {leaves_count}\n"
            f"Current Monthly Base Pay: {salary_val}\n"
            f"Estimated peer avg for {employee.designation}: {salary_val * 1.05}\n"
        )

        # 3. Call local LLM to get attrition prediction JSON
        try:
            prompt = PromptLibrary.hr_attrition_user(profile_data, behavior_context)
            res_text = await self.llm.complete(
                prompt=prompt,
                system=PromptLibrary.HR_ATTRITION_PREDICTION,
                model=model,
                json_mode=True,
                temperature=0.1
            )
            graded = ResponseParser.extract_json_object(res_text)
        except Exception as exc:
            logger.error("Attrition prediction failed: %s", exc)
            graded = {
                "risk_score": 0.0,
                "risk_level": "LOW",
                "top_risk_factors": [],
                "retention_recommendations": ""
            }

        # 4. Save Prediction record
        prediction = HRAttritionRiskPrediction(
            id=uuid.uuid4(),
            employee_id=employee_id,
            risk_score=graded.get("risk_score", 0.25),
            risk_level=graded.get("risk_level", "LOW"),
            top_risk_factors=graded.get("top_risk_factors"),
            retention_recommendations=graded.get("retention_recommendations"),
        )
        self.db.add(prediction)
        await self.db.commit()
        await self.db.refresh(prediction)
        logger.info("HR Attrition prediction completed for %s: Risk %s", employee_id, prediction.risk_level)
        return prediction

    async def run_ai_forecast(
        self,
        forecast_type: str,
        company_id: Optional[uuid.UUID] = None,
        months_ahead: int = 3,
        model: Optional[str] = None,
    ) -> HRForecastingRun:
        """Generate recruitment or payroll expense forecast metrics using LLM regression prompts."""
        forecast_type = forecast_type.upper()
        if forecast_type not in ("HEADCOUNT", "PAYROLL_EXPENSE", "RECRUITMENT_NEEDS"):
            raise ValueError("Invalid forecast type.")

        # Get active headcount baseline dynamically for the company
        emp_stmt = select(func.count(Employee.id)).where(Employee.status == "ACTIVE", Employee.is_deleted == False)
        if company_id:
            emp_stmt = emp_stmt.where(Employee.company_id == company_id)
        emp_res = await self.db.execute(emp_stmt)
        headcount = emp_res.scalar() or 0

        # Get payroll budget baseline dynamically for the company
        sal_stmt = select(func.sum(SalaryStructure.basic_monthly)).join(Employee, SalaryStructure.employee_id == Employee.id).where(Employee.is_deleted == False)
        if company_id:
            sal_stmt = sal_stmt.where(Employee.company_id == company_id)
        sal_res = await self.db.execute(sal_stmt)
        payroll_budget = float(sal_res.scalar() or 0.0)

        history_data = f"Current Active Headcount: {headcount}, Current Monthly Payroll Budget: {payroll_budget}"

        # Call forecasting compilation LLM
        try:
            prompt = PromptLibrary.hr_forecasting_user(forecast_type, history_data, months_ahead)
            res_text = await self.llm.complete(
                prompt=prompt,
                system=PromptLibrary.HR_FORECASTING_COMPILATION,
                model=model,
                json_mode=True,
                temperature=0.2
            )
            forecast = ResponseParser.extract_json_object(res_text)
        except Exception as exc:
            logger.error("Forecasting run failed: %s", exc)
            forecast = {
                "predicted_value": 0.0,
                "lower_confidence_bound": 0.0,
                "upper_confidence_bound": 0.0,
                "model_parameters": {"method": "No baseline history"}
            }

        target_date = date.today() + timedelta(days=30 * months_ahead)

        run = HRForecastingRun(
            id=uuid.uuid4(),
            forecast_type=forecast_type,
            forecast_target_date=target_date,
            predicted_value=forecast.get("predicted_value", 0.0),
            lower_confidence_bound=forecast.get("lower_confidence_bound", 0.0),
            upper_confidence_bound=forecast.get("upper_confidence_bound", 0.0),
            model_parameters=forecast.get("model_parameters"),
        )
        self.db.add(run)
        await self.db.commit()
        await self.db.refresh(run)
        logger.info("AI Forecast executed: Type %s, Date %s", forecast_type, target_date)
        return run

    async def get_executive_dashboard_summary(self, company_id: Optional[uuid.UUID] = None) -> dict[str, Any]:
        """Compile cached snapshots, forecasting metrics, and high-risk employee risk predictions."""
        # Calculate dynamic snapshot on the fly for the company
        snapshot = await self.compute_analytics_snapshot(company_id=company_id)

        # Get active high-risk alerts for the company
        high_risk_stmt = (
            select(HRAttritionRiskPrediction)
            .join(Employee, HRAttritionRiskPrediction.employee_id == Employee.id)
            .where(HRAttritionRiskPrediction.risk_level == "HIGH", Employee.is_deleted == False)
        )
        if company_id:
            high_risk_stmt = high_risk_stmt.where(Employee.company_id == company_id)

        high_risk_stmt = (
            high_risk_stmt.options(selectinload(HRAttritionRiskPrediction.employee))
            .order_by(HRAttritionRiskPrediction.predicted_at.desc())
            .limit(5)
        )
        high_risk_res = await self.db.execute(high_risk_stmt)
        high_risks = high_risk_res.scalars().all()

        alerts = [
            {
                "employee_id": str(r.employee_id),
                "name": f"{r.employee.first_name} {r.employee.last_name}" if r.employee else "Unknown Employee",
                "designation": r.employee.designation if r.employee else "Unknown",
                "risk_score": float(r.risk_score),
                "recommendation": r.retention_recommendations,
            }
            for r in high_risks
            if r.employee is not None
        ]

        # Get latest forecasts
        forecasts_stmt = select(HRForecastingRun).order_by(HRForecastingRun.run_at.desc()).limit(3)
        forecasts_res = await self.db.execute(forecasts_stmt)
        forecasts = forecasts_res.scalars().all()

        forecast_summaries = [
            {
                "type": f.forecast_type,
                "target_date": str(f.forecast_target_date),
                "predicted": float(f.predicted_value),
                "bounds": [float(f.lower_confidence_bound), float(f.upper_confidence_bound)],
            }
            for f in forecasts
        ]

        return {
            "snapshot_id": str(snapshot.id),
            "snapshot_date": str(snapshot.snapshot_date),
            "total_headcount": snapshot.total_headcount,
            "overall_attrition_rate": float(snapshot.overall_attrition_rate),
            "average_tenure_months": float(snapshot.average_tenure_months),
            "diversity": snapshot.diversity_metrics,
            "salary": snapshot.salary_metrics,
            "leave_attendance": snapshot.leave_attendance_metrics,
            "high_attrition_risk_alerts": alerts,
            "active_workforce_forecasts": forecast_summaries,
        }

    async def get_leave_analytics(self, company_id: uuid.UUID) -> dict[str, Any]:
        """Compile leave availability ratios, overlap conflicts, and weekly forecasts."""
        from app.models.leave import LeaveRequest
        from app.models.employee import Employee
        
        # Get all active employees in this company
        emp_stmt = select(Employee.id).where(Employee.company_id == company_id, Employee.is_deleted == False)
        emp_res = await self.db.execute(emp_stmt)
        employee_ids = emp_res.scalars().all()

        if not employee_ids:
            return {
                "pending_requests_count": 0,
                "approval_suggestions_count": 0,
                "conflicts_detected_count": 0,
                "team_availability_rate": 100.0,
                "leave_forecast": [],
                "leave_type_distribution": [],
            }

        # Query pending leave requests
        pending_stmt = select(LeaveRequest).where(
            LeaveRequest.employee_id.in_(employee_ids),
            LeaveRequest.status == "PENDING"
        )
        pending_res = await self.db.execute(pending_stmt)
        pending_requests = pending_res.scalars().all()
        pending_count = len(pending_requests)

        # Let's check overlaps (conflicts)
        conflicts_count = 0
        for req in pending_requests:
            # Check overlap with any APPROVED or other PENDING leave of OTHER employees in the same company
            overlap_stmt = select(LeaveRequest).where(
                LeaveRequest.id != req.id,
                LeaveRequest.employee_id.in_(employee_ids),
                LeaveRequest.status.in_(["PENDING", "APPROVED"]),
                LeaveRequest.start_date <= req.end_date,
                LeaveRequest.end_date >= req.start_date
            )
            overlap_res = await self.db.execute(overlap_stmt)
            if overlap_res.scalars().first():
                conflicts_count += 1

        approval_suggestions = max(0, pending_count - conflicts_count)

        # Team availability rate
        # Let's count how many active employees are on leave TODAY
        today = date.today()
        on_leave_stmt = select(func.count(LeaveRequest.id)).where(
            LeaveRequest.employee_id.in_(employee_ids),
            LeaveRequest.status == "APPROVED",
            LeaveRequest.start_date <= today,
            LeaveRequest.end_date >= today
        )
        on_leave_res = await self.db.execute(on_leave_stmt)
        on_leave_count = on_leave_res.scalar() or 0
        total_active_count = len(employee_ids)
        availability_rate = 100.0
        if total_active_count > 0:
            availability_rate = round(((total_active_count - on_leave_count) / total_active_count) * 100, 1)

        # Leave type distribution
        # Let's group approved/pending leave request days by leave type
        dist_stmt = select(
            LeaveRequest.leave_type,
            func.sum(LeaveRequest.total_days)
        ).where(
            LeaveRequest.employee_id.in_(employee_ids),
            LeaveRequest.status.in_(["APPROVED", "PENDING"])
        ).group_by(LeaveRequest.leave_type)
        
        dist_res = await self.db.execute(dist_stmt)
        distribution = [
            {"t": str(row[0]), "days": float(row[1])}
            for row in dist_res.all()
        ]

        # Leave forecast
        # We can forecast weekly leave counts for the next 4 weeks
        forecast = []
        for i in range(4):
            week_start = today + timedelta(weeks=i)
            week_end = week_start + timedelta(days=6)
            week_label = f"W{i+1} ({week_start.strftime('%b %d')})"
            
            # Count leaves active during this week
            week_stmt = select(func.count(LeaveRequest.id)).where(
                LeaveRequest.employee_id.in_(employee_ids),
                LeaveRequest.status.in_(["APPROVED", "PENDING"]),
                LeaveRequest.start_date <= week_end,
                LeaveRequest.end_date >= week_start
            )
            week_res = await self.db.execute(week_stmt)
            week_count = week_res.scalar() or 0
            forecast.append({
                "w": week_label,
                "leaves": int(week_count)
            })

        return {
            "pending_requests_count": pending_count,
            "approval_suggestions_count": approval_suggestions,
            "conflicts_detected_count": conflicts_count,
            "team_availability_rate": availability_rate,
            "leave_forecast": forecast,
            "leave_type_distribution": distribution,
        }
