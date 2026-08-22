"""
RBAC permission catalog. Mirrors src/lib/permissions.ts EXACTLY so tokens
issued here are understood by the existing frontend PermissionGuard/RoleGuard.

Frontend is UI-gating only — every one of these is re-checked server-side.
"""

ROLES = ["admin", "teacher", "student", "parent", "accountant"]

ROLE_PERMISSIONS: dict[str, list[str]] = {
    "admin": ["*"],
    "teacher": [
        "classes:read",
        "students:read",
        "attendance:read",
        "attendance:write",
        "marks:read",
        "marks:write",
        "homework:read",
        "homework:write",
        "reports:read",
        "documents:read",
        "notifications:read",
    ],
    "student": [
        "self:attendance:read",
        "self:marks:read",
        "self:documents:read",
        "self:profile:read",
        "self:profile:write",
        "notifications:read",
    ],
    "parent": [
        "children:read",
        "children:attendance:read",
        "fees:read",
        "notifications:read",
        "documents:read",
        "self:profile:read",
    ],
    "accountant": [
        "fees:read",
        "fees:write",
        "finance:read",
        "finance:write",
        "reports:read",
        "notifications:read",
        "documents:read",
    ],
}


def permissions_for_role(role: str) -> list[str]:
    return ROLE_PERMISSIONS.get(role, [])


def permission_granted(permissions: list[str] | None, required: str) -> bool:
    """Supports exact match, '*' (all), and prefix wildcards like 'fees:*'."""
    if not permissions:
        return False
    if "*" in permissions:
        return True
    if required in permissions:
        return True
    return any(p.endswith(":*") and required.startswith(p[:-1]) for p in permissions)


ROLE_HOME = {
    "admin": "/dashboard",
    "teacher": "/attendance",
    "student": "/my-attendance",
    "parent": "/parent",
    "accountant": "/fees",
}
