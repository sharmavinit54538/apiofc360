"""Centralized audit logging service for payroll lifecycle events."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payroll import PayrollAuditLog

logger = logging.getLogger(__name__)


class PayrollAuditService:
    """Logs state transitions and sensitive data access."""

    @classmethod
    async def log_event(
        cls,
        session: AsyncSession,
        entity_type: str,
        entity_id: uuid.UUID | str | None,
        action: str,
        company_id: uuid.UUID | str | None = None,
        actor_id: uuid.UUID | str | None = None,
        actor_role: str | None = None,
        before_status: str | None = None,
        after_status: str | None = None,
        reason: str | None = None,
        extra_data: Optional[dict[str, Any]] = None,
    ) -> PayrollAuditLog:
        """Create and commit a persistent audit log entry for a payroll state change."""
        parsed_entity_id = None
        if entity_id:
            try:
                parsed_entity_id = uuid.UUID(str(entity_id))
            except ValueError:
                parsed_entity_id = None

        parsed_company_id = None
        if company_id:
            try:
                parsed_company_id = uuid.UUID(str(company_id))
            except ValueError:
                parsed_company_id = None

        parsed_actor_id = None
        if actor_id:
            try:
                parsed_actor_id = uuid.UUID(str(actor_id))
            except ValueError:
                parsed_actor_id = None

        entry = PayrollAuditLog(
            id=uuid.uuid4(),
            entity_type=entity_type,
            entity_id=parsed_entity_id,
            company_id=parsed_company_id,
            action=action.upper(),
            actor_id=parsed_actor_id,
            actor_role=actor_role,
            old_status=before_status,
            new_status=after_status,
            reason=reason,
            extra_data=extra_data or {},
        )
        session.add(entry)
        try:
            await session.flush()
        except Exception as e:
            logger.warning("Failed to flush audit log entry: %s", e)
        return entry
