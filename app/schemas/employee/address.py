"""EmployeeAddress schemas."""

from __future__ import annotations

from typing import Any
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.employee.constants import ADDRESS_TYPE_VALUES


class EmployeeAddressCreate(BaseModel):
    address_type: str = Field("CURRENT", description="CURRENT or PERMANENT")
    address_line_1: str = Field(..., min_length=1, max_length=255)
    address_line_2: str | None = Field(None, max_length=255)
    city: str = Field("Not Specified", max_length=100)
    state: str = Field("Not Specified", max_length=100)
    country: str = Field("India", max_length=100)
    pincode: str = Field("400001", min_length=4, max_length=10)
    is_same_as_current: bool = False

    @model_validator(mode="before")
    @classmethod
    def normalize_address_data(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Aliases for address_line_1
            if not data.get("address_line_1"):
                data["address_line_1"] = data.get("address1") or data.get("address_1") or data.get("line1") or data.get("street") or ""
            if isinstance(data.get("address_line_1"), str):
                data["address_line_1"] = data["address_line_1"].strip()

            # Aliases for address_line_2
            if not data.get("address_line_2"):
                data["address_line_2"] = data.get("address2") or data.get("address_2") or data.get("line2") or None
            if data.get("address_line_2") is not None and str(data["address_line_2"]).strip() == "":
                data["address_line_2"] = None
            elif isinstance(data.get("address_line_2"), str):
                data["address_line_2"] = data["address_line_2"].strip()

            # Aliases for pincode
            if not data.get("pincode"):
                data["pincode"] = data.get("postal_code") or data.get("postalCode") or data.get("zip") or data.get("zipcode") or data.get("zip_code") or "400001"

            # Clean address_type
            if not data.get("address_type") or str(data.get("address_type")).strip() == "":
                data["address_type"] = "CURRENT"
        return data

    @field_validator("address_type", mode="before")
    @classmethod
    def validate_address_type(cls, v: Any) -> str:
        if v is None or not str(v).strip():
            return "CURRENT"
        v_upper = str(v).strip().upper()
        if v_upper not in ADDRESS_TYPE_VALUES:
            return "CURRENT"
        return v_upper

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
