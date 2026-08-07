"""Asset Repository: async database operations, no business logic."""

from __future__ import annotations
import logging
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, or_, select, desc, asc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.asset import Asset, AssetAssignmentHistory, AssetMaintenanceRecord
from app.models.employee import Employee

logger = logging.getLogger(__name__)


class AssetRepository:
    """Data access layer for all asset-related tables."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_asset(self, **kwargs) -> Asset:
        """Create a new asset record."""
        asset = Asset(**kwargs)
        self.session.add(asset)
        return asset

    async def get_asset_by_id(self, asset_id: uuid.UUID) -> Asset | None:
        """Retrieve asset with loaded relationships."""
        stmt = (
            select(Asset)
            .where(Asset.id == asset_id)
            .options(
                selectinload(Asset.employee),
                selectinload(Asset.assignment_history),
                selectinload(Asset.maintenance_history),
            )
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_asset_by_tag(self, tag: str) -> Asset | None:
        """Retrieve asset by tag with loaded relationships."""
        stmt = (
            select(Asset)
            .where(Asset.tag == tag)
            .options(
                selectinload(Asset.employee),
                selectinload(Asset.assignment_history),
                selectinload(Asset.maintenance_history),
            )
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

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
    ) -> tuple[list[Asset], int]:
        """Query paginated lists of assets with filters."""
        # 1. Build Query
        stmt = select(Asset).options(
            selectinload(Asset.employee),
            selectinload(Asset.maintenance_history)
        )
        count_stmt = select(func.count(Asset.id))
        
        needs_employee_join = bool(search or (department and department != "all") or sort_by in ("department", "assignedTo"))
        if needs_employee_join:
            stmt = stmt.outerjoin(Asset.employee)
            count_stmt = count_stmt.outerjoin(Asset.employee)
            
        filters = []
        if category and category != "all":
            filters.append(Asset.category == category)
        if status and status != "all":
            if status == "retired":
                filters.append(Asset.status.in_(["retired", "expired"]))
            else:
                filters.append(Asset.status == status)
        if vendor and vendor != "all":
            filters.append(Asset.vendor == vendor)
        if location and location != "all":
            filters.append(Asset.location == location)
        if department and department != "all":
            filters.append(Employee.department == department)
                
        if search:
            search_pattern = f"%{search.lower()}%"
            search_filter = or_(
                func.lower(Asset.name).like(search_pattern),
                func.lower(Asset.tag).like(search_pattern),
                func.lower(Asset.serial).like(search_pattern),
                func.lower(Asset.brand).like(search_pattern),
                func.lower(Asset.model).like(search_pattern),
                func.lower(Asset.location).like(search_pattern),
                func.lower(Employee.first_name).like(search_pattern),
                func.lower(Employee.last_name).like(search_pattern),
            )
            filters.append(search_filter)

        if filters:
            stmt = stmt.where(and_(*filters))
            count_stmt = count_stmt.where(and_(*filters))

        # 2. Count Total
        count_res = await self.session.execute(count_stmt)
        total = count_res.scalar_one()

        # 3. Paginate Items
        sort_mapping = {
            "tag": Asset.tag,
            "name": Asset.name,
            "category": Asset.category,
            "brand": Asset.brand,
            "serial": Asset.serial,
            "vendor": Asset.vendor,
            "location": Asset.location,
            "warranty_until": Asset.warranty_until,
            "status": Asset.status,
            "created_at": Asset.created_at,
            "department": Employee.department,
            "assignedTo": Employee.first_name
        }
        sort_col = sort_mapping.get(sort_by, Asset.created_at)
        sort_dir_fn = asc if sort_dir == "asc" else desc
        stmt = stmt.order_by(sort_dir_fn(sort_col))
        
        stmt = stmt.offset((page - 1) * limit).limit(limit)
        
        items_res = await self.session.execute(stmt)
        items = list(items_res.scalars().all())

        return items, total

    async def update_asset(self, asset: Asset, **kwargs) -> Asset:
        """Update fields on an asset instance."""
        for key, value in kwargs.items():
            if hasattr(asset, key):
                setattr(asset, key, value)
        return asset

    async def delete_asset(self, asset: Asset) -> None:
        """Remove asset record."""
        await self.session.delete(asset)

    async def add_assignment_history(self, **kwargs) -> AssetAssignmentHistory:
        """Append an assignment transaction trail."""
        hist = AssetAssignmentHistory(**kwargs)
        self.session.add(hist)
        return hist

    async def add_maintenance_record(self, **kwargs) -> AssetMaintenanceRecord:
        """Append a maintenance or repair log."""
        record = AssetMaintenanceRecord(**kwargs)
        self.session.add(record)
        return record

    async def get_analytics_data(self) -> dict[str, Any]:
        """Aggregate statistics for asset inventory, value, categories, and maintenance."""
        # 1. Total valuation
        val_stmt = select(func.sum(Asset.purchase_cost))
        val_res = await self.session.execute(val_stmt)
        total_valuation = val_res.scalar_one() or Decimal("0.0")

        # 2. Status counts
        status_stmt = select(Asset.status, func.count(Asset.id)).group_by(Asset.status)
        status_res = await self.session.execute(status_stmt)
        status_counts = dict(status_res.all())

        # 3. Category counts
        cat_stmt = select(Asset.category, func.count(Asset.id)).group_by(Asset.category)
        cat_res = await self.session.execute(cat_stmt)
        category_counts = dict(cat_res.all())

        # 4. Repair costs by category
        repair_stmt = (
            select(Asset.category, func.coalesce(func.sum(AssetMaintenanceRecord.cost), 0))
            .join(AssetMaintenanceRecord, AssetMaintenanceRecord.asset_id == Asset.id, isouter=True)
            .group_by(Asset.category)
        )
        repair_res = await self.session.execute(repair_stmt)
        repair_costs = dict(repair_res.all())

        # 5. Warranty expired & expiring soon (within 30 days)
        from datetime import date, timedelta
        today = date.today()
        thirty_days_later = today + timedelta(days=30)
        
        exp_stmt = select(func.count(Asset.id)).where(
            and_(Asset.warranty_until.isnot(None), Asset.warranty_until <= thirty_days_later)
        )
        exp_res = await self.session.execute(exp_stmt)
        expiring_count = exp_res.scalar_one()

        return {
            "total_valuation": total_valuation,
            "status_counts": status_counts,
            "category_counts": category_counts,
            "repair_costs": repair_costs,
            "expiring_warranty_count": expiring_count,
        }

    async def get_filter_options(self) -> tuple[list[str], list[str], list[str]]:
        """Retrieve distinct vendors, locations, and departments excluding NULLs, sorted alphabetically."""
        # 1. Distinct Vendors
        vendor_stmt = select(Asset.vendor).distinct().where(Asset.vendor.isnot(None)).order_by(Asset.vendor)
        vendor_res = await self.session.execute(vendor_stmt)
        vendors = list(vendor_res.scalars().all())

        # 2. Distinct Locations
        location_stmt = select(Asset.location).distinct().where(Asset.location.isnot(None)).order_by(Asset.location)
        location_res = await self.session.execute(location_stmt)
        locations = list(location_res.scalars().all())

        # 3. Distinct Departments via join through assigned assets
        dept_stmt = (
            select(Employee.department)
            .distinct()
            .join(Asset, Asset.employee_id == Employee.id)
            .where(Employee.department.isnot(None))
            .order_by(Employee.department)
        )
        dept_res = await self.session.execute(dept_stmt)
        departments = list(dept_res.scalars().all())

        return vendors, locations, departments
