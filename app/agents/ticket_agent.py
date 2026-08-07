"""Support Ticket AI Agent.

Handles:
- Creating a support ticket.
- Querying a list of logged tickets for an employee.
- Updating ticket status (e.g., CLOSED, ESCALATED).
- Escalation rules (notifying IT or HR admins).
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.ai_employee_support import SupportTicket, TicketUpdate

logger = logging.getLogger(__name__)


class TicketAgent:
    """Specialized agent dealing with ticket creation, updating, and audit logs."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_ticket(
        self,
        employee_id: uuid.UUID,
        category: str,
        priority: str,
        title: str,
        description: str,
        company_id: Optional[uuid.UUID] = None,
    ) -> SupportTicket:
        """Create a new SupportTicket in the database."""
        ticket = SupportTicket(
            id=uuid.uuid4(),
            company_id=company_id,
            employee_id=employee_id,
            category=category.upper(),
            priority=priority.upper(),
            status="OPEN",
            title=title,
            description=description,
        )
        self.db.add(ticket)
        await self.db.commit()
        await self.db.refresh(ticket)

        # Log creation update
        initial_update = TicketUpdate(
            ticket_id=ticket.id,
            update_text="Ticket opened automatically by Employee Support AI Agent.",
            status_changed_to="OPEN",
        )
        self.db.add(initial_update)
        await self.db.commit()

        logger.info("Support ticket %s created for employee %s", ticket.id, employee_id)
        return ticket

    async def get_tickets_by_employee(self, employee_id: uuid.UUID) -> list[SupportTicket]:
        """Fetch all tickets raised by an employee, sorted by created date."""
        stmt = (
            select(SupportTicket)
            .where(SupportTicket.employee_id == employee_id)
            .options(selectinload(SupportTicket.updates))
            .order_by(SupportTicket.created_at.desc())
        )
        res = await self.db.execute(stmt)
        return list(res.scalars().all())

    async def get_ticket_details(self, ticket_id: uuid.UUID) -> Optional[SupportTicket]:
        stmt = (
            select(SupportTicket)
            .where(SupportTicket.id == ticket_id)
            .options(selectinload(SupportTicket.updates).selectinload(TicketUpdate.author))
        )
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def update_ticket(
        self,
        ticket_id: uuid.UUID,
        update_text: str,
        new_status: Optional[str] = None,
        updater_uuid: Optional[uuid.UUID] = None,
    ) -> bool:
        """Update ticket state or append comments."""
        ticket = await self.get_ticket_details(ticket_id)
        if not ticket:
            return False

        if new_status:
            ticket.status = new_status.upper()

        update_log = TicketUpdate(
            ticket_id=ticket_id,
            updated_by=updater_uuid,
            update_text=update_text,
            status_changed_to=new_status.upper() if new_status else None,
        )
        self.db.add(update_log)
        await self.db.commit()
        return True

    async def close_ticket(self, ticket_id: uuid.UUID, updater_uuid: Optional[uuid.UUID] = None) -> bool:
        """Close support ticket."""
        return await self.update_ticket(
            ticket_id=ticket_id,
            update_text="Ticket marked as resolved and closed.",
            new_status="CLOSED",
            updater_uuid=updater_uuid,
        )

    async def escalate_ticket(self, ticket_id: uuid.UUID, updater_uuid: Optional[uuid.UUID] = None) -> bool:
        """Escalate to senior IT / HR support team."""
        return await self.update_ticket(
            ticket_id=ticket_id,
            update_text="AI Agent determined this ticket requires manual intervention. Escalated to senior HR/IT queue.",
            new_status="ESCALATED",
            updater_uuid=updater_uuid,
        )
