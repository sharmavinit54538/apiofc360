"""Employee onboarding and policy schemas."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator


class EmployeeLeavePolicyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    employee_id: uuid.UUID
    leave_type: str
    total_days: Decimal
    used_days: Decimal
    carry_forward: bool
    effective_from: date | None = None
    effective_to: date | None = None
    created_at: datetime
    updated_at: datetime


class EmployeeOnboardingStepResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    step_name: str
    step_order: int
    is_required: bool
    is_completed: bool
    completed_at: datetime | None
    status: str
    notes: str | None
    verified_at: datetime | None


class EmployeeOnboardingStatusResponse(BaseModel):
    employee_id: uuid.UUID
    status: str
    total_steps: int
    completed_steps: int
    completion_percentage: float
    steps: list[EmployeeOnboardingStepResponse]


class ActivateEmployeeRequest(BaseModel):
    token: str = Field(..., min_length=10)
    new_password: str = Field(..., min_length=8, max_length=128)
    confirm_password: str = Field(..., min_length=8, max_length=128)

    @field_validator("new_password", mode="after")
    @classmethod
    def validate_password_complexity(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long.")
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter.")
        if not any(c.islower() for c in v):
            raise ValueError("Password must contain at least one lowercase letter.")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one number.")
        if not any(not c.isalnum() for c in v):
            raise ValueError("Password must contain at least one special character.")
        return v

    @model_validator(mode="after")
    def passwords_match(self) -> ActivateEmployeeRequest:
        if self.new_password != self.confirm_password:
            raise ValueError("Passwords do not match.")
        return self


class ActivateOnboardingRequest(BaseModel):
    token: str = Field(..., min_length=10)
    password: str = Field(..., min_length=8, max_length=128)
    phone: str | None = Field(None, max_length=30)
    emergency_contact_name: str | None = Field(None, max_length=150)
    emergency_contact_phone: str | None = Field(None, max_length=30)
    profile_photo_url: str | None = Field(None, max_length=500)

    @field_validator("password", mode="after")
    @classmethod
    def validate_password_complexity(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long.")
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter.")
        if not any(c.islower() for c in v):
            raise ValueError("Password must contain at least one lowercase letter.")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one number.")
        if not any(not c.isalnum() for c in v):
            raise ValueError("Password must contain at least one special character.")
        return v

    @field_validator("phone", "emergency_contact_phone", mode="before")
    @classmethod
    def clean_optional_phones(cls, v: Any) -> Any:
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return None
        return v

    @field_validator("phone", mode="after")
    @classmethod
    def validate_phone(cls, v: Any) -> Any:
        if v is not None:
            cleaned = "".join(c for c in v if c.isdigit())
            if not cleaned:
                return None
            if len(cleaned) < 10:
                raise ValueError("Phone number must contain at least 10 digits.")
            if len(cleaned) > 15:
                raise ValueError("Phone number must contain at most 15 digits.")
            return cleaned
        return v

    @field_validator("emergency_contact_phone", mode="after")
    @classmethod
    def validate_emergency_phone(cls, v: Any) -> Any:
        if v is not None:
            cleaned = "".join(c for c in v if c.isdigit())
            if not cleaned:
                return None
            if len(cleaned) < 10:
                raise ValueError("Emergency contact phone must contain at least 10 digits.")
            if len(cleaned) > 15:
                raise ValueError("Emergency contact phone must contain at most 15 digits.")
            return cleaned
        return v


class ApproveRejectRequest(BaseModel):
    reason: str | None = Field(None, max_length=1000)


class DeactivateEmployeeRequest(BaseModel):
    reason: str = Field(..., min_length=2, max_length=1000)

