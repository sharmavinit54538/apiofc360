"""EmployeeEmergencyContact schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from typing import Any
from pydantic import BaseModel, ConfigDict, Field, EmailStr, model_validator


class EmployeeEmergencyContactCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=150)
    relation: str = Field(..., min_length=1, max_length=50)
    phone: str = Field(..., min_length=10, max_length=15)
    alternate_phone: str | None = Field(None, max_length=15)
    email: EmailStr | None = None
    address: str | None = Field(None, max_length=500)

    @model_validator(mode="before")
    @classmethod
    def normalize_emergency_data(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Aliases for name
            if not data.get("name"):
                data["name"] = data.get("emergency_contact_name") or data.get("contact_name") or ""
            if isinstance(data.get("name"), str):
                data["name"] = data["name"].strip()

            # Aliases for phone
            if not data.get("phone"):
                data["phone"] = data.get("emergency_contact_phone") or data.get("contact_phone") or ""
            if isinstance(data.get("phone"), str):
                data["phone"] = data["phone"].strip()

            # Clean empty strings to None
            for fld in ("alternate_phone", "email", "address"):
                if fld in data and (data[fld] is None or str(data[fld]).strip() == ""):
                    data[fld] = None
        return data


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
