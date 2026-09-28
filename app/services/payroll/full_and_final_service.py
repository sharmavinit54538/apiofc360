"""Service for Full & Final Settlement (FnF) workflow."""

from __future__ import annotations

import io
import logging
import uuid
from datetime import date, datetime
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employee import Employee
from app.models.payroll_models import Compensation, FullAndFinalSettlement
from app.schemas.payroll_v2.full_and_final import ExitDetails
from app.services.payroll.audit_service import PayrollAuditService

logger = logging.getLogger(__name__)


class FullAndFinalService:
    """Business logic for employee exit Full & Final settlements."""

    @classmethod
    async def get_settlement(cls, session: AsyncSession, fnf_id: uuid.UUID) -> FullAndFinalSettlement:
        stmt = select(FullAndFinalSettlement).where(FullAndFinalSettlement.id == fnf_id)
        res = await session.execute(stmt)
        item = res.scalar_one_or_none()
        if not item:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Full & Final settlement '{fnf_id}' not found.",
            )
        return item

    @classmethod
    async def list_settlements(
        cls,
        session: AsyncSession,
        company_id: Optional[uuid.UUID] = None,
        status_filter: Optional[str] = None,
        department: Optional[str] = None,
        search: Optional[str] = None,
        page: int = 1,
        limit: int = 20,
    ) -> dict[str, Any]:
        stmt = (
            select(FullAndFinalSettlement)
            .join(Employee, FullAndFinalSettlement.employee_id == Employee.id)
        )
        if company_id:
            stmt = stmt.where(FullAndFinalSettlement.company_id == company_id)
        if status_filter:
            stmt = stmt.where(func.upper(FullAndFinalSettlement.status) == status_filter.upper())
        if department:
            stmt = stmt.where(Employee.department == department)
        if search:
            stmt = stmt.where(
                or_(
                    Employee.first_name.ilike(f"%{search}%"),
                    Employee.last_name.ilike(f"%{search}%"),
                    Employee.employee_id.ilike(f"%{search}%"),
                )
            )

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await session.execute(count_stmt)).scalar() or 0

        offset = max(0, (page - 1) * limit)
        stmt = stmt.order_by(desc(FullAndFinalSettlement.created_at)).offset(offset).limit(limit)
        items = (await session.execute(stmt)).scalars().all()

        return {
            "items": items,
            "total": total,
            "page": page,
            "limit": limit,
        }

    @classmethod
    async def create_settlement(
        cls,
        session: AsyncSession,
        employee_id: uuid.UUID,
        exit_details: ExitDetails,
        remarks: Optional[str] = None,
        company_id: Optional[uuid.UUID] = None,
        user_id: Optional[uuid.UUID] = None,
    ) -> FullAndFinalSettlement:
        emp_stmt = select(Employee).where(Employee.id == employee_id)
        emp = (await session.execute(emp_stmt)).scalar_one_or_none()
        if not emp:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Employee '{employee_id}' not found.",
            )

        target_company_id = company_id or emp.company_id

        # Calculate preliminary net payable in paise
        comp_stmt = select(Compensation).where(
            Compensation.employee_id == employee_id, Compensation.status == "ACTIVE"
        )
        comp = (await session.execute(comp_stmt)).scalar_one_or_none()
        monthly_ctc_paise = (comp.ctc_annual_paise // 12) if comp else (50000 * 100)

        daily_rate_paise = monthly_ctc_paise // 30
        notice_shortfall_deduction = exit_details.shortfall_days * daily_rate_paise
        pending_salary_paise = monthly_ctc_paise
        net_payable_paise = max(0, pending_salary_paise - notice_shortfall_deduction)

        settlement = FullAndFinalSettlement(
            id=uuid.uuid4(),
            employee_id=employee_id,
            company_id=target_company_id,
            resignation_date=exit_details.resignation_date,
            last_working_date=exit_details.last_working_date,
            exit_type=exit_details.exit_type,
            reason=exit_details.reason,
            notice_period_days_required=exit_details.notice_period_days_required,
            notice_period_days_served=exit_details.notice_period_days_served,
            shortfall_days=exit_details.shortfall_days,
            status="PENDING_APPROVAL",
            net_payable_paise=net_payable_paise,
            settlement_breakup={
                "monthly_salary_paise": monthly_ctc_paise,
                "shortfall_deduction_paise": notice_shortfall_deduction,
                "net_payable_paise": net_payable_paise,
            },
            remarks=remarks,
        )
        session.add(settlement)
        await session.commit()
        await session.refresh(settlement)

        await PayrollAuditService.log_event(
            session=session,
            entity_type="FullAndFinalSettlement",
            entity_id=settlement.id,
            action="CREATE",
            company_id=target_company_id,
            actor_id=user_id,
            before_status=None,
            after_status="PENDING_APPROVAL",
            reason=remarks or "Created F&F settlement request",
        )
        return settlement

    @classmethod
    async def approve_settlement(
        cls,
        session: AsyncSession,
        fnf_id: uuid.UUID,
        remarks: Optional[str] = None,
        user_id: Optional[uuid.UUID] = None,
        user_role: Optional[str] = None,
    ) -> FullAndFinalSettlement:
        settlement = await cls.get_settlement(session, fnf_id)
        if settlement.status in ("APPROVED", "FINALIZED"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Settlement already in '{settlement.status}' status.",
            )

        old_status = settlement.status
        settlement.status = "APPROVED"
        settlement.approved_by = user_id
        settlement.approved_at = datetime.now()
        settlement.remarks = remarks

        await PayrollAuditService.log_event(
            session=session,
            entity_type="FullAndFinalSettlement",
            entity_id=settlement.id,
            action="APPROVE",
            company_id=settlement.company_id,
            actor_id=user_id,
            actor_role=user_role,
            before_status=old_status,
            after_status="APPROVED",
            reason=remarks or "Approved F&F settlement",
        )
        await session.commit()
        await session.refresh(settlement)
        return settlement

    @classmethod
    async def finalize_settlement(
        cls,
        session: AsyncSession,
        fnf_id: uuid.UUID,
        notes: Optional[str] = None,
        user_id: Optional[uuid.UUID] = None,
        user_role: Optional[str] = None,
    ) -> FullAndFinalSettlement:
        settlement = await cls.get_settlement(session, fnf_id)
        old_status = settlement.status
        settlement.status = "FINALIZED"
        settlement.finalized_by = user_id
        settlement.finalized_at = datetime.now()
        settlement.notes = notes

        await PayrollAuditService.log_event(
            session=session,
            entity_type="FullAndFinalSettlement",
            entity_id=settlement.id,
            action="FINALIZE",
            company_id=settlement.company_id,
            actor_id=user_id,
            actor_role=user_role,
            before_status=old_status,
            after_status="FINALIZED",
            reason=notes or "Finalized F&F settlement",
        )
        await session.commit()
        await session.refresh(settlement)
        return settlement

    @classmethod
    async def reject_settlement(
        cls,
        session: AsyncSession,
        fnf_id: uuid.UUID,
        reason: str,
        user_id: Optional[uuid.UUID] = None,
        user_role: Optional[str] = None,
    ) -> FullAndFinalSettlement:
        settlement = await cls.get_settlement(session, fnf_id)
        old_status = settlement.status
        settlement.status = "REJECTED"
        settlement.rejected_by = user_id
        settlement.rejected_at = datetime.now()
        settlement.rejection_reason = reason

        await PayrollAuditService.log_event(
            session=session,
            entity_type="FullAndFinalSettlement",
            entity_id=settlement.id,
            action="REJECT",
            company_id=settlement.company_id,
            actor_id=user_id,
            actor_role=user_role,
            before_status=old_status,
            after_status="REJECTED",
            reason=reason,
        )
        await session.commit()
        await session.refresh(settlement)
        return settlement

    @classmethod
    async def generate_statement(cls, session: AsyncSession, fnf_id: uuid.UUID) -> tuple[bytes, str]:
        settlement = await cls.get_settlement(session, fnf_id)
        emp_stmt = select(Employee).where(Employee.id == settlement.employee_id)
        emp = (await session.execute(emp_stmt)).scalar_one_or_none()

        emp_name = f"{emp.first_name} {emp.last_name}".strip() if emp else "Employee"
        statement_text = (
            f"FULL & FINAL SETTLEMENT STATEMENT\n"
            f"===================================\n"
            f"Settlement ID: {settlement.id}\n"
            f"Employee: {emp_name} ({emp.employee_id if emp else ''})\n"
            f"Resignation Date: {settlement.resignation_date}\n"
            f"Last Working Date: {settlement.last_working_date}\n"
            f"Exit Type: {settlement.exit_type}\n"
            f"Notice Required / Served: {settlement.notice_period_days_required} / {settlement.notice_period_days_served} days\n"
            f"Shortfall: {settlement.shortfall_days} days\n"
            f"Status: {settlement.status}\n"
            f"-----------------------------------\n"
            f"Net Payable: Rs. {settlement.net_payable_paise / 100.0:,.2f}\n"
            f"===================================\n"
        )
        filename = f"FnF_Statement_{settlement.id}.txt"
        return statement_text.encode("utf-8"), filename
