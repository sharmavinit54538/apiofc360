"""Pydantic v2 schemas for the Manager Management module."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Enums as string literals
# ---------------------------------------------------------------------------

GENDER_VALUES = {"MALE", "FEMALE", "OTHER"}
BLOOD_GROUP_VALUES = {"A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"}
MARITAL_STATUS_VALUES = {"SINGLE", "MARRIED", "DIVORCED", "WIDOWED"}
EMPLOYMENT_TYPE_VALUES = {"FULL_TIME", "PART_TIME", "CONTRACT", "INTERN"}
EMPLOYMENT_STATUS_VALUES = {"PROBATION", "CONFIRMED", "NOTICE_PERIOD"}
DOCUMENT_TYPE_VALUES = {"AADHAAR", "PAN", "PASSPORT"}
ADDRESS_TYPE_VALUES = {"CURRENT", "PERMANENT"}
PROFICIENCY_VALUES = {"BEGINNER", "INTERMEDIATE", "EXPERT"}
MANAGER_STATUS_VALUES = {
    "DRAFT", "CREATED", "INVITED", "INVITATION_SENT", "EMAIL_VERIFIED",
    "PASSWORD_CREATED", "ACTIVE", "INACTIVE", "TERMINATED",
}
from app.schemas.employee.constants import ROLE_VALUES


# ---------------------------------------------------------------------------
# Address schemas
# ---------------------------------------------------------------------------

class ManagerAddressCreate(BaseModel):
    address_type: str = Field(..., description="CURRENT or PERMANENT")
    address_line_1: str = Field(..., min_length=1, max_length=255)
    address_line_2: str | None = Field(None, max_length=255)
    city: str = Field(..., min_length=1, max_length=100)
    state: str = Field(..., min_length=1, max_length=100)
    country: str = Field("India", max_length=100)
    pincode: str = Field(..., min_length=4, max_length=10)
    is_same_as_current: bool = False

    @field_validator("address_type")
    @classmethod
    def validate_address_type(cls, v: str) -> str:
        v = v.upper()
        if v not in ADDRESS_TYPE_VALUES:
            raise ValueError("address_type must be CURRENT or PERMANENT")
        return v


class ManagerAddressResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    manager_id: uuid.UUID
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


# ---------------------------------------------------------------------------
# Document schemas
# ---------------------------------------------------------------------------

class ManagerDocumentCreate(BaseModel):
    document_type: str = Field(..., description="AADHAAR/PAN/PASSPORT")
    document_number: str | None = Field(None, max_length=100)
    document_url: str | None = Field(None, max_length=500)
    expiry_date: date | None = None

    @field_validator("document_type")
    @classmethod
    def validate_document_type(cls, v: str) -> str:
        v = v.upper()
        if v not in DOCUMENT_TYPE_VALUES:
            raise ValueError("document_type must be one of AADHAAR, PAN, PASSPORT")
        return v


class ManagerDocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    manager_id: uuid.UUID
    document_type: str
    document_number: str | None
    document_url: str | None
    expiry_date: date | None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Education schemas
# ---------------------------------------------------------------------------

class ManagerEducationCreate(BaseModel):
    degree: str = Field(..., min_length=1, max_length=150)
    institution: str = Field(..., min_length=1, max_length=255)
    field_of_study: str | None = Field(None, max_length=150)
    start_year: int | None = Field(None, ge=1950, le=2100)
    end_year: int | None = Field(None, ge=1950, le=2100)
    grade: str | None = Field(None, max_length=50)
    certificate_url: str | None = Field(None, max_length=500)


class ManagerEducationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    manager_id: uuid.UUID
    degree: str
    institution: str
    field_of_study: str | None
    start_year: int | None
    end_year: int | None
    grade: str | None
    certificate_url: str | None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Experience schemas
# ---------------------------------------------------------------------------

class ManagerExperienceCreate(BaseModel):
    company_name: str = Field(..., min_length=1, max_length=255)
    designation: str = Field(..., min_length=1, max_length=150)
    employment_type: str | None = Field(None, max_length=30)
    start_date: date
    end_date: date | None = None
    is_current: bool = False
    description: str | None = None

    @model_validator(mode="after")
    def validate_dates(self) -> ManagerExperienceCreate:
        if self.end_date and self.start_date and self.end_date < self.start_date:
            raise ValueError("end_date must be after start_date")
        if self.is_current and self.end_date:
            raise ValueError("is_current cannot be True when end_date is set")
        return self


class ManagerExperienceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    manager_id: uuid.UUID
    company_name: str
    designation: str
    employment_type: str | None
    start_date: date
    end_date: date | None
    is_current: bool
    description: str | None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Skill schemas
# ---------------------------------------------------------------------------

class ManagerSkillCreate(BaseModel):
    skill_name: str = Field(..., min_length=1, max_length=100)
    proficiency: str | None = Field(None)
    years_of_experience: int | None = Field(None, ge=0, le=50)

    @field_validator("proficiency")
    @classmethod
    def validate_proficiency(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.upper()
        if v not in PROFICIENCY_VALUES:
            raise ValueError("proficiency must be BEGINNER, INTERMEDIATE, or EXPERT")
        return v


class ManagerSkillResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    manager_id: uuid.UUID
    skill_name: str
    proficiency: str | None
    years_of_experience: int | None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Emergency contact schemas
# ---------------------------------------------------------------------------

class ManagerEmergencyContactCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=150)
    relation: str = Field(..., min_length=1, max_length=50)
    phone: str = Field(..., min_length=10, max_length=15)
    alternate_phone: str | None = Field(None, max_length=15)
    email: EmailStr | None = None
    address: str | None = Field(None, max_length=500)


class ManagerEmergencyContactResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    manager_id: uuid.UUID
    name: str
    relation: str
    phone: str
    alternate_phone: str | None
    email: str | None
    address: str | None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Main manager schemas
# ---------------------------------------------------------------------------

class ManagerCreate(BaseModel):
    @model_validator(mode="before")
    @classmethod
    def map_camel_to_snake(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # If permissions are nested in a dict, extract them to the root
            permissions = data.get("permissions")
            if isinstance(permissions, dict):
                for pk, pv in permissions.items():
                    data[pk] = pv
            
            import re
            new_data = {}
            for k, v in data.items():
                s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', k)
                snake_key = re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()
                new_data[snake_key] = v
            
            # Convert empty/invalid strings for reporting_to to None (helps frontend dropdowns)
            rep_to = new_data.get("reporting_to")
            if isinstance(rep_to, str):
                rep_to_clean = rep_to.strip().lower()
                if rep_to_clean in ("", "null", "undefined", "none"):
                    new_data["reporting_to"] = None
                
            return new_data
        return data

    # Required — Basic
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    personal_email: EmailStr
    phone: str = Field(..., min_length=10, max_length=15)
    manager_id: str | None = None

    # Required — Employment
    department: str = Field(..., min_length=1, max_length=100)
    designation: str = Field(..., min_length=1, max_length=100)
    joining_date: date

    # Optional — Basic
    profile_photo_url: str | None = Field(None, max_length=500)
    gender: str | None = None
    date_of_birth: date | None = None
    company_email: EmailStr | None = None
    alternate_phone: str | None = Field(None, max_length=15)
    blood_group: str | None = None
    marital_status: str | None = None

    # Optional — Employment
    branch: str | None = Field(None, max_length=100)
    work_location: str | None = Field(None, max_length=100)
    employment_type: str = "FULL_TIME"
    employment_status: str = "PROBATION"
    shift: str | None = Field(None, max_length=50)
    probation_period_months: int | None = Field(None, ge=0, le=36)

    # Optional — Salary
    ctc: Decimal | None = Field(None, ge=0)
    basic_salary: Decimal | None = Field(None, ge=0)
    hra: Decimal | None = Field(None, ge=0)
    bonus: Decimal | None = Field(None, ge=0)
    pf: Decimal | None = Field(None, ge=0)
    esi: Decimal | None = Field(None, ge=0)
    professional_tax: Decimal | None = Field(None, ge=0)

    # Optional — System
    role: str = Field("manager")
    leave_group: str | None = Field(None, max_length=100)
    reporting_to: uuid.UUID | None = None

    # Optional — Permissions & Access Settings
    can_approve_leave: bool = False
    can_approve_attendance: bool = False
    can_manage_employees: bool = False
    can_view_payroll: bool = False
    can_edit_departments: bool = False
    can_invite_users: bool = False
    can_manage_recruitment: bool = False
    can_manage_performance: bool = False

    # Optional — Nested relations
    addresses: list[ManagerAddressCreate] = []
    documents: list[ManagerDocumentCreate] = []
    education: list[ManagerEducationCreate] = []
    experience: list[ManagerExperienceCreate] = []
    skills: list[ManagerSkillCreate] = []
    emergency_contacts: list[ManagerEmergencyContactCreate] = []

    @field_validator("employment_type")
    @classmethod
    def validate_employment_type(cls, v: str) -> str:
        v = v.upper()
        if v not in EMPLOYMENT_TYPE_VALUES:
            raise ValueError("employment_type must be one of: " + ", ".join(EMPLOYMENT_TYPE_VALUES))
        return v

    @field_validator("employment_status")
    @classmethod
    def validate_employment_status(cls, v: str) -> str:
        v = v.upper()
        if v not in EMPLOYMENT_STATUS_VALUES:
            raise ValueError("employment_status must be one of: " + ", ".join(EMPLOYMENT_STATUS_VALUES))
        return v

    @field_validator("gender")
    @classmethod
    def validate_gender(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.upper()
        if v not in GENDER_VALUES:
            raise ValueError("gender must be MALE, FEMALE, or OTHER")
        return v

    @field_validator("blood_group")
    @classmethod
    def validate_blood_group(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.upper()
        if v not in BLOOD_GROUP_VALUES:
            raise ValueError("blood_group must be one of: " + ", ".join(BLOOD_GROUP_VALUES))
        return v

    @field_validator("marital_status")
    @classmethod
    def validate_marital_status(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.upper()
        if v not in MARITAL_STATUS_VALUES:
            raise ValueError("marital_status must be one of: " + ", ".join(MARITAL_STATUS_VALUES))
        return v

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        v = v.lower()
        if v not in ROLE_VALUES:
            raise ValueError("role must be one of: super_admin, hr_admin, manager, employee, executive, it_admin")
        return v



class ManagerUpdate(BaseModel):
    @model_validator(mode="before")
    @classmethod
    def map_camel_to_snake(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # If permissions are nested in a dict, extract them to the root
            permissions = data.get("permissions")
            if isinstance(permissions, dict):
                for pk, pv in permissions.items():
                    data[pk] = pv
            
            import re
            new_data = {}
            for k, v in data.items():
                s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', k)
                snake_key = re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()
                new_data[snake_key] = v
            
            # Convert empty/invalid strings for reporting_to to None (helps frontend dropdowns)
            rep_to = new_data.get("reporting_to")
            if isinstance(rep_to, str):
                rep_to_clean = rep_to.strip().lower()
                if rep_to_clean in ("", "null", "undefined", "none"):
                    new_data["reporting_to"] = None
                
            return new_data
        return data

    first_name: str | None = Field(None, min_length=1, max_length=100)
    last_name: str | None = Field(None, min_length=1, max_length=100)
    profile_photo_url: str | None = None
    gender: str | None = None
    date_of_birth: date | None = None
    alternate_phone: str | None = None
    blood_group: str | None = None
    marital_status: str | None = None
    department: str | None = Field(None, max_length=100)
    designation: str | None = Field(None, max_length=100)
    branch: str | None = None
    work_location: str | None = None
    employment_type: str | None = None
    employment_status: str | None = None
    shift: str | None = None
    probation_period_months: int | None = None
    ctc: Decimal | None = None
    basic_salary: Decimal | None = None
    hra: Decimal | None = None
    bonus: Decimal | None = None
    pf: Decimal | None = None
    esi: Decimal | None = None
    professional_tax: Decimal | None = None
    role: str | None = None
    leave_group: str | None = None
    reporting_to: uuid.UUID | None = None

    # Permissions & Access Settings
    can_approve_leave: bool | None = None
    can_approve_attendance: bool | None = None
    can_manage_employees: bool | None = None
    can_view_payroll: bool | None = None
    can_edit_departments: bool | None = None
    can_invite_users: bool | None = None
    can_manage_recruitment: bool | None = None
    can_manage_performance: bool | None = None


class ManagerPermissionsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    canApproveLeave: bool = False
    canApproveAttendance: bool = False
    canManageEmployees: bool = False
    canViewPayroll: bool = False
    canEditDepartments: bool = False
    canInviteUsers: bool = False
    canManageRecruitment: bool = False
    canManagePerformance: bool = False


class ManagerListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    manager_id: str
    first_name: str
    last_name: str
    profile_photo_url: str | None
    company_email: str | None
    personal_email: str
    phone: str
    department: str
    designation: str

    # Employment — create API se match
    employment_type: str
    employment_status: str          # create API: employment_status ✅
    shift: str | None = None        # create API: shift ✅ (pehle missing tha)
    status: str
    role: str                       # create API: role ✅ (pehle missing tha)
    joining_date: date

    # Personal — create API se match
    date_of_birth: date | None = None   # create API: date_of_birth ✅ (pehle missing tha)
    blood_group: str | None = None      # ✅ Added
    marital_status: str | None = None   # ✅ Added
    gender: str | None = None           # ✅ Added
    alternate_phone: str | None = None  # ✅ Added

    # Salary — create API se match
    ctc: Decimal | None = None          # create API: ctc ✅ (pehle missing tha)

    # Reporting
    reporting_to: uuid.UUID | None = None
    reporting_manager_name: str | None = None

    # Permissions & Access Settings
    can_approve_leave: bool = False
    can_approve_attendance: bool = False
    can_manage_employees: bool = False
    can_view_payroll: bool = False
    can_edit_departments: bool = False
    can_invite_users: bool = False
    can_manage_recruitment: bool = False
    can_manage_performance: bool = False

    permissions: ManagerPermissionsResponse | None = None

    # Extra profile fields
    branch: str | None = None
    avatar: str | None = None
    bio: str | None = None
    timezone: str | None = None
    language: str | None = None
    team_size: int = 0
    last_active: datetime | None = None
    is_first_login: bool = True
    profile_completed: bool = False
    created_at: datetime
    activation_token: str | None = None
    activation_token_expires_at: datetime | None = None

    @model_validator(mode="before")
    @classmethod
    def populate_custom_fields(cls, data: Any) -> Any:
        if data is None:
            return data
        
        def get_val(obj, attr):
            if isinstance(obj, dict):
                return obj.get(attr)
            return getattr(obj, attr, None)

        def set_val(obj, attr, val):
            if isinstance(obj, dict):
                obj[attr] = val
            else:
                setattr(obj, attr, val)

        marital_status = get_val(data, "marital_status")
        if marital_status is not None:
            set_val(data, "maritalStatus", marital_status)

        branch = get_val(data, "branch")
        office_location = get_val(data, "office_location")
        
        office_val = branch if branch is not None else office_location
        if office_val is not None:
            set_val(data, "office", office_val)
            if branch is None:
                set_val(data, "branch", office_val)
            if office_location is None:
                set_val(data, "office_location", office_val)

        # Build permissions object
        permissions_dict = {
            "canApproveLeave": bool(get_val(data, "can_approve_leave")),
            "canApproveAttendance": bool(get_val(data, "can_approve_attendance")),
            "canManageEmployees": bool(get_val(data, "can_manage_employees")),
            "canViewPayroll": bool(get_val(data, "can_view_payroll")),
            "canEditDepartments": bool(get_val(data, "can_edit_departments")),
            "canInviteUsers": bool(get_val(data, "can_invite_users")),
            "canManageRecruitment": bool(get_val(data, "can_manage_recruitment")),
            "canManagePerformance": bool(get_val(data, "can_manage_performance")),
        }
        set_val(data, "permissions", permissions_dict)

        # Resolve Reporting Manager details
        reporting_to_uuid = get_val(data, "reporting_to")
        if reporting_to_uuid is not None:
            set_val(data, "reportingTo", reporting_to_uuid)
            
        reporting_mgr = get_val(data, "reporting_manager")
        if reporting_mgr is not None:
            set_val(data, "reportingTo", getattr(reporting_mgr, "id", None))
            set_val(data, "reportingManagerId", getattr(reporting_mgr, "manager_id", None))
            set_val(data, "reportingManagerName", f"{getattr(reporting_mgr, 'first_name', '')} {getattr(reporting_mgr, 'last_name', '')}".strip())
        return data


class ManagerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID | None
    manager_id: str
    first_name: str
    last_name: str
    profile_photo_url: str | None
    gender: str | None
    date_of_birth: date | None
    personal_email: str
    company_email: str | None
    phone: str
    alternate_phone: str | None
    blood_group: str | None
    marital_status: str | None
    department: str
    designation: str
    work_location: str | None
    joining_date: date
    employment_type: str
    employment_status: str
    shift: str | None
    probation_period_months: int | None
    ctc: Decimal | None
    basic_salary: Decimal | None
    hra: Decimal | None
    bonus: Decimal | None
    pf: Decimal | None
    esi: Decimal | None
    professional_tax: Decimal | None
    role: str
    leave_group: str | None
    status: str
    is_deleted: bool
    created_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    is_first_login: bool
    profile_completed: bool
    last_login: datetime | None
    branch: str | None = None
    reporting_to: uuid.UUID | None = None
    reporting_manager_name: str | None = None
    avatar: str | None = None
    bio: str | None = None
    timezone: str | None = None
    language: str | None = None
    team_size: int = 0
    last_active: datetime | None = None
    activation_token: str | None = None
    activation_token_expires_at: datetime | None = None

    @model_validator(mode="before")
    @classmethod
    def populate_custom_fields(cls, data: Any) -> Any:
        if data is None:
            return data
        
        def get_val(obj, attr):
            if isinstance(obj, dict):
                return obj.get(attr)
            return getattr(obj, attr, None)

        def set_val(obj, attr, val):
            if isinstance(obj, dict):
                obj[attr] = val
            else:
                setattr(obj, attr, val)

        marital_status = get_val(data, "marital_status")
        if marital_status is not None:
            set_val(data, "maritalStatus", marital_status)

        branch = get_val(data, "branch")
        office_location = get_val(data, "office_location")
        
        office_val = branch if branch is not None else office_location
        if office_val is not None:
            set_val(data, "office", office_val)
            if branch is None:
                set_val(data, "branch", office_val)
            if office_location is None:
                set_val(data, "office_location", office_val)

        # Build permissions object
        permissions_dict = {
            "canApproveLeave": bool(get_val(data, "can_approve_leave")),
            "canApproveAttendance": bool(get_val(data, "can_approve_attendance")),
            "canManageEmployees": bool(get_val(data, "can_manage_employees")),
            "canViewPayroll": bool(get_val(data, "can_view_payroll")),
            "canEditDepartments": bool(get_val(data, "can_edit_departments")),
            "canInviteUsers": bool(get_val(data, "can_invite_users")),
            "canManageRecruitment": bool(get_val(data, "can_manage_recruitment")),
            "canManagePerformance": bool(get_val(data, "can_manage_performance")),
        }
        set_val(data, "permissions", permissions_dict)

        # Resolve Reporting Manager details
        reporting_to_uuid = get_val(data, "reporting_to")
        if reporting_to_uuid is not None:
            set_val(data, "reportingTo", reporting_to_uuid)
            
        reporting_mgr = get_val(data, "reporting_manager")
        if reporting_mgr is not None:
            set_val(data, "reportingTo", getattr(reporting_mgr, "id", None))
            set_val(data, "reportingManagerId", getattr(reporting_mgr, "manager_id", None))
            set_val(data, "reportingManagerName", f"{getattr(reporting_mgr, 'first_name', '')} {getattr(reporting_mgr, 'last_name', '')}".strip())
        return data

    # Permissions & Access Settings
    can_approve_leave: bool = False
    can_approve_attendance: bool = False
    can_manage_employees: bool = False
    can_view_payroll: bool = False
    can_edit_departments: bool = False
    can_invite_users: bool = False
    can_manage_recruitment: bool = False
    can_manage_performance: bool = False

    permissions: ManagerPermissionsResponse | None = None  # ✅ Added

    # Relations
    addresses: list[ManagerAddressResponse] = []
    documents: list[ManagerDocumentResponse] = []
    education: list[ManagerEducationResponse] = []
    experience: list[ManagerExperienceResponse] = []
    skills: list[ManagerSkillResponse] = []
    emergency_contacts: list[ManagerEmergencyContactResponse] = []


class ActivateManagerRequest(BaseModel):
    token: str = Field(..., min_length=10)
    new_password: str = Field(..., min_length=8, max_length=128)
    confirm_password: str = Field(..., min_length=8, max_length=128)

    @model_validator(mode="after")
    def passwords_match(self) -> ActivateManagerRequest:
        if self.new_password != self.confirm_password:
            raise ValueError("Passwords do not match.")
        return self


class ManagerListResponse(BaseModel):
    items: list[ManagerListItem]
    total: int
    page: int
    limit: int
    pages: int


class ActivateManagerOnboardingRequest(BaseModel):
    """Public activation request — manager sets password on first login."""
    token: str = Field(..., min_length=10)
    password: str = Field(..., min_length=8, max_length=128)
    phone: str | None = Field(None, max_length=30)
    emergency_contact_name: str | None = Field(None, max_length=150)
    emergency_contact_phone: str | None = Field(None, max_length=30)
    profile_photo_url: str | None = Field(None, max_length=500)

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


class ManagerOnboardingCompleteRequest(BaseModel):
    """Payload for completing the manager onboarding step."""
    @model_validator(mode="before")
    @classmethod
    def map_camel_to_snake(cls, data: Any) -> Any:
        if isinstance(data, dict):
            permissions = data.get("permissions")
            if isinstance(permissions, dict):
                for pk, pv in permissions.items():
                    data[pk] = pv
            
            import re
            new_data = {}
            for k, v in data.items():
                s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', k)
                snake_key = re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()
                new_data[snake_key] = v
            
            rep_to = new_data.get("reporting_to")
            if isinstance(rep_to, str):
                rep_to_clean = rep_to.strip().lower()
                if rep_to_clean in ("", "null", "undefined", "none"):
                    new_data["reporting_to"] = None
                
            return new_data
        return data
    avatar: str | None = Field(None, max_length=500)
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    phone: str = Field(..., min_length=10, max_length=15)
    department: str = Field(..., min_length=1, max_length=100)
    designation: str = Field(..., min_length=1, max_length=100)
    manager_id: str = Field(..., min_length=1, max_length=20)  # Employee ID
    office_location: str | None = Field(None, max_length=100)
    reporting_to: uuid.UUID | None = None
    joining_date: date
    emergency_contact_name: str | None = Field(None, max_length=150)
    emergency_contact_phone: str | None = Field(None, min_length=10, max_length=15)
    bio: str | None = Field(None, max_length=500)
    timezone: str | None = Field(None, max_length=100)
    language: str | None = Field(None, max_length=50)
    password: str | None = Field(None, min_length=8, max_length=128)  # Optional password change
