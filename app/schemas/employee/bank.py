"""EmployeeBankAccount schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.employee.constants import ACCOUNT_TYPE_VALUES


class EmployeeBankAccountCreate(BaseModel):
    bank_name: str = Field(..., min_length=1, max_length=150)
    account_holder_name: str | None = Field(None, min_length=1, max_length=150)
    account_number: str = Field(..., min_length=5, max_length=30)
    ifsc_code: str = Field(..., min_length=11, max_length=11, pattern=r"^[A-Z]{4}0[A-Z0-9]{6}$")
    account_type: str = Field("SAVINGS")
    is_primary: bool = False

    @field_validator("account_type")
    @classmethod
    def validate_account_type(cls, v: str) -> str:
        v = v.upper()
        if v not in ACCOUNT_TYPE_VALUES:
            raise ValueError("account_type must be SAVINGS or CURRENT")
        return v


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
