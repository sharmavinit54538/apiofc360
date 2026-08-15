"""Exit Management service layer coordinating approvals, clearances, and termination lifecycles."""

from __future__ import annotations

import logging
import math
import uuid
from decimal import Decimal
from datetime import date, datetime, timezone

from fastapi import Depends, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, ConflictException, DatabaseException
from app.db.database import get_db_session
from app.repositories.auth_repository import AuthRepository
from app.repositories.employee_repository import EmployeeRepository
from app.repositories.exit_repository import ExitRepository
from app.schemas.exit import (
    AssetReturnCreate,
    AssetReturnResponse,
    ClearanceResponse,
    ClearanceUpdate,
    ExitDashboardStats,
    ExitDocumentResponse,
    ExitInterviewCreate,
    ExitInterviewResponse,
    ExitListResponse,
    ExitResponse,
    FnfCreate,
    FnfResponse,
    KTCreate,
    KTResponse,
    ResignationRequest,
)

logger = logging.getLogger(__name__)


class ExitService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        repo: ExitRepository,
        auth_repo: AuthRepository,
        employee_repo: EmployeeRepository,
    ) -> None:
        self.session = session
        self.repo = repo
        self.auth_repo = auth_repo
        self.employee_repo = employee_repo

    # ------------------------------------------------------------------
    # Dashboard Metrics
    # ------------------------------------------------------------------

    async def get_dashboard_stats(self) -> ExitDashboardStats:
        try:
            metrics = await self.repo.get_dashboard_metrics()
            return ExitDashboardStats(**metrics)
        except SQLAlchemyError as exc:
            logger.exception("get_dashboard_stats: db error", exc_info=exc)
            raise DatabaseException() from exc

    # ------------------------------------------------------------------
    # Employee Operations
    # ------------------------------------------------------------------

    async def submit_resignation(self, user_id: uuid.UUID, payload: ResignationRequest) -> ExitResponse:
        logger.info("submit_resignation | user_id=%s | last_date=%s", user_id, payload.last_working_date)
        try:
            employee = await self.employee_repo.get_by_user_id(user_id)
            if not employee:
                raise AppException(message="Employee profile not found.", status_code=status.HTTP_404_NOT_FOUND)

            # Check for existing active resignation request
            existing = await self.repo.get_active_exit_by_employee_id(employee.id)
            if existing:
                raise ConflictException(message="You already have an active resignation request pending or in progress.")

            exit_kwargs = {
                "employee_id": employee.id,
                "last_working_date": payload.last_working_date,
                "reason": payload.reason,
                "comments": payload.comments,
                "personal_email": payload.personal_email,
                "personal_phone": payload.personal_phone,
                "status": "SUBMITTED",
            }

            exit_obj = await self.repo.create_exit(**exit_kwargs)

            # Seed default empty checklists
            await self.repo.upsert_clearance(exit_obj.id, {
                "it_clearance": False,
                "hr_clearance": False,
                "finance_clearance": False,
                "admin_clearance": False,
                "manager_clearance": False,
                "security_clearance": False,
            })

            await self.repo.upsert_kt(exit_obj.id, {
                "projects_handed_over": "Pending Handover Description",
                "is_completed": False,
            })

            # Seed standard assets returns checklist
            default_assets = ["Laptop", "Monitor", "Keyboard", "Mouse", "SIM Card", "Access Card", "ID Card"]
            for asset in default_assets:
                await self.repo.upsert_asset_return(exit_obj.id, asset, {"return_status": "PENDING"})

            await self.session.commit()

            full_exit = await self.repo.get_exit_by_id(exit_obj.id)
            return ExitResponse.model_validate(full_exit)

        except (AppException, ConflictException):
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("submit_resignation: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def get_my_request(self, user_id: uuid.UUID) -> ExitResponse:
        try:
            employee = await self.employee_repo.get_by_user_id(user_id)
            if not employee:
                raise AppException(message="Employee profile not found.", status_code=status.HTTP_404_NOT_FOUND)

            exit_obj = await self.repo.get_exit_by_employee_id_raw(employee.id)
            if not exit_obj:
                raise AppException(message="No resignation request found.", status_code=status.HTTP_404_NOT_FOUND)

            full_exit = await self.repo.get_exit_by_id(exit_obj.id)
            return ExitResponse.model_validate(full_exit)
        except AppException:
            raise
        except SQLAlchemyError as exc:
            logger.exception("get_my_request: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def cancel_my_request(self, user_id: uuid.UUID) -> None:
        logger.info("cancel_my_request | user_id=%s", user_id)
        try:
            employee = await self.employee_repo.get_by_user_id(user_id)
            if not employee:
                raise AppException(message="Employee profile not found.", status_code=status.HTTP_404_NOT_FOUND)

            exit_obj = await self.repo.get_active_exit_by_employee_id(employee.id)
            if not exit_obj:
                raise AppException(message="No active resignation request found to cancel.", status_code=status.HTTP_404_NOT_FOUND)

            # Allowed to cancel only if not fully approved
            if exit_obj.status in {"COMPLETED", "NOTICE_PERIOD", "HR_APPROVED"}:
                raise AppException(message="Cannot cancel resignation request after HR approval.", status_code=status.HTTP_400_BAD_REQUEST)

            await self.repo.update_exit_status(exit_obj.id, "CANCELLED")
            await self.session.commit()

        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("cancel_my_request: db error", exc_info=exc)
            raise DatabaseException() from exc

    # ------------------------------------------------------------------
    # Manager Approvals
    # ------------------------------------------------------------------

    async def manager_approve(self, exit_uuid: uuid.UUID, remarks: str | None) -> ExitResponse:
        logger.info("manager_approve | exit_id=%s", exit_uuid)
        try:
            exit_obj = await self.repo.get_exit_by_id(exit_uuid)
            if not exit_obj:
                raise AppException(message="Exit request not found.", status_code=status.HTTP_404_NOT_FOUND)

            await self.repo.update_exit_status(exit_uuid, "PENDING_HR_APPROVAL", manager_remarks=remarks)
            
            # Automatically check manager clearance box
            await self.repo.upsert_clearance(exit_uuid, {"manager_clearance": True})

            await self.session.commit()
            full_exit = await self.repo.get_exit_by_id(exit_uuid)
            return ExitResponse.model_validate(full_exit)
        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("manager_approve: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def manager_reject(self, exit_uuid: uuid.UUID, remarks: str | None) -> ExitResponse:
        logger.info("manager_reject | exit_id=%s", exit_uuid)
        try:
            exit_obj = await self.repo.get_exit_by_id(exit_uuid)
            if not exit_obj:
                raise AppException(message="Exit request not found.", status_code=status.HTTP_440_NOT_FOUND if hasattr(status, "HTTP_440_NOT_FOUND") else status.HTTP_404_NOT_FOUND)

            await self.repo.update_exit_status(exit_uuid, "MANAGER_REJECTED", manager_remarks=remarks)
            await self.session.commit()
            full_exit = await self.repo.get_exit_by_id(exit_uuid)
            return ExitResponse.model_validate(full_exit)
        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("manager_reject: db error", exc_info=exc)
            raise DatabaseException() from exc

    # ------------------------------------------------------------------
    # HR Approvals & Notice transitions
    # ------------------------------------------------------------------

    async def list_exits(
        self,
        status_filter: str | None,
        search: str | None,
        page: int,
        limit: int,
    ) -> ExitListResponse:
        try:
            offset = (page - 1) * limit
            exits = await self.repo.list_exits(
                status=status_filter,
                search=search,
                limit=limit,
                offset=offset,
            )
            total = await self.repo.count_exits(
                status=status_filter,
                search=search,
            )

            items = []
            for e in exits:
                items.append({
                    "id": e.id,
                    "employee_id": e.employee_id,
                    "employee_name": f"{e.employee.first_name} {e.employee.last_name}",
                    "employee_code": e.employee.employee_id,
                    "department": e.employee.department,
                    "status": e.status,
                    "last_working_date": e.last_working_date,
                    "reason": e.reason,
                    "created_at": e.created_at,
                })

            pages = math.ceil(total / limit) if limit > 0 else 0
            return ExitListResponse(items=items, total=total, page=page, limit=limit, pages=pages)
        except SQLAlchemyError as exc:
            logger.exception("list_exits: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def get_exit(self, exit_uuid: uuid.UUID) -> ExitResponse:
        try:
            exit_obj = await self.repo.get_exit_by_id(exit_uuid)
            if not exit_obj:
                raise AppException(message="Exit request not found.", status_code=status.HTTP_404_NOT_FOUND)
            return ExitResponse.model_validate(exit_obj)
        except AppException:
            raise
        except SQLAlchemyError as exc:
            logger.exception("get_exit: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def hr_approve(self, exit_uuid: uuid.UUID, remarks: str | None) -> ExitResponse:
        logger.info("hr_approve | exit_id=%s", exit_uuid)
        try:
            exit_obj = await self.repo.get_exit_by_id(exit_uuid)
            if not exit_obj:
                raise AppException(message="Exit request not found.", status_code=status.HTTP_404_NOT_FOUND)

            await self.repo.update_exit_status(exit_uuid, "HR_APPROVED", hr_remarks=remarks)
            await self.repo.upsert_clearance(exit_uuid, {"hr_clearance": True})

            await self.session.commit()
            full_exit = await self.repo.get_exit_by_id(exit_uuid)
            return ExitResponse.model_validate(full_exit)
        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("hr_approve: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def hr_reject(self, exit_uuid: uuid.UUID, remarks: str | None) -> ExitResponse:
        logger.info("hr_reject | exit_id=%s", exit_uuid)
        try:
            exit_obj = await self.repo.get_exit_by_id(exit_uuid)
            if not exit_obj:
                raise AppException(message="Exit request not found.", status_code=status.HTTP_404_NOT_FOUND)

            await self.repo.update_exit_status(exit_uuid, "CANCELLED", hr_remarks=remarks)
            await self.session.commit()
            full_exit = await self.repo.get_exit_by_id(exit_uuid)
            return ExitResponse.model_validate(full_exit)
        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("hr_reject: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def start_notice_period(self, exit_uuid: uuid.UUID) -> ExitResponse:
        logger.info("start_notice_period | exit_id=%s", exit_uuid)
        try:
            exit_obj = await self.repo.get_exit_by_id(exit_uuid)
            if not exit_obj:
                raise AppException(message="Exit request not found.", status_code=status.HTTP_404_NOT_FOUND)

            # Notice starts only after HR approval
            if exit_obj.status not in {"HR_APPROVED", "PENDING_HR_APPROVAL"}:
                raise AppException(message="HR Approval is required before starting the notice period.", status_code=status.HTTP_400_BAD_REQUEST)

            await self.repo.update_exit_status(exit_uuid, "NOTICE_PERIOD")
            
            # Switch employee status to NOTICE_PERIOD
            from sqlalchemy import update as sa_update
            from app.models.employee import Employee
            await self.session.execute(
                sa_update(Employee).where(Employee.id == exit_obj.employee_id).values(employment_status="NOTICE_PERIOD")
            )

            await self.session.commit()
            full_exit = await self.repo.get_exit_by_id(exit_uuid)
            return ExitResponse.model_validate(full_exit)

        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("start_notice_period: db error", exc_info=exc)
            raise DatabaseException() from exc

    # ------------------------------------------------------------------
    # Knowledge Transfer, Assets & Clearances
    # ------------------------------------------------------------------

    async def complete_kt(self, exit_uuid: uuid.UUID, payload: KTCreate) -> KTResponse:
        try:
            exit_obj = await self.repo.get_exit_by_id(exit_uuid)
            if not exit_obj:
                raise AppException(message="Exit request not found.", status_code=status.HTTP_404_NOT_FOUND)

            data = payload.model_dump()
            if payload.is_completed and not payload.completion_date:
                data["completion_date"] = date.today()

            kt = await self.repo.upsert_kt(exit_uuid, data)
            await self.session.commit()
            return KTResponse.model_validate(kt)
        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("complete_kt: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def get_assets(self, exit_uuid: uuid.UUID) -> list[AssetReturnResponse]:
        try:
            assets = await self.repo.get_asset_returns_by_exit_id(exit_uuid)
            return [AssetReturnResponse.model_validate(a) for a in assets]
        except SQLAlchemyError as exc:
            logger.exception("get_assets: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def return_asset(self, exit_uuid: uuid.UUID, payload: AssetReturnCreate) -> AssetReturnResponse:
        try:
            exit_obj = await self.repo.get_exit_by_id(exit_uuid)
            if not exit_obj:
                raise AppException(message="Exit request not found.", status_code=status.HTTP_404_NOT_FOUND)

            data = payload.model_dump(exclude={"asset_name"})
            if payload.return_status == "RETURNED" and not payload.return_date:
                data["return_date"] = date.today()

            asset = await self.repo.upsert_asset_return(exit_uuid, payload.asset_name, data)
            await self.session.commit()
            return AssetReturnResponse.model_validate(asset)
        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("return_asset: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def update_clearance(self, exit_uuid: uuid.UUID, payload: ClearanceUpdate) -> ClearanceResponse:
        try:
            exit_obj = await self.repo.get_exit_by_id(exit_uuid)
            if not exit_obj:
                raise AppException(message="Exit request not found.", status_code=status.HTTP_404_NOT_FOUND)

            data = {k: v for k, v in payload.model_dump().items() if v is not None}
            cl = await self.repo.upsert_clearance(exit_uuid, data)
            await self.session.commit()
            return ClearanceResponse.model_validate(cl)
        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("update_clearance: db error", exc_info=exc)
            raise DatabaseException() from exc

    # ------------------------------------------------------------------
    # Exit Interview & FNF
    # ------------------------------------------------------------------

    async def submit_exit_interview(self, exit_uuid: uuid.UUID, payload: ExitInterviewCreate) -> ExitInterviewResponse:
        try:
            exit_obj = await self.repo.get_exit_by_id(exit_uuid)
            if not exit_obj:
                raise AppException(message="Exit request not found.", status_code=status.HTTP_404_NOT_FOUND)

            interview = await self.repo.upsert_exit_interview(exit_uuid, payload.model_dump())
            await self.session.commit()
            return ExitInterviewResponse.model_validate(interview)
        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("submit_exit_interview: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def submit_fnf(self, exit_uuid: uuid.UUID, payload: FnfCreate) -> FnfResponse:
        try:
            exit_obj = await self.repo.get_exit_by_id(exit_uuid)
            if not exit_obj:
                raise AppException(message="Exit request not found.", status_code=status.HTTP_404_NOT_FOUND)

            fnf = await self.repo.upsert_fnf(exit_uuid, payload.model_dump())
            await self.session.commit()
            return FnfResponse.model_validate(fnf)
        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("submit_fnf: db error", exc_info=exc)
            raise DatabaseException() from exc

    # ------------------------------------------------------------------
    # Document Generations
    # ------------------------------------------------------------------

    async def get_documents(self, exit_uuid: uuid.UUID) -> list[ExitDocumentResponse]:
        try:
            docs = await self.repo.get_documents_by_exit_id(exit_uuid)
            return [ExitDocumentResponse.model_validate(d) for d in docs]
        except SQLAlchemyError as exc:
            logger.exception("get_documents: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def generate_exit_documents(self, exit_uuid: uuid.UUID) -> list[ExitDocumentResponse]:
        logger.info("generate_exit_documents | exit_id=%s", exit_uuid)
        try:
            exit_obj = await self.repo.get_exit_by_id(exit_uuid)
            if not exit_obj:
                raise AppException(message="Exit request not found.", status_code=status.HTTP_404_NOT_FOUND)

            # Generate default exit letters (Relieving, Experience, FNF Settlement)
            doc_types = ["RELIEVING_LETTER", "EXPERIENCE_LETTER", "FINAL_SETTLEMENT_LETTER"]
            generated = []
            for doc_type in doc_types:
                doc_kwargs = {
                    "exit_id": exit_uuid,
                    "document_type": doc_type,
                    "file_path": f"uploads/exit_documents/{doc_type.lower()}_{exit_uuid}.pdf",
                }
                doc = await self.repo.create_exit_document(**doc_kwargs)
                generated.append(doc)

            await self.session.commit()
            return [ExitDocumentResponse.model_validate(d) for d in generated]

        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("generate_exit_documents: db error", exc_info=exc)
            raise DatabaseException() from exc

    # ------------------------------------------------------------------
    # FNF Final Completion & Account Deactivation
    # ------------------------------------------------------------------

    async def complete_exit(self, exit_uuid: uuid.UUID) -> ExitResponse:
        logger.info("complete_exit | exit_id=%s", exit_uuid)
        try:
            exit_obj = await self.repo.get_exit_by_id(exit_uuid)
            if not exit_obj:
                raise AppException(message="Exit request not found.", status_code=status.HTTP_404_NOT_FOUND)

            # Rule: KT, Assets, clearances, and FNF must be complete
            kt = await self.repo.get_kt_by_exit_id(exit_uuid)
            if not kt or not kt.is_completed:
                raise AppException(message="Knowledge Transfer must be completed first.", status_code=status.HTTP_400_BAD_REQUEST)

            assets = await self.repo.get_asset_returns_by_exit_id(exit_uuid)
            if any(a.return_status == "PENDING" for a in assets):
                raise AppException(message="All assigned assets must be returned first.", status_code=status.HTTP_400_BAD_REQUEST)

            cl = await self.repo.get_clearance_by_exit_id(exit_uuid)
            if not cl or cl.overall_status != "CLEARED":
                raise AppException(message="All department clearance dues must be cleared first.", status_code=status.HTTP_400_BAD_REQUEST)

            fnf = await self.repo.get_fnf_by_exit_id(exit_uuid)
            if not fnf or fnf.payment_status != "PAID":
                raise AppException(message="Full & Final settlement payment must be paid first.", status_code=status.HTTP_400_BAD_REQUEST)

            # 1. Update exit status to COMPLETED
            await self.repo.update_exit_status(exit_uuid, "COMPLETED")

            # 2. Deactivate and archive employee profile
            from sqlalchemy import update as sa_update
            from app.models.employee import Employee
            from app.models.manager import Manager
            from app.models.user import User

            now_utc = datetime.now(timezone.utc)
            await self.session.execute(
                sa_update(Employee)
                .where(Employee.id == exit_obj.employee_id)
                .values(
                    employment_status="EXITED",
                    status="ARCHIVED",
                    is_active=False,
                    deactivated_at=now_utc,
                )
            )

            # 3. Deactivate User credentials & revoke JWT Refresh Tokens
            if exit_obj.employee.user_id:
                await self.session.execute(
                    sa_update(User)
                    .where(User.id == exit_obj.employee.user_id)
                    .values(is_active=False, account_status="DEACTIVATED")
                )
                await self.session.execute(
                    sa_update(Manager)
                    .where(Manager.user_id == exit_obj.employee.user_id)
                    .values(is_active=False, status="ARCHIVED", deactivated_at=now_utc)
                )
                await self.auth_repo.revoke_all_user_refresh_tokens(exit_obj.employee.user_id)

            await self.session.commit()
            logger.info("complete_exit: success | deactivated user_id=%s", exit_obj.employee.user_id)
            full_exit = await self.repo.get_exit_by_id(exit_uuid)
            return ExitResponse.model_validate(full_exit)

        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("complete_exit: db error", exc_info=exc)
            raise DatabaseException() from exc


async def get_exit_service(
    session: AsyncSession = Depends(get_db_session),
) -> ExitService:
    return ExitService(
        session=session,
        repo=ExitRepository(session),
        auth_repo=AuthRepository(session),
        employee_repo=EmployeeRepository(session),
    )
