"""EmployeeEducation schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class EmployeeEducationCreate(BaseModel):
    degree: str = Field(..., min_length=1, max_length=150)
    institution: str = Field(..., min_length=1, max_length=255)
    field_of_study: str | None = Field(None, max_length=150)
    start_year: int | None = Field(None, ge=1950, le=2100)
    end_year: int | None = Field(None, ge=1950, le=2100)
    grade: str | None = Field(None, max_length=50)
    certificate_url: str | None = Field(None, max_length=500)


class EmployeeEducationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    employee_id: uuid.UUID
    degree: str
    institution: str
    field_of_study: str | None
    start_year: int | None
    end_year: int | None
    grade: str | None
    certificate_url: str | None
    created_at: datetime
    updated_at: datetime
