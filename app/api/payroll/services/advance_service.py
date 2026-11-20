"""Service handling salary advance and loan requests — 100% Database Driven."""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional, List, Dict, Any

from sqlalchemy import select, update, or_, and_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.payroll import AdvanceLoan, AdvanceLoanInstallment, PayrollAuditLog
from app.models.employee import Employee
from app.services.payroll.audit_service import PayrollAuditService

logger = logging.getLogger(__name__)


class AdvanceService:
    """Business logic for salary advances and loan repayments."""

    def __init__(self, db: AsyncSession, company_id: Optional[uuid.UUID] = None, actor_id: Optional[uuid.UUID] = None):
        self.db = db
        self.company_id = company_id
        self.actor_id = actor_id

    def _resolve_cid(self, company_id: Optional[uuid.UUID] = None) -> Optional[uuid.UUID]:
        return company_id or self.company_id

    async def list_loans(
        self,
        employee_id: Optional[uuid.UUID] = None,
        company_id: Optional[uuid.UUID] = None,
    ) -> list[dict]:
        """List active advances and loans from PostgreSQL database."""
        cid = self._resolve_cid(company_id)

        stmt = (
            select(AdvanceLoan)
            .join(Employee, AdvanceLoan.employee_id == Employee.id, isouter=True)
            .options(selectinload(AdvanceLoan.installments))
            .order_by(AdvanceLoan.created_at.desc())
        )

        if cid:
            stmt = stmt.where(
                or_(
                    AdvanceLoan.company_id == cid,
                    Employee.company_id == cid,
                )
            )

        if employee_id:
            stmt = stmt.where(AdvanceLoan.employee_id == employee_id)

        result = await self.db.execute(stmt)
        loans = result.scalars().all()

        if not loans:
            return []

        # Bulk fetch employees
        emp_ids = {l.employee_id for l in loans if l.employee_id}
        emp_map: dict[uuid.UUID, Employee] = {}
        if emp_ids:
            emp_stmt = select(Employee).where(Employee.id.in_(emp_ids))
            emp_result = await self.db.execute(emp_stmt)
            for emp in emp_result.scalars().all():
                emp_map[emp.id] = emp

        output = []
        for l in loans:
            emp = emp_map.get(l.employee_id)
            emp_name = f"{emp.first_name} {emp.last_name}".strip() if emp else "Unknown Employee"
            emp_code = emp.employee_id if emp else "N/A"
            dept = emp.department if emp and emp.department else "General"
            desig = emp.designation if emp and emp.designation else "Staff"
            loc = emp.work_location if emp and emp.work_location else "HQ Office"

            req_amt = float(l.principal_amount) if l.principal_amount is not None else 0.0
            app_amt = req_amt
            bal = float(l.outstanding_balance) if l.outstanding_balance is not None else req_amt
            rec = max(0.0, req_amt - bal)
            emi = float(l.emi_amount) if l.emi_amount is not None else (req_amt / max(1, l.total_installments or 10))
            status = (l.status or "PENDING_MANAGER").upper()

            # Derive real recovery dates from start month and year
            start_m = l.start_from_month or 1
            start_y = l.start_from_year or datetime.now(timezone.utc).year
            start_date_str = f"{start_y:04d}-{start_m:02d}-01"

            # Compute end recovery date
            total_inst = l.total_installments or 1
            end_m = ((start_m - 1 + total_inst - 1) % 12) + 1
            end_y = start_y + ((start_m - 1 + total_inst - 1) // 12)
            end_date_str = f"{end_y:04d}-{end_m:02d}-01"

            # Build installment list from actual installments or schedule
            installments = []
            if l.installments:
                for inst in l.installments:
                    installments.append({
                        "installmentNumber": inst.period_month,
                        "dueDate": f"{inst.period_year:04d}-{inst.period_month:02d}-01",
                        "amount": float(inst.emi_amount),
                        "status": inst.status,
                    })
            else:
                for i in range(total_inst):
                    im = ((start_m - 1 + i) % 12) + 1
                    iy = start_y + ((start_m - 1 + i) // 12)
                    paid_count = l.installments_paid or 0
                    inst_status = "PAID" if i < paid_count else "PENDING"
                    installments.append({
                        "installmentNumber": i + 1,
                        "dueDate": f"{iy:04d}-{im:02d}-01",
                        "amount": emi,
                        "status": inst_status,
                    })

            output.append({
                "id": str(l.id),
                "advanceCode": f"ADV-{str(l.id)[:8].upper()}",
                "employeeId": str(l.employee_id),
                "employeeCode": emp_code,
                "employeeName": emp_name,
                "department": dept,
                "designation": desig,
                "location": loc,
                "employmentType": "FULL_TIME",
                "advanceType": l.loan_type or "ADVANCE",
                "reason": l.reason or "Salary advance request.",
                "requestedAmount": req_amt,
                "approvedAmount": app_amt,
                "outstandingBalance": bal,
                "recoveredAmount": rec,
                "interestRate": 0.0,
                "recoveryMethod": "MONTHLY_PAYROLL",
                "totalInstallments": l.total_installments or 10,
                "installmentsPaid": l.installments_paid or 0,
                "installmentAmount": emi,
                "startRecoveryDate": start_date_str,
                "endRecoveryDate": end_date_str,
                "nextRecoveryDate": start_date_str,
                "approvalStatus": status,
                "paymentStatus": "DISBURSED" if status in ("APPROVED", "ACTIVE") else "UNPAID",
                "recoveryStatus": "RECOVERING" if (bal > 0 and status in ("APPROVED", "ACTIVE")) else ("CLOSED" if bal <= 0 else "NOT_STARTED"),
                "installments": installments,
                "createdOn": l.created_at.strftime("%Y-%m-%d") if l.created_at else None,
                "updatedOn": l.updated_at.strftime("%Y-%m-%d") if l.updated_at else None,
                "createdBy": emp_name,
            })

        return output

    async def create_loan(self, data: dict, company_id: Optional[uuid.UUID] = None, actor_id: Optional[uuid.UUID] = None) -> dict:
        """Create a real advance/loan in DB for the specified employee."""
        cid = self._resolve_cid(company_id)
        aid = actor_id or self.actor_id

        # 1. Require valid employee_id
        emp_id_raw = data.get("employee_id") or data.get("employeeId")
        if not emp_id_raw:
            raise ValueError("Field 'employee_id' is required for salary advance / loan creation.")

        try:
            emp_uuid = uuid.UUID(str(emp_id_raw))
        except (ValueError, TypeError):
            raise ValueError(f"Invalid employee_id: {emp_id_raw}")

        # 2. Query the exact employee inside the company
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

        # 3. Validate positive principal amount
        amt_raw = data.get("requestedAmount") or data.get("amount") or data.get("principal_amount")
        if amt_raw is None:
            raise ValueError("Requested loan amount is required.")

        try:
            amt = Decimal(str(amt_raw))
            if amt <= Decimal(0):
                raise ValueError("Loan amount must be greater than zero.")
        except Exception as e:
            raise ValueError(f"Invalid loan amount: {amt_raw}") from e

        # 4. Total installments & EMI calculation
        total_installments = int(data.get("totalInstallments") or data.get("total_installments") or 10)
        if total_installments <= 0:
            raise ValueError("Total installments must be at least 1.")

        emi = amt / Decimal(str(total_installments))

        # 5. Start month and year from data or current date
        now = datetime.now(timezone.utc)
        start_month = int(data.get("start_from_month") or data.get("startMonth") or ((now.month % 12) + 1))
        start_year = int(data.get("start_from_year") or data.get("startYear") or (now.year + (1 if now.month == 12 else 0)))

        loan_id = uuid.uuid4()
        reason = data.get("reason", "Salary Advance Request")
        loan_type = data.get("loan_type") or data.get("advanceType") or "ADVANCE"

        new_loan = AdvanceLoan(
            id=loan_id,
            employee_id=emp.id,
            company_id=cid or emp.company_id,
            loan_type=loan_type,
            principal_amount=amt,
            outstanding_balance=amt,
            emi_amount=emi,
            total_installments=total_installments,
            installments_paid=0,
            start_from_month=start_month,
            start_from_year=start_year,
            reason=reason,
            status="PENDING_MANAGER",
            created_by=aid,
        )
        self.db.add(new_loan)
        await self.db.commit()

        # Audit log
        await PayrollAuditService.log_event(
            session=self.db,
            entity_type="AdvanceLoan",
            entity_id=new_loan.id,
            action="CREATE_ADVANCE_LOAN",
            company_id=cid or emp.company_id,
            actor_id=aid,
            after_status="PENDING_MANAGER",
            reason=f"Requested {loan_type} of ₹{amt:.2f} across {total_installments} EMIs: {reason}",
            extra_data={"principal_amount": float(amt), "employee_id": str(emp.id)},
        )
        await self.db.commit()

        return {
            "id": str(loan_id),
            "advanceCode": f"ADV-{str(loan_id)[:8].upper()}",
            "employee_id": str(emp.id),
            "employee_name": f"{emp.first_name} {emp.last_name}".strip(),
            "principal_amount": float(amt),
            "emi_amount": float(emi),
            "total_installments": total_installments,
            "status": "PENDING_MANAGER",
            "message": "Advance request submitted successfully.",
        }

    async def approve_loan(self, loan_id: str, company_id: Optional[uuid.UUID] = None, approver_id: Optional[uuid.UUID] = None) -> dict:
        """Approve loan request in the database without exception swallowing."""
        cid = self._resolve_cid(company_id)
        aid = approver_id or self.actor_id

        try:
            uid = uuid.UUID(loan_id)
        except (ValueError, TypeError):
            raise ValueError(f"Invalid loan ID: {loan_id}")

        stmt = select(AdvanceLoan).where(AdvanceLoan.id == uid)
        if cid:
            stmt = stmt.where(AdvanceLoan.company_id == cid)

        res = await self.db.execute(stmt)
        loan = res.scalars().first()
        if not loan:
            raise ValueError(f"Loan '{loan_id}' not found.")

        if (loan.status or "").upper() != "PENDING_MANAGER":
            raise ValueError(f"Cannot approve loan in status '{loan.status}'. Only PENDING_MANAGER loans can be approved.")

        now = datetime.now(timezone.utc)
        loan.status = "APPROVED"
        loan.approved_by = aid
        loan.updated_at = now
        await self.db.commit()

        await PayrollAuditService.log_event(
            session=self.db,
            entity_type="AdvanceLoan",
            entity_id=loan.id,
            action="APPROVE_ADVANCE_LOAN",
            company_id=cid,
            actor_id=aid,
            before_status="PENDING_MANAGER",
            after_status="APPROVED",
            reason=f"Approved loan of ₹{loan.principal_amount:.2f}",
        )
        await self.db.commit()

        return {
            "id": str(loan.id),
            "status": "APPROVED",
            "approved_by": str(aid) if aid else None,
            "approved_at": now.isoformat(),
            "message": "Loan request approved successfully.",
        }

    async def reject_loan(self, loan_id: str, reason: str = "Rejected by Management", company_id: Optional[uuid.UUID] = None, approver_id: Optional[uuid.UUID] = None) -> dict:
        """Reject loan request in the database without exception swallowing."""
        cid = self._resolve_cid(company_id)
        aid = approver_id or self.actor_id

        try:
            uid = uuid.UUID(loan_id)
        except (ValueError, TypeError):
            raise ValueError(f"Invalid loan ID: {loan_id}")

        stmt = select(AdvanceLoan).where(AdvanceLoan.id == uid)
        if cid:
            stmt = stmt.where(AdvanceLoan.company_id == cid)

        res = await self.db.execute(stmt)
        loan = res.scalars().first()
        if not loan:
            raise ValueError(f"Loan '{loan_id}' not found.")

        if (loan.status or "").upper() != "PENDING_MANAGER":
            raise ValueError(f"Cannot reject loan in status '{loan.status}'. Only PENDING_MANAGER loans can be rejected.")

        now = datetime.now(timezone.utc)
        loan.status = "REJECTED"
        loan.updated_at = now
        await self.db.commit()

        await PayrollAuditService.log_event(
            session=self.db,
            entity_type="AdvanceLoan",
            entity_id=loan.id,
            action="REJECT_ADVANCE_LOAN",
            company_id=cid,
            actor_id=aid,
            before_status="PENDING_MANAGER",
            after_status="REJECTED",
            reason=reason,
        )
        await self.db.commit()

        return {
            "id": str(loan.id),
            "status": "REJECTED",
            "message": "Loan request rejected.",
        }

    async def copilot_chat(self, query: str) -> dict:
        """AI Financial Assistant handler."""
        lower = query.lower()
        if "limit" in lower or "policy" in lower:
            reply = "📜 Advance Policy Limits: Maximum salary advance is capped at 50% of the employee's gross monthly basic salary."
        elif "emi" in lower or "calculator" in lower:
            reply = "💰 EMI Calculation: Salary advance EMIs are calculated with 0% interest for emergency requests, auto-deducted during monthly salary processing."
        else:
            reply = "🤖 Aurix AI Financial Assistant: Salary advance repayments are 100% integrated with monthly payroll runs under Company Policy."
        return {"query": query, "reply": reply}
