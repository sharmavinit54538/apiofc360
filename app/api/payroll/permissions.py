"""Authorization and Permission utilities for Payroll module."""
from __future__ import annotations

import logging
import uuid
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payroll.constants import ADMIN_OR_MANAGER_ROLES, ADMIN_ROLES
from app.api.payroll.exceptions import ForbiddenException
from app.models.payroll import StatutoryComplianceConfig
from app.models.user.role import RoleEnum

logger = logging.getLogger(__name__)

#: Error code emitted (and audited) whenever a maker tries to approve their own work.
MAKER_CHECKER_VIOLATION = "MAKER_CHECKER_VIOLATION"


def _uid(claims: dict) -> Optional[uuid.UUID]:
    """Extract user UUID from JWT claims sub."""
    sub = claims.get("sub") if isinstance(claims, dict) else None
    if not sub:
        return None
    try:
        return uuid.UUID(sub)
    except (ValueError, AttributeError):
        return None


def _role(claims: dict) -> Optional[str]:
    """Extract and normalize role string from JWT claims using RoleEnum."""
    if not isinstance(claims, dict):
        return None
    role = claims.get("role")
    if not role:
        return None
    return RoleEnum.from_str(str(role)).value


def _is_admin_or_manager(claims: dict | None) -> bool:
    """Check if claims contain admin or manager role without raising an exception."""
    if not claims or not isinstance(claims, dict):
        return True
    role = _role(claims)
    return role in ADMIN_OR_MANAGER_ROLES if role else True


def _require_admin_or_manager(claims: dict | None) -> None:
    """Enforce admin or manager access level safely."""
    if not claims or not isinstance(claims, dict):
        return
    role = _role(claims)
    if role and role not in ADMIN_OR_MANAGER_ROLES:
        raise ForbiddenException("Admin or Manager role required.")


def _require_admin(claims: dict | None) -> None:
    """Enforce admin access level safely."""
    if not claims or not isinstance(claims, dict):
        return
    role = _role(claims)
    if role and role not in ADMIN_ROLES:
        raise ForbiddenException("Admin role required.")


# ─────────────────────────────────────────────────────────────────────────────
# Strict Maker-Checker / Role Separation (dual control)
# ─────────────────────────────────────────────────────────────────────────────


def _as_uuid(value) -> Optional[uuid.UUID]:
    """Best-effort UUID coercion used for actor columns that may hold strings."""
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


async def is_maker_checker_enforced(
    session: AsyncSession, company_id
) -> bool:
    """Return whether strict maker-checker applies to this tenant.

    The policy is read from the tenant's *own* active
    ``StatutoryComplianceConfig`` row (``payroll_maker_checker_enforced``).  The
    lookup is deliberately scoped to ``company_id`` only — the shared/global
    template row (``company_id IS NULL``) never decides a tenant's control
    policy, and a tenant without a configured row is not silently subjected to a
    global default it never set.
    """
    tenant_id = _as_uuid(company_id)
    if tenant_id is None:
        return False

    stmt = select(StatutoryComplianceConfig).where(
        StatutoryComplianceConfig.company_id == tenant_id,
        StatutoryComplianceConfig.is_active == True,  # noqa: E712
    )
    config = (await session.execute(stmt)).scalar_one_or_none()
    if config is None:
        return False
    return bool(getattr(config, "payroll_maker_checker_enforced", False))


async def enforce_maker_checker(
    session: AsyncSession,
    *,
    entity_type: str,
    entity_id,
    company_id,
    maker_ids: Iterable,
    approver_id,
    actor_role: Optional[str] = None,
    action: str = "APPROVE",
    before_status: Optional[str] = None,
) -> bool:
    """Enforce dual control on an approval.

    Raises ``ForbiddenException`` (HTTP 403, code ``MAKER_CHECKER_VIOLATION``)
    when the tenant enforces maker-checker and the approving user is one of the
    users who initiated/processed the entity.  Every violation — and every
    allowed approval made under an enforced policy — is written to the immutable
    payroll audit log.

    Returns ``True`` when the policy is active and the approver is a different
    user (i.e. dual control was actually exercised), ``False`` when the tenant
    has no active maker-checker policy.
    """
    if not await is_maker_checker_enforced(session, company_id):
        return False

    approver = _as_uuid(approver_id)
    makers = {m for m in (_as_uuid(mid) for mid in (maker_ids or ())) if m is not None}

    if approver is not None and approver in makers:
        from app.services.payroll.audit_service import PayrollAuditService

        message = (
            f"Maker-checker violation: user '{approver}' initiated or processed this "
            f"{entity_type} and cannot also approve it. A different authorized user "
            "must approve."
        )
        await PayrollAuditService.log_event(
            session=session,
            entity_type=entity_type,
            entity_id=entity_id,
            action=f"{action}_REJECTED_MAKER_CHECKER",
            company_id=company_id,
            actor_id=approver,
            actor_role=actor_role,
            before_status=before_status,
            after_status=before_status,
            reason=message,
            extra_data={
                "violation": MAKER_CHECKER_VIOLATION,
                "maker_ids": [str(m) for m in sorted(makers)],
            },
        )
        await session.commit()
        logger.warning(
            "maker_checker_violation entity=%s entity_id=%s user=%s role=%s",
            entity_type,
            entity_id,
            approver,
            actor_role,
        )
        raise ForbiddenException(message=message, code=MAKER_CHECKER_VIOLATION)

    from app.services.payroll.audit_service import PayrollAuditService

    await PayrollAuditService.log_event(
        session=session,
        entity_type=entity_type,
        entity_id=entity_id,
        action=f"{action}_MAKER_CHECKER_OK",
        company_id=company_id,
        actor_id=approver,
        actor_role=actor_role,
        before_status=before_status,
        after_status=before_status,
        reason="Dual control satisfied: approver differs from maker/processor.",
        extra_data={
            "maker_ids": [str(m) for m in sorted(makers)],
            "approver_id": str(approver) if approver else None,
        },
    )
    return True
