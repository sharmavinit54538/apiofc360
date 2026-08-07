"""Pydantic v2 schemas for the Document Management module."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VISIBILITY_VALUES = {"PUBLIC", "PRIVATE", "DEPARTMENT", "MANAGER_ONLY", "HR_ONLY"}
STATUS_VALUES = {"PENDING", "VERIFIED", "REJECTED", "REQUIRES_SIGNATURE"}
SIGNATURE_STATUS_VALUES = {"PENDING", "SIGNED", "REJECTED"}
VERIFICATION_ACTION_VALUES = {"APPROVED", "REJECTED", "RE_UPLOAD_REQUESTED"}

EMPLOYEE_DOC_CATEGORIES = {
    "Resume", "Offer Letter", "Appointment Letter", "Employment Contract",
    "Aadhaar", "PAN", "Passport", "Driving License", "Voter ID",
    "Educational Certificates", "Experience Letter", "Salary Slip",
    "Bank Passbook", "Cancelled Cheque", "Medical Certificate",
    "PF Documents", "ESIC Documents", "Visa", "Work Permit", "Other",
}

COMPANY_DOC_CATEGORIES = {
    "HR Policy", "Leave Policy", "Payroll Policy", "Code of Conduct",
    "Employee Handbook", "NDA", "Holiday Calendar", "Compliance Documents",
    "ISO Documents", "Audit Reports", "Legal Agreements",
    "Training Materials", "Company Forms", "Templates", "Other",
}


# ---------------------------------------------------------------------------
# Categories Schemas
# ---------------------------------------------------------------------------

class CategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    code: str
    is_company: bool


# ---------------------------------------------------------------------------
# Employee Document Schemas
# ---------------------------------------------------------------------------

class EmployeeDocumentCreate(BaseModel):
    employee_id: uuid.UUID
    category_id: uuid.UUID
    title: str = Field(..., min_length=1, max_length=150)
    description: str | None = None
    issue_date: date | None = None
    expiry_date: date | None = None
    visibility: str = "PRIVATE"
    status: str = "PENDING"
    tags: str | None = None

    @field_validator("visibility")
    @classmethod
    def validate_visibility(cls, v: str) -> str:
        v = v.upper()
        if v not in VISIBILITY_VALUES:
            raise ValueError(f"visibility must be one of: {', '.join(VISIBILITY_VALUES)}")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        v = v.upper()
        if v not in STATUS_VALUES:
            raise ValueError(f"status must be one of: {', '.join(STATUS_VALUES)}")
        return v


class EmployeeDocumentUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=150)
    description: str | None = None
    issue_date: date | None = None
    expiry_date: date | None = None
    visibility: str | None = None
    status: str | None = None
    tags: str | None = None

    @field_validator("visibility")
    @classmethod
    def validate_visibility(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.upper()
        if v not in VISIBILITY_VALUES:
            raise ValueError(f"visibility must be one of: {', '.join(VISIBILITY_VALUES)}")
        return v


class EmployeeDocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    employee_id: uuid.UUID
    category_id: uuid.UUID | None
    uploaded_by: uuid.UUID | None
    title: str | None
    description: str | None
    file_name: str | None
    file_size: int | None
    issue_date: date | None
    expiry_date: date | None
    version: int
    status: str
    visibility: str
    tags: str | None
    created_at: datetime


# ---------------------------------------------------------------------------
# Company Document Schemas
# ---------------------------------------------------------------------------

class CompanyDocumentCreate(BaseModel):
    category_id: uuid.UUID
    title: str = Field(..., min_length=1, max_length=150)
    description: str | None = None
    department: str | None = Field(None, max_length=100)
    branch: str | None = Field(None, max_length=100)
    visibility: str = "PUBLIC"

    @field_validator("visibility")
    @classmethod
    def validate_visibility(cls, v: str) -> str:
        v = v.upper()
        if v not in VISIBILITY_VALUES:
            raise ValueError(f"visibility must be one of: {', '.join(VISIBILITY_VALUES)}")
        return v


class CompanyDocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    category_id: uuid.UUID
    uploaded_by: uuid.UUID
    title: str
    description: str | None
    file_name: str
    file_size: int
    department: str | None
    branch: str | None
    visibility: str
    status: str
    created_at: datetime


# ---------------------------------------------------------------------------
# Templates Schemas
# ---------------------------------------------------------------------------

class TemplateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=150)
    description: str | None = None
    template_body: str = Field(..., min_length=1)


class TemplateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    template_body: str
    created_by: uuid.UUID
    created_at: datetime


# ---------------------------------------------------------------------------
# Signature Schemas
# ---------------------------------------------------------------------------

class SignatureRequest(BaseModel):
    signer_user_id: uuid.UUID


class SignDocumentPayload(BaseModel):
    device_info: str | None = Field(None, max_length=255)


class SignatureResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    employee_doc_id: uuid.UUID
    signer_user_id: uuid.UUID
    status: str
    signed_at: datetime | None
    ip_address: str | None
    device_info: str | None


# ---------------------------------------------------------------------------
# Verification Schemas
# ---------------------------------------------------------------------------

class VerificationPayload(BaseModel):
    comments: str | None = Field(None, max_length=1000)


# ---------------------------------------------------------------------------
# Version History Schemas
# ---------------------------------------------------------------------------

class VersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version_number: int
    file_path: str
    uploaded_by: uuid.UUID
    created_at: datetime


# ---------------------------------------------------------------------------
# Audit Logs Schemas
# ---------------------------------------------------------------------------

class AuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    action: str
    target_type: str
    target_id: uuid.UUID
    details: str | None
    ip_address: str | None
    created_at: datetime
