"""Pydantic schemas for Settings Core Module."""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional
from uuid import UUID
from pydantic import BaseModel, Field


class CompanyConfigSectionUpdate(BaseModel):
    # inferred field — confirm with product/spec owner
    config: Dict[str, Any] = Field(default_factory=dict, description="Key-value dictionary for settings section")


class EmploymentTypeCreateRequest(BaseModel):
    # inferred field — confirm with product/spec owner
    name: str = Field(..., description="Full-Time, Contract, Intern, Part-Time")
    # inferred field — confirm with product/spec owner
    code: str = Field(..., description="Short code like FT, CT, INT")
    # inferred field — confirm with product/spec owner
    description: Optional[str] = None
    # inferred field — confirm with product/spec owner
    is_active: bool = True


class DesignationCreateRequest(BaseModel):
    # inferred field — confirm with product/spec owner
    name: str = Field(..., description="Job designation title e.g. Senior Software Engineer")
    # inferred field — confirm with product/spec owner
    description: Optional[str] = None


class HolidayCreateRequest(BaseModel):
    # inferred field — confirm with product/spec owner
    name: str = Field(..., description="Holiday title e.g. Diwali, Independence Day")
    # inferred field — confirm with product/spec owner
    holiday_date: date = Field(..., description="Date of the holiday")
    # inferred field — confirm with product/spec owner
    type: str = Field("national", description="national | optional | restricted")
    # inferred field — confirm with product/spec owner
    is_recurring: bool = Field(False, description="Whether this recurs annually")
    # inferred field — confirm with product/spec owner
    description: Optional[str] = None


class MasterItemResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    created_at: Optional[str] = None
    # inferred field — confirm with product/spec owner
    extra: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        from_attributes = True
