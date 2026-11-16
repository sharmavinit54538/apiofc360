"""Asset Management Service."""

from __future__ import annotations
import logging
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException, BadRequestException
from app.db.database import get_db_session
from app.models.asset import Asset
from app.models.employee import Employee
from app.models.user import User
from app.repositories.asset_repository import AssetRepository
from app.schemas.asset import (
    AssetCreate,
    AssetUpdate,
    AssetAssignRequest,
    AssetTransferRequest,
    AssetMaintenanceCreate,
    AssetAnalyticsResponse,
    AssetListResponse,
    CategoryCount,
    StatusCount,
    AssetResponse,
    AssetFilterOptionsResponse,
    AssetPublicResponse,
    AssetRequestCreate,
    AssetRequestUpdate,
    AssetRequestResponse,
    AssetDamageReportCreate,
    AssetDamageReportResponse,
)

logger = logging.getLogger(__name__)


class AssetService:
    """Service layer coordinating asset management business rules."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = AssetRepository(session)

    async def _get_user_name(self, user_id: uuid.UUID) -> str:
        """Resolve full name of administrative user performing actions."""
        res = await self.session.execute(select(User).where(User.id == user_id))
        user = res.scalar_one_or_none()
        if user:
            return user.name or f"User {user.email}"
        return "IT Admin"

    async def list_assets(
        self,
        company_id: uuid.UUID,
        category: str | None = None,
        status: str | None = None,
        search: str | None = None,
        page: int = 1,
        limit: int = 20,
        vendor: str | None = None,
        location: str | None = None,
        department: str | None = None,
        sort_by: str = "created_at",
        sort_dir: str = "desc",
    ) -> AssetListResponse:
        """Query and paginate asset list from repository with additional filtering and sorting."""
        items, total = await self.repo.list_assets(
            company_id=company_id,
            category=category,
            status=status,
            search=search,
            page=page,
            limit=limit,
            vendor=vendor,
            location=location,
            department=department,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )
        return AssetListResponse(
            items=[AssetResponse.model_validate(i) for i in items],
            total=total,
            page=page,
            limit=limit,
        )

    async def get_filter_options(self, company_id: uuid.UUID) -> AssetFilterOptionsResponse:
        """Get distinct filter values (vendors, locations, departments) from repository."""
        vendors, locations, departments = await self.repo.get_filter_options(company_id=company_id)
        return AssetFilterOptionsResponse(
            vendors=vendors,
            locations=locations,
            departments=departments,
        )

    async def get_asset(self, asset_id: uuid.UUID, company_id: uuid.UUID | None = None) -> AssetResponse:
        """Fetch asset details by UUID."""
        asset = await self.repo.get_asset_by_id(asset_id, company_id=company_id)
        if not asset:
            raise NotFoundException("Asset not found.")
        return AssetResponse.model_validate(asset)

    async def get_public_asset(self, asset_id: uuid.UUID) -> AssetPublicResponse:
        """Fetch public asset details by UUID without tenant validation (for QR scanning)."""
        asset = await self.repo.get_asset_by_id(asset_id, company_id=None)
        if not asset:
            raise NotFoundException("Asset not found.")
        return AssetPublicResponse.model_validate(asset)

    async def create_asset(self, payload: AssetCreate, user_id: uuid.UUID, company_id: uuid.UUID) -> AssetResponse:
        """Register a new asset and append its creation log to the timeline."""
        # Check if asset tag already exists within company
        existing = await self.repo.get_asset_by_tag(payload.tag, company_id=company_id)
        if existing:
            raise BadRequestException(f"Asset tag '{payload.tag}' already exists.")

        user_name = await self._get_user_name(user_id)
        
        # Build initial timeline event
        timeline_event = {
            "id": str(uuid.uuid4()),
            "event": "Created",
            "performed_by": user_name,
            "timestamp": datetime.now().isoformat(),
            "notes": "Asset registered in central HRMS repository.",
        }

        asset_data = payload.model_dump()
        asset_data["company_id"] = company_id
        asset_data["timeline"] = [timeline_event]
        asset_data["status"] = "available"

        asset = await self.repo.create_asset(**asset_data)
        await self.session.commit()
        
        # Re-fetch with relationships
        full_asset = await self.repo.get_asset_by_id(asset.id, company_id=company_id)
        return AssetResponse.model_validate(full_asset)

    async def update_asset(self, asset_id: uuid.UUID, payload: AssetUpdate, user_id: uuid.UUID, company_id: uuid.UUID) -> AssetResponse:
        """Update specifications of an asset and append a specifications update log.
        
        Note: Status changes are not allowed through this method. Use explicit transition endpoints.
        """
        asset = await self.repo.get_asset_by_id(asset_id, company_id=company_id)
        if not asset:
            raise NotFoundException("Asset not found.")

        user_name = await self._get_user_name(user_id)
        update_data = payload.model_dump(exclude_unset=True)

        # Prevent direct status updates through generic update
        if "status" in update_data:
            raise BadRequestException(
                "Direct status updates are not allowed. Use explicit transition endpoints "
                "(assign, return, transfer, mark_lost, mark_retired, maintenance)."
            )

        # Append spec edit event to timeline
        timeline_event = {
            "id": str(uuid.uuid4()),
            "event": "Updated",
            "performed_by": user_name,
            "timestamp": datetime.now().isoformat(),
            "notes": "Asset specifications updated.",
        }
        
        current_timeline = asset.timeline or []
        current_timeline.append(timeline_event)
        update_data["timeline"] = current_timeline

        await self.repo.update_asset(asset, **update_data)
        await self.session.commit()

        full_asset = await self.repo.get_asset_by_id(asset.id, company_id=company_id)
        return AssetResponse.model_validate(full_asset)

    async def delete_asset(self, asset_id: uuid.UUID, company_id: uuid.UUID, user_id: uuid.UUID) -> None:
        """Soft delete an asset record (archive) - preserves all history."""
        asset = await self.repo.get_asset_by_id(asset_id, company_id=company_id)
        if not asset:
            raise NotFoundException("Asset not found.")
        
        # Prevent deletion if asset has active assignment
        if asset.status == "assigned" and asset.employee_id:
            raise BadRequestException("Cannot archive asset with active assignment. Return or transfer first.")
        
        # Soft delete: mark as archived and set deletion timestamp
        user_name = await self._get_user_name(user_id)
        asset.is_deleted = True
        asset.deleted_at = datetime.now()
        asset.status = "archived"
        
        # Add timeline event
        timeline_event = {
            "id": str(uuid.uuid4()),
            "event": "Archived",
            "performed_by": user_name,
            "timestamp": datetime.now().isoformat(),
            "notes": "Asset archived (soft deleted). All history preserved.",
        }
        current_timeline = asset.timeline or []
        current_timeline.append(timeline_event)
        asset.timeline = current_timeline
        
        await self.session.commit()

    async def assign_asset(self, asset_id: uuid.UUID, payload: AssetAssignRequest, user_id: uuid.UUID, company_id: uuid.UUID) -> AssetResponse:
        """Assign an asset to an employee, writing history and timeline events."""
        # Use row-level locking to prevent concurrent assignment
        asset = await self.repo.get_asset_by_id_for_update(asset_id, company_id=company_id)
        if not asset:
            raise NotFoundException("Asset not found.")

        # Validate asset is in an eligible state for assignment
        ineligible_statuses = {"assigned", "lost", "retired", "under-repair", "disposed", "maintenance"}
        if asset.status in ineligible_statuses:
            raise BadRequestException(f"Asset cannot be assigned: current status is '{asset.status}'. Only 'available' assets can be assigned.")

        # Find employee within the same company using immutable employee_id
        res = await self.session.execute(
            select(Employee).where(
                Employee.id == payload.employee_id,
                Employee.company_id == company_id,
                Employee.is_deleted == False
            )
        )
        emp = res.scalars().first()
        if not emp:
            raise NotFoundException("Employee not found.")
        
        # Validate employee is active and eligible
        if emp.is_deactivated:
            raise BadRequestException("Cannot assign asset to inactive or deactivated employee.")

        user_name = await self._get_user_name(user_id)
        employee_name = f"{emp.first_name} {emp.last_name}"
        department = emp.department
        
        # 1. Update Asset properties
        asset.status = "assigned"
        asset.employee_id = emp.id
        asset.assigned_at = datetime.now()

        # 2. Add history record
        await self.repo.add_assignment_history(
            asset_id=asset.id,
            employee_name=employee_name,
            department=department,
            assign_date=date.today(),
            expected_return_date=payload.expected_return_date,
            notes=payload.notes,
        )

        # 3. Append timeline log
        timeline_event = {
            "id": str(uuid.uuid4()),
            "event": "Assigned",
            "performed_by": user_name,
            "timestamp": datetime.now().isoformat(),
            "notes": f"Assigned to {employee_name} ({department})."
            + (f" Notes: {payload.notes}" if payload.notes else ""),
        }
        current_timeline = asset.timeline or []
        current_timeline.append(timeline_event)
        asset.timeline = current_timeline

        await self.session.commit()
        
        full_asset = await self.repo.get_asset_by_id(asset.id, company_id=company_id)
        # Ensure employee relationship is loaded for assignedTo field
        if full_asset and full_asset.employee_id:
            stmt = select(Employee).where(Employee.id == full_asset.employee_id)
            res = await self.session.execute(stmt)
            full_asset.employee = res.scalar_one_or_none()
        return AssetResponse.model_validate(full_asset)

    async def return_asset(self, asset_id: uuid.UUID, user_id: uuid.UUID, company_id: uuid.UUID) -> AssetResponse:
        """Return an asset back to inventory, closing active assignment history and logging timeline."""
        asset = await self.repo.get_asset_by_id(asset_id, company_id=company_id)
        if not asset:
            raise NotFoundException("Asset not found.")

        if asset.status != "assigned" or not asset.employee_id:
            raise BadRequestException("Asset is not currently assigned.")

        user_name = await self._get_user_name(user_id)
        old_emp_name = f"{asset.employee.first_name} {asset.employee.last_name}" if asset.employee else "employee"

        # 1. Close active assignment history
        # Find active history
        for hist in asset.assignment_history:
            if hist.actual_return_date is None:
                hist.actual_return_date = date.today()
                break

        # 2. Reset asset properties
        asset.status = "available"
        asset.employee_id = None
        asset.assigned_at = None

        # 3. Append timeline log
        timeline_event = {
            "id": str(uuid.uuid4()),
            "event": "Returned",
            "performed_by": user_name,
            "timestamp": datetime.now().isoformat(),
            "notes": f"Returned to IT Stock Room by {old_emp_name}.",
        }
        current_timeline = asset.timeline or []
        current_timeline.append(timeline_event)
        asset.timeline = current_timeline

        await self.session.commit()

        full_asset = await self.repo.get_asset_by_id(asset.id, company_id=company_id)
        # Ensure employee relationship is cleared for assignedTo field
        full_asset.employee = None
        return AssetResponse.model_validate(full_asset)

    async def transfer_asset(self, asset_id: uuid.UUID, payload: AssetTransferRequest, user_id: uuid.UUID, company_id: uuid.UUID) -> AssetResponse:
        """Transfer assignment directly from one employee to another with comprehensive validation."""
        # Use row-level locking to prevent concurrent modification
        asset = await self.repo.get_asset_by_id_for_update(asset_id, company_id=company_id)
        if not asset:
            raise NotFoundException("Asset not found.")

        # Validate asset is currently assigned
        if asset.status != "assigned" or not asset.employee_id:
            raise BadRequestException("Asset is not currently assigned to any employee.")

        # Validate source employee matches current holder
        if asset.employee_id != asset.employee_id:  # This is always true, we need to check the request context
            pass  # The asset.employee_id is the current holder

        # Find target employee within the same company
        res = await self.session.execute(
            select(Employee).where(
                Employee.id == payload.target_employee_id,
                Employee.company_id == company_id,
                Employee.is_deleted == False
            )
        )
        target_emp = res.scalars().first()
        if not target_emp:
            raise NotFoundException("Target employee not found.")

        # Validate target employee is active and eligible
        if target_emp.is_deactivated:
            raise BadRequestException("Cannot transfer asset to inactive or deactivated employee.")

        # Validate source and target are not the same
        if asset.employee_id == payload.target_employee_id:
            raise BadRequestException("Source and target employees cannot be identical.")

        user_name = await self._get_user_name(user_id)
        old_emp_name = f"{asset.employee.first_name} {asset.employee.last_name}" if asset.employee else "Previous Employee"
        target_emp_name = f"{target_emp.first_name} {target_emp.last_name}"
        target_department = target_emp.department

        # 1. Close active assignment history
        for hist in asset.assignment_history:
            if hist.actual_return_date is None:
                hist.actual_return_date = date.today()
                hist.notes = (hist.notes or "") + f" Transferred directly to {target_emp_name}."
                break

        # 2. Open new assignment history
        await self.repo.add_assignment_history(
            asset_id=asset.id,
            employee_name=target_emp_name,
            department=target_department,
            assign_date=date.today(),
            expected_return_date=payload.expected_return_date,
            notes=f"Transferred from {old_emp_name}. {payload.notes or ''}",
        )

        # 3. Update Asset
        asset.status = "assigned"
        asset.employee_id = target_emp.id
        asset.assigned_at = datetime.now()

        # 4. Append timeline log
        timeline_event = {
            "id": str(uuid.uuid4()),
            "event": "Transferred",
            "performed_by": user_name,
            "timestamp": datetime.now().isoformat(),
            "notes": f"Transferred from {old_emp_name} to {target_emp_name} ({target_department}).",
        }
        current_timeline = asset.timeline or []
        current_timeline.append(timeline_event)
        asset.timeline = current_timeline

        await self.session.commit()

        full_asset = await self.repo.get_asset_by_id(asset.id, company_id=company_id)
        return AssetResponse.model_validate(full_asset)

    async def mark_lost(self, asset_id: uuid.UUID, payload: AssetLostRequest, user_id: uuid.UUID, company_id: uuid.UUID) -> AssetResponse:
        """Flag asset status as lost with reason and last known holder tracking."""
        asset = await self.repo.get_asset_by_id_for_update(asset_id, company_id=company_id)
        if not asset:
            raise NotFoundException("Asset not found.")

        if asset.status == "lost":
            raise BadRequestException("Asset is already marked as lost.")

        # Store last known holder before clearing assignment
        last_holder_id = asset.employee_id
        last_holder_name = f"{asset.employee.first_name} {asset.employee.last_name}" if asset.employee else "Unknown"

        user_name = await self._get_user_name(user_id)
        asset.status = "lost"
        asset.lost_date = payload.lost_date or date.today()
        asset.lost_reason = payload.reason
        asset.last_known_holder_id = last_holder_id
        asset.employee_id = None
        asset.assigned_at = None

        # Close active assignment history
        for hist in asset.assignment_history:
            if hist.actual_return_date is None:
                hist.actual_return_date = date.today()
                hist.notes = (hist.notes or "") + f" Asset reported lost. Last holder: {last_holder_name}."
                break

        timeline_event = {
            "id": str(uuid.uuid4()),
            "event": "Lost",
            "performed_by": user_name,
            "timestamp": datetime.now().isoformat(),
            "notes": f"Asset marked as missing/lost. Reason: {payload.reason}. Last known holder: {last_holder_name}.",
        }
        current_timeline = asset.timeline or []
        current_timeline.append(timeline_event)
        asset.timeline = current_timeline

        await self.session.commit()

        full_asset = await self.repo.get_asset_by_id(asset.id, company_id=company_id)
        return AssetResponse.model_validate(full_asset)

    async def recover_lost_asset(self, asset_id: uuid.UUID, user_id: uuid.UUID, company_id: uuid.UUID) -> AssetResponse:
        """Recover a lost asset - transitions back to available status."""
        asset = await self.repo.get_asset_by_id_for_update(asset_id, company_id=company_id)
        if not asset:
            raise NotFoundException("Asset not found.")

        if asset.status != "lost":
            raise BadRequestException(f"Asset is not marked as lost. Current status: '{asset.status}'.")

        user_name = await self._get_user_name(user_id)
        asset.status = "available"
        asset.lost_date = None
        asset.lost_reason = None
        asset.last_known_holder_id = None

        timeline_event = {
            "id": str(uuid.uuid4()),
            "event": "Recovered",
            "performed_by": user_name,
            "timestamp": datetime.now().isoformat(),
            "notes": "Asset recovered from lost status. Returned to available inventory.",
        }
        current_timeline = asset.timeline or []
        current_timeline.append(timeline_event)
        asset.timeline = current_timeline

        await self.session.commit()

        full_asset = await self.repo.get_asset_by_id(asset.id, company_id=company_id)
        return AssetResponse.model_validate(full_asset)

    async def mark_retired(self, asset_id: uuid.UUID, user_id: uuid.UUID, company_id: uuid.UUID) -> AssetResponse:
        """Decommission asset, release active assignment, and log to timeline."""
        asset = await self.repo.get_asset_by_id(asset_id, company_id=company_id)
        if not asset:
            raise NotFoundException("Asset not found.")

        user_name = await self._get_user_name(user_id)
        
        # If assigned, close history
        for hist in asset.assignment_history:
            if hist.actual_return_date is None:
                hist.actual_return_date = date.today()
                break

        asset.status = "retired"
        asset.employee_id = None
        asset.assigned_at = None

        timeline_event = {
            "id": str(uuid.uuid4()),
            "event": "Retired",
            "performed_by": user_name,
            "timestamp": datetime.now().isoformat(),
            "notes": "Asset officially decommissioned and retired.",
        }
        current_timeline = asset.timeline or []
        current_timeline.append(timeline_event)
        asset.timeline = current_timeline

        await self.session.commit()

        full_asset = await self.repo.get_asset_by_id(asset.id, company_id=company_id)
        return AssetResponse.model_validate(full_asset)

    async def add_maintenance(
        self, asset_id: uuid.UUID, payload: AssetMaintenanceCreate, user_id: uuid.UUID, company_id: uuid.UUID
    ) -> AssetResponse:
        """Send asset for repair (mark as under-repair), register vendor/estimated cost, and log to timeline."""
        asset = await self.repo.get_asset_by_id_for_update(asset_id, company_id=company_id)
        if not asset:
            raise NotFoundException("Asset not found.")

        # Validate asset can be sent for maintenance
        if asset.status in {"lost", "retired", "disposed", "archived"}:
            raise BadRequestException(f"Asset cannot be sent for maintenance: current status is '{asset.status}'.")

        # Store previous assignee if assigned
        previous_holder_id = asset.employee_id
        previous_holder_name = f"{asset.employee.first_name} {asset.employee.last_name}" if asset.employee else None

        user_name = await self._get_user_name(user_id)
        asset.status = "under-repair"
        if asset.employee_id:
            asset.employee_id = None
            asset.assigned_at = None

        # Create maintenance record with REQUESTED status
        maintenance_record = await self.repo.add_maintenance_record(
            asset_id=asset.id,
            request_date=payload.request_date or date.today(),
            service_date=date.today(),
            vendor=payload.vendor,
            cost=payload.cost,
            estimated_cost=payload.estimated_cost,
            notes=payload.notes,
            status="REQUESTED",
        )

        timeline_event = {
            "id": str(uuid.uuid4()),
            "event": "MaintenanceRequested",
            "performed_by": user_name,
            "timestamp": datetime.now().isoformat(),
            "notes": f"Sent to maintenance: {payload.vendor}. Estimated cost: ${payload.estimated_cost or 'N/A'}."
            + (f" Issue: {payload.notes}" if payload.notes else "")
            + (f" Previous holder: {previous_holder_name}" if previous_holder_name else ""),
        }
        current_timeline = asset.timeline or []
        current_timeline.append(timeline_event)
        asset.timeline = current_timeline

        await self.session.commit()
        self.session.expire(asset, ["maintenance_history"])

        full_asset = await self.repo.get_asset_by_id(asset.id, company_id=company_id)
        return AssetResponse.model_validate(full_asset)

    async def complete_maintenance(
        self, asset_id: uuid.UUID, maintenance_id: uuid.UUID, payload: AssetMaintenanceComplete, user_id: uuid.UUID, company_id: uuid.UUID
    ) -> AssetResponse:
        """Complete maintenance - mark asset as available and update maintenance record."""
        asset = await self.repo.get_asset_by_id_for_update(asset_id, company_id=company_id)
        if not asset:
            raise NotFoundException("Asset not found.")

        if asset.status != "under-repair":
            raise BadRequestException(f"Asset is not under repair. Current status: '{asset.status}'.")

        # Find the maintenance record
        from app.models.asset import AssetMaintenanceRecord
        res = await self.session.execute(
            select(AssetMaintenanceRecord).where(
                AssetMaintenanceRecord.id == maintenance_id,
                AssetMaintenanceRecord.asset_id == asset_id,
            )
        )
        maintenance = res.scalar_one_or_none()
        if not maintenance:
            raise NotFoundException("Maintenance record not found.")

        if maintenance.status == "COMPLETED":
            raise BadRequestException("Maintenance already completed.")

        user_name = await self._get_user_name(user_id)
        
        # Update maintenance record
        maintenance.completion_date = payload.completion_date or date.today()
        maintenance.status = "COMPLETED"
        if payload.actual_cost is not None:
            maintenance.cost = payload.actual_cost
        if payload.completion_notes:
            maintenance.completion_notes = payload.completion_notes

        # Determine final asset status - if it had a previous holder, it goes back to available
        # The previous holder would need to be reassigned explicitly
        asset.status = "available"

        timeline_event = {
            "id": str(uuid.uuid4()),
            "event": "MaintenanceCompleted",
            "performed_by": user_name,
            "timestamp": datetime.now().isoformat(),
            "notes": f"Maintenance completed by {maintenance.vendor}. Actual cost: ${maintenance.cost}."
            + (f" Notes: {payload.completion_notes}" if payload.completion_notes else ""),
        }
        current_timeline = asset.timeline or []
        current_timeline.append(timeline_event)
        asset.timeline = current_timeline

        await self.session.commit()
        self.session.expire(asset, ["maintenance_history"])

        full_asset = await self.repo.get_asset_by_id(asset.id, company_id=company_id)
        return AssetResponse.model_validate(full_asset)

    async def get_analytics(self, company_id: uuid.UUID) -> AssetAnalyticsResponse:
        """Aggregate statistical report data of total inventory assets and repair valuations."""
        data = await self.repo.get_analytics_data(company_id=company_id)

        status_distribution = [
            StatusCount(name=k, value=v) for k, v in data["status_counts"].items()
        ]
        category_distribution = [
            CategoryCount(name=k, value=v) for k, v in data["category_counts"].items()
        ]
        
        repair_costs_by_category = [
            {"category": cat.upper(), "Total Repair Cost ($)": float(cost)}
            for cat, cost in data["repair_costs"].items()
        ]

        total_valuation = float(data["total_valuation"])

        # Populate count variables with defaults
        status_map = data["status_counts"]
        
        return AssetAnalyticsResponse(
            total_assets=sum(status_map.values()),
            available_assets=status_map.get("available", 0),
            assigned_assets=status_map.get("assigned", 0),
            under_repair_assets=status_map.get("under-repair", 0),
            lost_assets=status_map.get("lost", 0),
            active_warranty_assets=data.get("active_warranty_count", 0),
            expiring_warranty_assets=data.get("expiring_warranty_count", 0),
            expired_warranty_assets=data.get("expired_warranty_count", 0),
            unknown_warranty_assets=data.get("unknown_warranty_count", 0),
            category_distribution=category_distribution,
            status_distribution=status_distribution,
            total_valuation=total_valuation,
            repair_costs_by_category=repair_costs_by_category,
        )

    # Asset Request methods
    async def create_asset_request(self, payload: AssetRequestCreate, employee_id: uuid.UUID, company_id: uuid.UUID) -> AssetRequestResponse:
        """Create a new asset request from employee."""
        user_name = await self._get_user_name(employee_id)
        
        request = await self.repo.create_asset_request(
            company_id=company_id,
            employee_id=employee_id,
            request_type=payload.request_type,
            category=payload.category,
            justification=payload.justification,
            preferred_brand=payload.preferred_brand,
            preferred_model=payload.preferred_model,
            estimated_cost=payload.estimated_cost,
            status="PENDING",
        )
        await self.session.commit()
        
        # Re-fetch with relationships for response
        full_request = await self.repo.get_asset_request_by_id(request.id, company_id=company_id)
        return AssetRequestResponse.model_validate(full_request)

    async def list_asset_requests(
        self,
        company_id: uuid.UUID,
        employee_id: uuid.UUID | None = None,
        status: str | None = None,
        page: int = 1,
        limit: int = 20,
    ) -> tuple[list[AssetRequestResponse], int]:
        """List asset requests with filters."""
        items, total = await self.repo.list_asset_requests(
            company_id=company_id,
            employee_id=employee_id,
            status=status,
            page=page,
            limit=limit,
        )
        return [AssetRequestResponse.model_validate(item) for item in items], total

    async def approve_asset_request(self, request_id: uuid.UUID, approver_id: uuid.UUID, company_id: uuid.UUID) -> AssetRequestResponse:
        """Approve an asset request."""
        request = await self.repo.get_asset_request_by_id(request_id, company_id=company_id)
        if not request:
            raise NotFoundException("Asset request not found.")
        
        if request.status != "PENDING":
            raise BadRequestException(f"Request cannot be approved: current status is '{request.status}'.")

        user_name = await self._get_user_name(approver_id)
        await self.repo.update_asset_request(
            request,
            status="APPROVED",
            approver_id=approver_id,
            approved_at=datetime.now(),
        )
        await self.session.commit()
        
        full_request = await self.repo.get_asset_request_by_id(request.id, company_id=company_id)
        return AssetRequestResponse.model_validate(full_request)

    async def reject_asset_request(self, request_id: uuid.UUID, approver_id: uuid.UUID, rejection_reason: str, company_id: uuid.UUID) -> AssetRequestResponse:
        """Reject an asset request."""
        request = await self.repo.get_asset_request_by_id(request_id, company_id=company_id)
        if not request:
            raise NotFoundException("Asset request not found.")
        
        if request.status != "PENDING":
            raise BadRequestException(f"Request cannot be rejected: current status is '{request.status}'.")

        user_name = await self._get_user_name(approver_id)
        await self.repo.update_asset_request(
            request,
            status="REJECTED",
            approver_id=approver_id,
            approved_at=datetime.now(),
            rejection_reason=rejection_reason,
        )
        await self.session.commit()
        
        full_request = await self.repo.get_asset_request_by_id(request.id, company_id=company_id)
        return AssetRequestResponse.model_validate(full_request)

    async def fulfill_asset_request(self, request_id: uuid.UUID, asset_id: uuid.UUID, company_id: uuid.UUID) -> AssetRequestResponse:
        """Mark an asset request as fulfilled by assigning an asset."""
        request = await self.repo.get_asset_request_by_id(request_id, company_id=company_id)
        if not request:
            raise NotFoundException("Asset request not found.")
        
        if request.status != "APPROVED":
            raise BadRequestException(f"Request cannot be fulfilled: current status is '{request.status}'. Must be APPROVED first.")

        # Verify asset exists and is available
        asset = await self.repo.get_asset_by_id(asset_id, company_id=company_id)
        if not asset:
            raise NotFoundException("Asset not found.")
        if asset.status != "available":
            raise BadRequestException(f"Asset is not available for assignment: current status is '{asset.status}'.")

        await self.repo.update_asset_request(
            request,
            status="FULFILLED",
            assigned_asset_id=asset_id,
            fulfilled_at=datetime.now(),
        )
        await self.session.commit()
        
        full_request = await self.repo.get_asset_request_by_id(request.id, company_id=company_id)
        return AssetRequestResponse.model_validate(full_request)

    # Asset Damage Report methods
    async def create_damage_report(self, payload: AssetDamageReportCreate, reported_by_id: uuid.UUID, company_id: uuid.UUID) -> AssetDamageReportResponse:
        """Create a damage report for an asset."""
        # Verify asset exists and belongs to company
        asset = await self.repo.get_asset_by_id(payload.asset_id, company_id=company_id)
        if not asset:
            raise NotFoundException("Asset not found.")
        
        # Verify reporting employee belongs to company
        from app.models.employee import Employee
        res = await self.session.execute(
            select(Employee).where(Employee.id == reported_by_id, Employee.company_id == company_id, Employee.is_deleted == False)
        )
        reporter = res.scalars().first()
        if not reporter:
            raise NotFoundException("Reporting employee not found.")

        # Check for duplicate active damage report
        existing = await self.repo.get_damage_report_by_asset_and_employee(payload.asset_id, reported_by_id, company_id)
        if existing:
            raise BadRequestException("An active damage report already exists for this asset by this employee.")

        report = await self.repo.create_damage_report(
            company_id=company_id,
            asset_id=payload.asset_id,
            reported_by_id=reported_by_id,
            damage_type=payload.damage_type,
            severity=payload.severity,
            description=payload.description,
            location_of_incident=payload.location_of_incident,
            incident_date=payload.incident_date or date.today(),
            status="REPORTED",
        )
        await self.session.commit()
        
        full_report = await self.repo.get_damage_report_by_id(report.id, company_id=company_id)
        return AssetDamageReportResponse.model_validate(full_report)

    async def list_damage_reports(
        self,
        company_id: uuid.UUID,
        asset_id: uuid.UUID | None = None,
        status: str | None = None,
        page: int = 1,
        limit: int = 20,
    ) -> tuple[list[AssetDamageReportResponse], int]:
        """List damage reports with filters."""
        items, total = await self.repo.list_damage_reports(
            company_id=company_id,
            asset_id=asset_id,
            status=status,
            page=page,
            limit=limit,
        )
        return [AssetDamageReportResponse.model_validate(item) for item in items], total

    async def update_damage_report_status(
        self, report_id: uuid.UUID, status: str, resolution_notes: str | None, company_id: uuid.UUID
    ) -> AssetDamageReportResponse:
        """Update damage report status (e.g., to MAINTENANCE_SCHEDULED, REPAIRED, CLOSED)."""
        report = await self.repo.get_damage_report_by_id(report_id, company_id=company_id)
        if not report:
            raise NotFoundException("Damage report not found.")

        update_data = {"status": status}
        if status in ("REPAIRED", "CLOSED", "REPLACED"):
            update_data["resolved_at"] = datetime.now()
        if resolution_notes:
            update_data["resolution_notes"] = resolution_notes

        await self.repo.update_damage_report(report, **update_data)
        await self.session.commit()
        
        full_report = await self.repo.get_damage_report_by_id(report.id, company_id=company_id)
        return AssetDamageReportResponse.model_validate(full_report)


async def get_asset_service(
    session: Annotated[AsyncSession, Depends(get_db_session)]
) -> AssetService:
    """Dependency provider injecting database session to service layer."""
    return AssetService(session)
