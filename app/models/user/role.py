"""User role enum definition."""

from __future__ import annotations

import enum


class UserRole(str, enum.Enum):
    SUPER_ADMIN = "super_admin"
    HR_ADMIN = "hr_admin"
    MANAGER = "manager"
    EMPLOYEE = "employee"
    EXECUTIVE = "executive"
    IT_ADMIN = "it_admin"
    INTERN = "intern"

    @classmethod
    def from_str(cls, value: str | None) -> "UserRole":
        """Safely parse string to UserRole enum."""
        if not value:
            return cls.EMPLOYEE
        normalized = str(value).strip().lower()
        for role in cls:
            if role.value == normalized or role.name.lower() == normalized:
                return role
        return cls.EMPLOYEE


class UserAccountStatus(str, enum.Enum):
    """User account lifecycle status."""
    PENDING_EMAIL_VERIFICATION = "PENDING_EMAIL_VERIFICATION"
    INVITED = "INVITED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DEACTIVATED = "DEACTIVATED"
