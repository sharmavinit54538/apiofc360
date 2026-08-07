"""Onboarding Service — production-ready gate-keeping for the onboarding flow.

Provides:
- get_or_create_progress  : upsert a single OnboardingProgress row per company,
                            backfilling flags from company.onboarding_step for
                            returning users who have no progress row yet.
- check_step_access       : enforce sequential order and detect already-completed
                            steps WITHOUT raising exceptions — returns an action
                            enum so callers can respond gracefully.
- advance_step            : atomically mark a step complete and bump current_step.
- get_completion_summary  : dict of all step flags for /status and /progress.
"""

from __future__ import annotations

import logging
import uuid
from enum import Enum
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.onboarding import OnboardingProgress

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Step ordering metadata
# ─────────────────────────────────────────────────────────────────────────────

# Maps each step number → (completion_flag_attr, prerequisite_flag_attr | None, step_label)
STEP_META: dict[int, tuple[str, str | None, str]] = {
    1: ("company_completed",      None,                    "Company Details"),
    2: ("admin_completed",        "company_completed",     "Admin Profile"),
    3: ("hr_completed",           "admin_completed",       "HR Settings"),
    4: ("departments_completed",  "hr_completed",          "Departments"),
    5: ("designations_completed", "departments_completed", "Designations"),
    6: ("employees_invited",      "designations_completed","Invite Employees"),
    7: ("onboarding_completed",   "employees_invited",     "Complete"),
}

# What current_step advances TO after completing each step
NEXT_STEP: dict[int, int] = {1: 2, 2: 3, 3: 4, 4: 5, 5: 6, 6: 7, 7: 7}

# Backfill table: maps company.onboarding_step integer → which flags to enable.
# Used when creating a fresh OnboardingProgress row for a returning user.
# onboarding_step 2 means company done, onboarding_step 3 means company+admin done, etc.
_STEP_TO_FLAGS: dict[int, list[str]] = {
    1: [],
    2: ["company_completed"],
    3: ["company_completed", "admin_completed"],
    4: ["company_completed", "admin_completed", "hr_completed"],
    5: ["company_completed", "admin_completed", "hr_completed", "departments_completed", "designations_completed"],
    6: ["company_completed", "admin_completed", "hr_completed", "departments_completed", "designations_completed", "employees_invited"],
    7: ["company_completed", "admin_completed", "hr_completed", "departments_completed", "designations_completed", "employees_invited", "onboarding_completed"],
}


# ─────────────────────────────────────────────────────────────────────────────
# Step access result (replaces raising exceptions for resume scenarios)
# ─────────────────────────────────────────────────────────────────────────────

class StepAccess(str, Enum):
    """Result of check_step_access()."""
    ALLOWED    = "allowed"     # Step can proceed normally
    REDIRECT   = "redirect"    # Step already done; caller should redirect to current_step
    BLOCKED    = "blocked"     # Prerequisite not met; caller should redirect to current_step


# ─────────────────────────────────────────────────────────────────────────────
# Service
# ─────────────────────────────────────────────────────────────────────────────

