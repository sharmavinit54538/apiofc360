"""API v2 routers for: Voice Assistant, Mood Detection, Career Path, Learning Recommendation."""
from __future__ import annotations
import uuid
from typing import Annotated, Optional
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.auth import APIResponse
from app.services.employee_intelligence_services import VoiceAssistantService, MoodDetectionService, CareerPathService, LearningRecommendationService

# ── Voice Assistant ────────────────────────────────────────
voice_router = APIRouter(prefix="/voice", tags=["AI HR Voice Assistant v2"])

class VoiceCommandRequest(BaseModel):
    company_id: uuid.UUID
    user_id: Optional[uuid.UUID] = None
    transcript: str = Field(..., min_length=1)
    model: Optional[str] = None

@voice_router.post("/command", status_code=status.HTTP_201_CREATED, response_model=APIResponse[dict], summary="Process HR voice command transcript")
async def process_voice_command(body: VoiceCommandRequest, claims: Annotated[dict, Depends(get_current_user_claims)] = None, db: Annotated[AsyncSession, Depends(get_db_session)] = None):
    log = await VoiceAssistantService(db).process_command(body.company_id, body.user_id, body.transcript, body.model)
    return APIResponse[dict](success=True, message="Voice command processed.", data={"log_id": str(log.id), "parsed_intent": log.parsed_intent, "tts_response": log.tts_response}, errors=None)

# ── Mood Detection ─────────────────────────────────────────
mood_router = APIRouter(prefix="/mood", tags=["AI Mood Detection Engine v2"])

class MoodDetectRequest(BaseModel):
    company_id: uuid.UUID
    employee_id: uuid.UUID
    input_source: str = Field("CHAT", description="CHAT | VOICE | FEEDBACK | SURVEY | REVIEW")
    input_text: str
    model: Optional[str] = None

@mood_router.post("/detect", status_code=status.HTTP_201_CREATED, response_model=APIResponse[dict], summary="Detect employee mood from text input")
async def detect_mood(body: MoodDetectRequest, claims: Annotated[dict, Depends(get_current_user_claims)] = None, db: Annotated[AsyncSession, Depends(get_db_session)] = None):
    log = await MoodDetectionService(db).detect_mood(body.company_id, body.employee_id, body.input_source, body.input_text, body.model)
    return APIResponse[dict](success=True, message="Mood detected.", data={"log_id": str(log.id), "detected_mood": log.detected_mood, "confidence_score": log.confidence_score, "wellness_recommendations": log.wellness_recommendations}, errors=None)

# ── Career Path ────────────────────────────────────────────
career_router = APIRouter(prefix="/career-path", tags=["AI Career Path Generator v2"])

class CareerPathRequest(BaseModel):
    company_id: uuid.UUID
    employee_id: uuid.UUID
    employee_profile: dict
    model: Optional[str] = None

@career_router.post("/predict", status_code=status.HTTP_201_CREATED, response_model=APIResponse[dict], summary="Predict AI career path for an employee")
async def predict_career_path(body: CareerPathRequest, claims: Annotated[dict, Depends(get_current_user_claims)] = None, db: Annotated[AsyncSession, Depends(get_db_session)] = None):
    pred = await CareerPathService(db).generate_career_path(body.company_id, body.employee_id, body.employee_profile, body.model)
    return APIResponse[dict](success=True, message="Career path predicted.", data={"prediction_id": str(pred.id), "predicted_next_role": pred.predicted_next_role, "promotion_timeline_months": pred.promotion_timeline_months, "career_growth_narrative": pred.career_growth_narrative}, errors=None)


