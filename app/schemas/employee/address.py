"""EmployeeAddress schemas."""

from __future__ import annotations

from typing import Any
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.employee.constants import ADDRESS_TYPE_VALUES


class EmployeeAddressCreate(BaseModel):
    address_type: str = Field(..., description="CURRENT or PERMANENT")
    address_line_1: str = Field(..., min_length=1, max_length=255)
    address_line_2: str | None = Field(None, max_length=255)
    city: str = Field("Not Specified", max_length=100)
    state: str = Field("Not Specified", max_length=100)
    country: str = Field("India", max_length=100)
    pincode: str = Field("400001", min_length=4, max_length=10)
    is_same_as_current: bool = False

    @field_validator("address_type")
    @classmethod
    def validate_address_type(cls, v: str) -> str:
        v = v.upper()
        if v not in ADDRESS_TYPE_VALUES:
            raise ValueError("address_type must be CURRENT or PERMANENT")
        return v

    @field_validator("city", "state", mode="before")
    @classmethod
    def normalize_location_fields(cls, v: Any) -> str:
        if v is None or not str(v).strip():
            return "Not Specified"
        return str(v).strip()

    @field_validator("pincode", mode="before")
    @classmethod
    def normalize_pincode(cls, v: Any) -> str:
        if v is None or not str(v).strip():
            return "400001"
        return str(v).strip()

    @field_validator("country", mode="before")
    @classmethod
    def normalize_country(cls, v: Any) -> str:
        if v is None or not str(v).strip():
            return "India"
        return str(v).strip()


class EmployeeAddressResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    employee_id: uuid.UUID
    address_type: str
    address_line_1: str
    address_line_2: str | None
    city: str
    state: str
    country: str
    pincode: str
    is_same_as_current: bool
    created_at: datetime
    updated_at: datetime
