"""EmployeeDocument schemas."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.employee.constants import DOCUMENT_TYPE_VALUES


class EmployeeDocumentCreate(BaseModel):
    document_type: str = Field(..., description="AADHAAR/PAN/PASSPORT/DRIVING_LICENSE")
    document_number: str | None = Field(None, max_length=100)
    document_url: str | None = Field(None, max_length=500)
    expiry_date: date | None = None

    @field_validator("document_type")
    @classmethod
    def validate_document_type(cls, v: str) -> str:
        v = v.upper()
        if v not in DOCUMENT_TYPE_VALUES:
            raise ValueError("document_type must be one of: " + ", ".join(DOCUMENT_TYPE_VALUES))
        return v


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
