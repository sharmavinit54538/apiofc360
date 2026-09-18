"""Schemas for Face Attendance biometric enrollment and check-in."""

from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field


class FaceStatusResponse(BaseModel):
    """Response containing face enrollment status."""
    is_enrolled: bool
    enrolled_at: Optional[str] = None


class FaceEnrollRequest(BaseModel):
    """Request payload for enrolling an employee's face embedding."""
    image_base64: str = Field(..., description="Base64 encoded face image")


class FaceEnrollResponse(BaseModel):
    """Response after enrolling face biometric embedding."""
    is_enrolled: bool = True
    message: str = "Face enrolled successfully"


class CheckInRequest(BaseModel):
    """Request payload for AI facial recognition check-in."""
    image_base64: str = Field(..., description="Captured live face image base64")
    location: Optional[dict[str, Any]] = Field(None, description="GPS location details e.g. latitude, longitude")
    notes: Optional[str] = Field(None, description="Optional notes for check-in")
    device_info: Optional[str] = Field(None, description="Device and browser info")
    ip_address: Optional[str] = Field(None, description="Client IP address")