@career_router.get("/predictions", status_code=status.HTTP_200_OK, response_model=APIResponse[list[dict]], summary="Get saved career path predictions for the current employee")
async def get_saved_career_paths(claims: Annotated[dict, Depends(get_current_user_claims)] = None, db: Annotated[AsyncSession, Depends(get_db_session)] = None):
    from app.repositories.employee_repository import EmployeeRepository
    from app.models.career_path import CareerPathPrediction
    from sqlalchemy import select
    
    user_id = uuid.UUID(claims["sub"])
    emp_repo = EmployeeRepository(db)
    emp = await emp_repo.get_by_user_id(user_id)
    if not emp:
        return APIResponse[list[dict]](success=True, message="Employee not found.", data=[], errors=None)
        
    stmt = select(CareerPathPrediction).where(CareerPathPrediction.employee_id == emp.id).order_by(CareerPathPrediction.created_at.desc())
    res = await db.execute(stmt)
    preds = res.scalars().all()
    
    data = []
    for p in preds:
        data.append({
            "id": str(p.id),
            "predicted_next_role": p.predicted_next_role,
            "promotion_timeline_months": p.promotion_timeline_months,
            "career_growth_narrative": p.career_growth_narrative,
            "created_at": p.created_at.isoformat()
        })
        
    return APIResponse[list[dict]](
        success=True,
        message="Saved predictions retrieved.",
        data=data,
        errors=None,
    )

# ── Learning Recommendation ────────────────────────────────
learning_router = APIRouter(prefix="/learning", tags=["AI Learning Recommendation v2"])

class LearningRecRequest(BaseModel):
    company_id: uuid.UUID
    employee_id: uuid.UUID
    employee_name: str
    skill_gaps: list[str]
    model: Optional[str] = None

@learning_router.post("/recommend", status_code=status.HTTP_201_CREATED, response_model=APIResponse[dict], summary="Generate personalized learning recommendations")
async def get_learning_recommendations(body: LearningRecRequest, claims: Annotated[dict, Depends(get_current_user_claims)] = None, db: Annotated[AsyncSession, Depends(get_db_session)] = None):
    rec = await LearningRecommendationService(db).generate_recommendations(body.company_id, body.employee_id, body.employee_name, body.skill_gaps, body.model)
    return APIResponse[dict](success=True, message="Learning recommendations generated.", data={"recommendation_id": str(rec.id), "recommended_courses": rec.recommended_courses, "recommended_certifications": rec.recommended_certifications}, errors=None)


@learning_router.get("/recommendations", status_code=status.HTTP_200_OK, response_model=APIResponse[list[dict]], summary="Get saved learning recommendations for the current employee")
async def get_saved_recommendations(claims: Annotated[dict, Depends(get_current_user_claims)] = None, db: Annotated[AsyncSession, Depends(get_db_session)] = None):
    from app.repositories.employee_repository import EmployeeRepository
    from app.models.learning_recommendation import LearningRecommendation
    from sqlalchemy import select
    import json
    
    user_id = uuid.UUID(claims["sub"])
    emp_repo = EmployeeRepository(db)
    emp = await emp_repo.get_by_user_id(user_id)
    if not emp:
        return APIResponse[list[dict]](success=True, message="Employee not found.", data=[], errors=None)
        
    stmt = select(LearningRecommendation).where(LearningRecommendation.employee_id == emp.id).order_by(LearningRecommendation.created_at.desc())
    res = await db.execute(stmt)
    recs = res.scalars().all()
    
    data = []
    for r in recs:
        try:
            courses = json.loads(r.recommended_courses) if r.recommended_courses else []
        except Exception:
            courses = []
            
        try:
            certs = json.loads(r.recommended_certifications) if r.recommended_certifications else []
        except Exception:
            certs = []

        try:
            projects = json.loads(r.recommended_projects) if r.recommended_projects else []
        except Exception:
            projects = []

        try:
            trainings = json.loads(r.internal_training) if r.internal_training else []
        except Exception:
            trainings = []

        data.append({
            "id": str(r.id),
            "target_skill_gap": r.target_skill_gap,
            "courses": courses,
            "certifications": certs,
            "projects": projects,
            "internal_training": trainings,
            "created_at": r.created_at.isoformat()
        })
        
    return APIResponse[list[dict]](
        success=True,
        message="Saved recommendations retrieved.",
        data=data,
        errors=None,
    )
