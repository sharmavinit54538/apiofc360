from sqlalchemy import Date, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, new_uuid


class Teacher(Base, TimestampMixin):
    __tablename__ = "teachers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("schools.id"), index=True, nullable=False)
    school_id: Mapped[str] = mapped_column(String(36), ForeignKey("schools.id"), index=True, nullable=False)

    employee_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    subject: Mapped[str | None] = mapped_column(String(128), nullable=True)
    qualification: Mapped[str | None] = mapped_column(String(255), nullable=True)
    joining_date: Mapped[Date | None] = mapped_column(Date, nullable=True)
    class_assignments: Mapped[str | None] = mapped_column(String(512), nullable=True)  # JSON list, e.g. ["10-A"]
    photo: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)

    user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
