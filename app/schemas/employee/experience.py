"""EmployeeExperience schemas."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EmployeeExperienceCreate(BaseModel):
    company_name: str = Field(..., min_length=1, max_length=255)
    designation: str = Field("Employee", min_length=1, max_length=150)
    employment_type: str | None = Field(None, max_length=30)
    start_date: date = Field(default_factory=date.today)
    end_date: date | None = None
    is_current: bool = False
    description: str | None = None

    @model_validator(mode="before")
    @classmethod
    def map_frontend_fields(cls, data: Any) -> Any:
        from typing import Any
        if isinstance(data, dict):
            if "job_title" in data and ("designation" not in data or not data["designation"]):
                data["designation"] = data["job_title"]
            if "tenure_months" in data and ("start_date" not in data or not data["start_date"]):
                from datetime import date, timedelta
                tenure = data.get("tenure_months", 12)
                data["start_date"] = date.today() - timedelta(days=int(tenure) * 30)
        return data

    @model_validator(mode="after")
    def validate_dates(self) -> EmployeeExperienceCreate:
        if self.end_date and self.start_date and self.end_date < self.start_date:
            raise ValueError("end_date must be after start_date")
        if self.is_current and self.end_date:
            raise ValueError("is_current cannot be True when end_date is set")
        return self


class EmployeeExperienceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    employee_id: uuid.UUID
    company_name: str
    designation: str
    employment_type: str | None
    start_date: date
    end_date: date | None
    is_current: bool
    description: str | None
    created_at: datetime
    updated_at: datetime
