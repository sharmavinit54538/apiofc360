"""Duplicate Detector Service for identifying duplicate applicants based on email, phone, LinkedIn, and name/company."""

from __future__ import annotations

import logging
import re
import uuid
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
        company: str | None = None,
        company_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Check database for duplicate candidate records following strict priority chain:
        1. Email (exact match, case-insensitive)
        2. Phone (normalized digit match)
        3. LinkedIn URL
        4. Name + Current Company similarity
        """
        matched_by: list[str] = []
        duplicate_candidate: Candidate | None = None

        # 1. Email check (highest priority)
        if email and email.strip():
            clean_email = email.strip().lower()
            stmt = select(Candidate).where(Candidate.email.ilike(clean_email))
            res = await self.session.execute(stmt)
            cand = res.scalar_one_or_none()
            if cand:
                duplicate_candidate = cand
                matched_by.append("email")

        # 2. Phone check (normalized digits)
        if not duplicate_candidate and phone:
            clean_phone_digits = re.sub(r"[^\d]", "", phone)
            if len(clean_phone_digits) >= 7:
                # Compare exact phone or matching last 10 digits
                stmt = select(Candidate)
                res = await self.session.execute(stmt)
                all_cands = res.scalars().all()
                for c in all_cands:
                    if c.phone:
                        c_digits = re.sub(r"[^\d]", "", c.phone)
                        if c_digits and (c_digits == clean_phone_digits or c_digits[-10:] == clean_phone_digits[-10:]):
                            duplicate_candidate = c
                            matched_by.append("phone")
                            break

        # 3. LinkedIn URL check
        if not duplicate_candidate and linkedin and "linkedin.com/in/" in linkedin.lower():
            clean_handle_match = re.search(r"linkedin\.com/in/([a-zA-Z0-9_-]+)", linkedin, re.IGNORECASE)
            if clean_handle_match:
                handle = clean_handle_match.group(1).lower()
                from app.models.ai_recruitment import AIResumeDocument
                stmt = select(AIResumeDocument).where(AIResumeDocument.candidate_id.isnot(None))
                res = await self.session.execute(stmt)
                docs = res.scalars().all()
                for d in docs:
                    if d.parsed_data and isinstance(d.parsed_data, dict):
                        doc_linkedin = str(d.parsed_data.get("linkedin") or d.parsed_data.get("linkedin_url") or "")
                        if handle in doc_linkedin.lower():
                            cand = await self.session.get(Candidate, d.candidate_id)
                            if cand:
                                duplicate_candidate = cand
                                matched_by.append("linkedin_url")
                                break

        # 4. Name + Company similarity check
        if not duplicate_candidate and name and company:
            clean_name = name.strip()
            parts = clean_name.split()
            if len(parts) >= 2:
                first_name = parts[0]
                last_name = " ".join(parts[1:])
                stmt = select(Candidate).where(
                    Candidate.first_name.ilike(first_name),
                    Candidate.last_name.ilike(last_name),
                    Candidate.current_company.ilike(f"%{company.strip()}%"),
                )
                res = await self.session.execute(stmt)
                cand = res.scalar_one_or_none()
                if cand:
                    duplicate_candidate = cand
                    matched_by.append("name_and_company")

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

