"""Schemas for Face Attendance biometric enrollment, check-in, check-out, and geofence verification."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field


class FaceStatusResponse(BaseModel):
    """Response containing face enrollment status."""
    is_enrolled: bool
    enrolled_at: Optional[str] = None


class FaceEnrollRequest(BaseModel):
    """Request payload for enrolling an employee's face embedding."""
    image_base64: str = Field(..., description="Base64 encoded face image")
    allow_re_enroll: bool = Field(
        False, description="Set True to explicitly confirm replacing existing enrolled face biometric"
    )


class FaceEnrollResponse(BaseModel):
    """Response after enrolling face biometric embedding."""
    is_enrolled: bool = True
    action: str = "enrolled"
    message: str = "Face enrolled successfully"


class CheckInRequest(BaseModel):
    """Request payload for AI facial recognition check-in."""
    image_base64: str = Field(..., description="Captured live face image base64")
    location: Optional[dict[str, Any]] = Field(None, description="GPS location details e.g. latitude, longitude, accuracy")
    notes: Optional[str] = Field(None, description="Optional notes for check-in")
    device_info: Optional[str] = Field(None, description="Device and browser info")
    ip_address: Optional[str] = Field(None, description="Client IP address")


class CheckOutRequest(BaseModel):
    """Request payload for AI facial recognition check-out."""
    image_base64: str = Field(..., description="Captured live face image base64")
    location: Optional[dict[str, Any]] = Field(None, description="GPS location details e.g. latitude, longitude, accuracy")
    notes: Optional[str] = Field(None, description="Optional notes for check-out")
    device_info: Optional[str] = Field(None, description="Device and browser info")
    ip_address: Optional[str] = Field(None, description="Client IP address")


class GeofenceVerifyRequest(BaseModel):
    """Request payload for GPS geofence verification."""
    latitude: float = Field(..., description="Employee GPS latitude")
    longitude: float = Field(..., description="Employee GPS longitude")
    accuracy: Optional[float] = Field(None, description="GPS accuracy radius in meters")


class GeofenceVerifyResponse(BaseModel):
    """Response from geofence verification."""
    inside_geofence: bool
    distance: Optional[float] = None
    allowed_radius: float = 200.0
    accuracy: Optional[float] = None
    status: str
    office_name: str
    message: str


class BreakStartRequest(BaseModel):
    """Request payload to start a break session."""
    image_base64: Optional[str] = Field(None, description="Captured live face image base64")
    location: Optional[dict[str, Any]] = Field(None, description="GPS location details e.g. latitude, longitude, accuracy")
    notes: Optional[str] = Field(None, description="Optional reason or notes for the break")
    device_info: Optional[str] = Field(None, description="Device and browser info")
    ip_address: Optional[str] = Field(None, description="Client IP address")


class BreakEndRequest(BaseModel):
    """Request payload to end a break session."""
    image_base64: Optional[str] = Field(None, description="Captured live face image base64")
    location: Optional[dict[str, Any]] = Field(None, description="GPS location details e.g. latitude, longitude, accuracy")
    notes: Optional[str] = Field(None, description="Optional notes for ending the break")
    device_info: Optional[str] = Field(None, description="Device and browser info")
    ip_address: Optional[str] = Field(None, description="Client IP address")


class BreakSessionResponse(BaseModel):
    """Break session response item."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    attendance_id: uuid.UUID
    break_start: datetime
    break_end: Optional[datetime] = None
    duration_minutes: Optional[float] = None
    status: str
    notes: Optional[str] = None
    start_image_url: Optional[str] = None
    end_image_url: Optional[str] = None
    start_face_distance: Optional[float] = None
    end_face_distance: Optional[float] = None
    start_liveness_score: Optional[float] = None
    end_liveness_score: Optional[float] = None
    start_latitude: Optional[float] = None
    start_longitude: Optional[float] = None
    end_latitude: Optional[float] = None
    end_longitude: Optional[float] = None
    face_distance: Optional[float] = None
    liveness_score: Optional[float] = None
    image_url: Optional[str] = None

