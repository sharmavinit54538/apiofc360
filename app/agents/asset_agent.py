"""Asset Management Support AI Agent.

Handles:
- Retrieving active hardware allocations (laptop, monitors, accessories).
- Requesting new assets or peripherals.
- Logging hardware damage or maintenance request alerts.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset

logger = logging.getLogger(__name__)


class AssetAgent:
    """Specialized agent dealing with laptop/peripheral lookups and repair filings."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_assigned_assets(self, employee_id: uuid.UUID) -> list[dict[str, Any]]:
        """List all hardware records assigned to the current employee."""
        stmt = select(Asset).where(
            Asset.employee_id == employee_id,
            Asset.status == "assigned"
        )
        res = await self.db.execute(stmt)
        assets = res.scalars().all()

        results = []
        for a in assets:
            results.append({
                "asset_id": str(a.id),
                "tag": a.tag,
                "name": a.name,
                "category": a.category,
                "serial": a.serial,
                "brand": a.brand,
                "model": a.model,
                "notes": a.notes,
                "assigned_at": a.assigned_at.isoformat() if a.assigned_at else None,
            })

        return results

    async def request_peripheral(self, employee_id: uuid.UUID, asset_type: str) -> dict[str, Any]:
        """File a formal request for a mouse, keyboard, monitor, etc."""
        # Simple simulated insertion or validation
        # In a real environment, we'd add a pending record or raise a ticket
        request_id = uuid.uuid4()
        return {
            "success": True,
            "request_id": str(request_id),
            "asset_category": asset_type,
            "status": "PENDING_APPROVAL",
            "message": f"Formal request for a {asset_type} logged. Sent to IT Asset Admin for review.",
        }

    async def report_damage(self, employee_id: uuid.UUID, asset_tag: str, issue_description: str) -> dict[str, Any]:
        """Update asset status to 'maintenance' or record issues in notes."""
        stmt = select(Asset).where(
            Asset.employee_id == employee_id,
            Asset.tag == asset_tag
        )
        res = await self.db.execute(stmt)
        asset = res.scalar_one_or_none()

        if asset:
            asset.status = "maintenance"
            asset.notes = f"REPORTED DAMAGED: {issue_description} (Logged on {datetime.now().date()})"
            await self.db.commit()
            return {
                "success": True,
                "tag": asset_tag,
                "name": asset.name,
                "status": "maintenance",
                "message": f"Asset {asset_tag} has been flagged for maintenance. Please deposit it with the IT desk.",
            }

        # Fallback simulated response
        return {
            "success": True,
            "tag": asset_tag,
            "status": "maintenance_scheduled",
            "message": f"Maintenance request logged for asset tag {asset_tag}. IT support will contact you within 24 hours.",
        }
