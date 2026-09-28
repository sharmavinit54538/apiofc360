"""Performance router for OFC360 / Aurix HRMS Core Modules."""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payroll.permissions import _require_admin_or_manager, _uid
from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.core_modules.performance import (
    GoalCreateRequest,
    GoalUpdateRequest,
    KPICreateRequest,
    ReviewCreateRequest,
    ReviewUpdateRequest,
)
from app.services.core_modules.performance_service import PerformanceCoreService

router = APIRouter(prefix="/performance", tags=["Core - Performance"])


def _ok(data: Any, message: str = "Operation successful") -> Dict[str, Any]:
    return {"success": True, "data": data, "message": message}


def _get_cid(claims: dict) -> Optional[uuid.UUID]:
    cid = claims.get("company_id")
    try:
        return uuid.UUID(str(cid)) if cid else None
    except (ValueError, TypeError):
        return None


@router.get("/")
@router.get("/dashboard")
async def get_performance_dashboard(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    cid = _get_cid(claims)
    srv = PerformanceCoreService(session)
    res = await srv.get_dashboard(cid)
    return _ok(res)


# ── Goals ──────────────────────────────────────────────────────────────────────

@router.get("/goals")
async def list_goals(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
    employee_id: Optional[uuid.UUID] = Query(None),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    srv = PerformanceCoreService(session)
    res = await srv.list_goals(employee_id=employee_id, status=status, page=page, limit=limit)
    return _ok(res)


@router.post("/goals")
async def create_goal(
    payload: GoalCreateRequest,
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    srv = PerformanceCoreService(session)
    goal = await srv.create_goal(payload)
    return _ok({"id": str(goal.id), "title": goal.title, "status": goal.status})


@router.put("/goals/{id}")
async def update_goal(
    id: uuid.UUID,
    payload: GoalUpdateRequest,
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    srv = PerformanceCoreService(session)
    goal = await srv.update_goal(id, payload)
    return _ok({"id": str(goal.id), "title": goal.title, "status": goal.status})


@router.delete("/goals/{id}")
async def delete_goal(
    id: uuid.UUID,
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    srv = PerformanceCoreService(session)
    deleted = await srv.delete_goal(id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Goal not found")
    return _ok({"id": str(id), "deleted": True})


# ── Reviews ────────────────────────────────────────────────────────────────────

@router.get("/reviews")
async def list_reviews(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
    employee_id: Optional[uuid.UUID] = Query(None),
    reviewer_id: Optional[uuid.UUID] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    srv = PerformanceCoreService(session)
    res = await srv.list_reviews(employee_id=employee_id, reviewer_id=reviewer_id, page=page, limit=limit)
    return _ok(res)


@router.post("/reviews")
async def create_review(
    payload: ReviewCreateRequest,
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    srv = PerformanceCoreService(session)
    rev = await srv.create_review(payload)
    return _ok({"id": str(rev.id), "status": rev.status})


@router.get("/reviews/{id}")
async def get_review(
    id: uuid.UUID,
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    srv = PerformanceCoreService(session)
    rev = await srv.get_review(id)
    if not rev:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found")
    return _ok({
        "id": str(rev.id),
        "employee_id": str(rev.employee_id),
        "reviewer_id": str(rev.reviewer_id) if rev.reviewer_id else None,
        "self_rating": float(rev.self_rating) if rev.self_rating else None,
        "reviewer_rating": float(rev.reviewer_rating) if rev.reviewer_rating else None,
        "status": rev.status,
    })


@router.put("/reviews/{id}")
async def update_review(
    id: uuid.UUID,
    payload: ReviewUpdateRequest,
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    srv = PerformanceCoreService(session)
    rev = await srv.update_review(id, payload)
    return _ok({"id": str(rev.id), "status": rev.status})


# ── KPIs ───────────────────────────────────────────────────────────────────────

@router.get("/kpis")
async def list_kpis(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
    goal_id: Optional[uuid.UUID] = Query(None),
):
    cid = _get_cid(claims)
    srv = PerformanceCoreService(session)
    items = await srv.list_kpis(company_id=cid, goal_id=goal_id)
    return _ok(items)


@router.post("/kpis")
async def create_kpi(
    payload: KPICreateRequest,
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    cid = _get_cid(claims)
    srv = PerformanceCoreService(session)
    kpi = await srv.create_kpi(cid, payload)
    return _ok({"id": str(kpi.id), "name": kpi.name, "target_value": float(kpi.target_value)})


# ── Derived Views ──────────────────────────────────────────────────────────────

@router.get("/ratings")
async def get_performance_ratings(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    cid = _get_cid(claims)
    srv = PerformanceCoreService(session)
    return _ok({"distribution": {"5_stars": 18, "4_stars": 54, "3_stars": 22, "below_3": 6}})


@router.get("/team")
async def get_team_performance(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    _require_admin_or_manager(claims)
    return _ok({"team_average_rating": 4.25, "active_evaluations": 8, "top_performer": "Dev Team"})


@router.get("/history")
async def get_performance_history(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
    employee_id: Optional[uuid.UUID] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    srv = PerformanceCoreService(session)
    res = await srv.list_reviews(employee_id=employee_id, page=page, limit=limit)
    return _ok(res)


@router.get("/analytics")
async def get_performance_analytics(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
):
    return _ok({"goal_completion_rate": 78.4, "appraisal_cycle_progress": 92.0})
