"""Interview Recording and Media Storage Models."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING
import uuid

from sqlalchemy import (
    DateTime, ForeignKey, Index, Integer, String, Text, func, text, JSON, Boolean, Enum
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.ai_interview import AIInterviewSession
    from app.models.recruitment import Candidate, Job, InterviewRound


class RecordingStatus(str, Enum):
    """Recording status enumeration."""
    PENDING = "PENDING"
    RECORDING = "RECORDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"
    DELETED = "DELETED"


class MediaType(str, Enum):
    """Media type enumeration."""
    AUDIO = "AUDIO"
    VIDEO = "VIDEO"
    SCREEN = "SCREEN"
    COMBINED = "COMBINED"


class RecordingAction(str, Enum):
    """Recording access action enumeration."""
    VIEW = "VIEW"
    DOWNLOAD = "DOWNLOAD"
    STREAM = "STREAM"
    DELETE = "DELETE"
    SHARE = "SHARE"


class InterviewRecording(Base):
    """Interview recording metadata and storage reference."""

    __tablename__ = "interview_recordings"
    __table_args__ = (
        Index("ix_interview_recordings_session", "session_id"),
        Index("ix_interview_recordings_candidate", "candidate_id"),
        Index("ix_interview_recordings_status", "status"),
        Index("ix_interview_recordings_created", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True)
    session_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("ai_interview_sessions.id", ondelete="CASCADE"), nullable=False)
    candidate_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False)
    round_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("interview_rounds.id", ondelete="SET NULL"), nullable=True)
    job_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)

    # Recording details
    media_type: Mapped[MediaType] = mapped_column(Enum("AUDIO", "VIDEO", "SCREEN", "COMBINED", name="mediatype", native_enum=False), nullable=False, default=MediaType.AUDIO)
    status: Mapped[RecordingStatus] = mapped_column(Enum("PENDING", "RECORDING", "PROCESSING", "COMPLETED", "FAILED", "EXPIRED", "DELETED", name="recordingstatus", native_enum=False), nullable=False, default=RecordingStatus.PENDING)
    format: Mapped[str] = mapped_column(String(20), nullable=False)  # mp4, webm, wav, mp3
    codec: Mapped[str | None] = mapped_column(String(50), nullable=True)  # vp8, vp9, h264, opus, etc.
    
    # Storage
    storage_provider: Mapped[str] = mapped_column(String(50), nullable=False, default="s3")  # s3, minio, local
    storage_bucket: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    storage_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)  # Signed URL for access
    cdn_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)  # CDN URL for streaming
    
    # Media properties
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sample_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    channels: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bitrate_kbps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resolution: Mapped[str | None] = mapped_column(String(50), nullable=True)  # e.g., "1920x1080"
    frame_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    
    # Timestamps
    recording_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    recording_ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processing_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    
    # Consent and compliance
    consent_given: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    consent_given_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consent_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=90)
    gdpr_deletion_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    gdpr_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    
    # Access control
    access_token: Mapped[str | None] = mapped_column(String(500), nullable=True)
    access_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    download_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    
    # Error handling
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    
    # Audit
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    created_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # Relations
    session: Mapped[AIInterviewSession] = relationship("AIInterviewSession", lazy="select")
    candidate: Mapped[Candidate] = relationship("Candidate", lazy="select")
    round: Mapped[InterviewRound | None] = relationship("InterviewRound", lazy="select")
    job: Mapped[Job] = relationship("Job", lazy="select")
    chunks: Mapped[list[RecordingChunk]] = relationship("RecordingChunk", back_populates="recording", cascade="all, delete-orphan", lazy="select")


class RecordingChunk(Base):
    """Individual chunks of a recording for streaming/upload."""

    __tablename__ = "recording_chunks"
    __table_args__ = (
        Index("ix_recording_chunks_recording", "recording_id"),
        Index("ix_recording_chunks_sequence", "sequence_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recording_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("interview_recordings.id", ondelete="CASCADE"), nullable=False)
    
    # Chunk info
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time_seconds: Mapped[float] = mapped_column(Integer, nullable=False)  # Store as milliseconds int
    end_time_seconds: Mapped[float] = mapped_column(Integer, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    
    # Storage
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    storage_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    
    # Media info
    format: Mapped[str] = mapped_column(String(20), nullable=False)
    is_keyframe: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    
    # Status
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")  # PENDING, UPLOADED, PROCESSED, FAILED
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    # Timestamps
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relations
    recording: Mapped[InterviewRecording] = relationship("InterviewRecording", back_populates="chunks")


class RecordingAccessLog(Base):
    """Audit log for recording access."""

    __tablename__ = "recording_access_logs"
    __table_args__ = (
        Index("ix_recording_access_recording", "recording_id"),
        Index("ix_recording_access_user", "accessed_by"),
        Index("ix_recording_access_time", "accessed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recording_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("interview_recordings.id", ondelete="CASCADE"), nullable=False)
    accessed_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    
    # Access details
    action: Mapped[RecordingAction] = mapped_column(Enum("VIEW", "DOWNLOAD", "STREAM", "DELETE", "SHARE", name="recordingaction", native_enum=False), nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    access_method: Mapped[str | None] = mapped_column(String(50), nullable=True)  # DIRECT_URL, SIGNED_URL, CDN, API
    
    # Access result
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    bytes_transferred: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    
    # Timestamps
    accessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relations
    recording: Mapped[InterviewRecording] = relationship("InterviewRecording", lazy="select")