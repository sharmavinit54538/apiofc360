"""Pydantic schemas for Attendance Core Module."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class AttendanceCheckInRequest(BaseModel):
    # inferred field — confirm with product/spec owner
    latitude: Optional[float] = Field(None, description="GPS latitude for geofenced check-in")
    # inferred field — confirm with product/spec owner
    longitude: Optional[float] = Field(None, description="GPS longitude for geofenced check-in")
    # inferred field — confirm with product/spec owner
    ip_address: Optional[str] = Field(None, description="Client IP address")
    # inferred field — confirm with product/spec owner
    device_info: Optional[str] = Field(None, description="User agent or device model")
    # inferred field — confirm with product/spec owner
    notes: Optional[str] = Field(None, description="Optional check-in remark")


class AttendanceCheckOutRequest(BaseModel):
    # inferred field — confirm with product/spec owner
    latitude: Optional[float] = Field(None, description="GPS latitude for geofenced check-out")
    # inferred field — confirm with product/spec owner
    longitude: Optional[float] = Field(None, description="GPS longitude for geofenced check-out")
    # inferred field — confirm with product/spec owner
    ip_address: Optional[str] = Field(None, description="Client IP address")
    # inferred field — confirm with product/spec owner
    device_info: Optional[str] = Field(None, description="User agent or device model")
    # inferred field — confirm with product/spec owner
    notes: Optional[str] = Field(None, description="Optional check-out remark")


class FaceCheckInRequest(BaseModel):
    # inferred field — confirm with product/spec owner
    image_base64: Optional[str] = Field(None, description="Base64 encoded live webcam/mobile capture")
    # inferred field — confirm with product/spec owner
    image_url: Optional[str] = Field(None, description="S3 or cloud storage image URL")
    # inferred field — confirm with product/spec owner
    latitude: Optional[float] = None
    # inferred field — confirm with product/spec owner
    longitude: Optional[float] = None
    # inferred field — confirm with product/spec owner
    liveness_verified: bool = Field(True, description="Biometric anti-spoofing status")


class FaceEnrollRequest(BaseModel):
    # inferred field — confirm with product/spec owner
    employee_id: UUID = Field(..., description="Target employee for biometric registration")
    # inferred field — confirm with product/spec owner
    image_base64: str = Field(..., description="Reference face image base64")
    # inferred field — confirm with product/spec owner
    consent_given: bool = Field(True, description="Explicit employee biometric storage consent")


class AttendanceManualUpdateRequest(BaseModel):
    # inferred field — confirm with product/spec owner
    check_in_time: Optional[datetime] = None
    # inferred field — confirm with product/spec owner
    check_out_time: Optional[datetime] = None
    # inferred field — confirm with product/spec owner
    status: Optional[str] = Field(None, description="PRESENT, ABSENT, HALF_DAY, ON_LEAVE, LATE")
    # inferred field — confirm with product/spec owner
    audit_reason: str = Field(..., description="Mandatory audit log rationale for manual edit")


class AttendanceRegularizationCreateRequest(BaseModel):
    # inferred field — confirm with product/spec owner
    request_date: date = Field(..., description="The date requiring regularization")
    # inferred field — confirm with product/spec owner
    requested_check_in: Optional[datetime] = None
    # inferred field — confirm with product/spec owner
    requested_check_out: Optional[datetime] = None
    # inferred field — confirm with product/spec owner
    reason: str = Field(..., description="Reason for regularization request")
    # inferred field — confirm with product/spec owner
    attendance_id: Optional[UUID] = None


class AttendanceRegularizationActionRequest(BaseModel):
    # inferred field — confirm with product/spec owner
    action: str = Field(..., description="APPROVE or REJECT")
    # inferred field — confirm with product/spec owner
    remarks: Optional[str] = None


class AttendanceRecordResponse(BaseModel):
    id: str
    employee_id: str
    date: str
    check_in_time: Optional[str] = None
    check_out_time: Optional[str] = None
    status: str
    is_late: bool = False
    late_minutes: int = 0
    working_hours: float = 0.0
    verified: bool = False
    punch_type: Optional[str] = None
    notes: Optional[str] = None

    class Config:
        from_attributes = True


class AttendanceRegularizationResponse(BaseModel):
    id: str
    employee_id: str
    request_date: str
    requested_check_in: Optional[str] = None
    requested_check_out: Optional[str] = None
    reason: str
    status: str
    remarks: Optional[str] = None
    created_at: str

    class Config:
        from_attributes = True
