"""API v2 router for the Enterprise Performance Management AI Engine."""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from datetime import date, datetime, timedelta
from typing import Annotated, Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, update, func
from sqlalchemy.orm import selectinload

from app.core.rbac import require_employee_or_above
from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.auth import APIResponse
from app.services.performance_service import PerformanceService
from app.models.performance import (
    PerformanceReview,
    PerformanceReviewCycle,
    EmployeePerformanceGoal,
    PerformanceFeedback,
    PerformanceReward,
    TrainingCourse,
    TrainingAssignment,
)
from app.models.employee import Employee

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/performance",
    tags=["AI Performance Management v2"],
    dependencies=[Depends(require_employee_or_above)],
)

# Helper for safe UUID conversion
def safe_uuid(val: Any) -> uuid.UUID:
    try:
        if isinstance(val, uuid.UUID):
            return val
        return uuid.UUID(str(val))
    except (ValueError, TypeError):
        return uuid.uuid4()

# ---------------- Requests & Schemas ----------------
class CycleRequest(BaseModel):
    name: str = Field(..., min_length=2)
    start_date: date
    end_date: date

class GoalRequest(BaseModel):
    employee_id: uuid.UUID
    title: str = Field(..., min_length=2)
    target_value: str
    due_date: date
    description: Optional[str] = None

class ReviewInitRequest(BaseModel):
    cycle_id: uuid.UUID
    employee_id: uuid.UUID
    self_rating: Optional[Decimal] = None
    reviewer_rating: Optional[Decimal] = None
    feedback_360: Optional[dict] = None

class EvaluateRequest(BaseModel):
    model: Optional[str] = None

# Bulk Actions
class BulkDeleteRequest(BaseModel):
    ids: List[str]

class BulkStatusRequest(BaseModel):
    ids: List[str]
    status: str

# ---------------- API Endpoints ----------------

