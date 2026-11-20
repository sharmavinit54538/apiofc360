"""Service handling bonus plans and allocations — 100% Database Driven."""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional, List, Dict, Any

from sqlalchemy import select, update, or_, and_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.payroll import BonusPlan, BonusAward, PayrollAuditLog
from app.models.employee import Employee
from app.services.payroll.audit_service import PayrollAuditService

logger = logging.getLogger(__name__)


class BonusService:
    """Business logic for bonus plans and employee allocations."""

    def __init__(self, db: AsyncSession, company_id: Optional[uuid.UUID] = None, actor_id: Optional[uuid.UUID] = None):
        self.db = db
        self.company_id = company_id
        self.actor_id = actor_id

    def _resolve_cid(self, company_id: Optional[uuid.UUID] = None) -> Optional[uuid.UUID]:
        return company_id or self.company_id

    async def list_plans(self, company_id: Optional[uuid.UUID] = None) -> list[dict]:
        """List active bonus plans from PostgreSQL database."""
        cid = self._resolve_cid(company_id)

        stmt = select(BonusPlan).order_by(BonusPlan.created_at.desc())
        if cid:
            stmt = stmt.where(
                or_(
                    BonusPlan.company_id == cid,
                    BonusPlan.company_id.is_(None),
                )
            )

        result = await self.db.execute(stmt)
        plans = result.scalars().all()

        output = []
        for p in plans:
            amt = float(p.default_amount) if p.default_amount is not None else 0.0
            output.append({
                "id": str(p.id),
                "name": p.name,
                "plan_type": p.plan_type,
                "description": p.description or "",
                "eligibility_scope": p.eligibility_scope,
                "default_amount": amt,
                "recurrence_months": p.recurrence_months,
                "requires_approval": p.requires_approval,
                "is_active": p.is_active,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            })

        return output

    async def list_bonuses(
        self,
        employee_id: Optional[uuid.UUID] = None,
        status: Optional[str] = None,
        search: Optional[str] = None,
        company_id: Optional[uuid.UUID] = None,
    ) -> list[dict]:
        """List individual employee bonus awards from PostgreSQL database."""
        cid = self._resolve_cid(company_id)

        stmt = (
            select(BonusAward)
            .join(Employee, BonusAward.employee_id == Employee.id, isouter=True)
            .join(BonusPlan, BonusAward.bonus_plan_id == BonusPlan.id, isouter=True)
            .order_by(BonusAward.created_at.desc())
        )

        if cid:
            stmt = stmt.where(
                or_(
                    BonusAward.company_id == cid,
                    Employee.company_id == cid,
                )
            )

        if employee_id:
            stmt = stmt.where(BonusAward.employee_id == employee_id)

        if status and status.upper() not in ("ALL", ""):
            stmt = stmt.where(BonusAward.status == status.upper())

        result = await self.db.execute(stmt)
        awards = result.scalars().all()

        if not awards:
            return []

        # Bulk fetch employees to avoid N+1 queries
        emp_ids = {a.employee_id for a in awards if a.employee_id}
        emp_map: dict[uuid.UUID, Employee] = {}
        if emp_ids:
            emp_stmt = select(Employee).where(Employee.id.in_(emp_ids))
            emp_result = await self.db.execute(emp_stmt)
            for emp in emp_result.scalars().all():
                emp_map[emp.id] = emp

        plan_ids = {a.bonus_plan_id for a in awards if a.bonus_plan_id}
        plan_map: dict[uuid.UUID, BonusPlan] = {}
        if plan_ids:
            plan_stmt = select(BonusPlan).where(BonusPlan.id.in_(plan_ids))
            plan_result = await self.db.execute(plan_stmt)
            for pl in plan_result.scalars().all():
                plan_map[pl.id] = pl

        output = []
        for a in awards:
            emp = emp_map.get(a.employee_id)
            plan = plan_map.get(a.bonus_plan_id)

            emp_name = f"{emp.first_name} {emp.last_name}".strip() if emp else "Unknown Employee"
            emp_code = emp.employee_id if emp else "N/A"
            dept = emp.department if emp and emp.department else "General"
            desig = emp.designation if emp and emp.designation else "Staff"

            amt = float(a.amount) if a.amount is not None else 0.0
            category = plan.name if plan else (a.reason or "Performance Bonus")

            status_val = (a.status or "PENDING").upper()
            pay_status = "PAID" if status_val == "PAID" else ("SCHEDULED" if status_val == "APPROVED" else "UNPAID")

            item = {
                "id": str(a.id),
                "bonusCode": f"BON-{str(a.id)[:8].upper()}",
                "employeeId": str(a.employee_id),
                "employeeCode": emp_code,
                "employeeName": emp_name,
                "department": dept,
                "designation": desig,
                "bonusType": plan.plan_type if plan else "SPOT",
                "bonusCategory": category,
                "recommendedAmount": amt,
                "finalBonusAmount": amt,
                "reason": a.reason or "",
                "approvalStatus": status_val,
                "payrollStatus": pay_status,
                "rejection_reason": a.rejection_reason,
                "approved_by": str(a.approved_by) if a.approved_by else None,
                "approved_at": a.approved_at.isoformat() if a.approved_at else None,
                "createdOn": a.created_at.strftime("%Y-%m-%d") if a.created_at else None,
                "updatedOn": a.updated_at.strftime("%Y-%m-%d") if a.updated_at else None,
            }

            if search:
                q = search.lower()
                if (
                    q not in emp_name.lower()
                    and q not in dept.lower()
                    and q not in item["bonusCode"].lower()
                    and q not in desig.lower()
                ):
                    continue

            output.append(item)

        return output

    async def create_bonus(self, data: dict, company_id: Optional[uuid.UUID] = None, actor_id: Optional[uuid.UUID] = None) -> dict:
        """Create a real BonusAward entry in DB for a specific employee."""
        cid = self._resolve_cid(company_id)
        aid = actor_id or self.actor_id

        # Require a valid employee_id
        emp_id_raw = data.get("employee_id") or data.get("employeeId")
        if not emp_id_raw:
            raise ValueError("Field 'employee_id' is required for creating a bonus award.")

        try:
            emp_uuid = uuid.UUID(str(emp_id_raw))
        except (ValueError, TypeError):
            raise ValueError(f"Invalid employee_id: {emp_id_raw}")

        # Validate employee exists in company
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

        # Validate amount
        amt_raw = data.get("finalBonusAmount") or data.get("amount") or data.get("recommendedAmount")
        if amt_raw is None:
            raise ValueError("Bonus amount is required.")

        try:
            amt = Decimal(str(amt_raw))
            if amt <= Decimal(0):
                raise ValueError("Bonus amount must be greater than zero.")
        except Exception as e:
            raise ValueError(f"Invalid bonus amount: {amt_raw}") from e

        # Optional bonus plan linkage
        plan_id_raw = data.get("bonus_plan_id") or data.get("bonusPlanId")
        plan_uuid = None
        if plan_id_raw:
            try:
                plan_uuid = uuid.UUID(str(plan_id_raw))
            except (ValueError, TypeError):
                pass

        bid = uuid.uuid4()
        reason = data.get("justification") or data.get("reason") or data.get("bonusCategory") or "Performance Bonus"

        award = BonusAward(
            id=bid,
            company_id=cid or emp.company_id,
            bonus_plan_id=plan_uuid,
            employee_id=emp.id,
            amount=amt,
            reason=reason,
            status="PENDING",
            created_by=aid,
        )
        self.db.add(award)
        await self.db.commit()

        # Audit log
        await PayrollAuditService.log_event(
            session=self.db,
            entity_type="BonusAward",
            entity_id=award.id,
            action="CREATE_BONUS_AWARD",
            company_id=cid or emp.company_id,
            actor_id=aid,
            after_status="PENDING",
            reason=f"Created bonus award of ₹{amt:.2f} for employee {emp.first_name} {emp.last_name}: {reason}",
            extra_data={"amount": float(amt), "employee_id": str(emp.id)},
        )
        await self.db.commit()

        return {
            "id": str(bid),
            "bonusCode": f"BON-{str(bid)[:8].upper()}",
            "employee_id": str(emp.id),
            "employee_name": f"{emp.first_name} {emp.last_name}".strip(),
            "amount": float(amt),
            "status": "PENDING",
            "message": "Bonus award created successfully.",
        }

    async def approve_bonus(self, bonus_id: str, company_id: Optional[uuid.UUID] = None, approver_id: Optional[uuid.UUID] = None) -> dict:
        """Approve bonus award in the database."""
        cid = self._resolve_cid(company_id)
        aid = approver_id or self.actor_id

        try:
            uid = uuid.UUID(bonus_id)
        except (ValueError, TypeError):
            raise ValueError(f"Invalid bonus ID: {bonus_id}")

        stmt = select(BonusAward).where(BonusAward.id == uid)
        if cid:
            stmt = stmt.where(BonusAward.company_id == cid)

        res = await self.db.execute(stmt)
        award = res.scalars().first()
        if not award:
            raise ValueError(f"Bonus award '{bonus_id}' not found.")

        if (award.status or "").upper() != "PENDING":
            raise ValueError(f"Cannot approve bonus with status '{award.status}'. Only PENDING awards can be approved.")

        now = datetime.now(timezone.utc)
        award.status = "APPROVED"
        award.approved_by = aid
        award.approved_at = now
        award.updated_at = now
        await self.db.commit()

        await PayrollAuditService.log_event(
            session=self.db,
            entity_type="BonusAward",
            entity_id=award.id,
            action="APPROVE_BONUS_AWARD",
            company_id=cid,
            actor_id=aid,
            before_status="PENDING",
            after_status="APPROVED",
            reason=f"Approved bonus award of ₹{award.amount:.2f}",
        )
        await self.db.commit()

        return {
            "id": str(award.id),
            "status": "APPROVED",
            "approved_by": str(aid) if aid else None,
            "approved_at": now.isoformat(),
            "message": "Bonus request approved successfully.",
        }

    async def reject_bonus(self, bonus_id: str, reason: str = "Rejected by HR/Management", company_id: Optional[uuid.UUID] = None, approver_id: Optional[uuid.UUID] = None) -> dict:
        """Reject bonus award in the database."""
        cid = self._resolve_cid(company_id)
        aid = approver_id or self.actor_id

        try:
            uid = uuid.UUID(bonus_id)
        except (ValueError, TypeError):
            raise ValueError(f"Invalid bonus ID: {bonus_id}")

        stmt = select(BonusAward).where(BonusAward.id == uid)
        if cid:
            stmt = stmt.where(BonusAward.company_id == cid)

        res = await self.db.execute(stmt)
        award = res.scalars().first()
        if not award:
            raise ValueError(f"Bonus award '{bonus_id}' not found.")

        if (award.status or "").upper() != "PENDING":
            raise ValueError(f"Cannot reject bonus with status '{award.status}'. Only PENDING awards can be rejected.")

        now = datetime.now(timezone.utc)
        award.status = "REJECTED"
        award.rejection_reason = reason
        award.updated_at = now
        await self.db.commit()

        await PayrollAuditService.log_event(
            session=self.db,
            entity_type="BonusAward",
            entity_id=award.id,
            action="REJECT_BONUS_AWARD",
            company_id=cid,
            actor_id=aid,
            before_status="PENDING",
            after_status="REJECTED",
            reason=reason,
        )
        await self.db.commit()

        return {
            "id": str(award.id),
            "status": "REJECTED",
            "rejection_reason": reason,
            "message": "Bonus request rejected.",
        }

    async def copilot_chat(self, query: str) -> dict:
        """AI Bonus Intelligence handler."""
        lower = query.lower()
        if "tax" in lower or "tds" in lower:
            reply = "📜 Bonus TDS Tax Policy: Bonus payouts are treated as taxable salary earnings under IT Act Section 192."
        elif "formula" in lower or "rating" in lower:
            reply = "💰 Formula Calculator: Ratings above 4.5 earn 15% to 20% annual basic salary multipliers."
        else:
            reply = "🤖 Aurix AI Bonus Intelligence: All bonus allocations are 100% integrated with monthly payroll runs under Company Compensation Policy."
        return {"query": query, "reply": reply}
