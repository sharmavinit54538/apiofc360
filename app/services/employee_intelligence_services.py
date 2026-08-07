"""AI Voice Assistant, Mood Detection, Career Path, and Learning Recommendation services."""
from __future__ import annotations
import json, logging, uuid
from typing import Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.llm.client import get_llm_client
from app.llm.prompts import PromptLibrary
from app.llm.response_parser import ResponseParser
from app.models.voice_assistant import VoiceCommandLog
from app.models.mood_detection import MoodDetectionLog
from app.models.career_path import CareerPathPrediction
from app.models.learning_recommendation import LearningRecommendation

logger = logging.getLogger(__name__)


class VoiceAssistantService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.llm = get_llm_client()

    async def process_command(self, company_id: uuid.UUID, user_id: Optional[uuid.UUID], transcript: str, model: Optional[str] = None) -> VoiceCommandLog:
        try:
            res = await self.llm.complete(PromptLibrary.ai_voice_assistant_user(transcript), system=PromptLibrary.AI_VOICE_ASSISTANT, model=model, json_mode=True, temperature=0.2)
            data = ResponseParser.extract_json_object(res)
        except Exception as e:
            logger.error("VoiceAssistant failed: %s", e)
            data = {"parsed_intent": "UNKNOWN", "parsed_entities": {}, "tts_response": "Sorry, I could not understand that command."}
        log = VoiceCommandLog(id=uuid.uuid4(), company_id=company_id, user_id=user_id, raw_transcript=transcript, parsed_intent=data.get("parsed_intent"), parsed_entities=json.dumps(data.get("parsed_entities", {})), tts_response=data.get("tts_response"))
        self.db.add(log)
        await self.db.commit()
        await self.db.refresh(log)
        return log


class MoodDetectionService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.llm = get_llm_client()

    async def detect_mood(self, company_id: uuid.UUID, employee_id: uuid.UUID, input_source: str, input_text: str, model: Optional[str] = None) -> MoodDetectionLog:
        try:
            res = await self.llm.complete(PromptLibrary.ai_mood_detector_user(input_source, input_text), system=PromptLibrary.AI_MOOD_DETECTOR, model=model, json_mode=True, temperature=0.3)
            data = ResponseParser.extract_json_object(res)
        except Exception as e:
            logger.error("MoodDetection failed: %s", e)
            data = {"detected_mood": "NEUTRAL", "confidence_score": 50, "wellness_recommendations": "Standard wellness check recommended."}
        log = MoodDetectionLog(id=uuid.uuid4(), company_id=company_id, employee_id=employee_id, input_source=input_source.upper(), input_text=input_text, detected_mood=data.get("detected_mood", "NEUTRAL").upper(), confidence_score=int(data.get("confidence_score", 50)), wellness_recommendations=data.get("wellness_recommendations"))
        self.db.add(log)
        await self.db.commit()
        await self.db.refresh(log)
        return log


class CareerPathService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.llm = get_llm_client()

    async def generate_career_path(self, company_id: uuid.UUID, employee_id: uuid.UUID, employee_profile: dict, model: Optional[str] = None) -> CareerPathPrediction:
        try:
            res = await self.llm.complete(PromptLibrary.ai_career_path_user(str(employee_profile)), system=PromptLibrary.AI_CAREER_PATH, model=model, json_mode=True, temperature=0.3)
            data = ResponseParser.extract_json_object(res)
        except Exception as e:
            logger.error("CareerPath failed: %s", e)
            data = {"predicted_next_role": "Senior Role", "promotion_timeline_months": 12, "skill_roadmap": "N/A", "career_growth_narrative": "Standard growth trajectory.", "internal_opportunities": []}
        pred = CareerPathPrediction(id=uuid.uuid4(), company_id=company_id, employee_id=employee_id, predicted_next_role=data.get("predicted_next_role"), promotion_timeline_months=int(data.get("promotion_timeline_months", 12)), skill_roadmap=data.get("skill_roadmap"), career_growth_narrative=data.get("career_growth_narrative"), internal_opportunities=json.dumps(data.get("internal_opportunities", [])))
        self.db.add(pred)
        await self.db.commit()
        await self.db.refresh(pred)
        return pred


class LearningRecommendationService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.llm = get_llm_client()

    async def generate_recommendations(self, company_id: uuid.UUID, employee_id: uuid.UUID, employee_name: str, skill_gaps: list, model: Optional[str] = None) -> LearningRecommendation:
        try:
            res = await self.llm.complete(PromptLibrary.ai_learning_rec_user(employee_name, str(skill_gaps)), system=PromptLibrary.AI_LEARNING_REC, model=model, json_mode=True, temperature=0.3)
            data = ResponseParser.extract_json_object(res)
        except Exception as e:
            logger.error("LearningRec failed: %s", e)
            data = {"recommended_courses": [], "recommended_certifications": [], "recommended_videos": [], "recommended_books": [], "recommended_projects": [], "internal_training": []}
        rec = LearningRecommendation(id=uuid.uuid4(), company_id=company_id, employee_id=employee_id, target_skill_gap=str(skill_gaps), recommended_courses=json.dumps(data.get("recommended_courses", [])), recommended_certifications=json.dumps(data.get("recommended_certifications", [])), recommended_videos=json.dumps(data.get("recommended_videos", [])), recommended_books=json.dumps(data.get("recommended_books", [])), recommended_projects=json.dumps(data.get("recommended_projects", [])), internal_training=json.dumps(data.get("internal_training", [])))
        self.db.add(rec)
        await self.db.commit()
        await self.db.refresh(rec)
        return rec
