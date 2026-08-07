"""Pydantic schemas for the Employee Onboarding Flow."""
from __future__ import annotations
from datetime import date, datetime
from typing import Any, Generic, TypeVar, List, Optional
from pydantic import BaseModel, EmailStr, Field

T = TypeVar("T")

class EmployeeOnboardingAPIResponse(BaseModel, Generic[T]):
    """Standardized employee onboarding API response envelope."""
    success: bool
    message: str
    current_step: int
    onboarding_completed: bool
    data: T
    redirect_step: Optional[int] = None

class EmployeeOnboardingStatus(BaseModel):
    """Overall status of employee onboarding."""
    onboarding_completed: bool
    current_step: int
    completion_percentage: float
    steps_completed: dict[str, bool]

class PersonalInfoInput(BaseModel):
    """Payload for Step 1 — Personal Information."""
    first_name: str = Field(..., min_length=1, max_length=100)
    middle_name: Optional[str] = Field(None, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    profile_photo_url: Optional[str] = Field(None, max_length=500)
    gender: str = Field(...)
    date_of_birth: date = Field(...)
    marital_status: str = Field(...)
    blood_group: Optional[str] = Field(None, max_length=10)
    nationality: str = Field(..., max_length=100)
    father_name: str = Field(..., max_length=100)
    mother_name: str = Field(..., max_length=100)
    spouse_name: Optional[str] = Field(None, max_length=100)
    personal_email: EmailStr = Field(...)
    phone: str = Field(..., min_length=10, max_length=15)
    
    # Address details (Current & Permanent)
    current_address_line1: str = Field(..., max_length=255)
    current_address_line2: Optional[str] = Field(None, max_length=255)
    current_city: str = Field(..., max_length=100)
    current_state: str = Field(..., max_length=100)
    current_country: str = Field("India", max_length=100)
    current_pincode: str = Field(..., max_length=10)

    permanent_address_line1: str = Field(..., max_length=255)
    permanent_address_line2: Optional[str] = Field(None, max_length=255)
    permanent_city: str = Field(..., max_length=100)
    permanent_state: str = Field(..., max_length=100)
    permanent_country: str = Field("India", max_length=100)
    permanent_pincode: str = Field(..., max_length=10)
    is_same_address: bool = Field(False)

    # Emergency Contact
    emergency_contact_name: str = Field(..., max_length=150)
    emergency_contact_relation: str = Field(..., max_length=50)
    emergency_contact_phone: str = Field(..., max_length=15)
    preferred_language: str = Field("English", max_length=50)

class IdentityVerificationInput(BaseModel):
    """Payload for Step 2 — Identity Verification Numbers."""
    aadhaar_number: str = Field(..., min_length=12, max_length=12)
    pan_number: str = Field(..., min_length=10, max_length=10)
    passport_number: Optional[str] = Field(None, max_length=20)
    driving_license: Optional[str] = Field(None, max_length=30)
    voter_id: Optional[str] = Field(None, max_length=20)

class EmploymentDetailsInput(BaseModel):
    """Payload for Step 3 — Employment Details (prefills/reviews)."""
    employee_id: str = Field(...)
    department: str = Field(...)
    designation: str = Field(...)
    reporting_manager_id: Optional[str] = None
    employment_type: str = Field(...)
    work_location: Optional[str] = Field(None)
    joining_date: date = Field(...)
    probation_period_months: int = Field(...)
    shift: Optional[str] = Field(None)
    work_mode: str = Field("ONSITE")
    office_location: Optional[str] = Field(None)
    business_unit: Optional[str] = Field(None)
    cost_center_id: Optional[str] = Field(None)
    employee_category: Optional[str] = Field(None)

class EducationItem(BaseModel):
    """Single education qualification record."""
    degree: str = Field(..., max_length=150)
    institution: str = Field(..., max_length=255)
    field_of_study: Optional[str] = Field(None, max_length=150)
    start_year: int = Field(...)
    end_year: int = Field(...)
    grade: Optional[str] = Field(None, max_length=50)
    certificate_url: Optional[str] = Field(None, max_length=500)

class EducationDetailsInput(BaseModel):
    """Payload for Step 4 — Educational Details."""
    education_records: List[EducationItem] = Field(...)

class ExperienceItem(BaseModel):
    """Single work experience record."""
    company_name: str = Field(..., max_length=255)
    designation: str = Field(..., max_length=150)
    employment_type: Optional[str] = Field(None, max_length=30)
    start_date: date = Field(...)
    end_date: Optional[date] = None
    is_current: bool = Field(False)
    description: Optional[str] = None
    ctc: Optional[float] = None
    manager_name: Optional[str] = Field(None, max_length=150)
    reason_for_leaving: Optional[str] = None
    experience_certificate_url: Optional[str] = Field(None, max_length=500)
    relieving_letter_url: Optional[str] = Field(None, max_length=500)
    salary_slip_url: Optional[str] = Field(None, max_length=500)

class ExperienceDetailsInput(BaseModel):
    """Payload for Step 5 — Professional Experience."""
    experience_records: List[ExperienceItem] = Field(...)

class BankDetailsInput(BaseModel):
    """Payload for Step 6 — Bank Details."""
    bank_name: str = Field(..., max_length=150)
    account_holder_name: str = Field(..., max_length=150)
    account_number: str = Field(..., max_length=30)
    ifsc_code: str = Field(..., max_length=15)
    branch: Optional[str] = Field(None, max_length=100)
    upi_id: Optional[str] = Field(None, max_length=50)
    cancelled_cheque_url: Optional[str] = Field(None, max_length=500)
    passbook_url: Optional[str] = Field(None, max_length=500)

class TaxNomineeInput(BaseModel):
    """Payload for Step 7 — Tax regime, PF numbers and Nominee."""
    tax_regime: str = Field("NEW")  # OLD / NEW
    uan_number: Optional[str] = Field(None, max_length=12)
    pf_number: Optional[str] = Field(None, max_length=30)
    esic_number: Optional[str] = Field(None, max_length=30)
    professional_tax: Optional[float] = None
    
    # Nominee Details
    nominee_name: str = Field(..., max_length=150)
    nominee_relation: str = Field(..., max_length=50)
    nominee_aadhaar: Optional[str] = Field(None, max_length=20)
    nominee_dob: Optional[str] = Field(None, max_length=20)

class PolicyAcceptanceItem(BaseModel):
    """Indicates acceptance of a specific policy."""
    policy_name: str = Field(...)
    accepted: bool = Field(...)
    digital_signature: str = Field(...)

class PoliciesAcceptanceInput(BaseModel):
    """Payload for Step 9 — Policies and Agreements."""
    acceptances: List[PolicyAcceptanceItem] = Field(...)
    ip_address: Optional[str] = None

class EmployeeOnboardingDraft(BaseModel):
    """Payload to save complete draft of form state."""
    current_step: int
    draft_data: dict[str, Any]
