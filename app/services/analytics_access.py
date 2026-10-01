"""Centralized access control and RBAC rules for Analytics, Reports, and AI Insights.

=============================================================================
ANALYTICS & REPORTS ROLE-PERMISSION MATRIX
=============================================================================
Role           | Company-Wide | Reporting Hierarchy | Payroll Cost | Status
---------------|--------------|---------------------|--------------|---------
super_admin    | Full (Any Co)| Full                | Yes          | 200 OK
hr_admin       | Tenant Scope | Full Tenant         | Yes          | 200 OK
executive      | Tenant Scope | Full Tenant         | Yes (Read)   | 200 OK
manager        | No           | Hierarchy Only      | No (403)     | 200 OK (Scoped)
employee       | No           | No                  | No           | 403 Forbidden
recruiter      | No           | No                  | No           | 403 Forbidden
it_admin       | No           | No                  | No           | 403 Forbidden
=============================================================================
"""

from __future__ import annotations

import logging
from typing import Annotated, List, Optional, Set
import uuid

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.services.document_access import resolve_visible_employee_ids

logger = logging.getLogger(__name__)

ANALYTICS_ALLOWED_ROLES: Set[str] = {
    "super_admin",
    "company_admin",
    "admin",
    "hr_admin",
    "hr_manager",
    "executive",
    "manager",
}

PAYROLL_ANALYTICS_ROLES: Set[str] = {
    "super_admin",
    "company_admin",
    "admin",
    "hr_admin",
    "executive",
}

FORBIDDEN_ROLES: Set[str] = {
    "employee",
    "recruiter",
    "it_admin",
}


class AnalyticsContext:
    """Encapsulates authenticated tenant context and employee visibility scoping."""

    def __init__(
        self,
        company_id: uuid.UUID,
        role: str,
        user_id: uuid.UUID,
        allowed_employee_ids: Optional[List[uuid.UUID]] = None,
        is_company_wide: bool = False,
    ) -> None:
        self.company_id = company_id
        self.role = role
        self.user_id = user_id
        self.allowed_employee_ids = allowed_employee_ids
        self.is_company_wide = is_company_wide


async def require_analytics_access(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    company_id_query: Optional[uuid.UUID] = Query(None, alias="company_id"),
) -> AnalyticsContext:
    """Dependency enforcing authentication, role authorization, and tenant isolation for analytics endpoints."""
    raw_role = (claims.get("role") or "").lower()
    if raw_role in FORBIDDEN_ROLES or raw_role not in ANALYTICS_ALLOWED_ROLES:
        logger.warning("Analytics access rejected for role: %s", raw_role)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: Role '{raw_role}' is not authorized to access analytics.",
        )

    # Resolve company_id
    company_id: Optional[uuid.UUID] = None
    if raw_role == "super_admin":
        if company_id_query:
            company_id = company_id_query
        elif claims.get("company_id"):
            try:
                company_id = uuid.UUID(str(claims["company_id"]))
            except (ValueError, TypeError):
                company_id = None
        if not company_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="company_id parameter required for super_admin analytics query.",
            )
    else:
        raw_cid = claims.get("company_id")
        if not raw_cid:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is not associated with a company (missing company_id in token).",
            )
        try:
            company_id = uuid.UUID(str(raw_cid))
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid company_id format in token claims.",
            )

    raw_uid = claims.get("sub") or claims.get("user_id") or claims.get("id")
    user_id = uuid.UUID(str(raw_uid)) if raw_uid else uuid.uuid4()

    # Resolve employee visibility scoping
    # super_admin, hr_admin, executive get None (company-wide)
    # manager gets their hierarchy of direct and indirect reports
    visible_ids = await resolve_visible_employee_ids(claims, session)
    is_company_wide = visible_ids is None

    return AnalyticsContext(
        company_id=company_id,
        role=raw_role,
        user_id=user_id,
        allowed_employee_ids=visible_ids,
        is_company_wide=is_company_wide,
    )


def assert_can_view_payroll_cost(ctx: AnalyticsContext) -> None:
    """Enforce strict authorization for sensitive salary / payroll cost analytics.
    
    Managers are explicitly forbidden (403). Only HR Admin, Executive, and Super Admin are permitted.
    """
    if ctx.role not in PAYROLL_ANALYTICS_ROLES:
        logger.warning("Payroll cost access rejected for role: %s", ctx.role)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Role is not authorized to view salary and payroll cost analytics.",
        )