@router.post(
    "/cycles",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[dict],
    summary="Create a new evaluation review cycle",
)
async def create_cycle(
    body: CycleRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    service = PerformanceService(db)
    cycle = await service.create_review_cycle(
        name=body.name,
        start_date=body.start_date,
        end_date=body.end_date
    )
    return APIResponse[dict](
        success=True,
        message="Performance Review Cycle created.",
        data={
            "cycle_id": str(cycle.id),
            "name": cycle.name,
            "status": cycle.status,
        },
        errors=None
    )

@router.post(
    "/goals",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[dict],
    summary="Register a performance goal or OKR for tracking",
)
async def create_goal_api(
    body: dict,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    emp_id = safe_uuid(body.get("employeeId") or body.get("employee_id"))
    
    goal = EmployeePerformanceGoal(
        id=uuid.uuid4(),
        employee_id=emp_id,
        title=body.get("title", "Untitled Goal"),
        description=body.get("description"),
        target_value=str(body.get("target_value") or body.get("progress") or "100"),
        current_value=str(body.get("progress", 0)),
        due_date=date.fromisoformat(body.get("dueDate", date.today().isoformat())),
        status="IN_PROGRESS" if int(body.get("progress", 0)) > 0 else "PENDING"
    )
    
    db.add(goal)
    await db.commit()
    
    return APIResponse[dict](
        success=True,
        message="Employee goal registered successfully.",
        data={
            "id": str(goal.id),
            "employeeId": str(goal.employee_id),
            "title": goal.title,
            "status": goal.status.lower(),
        },
        errors=None
    )

@router.put(
    "/goals/{id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Update goal details"
)
async def update_goal_api(
    id: uuid.UUID,
    body: dict,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    stmt = select(EmployeePerformanceGoal).where(EmployeePerformanceGoal.id == id)
    res = await db.execute(stmt)
    goal = res.scalar_one_or_none()
    
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found.")
        
    if "title" in body: goal.title = body["title"]
    if "description" in body: goal.description = body["description"]
    if "progress" in body:
        val = int(body["progress"])
        goal.current_value = str(val)
        if val >= 100:
            goal.status = "ACHIEVED"
        elif val > 0:
            goal.status = "IN_PROGRESS"
        else:
            goal.status = "PENDING"
            
    await db.commit()
    return APIResponse[dict](
        success=True,
        message="Goal updated successfully.",
        data={"id": str(goal.id), "status": goal.status.lower()}
    )

@router.delete(
    "/goals/{id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[None],
    summary="Delete a goal"
)
async def delete_goal_api(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[None]:
    stmt = select(EmployeePerformanceGoal).where(EmployeePerformanceGoal.id == id)
    res = await db.execute(stmt)
    goal = res.scalar_one_or_none()
    
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found.")
        
    await db.delete(goal)
    await db.commit()
    
    return APIResponse[None](success=True, message="Goal deleted.", data=None)

@router.post(
    "/goals/assign",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[dict],
    summary="Assign a goal to an employee"
)
async def assign_goal_api(
    body: dict,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    emp_id = safe_uuid(body.get("employeeId"))
    
    goal = EmployeePerformanceGoal(
        id=uuid.uuid4(),
        employee_id=emp_id,
        title=body.get("title", "Untitled Assigned Goal"),
        description=body.get("description"),
        target_value="100",
        current_value="0",
        due_date=date.fromisoformat(body.get("dueDate", date.today().isoformat())),
        status="PENDING"
    )
    
    db.add(goal)
    await db.commit()
    
    return APIResponse[dict](
        success=True,
        message="Goal assigned.",
        data={"id": str(goal.id)}
    )

@router.post(
    "/goals/{id}/complete",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Complete a goal"
)
async def complete_goal_api(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    stmt = select(EmployeePerformanceGoal).where(EmployeePerformanceGoal.id == id)
    res = await db.execute(stmt)
    goal = res.scalar_one_or_none()
    
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found.")
        
    goal.current_value = "100"
    goal.status = "ACHIEVED"
    await db.commit()
    
    return APIResponse[dict](
        success=True,
        message="Goal marked as completed.",
        data={"id": str(goal.id)}
    )

@router.post(
    "/reviews",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[dict],
    summary="Initialize performance review parameters",
)
async def init_review(
    body: dict,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    reviewer_id = uuid.UUID(claims["sub"]) if claims else None
    emp_id = safe_uuid(body.get("employeeId"))
    
    # Ensure cycle exists or seed one
    cycle_stmt = select(PerformanceReviewCycle)
    cycle_res = await db.execute(cycle_stmt)
    cycle = cycle_res.scalars().first()
    
    if not cycle:
        cycle = PerformanceReviewCycle(
            id=uuid.uuid4(),
            name="Default Performance Cycle",
            start_date=date.today(),
            end_date=date.today() + timedelta(days=90),
            status="ACTIVE"
        )
        db.add(cycle)
        await db.flush()
        
    review = PerformanceReview(
        id=uuid.uuid4(),
        cycle_id=cycle.id,
        employee_id=emp_id,
        reviewer_id=reviewer_id,
        self_rating=Decimal(str(body.get("overallRating") or 3.0)),
        reviewer_rating=Decimal(str(body.get("overallRating") or 3.0)),
        status=body.get("reviewStatus", "draft").upper(),
    )
    
    db.add(review)
    await db.commit()
    
    return APIResponse[dict](
        success=True,
        message="Performance review sheet initialized.",
        data={
            "id": str(review.id),
            "employeeId": str(review.employee_id),
            "status": review.status.lower(),
        },
        errors=None
    )

@router.put(
    "/reviews/{id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Update performance review details"
)
async def update_review_api(
    id: uuid.UUID,
    body: dict,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    stmt = select(PerformanceReview).where(PerformanceReview.id == id)
    res = await db.execute(stmt)
    review = res.scalar_one_or_none()
    
    if not review:
        raise HTTPException(status_code=404, detail="Performance review not found.")
        
    if "overallRating" in body:
        review.reviewer_rating = Decimal(str(body["overallRating"]))
    if "reviewStatus" in body:
        review.status = body["reviewStatus"].upper()
    if "managerComments" in body:
        review.ai_review_justification = body["managerComments"]
        
    await db.commit()
    return APIResponse[dict](
        success=True,
        message="Review updated successfully.",
        data={"id": str(review.id), "status": review.status.lower()}
    )

@router.delete(
    "/reviews/{id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[None],
    summary="Delete a performance review"
)
async def delete_review_api(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[None]:
    stmt = select(PerformanceReview).where(PerformanceReview.id == id)
    res = await db.execute(stmt)
    review = res.scalar_one_or_none()
    
    if not review:
        raise HTTPException(status_code=404, detail="Performance review not found.")
        
    await db.delete(review)
    await db.commit()
    return APIResponse[None](success=True, message="Review deleted.", data=None)

@router.post(
    "/reviews/bulk-delete",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[None],
    summary="Bulk delete performance reviews"
)
async def bulk_delete_reviews_api(
    body: BulkDeleteRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[None]:
    uuids = [safe_uuid(uid_str) for uid_str in body.ids]
    stmt = delete(PerformanceReview).where(PerformanceReview.id.in_(uuids))
    await db.execute(stmt)
    await db.commit()
    return APIResponse[None](success=True, message="Bulk reviews deleted.", data=None)

@router.post(
    "/reviews/bulk-status",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[None],
    summary="Bulk set reviews status"
)
async def bulk_status_reviews_api(
    body: BulkStatusRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[None]:
    uuids = [safe_uuid(uid_str) for uid_str in body.ids]
    status_val = body.status.upper()
    stmt = update(PerformanceReview).where(PerformanceReview.id.in_(uuids)).values(status=status_val)
    await db.execute(stmt)
    await db.commit()
    return APIResponse[None](success=True, message="Bulk status updated.", data=None)

@router.post(
    "/reviews/import",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[None],
    summary="Import multiple performance reviews"
)
async def import_reviews_api(
    body: dict,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[None]:
    """Import multiple performance reviews into the database."""
    reviews_data = body.get("reviews", []) if isinstance(body, dict) else []
    if isinstance(body, list):
        reviews_data = body

    from app.models.performance import PerformanceReview
    created_count = 0
    for rev in reviews_data:
        if isinstance(rev, dict) and "employee_id" in rev and "cycle_id" in rev:
            new_review = PerformanceReview(
                id=uuid.uuid4(),
                employee_id=uuid.UUID(str(rev["employee_id"])),
                cycle_id=uuid.UUID(str(rev["cycle_id"])),
                reviewer_id=uuid.UUID(str(rev["reviewer_id"])) if rev.get("reviewer_id") else None,
                status=rev.get("status", "DRAFT").upper(),
                overall_rating=float(rev["overall_rating"]) if rev.get("overall_rating") is not None else None,
                summary_notes=rev.get("summary_notes"),
            )
            db.add(new_review)
            created_count += 1

    if created_count > 0:
        await db.commit()

    return APIResponse[None](
        success=True,
        message=f"{created_count} performance reviews imported successfully.",
        data=None,
    )

@router.post(
    "/reviews/{review_id}/evaluate",
    response_model=APIResponse[dict],
    summary="Trigger local LLM performance review and predictions calculation",
)
async def evaluate_review(
    review_id: uuid.UUID,
    body: EvaluateRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    service = PerformanceService(db)
    try:
        review = await service.evaluate_employee_performance(review_id, model=body.model)
    except ValueError as val_err:
        raise HTTPException(status_code=404, detail=str(val_err))

    return APIResponse[dict](
        success=True,
        message="Performance AI evaluation scorecard completed successfully.",
        data={
            "review_id": str(review.id),
            "ai_overall_score": float(review.ai_overall_score) if review.ai_overall_score else None,
            "ai_review_justification": review.ai_review_justification,
            "promotion_recommendation": review.promotion_recommendation,
            "salary_increment_percentage": float(review.salary_increment_percentage) if review.salary_increment_percentage else None,
            "skill_gap_analysis": review.skill_gap_analysis,
            "learning_recommendations": review.learning_recommendations,
            "status": review.status,
        },
        errors=None
    )

@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Get all performance data"
)
async def get_performance_data(
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    # Query reviews
    reviews_stmt = select(PerformanceReview).options(selectinload(PerformanceReview.employee))
    reviews_res = await db.execute(reviews_stmt)
    db_reviews = reviews_res.scalars().all()

    # Query goals
    goals_stmt = select(EmployeePerformanceGoal).options(selectinload(EmployeePerformanceGoal.employee))
    goals_res = await db.execute(goals_stmt)
    db_goals = goals_res.scalars().all()

    # Map reviews to frontend format
    reviews_list = []
    for r in db_reviews:
        if not r.employee:
            continue
        reviews_list.append({
            "id": str(r.id),
            "employeeId": str(r.employee_id),
            "employeeName": f"{r.employee.first_name} {r.employee.last_name}",
            "employeeIdCode": r.employee.employee_id,
            "department": r.employee.department,
            "designation": r.employee.designation,
            "managerName": None,
            "overallRating": float(r.reviewer_rating or r.self_rating) if (r.reviewer_rating or r.self_rating) else None,
            "kpiScore": float(r.ai_overall_score * 20) if r.ai_overall_score else None,
            "productivity": None,
            "attendance": None,
            "communication": None,
            "leadership": None,
            "teamwork": None,
            "innovation": None,
            "problemSolving": None,
            "technicalSkills": None,
            "discipline": None,
            "goalProgress": None,
            "achievements": "",
            "challenges": "",
            "feedback": "",
            "managerComments": r.ai_review_justification or "",
            "promotionEligible": r.promotion_recommendation,
            "promotionStatus": "eligible" if r.promotion_recommendation else "not_recommended",
            "salaryIncrement": float(r.salary_increment_percentage) if r.salary_increment_percentage else None,
            "bonusRecommendation": None,
            "reviewStatus": r.status.lower(),
            "reviewDate": r.created_at.strftime("%Y-%m-%d") if r.created_at else "",
            "lastReview": "",
            "nextReview": "",
            "createdAt": r.created_at.isoformat() if r.created_at else ""
        })

    # Map goals to frontend format
    goals_list = []
    for g in db_goals:
        progress_val = 0
        try:
            progress_val = int(g.current_value)
        except ValueError:
            pass
            
        goals_list.append({
            "id": str(g.id),
            "employeeId": str(g.employee_id),
            "title": g.title,
            "description": g.description or "",
            "progress": progress_val,
            "status": g.status.lower(),
            "priority": "medium",
            "dueDate": g.due_date.strftime("%Y-%m-%d") if g.due_date else "",
            "createdAt": g.created_at.isoformat() if g.created_at else ""
        })

    return APIResponse[dict](
        success=True,
        message="Performance data retrieved.",
        data={
            "reviews": reviews_list,
            "goals": goals_list,
            "feedback360": [],
            "rewards": [],
            "courses": []
        },
        errors=None
    )


# ---------------------------------------------------------------------------
# Batch 6: tenant-safe 360 reviews, calibration, and promotion pipeline
# ---------------------------------------------------------------------------
from app.api.v2.enterprise_dependencies import (
    company_id as _tenant_id, ok as _ok, require_admin as _require_admin,
    require_manager as _require_manager, translate as _translate, user_id as _actor_id,
)
from app.services.performance_service import PerformanceEnterpriseService


class EnterpriseCycleRequest(BaseModel):
    name: str
    start_date: date
    end_date: date
    bell_curve_targets: dict[str, float] | None = None


class Review360Request(BaseModel):
    employee_id: uuid.UUID
    review_type: str


class Review360Submission(BaseModel):
    rating: Decimal = Field(ge=0, le=5)
    comments: str | None = None


class PromotionRequest(BaseModel):
    employee_id: uuid.UUID
    target_band_id: uuid.UUID
    justification: str = Field(min_length=10)


class PromotionDecision(BaseModel):
    stage: str
    approved: bool


# ── Module D: Performance Feedback, Rewards, Training ─────────────────────────

class FeedbackTypeEnum(str):
    EMPLOYEE = "employee"
    MANAGER = "manager"
    PEER = "peer"
    SELF = "self"


class FeedbackCreate(BaseModel):
    employee_id: uuid.UUID
    review_id: uuid.UUID | None = None
    feedback_type: Literal["employee", "manager", "peer", "self"]
    rating: Decimal = Field(ge=0, le=5)
    strengths: str = Field(min_length=1, max_length=2000)
    improvement_areas: str = Field(min_length=1, max_length=2000)
    comments: str | None = Field(default=None, max_length=3000)
    confidential: bool = False


class FeedbackResponse(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    review_id: uuid.UUID | None
    author_id: uuid.UUID
    feedback_type: str
    rating: Decimal
    strengths: str
    improvement_areas: str
    comments: str | None
    confidential: bool
    created_at: datetime
    updated_at: datetime


class RewardCreate(BaseModel):
    employee_id: uuid.UUID
    review_id: uuid.UUID | None = None
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=2000)
    reward_type: Literal["recognition", "award", "bonus", "promotion", "other"]
    monetary_value: Decimal | None = Field(default=None, ge=0)
    effective_date: date
    approval_required: bool = True


class RewardResponse(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    review_id: uuid.UUID | None
    title: str
    description: str
    reward_type: str
    monetary_value: Decimal | None
    effective_date: date
    approval_required: bool
    approved: bool
    approved_by: uuid.UUID | None
    approved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class TrainingAssignmentCreate(BaseModel):
    employee_id: uuid.UUID
    training_id: uuid.UUID
    assigned_by: uuid.UUID
    due_date: date
    priority: Literal["low", "medium", "high", "critical"] = "medium"
    notes: str | None = Field(default=None, max_length=1000)
    review_id: uuid.UUID | None = None


class TrainingAssignmentResponse(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    training_id: uuid.UUID
    assigned_by: uuid.UUID
    assigned_at: datetime
    due_date: date
    priority: str
    status: str
    progress: int
    notes: str | None
    review_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class TrainingAssignmentUpdate(BaseModel):
    status: Literal["assigned", "in_progress", "completed", "cancelled"] | None = None
    progress: int | None = Field(default=None, ge=0, le=100)
    due_date: date | None = None
    notes: str | None = Field(default=None, max_length=1000)


@router.post("/enterprise/cycles", status_code=201)
async def create_enterprise_cycle(body: EnterpriseCycleRequest, claims: Annotated[dict, Depends(get_current_user_claims)], db: Annotated[AsyncSession, Depends(get_db_session)]):
    _require_admin(claims)
    try:
        cycle = await PerformanceEnterpriseService(db).create_cycle(company_id=_tenant_id(claims), **body.model_dump())
        return _ok({"id": str(cycle.id), "status": cycle.status, "bell_curve_targets": cycle.bell_curve_targets})
    except ValueError as exc:
        _translate(exc)


@router.post("/enterprise/cycles/{cycle_id}/reviews", status_code=201)
async def add_360_review(cycle_id: uuid.UUID, body: Review360Request, claims: Annotated[dict, Depends(get_current_user_claims)], db: Annotated[AsyncSession, Depends(get_db_session)]):
    try:
        review = await PerformanceEnterpriseService(db).add_review(
            company_id=_tenant_id(claims), cycle_id=cycle_id, employee_id=body.employee_id,
            reviewer_id=_actor_id(claims), review_type=body.review_type,
        )
        return _ok({"id": str(review.id), "review_type": review.review_type, "status": review.status})
    except (ValueError, LookupError, PermissionError) as exc:
        _translate(exc)


@router.post("/enterprise/reviews/{review_id}/submit")
async def submit_360_review(review_id: uuid.UUID, body: Review360Submission, claims: Annotated[dict, Depends(get_current_user_claims)], db: Annotated[AsyncSession, Depends(get_db_session)]):
    try:
        review = await PerformanceEnterpriseService(db).submit_review(
            review_id, company_id=_tenant_id(claims), reviewer_id=_actor_id(claims),
            rating=float(body.rating), comments=body.comments,
        )
        return _ok({"id": str(review.id), "status": review.status, "rating": float(review.rating)})
    except (ValueError, LookupError, PermissionError) as exc:
        _translate(exc)


@router.post("/enterprise/cycles/{cycle_id}/calibrate")
async def calibrate_enterprise_cycle(cycle_id: uuid.UUID, claims: Annotated[dict, Depends(get_current_user_claims)], db: Annotated[AsyncSession, Depends(get_db_session)]):
    _require_admin(claims)
    try:
        run = await PerformanceEnterpriseService(db).calibrate_cycle(cycle_id, company_id=_tenant_id(claims), actor_id=_actor_id(claims))
        return _ok({"id": str(run.id), "status": run.status, **run.result_json})
    except (ValueError, LookupError) as exc:
        _translate(exc)


@router.post("/enterprise/cycles/{cycle_id}/promotions", status_code=201)
async def create_promotion(cycle_id: uuid.UUID, body: PromotionRequest, claims: Annotated[dict, Depends(get_current_user_claims)], db: Annotated[AsyncSession, Depends(get_db_session)]):
    _require_manager(claims)
    try:
        promotion = await PerformanceEnterpriseService(db).create_promotion_request(
            company_id=_tenant_id(claims), cycle_id=cycle_id, requested_by=_actor_id(claims), **body.model_dump(),
        )
        return _ok({"id": str(promotion.id), "status": promotion.status, "recommended_increment_percentage": float(promotion.recommended_increment_percentage)})
    except (ValueError, LookupError) as exc:
        _translate(exc)


@router.post("/enterprise/promotions/{promotion_id}/decision")
async def decide_promotion(promotion_id: uuid.UUID, body: PromotionDecision, claims: Annotated[dict, Depends(get_current_user_claims)], db: Annotated[AsyncSession, Depends(get_db_session)]):
    _require_manager(claims)
    try:
        promotion = await PerformanceEnterpriseService(db).decide_promotion(
            promotion_id, company_id=_tenant_id(claims), actor_id=_actor_id(claims), **body.model_dump(),
        )
        return _ok({"id": str(promotion.id), "status": promotion.status})
    except (ValueError, LookupError) as exc:
        _translate(exc)


# ── Module D: Performance Feedback, Rewards, Training Assignments ─────────────

@router.post(
    "/feedback",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[FeedbackResponse],
    summary="Submit performance feedback",
)
async def create_feedback(
    body: FeedbackCreate,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[FeedbackResponse]:
    """Submit performance feedback (employee, manager, peer, or self)."""
    author_id = uuid.UUID(claims["sub"]) if claims else None
    if not author_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    # Validate employee exists and belongs to company
    emp_stmt = select(Employee).where(
        Employee.id == body.employee_id,
        Employee.company_id == _tenant_id(claims) if claims else True,
    )
    emp_res = await db.execute(emp_stmt)
    employee = emp_res.scalar_one_or_none()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    # Validate review exists if provided
    if body.review_id:
        review_stmt = select(PerformanceReview).where(
            PerformanceReview.id == body.review_id,
            PerformanceReview.employee_id == body.employee_id,
        )
        review_res = await db.execute(review_stmt)
        review = review_res.scalar_one_or_none()
        if not review:
            raise HTTPException(status_code=404, detail="Review not found for this employee")

    feedback = PerformanceFeedback(
        id=uuid.uuid4(),
        employee_id=body.employee_id,
        review_id=body.review_id,
        author_id=author_id,
        feedback_type=body.feedback_type,
        rating=body.rating,
        strengths=body.strengths,
        improvement_areas=body.improvement_areas,
        comments=body.comments,
        confidential=body.confidential,
    )
    db.add(feedback)
    await db.commit()
    await db.refresh(feedback)

    return APIResponse[FeedbackResponse](
        success=True,
        message="Performance feedback submitted successfully.",
        data=FeedbackResponse(
            id=feedback.id,
            employee_id=feedback.employee_id,
            review_id=feedback.review_id,
            author_id=feedback.author_id,
            feedback_type=feedback.feedback_type,
            rating=feedback.rating,
            strengths=feedback.strengths,
            improvement_areas=feedback.improvement_areas,
            comments=feedback.comments,
            confidential=feedback.confidential,
            created_at=feedback.created_at,
            updated_at=feedback.updated_at,
        ),
        errors=None,
    )


@router.post(
    "/rewards",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[RewardResponse],
    summary="Create performance reward",
)
async def create_reward(
    body: RewardCreate,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[RewardResponse]:
    """Create a performance reward or recognition."""
    # Validate employee exists and belongs to company
    emp_stmt = select(Employee).where(
        Employee.id == body.employee_id,
        Employee.company_id == _tenant_id(claims) if claims else True,
    )
    emp_res = await db.execute(emp_stmt)
    employee = emp_res.scalar_one_or_none()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    # Validate review exists if provided
    if body.review_id:
        review_stmt = select(PerformanceReview).where(
            PerformanceReview.id == body.review_id,
            PerformanceReview.employee_id == body.employee_id,
        )
        review_res = await db.execute(review_stmt)
        review = review_res.scalar_one_or_none()
        if not review:
            raise HTTPException(status_code=404, detail="Review not found for this employee")

    reward = PerformanceReward(
        id=uuid.uuid4(),
        employee_id=body.employee_id,
        review_id=body.review_id,
        title=body.title,
        description=body.description,
        reward_type=body.reward_type,
        monetary_value=body.monetary_value,
        effective_date=body.effective_date,
        approval_required=body.approval_required,
        approved=False,
    )
    db.add(reward)
    await db.commit()
    await db.refresh(reward)

    return APIResponse[RewardResponse](
        success=True,
        message="Performance reward created successfully.",
        data=RewardResponse(
            id=reward.id,
            employee_id=reward.employee_id,
            review_id=reward.review_id,
            title=reward.title,
            description=reward.description,
            reward_type=reward.reward_type,
            monetary_value=reward.monetary_value,
            effective_date=reward.effective_date,
            approval_required=reward.approval_required,
            approved=reward.approved,
            approved_by=reward.approved_by,
            approved_at=reward.approved_at,
            created_at=reward.created_at,
            updated_at=reward.updated_at,
        ),
        errors=None,
    )


@router.post(
    "/training/assign",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[TrainingAssignmentResponse],
    summary="Assign training to employee",
)
async def assign_training(
    body: TrainingAssignmentCreate,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[TrainingAssignmentResponse]:
    """Assign a training course to an employee."""
    # Validate employee exists and belongs to company
    emp_stmt = select(Employee).where(
        Employee.id == body.employee_id,
        Employee.company_id == _tenant_id(claims) if claims else True,
    )
    emp_res = await db.execute(emp_stmt)
    employee = emp_res.scalar_one_or_none()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    # Validate training exists
    training_stmt = select(TrainingCourse).where(TrainingCourse.id == body.training_id)
    training_res = await db.execute(training_stmt)
    training = training_res.scalar_one_or_none()
    if not training:
        raise HTTPException(status_code=404, detail="Training course not found")

    # Validate review exists if provided
    if body.review_id:
        review_stmt = select(PerformanceReview).where(
            PerformanceReview.id == body.review_id,
            PerformanceReview.employee_id == body.employee_id,
        )
        review_res = await db.execute(review_stmt)
        review = review_res.scalar_one_or_none()
        if not review:
            raise HTTPException(status_code=404, detail="Review not found for this employee")

    assignment = TrainingAssignment(
        id=uuid.uuid4(),
        employee_id=body.employee_id,
        training_id=body.training_id,
        assigned_by=body.assigned_by,
        assigned_at=datetime.now(timezone.utc),
        due_date=body.due_date,
        priority=body.priority,
        status="assigned",
        progress=0,
        notes=body.notes,
        review_id=body.review_id,
    )
    db.add(assignment)
    await db.commit()
    await db.refresh(assignment)

    return APIResponse[TrainingAssignmentResponse](
        success=True,
        message="Training assigned successfully.",
        data=TrainingAssignmentResponse(
            id=assignment.id,
            employee_id=assignment.employee_id,
            training_id=assignment.training_id,
            assigned_by=assignment.assigned_by,
            assigned_at=assignment.assigned_at,
            due_date=assignment.due_date,
            priority=assignment.priority,
            status=assignment.status,
            progress=assignment.progress,
            notes=assignment.notes,
            review_id=assignment.review_id,
            created_at=assignment.created_at,
            updated_at=assignment.updated_at,
        ),
        errors=None,
    )


@router.patch(
    "/training/{assignment_id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[TrainingAssignmentResponse],
    summary="Update training assignment",
)
async def update_training_assignment(
    assignment_id: uuid.UUID,
    body: TrainingAssignmentUpdate,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[TrainingAssignmentResponse]:
    """Update training assignment status and progress."""
    stmt = select(TrainingAssignment).where(TrainingAssignment.id == assignment_id)
    res = await db.execute(stmt)
    assignment = res.scalar_one_or_none()
    if not assignment:
        raise HTTPException(status_code=404, detail="Training assignment not found")

    # Validate state transitions
    valid_transitions = {
        "assigned": ["in_progress", "cancelled"],
        "in_progress": ["completed", "cancelled"],
        "completed": [],
        "cancelled": [],
    }

    if body.status and body.status != assignment.status:
        if body.status not in valid_transitions.get(assignment.status, []):
            raise HTTPException(
                status_code=409,
                detail=f"Invalid status transition from {assignment.status} to {body.status}",
            )

    if body.status:
        assignment.status = body.status
    if body.progress is not None:
        assignment.progress = body.progress
        if body.progress >= 100 and assignment.status != "completed":
            assignment.status = "completed"
    if body.due_date:
        assignment.due_date = body.due_date
    if body.notes is not None:
        assignment.notes = body.notes

    assignment.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(assignment)

    return APIResponse[TrainingAssignmentResponse](
        success=True,
        message="Training assignment updated successfully.",
        data=TrainingAssignmentResponse(
            id=assignment.id,
            employee_id=assignment.employee_id,
            training_id=assignment.training_id,
            assigned_by=assignment.assigned_by,
            assigned_at=assignment.assigned_at,
            due_date=assignment.due_date,
            priority=assignment.priority,
            status=assignment.status,
            progress=assignment.progress,
            notes=assignment.notes,
            review_id=assignment.review_id,
            created_at=assignment.created_at,
            updated_at=assignment.updated_at,
        ),
        errors=None,
    )
