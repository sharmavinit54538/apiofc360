"""Tenant-isolated database repository for OFC360 Helpdesk & Support."""

from __future__ import annotations

from datetime import datetime, timezone
import math
import random
from typing import Any, Sequence
import uuid

from sqlalchemy import (
    and_, case, delete, desc, func, or_, select, update,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.helpdesk import (
    HelpdeskAttachment,
    HelpdeskComment,
    HelpdeskFAQ,
    HelpdeskInternalNote,
    HelpdeskTicket,
)
from app.models.user import User
from app.services.helpdesk_sla_service import HelpdeskSLAService


class HelpdeskRepository:
    """Repository managing tenant-isolated database access for the Helpdesk module."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # =======================================================================
    # Ticket Number Generation
    # =======================================================================

    async def generate_unique_ticket_number(self, company_id: uuid.UUID) -> str:
        """Generate a random unique ticket number scoped to the company."""
        for _ in range(10):
            number_val = random.randint(1000, 99999)
            candidate = f"TICKET-{number_val}"

            stmt = select(func.count()).select_from(HelpdeskTicket).where(
                and_(
                    HelpdeskTicket.company_id == company_id,
                    HelpdeskTicket.ticket_number == candidate,
                )
            )
            count = (await self.db.execute(stmt)).scalar() or 0
            if count == 0:
                return candidate

        # Fallback with timestamp suffix
        return f"TICKET-{int(datetime.now().timestamp()) % 100000}"

    # =======================================================================
    # My Tickets (Requester View)
    # =======================================================================

    async def get_my_tickets(
        self,
        company_id: uuid.UUID,
        requester_id: uuid.UUID,
        status_filter: str | None = None,
        category: str | None = None,
        search: str | None = None,
        page: int = 1,
        limit: int = 20,
    ) -> tuple[Sequence[HelpdeskTicket], int]:
        """Fetch tickets created by the authenticated user with filtering and pagination."""
        query = (
            select(HelpdeskTicket)
            .where(
                and_(
                    HelpdeskTicket.company_id == company_id,
                    HelpdeskTicket.requester_id == requester_id,
                )
            )
            .options(
                selectinload(HelpdeskTicket.requester),
                selectinload(HelpdeskTicket.assigned_to),
                selectinload(HelpdeskTicket.attachments),
                selectinload(HelpdeskTicket.comments),
            )
        )

        if status_filter and status_filter.upper() != "ALL":
            query = query.where(func.lower(HelpdeskTicket.status) == status_filter.lower().strip())

        if category and category.upper() != "ALL":
            query = query.where(func.lower(HelpdeskTicket.category) == category.lower().strip())

        if search:
            search_pattern = f"%{search.strip()}%"
            query = query.where(
                or_(
                    HelpdeskTicket.ticket_number.ilike(search_pattern),
                    HelpdeskTicket.subject.ilike(search_pattern),
                    HelpdeskTicket.description.ilike(search_pattern),
                )
            )

        # Count total
        count_stmt = select(func.count()).select_from(query.order_by(None).subquery())
        total = (await self.db.execute(count_stmt)).scalar() or 0

        # Paginate
        offset = (page - 1) * limit
        query = query.order_by(desc(HelpdeskTicket.created_at)).offset(offset).limit(limit)

        result = await self.db.execute(query)
        tickets = result.scalars().all()
        return tickets, total

    # =======================================================================
    # Create Ticket
    # =======================================================================

    async def create_ticket(
        self,
        company_id: uuid.UUID,
        requester_id: uuid.UUID,
        category: str,
        priority: str,
        subject: str,
        description: str,
        attachment_ids: list[uuid.UUID] | None = None,
        department: str | None = None,
    ) -> HelpdeskTicket:
        """Create a new support ticket and link any pre-uploaded attachments."""
        ticket_number = await self.generate_unique_ticket_number(company_id)
        first_resp_due, res_due = HelpdeskSLAService.calculate_sla_deadlines(priority)

        ticket = HelpdeskTicket(
            id=uuid.uuid4(),
            company_id=company_id,
            ticket_number=ticket_number,
            requester_id=requester_id,
            category=category,
            priority=priority,
            status="Open",
            subject=subject,
            description=description,
            department=department,
            sla_first_response_due_at=first_resp_due,
            sla_resolution_due_at=res_due,
        )
        self.db.add(ticket)
        await self.db.flush()

        # Link attachments
        if attachment_ids:
            link_stmt = (
                update(HelpdeskAttachment)
                .where(
                    and_(
                        HelpdeskAttachment.id.in_(attachment_ids),
                        HelpdeskAttachment.company_id == company_id,
                    )
                )
                .values(ticket_id=ticket.id)
            )
            await self.db.execute(link_stmt)

        await self.db.commit()

        # Reload with relationships
        return await self.get_ticket_by_id(ticket.id, company_id) or ticket

    # =======================================================================
    # Ticket Details
    # =======================================================================

    async def get_ticket_by_id(
        self,
        ticket_id: uuid.UUID,
        company_id: uuid.UUID,
    ) -> HelpdeskTicket | None:
        """Fetch single ticket by ID strictly scoped to company."""
        stmt = (
            select(HelpdeskTicket)
            .where(
                and_(
                    HelpdeskTicket.id == ticket_id,
                    HelpdeskTicket.company_id == company_id,
                )
            )
            .options(
                selectinload(HelpdeskTicket.requester),
                selectinload(HelpdeskTicket.assigned_to),
                selectinload(HelpdeskTicket.attachments),
                selectinload(HelpdeskTicket.comments),
                selectinload(HelpdeskTicket.internal_notes),
            )
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    # =======================================================================
    # Comments & Discussion
    # =======================================================================

    async def get_ticket_comments(
        self,
        ticket_id: uuid.UUID,
        company_id: uuid.UUID,
    ) -> Sequence[HelpdeskComment]:
        """Fetch chronological discussion comments for a ticket."""
        stmt = (
            select(HelpdeskComment)
            .join(HelpdeskTicket, HelpdeskComment.ticket_id == HelpdeskTicket.id)
            .where(
                and_(
                    HelpdeskComment.ticket_id == ticket_id,
                    HelpdeskTicket.company_id == company_id,
                )
            )
            .options(
                selectinload(HelpdeskComment.author),
                selectinload(HelpdeskComment.attachments),
            )
            .order_by(HelpdeskComment.created_at.asc())
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def add_comment(
        self,
        ticket: HelpdeskTicket,
        author_id: uuid.UUID,
        message: str,
        attachment_ids: list[uuid.UUID] | None = None,
        is_staff: bool = False,
    ) -> HelpdeskComment:
        """Add a comment to a ticket, update SLA tracking, and link attachments."""
        comment = HelpdeskComment(
            id=uuid.uuid4(),
            ticket_id=ticket.id,
            author_id=author_id,
            message=message,
        )
        self.db.add(comment)
        await self.db.flush()

        # Update first response if staff and not yet recorded
        if is_staff and ticket.first_responded_at is None:
            ticket.first_responded_at = datetime.now(timezone.utc)

        ticket.updated_at = datetime.now(timezone.utc)

        # Link attachments
        if attachment_ids:
            link_stmt = (
                update(HelpdeskAttachment)
                .where(
                    and_(
                        HelpdeskAttachment.id.in_(attachment_ids),
                        HelpdeskAttachment.company_id == ticket.company_id,
                    )
                )
                .values(comment_id=comment.id, ticket_id=ticket.id)
            )
            await self.db.execute(link_stmt)

        await self.db.commit()

        # Eager reload
        stmt = (
            select(HelpdeskComment)
            .where(HelpdeskComment.id == comment.id)
            .options(
                selectinload(HelpdeskComment.author),
                selectinload(HelpdeskComment.attachments),
            )
        )
        res = await self.db.execute(stmt)
        return res.scalar_one()

    # =======================================================================
    # Internal Notes (Staff Only)
    # =======================================================================

    async def add_internal_note(
        self,
        ticket: HelpdeskTicket,
        author_id: uuid.UUID,
        note_text: str,
    ) -> HelpdeskInternalNote:
        """Add internal note for staff collaboration."""
        note = HelpdeskInternalNote(
            id=uuid.uuid4(),
            ticket_id=ticket.id,
            author_id=author_id,
            note=note_text,
        )
        self.db.add(note)
        ticket.updated_at = datetime.now(timezone.utc)
        await self.db.commit()

        stmt = (
            select(HelpdeskInternalNote)
            .where(HelpdeskInternalNote.id == note.id)
            .options(selectinload(HelpdeskInternalNote.author))
        )
        res = await self.db.execute(stmt)
        return res.scalar_one()

    async def get_internal_notes(
        self,
        ticket_id: uuid.UUID,
        company_id: uuid.UUID,
    ) -> Sequence[HelpdeskInternalNote]:
        """Fetch all internal notes for a ticket."""
        stmt = (
            select(HelpdeskInternalNote)
            .join(HelpdeskTicket, HelpdeskInternalNote.ticket_id == HelpdeskTicket.id)
            .where(
                and_(
                    HelpdeskInternalNote.ticket_id == ticket_id,
                    HelpdeskTicket.company_id == company_id,
                )
            )
            .options(selectinload(HelpdeskInternalNote.author))
            .order_by(HelpdeskInternalNote.created_at.asc())
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()

    # =======================================================================
    # Attachments
    # =======================================================================

    async def create_attachment(
        self,
        company_id: uuid.UUID,
        uploader_id: uuid.UUID,
        name: str,
        size: int,
        type_: str,
        url: str,
        file_path: str | None = None,
        ticket_id: uuid.UUID | None = None,
        comment_id: uuid.UUID | None = None,
    ) -> HelpdeskAttachment:
        """Save an uploaded attachment record."""
        att = HelpdeskAttachment(
            id=uuid.uuid4(),
            company_id=company_id,
            uploader_id=uploader_id,
            ticket_id=ticket_id,
            comment_id=comment_id,
            name=name,
            size=size,
            type=type_,
            url=url,
            file_path=file_path,
        )
        self.db.add(att)
        await self.db.commit()
        await self.db.refresh(att)
        return att

    # =======================================================================
    # Admin Tickets View
    # =======================================================================

    async def get_all_admin_tickets(
        self,
        company_id: uuid.UUID,
        status_filter: str | None = None,
        category: str | None = None,
        priority: str | None = None,
        assigned_to: str | None = None,
        is_sla_breached: bool | None = None,
        search: str | None = None,
        scoped_requester_ids: list[uuid.UUID] | None = None,
        page: int = 1,
        limit: int = 30,
    ) -> tuple[Sequence[HelpdeskTicket], dict[str, int]]:
        """Fetch all tickets across company for admins/managers with status counts."""
        base_filters = [HelpdeskTicket.company_id == company_id]

        if scoped_requester_ids is not None:
            # Hierarchy restriction for managers
            base_filters.append(HelpdeskTicket.requester_id.in_(scoped_requester_ids))

        # 1. Fetch Aggregated Status Counts
        counts_query = select(
            func.count().label("total"),
            func.count(case((func.lower(HelpdeskTicket.status) == "open", 1))).label("open_count"),
            func.count(case((func.lower(HelpdeskTicket.status) == "in progress", 1))).label("in_progress_count"),
            func.count(case((func.lower(HelpdeskTicket.status) == "resolved", 1))).label("resolved_count"),
        ).where(and_(*base_filters))

        counts_res = (await self.db.execute(counts_query)).one()
        counts_dict = {
            "total": counts_res.total or 0,
            "openCount": counts_res.open_count or 0,
            "inProgressCount": counts_res.in_progress_count or 0,
            "resolvedCount": counts_res.resolved_count or 0,
        }

        # 2. Build Filtered Query
        query_filters = list(base_filters)

        if status_filter and status_filter.upper() != "ALL":
            query_filters.append(func.lower(HelpdeskTicket.status) == status_filter.lower().strip())

        if category and category.upper() != "ALL":
            query_filters.append(func.lower(HelpdeskTicket.category) == category.lower().strip())

        if priority and priority.upper() != "ALL":
            query_filters.append(func.lower(HelpdeskTicket.priority) == priority.lower().strip())

        if assigned_to:
            if assigned_to.lower() == "unassigned":
                query_filters.append(HelpdeskTicket.assigned_to_id.is_(None))
            else:
                try:
                    assigned_uuid = uuid.UUID(assigned_to)
                    query_filters.append(HelpdeskTicket.assigned_to_id == assigned_uuid)
                except ValueError:
                    pass

        if is_sla_breached is not None:
            now_dt = datetime.now(timezone.utc)
            if is_sla_breached:
                query_filters.append(
                    and_(
                        func.lower(HelpdeskTicket.status).notin_(["resolved", "closed"]),
                        HelpdeskTicket.sla_resolution_due_at < now_dt,
                    )
                )
            else:
                query_filters.append(
                    or_(
                        func.lower(HelpdeskTicket.status).in_(["resolved", "closed"]),
                        HelpdeskTicket.sla_resolution_due_at >= now_dt,
                        HelpdeskTicket.sla_resolution_due_at.is_(None),
                    )
                )

        if search:
            search_pattern = f"%{search.strip()}%"
            query_filters.append(
                or_(
                    HelpdeskTicket.ticket_number.ilike(search_pattern),
                    HelpdeskTicket.subject.ilike(search_pattern),
                    HelpdeskTicket.description.ilike(search_pattern),
                )
            )

        main_query = (
            select(HelpdeskTicket)
            .where(and_(*query_filters))
            .options(
                selectinload(HelpdeskTicket.requester),
                selectinload(HelpdeskTicket.assigned_to),
                selectinload(HelpdeskTicket.attachments),
                selectinload(HelpdeskTicket.comments),
            )
        )

        # Count filtered total
        filtered_count_stmt = select(func.count()).select_from(main_query.order_by(None).subquery())
        filtered_total = (await self.db.execute(filtered_count_stmt)).scalar() or 0
        counts_dict["filteredTotal"] = filtered_total

        # Paginate
        offset = (page - 1) * limit
        main_query = main_query.order_by(desc(HelpdeskTicket.created_at)).offset(offset).limit(limit)

        items_res = await self.db.execute(main_query)
        items = items_res.scalars().all()
        return items, counts_dict

    # =======================================================================
    # Ticket Status & Assignment
    # =======================================================================

    async def update_ticket_status(
        self,
        ticket: HelpdeskTicket,
        new_status: str,
        resolution_notes: str | None = None,
    ) -> HelpdeskTicket:
        """Update ticket status and update timestamps accordingly."""
        ticket.status = new_status
        now = datetime.now(timezone.utc)
        status_lower = new_status.lower().strip()

        if status_lower == "resolved":
            ticket.resolved_at = now
            if resolution_notes:
                ticket.resolution_notes = resolution_notes
        elif status_lower == "closed":
            ticket.closed_at = now
        elif status_lower == "reopened":
            ticket.resolved_at = None
            ticket.closed_at = None
            ticket.status = "Reopened"

        ticket.updated_at = now
        await self.db.commit()
        await self.db.refresh(ticket)
        return ticket

    async def assign_ticket_agent(
        self,
        ticket: HelpdeskTicket,
        agent_id: uuid.UUID,
        department: str | None = None,
    ) -> HelpdeskTicket:
        """Assign agent and update department for ticket."""
        ticket.assigned_to_id = agent_id
        if department:
            ticket.department = department
        ticket.updated_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(ticket)
        return ticket

    # =======================================================================
    # FAQs
    # =======================================================================

    async def get_faqs(
        self,
        company_id: uuid.UUID,
        category: str | None = None,
        search: str | None = None,
        public_only: bool = True,
    ) -> Sequence[HelpdeskFAQ]:
        """Fetch FAQs for company with search and category filtering."""
        query = select(HelpdeskFAQ).where(HelpdeskFAQ.company_id == company_id)

        if public_only:
            query = query.where(HelpdeskFAQ.is_public.is_(True))

        if category and category.lower() != "all":
            query = query.where(func.lower(HelpdeskFAQ.category) == category.lower().strip())

        if search:
            search_pattern = f"%{search.strip()}%"
            query = query.where(
                or_(
                    HelpdeskFAQ.question.ilike(search_pattern),
                    HelpdeskFAQ.answer.ilike(search_pattern),
                    HelpdeskFAQ.category.ilike(search_pattern),
                )
            )

        query = query.order_by(HelpdeskFAQ.category.asc(), HelpdeskFAQ.view_count.desc())
        res = await self.db.execute(query)
        return res.scalars().all()

    async def upsert_faq(
        self,
        company_id: uuid.UUID,
        category: str,
        question: str,
        answer: str,
        is_public: bool = True,
        faq_id: uuid.UUID | None = None,
        created_by: uuid.UUID | None = None,
    ) -> HelpdeskFAQ:
        """Create or update FAQ."""
        if faq_id:
            stmt = select(HelpdeskFAQ).where(
                and_(
                    HelpdeskFAQ.id == faq_id,
                    HelpdeskFAQ.company_id == company_id,
                )
            )
            faq = (await self.db.execute(stmt)).scalar_one_or_none()
            if faq:
                faq.category = category
                faq.question = question
                faq.answer = answer
                faq.is_public = is_public
                faq.updated_at = datetime.now(timezone.utc)
                await self.db.commit()
                await self.db.refresh(faq)
                return faq

        faq = HelpdeskFAQ(
            id=uuid.uuid4(),
            company_id=company_id,
            category=category,
            question=question,
            answer=answer,
            is_public=is_public,
            created_by=created_by,
        )
        self.db.add(faq)
        await self.db.commit()
        await self.db.refresh(faq)
        return faq

    # =======================================================================
    # SLA Metrics Calculation
    # =======================================================================

    async def calculate_sla_metrics(self, company_id: uuid.UUID) -> dict[str, Any]:
        """Calculate SLA metrics and KPIs from actual database records."""
        # 1. Total and status counts
        total_stmt = select(func.count()).select_from(HelpdeskTicket).where(HelpdeskTicket.company_id == company_id)
        total_tickets = (await self.db.execute(total_stmt)).scalar() or 0

        resolved_stmt = (
            select(func.count())
            .select_from(HelpdeskTicket)
            .where(
                and_(
                    HelpdeskTicket.company_id == company_id,
                    func.lower(HelpdeskTicket.status).in_(["resolved", "closed"]),
                )
            )
        )
        resolved_tickets = (await self.db.execute(resolved_stmt)).scalar() or 0

        # 2. SLA Compliance Rate: % of resolved tickets where resolved_at <= sla_resolution_due_at
        compliant_stmt = (
            select(func.count())
            .select_from(HelpdeskTicket)
            .where(
                and_(
                    HelpdeskTicket.company_id == company_id,
                    HelpdeskTicket.resolved_at.is_not(None),
                    HelpdeskTicket.sla_resolution_due_at.is_not(None),
                    HelpdeskTicket.resolved_at <= HelpdeskTicket.sla_resolution_due_at,
                )
            )
        )
        compliant_count = (await self.db.execute(compliant_stmt)).scalar() or 0
        sla_compliance_rate = round((compliant_count / resolved_tickets * 100.0), 1) if resolved_tickets > 0 else 100.0

        # 3. Average First Response Hours
        first_resp_query = select(
            func.avg(
                func.extract("epoch", HelpdeskTicket.first_responded_at - HelpdeskTicket.created_at) / 3600.0
            )
        ).where(
            and_(
                HelpdeskTicket.company_id == company_id,
                HelpdeskTicket.first_responded_at.is_not(None),
            )
        )
        avg_resp_seconds = (await self.db.execute(first_resp_query)).scalar()
        average_first_response_hours = round(float(avg_resp_seconds), 1) if avg_resp_seconds is not None else 0.0

        # 4. Average Resolution Hours
        res_hours_query = select(
            func.avg(
                func.extract("epoch", HelpdeskTicket.resolved_at - HelpdeskTicket.created_at) / 3600.0
            )
        ).where(
            and_(
                HelpdeskTicket.company_id == company_id,
                HelpdeskTicket.resolved_at.is_not(None),
            )
        )
        avg_res_seconds = (await self.db.execute(res_hours_query)).scalar()
        average_resolution_hours = round(float(avg_res_seconds), 1) if avg_res_seconds is not None else 0.0

        # 5. Category Breakdown
        cat_stmt = (
            select(HelpdeskTicket.category, func.count())
            .where(HelpdeskTicket.company_id == company_id)
            .group_by(HelpdeskTicket.category)
        )
        cat_rows = (await self.db.execute(cat_stmt)).all()
        category_breakdown = {row[0]: row[1] for row in cat_rows}

        # 6. Urgent Open Count
        urgent_stmt = (
            select(func.count())
            .select_from(HelpdeskTicket)
            .where(
                and_(
                    HelpdeskTicket.company_id == company_id,
                    func.lower(HelpdeskTicket.priority) == "urgent",
                    func.lower(HelpdeskTicket.status).notin_(["resolved", "closed"]),
                )
            )
        )
        urgent_open_count = (await self.db.execute(urgent_stmt)).scalar() or 0

        return {
            "totalTickets": total_tickets,
            "resolvedTickets": resolved_tickets,
            "slaComplianceRate": sla_compliance_rate,
            "averageFirstResponseHours": average_first_response_hours,
            "averageResolutionHours": average_resolution_hours,
            "categoryBreakdown": category_breakdown,
            "urgentOpenCount": urgent_open_count,
        }
