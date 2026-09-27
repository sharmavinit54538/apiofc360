"""Pydantic schemas for Users and Profile Core Modules."""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional
from uuid import UUID
from pydantic import BaseModel, EmailStr, Field


class UserUpdateRequest(BaseModel):
    # inferred field — confirm with product/spec owner
    name: Optional[str] = None
    # inferred field — confirm with product/spec owner
    email: Optional[EmailStr] = None
    # inferred field — confirm with product/spec owner
    phone: Optional[str] = None
    # inferred field — confirm with product/spec owner
    role: Optional[str] = None
    # inferred field — confirm with product/spec owner
    is_active: Optional[bool] = None
    # inferred field — confirm with product/spec owner
    account_status: Optional[str] = None


class ProfileUpdateRequest(BaseModel):
    # inferred field — confirm with product/spec owner
    first_name: Optional[str] = None
    # inferred field — confirm with product/spec owner
    last_name: Optional[str] = None
    # inferred field — confirm with product/spec owner
    phone: Optional[str] = None
    # inferred field — confirm with product/spec owner
    alternate_phone: Optional[str] = None
    # inferred field — confirm with product/spec owner
    personal_email: Optional[EmailStr] = None
    # inferred field — confirm with product/spec owner
    marital_status: Optional[str] = None
    # inferred field — confirm with product/spec owner
    blood_group: Optional[str] = None
    # inferred field — confirm with product/spec owner
    work_location: Optional[str] = None
    # inferred field — confirm with product/spec owner
    work_mode: Optional[str] = None
    # inferred field — confirm with product/spec owner
    emergency_contact: Optional[str] = None


class UserResponse(BaseModel):
    id: str
    email: str
    name: Optional[str] = None
    phone: Optional[str] = None
    role: str
    is_active: bool
    is_verified: bool
    account_status: Optional[str] = None
    company_id: Optional[str] = None
    created_at: Optional[str] = None

    class Config:
        from_attributes = True


class ProfileResponse(BaseModel):
    id: str
    user_id: Optional[str] = None
    employee_id: Optional[str] = None
    first_name: str
    last_name: str
    company_email: Optional[str] = None
    personal_email: Optional[str] = None
    phone: Optional[str] = None
    department: Optional[str] = None
    designation: Optional[str] = None
    joining_date: Optional[str] = None
    employment_status: Optional[str] = None
    employment_type: Optional[str] = None
    work_location: Optional[str] = None
    is_active: bool

    class Config:
        from_attributes = True
