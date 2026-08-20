"""Canonical User Role and Lifecycle status enum definitions."""

from __future__ import annotations

import enum


OFFICIAL_SUPER_ADMIN_EMAIL = "superadmin@ofc360.com"


class RoleEnum(str, enum.Enum):
    """Canonical Role Enum for the OFC360 enterprise platform."""
    SUPER_ADMIN = "super_admin"
    HR_ADMIN = "hr_admin"
    MANAGER = "manager"
    EMPLOYEE = "employee"
    EXECUTIVE = "executive"
    IT_ADMIN = "it_admin"
    INTERN = "intern"

    # Executive & Admin roles present in production database
    ADMIN = "admin"
    COMPANY_ADMIN = "company_admin"
    HR_MANAGER = "hr_manager"
    CEO = "ceo"
    CTO = "cto"
    CFO = "cfo"
    COO = "coo"
    CMO = "cmo"
    CLO = "clo"
    CISO = "ciso"
    CIO = "cio"




    @classmethod
    def from_str(cls, value: str | None) -> "RoleEnum":
        """Safely parse and normalize any string representation to canonical RoleEnum."""
        if not value:
            return cls.EMPLOYEE
        normalized = str(value).strip().lower()

        # Alias mappings for legacy, C-Suite, IT Admin, and administrative roles (checked first)
        aliases = {
            "superadmin": cls.SUPER_ADMIN,
            "super_admin": cls.SUPER_ADMIN,
            "super_administrator": cls.SUPER_ADMIN,
            "admin": cls.HR_ADMIN,
            "company_admin": cls.HR_ADMIN,
            "hr": cls.HR_ADMIN,
            "hradmin": cls.HR_ADMIN,
            "hr_admin": cls.HR_ADMIN,
            "hr_manager": cls.HR_ADMIN,
            "payroll_admin": cls.HR_ADMIN,
            "finance": cls.HR_ADMIN,
            "itadmin": cls.IT_ADMIN,
            "it_admin": cls.IT_ADMIN,
            "it": cls.IT_ADMIN,
            "tech_admin": cls.IT_ADMIN,
            "system_admin": cls.IT_ADMIN,
            "it_system_admin": cls.IT_ADMIN,
            "sysadmin": cls.IT_ADMIN,
            "sys_admin": cls.IT_ADMIN,
            "executive": cls.EXECUTIVE,
            "executive_cxo": cls.EXECUTIVE,
            "cxo": cls.EXECUTIVE,
            "ceo": cls.EXECUTIVE,
            "cto": cls.EXECUTIVE,
            "cfo": cls.EXECUTIVE,
            "coo": cls.EXECUTIVE,
            "cmo": cls.EXECUTIVE,
            "clo": cls.EXECUTIVE,
            "ciso": cls.EXECUTIVE,
            "cio": cls.EXECUTIVE,
            "chro": cls.EXECUTIVE,
            "cpo": cls.EXECUTIVE,
            "vp": cls.EXECUTIVE,
            "director": cls.EXECUTIVE,
            "manager": cls.MANAGER,
            "lead": cls.MANAGER,
            "team_lead": cls.MANAGER,
            "intern": cls.INTERN,
            "internship": cls.INTERN,
            "trainee": cls.INTERN,
            "employee": cls.EMPLOYEE,
            "staff": cls.EMPLOYEE,
            "worker": cls.EMPLOYEE,
            "user": cls.EMPLOYEE,
        }
        if normalized in aliases:
            return aliases[normalized]

        # Direct value and name checks
        for role in cls:
            if role.value == normalized or role.name.lower() == normalized:
                return role

        return cls.EMPLOYEE

    def is_admin(self) -> bool:
        """Check if role has administrative privileges."""
        return self in (
            RoleEnum.SUPER_ADMIN,
            RoleEnum.HR_ADMIN,
            RoleEnum.IT_ADMIN,
            RoleEnum.ADMIN,
            RoleEnum.COMPANY_ADMIN,
        )

    def is_super_admin(self) -> bool:
        """Check if role is super_admin."""
        return self == RoleEnum.SUPER_ADMIN

    def is_manager(self) -> bool:
        """Check if role is manager or executive."""
        return self in (
            RoleEnum.MANAGER,
            RoleEnum.SUPER_ADMIN,
            RoleEnum.HR_ADMIN,
            RoleEnum.EXECUTIVE,
            RoleEnum.HR_MANAGER,
            RoleEnum.CEO,
            RoleEnum.CTO,
            RoleEnum.CFO,
            RoleEnum.COO,
            RoleEnum.CMO,
            RoleEnum.CLO,
            RoleEnum.CISO,
            RoleEnum.CIO,
        )

    def is_executive(self) -> bool:
        """Check if role has executive or C-suite privileges."""
        return self in (
            RoleEnum.EXECUTIVE,
            RoleEnum.SUPER_ADMIN,
            RoleEnum.HR_ADMIN,
            RoleEnum.CEO,
            RoleEnum.CTO,
            RoleEnum.CFO,
            RoleEnum.COO,
            RoleEnum.CMO,
            RoleEnum.CLO,
            RoleEnum.CISO,
            RoleEnum.CIO,
        )

    def is_it_admin(self) -> bool:
        """Check if role has IT or system administrative privileges."""
        return self in (
            RoleEnum.IT_ADMIN,
            RoleEnum.SUPER_ADMIN,
        )


# Canonical alias for full backward compatibility
UserRole = RoleEnum


class UserAccountStatus(str, enum.Enum):
    """User account lifecycle status."""
    PENDING_EMAIL_VERIFICATION = "PENDING_EMAIL_VERIFICATION"
    INVITED = "INVITED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DEACTIVATED = "DEACTIVATED"
