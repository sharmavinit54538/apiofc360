"""SQLAlchemy models for Enterprise Payroll Security Management System."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional, List

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Index, Integer,
    Numeric, String, UniqueConstraint, JSON, Text, func, text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class SecurityRole(Base):
    """Configurable RBAC Role Entity."""
    __tablename__ = "security_roles"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True)

    role_name: Mapped[str] = mapped_column(String(100), nullable=False)
    role_code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_system_role: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class SecurityPermission(Base):
    """Granular Action Permission Definition."""
    __tablename__ = "security_permissions"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    module_name: Mapped[str] = mapped_column(String(50), nullable=False) # PAYROLL | EMPLOYEES | COMPLIANCE | SETTINGS
    action_name: Mapped[str] = mapped_column(String(50), nullable=False) # VIEW | CREATE | UPDATE | DELETE | APPROVE | EXPORT
    permission_code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)


class RolePermission(Base):
    """Mapping between SecurityRole and SecurityPermission."""
    __tablename__ = "role_permissions"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    role_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("security_roles.id", ondelete="CASCADE"), nullable=False)
    permission_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("security_permissions.id", ondelete="CASCADE"), nullable=False)


class SecurityPolicy(Base):
    """Global Enterprise Security Policy settings."""
    __tablename__ = "security_policies"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True)

    session_timeout_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    idle_timeout_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    max_concurrent_sessions: Mapped[int] = mapped_column(Integer, nullable=False, default=3)

    min_password_length: Mapped[int] = mapped_column(Integer, nullable=False, default=12)
    require_uppercase: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    require_lowercase: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    require_numbers: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    require_special_chars: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    mfa_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    aes_256_encryption_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    mask_salary_non_payroll: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class UserSession(Base):
    """Active User Web Sessions Monitor."""
    __tablename__ = "user_sessions"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_email: Mapped[str] = mapped_column(String(100), nullable=False)
    device_info: Mapped[str] = mapped_column(String(255), nullable=False)
    browser: Mapped[str] = mapped_column(String(100), nullable=False)
    ip_address: Mapped[str] = mapped_column(String(50), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    login_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_activity: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class IPWhitelist(Base):
    """Corporate Network IP Whitelist."""
    __tablename__ = "ip_whitelist"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True)

    ip_address_or_range: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SecurityAuditLog(Base):
    """Immutable Security Event Audit Trail."""
    __tablename__ = "security_audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    actor: Mapped[str] = mapped_column(String(100), nullable=False)
    details: Mapped[str] = mapped_column(Text, nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(50), nullable=True)
    browser: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SecurityAlert(Base):
    """Real-time Security Alerts."""
    __tablename__ = "security_alerts"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    alert_type: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="HIGH") # LOW | MEDIUM | HIGH | CRITICAL
    message: Mapped[str] = mapped_column(Text, nullable=False)
    is_resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
