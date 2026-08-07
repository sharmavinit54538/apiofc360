"""Duplicate Detector Service for identifying duplicate applicants based on email, phone, name, or LinkedIn."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.recruitment import Candidate

logger = logging.getLogger(__name__)


class DuplicateDetectorService:
    """Service to detect existing duplicate candidate records in the database."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def check_duplicate(
        self,
        email: str | None,
        phone: str | None,
        name: str | None = None,
        linkedin: str | None = None,
    ) -> dict[str, Any]:
        """Check database for duplicate candidate records matching email, phone, or LinkedIn."""
        matched_by = []
        duplicate_candidate = None

        if email:
            stmt = select(Candidate).where(Candidate.email.ilike(email.strip()))
            res = await self.session.execute(stmt)
            cand = res.scalar_one_or_none()
            if cand:
                duplicate_candidate = cand
                matched_by.append("email")

        if phone and not duplicate_candidate:
            stmt = select(Candidate).where(Candidate.phone == phone.strip())
            res = await self.session.execute(stmt)
            cand = res.scalar_one_or_none()
            if cand:
                duplicate_candidate = cand
                matched_by.append("phone")

        if duplicate_candidate:
            logger.info("Found duplicate candidate ID=%s matched by %s", duplicate_candidate.id, matched_by)
            return {
                "is_duplicate": True,
                "duplicate_candidate_id": str(duplicate_candidate.id),
                "matched_by": matched_by,
                "candidate": duplicate_candidate,
            }

        return {
            "is_duplicate": False,
            "duplicate_candidate_id": None,
            "matched_by": [],
            "candidate": None,
        }
