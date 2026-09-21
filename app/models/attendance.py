from sqlalchemy import Date, DateTime, Float, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, new_uuid


class Attendance(Base, TimestampMixin):
    __tablename__ = "attendance"
    __table_args__ = (
        UniqueConstraint("student_id", "date", name="uq_attendance_student_date"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("schools.id"), index=True, nullable=False)
    school_id: Mapped[str] = mapped_column(String(36), ForeignKey("schools.id"), index=True, nullable=False)

    student_id: Mapped[str] = mapped_column(String(36), ForeignKey("students.id"), index=True, nullable=False)
    date: Mapped[Date] = mapped_column(Date, index=True, nullable=False)
    class_name: Mapped[str] = mapped_column(String(32), nullable=False)
    section: Mapped[str | None] = mapped_column(String(16), nullable=True)

    status: Mapped[str] = mapped_column(String(16), nullable=False)  # present|absent|late|excused
    source: Mapped[str] = mapped_column(String(16), default="manual", nullable=False)  # manual|webcam|face|cctv

    check_in_time: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    check_out_time: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    remarks: Mapped[str | None] = mapped_column(String(512), nullable=True)
    marked_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
