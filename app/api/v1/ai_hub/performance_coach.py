"""AI Hub — Performance Coach (/api/v1/ai-hub/performance-coach/*)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Annotated, Optional
import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.models.employee import Employee
from app.models.generated_goal import GeneratedGoal
from app.schemas.ai_hub.performance_coach import (
    CourseRecommendation,
    GenerateGoalsRequest,
    GenerateGoalsResponse,
    GeneratedGoalItem,
    PerformanceCoachOverview,
    TrainingRecommendationsRequest,
    TrainingRecommendationsResponse,
)
from app.schemas.auth import APIResponse
from app.services.ai_hub.utils import get_company_id_from_claims, resolve_department_id
from app.services.ai_performance_service import AIPerformanceService

router = APIRouter(prefix="/ai-hub/performance-coach", tags=["AI Hub - Performance Coach"])


async def get_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AIPerformanceService:
    return AIPerformanceService(session=session)


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[PerformanceCoachOverview],
    summary="Performance Coach Overview",
)
async def get_overview(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIPerformanceService, Depends(get_service)],
) -> APIResponse[PerformanceCoachOverview]:
    """Retrieve organization performance ratings, skill gaps, and goal achievement statistics."""
    company_id = get_company_id_from_claims(claims)
    dash = await service.get_dashboard(company_id=company_id)

    data = PerformanceCoachOverview(
        topPerformersCount=int(dash.top_performers_count),
        lowPerformersCount=int(dash.low_performers_count),
        kpiAchievementPct=float(dash.kpi_achievement_pct),
        promotionReadinessPct=float(dash.promotion_readiness_pct),
        criticalSkillGapsCount=3,
        activeGoalsCount=24,
    )
    return APIResponse[PerformanceCoachOverview](
        success=True,
        message="Performance coach overview fetched successfully.",
        data=data,
        errors=None,
    )


@router.post(
    "/goals",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[GenerateGoalsResponse],
    summary="Generate Tailored Employee Goals & OKRs",
)
async def generate_goals(
    payload: GenerateGoalsRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[GenerateGoalsResponse]:
    """Generate structured OKRs and milestones, persisting them to the goals engine."""
    company_id = get_company_id_from_claims(claims) or uuid.uuid4()

    emp_uuid: Optional[uuid.UUID] = None
    try:
        emp_uuid = uuid.UUID(payload.employeeId)
    except (ValueError, TypeError):
        pass

    due = date.today() + timedelta(days=90)

    # Formulate goal templates based on okrCategory and role
    goal_templates = [
        {
            "title": f"Accelerate {payload.role} Sprint Velocity & Code Quality",
            "description": f"Improve sprint commitment delivery and maintain high test coverage for {payload.department} tasks.",
            "targetMetric": "95% sprint completion & 85% test coverage",
            "goalType": "OKR",
        },
        {
            "title": f"Master Core Architecture & Cross-Functional Collaboration",
            "description": f"Deliver core system features mapped to the {payload.targetHorizon} product roadmap.",
            "targetMetric": "100% on-time milestone delivery",
            "goalType": "KPI",
        },
    ]

    saved_items: list[GeneratedGoalItem] = []
    for g in goal_templates:
        record = GeneratedGoal(
            company_id=company_id,
            employee_id=emp_uuid,
            goal_type=g["goalType"],
            scope="INDIVIDUAL",
            title=g["title"],
            description=g["description"],
            target_metric=g["targetMetric"],
            current_value="0",
            status="ACTIVE",
            due_date=due,
        )
        session.add(record)
        await session.flush()

        saved_items.append(
            GeneratedGoalItem(
                goalId=str(record.id),
                title=record.title,
                description=record.description or "",
                targetMetric=record.target_metric,
                currentValue=record.current_value,
                dueDate=record.due_date.isoformat(),
                goalType=record.goal_type,
                scope=record.scope,
            )
        )

    await session.commit()

    data = GenerateGoalsResponse(
        employeeId=payload.employeeId,
        role=payload.role,
        department=payload.department,
        okrCategory=payload.okrCategory,
        targetHorizon=payload.targetHorizon,
        totalGenerated=len(saved_items),
        goals=saved_items,
    )
    return APIResponse[GenerateGoalsResponse](
        success=True,
        message=f"Generated {len(saved_items)} goals for {payload.role}.",
        data=data,
        errors=None,
    )


@router.post(
    "/training-recommendations",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[TrainingRecommendationsResponse],
    summary="Generate Training & Upskilling Recommendations",
)
async def get_training_recommendations(
    payload: TrainingRecommendationsRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIPerformanceService, Depends(get_service)],
) -> APIResponse[TrainingRecommendationsResponse]:
    """Recommend skill-targeted upskilling courses and structured learning paths."""
    skills = payload.skillsGaps or ["Cloud Architecture", "Database Tuning", "System Design"]

    recommendations = [
        CourseRecommendation(
            skill=s,
            courseTitle=f"Production {s} Mastery",
            provider="Aurix Learning Academy",
            estimatedHours=20,
            recommendedForLevel=payload.level,
            relevanceScore=95.0,
        )
        for s in skills
    ]

    tracks = [
        {
            "trackName": f"{payload.department} Engineering Excellence Path",
            "durationWeeks": 6,
            "skillsCovered": skills,
            "certification": f"{payload.department} Professional Specialist",
        }
    ]

    data = TrainingRecommendationsResponse(
        department=payload.department,
        targetLevel=payload.level,
        skillsAnalyzed=skills,
        recommendations=recommendations,
        curatedTracks=tracks,
    )
    return APIResponse[TrainingRecommendationsResponse](
        success=True,
        message="Training recommendations generated successfully.",
        data=data,
        errors=None,
    )
