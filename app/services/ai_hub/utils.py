"""Utility functions for AI Hub Gateway."""

from __future__ import annotations

import logging
from typing import Optional
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.department import Department

logger = logging.getLogger(__name__)


def get_company_id_from_claims(claims: dict) -> Optional[uuid.UUID]:
    """Extract company_id UUID safely from auth claims."""
    if not isinstance(claims, dict):
        return None
    co_id_str = claims.get("company_id")
    if not co_id_str:
        return None
    try:
        return uuid.UUID(str(co_id_str))
    except (ValueError, TypeError):
        return None


async def resolve_department_id(
    session: AsyncSession,
    company_id: Optional[uuid.UUID],
    department: Optional[str],
) -> Optional[uuid.UUID]:
    """Resolve a department string (either UUID string or department name) to a UUID.

    If department is already a valid UUID string, returns that UUID.
    Otherwise queries the departments table filtered by company_id and case-insensitive name.
    """
    if not department or not str(department).strip():
        return None

    dep_clean = str(department).strip()

    # 1. Try parsing as UUID directly
    try:
        return uuid.UUID(dep_clean)
    except (ValueError, TypeError):
        pass

    # 2. Query Department by department_name or department_code
    try:
        stmt = select(Department.id).where(
            func.lower(Department.department_name) == dep_clean.lower()
        )
        if company_id is not None:
            stmt = stmt.where(Department.company_id == company_id)

        res = await session.execute(stmt)
        matched_id = res.scalars().first()
        if matched_id:
            return matched_id

        # Fallback to code
        stmt_code = select(Department.id).where(
            func.lower(Department.department_code) == dep_clean.lower()
        )
        if company_id is not None:
            stmt_code = stmt_code.where(Department.company_id == company_id)

        res_code = await session.execute(stmt_code)
        return res_code.scalars().first()

    except Exception as exc:
        logger.warning("Failed to resolve department '%s': %s", dep_clean, exc)
        return None
