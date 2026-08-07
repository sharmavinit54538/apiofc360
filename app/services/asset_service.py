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
    AssetMaintenanceCreate,
    AssetAnalyticsResponse,
    AssetListResponse,
    CategoryCount,
    StatusCount,
    AssetResponse,
    AssetFilterOptionsResponse,
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

    async def get_filter_options(self) -> AssetFilterOptionsResponse:
        """Get distinct filter values (vendors, locations, departments) from repository."""
        vendors, locations, departments = await self.repo.get_filter_options()
        return AssetFilterOptionsResponse(
            vendors=vendors,
            locations=locations,
            departments=departments,
        )

    async def get_asset(self, asset_id: uuid.UUID) -> AssetResponse:
        """Fetch asset details by UUID."""
        asset = await self.repo.get_asset_by_id(asset_id)
        if not asset:
            raise NotFoundException("Asset not found.")
        return AssetResponse.model_validate(asset)

    async def create_asset(self, payload: AssetCreate, user_id: uuid.UUID) -> AssetResponse:
        """Register a new asset and append its creation log to the timeline."""
        # Check if asset tag already exists
        existing = await self.repo.get_asset_by_tag(payload.tag)
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
        asset_data["timeline"] = [timeline_event]
        asset_data["status"] = "available"

        asset = await self.repo.create_asset(**asset_data)
        await self.session.commit()
        
        # Re-fetch with relationships
        full_asset = await self.repo.get_asset_by_id(asset.id)
        return AssetResponse.model_validate(full_asset)

    async def update_asset(self, asset_id: uuid.UUID, payload: AssetUpdate, user_id: uuid.UUID) -> AssetResponse:
        """Update specifications of an asset and append a specifications update log."""
        asset = await self.repo.get_asset_by_id(asset_id)
        if not asset:
            raise NotFoundException("Asset not found.")

        user_name = await self._get_user_name(user_id)
        update_data = payload.model_dump(exclude_unset=True)

        # Append spec edit event to timeline
        timeline_event = {
            "id": str(uuid.uuid4()),
            "event": "Created",
            "performed_by": user_name,
            "timestamp": datetime.now().isoformat(),
            "notes": "Asset specifications updated.",
        }
        
        current_timeline = asset.timeline or []
        current_timeline.append(timeline_event)
        update_data["timeline"] = current_timeline

        await self.repo.update_asset(asset, **update_data)
        await self.session.commit()

        full_asset = await self.repo.get_asset_by_id(asset.id)
        return AssetResponse.model_validate(full_asset)

    async def delete_asset(self, asset_id: uuid.UUID) -> None:
        """Delete an asset record."""
        asset = await self.repo.get_asset_by_id(asset_id)
        if not asset:
            raise NotFoundException("Asset not found.")
        await self.repo.delete_asset(asset)
        await self.session.commit()

    async def assign_asset(self, asset_id: uuid.UUID, payload: AssetAssignRequest, user_id: uuid.UUID) -> AssetResponse:
        """Assign an asset to an employee, writing history and timeline events."""
        asset = await self.repo.get_asset_by_id(asset_id)
        if not asset:
            raise NotFoundException("Asset not found.")

        if asset.status == "assigned":
            raise BadRequestException("Asset is already assigned to another employee.")

        # Find employee
        res = await self.session.execute(
            select(Employee).where(
                func.concat(Employee.first_name, " ", Employee.last_name) == payload.employee_name,
                Employee.is_deleted == False
            )
        )
        emp = res.scalars().first()
        if not emp:
            raise NotFoundException(f"Employee '{payload.employee_name}' not found.")

        user_name = await self._get_user_name(user_id)
        
        # 1. Update Asset properties
        asset.status = "assigned"
        asset.employee_id = emp.id
        asset.assigned_at = datetime.now()

        # 2. Add history record
        await self.repo.add_assignment_history(
            asset_id=asset.id,
            employee_name=payload.employee_name,
            department=payload.department,
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
            "notes": f"Assigned to {payload.employee_name} ({payload.department})."
            + (f" Notes: {payload.notes}" if payload.notes else ""),
        }
        current_timeline = asset.timeline or []
        current_timeline.append(timeline_event)
        asset.timeline = current_timeline

        await self.session.commit()
        
        full_asset = await self.repo.get_asset_by_id(asset.id)
        return AssetResponse.model_validate(full_asset)

    async def return_asset(self, asset_id: uuid.UUID, user_id: uuid.UUID) -> AssetResponse:
        """Return an asset back to inventory, closing active assignment history and logging timeline."""
        asset = await self.repo.get_asset_by_id(asset_id)
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

        full_asset = await self.repo.get_asset_by_id(asset.id)
        return AssetResponse.model_validate(full_asset)

    async def transfer_asset(self, asset_id: uuid.UUID, payload: AssetAssignRequest, user_id: uuid.UUID) -> AssetResponse:
        """Transfer assignment directly from one employee to another."""
        asset = await self.repo.get_asset_by_id(asset_id)
        if not asset:
            raise NotFoundException("Asset not found.")

        res = await self.session.execute(
            select(Employee).where(
                func.concat(Employee.first_name, " ", Employee.last_name) == payload.employee_name,
                Employee.is_deleted == False
            )
        )
        emp = res.scalars().first()
        if not emp:
            raise NotFoundException(f"Employee '{payload.employee_name}' not found.")

        user_name = await self._get_user_name(user_id)
        old_emp_name = f"{asset.employee.first_name} {asset.employee.last_name}" if asset.employee else "Previous Employee"

        # 1. Close active assignment history
        for hist in asset.assignment_history:
            if hist.actual_return_date is None:
                hist.actual_return_date = date.today()
                hist.notes = (hist.notes or "") + f" Transferred directly to {payload.employee_name}."
                break

        # 2. Open new assignment history
        await self.repo.add_assignment_history(
            asset_id=asset.id,
            employee_name=payload.employee_name,
            department=payload.department,
            assign_date=date.today(),
            expected_return_date=payload.expected_return_date,
            notes=f"Transferred from {old_emp_name}. {payload.notes or ''}",
        )

        # 3. Update Asset
        asset.status = "assigned"
        asset.employee_id = emp.id
        asset.assigned_at = datetime.now()

        # 4. Append timeline log
        timeline_event = {
            "id": str(uuid.uuid4()),
            "event": "Transferred",
            "performed_by": user_name,
            "timestamp": datetime.now().isoformat(),
            "notes": f"Transferred from {old_emp_name} to {payload.employee_name} ({payload.department}).",
        }
        current_timeline = asset.timeline or []
        current_timeline.append(timeline_event)
        asset.timeline = current_timeline

        await self.session.commit()

        full_asset = await self.repo.get_asset_by_id(asset.id)
        return AssetResponse.model_validate(full_asset)

    async def mark_lost(self, asset_id: uuid.UUID, user_id: uuid.UUID) -> AssetResponse:
        """Flag asset status as lost and append timeline audit log."""
        asset = await self.repo.get_asset_by_id(asset_id)
        if not asset:
            raise NotFoundException("Asset not found.")

        user_name = await self._get_user_name(user_id)
        asset.status = "lost"

        timeline_event = {
            "id": str(uuid.uuid4()),
            "event": "Lost",
            "performed_by": user_name,
            "timestamp": datetime.now().isoformat(),
            "notes": "Asset marked as missing/lost. Initiating replacement audit.",
        }
        current_timeline = asset.timeline or []
        current_timeline.append(timeline_event)
        asset.timeline = current_timeline

        await self.session.commit()

        full_asset = await self.repo.get_asset_by_id(asset.id)
        return AssetResponse.model_validate(full_asset)

    async def mark_retired(self, asset_id: uuid.UUID, user_id: uuid.UUID) -> AssetResponse:
        """Decommission asset, release active assignment, and log to timeline."""
        asset = await self.repo.get_asset_by_id(asset_id)
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

        full_asset = await self.repo.get_asset_by_id(asset.id)
        return AssetResponse.model_validate(full_asset)

    async def add_maintenance(
        self, asset_id: uuid.UUID, payload: AssetMaintenanceCreate, user_id: uuid.UUID
    ) -> AssetResponse:
        """Send asset for repair, register cost/vendor, and log to timeline."""
        asset = await self.repo.get_asset_by_id(asset_id)
        if not asset:
            raise NotFoundException("Asset not found.")

        user_name = await self._get_user_name(user_id)
        asset.status = "under-repair"

        # Create record
        await self.repo.add_maintenance_record(
            asset_id=asset.id,
            request_date=payload.request_date or date.today(),
            service_date=date.today(),
            vendor=payload.vendor,
            cost=payload.cost,
            notes=payload.notes,
        )

        timeline_event = {
            "id": str(uuid.uuid4()),
            "event": "Repaired",
            "performed_by": user_name,
            "timestamp": datetime.now().isoformat(),
            "notes": f"Sent to maintenance: {payload.vendor}. Cost: ${payload.cost}."
            + (f" Issue: {payload.notes}" if payload.notes else ""),
        }
        current_timeline = asset.timeline or []
        current_timeline.append(timeline_event)
        asset.timeline = current_timeline

        await self.session.commit()
        self.session.expire(asset, ["maintenance_history"])

        full_asset = await self.repo.get_asset_by_id(asset.id)
        return AssetResponse.model_validate(full_asset)

    async def get_analytics(self) -> AssetAnalyticsResponse:
        """Aggregate statistical report data of total inventory assets and repair valuations."""
        data = await self.repo.get_analytics_data()

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
            expiring_warranty_assets=data["expiring_warranty_count"],
            category_distribution=category_distribution,
            status_distribution=status_distribution,
            total_valuation=total_valuation,
            repair_costs_by_category=repair_costs_by_category,
        )


async def get_asset_service(
    session: Annotated[AsyncSession, Depends(get_db_session)]
) -> AssetService:
    """Dependency provider injecting database session to service layer."""
    return AssetService(session)
