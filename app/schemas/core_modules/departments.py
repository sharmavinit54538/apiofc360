"""Pydantic schemas for Departments Core Module."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID
from pydantic import BaseModel, Field


class DepartmentCreateRequest(BaseModel):
    # inferred field — confirm with product/spec owner
    department_name: str = Field(..., description="Name of the department")
    # inferred field — confirm with product/spec owner
    department_code: str = Field(..., description="Unique department code e.g. ENG, HR")
    # inferred field — confirm with product/spec owner
    description: Optional[str] = None
    # inferred field — confirm with product/spec owner
    manager_id: Optional[UUID] = None
    # inferred field — confirm with product/spec owner
    parent_department_id: Optional[UUID] = None
    # inferred field — confirm with product/spec owner
    location: Optional[str] = None
    # inferred field — confirm with product/spec owner
    cost_center: Optional[str] = None
    # inferred field — confirm with product/spec owner
    budget: Optional[float] = None


class DepartmentUpdateRequest(BaseModel):
    # inferred field — confirm with product/spec owner
    department_name: Optional[str] = None
    # inferred field — confirm with product/spec owner
    department_code: Optional[str] = None
    # inferred field — confirm with product/spec owner
    description: Optional[str] = None
    # inferred field — confirm with product/spec owner
    manager_id: Optional[UUID] = None
    # inferred field — confirm with product/spec owner
    parent_department_id: Optional[UUID] = None
    # inferred field — confirm with product/spec owner
    location: Optional[str] = None
    # inferred field — confirm with product/spec owner
    cost_center: Optional[str] = None
    # inferred field — confirm with product/spec owner
    budget: Optional[float] = None
    # inferred field — confirm with product/spec owner
    status: Optional[str] = None


class DepartmentResponse(BaseModel):
    id: str
    department_name: str
    department_code: str
    description: Optional[str] = None
    manager_id: Optional[str] = None
    parent_department_id: Optional[str] = None
    location: Optional[str] = None
    status: Optional[str] = None
    is_deleted: bool = False
    created_at: Optional[str] = None

    class Config:
        from_attributes = True
