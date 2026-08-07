"""Pydantic schemas and validation for Enterprise Payroll Security Management System."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


class SecurityRoleSchema(BaseModel):
    id: Optional[str] = None
    role_name: str
    role_code: str
    description: Optional[str] = None
    is_system_role: bool = False
    is_active: bool = True
    permissions: List[str] = []


class RoleCreateSchema(BaseModel):
    role_name: str = Field(..., min_length=2, max_length=100)
    role_code: str = Field(..., min_length=2, max_length=50)
    description: Optional[str] = None
    permissions: List[str] = []

    @field_validator("role_code")
    @classmethod
    def validate_role_code(cls, v: str) -> str:
        v = v.strip().upper().replace(" ", "_")
        if not re.match(r"^[A-Z0-9_]{2,50}$", v):
            raise ValueError("Role code must contain uppercase letters, numbers, or underscores")
        return v


class SecurityPolicyUpdateSchema(BaseModel):
    session_timeout_minutes: Optional[int] = Field(None, ge=5, le=1440)
    idle_timeout_minutes: Optional[int] = Field(None, ge=1, le=120)
    max_concurrent_sessions: Optional[int] = Field(None, ge=1, le=10)

    min_password_length: Optional[int] = Field(None, ge=8, le=32)
    require_uppercase: Optional[bool] = None
    require_lowercase: Optional[bool] = None
    require_numbers: Optional[bool] = None
    require_special_chars: Optional[bool] = None

    mfa_enabled: Optional[bool] = None
    aes_256_encryption_enabled: Optional[bool] = None
    mask_salary_non_payroll: Optional[bool] = None


class IPWhitelistCreateSchema(BaseModel):
    ip_address_or_range: str = Field(..., min_length=7, max_length=50)
    description: Optional[str] = None

    @field_validator("ip_address_or_range")
    @classmethod
    def validate_ip(cls, v: str) -> str:
        v = v.strip()
        # Accepts IPv4, CIDR like 192.168.1.0/24, or wildcard
        if not re.match(r"^([0-9]{1,3}\.){3}[0-9]{1,3}(/[0-9]{1,2})?$", v) and v != "*":
            raise ValueError("Invalid IP address or CIDR range format (e.g., 192.168.1.1 or 10.0.0.0/16)")
        return v
