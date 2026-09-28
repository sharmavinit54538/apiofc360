"""AI Hub — Agents (/api/v1/ai-hub/agents/*)."""

from __future__ import annotations

from typing import Annotated, Optional
import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.ai_hub.agents import (
    AgentDetailResponse,
    AgentFeedbackRequest,
    AgentFeedbackResponse,
    AgentHistoryPage,
    AgentRegistryItem,
    AgentRunResult,
    AgentStatusResponse,
    RunAgentRequest,
)
from app.schemas.auth import APIResponse
from app.services.ai_hub.agents_service import AgentsService
from app.services.ai_hub.utils import get_company_id_from_claims

router = APIRouter(prefix="/ai-hub/agents", tags=["AI Hub - Agents"])


async def get_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AgentsService:
    return AgentsService(session=session)


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[list[AgentRegistryItem]],
    summary="List Registered AI Agents",
)
async def list_agents(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AgentsService, Depends(get_service)],
) -> APIResponse[list[AgentRegistryItem]]:
    """List all registered AI Agents in the AI Hub catalog."""
    data = service.list_agents()
    return APIResponse[list[AgentRegistryItem]](
        success=True,
        message="AI Hub agents retrieved successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/{agentId}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[AgentDetailResponse],
    summary="Get Agent Detail and Summary",
)
async def get_agent(
    agentId: str,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AgentsService, Depends(get_service)],
) -> APIResponse[AgentDetailResponse]:
    """Get metadata, execution statistics, and last run summary for a specific agent."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_agent(agent_id=agentId, company_id=company_id)
    return APIResponse[AgentDetailResponse](
        success=True,
        message=f"Agent '{agentId}' details fetched successfully.",
        data=data,
        errors=None,
    )


@router.post(
    "/{agentId}/run",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[AgentRunResult],
    summary="Execute AI Agent",
)
async def run_agent(
    agentId: str,
    payload: RunAgentRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AgentsService, Depends(get_service)],
) -> APIResponse[AgentRunResult]:
    """Trigger execution of an AI agent, log execution to database, and return results."""
    company_id = get_company_id_from_claims(claims)
    user_id_raw = claims.get("sub")
    user_id = uuid.UUID(user_id_raw) if user_id_raw else None

    data = await service.run_agent(
        agent_id=agentId,
        company_id=company_id,
        user_id=user_id,
        payload=payload,
    )
    return APIResponse[AgentRunResult](
        success=True,
        message=f"Agent '{agentId}' executed with status: {data.status}.",
        data=data,
        errors=None,
    )


@router.get(
    "/{agentId}/history",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[AgentHistoryPage],
    summary="Get Agent Run History",
)
async def get_agent_history(
    agentId: str,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AgentsService, Depends(get_service)],
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None),
    sort_by: Optional[str] = Query(None, alias="sortBy"),
    sort_order: Optional[str] = Query(None, alias="sortOrder"),
) -> APIResponse[AgentHistoryPage]:
    """Retrieve paginated execution history for an agent scoped to current company."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_history(
        agent_id=agentId,
        company_id=company_id,
        page=page,
        limit=limit,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return APIResponse[AgentHistoryPage](
        success=True,
        message="Agent run history retrieved successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/{agentId}/status",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[AgentStatusResponse],
    summary="Get Agent Operational Status",
)
async def get_agent_status(
    agentId: str,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AgentsService, Depends(get_service)],
) -> APIResponse[AgentStatusResponse]:
    """Fetch current health and running status of an agent."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_status(agent_id=agentId, company_id=company_id)
    return APIResponse[AgentStatusResponse](
        success=True,
        message="Agent status retrieved successfully.",
        data=data,
        errors=None,
    )


@router.post(
    "/{agentId}/feedback",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[AgentFeedbackResponse],
    summary="Submit Agent Feedback",
)
async def submit_agent_feedback(
    agentId: str,
    payload: AgentFeedbackRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AgentsService, Depends(get_service)],
) -> APIResponse[AgentFeedbackResponse]:
    """Submit quality rating, comment, and tags for an agent run."""
    company_id = get_company_id_from_claims(claims)
    user_id_raw = claims.get("sub")
    user_id = uuid.UUID(user_id_raw) if user_id_raw else None

    data = await service.add_feedback(
        agent_id=agentId,
        company_id=company_id,
        user_id=user_id,
        payload=payload,
    )
    return APIResponse[AgentFeedbackResponse](
        success=True,
        message="Agent feedback submitted successfully.",
        data=data,
        errors=None,
    )
