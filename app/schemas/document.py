"""Pydantic v2 schemas for the Document Management module."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.services.document_categories import CANONICAL_CATEGORIES

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VISIBILITY_VALUES = {"PUBLIC", "PRIVATE", "DEPARTMENT", "MANAGER_ONLY", "HR_ONLY"}
STATUS_VALUES = {"PENDING", "VERIFIED", "REJECTED", "REQUIRES_SIGNATURE"}
SIGNATURE_STATUS_VALUES = {"PENDING", "SIGNED", "REJECTED"}
VERIFICATION_ACTION_VALUES = {"APPROVED", "REJECTED", "RE_UPLOAD_REQUESTED"}

EMPLOYEE_DOC_CATEGORIES = {c["name"] for c in CANONICAL_CATEGORIES if not c["is_company"]}
COMPANY_DOC_CATEGORIES = {c["name"] for c in CANONICAL_CATEGORIES if c["is_company"]}


# ---------------------------------------------------------------------------
# Categories Schemas
# ---------------------------------------------------------------------------

class CategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    code: str
    group: str | None = None
    is_company: bool


# ---------------------------------------------------------------------------
# Employee Document Schemas
# ---------------------------------------------------------------------------

class EmployeeDocumentCreate(BaseModel):
    employee_id: uuid.UUID
    category_id: uuid.UUID
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    issue_date: date | None = None
    expiry_date: date | None = None
    visibility: str = "PRIVATE"
    status: str = "PENDING"
    tags: str | None = Field(None, max_length=255)

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("title cannot be empty or blank")
        return v

    @model_validator(mode="after")
    def validate_dates(self) -> EmployeeDocumentCreate:
        if self.issue_date and self.expiry_date and self.expiry_date < self.issue_date:
            raise ValueError("expiry_date cannot be earlier than issue_date.")
        return self

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
    title: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    issue_date: date | None = None
    expiry_date: date | None = None
    visibility: str | None = None
    status: str | None = None
    tags: str | None = Field(None, max_length=255)

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("title cannot be empty or blank")
        return v

    @model_validator(mode="after")
    def validate_dates(self) -> EmployeeDocumentUpdate:
        if self.issue_date and self.expiry_date and self.expiry_date < self.issue_date:
            raise ValueError("expiry_date cannot be earlier than issue_date.")
        return self

    @field_validator("visibility")
    @classmethod
    def validate_visibility(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.upper()
        if v not in VISIBILITY_VALUES:
            raise ValueError(f"visibility must be one of: {', '.join(VISIBILITY_VALUES)}")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.upper()
        if v not in STATUS_VALUES:
            raise ValueError(f"status must be one of: {', '.join(STATUS_VALUES)}")
        if v in {"VERIFIED", "REJECTED"}:
            raise ValueError("Status transitions to VERIFIED or REJECTED must use dedicated /verify or /reject endpoints.")
        return v


class EmployeeDocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    employee_id: uuid.UUID
    category_id: uuid.UUID | None = None
    uploaded_by: uuid.UUID | None = None
    title: str | None = None
    description: str | None = None
    file_name: str | None = None
    file_size: int | None = None
    issue_date: date | None = None
    expiry_date: date | None = None
    version: int = 1
    status: str = "PENDING"
    visibility: str = "PRIVATE"
    tags: str | None = None
    created_at: datetime
    updated_at: datetime | None = None

    # Enriched fields
    is_verified: bool = False
    verified_by: uuid.UUID | None = None
    verified_at: datetime | None = None
    file_url: str | None = None
    document_type: str | None = None
    employee_name: str | None = None
    employee_code: str | None = None
    category_name: str | None = None
    category_code: str | None = None
    last_review: dict[str, Any] | None = None
    signature_status: str | None = None
    uploaded_by_name: str | None = None
    document_hash: str | None = None


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


class CompanyDocumentUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=150)
    description: str | None = None
    department: str | None = Field(None, max_length=100)
    branch: str | None = Field(None, max_length=100)
    visibility: str | None = None

    @field_validator("visibility")
    @classmethod
    def validate_visibility(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.upper()
        if v not in VISIBILITY_VALUES:
            raise ValueError(f"visibility must be one of: {', '.join(VISIBILITY_VALUES)}")
        return v


class CompanyDocumentResponse(BaseModel):
    """Schema for company document responses.

    Company documents are published directly by Admin/HR and do not undergo
    verification workflows (requires_verification is always False, status is ACTIVE/PUBLISHED).
    """
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    category_id: uuid.UUID
    uploaded_by: uuid.UUID
    title: str
    description: str | None = None
    file_name: str
    file_size: int
    department: str | None = None
    branch: str | None = None
    visibility: str = "PUBLIC"
    status: str = "PUBLISHED"
    requires_verification: bool = False
    created_at: datetime
    updated_at: datetime | None = None

    # Enriched fields
    file_url: str | None = None
    category_name: str | None = None
    category_code: str | None = None
    uploaded_by_name: str | None = None
    version: int | None = 1


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
    description: str | None = None
    template_body: str
    created_by: uuid.UUID
    created_at: datetime
    company_id: uuid.UUID | None = None


class TemplateGenerateRequest(BaseModel):
    employee_id: uuid.UUID
    fields: dict[str, str] = Field(default_factory=dict)
    save_as_document: bool = False


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
    signed_at: datetime | None = None
    ip_address: str | None = None
    device_info: str | None = None
    document_hash: str | None = None
    created_at: datetime | None = None


# ---------------------------------------------------------------------------
# Verification Schemas
# ---------------------------------------------------------------------------

class VerificationPayload(BaseModel):
    comments: str | None = Field(None, max_length=1000)


class RejectPayload(BaseModel):
    comments: str = Field(..., min_length=1, max_length=1000)


class ReuploadRequestPayload(BaseModel):
    comments: str = Field(..., min_length=1, max_length=1000)


# ---------------------------------------------------------------------------
# Version History Schemas
# ---------------------------------------------------------------------------

class VersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version_number: int
    uploaded_by: uuid.UUID
    created_at: datetime
    download_url: str | None = None
    document_hash: str | None = None


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
    details: str | None = None
    ip_address: str | None = None
    created_at: datetime
