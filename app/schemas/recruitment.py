"""Pydantic v2 schemas for the Recruitment Management module."""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Enums & Status Constants
# ---------------------------------------------------------------------------

EMPLOYMENT_TYPE_VALUES = {"FULL_TIME", "PART_TIME", "CONTRACT", "INTERN"}
JOB_STATUS_VALUES = {"DRAFT", "PUBLISHED", "CLOSED"}
INTERVIEW_MODE_VALUES = {"ONLINE", "OFFLINE"}
ROUND_STATUS_VALUES = {"PENDING", "PASSED", "REJECTED", "HOLD"}
APPLICATION_STATUS_VALUES = {
    "APPLIED", "UNDER_REVIEW", "SHORTLISTED", "INTERVIEW_SCHEDULED",
    "INTERVIEW_COMPLETED", "SELECTED", "REJECTED", "OFFER_SENT",
    "OFFER_ACCEPTED", "OFFER_REJECTED", "EMPLOYEE_CREATED",
}
OFFER_STATUS_VALUES = {"SENT", "ACCEPTED", "REJECTED", "EXPIRED"}


# ---------------------------------------------------------------------------
# Job Schemas
# ---------------------------------------------------------------------------

class JobSkillCreate(BaseModel):
    skill_name: str = Field(..., min_length=1, max_length=100)


class JobSkillResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    skill_name: str


class JobCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=150)
    department: str = Field(..., min_length=1, max_length=100)
    designation: str = Field(..., min_length=1, max_length=100)
    employment_type: str = "FULL_TIME"
    experience_required: str | None = Field(None, max_length=100)
    min_experience: int = Field(0, ge=0)
    max_experience: int | None = Field(None, ge=0)
    min_salary: Decimal | None = Field(None, ge=0)
    max_salary: Decimal | None = Field(None, ge=0)
    location: str = Field(..., min_length=1, max_length=100)
    vacancies: int = Field(1, ge=1)
    job_description: str = Field(..., min_length=1)
    responsibilities: str | None = None
    requirements: str | None = None
    benefits: str | None = None
    application_deadline: date | None = None
    interview_process_description: str | None = None
    status: str = "DRAFT"

    # Configured Rounds List (names of rounds in order)
    rounds: list[str] = Field(..., min_length=1, description="List of round names in order, e.g. ['Technical', 'Manager', 'HR']")
    skills: list[str] = Field([], description="List of required skill names")

    @field_validator("employment_type")
    @classmethod
    def validate_employment_type(cls, v: str) -> str:
        v = v.upper()
        if v not in EMPLOYMENT_TYPE_VALUES:
            raise ValueError("employment_type must be: " + ", ".join(EMPLOYMENT_TYPE_VALUES))
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        v = v.upper()
        if v not in JOB_STATUS_VALUES:
            raise ValueError("status must be: " + ", ".join(JOB_STATUS_VALUES))
        return v


class JobUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=150)
    department: str | None = Field(None, max_length=100)
    designation: str | None = Field(None, max_length=100)
    employment_type: str | None = None
    experience_required: str | None = None
    min_experience: int | None = Field(None, ge=0)
    max_experience: int | None = Field(None, ge=0)
    min_salary: Decimal | None = Field(None, ge=0)
    max_salary: Decimal | None = Field(None, ge=0)
    location: str | None = Field(None, min_length=1, max_length=100)
    vacancies: int | None = Field(None, ge=1)
    job_description: str | None = None
    responsibilities: str | None = None
    requirements: str | None = None
    benefits: str | None = None
    application_deadline: date | None = None
    interview_process_description: str | None = None
    status: str | None = None
    skills: list[str] | None = None


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    slug: str
    department: str
    designation: str
    employment_type: str
    experience_required: str | None
    min_experience: int
    max_experience: int | None
    min_salary: Decimal | None
    max_salary: Decimal | None
    location: str
    vacancies: int
    job_description: str
    responsibilities: str | None
    requirements: str | None
    benefits: str | None
    application_deadline: date | None
    interview_process_description: str | None
    status: str
    created_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime

    skills: list[JobSkillResponse] = []


class JobListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    slug: str
    department: str
    location: str
    employment_type: str
    vacancies: int
    status: str
    created_at: datetime


class JobListResponse(BaseModel):
    items: list[JobListItem]
    total: int
    page: int
    limit: int
    pages: int


# ---------------------------------------------------------------------------
# Career Portal & Applications
# ---------------------------------------------------------------------------

class CareerPortalJobDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    slug: str
    department: str
    designation: str
    employment_type: str
    experience_required: str | None
    min_experience: int
    max_experience: int | None
    location: str
    job_description: str
    responsibilities: str | None
    requirements: str | None
    benefits: str | None
    application_deadline: date | None
    skills: list[JobSkillResponse] = []


class ApplicationCreate(BaseModel):
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    phone: str = Field(..., min_length=10, max_length=20)
    country: str = Field(..., min_length=1, max_length=100)
    state: str = Field(..., min_length=1, max_length=100)
    city: str = Field(..., min_length=1, max_length=100)
    current_company: str | None = Field(None, max_length=150)
    current_designation: str | None = Field(None, max_length=150)
    current_ctc: Decimal | None = Field(None, ge=0)
    expected_ctc: Decimal | None = Field(None, ge=0)
    notice_period: str | None = Field(None, max_length=50)
    highest_qualification: str | None = Field(None, max_length=150)
    experience_years: Decimal = Field(0.0, ge=0.0)
    is_fresher: bool | None = Field(None)
    linkedin_url: str | None = Field(None, max_length=255)
    portfolio_url: str | None = Field(None, max_length=255)
    cover_letter: str | None = None
    declaration_checked: bool = Field(..., description="Must check declaration checkbox")

    @field_validator("declaration_checked")
    @classmethod
    def must_accept_declaration(cls, v: bool) -> bool:
        if not v:
            raise ValueError("Declaration checkbox must be checked to apply.")
        return v

    @model_validator(mode="after")
    def validate_experience_requirements(self) -> ApplicationCreate:
        is_fresher_flag = (
            self.is_fresher is True
            or self.experience_years == Decimal("0.0")
            or self.experience_years == 0
        )
        if not is_fresher_flag and self.experience_years > 0:
            if not self.current_company or not self.current_company.strip():
                raise ValueError("Current/Previous company name is required when work experience is greater than 0.")
            if not self.current_designation or not self.current_designation.strip():
                raise ValueError("Current/Previous designation is required when work experience is greater than 0.")
        return self


class ApplicationDocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_type: str
    file_name: str
    file_size: int
    uploaded_at: datetime


class ApplicationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    job_id: uuid.UUID
    first_name: str
    last_name: str
    email: str
    phone: str
    country: str
    state: str
    city: str
    current_company: str | None
    current_designation: str | None
    current_ctc: Decimal | None
    expected_ctc: Decimal | None
    notice_period: str | None
    highest_qualification: str | None
    experience_years: Decimal
    linkedin_url: str | None
    portfolio_url: str | None
    cover_letter: str | None
    status: str
    created_at: datetime

    documents: list[ApplicationDocumentResponse] = []
    job: JobListItem


class ApplicationListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    first_name: str
    last_name: str
    email: str
    phone: str
    status: str
    created_at: datetime
    job_title: str = Field(..., validation_alias="job_title")


class ApplicationListResponse(BaseModel):
    items: list[dict]
    total: int
    page: int
    limit: int
    pages: int


class ApplicationUpdate(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        v = v.upper()
        if v not in APPLICATION_STATUS_VALUES:
            raise ValueError("Invalid status: " + ", ".join(APPLICATION_STATUS_VALUES))
        return v


# ---------------------------------------------------------------------------
# Interviews & Scheduling
# ---------------------------------------------------------------------------

class InterviewRoundResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    round_name: str
    round_order: int
    feedback: str | None
    score: str | None
    status: str
    interviewer_name: str | None
    conducted_at: datetime | None


class InterviewScheduleCreate(BaseModel):
    interview_date: date
    interview_time: time
    mode: str = "ONLINE"
    meeting_url: str | None = Field(None, max_length=500)
    office_address: str | None = Field(None, max_length=500)

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, v: str) -> str:
        v = v.upper()
        if v not in INTERVIEW_MODE_VALUES:
            raise ValueError("mode must be ONLINE or OFFLINE")
        return v

    @model_validator(mode="after")
    def validate_venue_details(self) -> InterviewScheduleCreate:
        if self.mode == "ONLINE" and not self.meeting_url:
            raise ValueError("meeting_url is required when mode is ONLINE")
        if self.mode == "OFFLINE" and not self.office_address:
            raise ValueError("office_address is required when mode is OFFLINE")
        return self


class InterviewScheduleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    interview_id: uuid.UUID
    round_id: uuid.UUID
    interview_date: date
    interview_time: str = Field(..., description="HH:MM:SS format")
    mode: str
    meeting_url: str | None
    office_address: str | None
    created_at: datetime


class InterviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    application_id: uuid.UUID
    status: str
    current_round_index: int
    created_at: datetime
    updated_at: datetime

    rounds: list[InterviewRoundResponse] = []


class CompleteRoundRequest(BaseModel):
    feedback: str = Field(..., min_length=1)
    score: str = Field(..., min_length=1, max_length=20)
    interviewer_name: str = Field(..., min_length=1, max_length=100)


# ---------------------------------------------------------------------------
# Offers & Conversions
# ---------------------------------------------------------------------------

class OfferCreate(BaseModel):
    ctc: Decimal = Field(..., ge=0)
    joining_date: date
    offer_expiry_date: date

    @model_validator(mode="after")
    def validate_expiry(self) -> OfferCreate:
        if self.offer_expiry_date < date.today():
            raise ValueError("offer_expiry_date cannot be in the past.")
        if self.joining_date < self.offer_expiry_date:
            raise ValueError("joining_date must be after offer_expiry_date.")
        return self


class OfferDocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    file_name: str
    created_at: datetime


class OfferResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    application_id: uuid.UUID
    ctc: Decimal
    joining_date: date
    offer_expiry_date: date
    status: str
    created_by: uuid.UUID | None
    created_at: datetime

    documents: list[OfferDocumentResponse] = []


# ---------------------------------------------------------------------------
# Dashboard Stats
# ---------------------------------------------------------------------------

class RecruitmentDashboardStats(BaseModel):
    total_jobs: int
    published_jobs: int
    draft_jobs: int
    closed_jobs: int
    total_applications: int
    applications_today: int
    shortlisted_count: int
    rejected_count: int
    interviews_scheduled_count: int
    offers_sent_count: int
    offers_accepted_count: int
    employees_hired_count: int


# ---------------------------------------------------------------------------
# Extended Recruitment Module Schemas
# ---------------------------------------------------------------------------

class CandidateCreate(BaseModel):
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    phone: str = Field(..., min_length=10, max_length=20)
    location: str = Field(..., min_length=1, max_length=100)
    summary: str | None = None
    skills: list[str] | None = None
    tags: list[str] | None = None
    years_experience: Decimal = Field(0.0, ge=0.0)
    current_company: str | None = Field(None, max_length=150)
    current_role: str | None = Field(None, max_length=150)
    expected_salary: Decimal | None = Field(None, ge=0.0)
    notice_days: int = Field(0, ge=0)
    source: str = "DIRECT"
    is_talent_pool: bool = False
    vendor_id: uuid.UUID | None = None


class CandidateUpdate(BaseModel):
    first_name: str | None = Field(None, min_length=1, max_length=100)
    last_name: str | None = Field(None, min_length=1, max_length=100)
    email: EmailStr | None = None
    phone: str | None = Field(None, min_length=10, max_length=20)
    location: str | None = Field(None, min_length=1, max_length=100)
    summary: str | None = None
    skills: list[str] | None = None
    tags: list[str] | None = None
    years_experience: Decimal | None = Field(None, ge=0.0)
    current_company: str | None = Field(None, max_length=150)
    current_role: str | None = Field(None, max_length=150)
    expected_salary: Decimal | None = Field(None, ge=0.0)
    notice_days: int | None = Field(None, ge=0)
    source: str | None = None
    is_talent_pool: bool | None = None
    vendor_id: uuid.UUID | None = None


class CandidateApplicationJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID | None = None
    title: str
    department: str | None = None
    location: str | None = None

class CandidateApplicationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    job_id: uuid.UUID
    status: str
    created_at: datetime
    updated_at: datetime
    job: CandidateApplicationJobResponse | None = None

class CandidateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    first_name: str
    last_name: str
    email: str
    phone: str
    location: str
    summary: str | None
    skills: list[str] | None
    tags: list[str] | None
    years_experience: Decimal
    current_company: str | None
    current_role: str | None
    expected_salary: Decimal | None
    notice_days: int
    resume_path: str | None
    resume_name: str | None
    source: str
    is_talent_pool: bool
    vendor_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    ats_score: int | None = None
    job_match: int | None = None
    applications: list[CandidateApplicationResponse] = []


class JobRequisitionCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=150)
    department: str = Field(..., min_length=1, max_length=100)
    vacancies: int = Field(1, ge=1)
    min_experience: int = Field(0, ge=0)
    max_experience: int | None = Field(None, ge=0)
    min_salary: Decimal | None = Field(None, ge=0.0)
    max_salary: Decimal | None = Field(None, ge=0.0)
    description: str = Field(..., min_length=1)


class JobRequisitionUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=150)
    department: str | None = Field(None, max_length=100)
    vacancies: int | None = Field(None, ge=1)
    min_experience: int | None = Field(None, ge=0)
    max_experience: int | None = Field(None, ge=0)
    min_salary: Decimal | None = Field(None, ge=0.0)
    max_salary: Decimal | None = Field(None, ge=0.0)
    description: str | None = None
    status: str | None = None


class JobRequisitionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    department: str
    vacancies: int
    min_experience: int
    max_experience: int | None
    min_salary: Decimal | None
    max_salary: Decimal | None
    description: str
    status: str
    requested_by: uuid.UUID
    approved_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class RecruitmentVendorCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    contact_name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    phone: str = Field(..., min_length=1, max_length=20)
    commission_rate: Decimal = Field(Decimal("0.00"), ge=0.0, le=100.0)
    status: str = "ACTIVE"


class RecruitmentVendorUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    contact_name: str | None = Field(None, min_length=1, max_length=100)
    email: EmailStr | None = None
    phone: str | None = Field(None, min_length=1, max_length=20)
    commission_rate: Decimal | None = Field(None, ge=0.0, le=100.0)
    status: str | None = None


class RecruitmentVendorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    contact_name: str
    email: str
    phone: str
    commission_rate: Decimal
    status: str
    created_at: datetime
    updated_at: datetime


class ScorecardTemplateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    department: str = Field(..., min_length=1, max_length=100)
    criteria: list[dict] = Field(..., min_length=1, description="List of criteria parameters")


class ScorecardTemplateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    department: str
    criteria: list[dict] | None
    created_at: datetime
    updated_at: datetime


class ScorecardSubmissionCreate(BaseModel):
    interview_round_id: uuid.UUID
    scores: dict[str, int] = Field(..., description="Mapping of criteria ID to score (1-5)")
    overall_recommendation: str = Field(..., description="STRONG_HIRE, HIRE, MAYBE, or REJECT")
    feedback_notes: str | None = None


class ScorecardSubmissionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    interview_round_id: uuid.UUID
    submitted_by: uuid.UUID
    scores: dict
    overall_recommendation: str
    feedback_notes: str | None
    created_at: datetime


class CandidateCrmNoteCreate(BaseModel):
    candidate_id: uuid.UUID
    channel: str = "note"  # email | call | sms | linkedin | note
    subject: str | None = None
    note_text: str = Field(..., min_length=1)
    follow_up_date: date | None = None


class CandidateCrmNoteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    candidate_id: uuid.UUID
    author_id: uuid.UUID
    channel: str
    subject: str | None
    note_text: str
    follow_up_date: date | None
    created_at: datetime


class CandidateReferralCreate(BaseModel):
    candidate_id: uuid.UUID
    employee_id: uuid.UUID
    job_id: uuid.UUID | None = None
    reward_amount: Decimal = Field(Decimal("0.00"), ge=0.0)


class CandidateReferralResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    candidate_id: uuid.UUID
    employee_id: uuid.UUID
    job_id: uuid.UUID | None
    status: str
    reward_amount: Decimal
    reward_status: str
    created_at: datetime


class RecruitmentAutomationRuleCreate(BaseModel):
    trigger_event: str = Field(..., min_length=1, max_length=50)
    conditions: dict | None = None
    action_type: str = Field(..., min_length=1, max_length=50)
    action_config: dict | None = None
    is_active: bool = True


class RecruitmentAutomationRuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    trigger_event: str
    conditions: dict | None
    action_type: str
    action_config: dict | None
    is_active: bool
    created_at: datetime


class RecruitmentNotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    title: str
    message: str
    is_read: bool
    created_at: datetime


class RecruitmentRecentActivity(BaseModel):
    id: uuid.UUID
    at: datetime
    kind: str  # stage, note, interview, offer, system
    title: str
    detail: str | None = None
    actor: str | None = None
    who: str
    job_title: str


class RequisitionApproval(BaseModel):
    requisition_id: uuid.UUID
    approve: bool


class JobPublishResponse(BaseModel):
    channel_name: str
    is_active: bool
    published_at: datetime | None = None
    updated_at: datetime
    unique_key: str | None = None
    url: str | None = None

    class Config:
        from_attributes = True


class JobPublishRequest(BaseModel):
    channel_name: str
    is_active: bool


class JobDuplicateRequest(BaseModel):
    title: str | None = None
    location: str | None = None
    vacancies: int | None = None
    min_salary: Decimal | None = None
    max_salary: Decimal | None = None
