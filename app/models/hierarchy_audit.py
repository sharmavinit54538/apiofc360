"""Hierarchy audit log database model."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
import uuid

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.employee import Employee
    from app.models.user import User


class HierarchyAuditLog(Base):
    """Hierarchy audit log for tracking reporting manager changes and transfers."""

    __tablename__ = "hierarchy_audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
    )
    previous_manager_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="SET NULL"),
        nullable=True,
    )
    new_manager_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="SET NULL"),
        nullable=True,
    )
    updated_by: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # Relationships
    employee: Mapped[Employee] = relationship("Employee", foreign_keys=[employee_id], lazy="select")
    previous_manager: Mapped[Employee | None] = relationship("Employee", foreign_keys=[previous_manager_id], lazy="select")
    new_manager: Mapped[Employee | None] = relationship("Employee", foreign_keys=[new_manager_id], lazy="select")
    updater: Mapped[User] = relationship("User", foreign_keys=[updated_by], lazy="select")
