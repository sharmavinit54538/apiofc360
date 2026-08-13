"""Field validators mixin for Employee schemas."""

from __future__ import annotations

from decimal import Decimal
from pydantic import field_validator, model_validator

from app.schemas.employee.constants import (
    EMPLOYMENT_TYPE_VALUES, EMPLOYMENT_STATUS_VALUES, GENDER_VALUES,
    BLOOD_GROUP_VALUES, MARITAL_STATUS_VALUES, ROLE_VALUES
)


class EmployeeValidatorsMixin:
    """Reusable field validators for employee profile fields."""

    @field_validator("employment_type")
    @classmethod
    def validate_employment_type(cls, v: str | None) -> str | None:
        if v is None or str(v).strip() == "":
            return None
        v = v.upper()
        if v not in EMPLOYMENT_TYPE_VALUES:
            raise ValueError("employment_type must be one of: " + ", ".join(EMPLOYMENT_TYPE_VALUES))
        return v

    @field_validator("employment_status", check_fields=False)
    @classmethod
    def validate_employment_status(cls, v: str | None) -> str | None:
        if v is None or str(v).strip() == "":
            return None
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

    @field_validator("role", check_fields=False)
    @classmethod
    def validate_role(cls, v: str | None) -> str | None:
        if v is None or str(v).strip() == "":
            return None
        v_str = str(v).strip()
        v_lower = v_str.lower()
        if v_lower in ROLE_VALUES:
            return v_lower
        raise ValueError("role must be one of: super_admin, hr_admin, manager, employee, executive, it_admin")


    @field_validator("status", check_fields=False)
    @classmethod
    def validate_status(cls, v: str | None) -> str | None:
        if not v or not str(v).strip():
            return None
        norm = str(v).strip().upper().replace(" ", "_")
        return norm

    @model_validator(mode="after")
    def validate_salary_sanity(self) -> EmployeeValidatorsMixin:
        """Ensure individual salary components and combined breakups are realistic against CTC."""
        ctc = getattr(self, "ctc", None)
        if ctc is None:
            return self

        ctc_dec = Decimal(str(ctc))

        # 1. Individual check: hra, bonus, basic_salary, pf, esi, professional_tax must each be <= ctc if set
        salary_fields = ["hra", "bonus", "basic_salary", "pf", "esi", "professional_tax"]
        for field_name in salary_fields:
            val = getattr(self, field_name, None)
            if val is not None:
                val_dec = Decimal(str(val))
                if val_dec > ctc_dec:
                    raise ValueError(f"{field_name} ({val}) cannot exceed ctc ({ctc})")

        # 2. Combined check: basic_salary + hra + bonus should not exceed ctc by >1%
        basic = getattr(self, "basic_salary", None)
        hra = getattr(self, "hra", None)
        bonus = getattr(self, "bonus", None)

        basic_dec = Decimal(str(basic)) if basic is not None else Decimal("0")
        hra_dec = Decimal(str(hra)) if hra is not None else Decimal("0")
        bonus_dec = Decimal(str(bonus)) if bonus is not None else Decimal("0")

        combined = basic_dec + hra_dec + bonus_dec
        max_allowed = ctc_dec * Decimal("1.01")
        if combined > max_allowed:
            raise ValueError("basic_salary + hra + bonus exceeds ctc — check the compensation breakup")

        return self

