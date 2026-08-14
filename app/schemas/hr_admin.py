"""Schemas for HR Admin internal user management."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.models.user.role import UserRole
from app.utils.validators import normalize_email, validate_phone

# Allowed roles for HR Admin internal user creation
ALLOWED_HR_ADMIN_ROLES = {
    UserRole.EMPLOYEE.value,
    UserRole.MANAGER.value,
    UserRole.EXECUTIVE.value,
    UserRole.IT_ADMIN.value,
}


class HRAdminCreateUserRequest(BaseModel):
    """Payload for HR Admin to create internal company users."""

    model_config = ConfigDict(extra="ignore")

    first_name: str = Field(..., min_length=1, max_length=50, examples=["Rahul"])
    last_name: str = Field(default="", max_length=50, examples=["Sharma"])
    email: EmailStr = Field(..., examples=["rahul@example.com"])
    phone: str | None = Field(default=None, examples=["9876543210"])
    role: str = Field(
        ...,
        examples=["EMPLOYEE"],
        description="Allowed roles: EMPLOYEE, MANAGER, EXECUTIVE, IT_ADMIN",
    )
    department: str | None = Field(default=None, examples=["Engineering"])
    designation: str | None = Field(default=None, examples=["Software Engineer"])
    employment_type: str = Field(default="FULL_TIME", examples=["FULL_TIME", "PART_TIME", "CONTRACT"])
    joining_date: date | None = Field(default=None, examples=["2026-08-15"])
    basic_salary: Decimal | None = Field(default=None, ge=0)
    ctc: Decimal | None = Field(default=None, ge=0)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email_field(cls, value: str) -> str:
        return normalize_email(value)

    @field_validator("phone", mode="before")
    @classmethod
    def normalize_phone_field(cls, value: Any) -> str | None:
        if not value:
            return None
        return validate_phone(value)

    @field_validator("role")
    @classmethod
    def validate_role_field(cls, value: str) -> str:
        clean_role = str(value or "").strip().lower()
        if clean_role not in ALLOWED_HR_ADMIN_ROLES:
            raise ValueError(
                "Role must be one of: EMPLOYEE, MANAGER, EXECUTIVE, IT_ADMIN. "
                "HR Admins cannot create Super Admin or HR Admin accounts."
            )
        return clean_role


class HRAdminUpdateUserRequest(BaseModel):
    """Payload for HR Admin to update an existing internal company user."""

    model_config = ConfigDict(extra="ignore")

    first_name: str | None = Field(default=None, max_length=50)
    last_name: str | None = Field(default=None, max_length=50)
    phone: str | None = Field(default=None)
    role: str | None = Field(default=None, description="Allowed roles: EMPLOYEE, MANAGER, EXECUTIVE, IT_ADMIN")
    department: str | None = Field(default=None)
    designation: str | None = Field(default=None)
    account_status: str | None = Field(default=None, examples=["ACTIVE", "SUSPENDED", "DEACTIVATED", "INVITED"])
    is_active: bool | None = Field(default=None)

    @field_validator("phone", mode="before")
    @classmethod
    def normalize_phone_field(cls, value: Any) -> str | None:
        if not value:
            return None
        return validate_phone(value)

    @field_validator("role")
    @classmethod
    def validate_role_field(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean_role = str(value).strip().lower()
        if clean_role not in ALLOWED_HR_ADMIN_ROLES:
            raise ValueError(
                "Role must be one of: EMPLOYEE, MANAGER, EXECUTIVE, IT_ADMIN. "
                "HR Admins cannot assign Super Admin or HR Admin roles."
            )
        return clean_role


class HRAdminUserResponse(BaseModel):
    """Safe response payload representing a company user."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    first_name: str | None = None
    last_name: str | None = None
    email: EmailStr
    phone: str | None = None
    role: str
    department: str | None = None
    designation: str | None = None
    account_status: str = "ACTIVE"
    is_active: bool = True
    is_verified: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_login_at: datetime | None = None
    employee_id: str | None = None


class HRAdminUserListResponse(BaseModel):
    """Paginated user listing response."""

    items: list[HRAdminUserResponse]
    total: int
    page: int
    page_size: int
