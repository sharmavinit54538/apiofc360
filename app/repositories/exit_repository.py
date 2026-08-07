"""Exit Management repository layer: direct database operations."""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.exit import (
    EmployeeExit,
    KnowledgeTransfer,
    AssetReturn,
    ClearanceRequest,
    ExitInterview,
    FnfSettlement,
    ExitDocument,
)
from app.models.employee import Employee

logger = logging.getLogger(__name__)


class ExitRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _active_filter(self):
        return EmployeeExit.is_deleted == False  # noqa: E712

    # ------------------------------------------------------------------
    # EmployeeExit CRUD
    # ------------------------------------------------------------------

    async def create_exit(self, **kwargs: Any) -> EmployeeExit:
        obj = EmployeeExit(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def get_exit_by_id(self, exit_uuid: uuid.UUID) -> EmployeeExit | None:
        result = await self.session.execute(
            select(EmployeeExit)
            .where(and_(EmployeeExit.id == exit_uuid, self._active_filter()))
            .options(
                selectinload(EmployeeExit.employee),
                selectinload(EmployeeExit.knowledge_transfers),
                selectinload(EmployeeExit.asset_returns),
                selectinload(EmployeeExit.clearances),
                selectinload(EmployeeExit.exit_interviews),
                selectinload(EmployeeExit.fnf_settlements),
                selectinload(EmployeeExit.documents),
            )
        )
        return result.scalar_one_or_none()

    async def get_active_exit_by_employee_id(self, employee_uuid: uuid.UUID) -> EmployeeExit | None:
        result = await self.session.execute(
            select(EmployeeExit)
            .where(
                and_(
                    EmployeeExit.employee_id == employee_uuid,
                    self._active_filter(),
                    EmployeeExit.status != "COMPLETED",
                    EmployeeExit.status != "CANCELLED",
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_exit_by_employee_id_raw(self, employee_uuid: uuid.UUID) -> EmployeeExit | None:
        result = await self.session.execute(
            select(EmployeeExit)
            .where(and_(EmployeeExit.employee_id == employee_uuid, self._active_filter()))
            .order_by(EmployeeExit.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_exits(
        self,
        status: str | None = None,
        search: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[EmployeeExit]:
        stmt = select(EmployeeExit).where(self._active_filter()).options(
            selectinload(EmployeeExit.employee),
        )

        if status:
            stmt = stmt.where(EmployeeExit.status == status.upper())
        if search:
            pattern = f"%{search}%"
            # Join Employee for search
            stmt = stmt.join(Employee, EmployeeExit.employee_id == Employee.id).where(
                or_(
                    Employee.first_name.ilike(pattern),
                    Employee.last_name.ilike(pattern),
                    Employee.employee_id.ilike(pattern),
                    EmployeeExit.reason.ilike(pattern),
                )
            )

        stmt = stmt.order_by(EmployeeExit.created_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_exits(
        self,
        status: str | None = None,
        search: str | None = None,
    ) -> int:
        stmt = select(func.count()).select_from(EmployeeExit).where(self._active_filter())

        if status:
            stmt = stmt.where(EmployeeExit.status == status.upper())
        if search:
            pattern = f"%{search}%"
            stmt = stmt.join(Employee, EmployeeExit.employee_id == Employee.id).where(
                or_(
                    Employee.first_name.ilike(pattern),
                    Employee.last_name.ilike(pattern),
                    Employee.employee_id.ilike(pattern),
                    EmployeeExit.reason.ilike(pattern),
                )
            )

        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def update_exit_status(self, exit_uuid: uuid.UUID, status: str, **kwargs: Any) -> None:
        vals = {"status": status.upper()}
        vals.update(kwargs)
        await self.session.execute(
            update(EmployeeExit).where(EmployeeExit.id == exit_uuid).values(**vals)
        )

    async def soft_delete_exit(self, exit_uuid: uuid.UUID) -> None:
        await self.session.execute(
            update(EmployeeExit)
            .where(EmployeeExit.id == exit_uuid)
            .values(is_deleted=True, deleted_at=func.now())
        )

    # ------------------------------------------------------------------
    # Knowledge Transfer Repository methods
    # ------------------------------------------------------------------

    async def get_kt_by_exit_id(self, exit_uuid: uuid.UUID) -> KnowledgeTransfer | None:
        result = await self.session.execute(
            select(KnowledgeTransfer).where(KnowledgeTransfer.exit_id == exit_uuid)
        )
        return result.scalar_one_or_none()

    async def upsert_kt(self, exit_uuid: uuid.UUID, data: dict) -> KnowledgeTransfer:
        existing = await self.get_kt_by_exit_id(exit_uuid)
        if existing:
            for k, v in data.items():
                setattr(existing, k, v)
            return existing
        obj = KnowledgeTransfer(exit_id=exit_uuid, **data)
        self.session.add(obj)
        await self.session.flush()
        return obj

    # ------------------------------------------------------------------
    # Asset Return Repository methods
    # ------------------------------------------------------------------

    async def get_asset_returns_by_exit_id(self, exit_uuid: uuid.UUID) -> list[AssetReturn]:
        result = await self.session.execute(
            select(AssetReturn).where(AssetReturn.exit_id == exit_uuid)
        )
        return list(result.scalars().all())

    async def get_asset_return_by_name(self, exit_uuid: uuid.UUID, asset_name: str) -> AssetReturn | None:
        result = await self.session.execute(
            select(AssetReturn).where(
                and_(
                    AssetReturn.exit_id == exit_uuid,
                    func.lower(AssetReturn.asset_name) == asset_name.lower(),
                )
            )
        )
        return result.scalar_one_or_none()

    async def upsert_asset_return(self, exit_uuid: uuid.UUID, asset_name: str, data: dict) -> AssetReturn:
        existing = await self.get_asset_return_by_name(exit_uuid, asset_name)
        if existing:
            for k, v in data.items():
                setattr(existing, k, v)
            return existing
        obj = AssetReturn(exit_id=exit_uuid, asset_name=asset_name.strip(), **data)
        self.session.add(obj)
        await self.session.flush()
        return obj

    # ------------------------------------------------------------------
    # Clearance Repository methods
    # ------------------------------------------------------------------

    async def get_clearance_by_exit_id(self, exit_uuid: uuid.UUID) -> ClearanceRequest | None:
        result = await self.session.execute(
            select(ClearanceRequest).where(ClearanceRequest.exit_id == exit_uuid)
        )
        return result.scalar_one_or_none()

    async def upsert_clearance(self, exit_uuid: uuid.UUID, data: dict) -> ClearanceRequest:
        existing = await self.get_clearance_by_exit_id(exit_uuid)
        if existing:
            for k, v in data.items():
                setattr(existing, k, v)
            
            # Check overall clearance status
            all_cleared = (
                existing.it_clearance and
                existing.hr_clearance and
                existing.finance_clearance and
                existing.admin_clearance and
                existing.manager_clearance and
                existing.security_clearance
            )
            existing.overall_status = "CLEARED" if all_cleared else "PENDING"
            return existing

        obj = ClearanceRequest(exit_id=exit_uuid, **data)
        all_cleared = (
            obj.it_clearance and
            obj.hr_clearance and
            obj.finance_clearance and
            obj.admin_clearance and
            obj.manager_clearance and
            obj.security_clearance
        )
        obj.overall_status = "CLEARED" if all_cleared else "PENDING"
        self.session.add(obj)
        await self.session.flush()
        return obj

    # ------------------------------------------------------------------
    # Exit Interview Repository methods
    # ------------------------------------------------------------------

    async def get_interview_by_exit_id(self, exit_uuid: uuid.UUID) -> ExitInterview | None:
        result = await self.session.execute(
            select(ExitInterview).where(ExitInterview.exit_id == exit_uuid)
        )
        return result.scalar_one_or_none()

    async def upsert_exit_interview(self, exit_uuid: uuid.UUID, data: dict) -> ExitInterview:
        existing = await self.get_interview_by_exit_id(exit_uuid)
        if existing:
            for k, v in data.items():
                setattr(existing, k, v)
            return existing
        obj = ExitInterview(exit_id=exit_uuid, **data)
        self.session.add(obj)
        await self.session.flush()
        return obj

    # ------------------------------------------------------------------
    # FNF Settlement Repository methods
    # ------------------------------------------------------------------

    async def get_fnf_by_exit_id(self, exit_uuid: uuid.UUID) -> FnfSettlement | None:
        result = await self.session.execute(
            select(FnfSettlement).where(FnfSettlement.exit_id == exit_uuid)
        )
        return result.scalar_one_or_none()

    async def upsert_fnf(self, exit_uuid: uuid.UUID, data: dict) -> FnfSettlement:
        existing = await self.get_fnf_by_exit_id(exit_uuid)
        
        # Calculate net payable
        earnings = (
            Decimal(str(data.get("last_salary", 0.0))) +
            Decimal(str(data.get("pending_salary", 0.0))) +
            Decimal(str(data.get("leave_encashment", 0.0))) +
            Decimal(str(data.get("bonus", 0.0))) +
            Decimal(str(data.get("incentives", 0.0)))
        )
        deductions = (
            Decimal(str(data.get("recoveries", 0.0))) +
            Decimal(str(data.get("notice_recovery", 0.0))) +
            Decimal(str(data.get("asset_recovery", 0.0))) +
            Decimal(str(data.get("loan_recovery", 0.0))) +
            Decimal(str(data.get("other_deductions", 0.0)))
        )
        net_payable = earnings - deductions

        if existing:
            for k, v in data.items():
                setattr(existing, k, v)
            existing.net_payable_amount = net_payable
            return existing

        obj = FnfSettlement(exit_id=exit_uuid, net_payable_amount=net_payable, **data)
        self.session.add(obj)
        await self.session.flush()
        return obj

    # ------------------------------------------------------------------
    # Exit Document Repository methods
    # ------------------------------------------------------------------

    async def create_exit_document(self, **kwargs: Any) -> ExitDocument:
        obj = ExitDocument(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def get_documents_by_exit_id(self, exit_uuid: uuid.UUID) -> list[ExitDocument]:
        result = await self.session.execute(
            select(ExitDocument).where(ExitDocument.exit_id == exit_uuid)
        )
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Dashboard Metrics
    # ------------------------------------------------------------------

    async def get_dashboard_metrics(self) -> dict[str, int]:
        p_resign = await self.session.execute(select(func.count(EmployeeExit.id)).where(and_(EmployeeExit.status == "SUBMITTED", self._active_filter())))
        p_mgr = await self.session.execute(select(func.count(EmployeeExit.id)).where(and_(EmployeeExit.status == "PENDING_MANAGER_APPROVAL", self._active_filter())))
        p_hr = await self.session.execute(select(func.count(EmployeeExit.id)).where(and_(EmployeeExit.status == "PENDING_HR_APPROVAL", self._active_filter())))
        notice = await self.session.execute(select(func.count(EmployeeExit.id)).where(and_(EmployeeExit.status == "NOTICE_PERIOD", self._active_filter())))
        
        p_kt = await self.session.execute(
            select(func.count(EmployeeExit.id)).select_from(EmployeeExit)
            .join(KnowledgeTransfer, EmployeeExit.id == KnowledgeTransfer.exit_id)
            .where(and_(KnowledgeTransfer.is_completed == False, self._active_filter()))  # noqa: E712
        )
        p_asset = await self.session.execute(
            select(func.count(EmployeeExit.id)).select_from(EmployeeExit)
            .join(AssetReturn, EmployeeExit.id == AssetReturn.exit_id)
            .where(and_(AssetReturn.return_status == "PENDING", self._active_filter()))
        )
        p_clearance = await self.session.execute(
            select(func.count(EmployeeExit.id)).select_from(EmployeeExit)
            .join(ClearanceRequest, EmployeeExit.id == ClearanceRequest.exit_id)
            .where(and_(ClearanceRequest.overall_status == "PENDING", self._active_filter()))
        )
        p_interview = await self.session.execute(
            select(func.count(EmployeeExit.id)).select_from(EmployeeExit)
            .outerjoin(ExitInterview, EmployeeExit.id == ExitInterview.exit_id)
            .where(and_(ExitInterview.id == None, EmployeeExit.status == "EXIT_INTERVIEW_PENDING", self._active_filter()))  # noqa: E711
        )
        p_fnf = await self.session.execute(
            select(func.count(EmployeeExit.id)).select_from(EmployeeExit)
            .join(FnfSettlement, EmployeeExit.id == FnfSettlement.exit_id)
            .where(and_(FnfSettlement.payment_status == "PENDING", self._active_filter()))
        )
        completed = await self.session.execute(select(func.count(EmployeeExit.id)).where(and_(EmployeeExit.status == "COMPLETED", self._active_filter())))

        return {
            "pending_resignations": p_resign.scalar() or 0,
            "pending_manager_approval": p_mgr.scalar() or 0,
            "pending_hr_approval": p_hr.scalar() or 0,
            "employees_in_notice_period": notice.scalar() or 0,
            "pending_knowledge_transfer": p_kt.scalar() or 0,
            "pending_asset_return": p_asset.scalar() or 0,
            "pending_no_dues": p_clearance.scalar() or 0,
            "pending_exit_interviews": p_interview.scalar() or 0,
            "pending_final_settlement": p_fnf.scalar() or 0,
            "completed_exits": completed.scalar() or 0,
        }
