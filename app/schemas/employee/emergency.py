"""EmployeeEmergencyContact schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, EmailStr


class EmployeeEmergencyContactCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=150)
    relation: str = Field(..., min_length=1, max_length=50)
    phone: str = Field(..., min_length=10, max_length=15)
    alternate_phone: str | None = Field(None, max_length=15)
    email: EmailStr | None = None
    address: str | None = Field(None, max_length=500)


class EmployeeEmergencyContactResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    employee_id: uuid.UUID
    name: str
    relation: str
    phone: str
    alternate_phone: str | None
    email: str | None
    address: str | None
    created_at: datetime
    updated_at: datetime
