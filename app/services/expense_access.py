"""Authenticated, tenant-bound access rules shared by expense entry points.

The generic payroll administrator guard also grants IT/executive access and is
intentionally unsuitable for expense approval. Financial capabilities here come
from explicit grants. The sole role fallback is a manager reviewing direct reports
when no permission collection has been configured.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import uuid

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.core.permissions import permission_granted
from app.middleware.auth import get_current_user
from app.models.company import Company
from app.models.employee import Employee
from app.models.security_setting import RolePermission, SecurityPermission, SecurityRole
from app.models.user.role import OFFICIAL_SUPER_ADMIN_EMAIL, RoleEnum


EXPENSE_READ = "expenses:read"
EXPENSE_MANAGE = "expenses:manage"
EXPENSE_APPROVE = "expenses:approve"
EXPENSE_PAY = "expenses:pay"
_EXPENSE_PERMISSIONS = (EXPENSE_READ, EXPENSE_MANAGE, EXPENSE_APPROVE, EXPENSE_PAY)
_INACTIVE_STATUSES = {
    "DISABLED", "INACTIVE", "DEACTIVATED", "ARCHIVED", "TERMINATED", "EXITED", "DELETED",
}


@dataclass(frozen=True)
class ExpenseActor:
    """Verified identity; all capabilities remain confined to ``company_id``."""

    user_id: uuid.UUID
    company_id: uuid.UUID
    role: str
    employee_id: uuid.UUID | None = None
    permissions: frozenset[str] = field(default_factory=frozenset)
    team_employee_ids: frozenset[uuid.UUID] = field(default_factory=frozenset)
    permissions_explicit: bool = False

    def has_permission(self, permission: str) -> bool:
        """Use the existing exact/prefix-wildcard permission convention."""
        return permission_granted(list(self.permissions), permission)

    @property
    def can_read_all(self) -> bool:
        return self.role != "manager" and (
            self.role == "super_admin"
            or any(self.has_permission(code) for code in _EXPENSE_PERMISSIONS)
        )

    @property
    def can_manage(self) -> bool:
        return self.role != "manager" and (
            self.role == "super_admin" or self.has_permission(EXPENSE_MANAGE)
        )

    @property
    def can_review(self) -> bool:
        return (
            self.role == "super_admin"
            or self.has_permission(EXPENSE_APPROVE)
            or (self.role == "manager" and not self.permissions_explicit)
        )

    @property
    def can_pay(self) -> bool:
        # Even the official platform administrator needs an explicit grant.
        return self.has_permission(EXPENSE_PAY)

    @property
    def can_read_team(self) -> bool:
        return self.role == "manager" and (
            not self.permissions_explicit
            or any(self.has_permission(code) for code in _EXPENSE_PERMISSIONS)
        )

    def can_read_employee(self, employee_id: uuid.UUID) -> bool:
        return (
            employee_id == self.employee_id
            or self.can_read_all
            or (self.can_read_team and employee_id in self.team_employee_ids)
        )

    def can_review_employee(self, employee_id: uuid.UUID) -> bool:
        if employee_id == self.employee_id or not self.can_review:
            return False
        return self.role != "manager" or employee_id in self.team_employee_ids


def _uuid_claim(claims: dict, name: str, status_code: int) -> uuid.UUID:
    try:
        return uuid.UUID(str(claims[name]))
    except (KeyError, ValueError, TypeError, AttributeError) as exc:
        detail = "Invalid authenticated identity." if name == "sub" else "Valid tenant context is required."
        raise HTTPException(status_code=status_code, detail=detail) from exc


def _permission_collection(value: object) -> frozenset[str]:
    if isinstance(value, str):
        return frozenset({value})
    if isinstance(value, (list, tuple, set, frozenset)) and all(isinstance(item, str) for item in value):
        return frozenset(value)
    raise HTTPException(status_code=403, detail="Invalid expense permission collection.")


async def _resolve_permissions(
    db: AsyncSession, claims: dict, company_id: uuid.UUID, raw_role: str,
) -> tuple[frozenset[str], bool]:
    # Explicit token collections, including an empty list, are authoritative.
    for key in ("permissions", "permission_codes"):
        if key in claims and claims[key] is not None:
            return _permission_collection(claims[key]), True

    # Normal login tokens currently contain no permission collection. Resolve
    # configured grants from the existing RBAC tables without changing issuance.
    # Global template roles must not grant rights in an unrelated tenant.
    roles = (await db.execute(
        select(SecurityRole).where(
            SecurityRole.company_id == company_id,
            func.lower(SecurityRole.role_code) == raw_role,
        )
    )).scalars().all()
    if not roles:
        return frozenset(), False
    active_ids = [role.id for role in roles if role.is_active]
    if not active_ids:
        return frozenset(), True
    permissions = (await db.execute(
        select(SecurityPermission.permission_code)
        .join(RolePermission, RolePermission.permission_id == SecurityPermission.id)
        .where(RolePermission.role_id.in_(active_ids))
    )).scalars().all()
    return frozenset(permissions), True


async def resolve_expense_actor(db: AsyncSession, claims: dict) -> ExpenseActor:
    """Resolve a caller after the router's ``get_current_user_claims`` dependency.

    JWT verification/revocation remains owned by the existing authentication
    dependency. This resolver also checks the current database account, its
    tenant and role, and active employment before deriving ownership or access.
    No request body, query parameter, or header can select a tenant here.
    """
    if not isinstance(claims, dict):
        raise HTTPException(status_code=401, detail="Authentication is required.")
    user_id = _uuid_claim(claims, "sub", 401)
    company_id = _uuid_claim(claims, "company_id", 403)
    user = await get_current_user(claims=claims, session=db)
    # The shared active-profile check is cached. Recheck the returned account so
    # a disabled account cannot retain financial access for the cache duration.
    if not user.is_active or user.is_deleted or (user.account_status or "").upper() in (
        _INACTIVE_STATUSES | {"SUSPENDED"}
    ):
        raise HTTPException(status_code=403, detail="User account is inactive or disabled.")
    raw_role = str(getattr(user.role, "value", user.role)).lower().strip()
    role = RoleEnum.from_str(raw_role).value
    token_role = claims.get("role")
    if not isinstance(token_role, str) or RoleEnum.from_str(token_role).value != role:
        raise HTTPException(status_code=403, detail="Account role has changed. Please sign in again.")
    if role == "super_admin":
        if (user.email or "").lower().strip() != OFFICIAL_SUPER_ADMIN_EMAIL or (
            claims.get("email")
            and str(claims["email"]).lower().strip() != OFFICIAL_SUPER_ADMIN_EMAIL
        ):
            raise HTTPException(status_code=403, detail="Super Admin access required.")
        # A platform identity may have no company; a verified signed tenant
        # claim is still mandatory, never unrestricted multi-tenant access.
        company = (await db.execute(select(Company.id).where(Company.id == company_id))).scalar_one_or_none()
        if company is None:
            raise HTTPException(status_code=403, detail="Tenant context does not exist.")
    elif user.company_id != company_id:
        raise HTTPException(status_code=403, detail="Account does not belong to the authenticated tenant.")

    employees = (await db.execute(
        select(Employee)
        .options(
            load_only(
                Employee.id,
                Employee.company_id,
                Employee.user_id,
                Employee.is_active,
                Employee.status,
                Employee.employment_status,
                Employee.is_deleted,
            )
        )
        .where(
            Employee.user_id == user_id,
            Employee.company_id == company_id,
            Employee.is_deleted.is_(False),
        )
    )).scalars().all()
    if len(employees) > 1:
        raise HTTPException(status_code=409, detail="Multiple employee profiles require administrator review.")
    employee = employees[0] if employees else None
    if employee is not None and (
        not employee.is_active
        or (employee.status or "").upper() in _INACTIVE_STATUSES
        or (employee.employment_status or "").upper() in _INACTIVE_STATUSES
    ):
        raise HTTPException(status_code=403, detail="Employee profile is inactive.")

    permissions, explicit = await _resolve_permissions(db, claims, company_id, raw_role)
    team_ids: frozenset[uuid.UUID] = frozenset()
    if role == "manager" and employee is not None:
        team_ids = frozenset((await db.execute(
            select(Employee.id).where(
                Employee.company_id == company_id,
                Employee.is_deleted.is_(False),
                Employee.id != employee.id,
                or_(
                    Employee.manager_id == employee.id,
                    Employee.reporting_manager_id == employee.id,
                ),
            )
        )).scalars().all())
    return ExpenseActor(
        user_id=user_id,
        company_id=company_id,
        role=role,
        employee_id=employee.id if employee is not None else None,
        permissions=permissions,
        team_employee_ids=team_ids,
        permissions_explicit=explicit,
    )
