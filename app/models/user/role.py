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
    

