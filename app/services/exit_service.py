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
from app.core.redis_client import redis_client
from app.core.exit_state_machine import (
    ExitStatus,
    validate_transition,
    is_terminal,
    ACTIVE_STATUSES,
)
from app.db.database import get_db_session
from app.models.asset import Asset
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
    ExitInitiationRequest,
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
from sqlalchemy import select

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

    def _validate_transition(self, current_status: str, new_status: str) -> None:
        """Validate status transition using centralized state machine."""
        result = validate_transition(current_status, new_status)
        if not result.allowed:
            raise AppException(message=result.reason or f"Invalid status transition from {current_status} to {new_status}", status_code=status.HTTP_400_BAD_REQUEST)

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
        """Employee-initiated resignation."""
        return await self._initiate_exit(
            employee_id=None,  # Will be derived from user_id
            user_id=user_id,
            payload=payload,
            is_hr_initiated=False,
            actor_user_id=user_id,
            actor_role="employee",
        )

    async def hr_initiate_exit(self, payload: ExitInitiationRequest, actor_user_id: uuid.UUID, actor_role: str) -> ExitResponse:
        """HR/Admin-initiated exit (termination, retirement, contract end, etc.)."""
        if actor_role not in {"super_admin", "hr_admin"}:
            raise AppException(message="Only HR/Admin can initiate exits on behalf of employees.", status_code=status.HTTP_403_FORBIDDEN)
        
        if not payload.employee_id:
            raise AppException(message="employee_id is required for HR-initiated exits.", status_code=status.HTTP_400_BAD_REQUEST)
        
        # Validate the target employee exists and belongs to same tenant
        target_employee = await self.employee_repo.get_by_id(payload.employee_id)
        if not target_employee:
            raise AppException(message="Target employee not found.", status_code=status.HTTP_404_NOT_FOUND)
        
        actor_employee = await self.employee_repo.get_by_user_id(actor_user_id)
        if not actor_employee:
            raise AppException(message="Actor employee profile not found.", status_code=status.HTTP_404_NOT_FOUND)
        
        if actor_role != "super_admin" and target_employee.company_id != actor_employee.company_id:
            raise AppException(message="Cannot initiate exit for employee in different company.", status_code=status.HTTP_403_FORBIDDEN)
        
        # Check for existing active exit
        existing = await self.repo.get_active_exit_by_employee_id(payload.employee_id)
        if existing:
            raise ConflictException(message="Employee already has an active exit request.")
        
        return await self._initiate_exit(
            employee_id=payload.employee_id,
            user_id=target_employee.user_id,
            payload=payload,
            is_hr_initiated=True,
            actor_user_id=actor_user_id,
            actor_role=actor_role,
        )

    async def _initiate_exit(
        self,
        employee_id: uuid.UUID | None,
        user_id: uuid.UUID | None,
        payload: ExitInitiationRequest,
        is_hr_initiated: bool,
        actor_user_id: uuid.UUID,
        actor_role: str,
    ) -> ExitResponse:
        logger.info("_initiate_exit | hr_initiated=%s | actor=%s | exit_type=%s", is_hr_initiated, actor_user_id, payload.exit_type)
        try:
            # Determine employee
            if employee_id:
                employee = await self.employee_repo.get_by_id(employee_id)
            else:
                employee = await self.employee_repo.get_by_user_id(user_id) if user_id else None
            
            if not employee:
                raise AppException(message="Employee profile not found.", status_code=status.HTTP_404_NOT_FOUND)

            # For HR-initiated exits, validate mandatory fields
            if is_hr_initiated:
                if payload.exit_type in {"termination", "layoff", "probation_failure"} and not payload.reason:
                    raise AppException(message=f"Reason is mandatory for {payload.exit_type}.", status_code=status.HTTP_400_BAD_REQUEST)
                if payload.exit_type == "retirement" and not payload.effective_date:
                    raise AppException(message="Effective date is mandatory for retirement.", status_code=status.HTTP_400_BAD_REQUEST)
                if payload.exit_type == "contract_end" and not payload.effective_date:
                    raise AppException(message="Effective date is mandatory for contract end.", status_code=status.HTTP_400_BAD_REQUEST)
                
                # HR-initiated exits may not have personal_email/phone - use employee's record
                personal_email = payload.personal_email or employee.personal_email
                personal_phone = payload.personal_phone or employee.phone
            else:
                # Employee resignation - personal_email/phone are required (validated by schema)
                personal_email = payload.personal_email
                personal_phone = payload.personal_phone

            # Check for existing active resignation request (non-terminal)
            existing = await self.repo.get_active_exit_by_employee_id(employee.id)
            if existing:
                raise ConflictException(message="Employee already has an active exit request pending or in progress.")

            # Determine notice period
            notice_days = payload.notice_period_days_required or getattr(employee, "notice_period_days", 30) or 30
            
            # For certain HR-initiated types, notice may be waived or different
            if is_hr_initiated and payload.exit_type in {"termination", "layoff", "probation_failure", "death"}:
                # These may have immediate effect or different notice rules
                if payload.notice_waived:
                    notice_days = 0
            elif payload.exit_type == "retirement":
                # Retirement typically follows standard notice
                pass
            elif payload.exit_type == "contract_end":
                # Contract end follows contract terms
                pass

            # Determine initial status based on exit type and initiation
            if is_hr_initiated:
                if payload.exit_type in {"termination", "layoff", "probation_failure", "death"}:
                    # HR-initiated involuntary exits go directly to HR_APPROVED (HR is the initiator)
                    initial_status = ExitStatus.HR_APPROVED.value
                else:
                    # Retirement, contract_end, mutual_separation - may need manager acknowledgment
                    initial_status = ExitStatus.PENDING_MANAGER_APPROVAL.value
            else:
                # Employee resignation - starts pending manager approval
                initial_status = ExitStatus.PENDING_MANAGER_APPROVAL.value

            exit_kwargs = {
                "employee_id": employee.id,
                "company_id": employee.company_id,
                "last_working_date": payload.last_working_date,
                "reason": payload.reason,
                "comments": payload.comments,
                "personal_email": personal_email,
                "personal_phone": personal_phone,
                "notice_period_days_required": notice_days,
                "notice_waived": payload.notice_waived,
                "notice_buyout": payload.notice_buyout,
                "status": initial_status,
                "exit_type": payload.exit_type,
                "effective_date": payload.effective_date,
                "initiated_by": actor_user_id if is_hr_initiated else None,
                "initiated_by_role": actor_role if is_hr_initiated else None,
            }

            exit_obj = await self.repo.create_exit(**exit_kwargs)

            # Seed legacy clearance summary (for backward compatibility)
            await self.repo.upsert_clearance(exit_obj.id, {
                "it_clearance": False,
                "hr_clearance": is_hr_initiated,  # HR clearance auto-granted for HR-initiated
                "finance_clearance": False,
                "admin_clearance": False,
                "manager_clearance": False,
                "security_clearance": False,
            })

            # Initialize auditable departmental clearances
            await self.repo.initialize_departmental_clearances(exit_obj.id)
            
            # For HR-initiated, auto-approve HR clearance
            if is_hr_initiated:
                await self.repo.upsert_departmental_clearance(exit_obj.id, "HR", {
                    "status": "APPROVED",
                    "approver_id": actor_user_id,
                    "approver_role": actor_role,
                    "actioned_at": datetime.now(timezone.utc),
                    "comments": f"Auto-approved by HR initiator ({actor_role})",
                })
                # Also update legacy summary
                await self.repo.upsert_clearance(exit_obj.id, {"hr_clearance": True})

            await self.repo.upsert_kt(exit_obj.id, {
                "projects_handed_over": "Pending Handover Description",
                "is_completed": False,
            })

            # Query actual assigned assets from Asset Management
            assigned_assets_res = await self.session.execute(
                select(Asset).where(
                    Asset.employee_id == employee.id,
                    Asset.status == "assigned",
                    Asset.is_deleted == False
                )
            )
            assigned_assets = assigned_assets_res.scalars().all()

            # Create asset return entries from actual assignments
            for asset in assigned_assets:
                asset_name = f"{asset.name} ({asset.tag})"
                if asset.category:
                    asset_name += f" - {asset.category.title()}"
                await self.repo.upsert_asset_return(exit_obj.id, asset_name, {"return_status": "PENDING"})

            # If no assets assigned, do NOT create a placeholder - checklist stays empty
            # Frontend should handle empty state appropriately

            await self.session.commit()

            full_exit = await self.repo.get_exit_by_id(exit_obj.id)
            return ExitResponse.model_validate(full_exit)

        except (AppException, ConflictException):
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("_initiate_exit: db error", exc_info=exc)
            raise DatabaseException() from exc
        logger.info("submit_resignation | user_id=%s | last_date=%s", user_id, payload.last_working_date)
        try:
            employee = await self.employee_repo.get_by_user_id(user_id)
            if not employee:
                raise AppException(message="Employee profile not found.", status_code=status.HTTP_404_NOT_FOUND)

            # Check for existing active resignation request (non-terminal)
            existing = await self.repo.get_active_exit_by_employee_id(employee.id)
            if existing:
                raise ConflictException(message="You already have an active resignation request pending or in progress.")

            # Also check for rejected exits that could be re-applied
            rejected = await self.repo.get_exit_by_employee_id_raw(employee.id)
            if rejected and rejected.status in {"MANAGER_REJECTED", "HR_REJECTED"}:
                # Allow re-application by creating new exit (handled by the check above since rejected is not "active")
                pass

            exit_kwargs = {
                "employee_id": employee.id,
                "last_working_date": payload.last_working_date,
                "reason": payload.reason,
                "comments": payload.comments,
                "personal_email": payload.personal_email,
                "personal_phone": payload.personal_phone,
                "status": ExitStatus.SUBMITTED.value,
            }

            exit_obj = await self.repo.create_exit(**exit_kwargs)

            # Seed legacy clearance summary (for backward compatibility)
            await self.repo.upsert_clearance(exit_obj.id, {
                "it_clearance": False,
                "hr_clearance": False,
                "finance_clearance": False,
                "admin_clearance": False,
                "manager_clearance": False,
                "security_clearance": False,
            })

            # Initialize auditable departmental clearances
            await self.repo.initialize_departmental_clearances(exit_obj.id)

            await self.repo.upsert_kt(exit_obj.id, {
                "projects_handed_over": "Pending Handover Description",
                "is_completed": False,
            })

            # Query actual assigned assets from Asset Management
            assigned_assets_res = await self.session.execute(
                select(Asset).where(
                    Asset.employee_id == employee.id,
                    Asset.status == "assigned",
                    Asset.is_deleted == False
                )
            )
            assigned_assets = assigned_assets_res.scalars().all()

            # Create asset return entries from actual assignments
            for asset in assigned_assets:
                asset_name = f"{asset.name} ({asset.tag})"
                if asset.category:
                    asset_name += f" - {asset.category.title()}"
                await self.repo.upsert_asset_return(exit_obj.id, asset_name, {"return_status": "PENDING"})

            # If no assets assigned, do NOT create a placeholder - checklist stays empty
            # Frontend should handle empty state appropriately

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

            # Validate transition using state machine
            self._validate_transition(exit_obj.status, ExitStatus.CANCELLED.value)

            await self.repo.update_exit_status(exit_obj.id, ExitStatus.CANCELLED.value)
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

    async def manager_approve(self, exit_uuid: uuid.UUID, remarks: str | None, actor_user_id: uuid.UUID) -> ExitResponse:
        logger.info("manager_approve | exit_id=%s | actor=%s", exit_uuid, actor_user_id)
        try:
            exit_obj = await self.repo.get_exit_by_id(exit_uuid)
            if not exit_obj:
                raise AppException(message="Exit request not found.", status_code=status.HTTP_404_NOT_FOUND)

            # Validate manager authorization: actor must be the employee's reporting manager
            manager_employee = await self.employee_repo.get_by_user_id(actor_user_id)
            if not manager_employee:
                raise AppException(message="Manager profile not found.", status_code=status.HTTP_403_FORBIDDEN)
            
            exit_employee = await self.employee_repo.get_by_id(exit_obj.employee_id)
            if not exit_employee:
                raise AppException(message="Exit employee not found.", status_code=status.HTTP_404_NOT_FOUND)
            
            # Check direct reporting relationship
            if exit_employee.manager_id != manager_employee.id:
                # Check for delegated approval (if implemented via role metadata or separate delegation table)
                is_delegated = False
                if manager_employee.role_metadata and manager_employee.role_metadata.get("delegated_approvals"):
                    delegated_ids = manager_employee.role_metadata.get("delegated_approvals", [])
                    if str(exit_employee.id) in delegated_ids:
                        is_delegated = True
                if not is_delegated:
                    raise AppException(message="Access denied: not your direct report and no delegation found.", status_code=status.HTTP_403_FORBIDDEN)

            # Validate transition using state machine (allow both granular and simplified flows)
            # Simplified: PENDING_MANAGER_APPROVAL/SUBMITTED -> PENDING_HR_APPROVAL
            # Granular: PENDING_MANAGER_APPROVAL -> MANAGER_APPROVED -> PENDING_HR_APPROVAL
            if exit_obj.status in {ExitStatus.SUBMITTED.value, ExitStatus.PENDING_MANAGER_APPROVAL.value}:
                target_status = ExitStatus.PENDING_HR_APPROVAL.value
            elif exit_obj.status == ExitStatus.MANAGER_APPROVED.value:
                target_status = ExitStatus.PENDING_HR_APPROVAL.value
            else:
                self._validate_transition(exit_obj.status, ExitStatus.PENDING_HR_APPROVAL.value)
                target_status = ExitStatus.PENDING_HR_APPROVAL.value

            await self.repo.update_exit_status(exit_uuid, target_status, manager_remarks=remarks)
            
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

    async def manager_reject(self, exit_uuid: uuid.UUID, remarks: str | None, actor_user_id: uuid.UUID) -> ExitResponse:
        logger.info("manager_reject | exit_id=%s | actor=%s", exit_uuid, actor_user_id)
        try:
            exit_obj = await self.repo.get_exit_by_id(exit_uuid)
            if not exit_obj:
                raise AppException(message="Exit request not found.", status_code=status.HTTP_404_NOT_FOUND)

            # Validate manager authorization: actor must be the employee's reporting manager
            manager_employee = await self.employee_repo.get_by_user_id(actor_user_id)
            if not manager_employee:
                raise AppException(message="Manager profile not found.", status_code=status.HTTP_403_FORBIDDEN)
            
            exit_employee = await self.employee_repo.get_by_id(exit_obj.employee_id)
            if not exit_employee:
                raise AppException(message="Exit employee not found.", status_code=status.HTTP_404_NOT_FOUND)
            
            # Check direct reporting relationship
            if exit_employee.manager_id != manager_employee.id:
                is_delegated = False
                if manager_employee.role_metadata and manager_employee.role_metadata.get("delegated_approvals"):
                    delegated_ids = manager_employee.role_metadata.get("delegated_approvals", [])
                    if str(exit_employee.id) in delegated_ids:
                        is_delegated = True
                if not is_delegated:
                    raise AppException(message="Access denied: not your direct report and no delegation found.", status_code=status.HTTP_403_FORBIDDEN)

            # Validate transition using state machine
            self._validate_transition(exit_obj.status, ExitStatus.MANAGER_REJECTED.value)

            await self.repo.update_exit_status(exit_uuid, ExitStatus.MANAGER_REJECTED.value, manager_remarks=remarks)
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

            # Validate transition using state machine
            self._validate_transition(exit_obj.status, ExitStatus.HR_APPROVED.value)

            await self.repo.update_exit_status(exit_uuid, ExitStatus.HR_APPROVED.value, hr_remarks=remarks)
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

            # Validate transition using state machine (HR rejection goes to HR_REJECTED)
            self._validate_transition(exit_obj.status, ExitStatus.HR_REJECTED.value)

            await self.repo.update_exit_status(exit_uuid, ExitStatus.HR_REJECTED.value, hr_remarks=remarks)
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

            # Validate transition using state machine
            self._validate_transition(exit_obj.status, ExitStatus.NOTICE_PERIOD.value)

            await self.repo.update_exit_status(exit_uuid, ExitStatus.NOTICE_PERIOD.value)
            
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

    async def return_asset(self, exit_uuid: uuid.UUID, payload: AssetReturnCreate, actor_user_id: uuid.UUID) -> AssetReturnResponse:
        """Update asset return status and sync with canonical Asset Inventory.
        
        When an asset is marked RETURNED, this also updates the Asset record
        and creates an AssetAssignmentHistory entry for audit trail.
        """
        try:
            exit_obj = await self.repo.get_exit_by_id(exit_uuid)
            if not exit_obj:
                raise AppException(message="Exit request not found.", status_code=status.HTTP_404_NOT_FOUND)

            # Find the asset return record
            asset_return = await self.repo.get_asset_return_by_name(exit_uuid, payload.asset_name)
            if not asset_return:
                raise AppException(message="Asset return record not found.", status_code=status.HTTP_404_NOT_FOUND)

            data = payload.model_dump(exclude={"asset_name"})
            if payload.return_status == "RETURNED" and not payload.return_date:
                data["return_date"] = date.today()

            # Update the exit asset return record
            for k, v in data.items():
                setattr(asset_return, k, v)

            # If marking as RETURNED, also update canonical Asset Inventory
            if payload.return_status == "RETURNED":
                # Find the actual asset by matching name/tag
                # The asset_name format is "{name} ({tag}) - {category}"
                asset_name_parts = payload.asset_name.split(" (")
                if len(asset_name_parts) >= 2:
                    asset_tag = asset_name_parts[1].split(")")[0]
                    asset_res = await self.session.execute(
                        select(Asset).where(
                            Asset.tag == asset_tag,
                            Asset.employee_id == exit_obj.employee_id,
                            Asset.status == "assigned",
                            Asset.is_deleted == False
                        )
                    )
                    asset = asset_res.scalars().first()
                    
                    if asset:
                        # Update asset status to available
                        asset.status = "available"
                        asset.employee_id = None
                        asset.assigned_at = None
                        
                        # Create assignment history entry
                        from app.models.asset.assignment import AssetAssignmentHistory
                        history = AssetAssignmentHistory(
                            asset_id=asset.id,
                            employee_name=f"{exit_obj.employee.first_name} {exit_obj.employee.last_name}",
                            department=exit_obj.employee.department,
                            assign_date=asset.assigned_at.date() if asset.assigned_at else date.today(),
                            actual_return_date=date.today(),
                            notes=f"Returned during exit process by user {actor_user_id}"
                        )
                        self.session.add(history)
                        
                        # Add to asset timeline
                        if asset.timeline is None:
                            asset.timeline = []
                        asset.timeline.append({
                            "event": "returned_on_exit",
                            "date": date.today().isoformat(),
                            "actor_id": str(actor_user_id),
                            "exit_id": str(exit_uuid),
                            "notes": "Asset returned as part of employee exit process"
                        })
                    else:
                        logger.warning(f"Asset with tag {asset_tag} not found for exit {exit_uuid}")

            await self.session.commit()
            return AssetReturnResponse.model_validate(asset_return)
        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("return_asset: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def update_clearance(self, exit_uuid: uuid.UUID, payload: ClearanceUpdate, actor_user_id: uuid.UUID, actor_role: str) -> ClearanceResponse:
        """Update departmental clearance with auditable approval records.
        
        Each department approval creates/updates a DepartmentalClearance record
        with approver identity, timestamp, comments, and evidence reference.
        Also updates legacy ClearanceRequest summary fields for backward compatibility.
        """
        try:
            exit_obj = await self.repo.get_exit_by_id(exit_uuid)
            if not exit_obj:
                raise AppException(message="Exit request not found.", status_code=status.HTTP_404_NOT_FOUND)

            # Validate actor is HR/Admin (only they can approve clearances)
            if actor_role not in {"super_admin", "hr_admin"}:
                raise AppException(message="Only HR/Admin can update departmental clearances.", status_code=status.HTTP_403_FORBIDDEN)

            data = {k: v for k, v in payload.model_dump().items() if v is not None}
            
            # Update legacy summary fields
            legacy_data = {}
            dept_mapping = {
                "it_clearance": "IT",
                "hr_clearance": "HR",
                "finance_clearance": "FINANCE",
                "admin_clearance": "ADMIN",
                "manager_clearance": "MANAGER",
                "security_clearance": "SECURITY",
            }
            
            for field, value in data.items():
                if field in dept_mapping and value is not None:
                    dept = dept_mapping[field]
                    status_val = "APPROVED" if value else "PENDING"
                    
                    # Create/update auditable departmental clearance
                    await self.repo.upsert_departmental_clearance(exit_uuid, dept, {
                        "status": status_val,
                        "approver_id": actor_user_id,
                        "approver_role": actor_role,
                        "actioned_at": datetime.now(timezone.utc),
                        "comments": f"{'Approved' if value else 'Pending'} by {actor_role}",
                    })
                    legacy_data[field] = value
            
            cl = await self.repo.upsert_clearance(exit_uuid, legacy_data)
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

    async def get_fnf_preview(self, exit_uuid: uuid.UUID) -> dict:
        try:
            exit_obj = await self.repo.get_exit_by_id(exit_uuid)
            if not exit_obj:
                raise AppException(message="Exit request not found.", status_code=status.HTTP_404_NOT_FOUND)

            from app.services.fnf_calculation_service import FnfCalculationService
            fnf_calc = FnfCalculationService(self.session)
            return await fnf_calc.calculate_fnf_preview(exit_uuid)
        except AppException:
            raise
        except Exception as exc:
            logger.exception("get_fnf_preview error", exc_info=exc)
            raise AppException(message=f"Failed to calculate FNF preview: {str(exc)}", status_code=status.HTTP_400_BAD_REQUEST)

    async def confirm_fnf_payment(
        self,
        exit_uuid: uuid.UUID,
        payment_reference: str,
        payment_amount: Decimal,
        payment_date: date,
        actor_user_id: uuid.UUID,
        actor_role: str,
        bank_utr: str | None = None,
        remarks: str | None = None,
    ) -> FnfResponse:
        """Confirm FNF payment with full audit trail.
        
        This is the ONLY way to set payment_status=PAID.
        Requires HR/Admin role, payment reference, amount validation, and creates immutable audit log.
        """
        try:
            exit_obj = await self.repo.get_exit_by_id(exit_uuid)
            if not exit_obj:
                raise AppException(message="Exit request not found.", status_code=status.HTTP_404_NOT_FOUND)

            # Authorization: only HR/Admin can confirm payments
            if actor_role not in {"super_admin", "hr_admin"}:
                raise AppException(message="Only HR/Admin can confirm FNF payments.", status_code=status.HTTP_403_FORBIDDEN)

            fnf = await self.repo.get_fnf_by_exit_id(exit_uuid)
            if not fnf:
                raise AppException(message="FNF settlement not found.", status_code=status.HTTP_404_NOT_FOUND)

            # Validate FNF is in a state that can be paid
            if fnf.payment_status == "PAID":
                raise AppException(message="Payment already confirmed for this settlement.", status_code=status.HTTP_400_BAD_REQUEST)

            if fnf.status not in {"FINALIZED", "DRAFT", "SETTLED"}:
                raise AppException(message=f"Cannot confirm payment for FNF in status '{fnf.status}'.", status_code=status.HTTP_400_BAD_REQUEST)

            # Validate payment amount matches net payable (within 1 rupee tolerance)
            expected_amount = float(fnf.net_payable_amount)
            actual_amount = float(payment_amount)
            if abs(expected_amount - actual_amount) > 1.0:
                raise AppException(
                    message=f"Payment amount mismatch. Expected: {expected_amount}, Provided: {actual_amount}",
                    status_code=status.HTTP_400_BAD_REQUEST
                )

            # Check for duplicate payment reference (idempotency)
            from app.models.exit import FnfSettlement
            from sqlalchemy import select
            existing_payment = await self.session.execute(
                select(FnfSettlement).where(
                    FnfSettlement.payment_reference == payment_reference
                )
            )
            if existing_payment.scalars().first():
                raise AppException(message="Payment reference already used.", status_code=status.HTTP_409_CONFLICT)

            # Update payment status with audit trail
            fnf.payment_status = "PAID"
            fnf.payment_date = payment_date
            fnf.payment_reference = payment_reference
            fnf.payment_utr = bank_utr
            fnf.payment_confirmed_by = actor_user_id
            fnf.payment_confirmed_at = datetime.now(timezone.utc)
            fnf.payment_remarks = remarks

            # Also update legacy summary fields
            fnf.status = "SETTLED"
            exit_obj.fnf_status = "SETTLED"

            # Create audit log entry
            from app.services.payroll.audit_service import PayrollAuditService
            await PayrollAuditService.log_event(
                session=self.session,
                entity_type="FnfSettlement",
                entity_id=fnf.id,
                action="PAYMENT_CONFIRMED",
                company_id=exit_obj.company_id,
                actor_id=actor_user_id,
                actor_role=actor_role,
                before_status=fnf.status,
                after_status="SETTLED",
                reason=f"Payment confirmed: {payment_reference}, Amount: {payment_amount}",
                extra_data={
                    "payment_reference": payment_reference,
                    "payment_amount": str(payment_amount),
                    "payment_date": payment_date.isoformat(),
                    "bank_utr": bank_utr,
                }
            )

            await self.session.commit()
            return FnfResponse.model_validate(fnf)

        except AppException:
            await self.session.rollback()
            raise
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("confirm_fnf_payment: db error", exc_info=exc)
            raise DatabaseException() from exc

    async def reconcile_fnf_ledgers(self, exit_uuid: uuid.UUID, prefer_legacy: bool = True, actor_user_id: uuid.UUID | None = None) -> dict:
        """Reconcile legacy FnfSettlement with v2 FullAndFinalSettlement.
        
        Creates missing record from existing one, or updates both to match.
        Uses prefer_legacy to decide which source is authoritative for conflicts.
        
        Returns reconciliation result with actions taken.
        """
        try:
            exit_obj = await self.repo.get_exit_by_id(exit_uuid)
            if not exit_obj:
                raise AppException(message="Exit request not found.", status_code=status.HTTP_404_NOT_FOUND)

            legacy_fnf = await self.repo.get_fnf_by_exit_id(exit_uuid)
            
            from app.models.payroll_models import FullAndFinalSettlement
            from sqlalchemy import select
            v2_fnf_res = await self.session.execute(
                select(FullAndFinalSettlement).where(
                    FullAndFinalSettlement.exit_id == exit_uuid
                )
            )
            v2_fnf = v2_fnf_res.scalars().first()

            actions = []

            if legacy_fnf and not v2_fnf:
                # Create v2 from legacy
                from app.services.payroll.full_and_final_service import FullAndFinalService
                from app.schemas.payroll_v2.full_and_final import ExitDetails
                
                exit_details = ExitDetails(
                    resignationDate=exit_obj.created_at.date(),
                    lastWorkingDate=exit_obj.last_working_date,
                    exitType="resignation",
                    reason=exit_obj.reason,
                    noticePeriodDaysRequired=exit_obj.notice_period_days_required or 30,
                    noticePeriodDaysServed=exit_obj.notice_period_days_served or 0,
                    shortfallDays=exit_obj.notice_shortfall_days or 0,
                )
                
                v2_fnf = await FullAndFinalService.create_settlement(
                    session=self.session,
                    employee_id=exit_obj.employee_id,
                    exit_details=exit_details,
                    remarks="Auto-created from legacy FNF during reconciliation",
                    company_id=exit_obj.company_id,
                    user_id=actor_user_id or exit_obj.employee.user_id,
                    user_role="hr_admin",
                )
                
                # Update v2 with legacy financial data
                v2_fnf.net_payable_paise = int(legacy_fnf.net_payable_amount * 100)
                v2_fnf.settlement_breakup = legacy_fnf.settlement_breakup
                v2_fnf.status = legacy_fnf.status
                if legacy_fnf.payment_status == "PAID":
                    v2_fnf.status = "SETTLED"
                if legacy_fnf.statement_path:
                    v2_fnf.statement_path = legacy_fnf.statement_path
                if legacy_fnf.generated_letters_json:
                    v2_fnf.generated_letters_json = legacy_fnf.generated_letters_json
                
                actions.append("created_v2_from_legacy")

            elif v2_fnf and not legacy_fnf:
                # Create legacy from v2
                legacy_fnf = FnfSettlement(exit_id=exit_uuid)
                self.session.add(legacy_fnf)
                
                legacy_fnf.net_payable_amount = Decimal(str(v2_fnf.net_payable_paise / 100.0))
                legacy_fnf.settlement_breakup = v2_fnf.settlement_breakup
                legacy_fnf.status = v2_fnf.status
                legacy_fnf.payment_status = "PAID" if v2_fnf.status == "SETTLED" else "PENDING"
                if v2_fnf.statement_path:
                    legacy_fnf.statement_path = v2_fnf.statement_path
                if v2_fnf.generated_letters_json:
                    legacy_fnf.generated_letters_json = v2_fnf.generated_letters_json
                
                actions.append("created_legacy_from_v2")

            elif legacy_fnf and v2_fnf:
                # Both exist - reconcile differences
                if prefer_legacy:
                    # Update v2 from legacy
                    v2_fnf.net_payable_paise = int(legacy_fnf.net_payable_amount * 100)
                    v2_fnf.settlement_breakup = legacy_fnf.settlement_breakup
                    v2_fnf.status = legacy_fnf.status
                    if legacy_fnf.payment_status == "PAID":
                        v2_fnf.status = "SETTLED"
                    if legacy_fnf.statement_path:
                        v2_fnf.statement_path = legacy_fnf.statement_path
                    if legacy_fnf.generated_letters_json:
                        v2_fnf.generated_letters_json = legacy_fnf.generated_letters_json
                    actions.append("updated_v2_from_legacy")
                else:
                    # Update legacy from v2
                    legacy_fnf.net_payable_amount = Decimal(str(v2_fnf.net_payable_paise / 100.0))
                    legacy_fnf.settlement_breakup = v2_fnf.settlement_breakup
                    legacy_fnf.status = v2_fnf.status
                    legacy_fnf.payment_status = "PAID" if v2_fnf.status == "SETTLED" else "PENDING"
                    if v2_fnf.statement_path:
                        legacy_fnf.statement_path = v2_fnf.statement_path
                    if v2_fnf.generated_letters_json:
                        legacy_fnf.generated_letters_json = v2_fnf.generated_letters_json
                    actions.append("updated_legacy_from_v2")

            await self.session.commit()
            
            return {
                "exit_id": str(exit_uuid),
                "actions": actions,
                "legacy_id": str(legacy_fnf.id) if legacy_fnf else None,
                "v2_id": str(v2_fnf.id) if v2_fnf else None,
                "reconciled": True,
            }
        except AppException:
            await self.session.rollback()
            raise
        except Exception as exc:
            await self.session.rollback()
            logger.exception("reconcile_fnf_ledgers error", exc_info=exc)
            raise AppException(message=f"Failed to reconcile FNF ledgers: {str(exc)}", status_code=status.HTTP_400_BAD_REQUEST)

    async def submit_fnf(self, exit_uuid: uuid.UUID, payload: FnfCreate) -> FnfResponse:
        try:
            exit_obj = await self.repo.get_exit_by_id(exit_uuid)
            if not exit_obj:
                raise AppException(message="Exit request not found.", status_code=status.HTTP_404_NOT_FOUND)

            data = payload.model_dump()
            # payment_status is always PENDING initially - cannot be set via this endpoint
            data["payment_status"] = "PENDING"
            data["payment_date"] = None
            
            # If all amounts are zero/empty, auto-calculate from FnfCalculationService
            total_provided = sum(Decimal(str(v)) for k, v in data.items() if isinstance(v, (int, float, Decimal)) and k not in {"net_payable_amount", "payment_status"})
            if total_provided == Decimal("0.00"):
                from app.services.fnf_calculation_service import FnfCalculationService
                preview = await FnfCalculationService(self.session).calculate_fnf_preview(exit_uuid)
                data.update({
                    "last_salary": Decimal(str(preview["last_salary"])),
                    "pending_salary": Decimal(str(preview["pending_salary"])),
                    "leave_encashment": Decimal(str(preview["leave_encashment"])),
                    "gratuity": Decimal(str(preview["gratuity"])),
                    "bonus": Decimal(str(preview["bonus"])),
                    "incentives": Decimal(str(preview["incentives"])),
                    "notice_recovery": Decimal(str(preview["notice_recovery"])),
                    "loan_recovery": Decimal(str(preview["loan_recovery"])),
                    "settlement_breakup": preview,
                })
                exit_obj.notice_period_days_required = preview["required_notice_days"]
                exit_obj.notice_period_days_served = preview["actual_notice_days"]
                exit_obj.notice_shortfall_days = preview["notice_shortfall_days"]
                exit_obj.notice_buyout = preview["notice_buyout"]
                exit_obj.notice_waived = preview["notice_waived"]

            fnf = await self.repo.upsert_fnf(exit_uuid, data)
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

    async def generate_exit_documents(
        self, exit_uuid: uuid.UUID, actor_id: uuid.UUID | None = None,
    ) -> list[ExitDocumentResponse]:
        """Return real PDF exit letters, unlocked only by a SETTLED FnF."""
        logger.info("generate_exit_documents | exit_id=%s", exit_uuid)
        try:
            exit_obj = await self.repo.get_exit_by_id(exit_uuid)
            if not exit_obj:
                raise AppException(message="Exit request not found.", status_code=status.HTTP_404_NOT_FOUND)
            if exit_obj.status != "SETTLED":
                raise AppException(
                    message="Relieving and experience letters are locked until FnF is SETTLED.",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
            fnf = await self.repo.get_fnf_by_exit_id(exit_uuid)
            if fnf is not None:
                from app.services.fnf_workflow_service import FnFWorkflowService
                await FnFWorkflowService(self.session).settle_exit_fnf(
                    exit_uuid, actor_id=actor_id or exit_obj.employee.user_id,
                )
            documents = await self.repo.get_documents_by_exit_id(exit_uuid)
            if not documents:
                raise AppException(message="Settled exit documents were not found.", status_code=status.HTTP_404_NOT_FOUND)
            return [ExitDocumentResponse.model_validate(document) for document in documents]
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

            # Check exit clearance asset returns
            assets = await self.repo.get_asset_returns_by_exit_id(exit_uuid)
            if any(a.return_status == "PENDING" for a in assets):
                raise AppException(message="All assigned assets must be returned first.", status_code=status.HTTP_400_BAD_REQUEST)

            # Also verify actual asset management assignments are returned
            assigned_assets = await self.session.execute(
                select(Asset).where(
                    Asset.employee_id == exit_obj.employee_id,
                    Asset.status == "assigned",
                    Asset.is_deleted == False
                )
            )
            still_assigned = assigned_assets.scalars().all()
            if still_assigned:
                asset_names = ", ".join([f"{a.name} ({a.tag})" for a in still_assigned])
                raise AppException(
                    message=f"Employee still has assigned assets in Asset Management: {asset_names}. "
                            "All assets must be returned via Asset Management before exit completion.",
                    status_code=status.HTTP_400_BAD_REQUEST
                )

            cl = await self.repo.get_clearance_by_exit_id(exit_uuid)
            if not cl or cl.overall_status != "CLEARED":
                raise AppException(message="All department clearance dues must be cleared first.", status_code=status.HTTP_400_BAD_REQUEST)

            fnf = await self.repo.get_fnf_by_exit_id(exit_uuid)
            if not fnf or fnf.payment_status != "PAID":
                raise AppException(message="Full & Final settlement payment must be paid first.", status_code=status.HTTP_400_BAD_REQUEST)

            # Validate transition using state machine (from SETTLED to COMPLETED)
            self._validate_transition(exit_obj.status, ExitStatus.COMPLETED.value)

            # 1. Update exit status to COMPLETED
            await self.repo.update_exit_status(exit_uuid, ExitStatus.COMPLETED.value)

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
                    .values(is_active=False)
                )
                await self.session.execute(
                    sa_update(Manager)
                    .where(Manager.user_id == exit_obj.employee.user_id)
                    .values(status="ARCHIVED")
                )
                await self.auth_repo.revoke_all_user_refresh_tokens(exit_obj.employee.user_id)
                await redis_client.revoke_user_tokens(exit_obj.employee.user_id)
                # Invalidate auth active cache
                if exit_obj.employee.company_id:
                    from app.middleware.auth import invalidate_auth_active_cache
                    await invalidate_auth_active_cache(exit_obj.employee.user_id, exit_obj.employee.company_id)

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
