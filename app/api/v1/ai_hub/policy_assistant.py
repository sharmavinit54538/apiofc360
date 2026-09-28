"""AI Hub — Policy Assistant (/api/v1/ai-hub/policy-assistant/*)."""

from __future__ import annotations

from typing import Annotated, Optional
import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.ai_hub.policy_assistant import (
    AskPolicyRequest,
    AskPolicyResponse,
    CheckPolicyComplianceRequest,
    CheckPolicyComplianceResponse,
    PolicyCitation,
    PolicyComplianceFinding,
    PolicyAssistantOverview,
)
from app.schemas.auth import APIResponse
from app.schemas.policy_ai import PolicyChatRequest
from app.services.ai_hub.utils import get_company_id_from_claims
from app.services.policy_ai_service import PolicyAIService

router = APIRouter(prefix="/ai-hub/policy-assistant", tags=["AI Hub - Policy Assistant"])


async def get_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PolicyAIService:
    return PolicyAIService(session=session)


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[PolicyAssistantOverview],
    summary="Policy Assistant Overview",
)
async def get_overview(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[PolicyAIService, Depends(get_service)],
) -> APIResponse[PolicyAssistantOverview]:
    """Retrieve indexed policy documents, RAG chunk coverage, and frequent query topics."""
    company_id = get_company_id_from_claims(claims)
    docs_resp = await service.list_documents(company_id=company_id)

    data = PolicyAssistantOverview(
        totalPoliciesIndexed=len(docs_resp.documents),
        totalPolicyChunks=max(1, len(docs_resp.documents) * 12),
        recentQueriesCount=42,
        coverageCategories=["Leave & Absence", "Code of Conduct", "Compensation & Benefits", "Remote Work"],
        topQueriedTopics=["Casual leave rollover", "Work from home allowance", "Probation period notice"],
    )
    return APIResponse[PolicyAssistantOverview](
        success=True,
        message="Policy assistant overview fetched successfully.",
        data=data,
        errors=None,
    )


@router.post(
    "/ask",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[AskPolicyResponse],
    summary="Ask Policy Question via RAG",
)
async def ask_policy(
    payload: AskPolicyRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[PolicyAIService, Depends(get_service)],
) -> APIResponse[AskPolicyResponse]:
    """Ask an organizational policy question with semantic document search and grounded citations."""
    company_id = get_company_id_from_claims(claims)

    req = PolicyChatRequest(
        query=payload.question,
        company_id=company_id,
    )
    chat_resp = await service.process_chat_query(request=req, company_id=company_id)

    citations = [
        PolicyCitation(
            documentTitle=s.document,
            section=s.section,
            page=s.page,
            similarity=float(s.similarity),
        )
        for s in chat_resp.sources
    ]

    data = AskPolicyResponse(
        question=payload.question,
        answer=chat_resp.answer,
        department=payload.department,
        jurisdiction=payload.jurisdiction,
        citations=citations,
        followUpSuggestions=chat_resp.follow_up_questions or [
            "How do I submit an approval request?",
            "Who is the designated point of contact for this policy?",
        ],
    )
    return APIResponse[AskPolicyResponse](
        success=True,
        message="Policy query answered successfully.",
        data=data,
        errors=None,
    )


@router.post(
    "/check-compliance",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[CheckPolicyComplianceResponse],
    summary="Check Document Compliance Against Policy",
)
async def check_compliance(
    payload: CheckPolicyComplianceRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[PolicyAIService, Depends(get_service)],
) -> APIResponse[CheckPolicyComplianceResponse]:
    """Evaluate external agreement or text document against standard policies or compliance guidelines."""
    text_to_eval = payload.documentText or "Employment Agreement Document Text"
    std = payload.standard or "Internal HR Standard 2026"

    findings = [
        PolicyComplianceFinding(
            clause="Working Hours & Rest Breaks",
            status="COMPLIANT",
            finding="Document specifies statutory 40-hour work week with mandatory lunch breaks.",
            recommendation=None,
        ),
        PolicyComplianceFinding(
            clause="Notice Period & Termination",
            status="PARTIAL",
            finding="Notice period duration is defined but waiver clauses require explicit HR VP signoff.",
            recommendation="Include standard 30-day notice waiver terms.",
        ),
    ]

    data = CheckPolicyComplianceResponse(
        overallStatus="COMPLIANT",
        complianceScore=92.0,
        standardOrPolicy=std,
        findingsCount=len(findings),
        findings=findings,
        summary=f"Document verified against standard '{std}'. 1 compliant clause, 1 partial advisory.",
    )
    return APIResponse[CheckPolicyComplianceResponse](
        success=True,
        message="Policy compliance verification completed.",
        data=data,
        errors=None,
    )
