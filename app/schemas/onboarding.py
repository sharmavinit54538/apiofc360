"""Pydantic schemas for the HR Admin Onboarding Flow.

Production-ready schemas supporting all 6 onboarding stages:
1. Admin Profile
2. Company Setup
3. Organization & Departments
4. Work Schedule & Leave Policies
5. Employee Invitations (Individual Only)
6. Review & Activate
"""

from __future__ import annotations

from datetime import datetime
import re
from typing import Any, Generic, TypeVar
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AliasChoices, BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator


T = TypeVar("T")


class OnboardingRequestModel(BaseModel):
    """Base request contract for onboarding writes.

    Rejecting unknown fields is deliberate: silently accepting a misspelled
    field makes a successful-looking onboarding request lose data.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


# ─────────────────────────────────────────────────────────────────────────────
# API Response Envelopes
# ─────────────────────────────────────────────────────────────────────────────

class APIErrorDetail(BaseModel):
    """Detailed error object matching the required API contract."""
    code: str
    message: str
    fields: dict[str, Any] = {}


class OnboardingAPIResponse(BaseModel, Generic[T]):
    """Standardized onboarding API response envelope."""

    success: bool
    message: str
    data: T
    current_step: int | None = None
    onboarding_completed: bool | None = None
    redirect_step: int | None = None
    error: APIErrorDetail | None = None


# ─────────────────────────────────────────────────────────────────────────────
# 1. Admin Profile Schemas
# ─────────────────────────────────────────────────────────────────────────────

class HRAdminProfileInput(OnboardingRequestModel):
    """Payload to create or update HR Admin Profile."""

    first_name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        validation_alias=AliasChoices("first_name", "firstName", "name"),
        description="Admin first name",
    )
    last_name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        validation_alias=AliasChoices("last_name", "lastName"),
        description="Admin last name",
    )
    work_email: EmailStr | None = Field(
        default=None,
        validation_alias=AliasChoices("work_email", "workEmail", "email"),
        description="Admin work email",
    )
    phone_number: str = Field(
        ...,
        min_length=7,
        max_length=20,
        validation_alias=AliasChoices("phone_number", "phoneNumber", "phone", "mobile", "mobile_number", "mobileNumber"),
        description="Contact phone number",
    )
    job_title: str | None = Field(
        default="HR Admin",
        max_length=100,
        validation_alias=AliasChoices("job_title", "jobTitle", "designation", "role_title"),
        description="Job title / Designation",
    )
    profile_photo_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("profile_photo_url", "profilePhotoUrl", "profile_photo", "profilePhoto", "photo", "avatar"),
        description="Profile photo URL",
    )

    @field_validator("phone_number")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        clean = "".join(ch for ch in str(v).strip() if ch.isdigit() or ch in "+ -()")
        digits = "".join(filter(str.isdigit, clean))
        if len(digits) < 7:
            raise ValueError("Phone number must contain at least 7 digits.")
        return clean


class HRAdminProfileResponse(BaseModel):
    """Response containing HR Admin Profile data."""

    first_name: str
    last_name: str
    work_email: str
    phone_number: str
    job_title: str
    profile_photo_url: str | None = None
    organization_id: str | None = None


# Compatibility alias for existing codebase
AdminProfileStepInput = HRAdminProfileInput


# ─────────────────────────────────────────────────────────────────────────────
# 2. Organization / Company Schemas
# ─────────────────────────────────────────────────────────────────────────────

class OrganizationInput(OnboardingRequestModel):
    """Payload to create or update Company / Organization data."""

    company_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        validation_alias=AliasChoices("company_name", "companyName", "name", "title"),
        description="Company / Organization name",
    )
    legal_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        validation_alias=AliasChoices("legal_name", "legalName"),
    )
    industry: str | None = Field(default=None, max_length=100)
    company_size: str | None = Field(
        default=None,
        validation_alias=AliasChoices("company_size", "companySize", "size"),
    )
    website: str | None = Field(default=None, max_length=255)
    country: str = Field(default="India", max_length=100)
    address: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=100)
    state: str | None = Field(default=None, max_length=100)
    zip_code: str | None = Field(
        default=None,
        max_length=20,
        validation_alias=AliasChoices("zip_code", "zipCode", "postal_code", "postalCode", "pinCode"),
    )
    cin: str | None = Field(
        default=None,
        max_length=50,
        validation_alias=AliasChoices("cin", "cin_number", "cinNumber"),
    )
    gst_number: str | None = Field(
        default=None,
        max_length=50,
        validation_alias=AliasChoices("gst_number", "gstNumber", "gst"),
    )
    company_logo_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("company_logo_url", "companyLogoUrl", "company_logo", "companyLogo", "logo"),
    )
    company_stamp_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("company_stamp_url", "companyStampUrl", "company_stamp", "companyStamp", "stamp"),
    )
    timezone: str | None = Field(default=None, max_length=50, description="Organization primary timezone")
    currency: str | None = Field(default=None, max_length=10, description="Organization base currency")

    @field_validator("website")
    @classmethod
    def validate_website(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        value = value.strip()
        if not re.fullmatch(r"https?://[^\s/$.?#][^\s]*", value, flags=re.IGNORECASE):
            raise ValueError("Website must be a valid http(s) URL.")
        return value

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            ZoneInfo(value.strip())
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Timezone must be a valid IANA timezone.") from exc
        return value.strip()

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().upper()
        if not re.fullmatch(r"[A-Z]{3}", value):
            raise ValueError("Currency must be a three-letter ISO 4217 code.")
        return value


class OrganizationSummary(BaseModel):
    """Lightweight summary of organization for status and progress responses."""

    id: str
    name: str
    company_name: str | None = None


class OrganizationResponse(BaseModel):
    """Response containing Organization details."""

    id: str
    name: str = ""
    company_name: str = ""
    legal_name: str | None = None
    industry: str | None = None
    company_size: str | None = None
    website: str | None = None
    country: str = "India"
    address: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    cin: str | None = None
    gst_number: str | None = None
    company_logo_url: str | None = None
    company_stamp_url: str | None = None
    timezone: str | None = None
    currency: str | None = None
    status: str = "PENDING"
    onboarding_completed: bool = False
    organization: dict[str, Any] | None = None


# Compatibility alias for existing codebase
CompanyStepInput = OrganizationInput


# ─────────────────────────────────────────────────────────────────────────────
# 3. Department Schemas
# ─────────────────────────────────────────────────────────────────────────────

class DepartmentCreateInput(OnboardingRequestModel):
    """Payload to create a single department."""

    department_name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        validation_alias=AliasChoices("department_name", "departmentName", "name"),
    )
    department_code: str | None = Field(
        default=None,
        max_length=30,
        validation_alias=AliasChoices("department_code", "departmentCode", "code"),
    )
    description: str | None = Field(default="", max_length=1000)
    location: str | None = Field(default="Headquarters", max_length=100)


class DepartmentUpdateInput(OnboardingRequestModel):
    """Payload to update an existing department."""

    department_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        validation_alias=AliasChoices("department_name", "departmentName", "name"),
    )
    department_code: str | None = Field(
        default=None,
        max_length=30,
        validation_alias=AliasChoices("department_code", "departmentCode", "code"),
    )
    description: str | None = Field(default=None, max_length=1000)
    location: str | None = Field(default=None, max_length=100)
    status: str | None = Field(default=None, max_length=20)


class DepartmentItemResponse(BaseModel):
    """Department item representation."""

    id: str
    company_id: str
    department_name: str
    department_code: str
    description: str | None = None
    location: str = "Headquarters"
    status: str = "ACTIVE"
    employee_count: int = 0
    created_at: str | None = None


# Compatibility aliases for existing batch step endpoint
class DepartmentStepInput(OnboardingRequestModel):
    department_code: str = Field(default="", validation_alias=AliasChoices("department_code", "departmentCode", "code"))
    department_name: str = Field(default="", validation_alias=AliasChoices("department_name", "departmentName", "name"))
    description: str = Field(default="")


class DepartmentStepInputList(OnboardingRequestModel):
    departments: list[DepartmentStepInput] = Field(default=[])


# ─────────────────────────────────────────────────────────────────────────────
# 4. Designation Schemas
# ─────────────────────────────────────────────────────────────────────────────

class DesignationCreateInput(OnboardingRequestModel):
    """Payload to create a designation."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        validation_alias=AliasChoices("name", "designation_name", "designationName", "title"),
    )
    description: str | None = Field(default=None, max_length=255)


