"""AI Hub — Root Index (/api/v1/ai-hub)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.middleware.auth import get_current_user_claims
from app.schemas.ai_hub.root import AIHubIndexResponse, AIHubModuleInfo
from app.schemas.auth import APIResponse

router = APIRouter(prefix="/ai-hub", tags=["AI Hub - Index"])

MODULES_METADATA: list[dict] = [
    {
        "slug": "agents",
        "name": "AI Agents",
        "basePath": "/api/v1/ai-hub/agents",
        "description": "Unified registry, execution runner, history, and feedback for autonomous domain agents.",
        "category": "Core Agents",
        "endpointsCount": 6,
    },
    {
        "slug": "analytics-center",
        "name": "Analytics Center",
        "basePath": "/api/v1/ai-hub/analytics-center",
        "description": "Cross-module organizational health, attrition modeling, diversity analytics, and executive summaries.",
        "category": "Analytics",
        "endpointsCount": 5,
    },
    {
        "slug": "attendance-monitor",
        "name": "Attendance Monitor",
        "basePath": "/api/v1/ai-hub/attendance-monitor",
        "description": "Shift adherence, anomaly identification, overtime metrics, and attendance health scoring.",
        "category": "Workforce",
        "endpointsCount": 3,
    },
    {
        "slug": "chat-assistant",
        "name": "Chat Assistant",
        "basePath": "/api/v1/ai-hub/chat-assistant",
        "description": "Interactive conversational HR copilot with persistent memory, multi-agent support, and query suggestions.",
        "category": "Assistant",
        "endpointsCount": 5,
    },
    {
        "slug": "compliance-monitor",
        "name": "Compliance Monitor",
        "basePath": "/api/v1/ai-hub/compliance-monitor",
        "description": "Labor law adherence, missing document tracking, audit readiness assessment, and automated scans.",
        "category": "Compliance",
        "endpointsCount": 4,
    },
    {
        "slug": "document-generator",
        "name": "Document Generator",
        "basePath": "/api/v1/ai-hub/document-generator",
        "description": "Dynamic template rendering and export into PDF, DOCX, HTML, and text formats with variable injection.",
        "category": "Documents",
        "endpointsCount": 4,
    },
    {
        "slug": "employee-health",
        "name": "Employee Health",
        "basePath": "/api/v1/ai-hub/employee-health",
        "description": "Wellbeing score calculation, burnout risk evaluation, overtime fatigue warnings, and workload balance.",
        "category": "Health & Wellbeing",
        "endpointsCount": 3,
    },
    {
        "slug": "leave-assistant",
        "name": "Leave Assistant",
        "basePath": "/api/v1/ai-hub/leave-assistant",
        "description": "Department leave analytics, holiday conflict detection, team availability, and seasonal demand forecasting.",
        "category": "Workforce",
        "endpointsCount": 3,
    },
    {
        "slug": "meeting-intelligence",
        "name": "Meeting Intelligence",
        "basePath": "/api/v1/ai-hub/meeting-intelligence",
        "description": "Meeting transcript analysis, decision summaries, sentiment insights, and action item delegation.",
        "category": "Productivity",
        "endpointsCount": 4,
    },
    {
        "slug": "payroll-insights",
        "name": "Payroll Insights",
        "basePath": "/api/v1/ai-hub/payroll-insights",
        "description": "Payroll variance anomaly detection, statutory tax audits, cost driver breakdowns, and fraud flags.",
        "category": "Payroll",
        "endpointsCount": 4,
    },
    {
        "slug": "performance-coach",
        "name": "Performance Coach",
        "basePath": "/api/v1/ai-hub/performance-coach",
        "description": "AI-driven OKR/KPI generation, skill gap evaluations, and tailored training track recommendations.",
        "category": "Performance",
        "endpointsCount": 3,
    },
    {
        "slug": "policy-assistant",
        "name": "Policy Assistant",
        "basePath": "/api/v1/ai-hub/policy-assistant",
        "description": "RAG-powered conversational policy exploration and document-to-policy compliance checks.",
        "category": "HR Operations",
        "endpointsCount": 3,
    },
    {
        "slug": "recruiter",
        "name": "Recruiter",
        "basePath": "/api/v1/ai-hub/recruiter",
        "description": "Candidate-to-job matching, multi-criteria resume screening, and tailored interview question generation.",
        "category": "Recruitment",
        "endpointsCount": 4,
    },
    {
        "slug": "workforce-insights",
        "name": "Workforce Insights",
        "basePath": "/api/v1/ai-hub/workforce-insights",
        "description": "Workforce utilization metrics, productivity scores, and department capacity health.",
        "category": "Workforce",
        "endpointsCount": 2,
    },
    {
        "slug": "workforce-planning",
        "name": "Workforce Planning",
        "basePath": "/api/v1/ai-hub/workforce-planning",
        "description": "Quarterly headcount demand forecasting, hiring budget optimization, and capacity planning.",
        "category": "Workforce",
        "endpointsCount": 3,
    },
]


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[AIHubIndexResponse],
    summary="AI Hub Service Directory",
)
async def get_ai_hub_index(
    claims: Annotated[dict, Depends(get_current_user_claims)],
) -> APIResponse[AIHubIndexResponse]:
    """Return self-describing directory of all 15 AI Hub modules and endpoints."""
    modules = [AIHubModuleInfo(**m) for m in MODULES_METADATA]
    data = AIHubIndexResponse(
        version="v1",
        title="AI Hub Gateway",
        description="Unified enterprise AI services gateway for apiofc360",
        totalModules=len(modules),
        modules=modules,
    )
    return APIResponse[AIHubIndexResponse](
        success=True,
        message="AI Hub directory retrieved successfully.",
        data=data,
        errors=None,
    )
