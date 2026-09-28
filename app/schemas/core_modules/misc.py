"""Pydantic schemas for Recruiter, Workforce, Managers, Reports, and Misc Top-Level Modules."""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional
from uuid import UUID
from pydantic import BaseModel, Field


# ── Recruiter Schemas ─────────────────────────────────────────────────────────

class JobPostingCreateRequest(BaseModel):
    # inferred field — confirm with product/spec owner
    title: str = Field(..., description="Job role title e.g. Backend Engineer")
    # inferred field — confirm with product/spec owner
    department: Optional[str] = None
    # inferred field — confirm with product/spec owner
    location: Optional[str] = "Remote"
    # inferred field — confirm with product/spec owner
    status: str = Field("open", description="open | closed | on_hold")
    # inferred field — confirm with product/spec owner
    requirements: Optional[str] = None
    # inferred field — confirm with product/spec owner
    description: Optional[str] = None


class JobPostingResponse(BaseModel):
    id: str
    title: str
    department: Optional[str] = None
    status: str
    created_at: Optional[str] = None

    class Config:
        from_attributes = True


class CandidateResponse(BaseModel):
    id: str
    first_name: str
    last_name: str
    email: str
    phone: Optional[str] = None
    skills: Optional[List[str]] = None
    years_experience: Optional[float] = None
    created_at: Optional[str] = None

    class Config:
        from_attributes = True


# ── Reports & Exports ──────────────────────────────────────────────────────────

class ReportExportRequest(BaseModel):
    # inferred field — confirm with product/spec owner
    report_type: str = Field(..., description="attendance | payroll | performance | head_count")
    # inferred field — confirm with product/spec owner
    format: str = Field("csv", description="csv | xlsx | pdf")
    # inferred field — confirm with product/spec owner
    filters: Dict[str, Any] = Field(default_factory=dict)


# ── Top-Level Misc Responses ──────────────────────────────────────────────────

class NotificationResponse(BaseModel):
    id: str
    title: str
    message: str
    is_read: bool = False
    created_at: Optional[str] = None

    class Config:
        from_attributes = True


class DocumentResponse(BaseModel):
    id: str
    title: str
    file_name: Optional[str] = None
    file_size: Optional[int] = None
    department: Optional[str] = None
    created_at: Optional[str] = None

    class Config:
        from_attributes = True


class AssetResponse(BaseModel):
    id: str
    tag: Optional[str] = None
    name: str
    category: Optional[str] = None
    status: Optional[str] = None
    assigned_to: Optional[str] = None

    class Config:
        from_attributes = True
