"""FastAPI Router for OFC360 Helpdesk & Support Module containing all 14 required endpoints."""

from __future__ import annotations

import logging
from typing import Annotated, Any
import uuid

from fastapi import (
    APIRouter, Depends, File, Header, HTTPException,
    Query, UploadFile, status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, ForbiddenException, UnauthorizedException
from app.db.database import get_db_session
from app.middleware.auth import get_current_user, get_current_user_claims
from app.models.user import User
from app.schemas.helpdesk import (
    AddTicketCommentRequest,
    AIChatRequest,
    AssignTicketRequest,
    CreateTicketRequest,
    InternalNoteRequest,
    UpdateTicketStatusRequest,
    UpsertFAQRequest,
)
from app.services.helpdesk_service import HelpdeskService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/helpdesk", tags=["OFC360 Helpdesk & Support"])


# ===========================================================================
# Tenant Validation Helper
# ===========================================================================

def get_tenant_company_id(
    claims: dict[str, Any],
    user: User,
    x_company_id: str | None = None,
) -> uuid.UUID:
    """Validate and resolve tenant isolation company UUID."""
    user_company = user.company_id or claims.get("company_id")
    if not user_company:
        raise AppException(
            message="Authenticated user is not assigned to a company.",
            status_code=status.HTTP_403_FORBIDDEN,
        )

    user_company_uuid = uuid.UUID(str(user_company))

    if x_company_id and x_company_id.strip():
        try:
            header_uuid = uuid.UUID(x_company_id.strip())
            user_role = getattr(user.role, "value", str(user.role)).lower() if user.role else ""
            if header_uuid != user_company_uuid and user_role != "super_admin":
                logger.warning(
                    "Tenant ID mismatch attempt | user=%s header_tenant=%s user_tenant=%s",
                    user.id, header_uuid, user_company_uuid,
                )
                raise ForbiddenException("Access denied for the requested tenant.")
            return header_uuid
        except ValueError:
            raise AppException(message="Invalid X-Company-ID header.", status_code=status.HTTP_400_BAD_REQUEST)

    return user_company_uuid


# ===========================================================================
# 1. getMySupportTickets
# ===========================================================================

@router.get(
    "/tickets/my",
    summary="1. Helpdesk - Get My Support Tickets",
    description="Return support tickets created by the currently authenticated user.",
)
async def get_my_support_tickets(
    status_filter: str = Query("ALL", alias="status", description="Status filter: ALL, Open, In Progress, Resolved, Closed"),
    category: str | None = Query(None, description="Category filter"),
    search: str | None = Query(None, description="Search keyword in subject or description"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    current_user: User = Depends(get_current_user),
    claims: dict = Depends(get_current_user_claims),
    x_company_id: Annotated[str | None, Header(alias="X-Company-ID")] = None,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    company_id = get_tenant_company_id(claims, current_user, x_company_id)
    service = HelpdeskService(db)
    result = await service.get_my_tickets(
        user=current_user,
        company_id=company_id,
        status_filter=status_filter,
        category=category,
        search=search,
        page=page,
        limit=limit,
    )
    return {
        "success": True,
        "message": "User support tickets retrieved successfully",
        "data": result.model_dump(by_alias=True),
        "errors": None,
    }


# ===========================================================================
# 2. createSupportTicket
# ===========================================================================

@router.post(
    "/tickets",
    status_code=status.HTTP_201_CREATED,
    summary="2. Helpdesk - Create Support Ticket",
    description="Create a new support ticket with auto-calculated SLA deadlines.",
)
async def create_support_ticket(
    payload: CreateTicketRequest,
    current_user: User = Depends(get_current_user),
    claims: dict = Depends(get_current_user_claims),
    x_company_id: Annotated[str | None, Header(alias="X-Company-ID")] = None,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    company_id = get_tenant_company_id(claims, current_user, x_company_id)
    service = HelpdeskService(db)
    ticket = await service.create_ticket(
        user=current_user,
        company_id=company_id,
        category=payload.category,
        priority=payload.priority,
        subject=payload.subject,
        description=payload.description,
        attachment_ids=payload.attachmentIds,
    )
    return {
        "success": True,
        "message": "Support ticket created successfully",
        "data": ticket.model_dump(by_alias=True),
        "errors": None,
    }


# ===========================================================================
# 3. getTicketById
# ===========================================================================

@router.get(
    "/tickets/{ticketId}",
    summary="3. Helpdesk - Get Ticket by ID",
    description="Return detailed ticket information, SLA status, requester, and assigned agent.",
)
async def get_ticket_by_id(
    ticketId: uuid.UUID,
    current_user: User = Depends(get_current_user),
    claims: dict = Depends(get_current_user_claims),
    x_company_id: Annotated[str | None, Header(alias="X-Company-ID")] = None,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    company_id = get_tenant_company_id(claims, current_user, x_company_id)
    service = HelpdeskService(db)
    ticket = await service.get_ticket_by_id(
        ticket_id=ticketId,
        user=current_user,
        company_id=company_id,
    )
    return {
        "success": True,
        "message": "Ticket details retrieved successfully",
        "data": ticket.model_dump(by_alias=True),
        "errors": None,
    }


# ===========================================================================
# 4. getTicketComments
# ===========================================================================

@router.get(
    "/tickets/{ticketId}/comments",
    summary="4. Helpdesk - Get Ticket Discussion Comments",
    description="Return chronological ticket comments (internal notes excluded for regular employees).",
)
async def get_ticket_comments(
    ticketId: uuid.UUID,
    current_user: User = Depends(get_current_user),
    claims: dict = Depends(get_current_user_claims),
    x_company_id: Annotated[str | None, Header(alias="X-Company-ID")] = None,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    company_id = get_tenant_company_id(claims, current_user, x_company_id)
    service = HelpdeskService(db)
    comments = await service.get_ticket_comments(
        ticket_id=ticketId,
        user=current_user,
        company_id=company_id,
    )
    return {
        "success": True,
        "message": "Ticket comments retrieved successfully",
        "data": [c.model_dump(by_alias=True) for c in comments],
        "errors": None,
    }


# ===========================================================================
# 5. addTicketComment
# ===========================================================================

@router.post(
    "/tickets/{ticketId}/comments",
    status_code=status.HTTP_201_CREATED,
    summary="5. Helpdesk - Add Ticket Comment",
    description="Post a comment on a support ticket and notify the other party.",
)
async def add_ticket_comment(
    ticketId: uuid.UUID,
    payload: AddTicketCommentRequest,
    current_user: User = Depends(get_current_user),
    claims: dict = Depends(get_current_user_claims),
    x_company_id: Annotated[str | None, Header(alias="X-Company-ID")] = None,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    company_id = get_tenant_company_id(claims, current_user, x_company_id)
    service = HelpdeskService(db)
    comment = await service.add_comment(
        ticket_id=ticketId,
        user=current_user,
        company_id=company_id,
        message=payload.message,
        attachments=payload.attachments,
    )
    return {
        "success": True,
        "message": "Comment added successfully",
        "data": comment.model_dump(by_alias=True),
        "errors": None,
    }


# ===========================================================================
# 6. uploadTicketAttachment
# ===========================================================================

@router.post(
    "/tickets/attachments/upload",
    status_code=status.HTTP_201_CREATED,
    summary="6. Helpdesk - Upload Ticket Attachment",
    description="Upload a document or image attachment for a ticket or comment.",
)
async def upload_ticket_attachment(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    claims: dict = Depends(get_current_user_claims),
    x_company_id: Annotated[str | None, Header(alias="X-Company-ID")] = None,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    company_id = get_tenant_company_id(claims, current_user, x_company_id)
    service = HelpdeskService(db)
    att = await service.upload_attachment(
        user=current_user,
        company_id=company_id,
        file=file,
    )
    return {
        "success": True,
        "message": "Attachment uploaded successfully",
        "data": att.model_dump(by_alias=True),
        "errors": None,
    }


# ===========================================================================
# 7. getAllHelpdeskTickets (Admin)
# ===========================================================================

@router.get(
    "/admin/tickets",
    summary="7. Helpdesk - Get All Helpdesk Tickets (Admin/Manager)",
    description="Return all support tickets across company with filtering, search, and status counters.",
)
async def get_all_helpdesk_tickets(
    status_filter: str = Query("ALL", alias="status", description="Status filter: ALL, Open, In Progress, Resolved, Closed"),
    category: str | None = Query(None, description="Category filter"),
    priority: str | None = Query(None, description="Priority filter: Low, Medium, High, Urgent"),
    assigned_to: str | None = Query(None, alias="assignedTo", description="Agent user ID or 'unassigned'"),
    is_sla_breached: bool | None = Query(None, alias="isSlaBreached", description="Filter SLA breached tickets"),
    search: str | None = Query(None, description="Search keyword"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(30, ge=1, le=100, description="Items per page"),
    current_user: User = Depends(get_current_user),
    claims: dict = Depends(get_current_user_claims),
    x_company_id: Annotated[str | None, Header(alias="X-Company-ID")] = None,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    company_id = get_tenant_company_id(claims, current_user, x_company_id)
    service = HelpdeskService(db)
    result = await service.get_all_admin_tickets(
        user=current_user,
        company_id=company_id,
        status_filter=status_filter,
        category=category,
        priority=priority,
        assigned_to=assigned_to,
        is_sla_breached=is_sla_breached,
        search=search,
        page=page,
        limit=limit,
    )
    return {
        "success": True,
        "message": "All helpdesk tickets retrieved successfully",
        "data": result.model_dump(by_alias=True),
        "errors": None,
    }


# ===========================================================================
# 8. updateTicketStatus
# ===========================================================================

@router.patch(
    "/tickets/{ticketId}/status",
    summary="8. Helpdesk - Update Ticket Status",
    description="Update ticket status (Open, In Progress, Resolved, Closed, Reopened) with validation.",
)
async def update_ticket_status(
    ticketId: uuid.UUID,
    payload: UpdateTicketStatusRequest,
    current_user: User = Depends(get_current_user),
    claims: dict = Depends(get_current_user_claims),
    x_company_id: Annotated[str | None, Header(alias="X-Company-ID")] = None,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    company_id = get_tenant_company_id(claims, current_user, x_company_id)
    service = HelpdeskService(db)
    ticket = await service.update_ticket_status(
        ticket_id=ticketId,
        user=current_user,
        company_id=company_id,
        new_status=payload.status,
        resolution_notes=payload.resolutionNotes,
    )
    return {
        "success": True,
        "message": f"Ticket status updated to '{ticket.status}'",
        "data": ticket.model_dump(by_alias=True),
        "errors": None,
    }


# ===========================================================================
# 9. assignTicketAgent
# ===========================================================================

@router.patch(
    "/tickets/{ticketId}/assign",
    summary="9. Helpdesk - Assign Ticket to Agent",
    description="Assign ticket to an agent within the company and optionally set department.",
)
async def assign_ticket_agent(
    ticketId: uuid.UUID,
    payload: AssignTicketRequest,
    current_user: User = Depends(get_current_user),
    claims: dict = Depends(get_current_user_claims),
    x_company_id: Annotated[str | None, Header(alias="X-Company-ID")] = None,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    company_id = get_tenant_company_id(claims, current_user, x_company_id)
    service = HelpdeskService(db)
    ticket = await service.assign_ticket_agent(
        ticket_id=ticketId,
        user=current_user,
        company_id=company_id,
        assigned_to_user_id=payload.assignedToUserId,
        department=payload.department,
    )
    return {
        "success": True,
        "message": "Ticket assigned successfully",
        "data": ticket.model_dump(by_alias=True),
        "errors": None,
    }


# ===========================================================================
# 10. addInternalTicketNote
# ===========================================================================

@router.post(
    "/tickets/{ticketId}/internal-notes",
    status_code=status.HTTP_201_CREATED,
    summary="10. Helpdesk - Add Internal Staff Note",
    description="Add a staff-only internal note (visible only to admins and managers).",
)
async def add_internal_ticket_note(
    ticketId: uuid.UUID,
    payload: InternalNoteRequest,
    current_user: User = Depends(get_current_user),
    claims: dict = Depends(get_current_user_claims),
    x_company_id: Annotated[str | None, Header(alias="X-Company-ID")] = None,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    company_id = get_tenant_company_id(claims, current_user, x_company_id)
    service = HelpdeskService(db)
    note = await service.add_internal_note(
        ticket_id=ticketId,
        user=current_user,
        company_id=company_id,
        note=payload.note,
    )
    return {
        "success": True,
        "message": "Internal note added successfully",
        "data": note.model_dump(by_alias=True),
        "errors": None,
    }


# ===========================================================================
# 11. getHelpdeskFAQs
# ===========================================================================

@router.get(
    "/faqs",
    summary="11. Helpdesk - Get Knowledge Base FAQs",
    description="Fetch public FAQs with search and category filtering.",
)
async def get_helpdesk_faqs(
    category: str | None = Query(None, description="FAQ category"),
    search: str | None = Query(None, description="Search question or answer"),
    current_user: User = Depends(get_current_user),
    claims: dict = Depends(get_current_user_claims),
    x_company_id: Annotated[str | None, Header(alias="X-Company-ID")] = None,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    company_id = get_tenant_company_id(claims, current_user, x_company_id)
    service = HelpdeskService(db)
    faqs = await service.get_faqs(
        company_id=company_id,
        category=category,
        search=search,
    )
    return {
        "success": True,
        "message": "FAQs retrieved successfully",
        "data": [f.model_dump(by_alias=True) for f in faqs],
        "errors": None,
    }


# ===========================================================================
# 12. upsertHelpdeskFAQ (Admin)
# ===========================================================================

@router.post(
    "/admin/faqs",
    summary="12. Helpdesk - Create or Update FAQ (Admin)",
    description="Create or update knowledge base FAQ for the company.",
)
async def upsert_helpdesk_faq(
    payload: UpsertFAQRequest,
    current_user: User = Depends(get_current_user),
    claims: dict = Depends(get_current_user_claims),
    x_company_id: Annotated[str | None, Header(alias="X-Company-ID")] = None,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    company_id = get_tenant_company_id(claims, current_user, x_company_id)
    service = HelpdeskService(db)
    faq = await service.upsert_faq(
        user=current_user,
        company_id=company_id,
        category=payload.category,
        question=payload.question,
        answer=payload.answer,
        is_public=payload.is_public,
        faq_id=payload.id,
    )
    return {
        "success": True,
        "message": "FAQ saved successfully",
        "data": faq.model_dump(by_alias=True),
        "errors": None,
    }


# ===========================================================================
# 13. executeSupportAIChat
# ===========================================================================

@router.post(
    "/ai/chat",
    summary="13. Helpdesk - AI Support Copilot Chat",
    description="Query AI Support Copilot with automatic FAQ knowledge retrieval and deflection suggestions.",
)
async def execute_support_ai_chat(
    payload: AIChatRequest,
    current_user: User = Depends(get_current_user),
    claims: dict = Depends(get_current_user_claims),
    x_company_id: Annotated[str | None, Header(alias="X-Company-ID")] = None,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    company_id = get_tenant_company_id(claims, current_user, x_company_id)
    service = HelpdeskService(db)
    response = await service.execute_ai_support_chat(
        user=current_user,
        company_id=company_id,
        message=payload.message,
        conversation_history=payload.conversationHistory,
    )
    return {
        "success": True,
        "message": "AI support response generated successfully",
        "data": response.model_dump(by_alias=True),
        "errors": None,
    }


# ===========================================================================
# 14. getHelpdeskSLAMetrics (Admin)
# ===========================================================================

@router.get(
    "/admin/metrics",
    summary="14. Helpdesk - Get SLA & KPI Metrics (Admin/Executive)",
    description="Calculate actual database SLA metrics, compliance rates, average response hours, and category breakdown.",
)
async def get_helpdesk_sla_metrics(
    current_user: User = Depends(get_current_user),
    claims: dict = Depends(get_current_user_claims),
    x_company_id: Annotated[str | None, Header(alias="X-Company-ID")] = None,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    company_id = get_tenant_company_id(claims, current_user, x_company_id)
    service = HelpdeskService(db)
    metrics = await service.get_sla_metrics(
        user=current_user,
        company_id=company_id,
    )
    return {
        "success": True,
        "message": "Helpdesk SLA metrics calculated successfully",
        "data": metrics.model_dump(by_alias=True),
        "errors": None,
    }
