"""Centralized Service Level Agreement (SLA) Engine for OFC360 Helpdesk."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

# Default SLA duration configuration in hours
SLA_HOURS_CONFIG: dict[str, dict[str, int]] = {
    "urgent": {
        "first_response_hours": 1,
        "resolution_hours": 4,
    },
    "high": {
        "first_response_hours": 4,
        "resolution_hours": 24,
    },
    "medium": {
        "first_response_hours": 8,
        "resolution_hours": 48,
    },
    "low": {
        "first_response_hours": 24,
        "resolution_hours": 72,
    },
}


class HelpdeskSLAService:
    """Calculates and verifies SLA target deadlines and dynamically evaluates breaches."""

    @classmethod
    def calculate_sla_deadlines(
        cls,
        priority: str,
        from_time: datetime | None = None,
    ) -> tuple[datetime, datetime]:
        """Calculate first response and resolution target timestamps based on ticket priority."""
        base_time = from_time or datetime.now(timezone.utc)
        p_key = priority.lower().strip()
        config = SLA_HOURS_CONFIG.get(p_key, SLA_HOURS_CONFIG["medium"])

        first_response_due = base_time + timedelta(hours=config["first_response_hours"])
        resolution_due = base_time + timedelta(hours=config["resolution_hours"])

        return first_response_due, resolution_due

    @classmethod
    def check_is_breached(
        cls,
        status: str,
        sla_resolution_due_at: datetime | None,
        sla_first_response_due_at: datetime | None = None,
        first_responded_at: datetime | None = None,
        resolved_at: datetime | None = None,
    ) -> bool:
        """Dynamically determine if a ticket has breached SLA targets."""
        now = datetime.now(timezone.utc)

        # Normalize datetimes to timezone-aware UTC if needed
        def to_utc(dt: datetime | None) -> datetime | None:
            if dt is None:
                return None
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)

        res_due = to_utc(sla_resolution_due_at)
        resp_due = to_utc(sla_first_response_due_at)
        first_resp = to_utc(first_responded_at)
        res_at = to_utc(resolved_at)

        status_lower = status.lower().strip()

        # 1. First Response breach check
        if resp_due:
            if first_resp and first_resp > resp_due:
                return True
            if not first_resp and now > resp_due and status_lower not in ("resolved", "closed"):
                return True

        # 2. Resolution breach check
        if res_due:
            if res_at and res_at > res_due:
                return True
            if not res_at and now > res_due and status_lower not in ("resolved", "closed"):
                return True

        return False
