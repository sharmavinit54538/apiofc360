"""EmployeeEducation schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from typing import Any
from pydantic import BaseModel, ConfigDict, Field, model_validator


class EmployeeEducationCreate(BaseModel):
    degree: str = Field(..., min_length=1, max_length=150)
    institution: str = Field(..., min_length=1, max_length=255)
    field_of_study: str | None = Field(None, max_length=150)
    start_year: int | None = Field(None, ge=1950, le=2100)
    end_year: int | None = Field(None, ge=1950, le=2100)
    grade: str | None = Field(None, max_length=50)
    certificate_url: str | None = Field(None, max_length=500)

    @model_validator(mode="before")
    @classmethod
    def normalize_education_data(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Strip strings
            if isinstance(data.get("degree"), str):
                data["degree"] = data["degree"].strip()
            if isinstance(data.get("institution"), str):
                data["institution"] = data["institution"].strip()

            # Parse start_year and end_year
            for year_fld in ("start_year", "end_year"):
                val = data.get(year_fld)
                if val is not None:
                    s_val = str(val).strip()
                    if not s_val:
                        data[year_fld] = None
                    elif s_val.isdigit():
                        data[year_fld] = int(s_val)
                    elif len(s_val) >= 4 and s_val[:4].isdigit():
                        data[year_fld] = int(s_val[:4])
                    else:
                        try:
                            data[year_fld] = int(float(s_val))
                        except (ValueError, TypeError):
                            data[year_fld] = None

            # Clean empty strings to None
            for fld in ("field_of_study", "grade", "certificate_url"):
                if fld in data and (data[fld] is None or str(data[fld]).strip() == ""):
                    data[fld] = None
        return data


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