class OnboardingService:
    """Encapsulates all onboarding gate-keeping logic."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Progress row management — with backfill for returning users
    # ------------------------------------------------------------------

    async def get_or_create_progress(self, company_id: uuid.UUID) -> OnboardingProgress:
        """Return the OnboardingProgress row for a company, creating it if absent.

        KEY FIX: When creating a new row for a RETURNING USER (no progress row exists
        but the company already has onboarding_step > 1), we backfill the step flags
        from company.onboarding_step so the user resumes from where they left off
        instead of being reset to Step 1.

        Uses raw SQL to bypass the multi-tenant ORM filter.
        """
        from sqlalchemy import text

        # Check existence via raw SQL (bypasses tenant filter)
        exists_result = await self.db.execute(
            text("SELECT id FROM onboarding_progress WHERE company_id = :cid LIMIT 1"),
            {"cid": str(company_id)},
        )
        row = exists_result.fetchone()

        if row:
            # Row exists — load via ORM for tracked attribute access
            orm_result = await self.db.execute(
                select(OnboardingProgress).where(OnboardingProgress.company_id == company_id)
            )
            progress = orm_result.scalar_one()
            logger.debug("OnboardingProgress loaded: company_id=%s | current_step=%d", company_id, progress.current_step)
            return progress

        # No row yet — this is either a brand-new company or a returning user
        # whose progress row was never created. Backfill from company.onboarding_step.
        company_row = await self.db.execute(
            text("SELECT onboarding_step, onboarding_completed FROM companies WHERE id = :cid LIMIT 1"),
            {"cid": str(company_id)},
        )
        company_data = company_row.fetchone()
        existing_step = company_data[0] if company_data else 1
        existing_completed = company_data[1] if company_data else False

        # Determine which flags to enable based on existing progress
        flags_to_set = set(_STEP_TO_FLAGS.get(existing_step, []))
        if existing_completed:
            flags_to_set = set(_STEP_TO_FLAGS.get(7, []))

        progress = OnboardingProgress(
            id=uuid.uuid4(),
            company_id=company_id,
            current_step=max(existing_step, 1),
            company_completed=      "company_completed"      in flags_to_set,
            admin_completed=        "admin_completed"        in flags_to_set,
            hr_completed=           "hr_completed"           in flags_to_set,
            departments_completed=  "departments_completed"  in flags_to_set,
            designations_completed= "designations_completed" in flags_to_set,
            employees_invited=      "employees_invited"      in flags_to_set,
            onboarding_completed=   existing_completed or ("onboarding_completed" in flags_to_set),
        )
        self.db.add(progress)
        await self.db.flush()
        logger.info(
            "OnboardingProgress created (backfilled): company_id=%s | company_step=%d | current_step=%d | flags=%s",
            company_id, existing_step, progress.current_step, flags_to_set,
        )
        return progress

    # ------------------------------------------------------------------
    # Gate-keeping — returns StepAccess, never raises for resume scenarios
    # ------------------------------------------------------------------

    def check_step_access(self, progress: OnboardingProgress, step: int) -> StepAccess:
        """Check whether the given step is allowed to execute.

        Returns StepAccess enum — callers decide how to respond.
        This replaces the old assert_step_allowed which raised 409/400
        and caused the resume flow to crash.

        ALLOWED  → proceed with business logic as normal
        REDIRECT → step already completed; return 200 with redirect_step
        BLOCKED  → prerequisite not met; return 400 with redirect_step
        """
        completion_flag, prerequisite_flag, _ = STEP_META[step]

        if getattr(progress, completion_flag):
            # Already done — don't error; return REDIRECT so frontend resumes
            return StepAccess.REDIRECT

        if prerequisite_flag and not getattr(progress, prerequisite_flag):
            # Prerequisite incomplete — out of sequence
            return StepAccess.BLOCKED

        return StepAccess.ALLOWED

    # ------------------------------------------------------------------
    # Step advancement
    # ------------------------------------------------------------------

    def advance_step(self, progress: OnboardingProgress, step: int) -> None:
        """Mark a step as complete and advance current_step if appropriate.

        Safe to call even if current_step is already beyond this step
        (e.g. admin edited a previous step — we never regress).
        """
        completion_flag, _, _ = STEP_META[step]
        setattr(progress, completion_flag, True)
        next_step = NEXT_STEP[step]
        if progress.current_step < next_step:
            progress.current_step = next_step
        logger.info(
            "OnboardingProgress advanced: company_id=%s | step=%d completed | current_step=%d",
            progress.company_id, step, progress.current_step,
        )

    # ------------------------------------------------------------------
    # Summary helpers (for GET /status and GET /progress)
    # ------------------------------------------------------------------

    def get_completion_summary(self, progress: OnboardingProgress) -> dict[str, Any]:
        """Return a dict of all step flags for the progress response."""
        return {
            "company_completed":      progress.company_completed,
            "admin_completed":        progress.admin_completed,
            "hr_completed":           progress.hr_completed,
            "departments_completed":  progress.departments_completed,
            "designations_completed": progress.designations_completed,
            "employees_invited":      progress.employees_invited,
            "onboarding_completed":   progress.onboarding_completed,
        }

    def get_first_incomplete_step(self, progress: OnboardingProgress) -> int:
        """Return the first step number that has not been completed yet.

        Used by GET /status to give the frontend the exact page to open.
        """
        for step_num, (flag, _, _) in STEP_META.items():
            if not getattr(progress, flag):
                return step_num
        return 7  # All done → dashboard
