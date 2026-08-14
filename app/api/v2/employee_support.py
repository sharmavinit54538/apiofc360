"""API v2 router for the Employee Support AI Agent."""

from __future__ import annotations

import uuid
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Query, status, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.auth import APIResponse
from app.agents.support_router import SupportRouter
from app.agents.ticket_agent import TicketAgent
from app.core.config import settings

import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/employee-support", tags=["Employee Support AI Agent v2"])

# Schemas
class SupportChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=1000)
    conversation_id: Optional[uuid.UUID] = None
    model: Optional[str] = None

class CreateTicketRequest(BaseModel):
    category: str = Field("IT", description="IT | HR | PAYROLL | GENERAL")
    priority: str = Field("MEDIUM", description="LOW | MEDIUM | HIGH | URGENT")
    title: str = Field(..., min_length=5, max_length=200)
    description: str = Field(..., min_length=10)

class UpdateTicketRequest(BaseModel):
    update_text: str = Field(..., min_length=5)
    status: Optional[str] = Field(None, description="IN_PROGRESS | CLOSED | ESCALATED")


@router.post(
    "/chat",
    response_model=APIResponse[dict],
    summary="Chat with the Employee Support AI Assistant",
)
async def chat_employee_support(
    body: SupportChatRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Conversational support endpoint. Routes query, handles database transactions, returns resolved state."""
    user_id = uuid.UUID(claims["sub"]) if claims else None
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication credentials not found.")

    # Load Employee linked to current User account
    from app.models.employee import Employee
    emp_res = await db.execute(select(Employee).where(Employee.user_id == user_id, Employee.is_deleted == False))
    emp = emp_res.scalar_one_or_none()
    if not emp:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee record corresponding to authenticated user was not found."
        )

    # Invoke Multi-Agent Support Router
    router_agent = SupportRouter(db)
    result = await router_agent.handle_query(
        employee_id=emp.id,
        message=body.message,
        chat_context=body.message,
        model=body.model
    )

    return APIResponse[dict](
        success=True,
        message="Employee Support response generated.",
        data=result,
        errors=None
    )


@router.post(
    "/tickets",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[dict],
    summary="Create a support ticket manually",
)
async def create_ticket(
    body: CreateTicketRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Manually raise support ticket."""
    user_id = uuid.UUID(claims["sub"]) if claims else None
    
    from app.models.employee import Employee
    emp_res = await db.execute(select(Employee).where(Employee.user_id == user_id, Employee.is_deleted == False))
    emp = emp_res.scalar_one_or_none()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee record not found.")

    agent = TicketAgent(db)
    ticket = await agent.create_ticket(
        employee_id=emp.id,
        category=body.category,
        priority=body.priority,
        title=body.title,
        description=body.description,
        company_id=emp.company_id
    )

    return APIResponse[dict](
        success=True,
        message="Support ticket logged successfully.",
        data={
            "ticket_id": str(ticket.id),
            "status": ticket.status,
            "priority": ticket.priority,
            "category": ticket.category,
            "title": ticket.title,
            "created_at": ticket.created_at.isoformat(),
        },
        errors=None
    )


@router.get(
    "/tickets/my",
    response_model=APIResponse[dict],
    summary="Retrieve logged tickets for current employee",
)
async def get_my_tickets(
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """List all support tickets raised by the authenticated employee."""
    user_id = uuid.UUID(claims["sub"]) if claims else None
    
    from app.models.employee import Employee
    emp_res = await db.execute(select(Employee).where(Employee.user_id == user_id, Employee.is_deleted == False))
    emp = emp_res.scalar_one_or_none()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee record not found.")

    agent = TicketAgent(db)
    tickets = await agent.get_tickets_by_employee(emp.id)

    formatted = [
        {
            "ticket_id": str(t.id),
            "category": t.category,
            "priority": t.priority,
            "status": t.status,
            "title": t.title,
            "description": t.description,
            "created_at": t.created_at.isoformat(),
            "updated_at": t.updated_at.isoformat(),
        }
        for t in tickets
    ]

    return APIResponse[dict](
        success=True,
        message=f"Found {len(formatted)} support ticket(s).",
        data={"tickets": formatted, "count": len(formatted)},
        errors=None
    )


@router.patch(
    "/tickets/{ticket_id}",
    response_model=APIResponse[dict],
    summary="Update support ticket status or comment",
)
async def update_ticket(
    ticket_id: uuid.UUID,
    body: UpdateTicketRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Appends comments or modifies ticket status (CLOSE/ESCALATE)."""
    user_id = uuid.UUID(claims["sub"]) if claims else None
    
    agent = TicketAgent(db)
    success = await agent.update_ticket(
        ticket_id=ticket_id,
        update_text=body.update_text,
        new_status=body.status,
        updater_uuid=user_id
    )

    if not success:
        raise HTTPException(status_code=404, detail="Support ticket not found.")

    return APIResponse[dict](
        success=True,
        message="Ticket updated successfully.",
        data={"ticket_id": str(ticket_id), "status": body.status},
        errors=None
    )


@router.get(
    "/hr-copilot/stats",
    response_model=APIResponse[dict],
    summary="Aggregate support statistics for HR managers",
)
async def hr_copilot_stats(
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Dashboard aggregator overview for HR managers."""
    # Strict RBAC verification check
    role = claims.get("role", "employee") if claims else "employee"
    if role not in ("super_admin", "hr_admin", "manager"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="RBAC authorization failed. Access restricted to HR administrators."
        )

    # 1. Total unresolved support tickets
    from app.models.ai_employee_support import SupportTicket
    open_res = await db.execute(
        select(func.count(SupportTicket.id)).where(SupportTicket.status.in_(["OPEN", "IN_PROGRESS", "ESCALATED"]))
    )
    unresolved_count = open_res.scalar() or 0

    # 2. Tickets category distribution
    cat_res = await db.execute(
        select(SupportTicket.category, func.count(SupportTicket.id)).group_by(SupportTicket.category)
    )
    categories = {row[0]: row[1] for row in cat_res.all()}

    # 3. Escalated tickets list count
    esc_res = await db.execute(
        select(func.count(SupportTicket.id)).where(SupportTicket.status == "ESCALATED")
    )
    escalated_count = esc_res.scalar() or 0

    # 4. Total employees on leave (used_days > 0 in leave policies)
    from app.models.employee_leave_policy import EmployeeLeavePolicy
    leave_res = await db.execute(
        select(func.count(func.distinct(EmployeeLeavePolicy.employee_id))).where(EmployeeLeavePolicy.used_days > 0)
    )
    on_leave_count = leave_res.scalar() or 0

    return APIResponse[dict](
        success=True,
        message="HR Copilot aggregate statistics loaded.",
        data={
            "unresolved_tickets": unresolved_count,
            "escalated_tickets": escalated_count,
            "active_leave_count": on_leave_count,
            "tickets_by_category": categories,
        },
        errors=None
    )
