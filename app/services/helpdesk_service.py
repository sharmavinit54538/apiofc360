"""Business logic and RBAC service for OFC360 Helpdesk & Support."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
import math
import os
import re
from typing import Any, Sequence
import uuid

from fastapi import UploadFile, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import (
    AppException,
    ForbiddenException,
    NotFoundException,
    ValidationException,
)
from app.llm.client import get_llm_client
from app.models.employee import Employee
from app.models.helpdesk import (
    HelpdeskAttachment,
    HelpdeskComment,
    HelpdeskFAQ,
    HelpdeskInternalNote,
    HelpdeskTicket,
)
from app.models.user import User
from app.models.user.role import UserRole
from app.repositories.helpdesk_repository import HelpdeskRepository
from app.schemas.helpdesk import (
    AdminTicketsMeta,
    AdminTicketsResponse,
    AIChatResponse,
    AttachmentResponse,
    CommentResponse,
    FAQResponse,
    HelpdeskSLAMetricsResponse,
    HelpdeskUserSummary,
    InternalNoteResponse,
    MyTicketsResponse,
    PaginationMeta,
    TicketResponse,
)
from app.services.email_service import send_email
from app.services.helpdesk_sla_service import HelpdeskSLAService
from app.services.storage_service import StorageService

logger = logging.getLogger(__name__)

# Valid ticket status transitions
ALLOWED_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "open": {"in progress", "resolved", "closed"},
    "in progress": {"resolved", "open", "closed"},
    "resolved": {"closed", "reopened", "in progress"},
    "closed": {"reopened"},
    "reopened": {"in progress", "resolved", "closed", "open"},
}

ALLOWED_ATTACHMENT_EXTENSIONS = {
    ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp",
    ".doc", ".docx", ".xls", ".xlsx", ".txt", ".csv", ".zip",
}


class HelpdeskService:
    """Service encapsulating Helpdesk business logic, RBAC, SLA, storage, and AI interactions."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = HelpdeskRepository(db)
        self.storage = StorageService(target_dir=os.path.join(settings.UPLOAD_DIR, "helpdesk"))

    # =======================================================================
    # Helpers & Formatters
    # =======================================================================

    def _get_user_role_str(self, user: User) -> str:
        """Extract canonical role string from user."""
        if hasattr(user.role, "value"):
            return str(user.role.value).lower()
        return str(user.role or "").lower()

    def _is_staff(self, user: User) -> bool:
        """Check if user is staff (hr_admin, it_admin, manager, super_admin, executive)."""
        role = self._get_user_role_str(user)
        return role in ("hr_admin", "it_admin", "manager", "super_admin", "executive")

    def _format_user_summary(self, user: User | None) -> HelpdeskUserSummary | None:
        """Format User model to schema."""
        if not user:
            return None
        return HelpdeskUserSummary(
            id=user.id,
            name=user.name or f"{user.first_name or ''} {user.last_name or ''}".strip() or user.email,
            email=user.email,
            role=self._get_user_role_str(user),
            avatar_url=getattr(user, "profile_photo", None) or getattr(user, "avatar_url", None),
            department=getattr(user, "department", None),
        )

    def _format_attachment(self, att: HelpdeskAttachment) -> AttachmentResponse:
        """Format attachment model to schema."""
        return AttachmentResponse(
            id=att.id,
            name=att.name,
            size=att.size,
            type=att.type,
            url=att.url,
            created_at=att.created_at,
        )

    def _format_ticket(self, ticket: HelpdeskTicket) -> TicketResponse:
        """Format ticket model to schema with dynamic SLA breach computation."""
        is_breached = HelpdeskSLAService.check_is_breached(
            status=ticket.status,
            sla_resolution_due_at=ticket.sla_resolution_due_at,
            sla_first_response_due_at=ticket.sla_first_response_due_at,
            first_responded_at=ticket.first_responded_at,
            resolved_at=ticket.resolved_at,
        )

        attachments = [self._format_attachment(a) for a in (ticket.attachments or []) if a.comment_id is None]
        comments_count = len(ticket.comments) if ticket.comments is not None else 0

        return TicketResponse(
            id=ticket.id,
            ticketNumber=ticket.ticket_number,
            requester=self._format_user_summary(ticket.requester) or HelpdeskUserSummary(
                id=ticket.requester_id, name="User", email="", role="employee"
            ),
            assignedTo=self._format_user_summary(ticket.assigned_to),
            department=ticket.department,
            category=ticket.category,
            priority=ticket.priority,
            status=ticket.status,
            subject=ticket.subject,
            description=ticket.description,
            resolutionNotes=ticket.resolution_notes,
            isSlaBreached=is_breached,
            slaFirstResponseDueAt=ticket.sla_first_response_due_at,
            slaResolutionDueAt=ticket.sla_resolution_due_at,
            firstRespondedAt=ticket.first_responded_at,
            resolvedAt=ticket.resolved_at,
            closedAt=ticket.closed_at,
            attachments=attachments,
            commentsCount=comments_count,
            createdAt=ticket.created_at,
            updatedAt=ticket.updated_at,
        )

    async def _get_manager_team_ids(self, manager_user: User) -> list[uuid.UUID]:
        """Resolve all employee user IDs that report directly to this manager."""
        # Find employee profile of manager
        emp_stmt = select(Employee.id).where(Employee.user_id == manager_user.id)
        mgr_emp_id = (await self.db.execute(emp_stmt)).scalar_one_or_none()

        if not mgr_emp_id:
            return [manager_user.id]

        report_stmt = select(Employee.user_id).where(
            and_(
                Employee.manager_id == mgr_emp_id,
                Employee.user_id.is_not(None),
                Employee.is_deleted.is_(False),
            )
        )
        reports = (await self.db.execute(report_stmt)).scalars().all()
        team_ids = [uid for uid in reports if uid is not None]
        team_ids.append(manager_user.id)
        return team_ids

    # =======================================================================
    # 1. getMySupportTickets
    # =======================================================================

    async def get_my_tickets(
        self,
        user: User,
        company_id: uuid.UUID,
        status_filter: str | None = None,
        category: str | None = None,
        search: str | None = None,
        page: int = 1,
        limit: int = 20,
    ) -> MyTicketsResponse:
        """Fetch tickets created by current user."""
        tickets, total = await self.repo.get_my_tickets(
            company_id=company_id,
            requester_id=user.id,
            status_filter=status_filter,
            category=category,
            search=search,
            page=page,
            limit=limit,
        )
        total_pages = math.ceil(total / limit) if limit > 0 else 1
        items = [self._format_ticket(t) for t in tickets]

        return MyTicketsResponse(
            items=items,
            meta=PaginationMeta(
                total=total,
                page=page,
                limit=limit,
                totalPages=total_pages,
            ),
        )

    # =======================================================================
    # 2. createSupportTicket
    # =======================================================================

    async def create_ticket(
        self,
        user: User,
        company_id: uuid.UUID,
        category: str,
        priority: str,
        subject: str,
        description: str,
        attachment_ids: list[uuid.UUID] | None = None,
    ) -> TicketResponse:
        """Create a new support ticket with calculated SLA deadlines."""
        if not category or not category.strip():
            raise ValidationException(message="Category is required.")
        if not subject or not subject.strip():
            raise ValidationException(message="Subject is required.")
        if not description or not description.strip():
            raise ValidationException(message="Description is required.")

        ticket = await self.repo.create_ticket(
            company_id=company_id,
            requester_id=user.id,
            category=category.strip(),
            priority=priority.strip().title(),
            subject=subject.strip(),
            description=description.strip(),
            attachment_ids=attachment_ids,
        )

        logger.info("Created support ticket %s (%s) for user %s", ticket.ticket_number, ticket.id, user.id)
        return self._format_ticket(ticket)

    # =======================================================================
    # 3. getTicketById
    # =======================================================================

    async def get_ticket_by_id(
        self,
        ticket_id: uuid.UUID,
        user: User,
        company_id: uuid.UUID,
    ) -> TicketResponse:
        """Fetch ticket by ID with strict IDOR and authorization checks."""
        ticket = await self.repo.get_ticket_by_id(ticket_id, company_id)
        if not ticket:
            raise NotFoundException(message=f"Ticket '{ticket_id}' not found.")

        # RBAC Check
        role = self._get_user_role_str(user)
        if role == "employee":
            if ticket.requester_id != user.id:
                raise ForbiddenException(message="Access denied to this ticket.")
        elif role == "manager":
            if ticket.requester_id != user.id and ticket.assigned_to_id != user.id:
                team_ids = await self._get_manager_team_ids(user)
                if ticket.requester_id not in team_ids:
                    raise ForbiddenException(message="Access denied to this team ticket.")

        return self._format_ticket(ticket)

    # =======================================================================
    # 4. getTicketComments
    # =======================================================================

    async def get_ticket_comments(
        self,
        ticket_id: uuid.UUID,
        user: User,
        company_id: uuid.UUID,
    ) -> list[CommentResponse]:
        """Fetch discussion comments on ticket. Internal notes are excluded for regular employees."""
        # Verify access first
        await self.get_ticket_by_id(ticket_id, user, company_id)

        comments = await self.repo.get_ticket_comments(ticket_id, company_id)
        result = []
        for c in comments:
            author_role = self._get_user_role_str(c.author)
            is_agent = author_role in ("hr_admin", "it_admin", "manager", "super_admin")
            att_list = [self._format_attachment(a) for a in (c.attachments or [])]

            result.append(
                CommentResponse(
                    id=c.id,
                    ticketId=c.ticket_id,
                    author=self._format_user_summary(c.author) or HelpdeskUserSummary(
                        id=c.author_id, name="User", email="", role="employee"
                    ),
                    message=c.message,
                    isAgent=is_agent,
                    isInternalNote=False,
                    attachments=att_list,
                    createdAt=c.created_at,
                )
            )

        return result

    # =======================================================================
    # 5. addTicketComment
    # =======================================================================

    async def add_comment(
        self,
        ticket_id: uuid.UUID,
        user: User,
        company_id: uuid.UUID,
        message: str,
        attachments: list[uuid.UUID] | None = None,
    ) -> CommentResponse:
        """Add a comment to ticket discussion."""
        if not message or not message.strip():
            raise ValidationException(message="Comment message cannot be empty.")

        ticket = await self.repo.get_ticket_by_id(ticket_id, company_id)
        if not ticket:
            raise NotFoundException(message=f"Ticket '{ticket_id}' not found.")

        # Check access
        role = self._get_user_role_str(user)
        if role == "employee" and ticket.requester_id != user.id:
            raise ForbiddenException(message="Access denied to this ticket.")
        elif role == "manager":
            if ticket.requester_id != user.id and ticket.assigned_to_id != user.id:
                team_ids = await self._get_manager_team_ids(user)
                if ticket.requester_id not in team_ids:
                    raise ForbiddenException(message="Access denied to this ticket.")

        if ticket.status.lower() == "closed":
            raise ValidationException(message="Cannot reply to a closed ticket. Please reopen the ticket first.")

        is_staff = self._is_staff(user)
        comment = await self.repo.add_comment(
            ticket=ticket,
            author_id=user.id,
            message=message.strip(),
            attachment_ids=attachments,
            is_staff=is_staff,
        )

        # Notify counterpart
        if is_staff and ticket.requester and ticket.requester.email:
            try:
                asyncio.create_task(
                    send_email(
                        to=[ticket.requester.email],
                        subject=f"New comment on ticket {ticket.ticket_number}: {ticket.subject}",
                        body=f"Hi {ticket.requester.name or 'there'},\n\nA support agent commented on your ticket:\n\n\"{message}\"\n\nLog in to OFC360 to view the full discussion.",
                    )
                )
            except Exception as e:
                logger.warning("Failed to dispatch comment notification: %s", e)

        author_role = self._get_user_role_str(comment.author)
        return CommentResponse(
            id=comment.id,
            ticketId=comment.ticket_id,
            author=self._format_user_summary(comment.author) or HelpdeskUserSummary(
                id=comment.author_id, name="User", email="", role="employee"
            ),
            message=comment.message,
            isAgent=author_role in ("hr_admin", "it_admin", "manager", "super_admin"),
            isInternalNote=False,
            attachments=[self._format_attachment(a) for a in (comment.attachments or [])],
            createdAt=comment.created_at,
        )

    # =======================================================================
    # 6. uploadTicketAttachment
    # =======================================================================

    async def upload_attachment(
        self,
        user: User,
        company_id: uuid.UUID,
        file: UploadFile,
    ) -> AttachmentResponse:
        """Upload file attachment with security and size validation."""
        filename = file.filename or "attachment"
        clean_filename = os.path.basename(filename)

        # Path traversal guard
        if ".." in filename or "/" in filename or "\\" in filename:
            clean_filename = re.sub(r"[^a-zA-Z0-9_.-]", "_", clean_filename)

        ext = os.path.splitext(clean_filename)[1].lower()
        if ext not in ALLOWED_ATTACHMENT_EXTENSIONS:
            raise ValidationException(
                message=f"File extension '{ext}' is not supported. Supported: PDF, Images, Word, Excel, CSV, Text, ZIP."
            )

        content = await file.read()
        file_size = len(content)

        if file_size == 0:
            raise ValidationException(message="Uploaded file is empty.")

        max_bytes = 10 * 1024 * 1024  # 10MB
        if file_size > max_bytes:
            raise AppException(
                message="File size exceeds maximum allowed limit of 10MB.",
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )

        # Save to disk
        target_dir = os.path.join(settings.UPLOAD_DIR, "helpdesk")
        os.makedirs(target_dir, exist_ok=True)
        unique_name = f"hd_{uuid.uuid4().hex}{ext}"
        full_path = os.path.join(target_dir, unique_name)

        with open(full_path, "wb") as f:
            f.write(content)

        file_url = f"/uploads/helpdesk/{unique_name}"
        mime_type = file.content_type or "application/octet-stream"

        att = await self.repo.create_attachment(
            company_id=company_id,
            uploader_id=user.id,
            name=clean_filename,
            size=file_size,
            type_=mime_type,
            url=file_url,
            file_path=full_path,
        )

        return self._format_attachment(att)

    # =======================================================================
    # 7. getAllHelpdeskTickets (Admin)
    # =======================================================================

    async def get_all_admin_tickets(
        self,
        user: User,
        company_id: uuid.UUID,
        status_filter: str | None = None,
        category: str | None = None,
        priority: str | None = None,
        assigned_to: str | None = None,
        is_sla_breached: bool | None = None,
        search: str | None = None,
        page: int = 1,
        limit: int = 30,
    ) -> AdminTicketsResponse:
        """Fetch all tickets across company for admins, or team tickets for managers."""
        role = self._get_user_role_str(user)
        if role not in ("hr_admin", "it_admin", "manager", "super_admin", "executive"):
            raise ForbiddenException(message="Only administrators and managers can access all helpdesk tickets.")

        scoped_requester_ids = None
        if role == "manager":
            scoped_requester_ids = await self._get_manager_team_ids(user)

        tickets, counts = await self.repo.get_all_admin_tickets(
            company_id=company_id,
            status_filter=status_filter,
            category=category,
            priority=priority,
            assigned_to=assigned_to,
            is_sla_breached=is_sla_breached,
            search=search,
            scoped_requester_ids=scoped_requester_ids,
            page=page,
            limit=limit,
        )

        total = counts.get("filteredTotal", counts.get("total", 0))
        total_pages = math.ceil(total / limit) if limit > 0 else 1
        items = [self._format_ticket(t) for t in tickets]

        return AdminTicketsResponse(
            items=items,
            meta=AdminTicketsMeta(
                total=counts.get("total", 0),
                openCount=counts.get("openCount", 0),
                inProgressCount=counts.get("inProgressCount", 0),
                resolvedCount=counts.get("resolvedCount", 0),
                page=page,
                limit=limit,
                totalPages=total_pages,
            ),
        )

    # =======================================================================
    # 8. updateTicketStatus
    # =======================================================================

    async def update_ticket_status(
        self,
        ticket_id: uuid.UUID,
        user: User,
        company_id: uuid.UUID,
        new_status: str,
        resolution_notes: str | None = None,
    ) -> TicketResponse:
        """Update ticket status with transition validation."""
        ticket = await self.repo.get_ticket_by_id(ticket_id, company_id)
        if not ticket:
            raise NotFoundException(message=f"Ticket '{ticket_id}' not found.")

        current_status_lower = ticket.status.lower().strip()
        new_status_lower = new_status.lower().strip()

        # Validate allowed roles: staff or requester reopening/closing
        role = self._get_user_role_str(user)
        is_staff = self._is_staff(user)
        is_requester = ticket.requester_id == user.id

        if not is_staff and not is_requester:
            raise ForbiddenException(message="You do not have permission to update this ticket's status.")

        if not is_staff and is_requester:
            if new_status_lower not in ("closed", "reopened"):
                raise ForbiddenException(message="Requesters can only close or reopen their tickets.")

        # Check transition rule
        if current_status_lower != new_status_lower:
            allowed_next = ALLOWED_STATUS_TRANSITIONS.get(current_status_lower, set())
            if new_status_lower not in allowed_next:
                raise ValidationException(
                    message=f"Cannot transition ticket from '{ticket.status}' to '{new_status}'. Allowed transitions: {', '.join(allowed_next).title()}."
                )

        canonical_status_map = {
            "open": "Open",
            "in progress": "In Progress",
            "resolved": "Resolved",
            "closed": "Closed",
            "reopened": "Reopened",
        }
        canonical_status = canonical_status_map.get(new_status_lower, new_status.title())

        updated_ticket = await self.repo.update_ticket_status(
            ticket=ticket,
            new_status=canonical_status,
            resolution_notes=resolution_notes,
        )

        logger.info("Ticket %s status updated to %s by user %s", ticket.ticket_number, canonical_status, user.id)
        return self._format_ticket(updated_ticket)

    # =======================================================================
    # 9. assignTicketAgent
    # =======================================================================

    async def assign_ticket_agent(
        self,
        ticket_id: uuid.UUID,
        user: User,
        company_id: uuid.UUID,
        assigned_to_user_id: uuid.UUID,
        department: str | None = None,
    ) -> TicketResponse:
        """Assign support agent to ticket."""
        role = self._get_user_role_str(user)
        if role not in ("hr_admin", "it_admin", "manager", "super_admin"):
            raise ForbiddenException(message="Only administrators and managers can assign tickets.")

        ticket = await self.repo.get_ticket_by_id(ticket_id, company_id)
        if not ticket:
            raise NotFoundException(message=f"Ticket '{ticket_id}' not found.")

        # Validate target user belongs to same company
        target_stmt = select(User).where(
            and_(
                User.id == assigned_to_user_id,
                User.company_id == company_id,
            )
        )
        target_user = (await self.db.execute(target_stmt)).scalar_one_or_none()
        if not target_user:
            raise NotFoundException(message="Assigned agent user not found in this company.")

        updated_ticket = await self.repo.assign_ticket_agent(
            ticket=ticket,
            agent_id=target_user.id,
            department=department,
        )

        # Notify assigned agent
        if target_user.email:
            try:
                asyncio.create_task(
                    send_email(
                        to=[target_user.email],
                        subject=f"Ticket assigned to you: {ticket.ticket_number} - {ticket.subject}",
                        body=f"Hi {target_user.name or 'there'},\n\nYou have been assigned ticket {ticket.ticket_number} ({ticket.priority} priority).\nSubject: {ticket.subject}\n\nPlease review and action accordingly.",
                    )
                )
            except Exception as e:
                logger.warning("Failed to dispatch assignment email: %s", e)

        return self._format_ticket(updated_ticket)

    # =======================================================================
    # 10. addInternalTicketNote
    # =======================================================================

    async def add_internal_note(
        self,
        ticket_id: uuid.UUID,
        user: User,
        company_id: uuid.UUID,
        note: str,
    ) -> InternalNoteResponse:
        """Add staff-only internal note."""
        role = self._get_user_role_str(user)
        if role not in ("hr_admin", "it_admin", "manager", "super_admin"):
            raise ForbiddenException(message="Only administrators and managers can create internal staff notes.")

        if not note or not note.strip():
            raise ValidationException(message="Internal note text cannot be empty.")

        ticket = await self.repo.get_ticket_by_id(ticket_id, company_id)
        if not ticket:
            raise NotFoundException(message=f"Ticket '{ticket_id}' not found.")

        int_note = await self.repo.add_internal_note(
            ticket=ticket,
            author_id=user.id,
            note_text=note.strip(),
        )

        return InternalNoteResponse(
            id=int_note.id,
            ticketId=int_note.ticket_id,
            author=self._format_user_summary(int_note.author) or HelpdeskUserSummary(
                id=int_note.author_id, name="Staff", email="", role=role
            ),
            note=int_note.note,
            createdAt=int_note.created_at,
        )

    # =======================================================================
    # 11. getHelpdeskFAQs
    # =======================================================================

    async def get_faqs(
        self,
        company_id: uuid.UUID,
        category: str | None = None,
        search: str | None = None,
    ) -> list[FAQResponse]:
        """Fetch public FAQs for company."""
        faqs = await self.repo.get_faqs(
            company_id=company_id,
            category=category,
            search=search,
            public_only=True,
        )
        return [
            FAQResponse(
                id=f.id,
                category=f.category,
                question=f.question,
                answer=f.answer,
                isPublic=f.is_public,
                viewCount=f.view_count,
                isHelpfulCount=f.is_helpful_count,
                createdAt=f.created_at,
                updatedAt=f.updated_at,
            )
            for f in faqs
        ]

    # =======================================================================
    # 12. upsertHelpdeskFAQ (Admin)
    # =======================================================================

    async def upsert_faq(
        self,
        user: User,
        company_id: uuid.UUID,
        category: str,
        question: str,
        answer: str,
        is_public: bool = True,
        faq_id: uuid.UUID | None = None,
    ) -> FAQResponse:
        """Create or update FAQ (admin only)."""
        role = self._get_user_role_str(user)
        if role not in ("hr_admin", "it_admin", "super_admin"):
            raise ForbiddenException(message="Only administrators can manage helpdesk FAQs.")

        if not category or not category.strip():
            raise ValidationException(message="FAQ category is required.")
        if not question or not question.strip():
            raise ValidationException(message="FAQ question is required.")
        if not answer or not answer.strip():
            raise ValidationException(message="FAQ answer is required.")

        faq = await self.repo.upsert_faq(
            company_id=company_id,
            category=category.strip(),
            question=question.strip(),
            answer=answer.strip(),
            is_public=is_public,
            faq_id=faq_id,
            created_by=user.id,
        )

        return FAQResponse(
            id=faq.id,
            category=faq.category,
            question=faq.question,
            answer=faq.answer,
            isPublic=faq.is_public,
            viewCount=faq.view_count,
            isHelpfulCount=faq.is_helpful_count,
            createdAt=faq.created_at,
            updatedAt=faq.updated_at,
        )

    # =======================================================================
    # 13. executeSupportAIChat
    # =======================================================================

    async def execute_ai_support_chat(
        self,
        user: User,
        company_id: uuid.UUID,
        message: str,
        conversation_history: list[dict[str, Any]] | None = None,
    ) -> AIChatResponse:
        """AI Helpdesk Copilot answering questions from FAQs/Knowledge base."""
        if not message or not message.strip():
            raise ValidationException(message="Message cannot be empty.")

        # 1. Search relevant FAQs
        faqs = await self.repo.get_faqs(company_id=company_id, search=message, public_only=True)
        faq_context_list = [f"Q: {f.question}\nA: {f.answer}" for f in faqs[:5]]
        faq_context = "\n\n".join(faq_context_list) if faq_context_list else "No direct FAQ match found."

        system_prompt = (
            "You are the OFC360 Helpdesk & Support AI Assistant. "
            "Help the employee resolve their query accurately, courteously, and concisely. "
            "Use the provided company FAQ knowledge base below where applicable. "
            "If the issue cannot be resolved through self-service instructions, advise the user to open a support ticket.\n\n"
            f"--- COMPANY FAQ KNOWLEDGE BASE ---\n{faq_context}\n-----------------------------------"
        )

        messages = [{"role": "system", "content": system_prompt}]
        if conversation_history:
            for item in conversation_history[-6:]:
                role = item.get("role", "user")
                content = item.get("content", "")
                if content:
                    messages.append({"role": role, "content": content})

        messages.append({"role": "user", "content": message.strip()})

        client = get_llm_client()
        try:
            ai_reply = await asyncio.wait_for(
                client.chat(messages, temperature=0.3, num_predict=1024),
                timeout=25.0,
            )
        except asyncio.TimeoutError:
            ai_reply = "I apologize, but processing your request timed out. Please try again or create a support ticket directly."
        except Exception as exc:
            err_msg = str(exc).lower()
            if "429" in err_msg or "rate limit" in err_msg:
                raise AppException(
                    message="AI Support Copilot is currently handling high load. Please retry in a few moments or raise a ticket.",
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                )
            logger.warning("AI Chat failed, falling back to heuristic: %s", exc)
            if faqs:
                ai_reply = f"Here is relevant information from our knowledge base:\n\n{faqs[0].question}\n{faqs[0].answer}\n\nIf you need further help, you can raise a ticket."
            else:
                ai_reply = "I could not find an immediate solution in the knowledge base. Would you like to create a support ticket for our IT or HR team?"

        suggested_actions = ["Raise Support Ticket", "Browse FAQs", "Check Policy Documents"]
        is_deflected = not ("ticket" in message.lower() and "create" in message.lower())

        return AIChatResponse(
            reply=ai_reply,
            suggestedActions=suggested_actions,
            deflected=is_deflected,
        )

    # =======================================================================
    # 14. getHelpdeskSLAMetrics
    # =======================================================================

    async def get_sla_metrics(
        self,
        user: User,
        company_id: uuid.UUID,
    ) -> HelpdeskSLAMetricsResponse:
        """Calculate SLA metrics and KPIs from actual database records."""
        role = self._get_user_role_str(user)
        if role not in ("hr_admin", "it_admin", "executive", "super_admin"):
            raise ForbiddenException(message="Only administrators and executives can view SLA metrics.")

        metrics = await self.repo.calculate_sla_metrics(company_id)

        return HelpdeskSLAMetricsResponse(
            totalTickets=metrics["totalTickets"],
            resolvedTickets=metrics["resolvedTickets"],
            slaComplianceRate=metrics["slaComplianceRate"],
            averageFirstResponseHours=metrics["averageFirstResponseHours"],
            averageResolutionHours=metrics["averageResolutionHours"],
            categoryBreakdown=metrics["categoryBreakdown"],
            urgentOpenCount=metrics["urgentOpenCount"],
        )
