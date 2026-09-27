"""Pydantic schemas for Compliance and Employee Health Modules."""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional
from uuid import UUID
from pydantic import BaseModel, Field


# ── Compliance Schemas ─────────────────────────────────────────────────────────

class ComplianceRecordCreateRequest(BaseModel):
    # inferred field — confirm with product/spec owner
    compliance_type: str = Field(..., description="e.g. Labour Law, POSH Policy, Tax Filing")
    # inferred field — confirm with product/spec owner
    title: str = Field(..., description="Document or obligation title")
    # inferred field — confirm with product/spec owner
    employee_id: Optional[UUID] = None
    # inferred field — confirm with product/spec owner
    status: str = Field("compliant", description="compliant | pending | overdue")
    # inferred field — confirm with product/spec owner
    due_date: Optional[date] = None
    # inferred field — confirm with product/spec owner
    document_url: Optional[str] = None
    # inferred field — confirm with product/spec owner
    notes: Optional[str] = None


class ComplianceRecordResponse(BaseModel):
    id: str
    compliance_type: str
    title: str
    status: str
    due_date: Optional[str] = None
    completed_at: Optional[str] = None
    document_url: Optional[str] = None
    notes: Optional[str] = None
    created_at: Optional[str] = None

    class Config:
        from_attributes = True


class ComplianceDashboardResponse(BaseModel):
    # inferred field — confirm with product/spec owner
    health_score: float = Field(..., description="Overall company compliance health score out of 100")
    # inferred field — confirm with product/spec owner
    total_obligations: int
    # inferred field — confirm with product/spec owner
    compliant_count: int
    # inferred field — confirm with product/spec owner
    pending_count: int
    # inferred field — confirm with product/spec owner
    overdue_count: int
    # inferred field — confirm with product/spec owner
    breakdown: Dict[str, Any] = Field(default_factory=dict)


# ── Employee Health Schemas ───────────────────────────────────────────────────

class HealthRecordCreateRequest(BaseModel):
    # inferred field — confirm with product/spec owner
    employee_id: UUID
    # inferred field — confirm with product/spec owner
    record_type: str = Field("medical_checkup", description="annual_checkup | fitness | vaccination")
    # inferred field — confirm with product/spec owner
    blood_group: Optional[str] = None
    # inferred field — confirm with product/spec owner
    allergies: Optional[str] = None
    # inferred field — confirm with product/spec owner
    fitness_clearance: bool = Field(True, description="Fit to work clearance")
    # inferred field — confirm with product/spec owner
    doctor_remarks: Optional[str] = None
    # inferred field — confirm with product/spec owner
    last_checkup_date: Optional[date] = None


class HealthRecordResponse(BaseModel):
    id: str
    employee_id: str
    record_type: str
    blood_group: Optional[str] = None
    allergies: Optional[str] = None
    fitness_clearance: bool
    doctor_remarks: Optional[str] = None
    last_checkup_date: Optional[str] = None
    created_at: Optional[str] = None

    class Config:
        from_attributes = True
