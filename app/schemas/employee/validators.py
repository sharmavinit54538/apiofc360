"""Field validators mixin for Employee schemas."""

from __future__ import annotations

from pydantic import field_validator

from app.schemas.employee.constants import (
    EMPLOYMENT_TYPE_VALUES, EMPLOYMENT_STATUS_VALUES, GENDER_VALUES,
    BLOOD_GROUP_VALUES, MARITAL_STATUS_VALUES, ROLE_VALUES
)


class EmployeeValidatorsMixin:
    """Reusable field validators for employee profile fields."""

    @field_validator("employment_type")
    @classmethod
    def validate_employment_type(cls, v: str) -> str:
        v = v.upper()
        if v not in EMPLOYMENT_TYPE_VALUES:
            raise ValueError("employment_type must be one of: " + ", ".join(EMPLOYMENT_TYPE_VALUES))
        return v

    @field_validator("employment_status", check_fields=False)
    @classmethod
    def validate_employment_status(cls, v: str) -> str:
        v = v.upper()
        if v not in EMPLOYMENT_STATUS_VALUES:
            raise ValueError("employment_status must be one of: " + ", ".join(EMPLOYMENT_STATUS_VALUES))
        return v

    @field_validator("gender")
    @classmethod
    def validate_gender(cls, v: str | None) -> str | None:
        if v is None or str(v).strip() == "":
            return None
        v = str(v).strip().upper()
        if v not in GENDER_VALUES:
            raise ValueError("gender must be MALE, FEMALE, or OTHER")
        return v

    @field_validator("blood_group")
    @classmethod
    def validate_blood_group(cls, v: str | None) -> str | None:
        if v is None or str(v).strip() == "":
            return None
        v = str(v).strip().upper()
        if v not in BLOOD_GROUP_VALUES:
            raise ValueError("blood_group must be one of: " + ", ".join(BLOOD_GROUP_VALUES))
        return v

    @field_validator("marital_status")
    @classmethod
    def validate_marital_status(cls, v: str | None) -> str | None:
        if v is None or str(v).strip() == "":
            return None
        v = str(v).strip().upper()
        if v not in MARITAL_STATUS_VALUES:
            raise ValueError("marital_status must be one of: " + ", ".join(MARITAL_STATUS_VALUES))
        return v

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        v = v.lower()
        if v not in ROLE_VALUES:
            raise ValueError("role must be one of: " + ", ".join(ROLE_VALUES))
        return v

    @field_validator("status", check_fields=False)
    @classmethod
    def validate_status(cls, v: str | None) -> str | None:
        if not v or not str(v).strip():
            return None
        norm = str(v).strip().upper().replace(" ", "_")
        return norm
