from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, new_uuid


class Notification(Base, TimestampMixin):
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("schools.id"), index=True, nullable=False)
    school_id: Mapped[str] = mapped_column(String(36), ForeignKey("schools.id"), index=True, nullable=False)

    recipient_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True, nullable=False)
    type: Mapped[str] = mapped_column(String(16), default="in-app", nullable=False)  # SMS|WhatsApp|Email|in-app
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Document(Base, TimestampMixin):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("schools.id"), index=True, nullable=False)
    school_id: Mapped[str] = mapped_column(String(36), ForeignKey("schools.id"), index=True, nullable=False)

    document_type: Mapped[str] = mapped_column(String(64), nullable=False)
    student_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("students.id"), nullable=True)
    admission_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("admissions.id"), nullable=True)

    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    uploaded_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)


class FaceProfile(Base, TimestampMixin):
    __tablename__ = "face_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("schools.id"), index=True, nullable=False)
    school_id: Mapped[str] = mapped_column(String(36), ForeignKey("schools.id"), index=True, nullable=False)

    student_id: Mapped[str] = mapped_column(String(36), ForeignKey("students.id"), unique=True, index=True, nullable=False)
    embedding: Mapped[str] = mapped_column(Text, nullable=False)  # JSON-encoded float vector
    model_name: Mapped[str] = mapped_column(String(64), nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class RecognitionLog(Base, TimestampMixin):
    __tablename__ = "recognition_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("schools.id"), index=True, nullable=False)
    school_id: Mapped[str] = mapped_column(String(36), ForeignKey("schools.id"), index=True, nullable=False)

    student_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("students.id"), index=True, nullable=True)
    recognition_time: Mapped[DateTime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)  # webcam|cctv
    camera_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("cctv_cameras.id"), nullable=True)
    attendance_marked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class CCTVCamera(Base, TimestampMixin):
    __tablename__ = "cctv_cameras"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("schools.id"), index=True, nullable=False)
    school_id: Mapped[str] = mapped_column(String(36), ForeignKey("schools.id"), index=True, nullable=False)

    camera_name: Mapped[str] = mapped_column(String(128), nullable=False)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stream_url: Mapped[str] = mapped_column(String(1024), nullable=False)  # never returned verbatim to clients
    status: Mapped[str] = mapped_column(String(16), default="offline", nullable=False)  # online|offline|error


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
