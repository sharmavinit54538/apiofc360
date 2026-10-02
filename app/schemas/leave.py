"""Pydantic schemas for Leave Requests and Balances."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class LeaveRequestBase(BaseModel):
    leave_type: str = Field(..., description="Type of leave, e.g. Sick Leave, Casual Leave, Vacation Leave")
    start_date: date = Field(..., description="Start date of leave")
    end_date: date = Field(..., description="End date of leave")
    total_days: Optional[Decimal] = Field(None, ge=0.5, le=365, description="Total days requested (computed server-side)")
    reason: str = Field(..., min_length=5, description="Reason for taking leave")


class LeaveRequestCreate(LeaveRequestBase):
    pass


class LeaveApprovalRequest(BaseModel):
    status: str = Field(..., pattern="^(APPROVED|REJECTED)$")
    rejection_reason: Optional[str] = None


class LeaveRequestResponse(LeaveRequestBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    employee_id: uuid.UUID
    employee_name: str = ""
    department: Optional[str] = None
    total_days: Decimal = Field(..., description="Total days approved/requested")
    status: str
    approved_by_id: Optional[uuid.UUID] = None
    rejection_reason: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class LeaveBalanceResponse(BaseModel):
    leave_type: str
    total_days: float
    used_days: float
    remaining_days: float


class LeaveEmployeeItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    employee_code: str
    full_name: str
    department: str
    designation: str