class DesignationUpdateInput(OnboardingRequestModel):
    """Payload to update a designation."""

    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        validation_alias=AliasChoices("name", "designation_name", "designationName", "title"),
    )
    description: str | None = Field(default=None, max_length=255)


class DesignationItemResponse(BaseModel):
    """Designation item representation."""

    id: str
    company_id: str
    name: str
    description: str | None = None
    created_at: str | None = None


# Compatibility aliases for batch step
class DesignationStepInputList(OnboardingRequestModel):
    designations: list[str] = Field(default=[])


# ─────────────────────────────────────────────────────────────────────────────
# 5. Work Schedule & HR Settings Schemas
# ─────────────────────────────────────────────────────────────────────────────

VALID_DAYS = {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"}


class WorkScheduleInput(OnboardingRequestModel):
    """Payload for Work Schedule and HR Settings configuration."""

    timezone: str = Field(
        default="Asia/Kolkata",
        max_length=50,
        validation_alias=AliasChoices("timezone", "time_zone", "timeZone"),
    )
    currency: str = Field(
        default="INR",
        max_length=10,
        validation_alias=AliasChoices("currency", "currencyCode"),
    )
    date_format: str = Field(
        default="YYYY-MM-DD",
        max_length=20,
        validation_alias=AliasChoices("date_format", "dateFormat"),
    )
    time_format: str = Field(
        default="12h",
        max_length=20,
        validation_alias=AliasChoices("time_format", "timeFormat"),
    )
    financial_year: str = Field(
        default="2026-2027",
        max_length=30,
        validation_alias=AliasChoices("financial_year", "financialYear"),
    )
    week_start_day: str = Field(
        default="Monday",
        max_length=20,
        validation_alias=AliasChoices("week_start_day", "weekStartDay"),
    )
    working_days: list[str] = Field(
        default_factory=lambda: ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
        validation_alias=AliasChoices("working_days", "workingDays"),
    )
    office_start_time: str = Field(
        default="09:00",
        max_length=10,
        validation_alias=AliasChoices("office_start_time", "officeStartTime", "start_time", "startTime"),
    )
    office_end_time: str = Field(
        default="18:00",
        max_length=10,
        validation_alias=AliasChoices("office_end_time", "officeEndTime", "end_time", "endTime"),
    )
    default_shift: str = Field(
        default="General Shift",
        max_length=50,
        validation_alias=AliasChoices("default_shift", "defaultShift", "shift"),
    )
    leave_policy_template: str | None = Field(
        default=None,
        max_length=100,
        validation_alias=AliasChoices("leave_policy_template", "leavePolicyTemplate"),
    )

    @field_validator("timezone")
    @classmethod
    def validate_schedule_timezone(cls, value: str) -> str:
        value = value.strip()
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Timezone must be a valid IANA timezone.") from exc
        return value

    @field_validator("currency")
    @classmethod
    def validate_schedule_currency(cls, value: str) -> str:
        value = value.strip().upper()
        if not re.fullmatch(r"[A-Z]{3}", value):
            raise ValueError("Currency must be a three-letter ISO 4217 code.")
        return value

    @field_validator("date_format")
    @classmethod
    def validate_date_format(cls, value: str) -> str:
        value = value.strip()
        if value not in {"YYYY-MM-DD", "DD/MM/YYYY", "MM/DD/YYYY", "DD-MM-YYYY"}:
            raise ValueError("Unsupported date format.")
        return value

    @field_validator("time_format")
    @classmethod
    def validate_time_format(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in {"12h", "24h"}:
            raise ValueError("Time format must be either '12h' or '24h'.")
        return value

    @field_validator("week_start_day")
    @classmethod
    def validate_week_start_day(cls, value: str) -> str:
        value = value.strip().capitalize()
        if value not in VALID_DAYS:
            raise ValueError("week_start_day must be a valid weekday.")
        return value

    @field_validator("financial_year")
    @classmethod
    def validate_financial_year(cls, value: str) -> str:
        value = value.strip()
        match = re.fullmatch(r"(\d{4})-(\d{4})", value)
        if not match or int(match.group(2)) != int(match.group(1)) + 1:
            raise ValueError("financial_year must use YYYY-YYYY with consecutive years.")
        return value

    @field_validator("working_days")
    @classmethod
    def validate_working_days(cls, v: list[str]) -> list[str]:
        if not v or len(v) == 0:
            raise ValueError("At least one working day must be selected.")
        normalized = []
        for d in v:
            clean = str(d).strip().capitalize()
            if clean not in VALID_DAYS:
                raise ValueError(f"Invalid weekday: {d}. Must be one of {sorted(VALID_DAYS)}.")
            normalized.append(clean)
        if len(normalized) != len(set(normalized)):
            raise ValueError("working_days cannot contain duplicates.")
        return normalized

    @field_validator("office_start_time", "office_end_time")
    @classmethod
    def validate_time(cls, v: str) -> str:
        clean = str(v).strip()
        for fmt in ("%H:%M", "%I:%M %p"):
            try:
                datetime.strptime(clean.upper(), fmt)
                return clean
            except ValueError:
                continue
        raise ValueError("Time must use HH:MM (24-hour) or HH:MM AM/PM format.")

    @model_validator(mode="after")
    def validate_office_hours(self) -> "WorkScheduleInput":
        def to_minutes(value: str) -> int:
            for fmt in ("%H:%M", "%I:%M %p"):
                try:
                    parsed = datetime.strptime(value.upper(), fmt)
                    return parsed.hour * 60 + parsed.minute
                except ValueError:
                    continue
            raise ValueError("Invalid office time.")

        if to_minutes(self.office_start_time) >= to_minutes(self.office_end_time):
            raise ValueError("office_start_time must be earlier than office_end_time.")
        return self


class WorkScheduleResponse(BaseModel):
    """Response containing Work Schedule and HR Settings."""

    timezone: str
    currency: str
    date_format: str
    time_format: str
    financial_year: str
    week_start_day: str
    working_days: list[str]
    office_start_time: str
    office_end_time: str
    default_shift: str
    leave_policy_template: str | None = None


# Compatibility alias
HRSettingsStepInput = WorkScheduleInput


# ─────────────────────────────────────────────────────────────────────────────
# 6. Leave Policy Schemas
# ─────────────────────────────────────────────────────────────────────────────

class LeavePolicyCreateInput(OnboardingRequestModel):
    """Payload to create a leave policy."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        validation_alias=AliasChoices("name", "policy_name", "policyName"),
    )
    leave_type: str = Field(
        default="ANNUAL",
        max_length=50,
        validation_alias=AliasChoices("leave_type", "leaveType", "type"),
    )
    days_allowed: float = Field(
        ...,
        gt=0,
        le=365,
        validation_alias=AliasChoices("days_allowed", "daysAllowed", "days", "number_of_days", "numberOfDays"),
    )
    description: str | None = Field(default="", max_length=255)
    status: str = Field(default="ACTIVE", max_length=20)


class LeavePolicyUpdateInput(OnboardingRequestModel):
    """Payload to update a leave policy."""

    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        validation_alias=AliasChoices("name", "policy_name", "policyName"),
    )
    leave_type: str | None = Field(default=None, max_length=50, validation_alias=AliasChoices("leave_type", "leaveType"))
    days_allowed: float | None = Field(
        default=None,
        gt=0,
        le=365,
        validation_alias=AliasChoices("days_allowed", "daysAllowed", "days", "number_of_days"),
    )
    description: str | None = Field(default=None, max_length=255)
    status: str | None = Field(default=None, max_length=20)


class LeavePolicyResponse(BaseModel):
    """Leave policy item representation."""

    id: str
    company_id: str
    name: str
    leave_type: str
    days_allowed: float
    description: str | None = None
    status: str = "ACTIVE"
    created_at: str | None = None


# ─────────────────────────────────────────────────────────────────────────────
# 7. Individual Employee Invitation Schemas (STRICTLY INDIVIDUAL ONLY)
# ─────────────────────────────────────────────────────────────────────────────

class IndividualInvitationInput(OnboardingRequestModel):
    """Payload for individual employee invitation. Bulk APIs strictly prohibited."""

    employee_name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        validation_alias=AliasChoices("employee_name", "employeeName", "name", "fullName"),
    )
    employee_email: EmailStr = Field(
        ...,
        validation_alias=AliasChoices("employee_email", "employeeEmail", "email", "personal_email", "personalEmail"),
    )
    department: str | None = Field(default=None, max_length=100)
    designation: str | None = Field(default=None, max_length=100)


class InvitationResponse(BaseModel):
    """Response representing an employee invitation."""

    id: str
    company_id: str
    employee_name: str
    employee_email: str
    department: str | None = None
    designation: str | None = None
    status: str = "PENDING"
    delivery_status: str = "QUEUED"
    expires_at: str
    created_at: str


class InvitationListResponse(BaseModel):
    """List of pending employee invitations."""

    items: list[InvitationResponse]
    total: int


# Compatibility aliases for batch step
class InviteEmployeeStepInput(OnboardingRequestModel):
    first_name: str = Field(default="", validation_alias=AliasChoices("first_name", "firstName"))
    last_name: str = Field(default="", validation_alias=AliasChoices("last_name", "lastName"))
    personal_email: str = Field(default="", validation_alias=AliasChoices("personal_email", "personalEmail", "email"))
    phone: str = Field(default="", validation_alias=AliasChoices("phone", "mobile"))
    department: str = Field(default="")
    designation: str = Field(default="")


class InviteEmployeeStepInputList(OnboardingRequestModel):
    employees: list[InviteEmployeeStepInput] = Field(default=[])
    skip: bool = False


# ─────────────────────────────────────────────────────────────────────────────
# 8. Onboarding Progress & Structure Review Schemas
# ─────────────────────────────────────────────────────────────────────────────

class OnboardingProgressUpdateInput(OnboardingRequestModel):
    """Payload to save onboarding progress."""

    current_step: int = Field(..., ge=1, le=7)
    completed_steps: list[int | str] | None = None
    status: str | None = None


class OnboardingStatusResponse(BaseModel):
    """Payload for onboarding status endpoint."""

    onboarding_completed: bool
    current_step: int
    completion_percentage: float
    status: str = "in_progress"  # not_started, in_progress, completed
    started_at: str | None = None
    completed_at: str | None = None
    last_updated_at: str | None = None
    company_completed: bool = False
    admin_completed: bool = False
    hr_completed: bool = False
    departments_completed: bool = False
    designations_completed: bool = False
    employees_invited: bool = False
    organization: OrganizationSummary | dict[str, Any] | None = None


class OnboardingProgressResponse(BaseModel):
    """Comprehensive payload returning all saved onboarding progress data."""

    company_id: str | None = None
    organization: OrganizationSummary | dict[str, Any] | None = None
    onboarding_completed: bool
    current_step: int
    status: str = "in_progress"
    started_at: str | None = None
    completed_at: str | None = None
    last_updated_at: str | None = None
    company_profile: dict[str, Any] | None = None
    hr_settings: dict[str, Any] | None = None
    admin_profile: dict[str, Any] | None = None
    departments: list[dict[str, Any]] = []
    designations: list[dict[str, Any]] = []
    shifts: list[dict[str, Any]] = []
    leave_policies: list[dict[str, Any]] = []
    pending_invitations: list[dict[str, Any]] = []
    step_flags: dict[str, bool] = {}


class OnboardingReviewResponse(BaseModel):
    """Aggregated organization structure for Review & Activate screen (Step 6)."""

    organization: dict[str, Any]
    admin_profile: dict[str, Any]
    departments: list[dict[str, Any]]
    designations: list[dict[str, Any]]
    work_schedule: dict[str, Any]
    leave_policies: list[dict[str, Any]]
    pending_invitations: list[dict[str, Any]]
    onboarding_status: str
    current_step: int
    completion_percentage: float
    can_activate: bool = False


class OrganizationStructureInput(OnboardingRequestModel):
    """Atomically save the organization stage of the wizard."""

    departments: list[DepartmentCreateInput] = Field(min_length=1)
    designations: list[DesignationCreateInput] = Field(min_length=1)


class FileUploadResponse(BaseModel):
    """Response returned when an asset file is uploaded."""

    url: str
    filename: str
    size: int
    category: str
