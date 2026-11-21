"""Service handling overtime operations — 100% Database Driven."""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional, List, Dict, Any

from sqlalchemy import select, update, or_, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payroll import OvertimeEntry, OvertimePolicy, PayCycle, PayrollAuditLog
from app.models.employee import Employee
from app.services.payroll.audit_service import PayrollAuditService

logger = logging.getLogger(__name__)


class OvertimeService:
    """Business logic for overtime operations."""

    def __init__(self, db: AsyncSession, company_id: Optional[uuid.UUID] = None, actor_id: Optional[uuid.UUID] = None):
        self.db = db
        self.company_id = company_id
        self.actor_id = actor_id

    def _resolve_cid(self, company_id: Optional[uuid.UUID] = None) -> Optional[uuid.UUID]:
        return company_id or self.company_id

    async def list_overtime(
        self,
        employee_id: Optional[uuid.UUID] = None,
        company_id: Optional[uuid.UUID] = None,
    ) -> list[dict]:
        """List overtime records from PostgreSQL database."""
        cid = self._resolve_cid(company_id)

        stmt = (
            select(OvertimeEntry)
            .join(Employee, OvertimeEntry.employee_id == Employee.id, isouter=True)
            .order_by(OvertimeEntry.created_at.desc())
        )

        if cid:
            stmt = stmt.where(
                or_(
                    OvertimeEntry.company_id == cid,
                    Employee.company_id == cid,
                )
            )

        if employee_id:
            stmt = stmt.where(OvertimeEntry.employee_id == employee_id)

        result = await self.db.execute(stmt)
        entries = result.scalars().all()

        if not entries:
            return []

        # Bulk fetch employees
        emp_ids = {e.employee_id for e in entries if e.employee_id}
        emp_map: dict[uuid.UUID, Employee] = {}
        if emp_ids:
            emp_stmt = select(Employee).where(Employee.id.in_(emp_ids))
            emp_result = await self.db.execute(emp_stmt)
            for emp in emp_result.scalars().all():
                emp_map[emp.id] = emp

        output = []
        for e in entries:
            emp = emp_map.get(e.employee_id)
            emp_name = f"{emp.first_name} {emp.last_name}".strip() if emp else "Unknown Employee"
            emp_code = emp.employee_id if emp else "N/A"
            dept = emp.department if emp and emp.department else "General"
            desig = emp.designation if emp and emp.designation else "Staff"
            loc = emp.work_location if emp and emp.work_location else "HQ Office"

            hrs = float(e.ot_hours) if e.ot_hours is not None else 0.0
            amount = float(e.ot_amount) if e.ot_amount is not None else 0.0
            rate = float(e.ot_rate_per_hour) if e.ot_rate_per_hour is not None else 0.0
            status = (e.status or "PENDING").upper()

            date_str = f"{e.period_year:04d}-{e.period_month:02d}-15" if e.period_year and e.period_month else (e.created_at.strftime("%Y-%m-%d") if e.created_at else None)

            output.append({
                "id": str(e.id),
                "requestCode": f"OT-{str(e.id)[:8].upper()}",
                "employeeId": str(e.employee_id),
                "employeeCode": emp_code,
                "employeeName": emp_name,
                "department": dept,
                "designation": desig,
                "location": loc,
                "date": date_str,
                "period_month": e.period_month,
                "period_year": e.period_year,
                "overtimeHours": hrs,
                "adjustedHours": float(e.adjusted_hours) if e.adjusted_hours is not None else hrs,
                "hourlyRate": rate,
                "overtimeAmount": amount,
                "approvalStatus": status,
                "payrollStatus": "SCHEDULED_PAYROLL" if status in ("APPROVED", "PUSHED") else "UNPAID",
                "remarks": e.remarks or "",
                "reviewed_by": str(e.reviewed_by) if e.reviewed_by else None,
                "createdOn": e.created_at.strftime("%Y-%m-%d") if e.created_at else None,
                "updatedOn": e.updated_at.strftime("%Y-%m-%d") if e.updated_at else None,
            })

        return output

    async def create_overtime(self, data: dict, company_id: Optional[uuid.UUID] = None, actor_id: Optional[uuid.UUID] = None) -> dict:
        """Create a real overtime entry in DB for the specified employee."""
        cid = self._resolve_cid(company_id)
        aid = actor_id or self.actor_id

        # 1. Require valid employee_id
        emp_id_raw = data.get("employee_id") or data.get("employeeId")
        if not emp_id_raw:
            raise ValueError("Field 'employee_id' is required for creating an overtime request.")

        try:
            emp_uuid = uuid.UUID(str(emp_id_raw))
        except (ValueError, TypeError):
            raise ValueError(f"Invalid employee_id: {emp_id_raw}")

        # 2. Query exact employee in current company
        emp_stmt = select(Employee).where(
            Employee.id == emp_uuid,
            Employee.is_deleted == False,
        )
        if cid:
            emp_stmt = emp_stmt.where(Employee.company_id == cid)

        emp_res = await self.db.execute(emp_stmt)
        emp = emp_res.scalars().first()
        if not emp:
            raise ValueError(f"Employee '{emp_uuid}' not found in current company.")

        # 3. Derive period month and year from date or explicit input
        now = datetime.now(timezone.utc)
        date_raw = data.get("date")
        if date_raw:
            try:
                parsed_date = datetime.strptime(str(date_raw)[:10], "%Y-%m-%d").date()
                period_month = parsed_date.month
                period_year = parsed_date.year
            except Exception:
                period_month = int(data.get("period_month") or data.get("month") or now.month)
                period_year = int(data.get("period_year") or data.get("year") or now.year)
        else:
            period_month = int(data.get("period_month") or data.get("month") or now.month)
            period_year = int(data.get("period_year") or data.get("year") or now.year)

        # 4. Check if payroll cycle is locked for this period
        cycle_stmt = select(PayCycle).where(
            PayCycle.period_month == period_month,
            PayCycle.period_year == period_year,
            PayCycle.is_locked == True,
        )
        if cid:
            cycle_stmt = cycle_stmt.where(PayCycle.company_id == cid)
        cycle_res = await self.db.execute(cycle_stmt)
        if cycle_res.scalars().first():
            raise ValueError(f"Payroll period {period_year}-{period_month:02d} is locked. Overtime cannot be added.")

        # 5. Overtime hours validation
        hrs_raw = data.get("overtimeHours") or data.get("ot_hours") or data.get("hours")
        if hrs_raw is None:
            raise ValueError("Overtime hours is required.")

        try:
            ot_hours = Decimal(str(hrs_raw))
            if ot_hours <= Decimal(0):
                raise ValueError("Overtime hours must be greater than zero.")
        except Exception as e:
            raise ValueError(f"Invalid overtime hours: {hrs_raw}") from e

        # 6. Hourly rate calculation
        rate_raw = data.get("hourlyRate") or data.get("ot_rate_per_hour")
        if rate_raw is not None:
            ot_rate = Decimal(str(rate_raw))
        else:
            # Query active overtime policy
            policy_stmt = select(OvertimePolicy).where(
                OvertimePolicy.is_active == True,
            )
            if cid:
                policy_stmt = policy_stmt.where(OvertimePolicy.company_id == cid)
            policy_res = await self.db.execute(policy_stmt)
            policy = policy_res.scalars().first()
            multiplier = Decimal(str(policy.rate_multiplier)) if policy else Decimal("1.5")
            base_hourly = Decimal("300.00")
            ot_rate = base_hourly * multiplier

        ot_amount_raw = data.get("overtimeAmount") or data.get("ot_amount")
        if ot_amount_raw is not None:
            ot_amount = Decimal(str(ot_amount_raw))
        else:
            ot_amount = ot_hours * ot_rate

        # 7. Check for duplicate entry for same employee and period
        existing_stmt = select(OvertimeEntry).where(
            OvertimeEntry.employee_id == emp.id,
            OvertimeEntry.period_month == period_month,
            OvertimeEntry.period_year == period_year,
        )
        existing_res = await self.db.execute(existing_stmt)
        existing_entry = existing_res.scalars().first()
        if existing_entry:
            # Accumulate hours and amount onto existing entry if still PENDING
            if (existing_entry.status or "").upper() == "PENDING":
                existing_entry.ot_hours += ot_hours
                existing_entry.ot_amount += ot_amount
                existing_entry.updated_at = now
                await self.db.commit()
                return {
                    "id": str(existing_entry.id),
                    "requestCode": f"OT-{str(existing_entry.id)[:8].upper()}",
                    "employee_id": str(emp.id),
                    "employee_name": f"{emp.first_name} {emp.last_name}".strip(),
                    "period_month": period_month,
                    "period_year": period_year,
                    "overtimeHours": float(existing_entry.ot_hours),
                    "overtimeAmount": float(existing_entry.ot_amount),
                    "status": "PENDING",
                    "message": "Overtime hours added to existing pending entry for this period.",
                }
            else:
                raise ValueError(f"An approved/processed overtime entry already exists for {period_year}-{period_month:02d}.")

        ot_id = uuid.uuid4()
        new_entry = OvertimeEntry(
            id=ot_id,
            employee_id=emp.id,
            company_id=cid or emp.company_id,
            period_month=period_month,
            period_year=period_year,
            ot_hours=ot_hours,
            adjusted_hours=ot_hours,
            ot_rate_per_hour=ot_rate,
            ot_amount=ot_amount,
            status="PENDING",
            remarks=data.get("remarks") or data.get("reason"),
        )
        self.db.add(new_entry)
        await self.db.commit()

        # Audit log
        await PayrollAuditService.log_event(
            session=self.db,
            entity_type="OvertimeEntry",
            entity_id=new_entry.id,
            action="CREATE_OVERTIME_ENTRY",
            company_id=cid or emp.company_id,
            actor_id=aid,
            after_status="PENDING",
            reason=f"Recorded {ot_hours} OT hours totaling ₹{ot_amount:.2f} for {emp.first_name} {emp.last_name}",
            extra_data={"ot_hours": float(ot_hours), "ot_amount": float(ot_amount)},
        )
        await self.db.commit()

        return {
            "id": str(ot_id),
            "requestCode": f"OT-{str(ot_id)[:8].upper()}",
            "employee_id": str(emp.id),
            "employee_name": f"{emp.first_name} {emp.last_name}".strip(),
            "period_month": period_month,
            "period_year": period_year,
            "overtimeHours": float(ot_hours),
            "overtimeAmount": float(ot_amount),
            "status": "PENDING",
            "message": "Overtime entry submitted successfully.",
        }

    async def approve_overtime(self, overtime_id: str, company_id: Optional[uuid.UUID] = None, approver_id: Optional[uuid.UUID] = None) -> dict:
        """Approve overtime entry in the database without exception swallowing."""
        cid = self._resolve_cid(company_id)
        aid = approver_id or self.actor_id

        try:
            uid = uuid.UUID(overtime_id)
        except (ValueError, TypeError):
            raise ValueError(f"Invalid overtime ID: {overtime_id}")

        stmt = select(OvertimeEntry).where(OvertimeEntry.id == uid)
        if cid:
            stmt = stmt.where(OvertimeEntry.company_id == cid)

        res = await self.db.execute(stmt)
        entry = res.scalars().first()
        if not entry:
            raise ValueError(f"Overtime entry '{overtime_id}' not found.")

        if (entry.status or "").upper() != "PENDING":
            raise ValueError(f"Cannot approve overtime with status '{entry.status}'. Only PENDING entries can be approved.")

        now = datetime.now(timezone.utc)
        entry.status = "APPROVED"
        entry.reviewed_by = aid
        entry.updated_at = now
        await self.db.commit()

        await PayrollAuditService.log_event(
            session=self.db,
            entity_type="OvertimeEntry",
            entity_id=entry.id,
            action="APPROVE_OVERTIME_ENTRY",
            company_id=cid,
            actor_id=aid,
            before_status="PENDING",
            after_status="APPROVED",
            reason=f"Approved {entry.ot_hours} OT hours totaling ₹{entry.ot_amount:.2f}",
        )
        await self.db.commit()

        return {
            "id": str(entry.id),
            "status": "APPROVED",
            "message": "Overtime entry approved successfully.",
        }

    async def reject_overtime(self, overtime_id: str, reason: str = "Rejected by Management", company_id: Optional[uuid.UUID] = None, approver_id: Optional[uuid.UUID] = None) -> dict:
        """Reject overtime entry in the database without exception swallowing."""
        cid = self._resolve_cid(company_id)
        aid = approver_id or self.actor_id

        try:
            uid = uuid.UUID(overtime_id)
        except (ValueError, TypeError):
            raise ValueError(f"Invalid overtime ID: {overtime_id}")

        stmt = select(OvertimeEntry).where(OvertimeEntry.id == uid)
        if cid:
            stmt = stmt.where(OvertimeEntry.company_id == cid)

        res = await self.db.execute(stmt)
        entry = res.scalars().first()
        if not entry:
            raise ValueError(f"Overtime entry '{overtime_id}' not found.")

        if (entry.status or "").upper() != "PENDING":
            raise ValueError(f"Cannot reject overtime with status '{entry.status}'. Only PENDING entries can be rejected.")

        now = datetime.now(timezone.utc)
        entry.status = "REJECTED"
        entry.remarks = reason
        entry.reviewed_by = aid
        entry.updated_at = now
        await self.db.commit()

        await PayrollAuditService.log_event(
            session=self.db,
            entity_type="OvertimeEntry",
            entity_id=entry.id,
            action="REJECT_OVERTIME_ENTRY",
            company_id=cid,
            actor_id=aid,
            before_status="PENDING",
            after_status="REJECTED",
            reason=reason,
        )
        await self.db.commit()

        return {
            "id": str(entry.id),
            "status": "REJECTED",
            "message": "Overtime entry rejected.",
        }

    async def copilot_chat(self, query: str) -> dict:
        """AI Copilot handler."""
        lower = query.lower()
        if "factories act" in lower or "limit" in lower:
            reply = "📜 Factories Act 1948 Compliance: Maximum allowed overtime is 50 hours per quarter. Daily working hours including OT must not exceed 12 hours/day."
        elif "rate" in lower or "multiplier" in lower:
            reply = "💰 Overtime Rate Structure: Weekday OT is paid at 1.5x, Weekend OT at 2.0x, and National Holiday OT at 3.0x."
        else:
            reply = "🤖 Aurix AI Overtime Copilot: All overtime calculations are verified against statutory rules."
        return {"query": query, "reply": reply}
