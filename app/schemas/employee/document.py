"""EmployeeDocument schemas."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from typing import Any
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.employee.constants import DOCUMENT_TYPE_VALUES


class EmployeeDocumentCreate(BaseModel):
    document_type: str = Field(..., description="AADHAAR/PAN/PASSPORT/DRIVING_LICENSE")
    document_number: str | None = Field(None, max_length=100)
    document_url: str | None = Field(None, max_length=500)
    expiry_date: date | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_document_data(cls, data: Any) -> Any:
        if isinstance(data, dict):
            for fld in ("document_number", "document_url", "expiry_date"):
                if fld in data and (data[fld] is None or str(data[fld]).strip() == ""):
                    data[fld] = None
                elif isinstance(data.get(fld), str):
                    data[fld] = data[fld].strip()
        return data

    @field_validator("document_type", mode="before")
    @classmethod
    def validate_document_type(cls, v: Any) -> str:
        if v is None or not str(v).strip():
            return "OTHER"
        v_upper = str(v).strip().upper().replace(" ", "_")
        if v_upper in {"AADHAR", "UIDAI"}:
            return "AADHAAR"
        if v_upper in {"DL", "DRIVERS_LICENSE", "DRIVER_LICENSE"}:
            return "DRIVING_LICENSE"
        if v_upper in {"VOTER", "VOTER_CARD", "EPIC"}:
            return "VOTER_ID"
        if v_upper in DOCUMENT_TYPE_VALUES:
            return v_upper
        return "OTHER"


class EmployeeDocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    employee_id: uuid.UUID
    document_type: str
    document_number: str | None
    document_url: str | None
    expiry_date: date | None
    is_verified: bool
    verified_by: uuid.UUID | None
    verified_at: datetime | None
    created_at: datetime
    updated_at: datetime
