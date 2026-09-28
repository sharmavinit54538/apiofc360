"""Daily Face Attendance check-out controller routes."""

from __future__ import annotations

import base64
import logging
from typing import Annotated, Any, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance.schemas.response import AttendanceResponse
from app.attendance.services.checkout_service import AttendanceCheckOutService
from app.core.exceptions import AppException
from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_user_id(claims: dict) -> uuid.UUID:
    return uuid.UUID(claims.get("sub"))


def _get_company_id(claims: dict) -> uuid.UUID:
    company_id_str = claims.get("company_id")
    if not company_id_str:
        raise AppException(
            message="Company context missing in user authentication claims.",
            status_code=status.HTTP_403_FORBIDDEN,
        )
    return uuid.UUID(str(company_id_str))


async def _handle_checkout_request(
    request: Request,
    user_id: uuid.UUID,
    company_id: uuid.UUID,
    db: AsyncSession,
) -> dict:
    """Unified handler accepting either JSON body or multipart/form-data with real face verification."""
    content_type = request.headers.get("content-type", "").lower()
    service = AttendanceCheckOutService(db)
    client_ip = request.client.host if request.client else None

    image_b64: Optional[str] = None
    location_dict: Optional[dict] = None
    notes: Optional[str] = None
    device_info: Optional[str] = None

    if "multipart/form-data" in content_type:
        form = await request.form()
        file_obj = form.get("file")
        if not file_obj or not hasattr(file_obj, "read"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "FACE_QUALITY_LOW", "message": "Uploaded face image file is required for checkout."},
            )
        file_bytes = await file_obj.read()
        image_b64 = base64.b64encode(file_bytes).decode("utf-8")

        lat = form.get("latitude")
        lng = form.get("longitude")
        acc = form.get("accuracy")
        if lat is not None and lng is not None:
            location_dict = {
                "latitude": float(lat),
                "longitude": float(lng),
                "accuracy": float(acc) if acc is not None else None,
            }
        notes = form.get("notes")
        device_info = form.get("device_info")
    else:
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "BAD_REQUEST", "message": "Invalid JSON request payload."},
            )
        image_b64 = body.get("image_base64")
        location_dict = body.get("location")
        notes = body.get("notes")
        device_info = body.get("device_info")

    if not image_b64:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "FACE_QUALITY_LOW", "message": "Face image is required for checkout verification."},
        )

    record = await service.check_out_with_face_base64(
        user_id=user_id,
        company_id=company_id,
        image_base64=image_b64,
        location=location_dict,
        notes=notes,
        device_info=device_info,
        ip_address=client_ip,
    )

    return {
        "success": True,
        "message": "Checked out successfully.",
        "data": AttendanceResponse.model_validate(record).model_dump(mode="json"),
        "error": None,
    }


@router.post(
    "/face/check-out",
    status_code=status.HTTP_200_OK,
    summary="Record daily attendance check-out with real face matching (JSON or multipart)",
)
@router.post(
    "/checkout",
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
@router.post(
    "/face/checkout",
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
async def ai_face_check_out(
    request: Request,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict:
    """Record daily checkout with real face verification, computing working hours and breaks."""
    user_id = _get_user_id(claims)
    company_id = _get_company_id(claims)
    return await _handle_checkout_request(request, user_id, company_id, db)
