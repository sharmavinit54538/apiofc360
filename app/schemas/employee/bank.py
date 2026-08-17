"""EmployeeBankAccount schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from typing import Any
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.employee.constants import ACCOUNT_TYPE_VALUES


class EmployeeBankAccountCreate(BaseModel):
    bank_name: str = Field(..., min_length=1, max_length=150)
    account_holder_name: str | None = Field(None, min_length=1, max_length=150)
    account_number: str = Field(..., min_length=5, max_length=30)
    ifsc_code: str = Field(..., min_length=11, max_length=11, pattern=r"^[A-Z]{4}0[A-Z0-9]{6}$")
    account_type: str = Field("SAVINGS")
    is_primary: bool = False

    @model_validator(mode="before")
    @classmethod
    def normalize_bank_data(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if isinstance(data.get("bank_name"), str):
                data["bank_name"] = data["bank_name"].strip()
            if isinstance(data.get("account_number"), str):
                data["account_number"] = data["account_number"].strip()
            if "account_holder_name" in data and (data["account_holder_name"] is None or str(data["account_holder_name"]).strip() == ""):
                data["account_holder_name"] = None
            elif isinstance(data.get("account_holder_name"), str):
                data["account_holder_name"] = data["account_holder_name"].strip()
        return data

    @field_validator("ifsc_code", mode="before")
    @classmethod
    def normalize_ifsc_code(cls, v: Any) -> str:
        if v is None:
            return ""
        return str(v).strip().upper().replace(" ", "").replace("-", "")

    @field_validator("account_type", mode="before")
    @classmethod
    def validate_account_type(cls, v: Any) -> str:
        if v is None or not str(v).strip():
            return "SAVINGS"
        v_upper = str(v).strip().upper()
        if v_upper not in ACCOUNT_TYPE_VALUES:
            return "SAVINGS"
        return v_upper


class EmployeeBankAccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    employee_id: uuid.UUID
    bank_name: str
    account_holder_name: str | None
    account_number: str
    ifsc_code: str
    account_type: str
    is_primary: bool
    created_at: datetime
    updated_at: datetime
