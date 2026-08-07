"""User role enum definition."""

from __future__ import annotations

import enum


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    MANAGER = "manager"
    EMPLOYEE = "employee"
    CEO = "ceo"
    CFO = "cfo"
    CTO = "cto"
    COO = "coo"
    CMO = "cmo"
    CLO = "clo"
    CISO = "ciso"
    CIO = "cio"
