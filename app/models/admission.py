from sqlalchemy import Boolean, Date, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, new_uuid


class Admission(Base, TimestampMixin):
    __tablename__ = "admissions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("schools.id"), index=True, nullable=False)
    school_id: Mapped[str] = mapped_column(String(36), ForeignKey("schools.id"), index=True, nullable=False)

    form_number: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    student_name: Mapped[str] = mapped_column(String(255), nullable=False)
    dob: Mapped[Date | None] = mapped_column(Date, nullable=True)
    gender: Mapped[str | None] = mapped_column(String(16), nullable=True)
    class_applying_for: Mapped[str] = mapped_column(String(32), nullable=False)
    parent_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    parent_occupation: Mapped[str | None] = mapped_column(String(128), nullable=True)
    contact: Mapped[str | None] = mapped_column(String(32), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address: Mapped[str | None] = mapped_column(String(512), nullable=True)
    previous_school: Mapped[str | None] = mapped_column(String(255), nullable=True)
    blood_group: Mapped[str | None] = mapped_column(String(8), nullable=True)
    aadhaar: Mapped[str | None] = mapped_column(String(32), nullable=True)
    emergency_contact: Mapped[str | None] = mapped_column(String(32), nullable=True)
    religion: Mapped[str | None] = mapped_column(String(64), nullable=True)
    nationality: Mapped[str | None] = mapped_column(String(64), nullable=True)
    category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    transport_required: Mapped[bool] = mapped_column(Boolean, default=False)
    hostel_required: Mapped[bool] = mapped_column(Boolean, default=False)
    photo: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    # pending -> verified -> approved | rejected

    created_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    verified_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
