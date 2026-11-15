"""One transactional expense workflow for expenses and payroll reimbursements."""
from __future__ import annotations

from datetime import datetime, timezone
from math import ceil
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import contains_eager

from app.models.employee import Employee
from app.models.payroll import PayrollAuditLog, ReimbursementClaim
from app.schemas.expenses import ExpenseCreate, ExpenseFilters, ExpensePayment, ExpenseUpdate
from app.services.expense_access import ExpenseActor


class ExpenseService:
    """Tenant-scoped reads and row-locked writes, with atomic audit history."""

    transitions = {
        "DRAFT": {"SUBMITTED"},
        "SUBMITTED": {"APPROVED", "REJECTED", "CHANGES_REQUESTED"},
        "CHANGES_REQUESTED": {"SUBMITTED"},
        "APPROVED": {"PAID"},
        # Existing payroll-approved claims remain payable without rewriting history.
        "PAYROLL_APPROVED": {"PAID"},
    }

    def __init__(self, db: AsyncSession, actor: ExpenseActor):
        self.db = db
        self.actor = actor

    def _query(self):
        return (
            select(ReimbursementClaim)
            .join(Employee, ReimbursementClaim.employee_id == Employee.id)
            .where(
                ReimbursementClaim.company_id == self.actor.company_id,
                Employee.company_id == self.actor.company_id,
                ReimbursementClaim.deleted_at.is_(None),
            )
            .options(contains_eager(ReimbursementClaim.employee))
        )

    def _visible(self, statement):
        if self.actor.can_read_all:
            return statement
        ids = set(self.actor.team_employee_ids) if self.actor.can_read_team else set()
        if self.actor.employee_id:
            ids.add(self.actor.employee_id)
        if not ids:
            raise HTTPException(403, "Expense access has not been granted.")
        return statement.where(ReimbursementClaim.employee_id.in_(ids))

    async def get(self, expense_id: UUID, *, lock: bool = False) -> ReimbursementClaim:
        statement = self._query().where(ReimbursementClaim.id == expense_id)
        if lock:
            statement = statement.with_for_update(of=ReimbursementClaim).execution_options(populate_existing=True)
        claim = (await self.db.execute(statement)).scalar_one_or_none()
        if claim is None:
            raise HTTPException(404, "Expense not found.")
        if not self.actor.can_read_employee(claim.employee_id):
            raise HTTPException(403, "You cannot access this employee's expenses.")
        return claim

    def _require_edit(self, claim):
        if claim.employee_id != self.actor.employee_id and not self.actor.can_manage:
            raise HTTPException(403, "Only the owner or an authorized expense administrator may manage this claim.")

    async def _audit(self, claim, action, before=None, reason=None, details=None):
        self.db.add(PayrollAuditLog(
            id=uuid4(), company_id=self.actor.company_id,
            entity_type="ReimbursementClaim", entity_id=claim.id,
            actor_id=self.actor.user_id, actor_role=self.actor.role,
            action=action, old_status=before, new_status=claim.status,
            reason=reason, extra_data=details or {},
        ))
        # Failure must abort the financial update; never swallow audit errors.
        await self.db.flush()

    async def list(self, filters: ExpenseFilters) -> dict:
        statement = self._visible(self._query())
        if filters.status:
            values = [filters.status.upper()]
            if filters.status == "approved":
                values.append("PAYROLL_APPROVED")
            statement = statement.where(func.upper(ReimbursementClaim.status).in_(values))
        if filters.employee_id:
            statement = statement.where(ReimbursementClaim.employee_id == filters.employee_id)
        if filters.category:
            statement = statement.where(func.lower(ReimbursementClaim.category) == filters.category)
        if filters.date_from:
            statement = statement.where(ReimbursementClaim.claim_date >= filters.date_from)
        if filters.date_to:
            statement = statement.where(ReimbursementClaim.claim_date <= filters.date_to)
        if filters.search:
            # Search is literal text; %, _ and the escape character are not wildcards.
            term = "%" + filters.search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            columns = (ReimbursementClaim.description, ReimbursementClaim.merchant,
                       ReimbursementClaim.category, Employee.first_name,
                       Employee.last_name, Employee.employee_id)
            statement = statement.where(or_(*(c.ilike(term, escape="\\") for c in columns)))
        total = (await self.db.execute(select(func.count()).select_from(statement.subquery()))).scalar_one()
        sort_field = "claim_date" if filters.sort_by == "expense_date" else filters.sort_by
        column = getattr(ReimbursementClaim, sort_field)
        order = column.asc() if filters.sort_order == "asc" else column.desc()
        statement = statement.order_by(order, ReimbursementClaim.id.asc()).offset((filters.page - 1) * filters.limit).limit(filters.limit)
        rows = (await self.db.execute(statement)).scalars().all()
        pages = ceil(total / filters.limit)
        return {"items": [self.serialize(row) for row in rows], "total": total,
                "page": filters.page, "limit": filters.limit, "pages": pages,
                "has_next": filters.page < pages, "has_previous": filters.page > 1}

    async def create(self, payload: ExpenseCreate, *, submitted=False) -> ReimbursementClaim:
        if not self.actor.employee_id:
            raise HTTPException(403, "An active employee profile is required to create a claim.")
        values = payload.model_dump()
        values["claim_date"] = values.pop("expense_date")
        claim = ReimbursementClaim(
            id=uuid4(), company_id=self.actor.company_id,
            employee_id=self.actor.employee_id, status="SUBMITTED" if submitted else "DRAFT",
            payout_mode="STANDALONE", **values,
        )
        self.db.add(claim)
        await self._audit(claim, "CREATED")
        await self.db.commit()
        return await self.get(claim.id)

    async def update(self, expense_id: UUID, payload: ExpenseUpdate) -> ReimbursementClaim:
        claim = await self.get(expense_id, lock=True)
        self._require_edit(claim)
        if claim.status.upper() not in {"DRAFT", "CHANGES_REQUESTED"}:
            raise HTTPException(409, "Only draft claims or claims awaiting corrections can be edited.")
        changes = payload.model_dump(exclude_unset=True)
        if "expense_date" in changes:
            changes["claim_date"] = changes.pop("expense_date")
        before = {key: str(getattr(claim, key)) if getattr(claim, key) is not None else None for key in changes}
        for key, value in changes.items():
            setattr(claim, key, value)
        claim.updated_at = datetime.now(timezone.utc)
        await self._audit(claim, "UPDATED", claim.status, details={"before": before, "after": {k: str(v) if v is not None else None for k, v in changes.items()}})
        await self.db.commit()
        return claim

    async def delete(self, expense_id: UUID) -> None:
        claim = await self.get(expense_id, lock=True)
        self._require_edit(claim)
        if claim.status.upper() not in {"DRAFT", "CHANGES_REQUESTED", "REJECTED"}:
            raise HTTPException(409, "Only draft, changes-requested or rejected claims can be deleted.")
        claim.deleted_at = claim.updated_at = datetime.now(timezone.utc)
        await self._audit(claim, "DELETED", claim.status)
        await self.db.commit()

    async def transition(self, expense_id: UUID, target: str, *, reason=None,
                         payment: ExpensePayment | None = None, commit=True) -> ReimbursementClaim:
        claim = await self.get(expense_id, lock=True)
        target = target.upper()
        if target == "SUBMITTED":
            self._require_edit(claim)
        elif target in {"APPROVED", "REJECTED", "CHANGES_REQUESTED"}:
            if claim.employee_id == self.actor.employee_id or not self.actor.can_review_employee(claim.employee_id):
                raise HTTPException(403, "Review permission is required; self-review is not permitted.")
        elif target == "PAID":
            if not self.actor.can_pay:
                raise HTTPException(403, "Explicit expenses:pay permission is required.")
        else:
            raise HTTPException(409, "Invalid expense status transition.")
        before = claim.status.upper()
        if target not in self.transitions.get(before, set()):
            raise HTTPException(409, f"Cannot transition an expense from {before.lower()} to {target.lower()}.")
        if target in {"REJECTED", "CHANGES_REQUESTED"} and not reason:
            raise HTTPException(422, "A reason is required.")
        now = datetime.now(timezone.utc)
        details = {}
        if target in {"APPROVED", "REJECTED", "CHANGES_REQUESTED"}:
            claim.reviewed_by, claim.reviewed_at = self.actor.user_id, now
        if target == "APPROVED":
            claim.approved_by, claim.approved_at = self.actor.user_id, now
            claim.rejection_reason = None
        elif target == "REJECTED":
            claim.rejection_reason = reason
        elif target == "PAID":
            if payment is None:
                raise HTTPException(422, "Payment reference, method and timezone-aware timestamp are required.")
            if claim.paid_at or claim.payment_reference:
                raise HTTPException(409, "A payment is already recorded for this expense.")
            if claim.pay_cycle_id or claim.payout_mode == "CYCLE":
                raise HTTPException(409, "Expense is assigned to payroll; complete payment through its payroll workflow.")
            claim.payment_reference = payment.payment_reference
            claim.payment_method = payment.payment_method
            claim.paid_at, claim.paid_by = payment.paid_at, self.actor.user_id
            details = {"payment_reference": payment.payment_reference, "payment_method": payment.payment_method,
                       "paid_at": payment.paid_at.isoformat(), "amount": str(claim.amount), "currency": claim.currency}
        claim.status, claim.updated_at = target, now
        await self._audit(claim, target, before, reason, details)
        if commit:
            await self.db.commit()
        return claim

    @staticmethod
    def serialize(claim: ReimbursementClaim) -> dict:
        employee = claim.employee
        data = {name: getattr(claim, name) for name in (
            "id", "employee_id", "category", "amount", "currency", "description", "merchant", "receipt_url",
            "project_id", "approved_by", "approved_at", "reviewed_by", "reviewed_at", "rejection_reason",
            "payment_reference", "payment_method", "paid_at", "paid_by", "created_at", "updated_at",
        )}
        data.update(organization_id=claim.company_id, expense_date=claim.claim_date,
                    status="approved" if claim.status.upper() == "PAYROLL_APPROVED" else claim.status.lower(),
                    employee={"id": employee.id, "employee_code": employee.employee_id,
                              "name": f"{employee.first_name} {employee.last_name}".strip(),
                              "department": employee.department, "designation": employee.designation})
        return data
