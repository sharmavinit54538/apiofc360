"""Department database model."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING
import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, func, text, Numeric
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.employee import Employee
    from app.models.manager import Manager
    from app.models.company import Company


class Department(Base):
    """Department record representing an organizational unit."""

    __tablename__ = "departments"
    __table_args__ = (
        Index("ix_departments_department_code", "department_code", "company_id", unique=True),
        Index("ix_departments_department_name", "department_name", "company_id", unique=True),
        Index("ix_departments_manager_id", "manager_id"),
        Index("ix_departments_parent_department_id", "parent_department_id"),
        Index("ix_departments_status", "status"),
        Index("ix_departments_is_deleted", "is_deleted"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True,
    )
    department_code: Mapped[str] = mapped_column(String(30), nullable=False)
    department_name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(String(1000), nullable=False)

    # Department Head (links to users.id)
    manager_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Self-referencing FK for parent department
    parent_department_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("departments.id", ondelete="SET NULL"), nullable=True
    )

    branch_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    location: Mapped[str] = mapped_column(String(100), nullable=False)
    cost_center: Mapped[str | None] = mapped_column(String(50), nullable=True)
    budget: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True, default=0.0, server_default=text("0.0"))
    extension_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    employee_capacity: Mapped[int | None] = mapped_column(Integer, nullable=True, default=100, server_default=text("100"))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE", server_default=text("'ACTIVE'"))

    # Audit & Soft Delete
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    manager_user: Mapped[User | None] = relationship("User", foreign_keys=[manager_id], lazy="select")
    company: Mapped[Company | None] = relationship("Company", foreign_keys=[company_id], lazy="select")
    creator: Mapped[User | None] = relationship("User", foreign_keys=[created_by], lazy="select")
    parent_department: Mapped[Department | None] = relationship(
        "Department", remote_side=[id], back_populates="sub_departments", lazy="select"
    )
    sub_departments: Mapped[list[Department]] = relationship(
        "Department", back_populates="parent_department", lazy="select"
    )

    employees: Mapped[list[Employee]] = relationship(
        "Employee", back_populates="department_rel", foreign_keys="Employee.department_id", lazy="select"
    )
    managers_profile: Mapped[list[Manager]] = relationship(
        "Manager", back_populates="department_rel", foreign_keys="Manager.department_id", lazy="select"
    )
