"""EmployeeSkill schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.employee.constants import PROFICIENCY_VALUES


class EmployeeSkillCreate(BaseModel):
    skill_name: str = Field(..., min_length=1, max_length=100)
    proficiency: str | None = Field(None)
    years_of_experience: int | None = Field(None, ge=0, le=50)

    @field_validator("proficiency")
    @classmethod
    def validate_proficiency(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.upper()
        if v not in PROFICIENCY_VALUES:
            raise ValueError("proficiency must be BEGINNER, INTERMEDIATE, or EXPERT")
        return v


class EmployeeSkillResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    employee_id: uuid.UUID
    skill_name: str
    proficiency: str | None
    years_of_experience: int | None
    created_at: datetime
    updated_at: datetime
