"""Tenant attendance policy shared by all punch channels."""
from __future__ import annotations

import math
import uuid

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import Company


async def requires_daily_face(db: AsyncSession, company_id: uuid.UUID) -> bool:
    company = await db.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")
    config = (company.hr_settings or {}).get("hr_config") or {}
    # Face attendance is the default. Only an explicit persisted opt-out allows
    # a non-biometric punch, which must remain unverified.
    return config.get("daily_face_verification_required", True) is not False


def validate_biometric_evidence(image: str | None, distance: float, liveness: float) -> None:
    """Never label an attendance row verified with incomplete provider evidence."""
    if (not image or not math.isfinite(distance) or not 0 <= distance <= 0.50
            or not math.isfinite(liveness) or not 0.40 <= liveness <= 1):
        raise HTTPException(status_code=422, detail={
            "code": "BIOMETRIC_EVIDENCE_INVALID",
            "message": "A stored live image, valid face match and liveness result are required.",
        })
