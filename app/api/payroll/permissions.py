"""Authorization and Permission utilities for Payroll module."""
from __future__ import annotations

import logging
import uuid
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.payroll.constants import ADMIN_OR_MANAGER_ROLES, ADMIN_ROLES
from app.api.payroll.exceptions import ForbiddenException, UnauthorizedException
from app.models.payroll import StatutoryComplianceConfig
from app.models.user.role import RoleEnum

logger = logging.getLogger(__name__)

#: Error code emitted (and audited) whenever a maker tries to approve their own work.
MAKER_CHECKER_VIOLATION = "MAKER_CHECKER_VIOLATION"

# Granular attendance-close permissions.  They are also seeded by the Step 3
# migration; the role fallback preserves compatibility with existing JWTs that
# pre-date granular permission claims.
PAYROLL_LOCK_ATTENDANCE = "payroll:lock_attendance"
PAYROLL_UNLOCK_ATTENDANCE = "payroll:unlock_attendance"


def _require_authenticated(claims: dict | None) -> dict:
    """Fail-closed authentication check requiring verified claims dictionary."""
    if not claims or not isinstance(claims, dict):
        raise UnauthorizedException("Authentication required.")
    return claims


def _reject_super_admin(claims: dict | None) -> dict:
    """Fail-closed check blocking Platform Super Admin from tenant payroll/salary data."""
    verified = _require_authenticated(claims)
    if _role(verified) == RoleEnum.SUPER_ADMIN.value:
        raise ForbiddenException(
            "Super Admin is restricted to platform-level management and cannot access tenant payroll or salary data."
        )
    return verified


def _require_tenant_id(
    claims: dict | None,
    *,
    allow_super_admin_global: bool = False,
) -> Optional[uuid.UUID]:
    """Extract and validate verified company_id tenant scope from JWT claims.

    Fails closed unless the verified caller is a tenant user with a valid UUID company_id claim.
    Super Admin is strictly excluded from operational tenant payroll/salary access.
    """
    verified = _reject_super_admin(claims)
    raw = verified.get("company_id")
    if not raw:
        raise ForbiddenException("Company tenant scope is required.")
    try:
        return uuid.UUID(str(raw))
    except (ValueError, AttributeError, TypeError) as exc:
        raise ForbiddenException("Invalid company tenant scope.") from exc


def _require_payroll_permission(claims: dict | None, permission: str) -> None:
    """Require a granular permission, with an admin/manager role fallback (fail-closed)."""
    verified = _reject_super_admin(claims)
    raw_permissions = verified.get("permissions")
    if raw_permissions is None:
        raw_permissions = verified.get("permission_codes")
    if raw_permissions is not None:
        if isinstance(raw_permissions, str):
            permissions = {raw_permissions}
        else:
            try:
                permissions = {str(p) for p in raw_permissions}
            except TypeError:
                permissions = set()
        if permission not in permissions and "*" not in permissions and "payroll:*" not in permissions:
            raise ForbiddenException(f"Permission '{permission}' required.")
        return
    _require_admin_or_manager(verified)


def _uid(claims: dict | None) -> Optional[uuid.UUID]:
    """Extract user UUID from JWT claims sub."""
    sub = claims.get("sub") if isinstance(claims, dict) else None
    if not sub:
        return None
    try:
        return uuid.UUID(str(sub))
    except (ValueError, AttributeError, TypeError):
        return None


def _role(claims: dict | None) -> Optional[str]:
    """Extract and strictly normalize role string from JWT claims using RoleEnum."""
    if not isinstance(claims, dict):
        return None
    role = claims.get("role")
    if not role:
        return None
    parsed = RoleEnum.from_str(str(role), strict=True)
    return parsed.value if parsed is not None else None


def _is_admin_or_manager(claims: dict | None) -> bool:
    """Check if claims contain tenant admin or manager role without failing open."""
    if not claims or not isinstance(claims, dict):
        return False
    role = _role(claims)
    if role == RoleEnum.SUPER_ADMIN.value:
        return False
    return bool(role and role in ADMIN_OR_MANAGER_ROLES)


def _require_admin_or_manager(claims: dict | None) -> None:
    """Enforce tenant admin or manager access level (fail-closed, excludes Super Admin)."""
    verified = _reject_super_admin(claims)
    role = _role(verified)
    if not role or role not in ADMIN_OR_MANAGER_ROLES:
        raise ForbiddenException("Admin or Manager role required.")


def _require_admin(claims: dict | None) -> None:
    """Enforce tenant admin access level (fail-closed, excludes Super Admin)."""
    verified = _reject_super_admin(claims)
    role = _role(verified)
    if not role or role not in ADMIN_ROLES:
        raise ForbiddenException("Admin role required.")


def _has_explicit_permission(claims: dict | None, *needed: str) -> bool:
    """Return True only when explicit permission claims include one of *needed*."""
    if not claims or not isinstance(claims, dict):
        return False
    raw_permissions = claims.get("permissions")
    if raw_permissions is None:
        raw_permissions = claims.get("permission_codes")
    if raw_permissions is None:
        return False
    if isinstance(raw_permissions, str):
        perms = {raw_permissions}
    else:
        try:
            perms = {str(p) for p in raw_permissions}
        except TypeError:
            return False
    return bool(perms & set(needed) or "*" in perms or "payroll:*" in perms)


async def _is_payslip_admin_authorized(
    session: AsyncSession,
    claims: dict | None,
    company_id: Optional[uuid.UUID],
) -> bool:
    """Return True if caller may inspect or manage other employees' payslips within the tenant.

    Platform Super Admin is strictly blocked. Tenant Managers are denied unless
    explicitly authorized by BOTH company policy (`hr_settings.allow_manager_payslip_access`
    or `payslip_settings.allow_manager_payslip_access`) AND backend permission claims
    (`payroll:view_payslips` / `payroll:manage_payslips`); reporting hierarchy alone never
    grants salary access.
    """
    verified = _reject_super_admin(claims)
    role = _role(verified)
    if role in ADMIN_ROLES or role == RoleEnum.EXECUTIVE.value:
        return True
    if role == RoleEnum.MANAGER.value:
        if not _has_explicit_permission(verified, "payroll:view_payslips", "payroll:manage_payslips"):
            return False
        if company_id is None:
            return False
        from app.models.company import Company

        comp = await session.get(Company, company_id)
        if comp is None:
            return False
        hr_cfg = comp.hr_settings if isinstance(comp.hr_settings, dict) else {}
        ps_cfg = comp.payslip_settings if isinstance(comp.payslip_settings, dict) else {}
        return bool(hr_cfg.get("allow_manager_payslip_access") or ps_cfg.get("allow_manager_payslip_access"))
    return False


async def _require_payslip_manager_or_admin(
    session: AsyncSession,
    claims: dict | None,
    company_id: Optional[uuid.UUID],
) -> None:
    """Fail-closed check for tenant payslip admin/authorized-manager operations."""
    if not await _is_payslip_admin_authorized(session, claims, company_id):
        role = _role(claims)
        if role == RoleEnum.MANAGER.value:
            raise ForbiddenException(
                "Managers cannot access other employees' payslips without explicit company policy approval and backend permissions."
            )
        raise ForbiddenException("Authorized HR/Payroll Admin access required.")


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
