"""FastAPI router for AI Brain endpoints (/api/v1/ai-brain/*)."""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Dict, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.auth import APIResponse
from app.services.employee_health_service import EmployeeHealthService
from app.services.meeting_ai_service import MeetingAIService
from app.services.ai_workforce_service import AIWorkforceService
from app.services.chat_assistant_service import ChatAssistantService
from app.schemas.chat_assistant import ChatAssistantRequest

router = APIRouter(prefix="/ai-brain", tags=["AI Brain Module"])


def get_company_id_from_claims(claims: dict) -> Optional[uuid.UUID]:
    co_id_str = claims.get("company_id") if isinstance(claims, dict) else None
    return uuid.UUID(str(co_id_str)) if co_id_str else None


@router.post(
    "/meeting-intelligence",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="AI Brain Meeting Intelligence Endpoint",
)
@router.get(
    "/meeting-intelligence",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
)
async def ai_brain_meeting_intelligence(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[dict]:
    """Retrieve meeting intelligence analytics for AI Brain thunk."""
    company_id = get_company_id_from_claims(claims)
    service = MeetingAIService(session=session)
    data = await service.get_dashboard(company_id=company_id)
    return APIResponse[dict](
        success=True,
        message="AI Brain meeting intelligence fetched successfully.",
        data=data.model_dump() if hasattr(data, "model_dump") else data,
        errors=None,
    )


@router.post(
    "/workforce-insights",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="AI Brain Workforce Insights Endpoint",
)
@router.get(
    "/workforce-insights",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
)
async def ai_brain_workforce_insights(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[dict]:
    """Retrieve workforce insights analytics for AI Brain thunk."""
    company_id = get_company_id_from_claims(claims)
    service = AIWorkforceService(session=session)
    data = await service.get_dashboard(company_id=company_id)
    return APIResponse[dict](
        success=True,
        message="AI Brain workforce insights fetched successfully.",
        data=data.model_dump() if hasattr(data, "model_dump") else data,
        errors=None,
    )


@router.post(
    "/employee-health",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="AI Brain Employee Health Endpoint",
)
@router.get(
    "/employee-health",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
)
async def ai_brain_employee_health(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[dict]:
    """Retrieve employee health sentiment analytics for AI Brain thunk."""
    company_id = get_company_id_from_claims(claims)
    service = EmployeeHealthService(session=session)
    data = await service.get_dashboard(company_id=company_id)
    return APIResponse[dict](
        success=True,
        message="AI Brain employee health sentiment fetched successfully.",
        data=data.model_dump() if hasattr(data, "model_dump") else data,
        errors=None,
    )


@router.post(
    "",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="AI Brain Chat Completion Endpoint",
)
@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
)
async def ai_brain_chat(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    payload: Optional[dict] = None,
) -> APIResponse[dict]:
    """Process autonomous AI Brain agent query."""
    company_id = get_company_id_from_claims(claims)
    service = ChatAssistantService(session=session)
    query_text = (payload.get("prompt") or payload.get("message") or payload.get("query") if payload else "AI Brain workforce status")
    req = ChatAssistantRequest(query=str(query_text))
    data = await service.process_chat(request=req, company_id=company_id)
    return APIResponse[dict](
        success=True,
        message="AI Brain completion generated successfully.",
        data=data.model_dump() if hasattr(data, "model_dump") else data,
        errors=None,
    )
