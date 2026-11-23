"""Pydantic Schemas for Settings, MFA, and Billing modules."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


# ===========================================================================
# 1. HR Settings Schemas
# ===========================================================================

class HRSettingsResponseData(BaseModel):
    """Schema for HR configuration response."""
    hr_name: str = "HR Department"
    hr_email: str = "hr@ofc360.com"
    hr_phone: str = "+91 98765 43210"
    working_days: List[str] = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    working_hours_start: str = "09:00"
    working_hours_end: str = "18:00"
    timezone: str = "Asia/Kolkata"
    attendance_enabled: bool = True
    daily_face_verification_required: bool = True
    leave_enabled: bool = True
    payroll_enabled: bool = True
    week_start_day: Optional[str] = "Monday"
    office_timing: Optional[str] = "09:00 - 18:00"
    default_shift: Optional[str] = "General"
    time_format: Optional[str] = "12h"
    date_format: Optional[str] = "DD/MM/YYYY"
    financial_year: Optional[str] = "April - March"
    leave_policy_template: Optional[str] = "Standard"

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


class HRSettingsUpdatePayload(BaseModel):
    """Schema for updating company HR settings."""
    daily_face_verification_required: Optional[bool] = None
    hr_name: Optional[str] = Field(None, min_length=2, max_length=100)
    hr_email: Optional[EmailStr] = None
    hr_phone: Optional[str] = None
    working_days: Optional[List[str]] = None
    working_hours_start: Optional[str] = None
    working_hours_end: Optional[str] = None
    timezone: Optional[str] = None
    attendance_enabled: Optional[bool] = None
    leave_enabled: Optional[bool] = None
    payroll_enabled: Optional[bool] = None
    week_start_day: Optional[str] = None
    office_timing: Optional[str] = None
    default_shift: Optional[str] = None
    time_format: Optional[str] = None
    date_format: Optional[str] = None
    financial_year: Optional[str] = None
    leave_policy_template: Optional[str] = None

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("hr_phone")
    @classmethod
    def validate_phone(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            clean = re.sub(r"[\s\-\(\)\+]", "", v)
            if not (7 <= len(clean) <= 15 and clean.isdigit()):
                raise ValueError("Phone number must contain between 7 and 15 digits.")
        return v

    @field_validator("working_hours_start", "working_hours_end")
    @classmethod
    def validate_time_format(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            clean = v.strip()
            # Support HH:MM (24h) or HH:MM AM/PM
            if not re.match(r"^([01]?\d|2[0-3]):[0-5]\d(\s*(AM|PM|am|pm))?$", clean):
                raise ValueError("Time must be in HH:MM format (e.g. '09:00' or '18:00').")
        return v

    @field_validator("working_days")
    @classmethod
    def validate_working_days(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is not None:
            valid_days = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}
            for day in v:
                if str(day).strip().lower() not in valid_days:
                    raise ValueError(f"Invalid day name: '{day}'. Must be a standard day of the week.")
        return v


# ===========================================================================
# 2. MFA Schemas
# ===========================================================================

class MFAEnablePayload(BaseModel):
    """Payload to initiate or complete MFA enablement."""
    code: Optional[str] = Field(None, description="6-digit TOTP code to confirm activation.")
    password: Optional[str] = Field(None, description="User password for high-security confirmation if required.")

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            clean = v.strip().replace(" ", "")
            if not (len(clean) == 6 and clean.isdigit()):
                raise ValueError("MFA code must be exactly 6 numeric digits.")
            return clean
        return v


class MFAEnableResponseData(BaseModel):
    """Response data for MFA enable endpoint."""
    mfa_enabled: bool
    method: str = "totp"
    secret: Optional[str] = None
    provisioning_uri: Optional[str] = None
    qr_code: Optional[str] = None
    backup_codes: Optional[List[str]] = None


class MFADisablePayload(BaseModel):
    """Payload to disable MFA for the user."""
    code: Optional[str] = None
    password: Optional[str] = None

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            clean = v.strip().replace(" ", "")
            if not (len(clean) == 6 and clean.isdigit()):
                raise ValueError("MFA code must be exactly 6 numeric digits.")
            return clean
        return v


class MFADisableResponseData(BaseModel):
    """Response data for MFA disable endpoint."""
    mfa_enabled: bool = False


# ===========================================================================
# 3. Billing & Subscription Schemas
# ===========================================================================

class SubscriptionResponseData(BaseModel):
    """Schema for company subscription information."""
    subscription_id: str = "sub_enterprise_001"
    plan_name: str = "Enterprise AI Tier"
    plan_code: str = "enterprise"
    status: str = "active"
    billing_cycle: str = "monthly"
    price: float = 49999.0
    currency: str = "INR"
    start_date: Optional[str] = "2026-01-01T00:00:00Z"
    current_period_start: Optional[str] = "2026-01-01T00:00:00Z"
    current_period_end: Optional[str] = "2026-12-31T23:59:59Z"
    next_billing_date: Optional[str] = "2026-12-31"
    cancel_at_period_end: bool = False
    cancelled_at: Optional[str] = None
    used_seats: int = 1
    total_seats: int = 350
    features: List[str] = [
        "Unlimited AI Workflows",
        "Autonomous Screening & Interviews",
        "Full HR & Payroll Intelligence",
        "24/7 Priority Support",
    ]


class PaymentMethodResponseData(BaseModel):
    """Safe payment method representation without sensitive credentials."""
    id: str
    type: str = "card"
    brand: Optional[str] = "visa"
    last4: Optional[str] = "4242"
    expiry_month: Optional[int] = 12
    expiry_year: Optional[int] = 2030
    is_default: bool = False
    created_at: Optional[str] = None


class AddPaymentMethodPayload(BaseModel):
    """Payload to safely attach a new payment method."""
    payment_method_id: Optional[str] = None
    type: str = Field("card", description="Payment method type (card, upi, bank_account).")
    brand: Optional[str] = "visa"
    last4: Optional[str] = Field("4242", min_length=4, max_length=4)
    expiry_month: Optional[int] = Field(12, ge=1, le=12)
    expiry_year: Optional[int] = Field(2030, ge=2024, le=2099)
    make_default: bool = True

    @field_validator("last4")
    @classmethod
    def validate_last4(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not (len(v) == 4 and v.isdigit()):
            raise ValueError("last4 must be exactly 4 digits.")
        return v


class InvoiceItem(BaseModel):
    """Safe invoice record representation."""
    id: str
    invoice_number: str
    status: str = "paid"
    amount: float
    currency: str = "INR"
    invoice_date: str
    due_date: Optional[str] = None
    paid_at: Optional[str] = None
    pdf_url: Optional[str] = None


class InvoicesPaginationData(BaseModel):
    """Paginated invoices envelope."""
    items: List[InvoiceItem]
    page: int = 1
    page_size: int = 20
    total: int = 0
    pages: int = 1


# ===========================================================================
# 4. Settings Management Module Schemas (Employee, Leave, Document, Asset, Logo)
# ===========================================================================

class CompanyLogoResponse(BaseModel):
    """Company logo upload response."""
    logo_url: str
    updated_at: str
    logo: Optional[str] = None
    logoUrl: Optional[str] = None

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


class EmployeeSettingsResponse(BaseModel):
    """Organization-wide employee configuration response."""
    employee_id_prefix: str = "EMP"
    employee_id_start_number: int = 1001
    probation_period_days: int = 90
    default_employment_type: str = "full_time"
    default_employee_status: str = "active"
    allow_employee_profile_edit: bool = True
    require_manager_assignment: bool = False

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


class EmployeeSettingsUpdate(BaseModel):
    """Organization-wide employee configuration update payload."""
    employee_id_prefix: Optional[str] = Field(None, min_length=1, max_length=10)
    employee_id_start_number: Optional[int] = Field(None, ge=1)
    probation_period_days: Optional[int] = Field(None, ge=0, le=365)
    default_employment_type: Optional[str] = Field(None, max_length=50)
    default_employee_status: Optional[str] = Field(None, max_length=50)
    allow_employee_profile_edit: Optional[bool] = None
    require_manager_assignment: Optional[bool] = None

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("employee_id_prefix")
    @classmethod
    def validate_prefix(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            clean = v.strip().upper()
            if not re.match(r"^[A-Z0-9\-_]{1,10}$", clean):
                raise ValueError("Employee ID prefix must be 1-10 alphanumeric characters (hyphens and underscores allowed).")
            return clean
        return v


class LeaveSettingsResponse(BaseModel):
    """Organization-wide leave management configuration response."""
    leave_year_start_month: int = 1
    allow_half_day_leave: bool = True
    allow_negative_balance: bool = False
    require_manager_approval: bool = True
    max_consecutive_leave_days: int = 30
    carry_forward_enabled: bool = True
    carry_forward_limit: int = 10
    leave_encashment_enabled: bool = False

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


class LeaveSettingsUpdate(BaseModel):
    """Organization-wide leave management configuration update payload."""
    leave_year_start_month: Optional[int] = Field(None, ge=1, le=12)
    allow_half_day_leave: Optional[bool] = None
    allow_negative_balance: Optional[bool] = None
    require_manager_approval: Optional[bool] = None
    max_consecutive_leave_days: Optional[int] = Field(None, ge=1, le=365)
    carry_forward_enabled: Optional[bool] = None
    carry_forward_limit: Optional[int] = Field(None, ge=0)
    leave_encashment_enabled: Optional[bool] = None

    model_config = ConfigDict(populate_by_name=True)


FORBIDDEN_FILE_EXTENSIONS = {
    "exe", "bat", "cmd", "sh", "py", "pl", "php", "js", "html", "htm",
    "vbs", "jar", "svg", "dll", "so", "bin", "com", "scr", "msi", "app",
}


class DocumentSettingsResponse(BaseModel):
    """Organization-wide document management configuration response."""
    allowed_file_types: List[str] = ["pdf", "jpg", "jpeg", "png"]
    max_file_size_mb: int = 10
    require_document_verification: bool = True
    document_expiry_alert_days: int = 30
    employee_can_upload_documents: bool = True
    manager_can_view_documents: bool = False

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


class DocumentSettingsUpdate(BaseModel):
    """Organization-wide document management configuration update payload."""
    allowed_file_types: Optional[List[str]] = None
    max_file_size_mb: Optional[int] = Field(None, ge=1, le=100)
    require_document_verification: Optional[bool] = None
    document_expiry_alert_days: Optional[int] = Field(None, ge=0, le=365)
    employee_can_upload_documents: Optional[bool] = None
    manager_can_view_documents: Optional[bool] = None

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("allowed_file_types")
    @classmethod
    def validate_file_types(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is not None:
            if not v:
                raise ValueError("Allowed file types list cannot be empty.")
            cleaned: List[str] = []
            for ext in v:
                clean_ext = str(ext).strip().lower().lstrip(".")
                if not clean_ext:
                    continue
                if clean_ext in FORBIDDEN_FILE_EXTENSIONS:
                    raise ValueError(f"File type '{clean_ext}' is strictly forbidden for security reasons.")
                if not re.match(r"^[a-z0-9]{1,10}$", clean_ext):
                    raise ValueError(f"Invalid file extension format: '{clean_ext}'.")
                if clean_ext not in cleaned:
                    cleaned.append(clean_ext)
            if not cleaned:
                raise ValueError("At least one valid file type extension must be specified.")
            return cleaned
        return v


class AssetSettingsResponse(BaseModel):
    """Organization-wide asset management configuration response."""
    asset_id_prefix: str = "AST"
    require_assignment_approval: bool = True
    enable_asset_return_tracking: bool = True
    enable_asset_condition_tracking: bool = True
    enable_warranty_reminders: bool = True
    warranty_reminder_days: int = 30
    enable_asset_depreciation: bool = False

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


class AssetSettingsUpdate(BaseModel):
    """Organization-wide asset management configuration update payload."""
    asset_id_prefix: Optional[str] = Field(None, min_length=1, max_length=10)
    require_assignment_approval: Optional[bool] = None
    enable_asset_return_tracking: Optional[bool] = None
    enable_asset_condition_tracking: Optional[bool] = None
    enable_warranty_reminders: Optional[bool] = None
    warranty_reminder_days: Optional[int] = Field(None, ge=0, le=365)
    enable_asset_depreciation: Optional[bool] = None

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("asset_id_prefix")
    @classmethod
    def validate_asset_prefix(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            clean = v.strip().upper()
            if not re.match(r"^[A-Z0-9\-_]{1,10}$", clean):
                raise ValueError("Asset ID prefix must be 1-10 alphanumeric characters (hyphens and underscores allowed).")
            return clean
        return v
