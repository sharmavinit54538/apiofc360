"""EmployeeSkill schemas."""

from __future__ import annotations

from typing import Any
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.employee.constants import PROFICIENCY_VALUES


class EmployeeSkillCreate(BaseModel):
    skill_name: str = Field(..., min_length=1, max_length=100)
    proficiency: str | None = Field(None)
    years_of_experience: int | None = Field(None, ge=0, le=50)

    @model_validator(mode="before")
    @classmethod
    def normalize_skill_data(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Support aliases for skill_name
            if "skill_name" not in data or not data["skill_name"]:
                if "name" in data and data["name"]:
                    data["skill_name"] = str(data["name"]).strip()
                elif "skill" in data and data["skill"]:
                    data["skill_name"] = str(data["skill"]).strip()
            elif isinstance(data.get("skill_name"), str):
                data["skill_name"] = data["skill_name"].strip()

            # Handle years_of_experience
            yoe = data.get("years_of_experience") if "years_of_experience" in data else (data.get("experience_years") or data.get("years"))
            if yoe is not None:
                if str(yoe).strip() == "":
                    data["years_of_experience"] = None
                else:
                    try:
                        data["years_of_experience"] = int(float(str(yoe).strip()))
                    except (ValueError, TypeError):
                        data["years_of_experience"] = None
        return data

    @field_validator("proficiency")
    @classmethod
    def validate_proficiency(cls, v: Any) -> str | None:
        if v is None:
            return None
        v_str = str(v).strip()
        if not v_str:
            return None
        v_upper = v_str.upper()
        if v_upper in {"BEGINNER", "BASIC", "NOVICE", "ENTRY", "LEARNER", "JUNIOR"}:
            return "BEGINNER"
        if v_upper in {"INTERMEDIATE", "MID", "MEDIUM", "MED"}:
            return "INTERMEDIATE"
        if v_upper in {"ADVANCED", "SENIOR", "HIGH", "PROFICIENT"}:
            return "ADVANCED"
        if v_upper in {"EXPERT", "MASTER", "LEAD"}:
            return "EXPERT"
        if v_upper in PROFICIENCY_VALUES:
            return v_upper
        raise ValueError("proficiency must be BEGINNER, INTERMEDIATE, ADVANCED, or EXPERT")


class EmployeeSkillResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    employee_id: uuid.UUID
    skill_name: str
    proficiency: str | None
    years_of_experience: int | None
    created_at: datetime
    updated_at: datetime
