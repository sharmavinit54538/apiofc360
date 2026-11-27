"""Asset Repository: async database operations, no business logic."""

from __future__ import annotations
import logging
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, or_, select, desc, asc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only, selectinload

from app.models.asset import Asset, AssetAssignmentHistory, AssetMaintenanceRecord, AssetRequest, AssetDamageReport
from app.models.employee import Employee

logger = logging.getLogger(__name__)

# Assets responses only render assignee display identity and department; avoid loading encrypted PII.
_ASSET_EMPLOYEE_COLUMNS = (
    Employee.id,
    Employee.company_id,
    Employee.employee_id,
    Employee.first_name,
    Employee.last_name,
    Employee.department,
)


class AssetRepository:
    """Data access layer for all asset-related tables."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_asset(self, **kwargs) -> Asset:
        """Create a new asset record."""
        asset = Asset(**kwargs)
        self.session.add(asset)
        return asset

    async def get_asset_by_id(self, asset_id: uuid.UUID, company_id: uuid.UUID | None = None) -> Asset | None:
        """Retrieve asset with loaded relationships."""
        stmt = (
            select(Asset)
            .where(Asset.id == asset_id)
            .options(
                selectinload(Asset.employee).load_only(*_ASSET_EMPLOYEE_COLUMNS),
                selectinload(Asset.assignment_history),
                selectinload(Asset.maintenance_history),
            )
        )
        if company_id is not None:
            stmt = stmt.where(Asset.company_id == company_id)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_asset_by_id_for_update(self, asset_id: uuid.UUID, company_id: uuid.UUID | None = None) -> Asset | None:
        """Retrieve asset with row-level lock (SELECT FOR UPDATE) for concurrent assignment safety."""
        stmt = (
            select(Asset)
            .where(Asset.id == asset_id)
            .options(
                selectinload(Asset.employee).load_only(*_ASSET_EMPLOYEE_COLUMNS),
                selectinload(Asset.assignment_history),
                selectinload(Asset.maintenance_history),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if company_id is not None:
            stmt = stmt.where(Asset.company_id == company_id)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_asset_by_tag(self, tag: str, company_id: uuid.UUID | None = None) -> Asset | None:
        """Retrieve asset by tag with loaded relationships."""
        stmt = (
            select(Asset)
            .where(Asset.tag == tag)
            .options(
                selectinload(Asset.employee).load_only(*_ASSET_EMPLOYEE_COLUMNS),
                selectinload(Asset.assignment_history),
                selectinload(Asset.maintenance_history),
            )
        )
        if company_id is not None:
            stmt = stmt.where(Asset.company_id == company_id)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def list_assets(
        self,
        company_id: uuid.UUID | None = None,
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
            selectinload(Asset.employee).load_only(*_ASSET_EMPLOYEE_COLUMNS),
            selectinload(Asset.maintenance_history),
        )
        count_stmt = select(func.count(Asset.id))
        
        needs_employee_join = bool(search or (department and department != "all") or sort_by in ("department", "assignedTo"))
        if needs_employee_join:
            stmt = stmt.outerjoin(Asset.employee)
            count_stmt = count_stmt.outerjoin(Asset.employee)
            
        filters = []
        if company_id is not None:
            filters.append(Asset.company_id == company_id)
        else:
            # Enforce tenant isolation: if no company_id provided, return no assets
            filters.append(Asset.company_id.is_(None))

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

    async def get_analytics_data(self, company_id: uuid.UUID | None = None) -> dict[str, Any]:
        """Aggregate statistics for asset inventory, value, categories, and maintenance."""
        cid_filter = [Asset.company_id == company_id] if company_id is not None else []

        # 1. Total valuation
        val_stmt = select(func.sum(Asset.purchase_cost))
        if cid_filter:
            val_stmt = val_stmt.where(*cid_filter)
        val_res = await self.session.execute(val_stmt)
        total_valuation = val_res.scalar_one() or Decimal("0.0")

        # 2. Status counts
        status_stmt = select(Asset.status, func.count(Asset.id)).group_by(Asset.status)
        if cid_filter:
            status_stmt = status_stmt.where(*cid_filter)
        status_res = await self.session.execute(status_stmt)
        status_counts = dict(status_res.all())

        # 3. Category counts
        cat_stmt = select(Asset.category, func.count(Asset.id)).group_by(Asset.category)
        if cid_filter:
            cat_stmt = cat_stmt.where(*cid_filter)
        cat_res = await self.session.execute(cat_stmt)
        category_counts = dict(cat_res.all())

        # 4. Repair costs by category
        repair_stmt = (
            select(Asset.category, func.coalesce(func.sum(AssetMaintenanceRecord.cost), 0))
            .join(AssetMaintenanceRecord, AssetMaintenanceRecord.asset_id == Asset.id, isouter=True)
        )
        if cid_filter:
            repair_stmt = repair_stmt.where(*cid_filter)
        repair_stmt = repair_stmt.group_by(Asset.category)
        repair_res = await self.session.execute(repair_stmt)
        repair_costs = dict(repair_res.all())

        # 5. Warranty analytics - separate active, expiring, expired, unknown
        from datetime import date, timedelta
        today = date.today()
        thirty_days_later = today + timedelta(days=30)
        
        cid_cond = [Asset.company_id == company_id] if company_id is not None else []
        
        # Active excludes the separate 30-day expiring-soon bucket.
        active_conditions = [Asset.warranty_until.isnot(None), Asset.warranty_until > thirty_days_later] + cid_cond
        active_stmt = select(func.count(Asset.id)).where(and_(*active_conditions))
        active_res = await self.session.execute(active_stmt)
        active_warranty_count = active_res.scalar_one()
        
        # Expiring warranty: warranty_until between today and 30 days from now (inclusive)
        expiring_conditions = [
            Asset.warranty_until.isnot(None),
            Asset.warranty_until >= today,
            Asset.warranty_until <= thirty_days_later
        ] + cid_cond
        expiring_stmt = select(func.count(Asset.id)).where(and_(*expiring_conditions))
        expiring_res = await self.session.execute(expiring_stmt)
        expiring_warranty_count = expiring_res.scalar_one()
        
        # Expired warranty: warranty_until < today
        expired_conditions = [Asset.warranty_until.isnot(None), Asset.warranty_until < today] + cid_cond
        expired_stmt = select(func.count(Asset.id)).where(and_(*expired_conditions))
        expired_res = await self.session.execute(expired_stmt)
        expired_warranty_count = expired_res.scalar_one()
        
        # Unknown warranty: warranty_until is NULL
        unknown_conditions = [Asset.warranty_until.is_(None)] + cid_cond
        unknown_stmt = select(func.count(Asset.id)).where(and_(*unknown_conditions))
        unknown_res = await self.session.execute(unknown_stmt)
        unknown_warranty_count = unknown_res.scalar_one()

        return {
            "total_valuation": total_valuation,
            "status_counts": status_counts,
            "category_counts": category_counts,
            "repair_costs": repair_costs,
            "active_warranty_count": active_warranty_count,
            "expiring_warranty_count": expiring_warranty_count,
            "expired_warranty_count": expired_warranty_count,
            "unknown_warranty_count": unknown_warranty_count,
        }

    async def get_filter_options(self, company_id: uuid.UUID | None = None) -> tuple[list[str], list[str], list[str]]:
        """Retrieve distinct vendors, locations, and departments excluding NULLs, sorted alphabetically."""
        cid_filter = [Asset.company_id == company_id] if company_id is not None else []

        # 1. Distinct Vendors
        vendor_stmt = select(Asset.vendor).distinct().where(Asset.vendor.isnot(None), *cid_filter).order_by(Asset.vendor)
        vendor_res = await self.session.execute(vendor_stmt)
        vendors = list(vendor_res.scalars().all())

        # 2. Distinct Locations
        location_stmt = select(Asset.location).distinct().where(Asset.location.isnot(None), *cid_filter).order_by(Asset.location)
        location_res = await self.session.execute(location_stmt)
        locations = list(location_res.scalars().all())

        # 3. Distinct Departments via join through assigned assets
        dept_stmt = (
            select(Employee.department)
            .distinct()
            .join(Asset, Asset.employee_id == Employee.id)
            .where(Employee.department.isnot(None), *cid_filter)
            .order_by(Employee.department)
        )
        dept_res = await self.session.execute(dept_stmt)
        departments = list(dept_res.scalars().all())

        return vendors, locations, departments

    # Asset Request methods
    async def create_asset_request(self, **kwargs) -> AssetRequest:
        """Create a new asset request."""
        request = AssetRequest(**kwargs)
        self.session.add(request)
        return request

    async def get_asset_request_by_id(self, request_id: uuid.UUID, company_id: uuid.UUID | None = None, *, for_update: bool = False) -> AssetRequest | None:
        """Retrieve asset request by ID."""
        stmt = (
            select(AssetRequest)
            .options(selectinload(AssetRequest.employee).load_only(*_ASSET_EMPLOYEE_COLUMNS))
            .where(AssetRequest.id == request_id)
        )
        if for_update:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        if company_id is not None:
            stmt = stmt.where(AssetRequest.company_id == company_id)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def list_asset_requests(
        self,
        company_id: uuid.UUID,
        employee_id: uuid.UUID | None = None,
        status: str | None = None,
        page: int = 1,
        limit: int = 20,
    ) -> tuple[list[AssetRequest], int]:
        """List asset requests with filters."""
        stmt = (
            select(AssetRequest)
            .options(selectinload(AssetRequest.employee).load_only(*_ASSET_EMPLOYEE_COLUMNS))
            .where(AssetRequest.company_id == company_id)
        )
        count_stmt = select(func.count(AssetRequest.id)).where(AssetRequest.company_id == company_id)

        if employee_id:
            stmt = stmt.where(AssetRequest.employee_id == employee_id)
            count_stmt = count_stmt.where(AssetRequest.employee_id == employee_id)
        if status:
            stmt = stmt.where(AssetRequest.status == status)
            count_stmt = count_stmt.where(AssetRequest.status == status)

        count_res = await self.session.execute(count_stmt)
        total = count_res.scalar_one()

        stmt = stmt.order_by(desc(AssetRequest.created_at)).offset((page - 1) * limit).limit(limit)
        items_res = await self.session.execute(stmt)
        items = list(items_res.scalars().all())

        return items, total

    async def update_asset_request(self, request: AssetRequest, **kwargs) -> AssetRequest:
        """Update asset request fields."""
        for key, value in kwargs.items():
            if hasattr(request, key):
                setattr(request, key, value)
        return request

    # Asset Damage Report methods
    async def create_damage_report(self, **kwargs) -> AssetDamageReport:
        """Create a new damage report."""
        report = AssetDamageReport(**kwargs)
        self.session.add(report)
        return report

    async def get_damage_report_by_id(self, report_id: uuid.UUID, company_id: uuid.UUID | None = None) -> AssetDamageReport | None:
        """Retrieve damage report by ID with relationships loaded."""
        stmt = select(AssetDamageReport).options(
            selectinload(AssetDamageReport.asset),
            selectinload(AssetDamageReport.reported_by)
        ).where(AssetDamageReport.id == report_id)
        if company_id is not None:
            stmt = stmt.where(AssetDamageReport.company_id == company_id)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_damage_report_by_asset_and_employee(
        self, asset_id: uuid.UUID, employee_id: uuid.UUID, company_id: uuid.UUID | None = None
    ) -> AssetDamageReport | None:
        """Check for existing damage report for asset by employee."""
        stmt = select(AssetDamageReport).where(
            AssetDamageReport.asset_id == asset_id,
            AssetDamageReport.reported_by_id == employee_id,
            AssetDamageReport.status.in_(["REPORTED", "UNDER_REVIEW", "MAINTENANCE_SCHEDULED"])
        )
        if company_id is not None:
            stmt = stmt.where(AssetDamageReport.company_id == company_id)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def list_damage_reports(
        self,
        company_id: uuid.UUID,
        asset_id: uuid.UUID | None = None,
        status: str | None = None,
        page: int = 1,
        limit: int = 20,
    ) -> tuple[list[AssetDamageReport], int]:
        """List damage reports with filters."""
        stmt = select(AssetDamageReport).where(AssetDamageReport.company_id == company_id)
        count_stmt = select(func.count(AssetDamageReport.id)).where(AssetDamageReport.company_id == company_id)

        if asset_id:
            stmt = stmt.where(AssetDamageReport.asset_id == asset_id)
            count_stmt = count_stmt.where(AssetDamageReport.asset_id == asset_id)
        if status:
            stmt = stmt.where(AssetDamageReport.status == status)
            count_stmt = count_stmt.where(AssetDamageReport.status == status)

        count_res = await self.session.execute(count_stmt)
        total = count_res.scalar_one()

        stmt = stmt.order_by(desc(AssetDamageReport.created_at)).offset((page - 1) * limit).limit(limit)
        items_res = await self.session.execute(stmt)
        items = list(items_res.scalars().all())

        return items, total

    async def update_damage_report(self, report: AssetDamageReport, **kwargs) -> AssetDamageReport:
        """Update damage report fields."""
        for key, value in kwargs.items():
            if hasattr(report, key):
                setattr(report, key, value)
        return report
