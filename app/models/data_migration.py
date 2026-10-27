"""Persistent validation and rollback records for legacy data migration."""
from __future__ import annotations

from datetime import datetime
import uuid

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TenantMixin, TimestampMixin


class DataMigrationBatch(TenantMixin, TimestampMixin, Base):
    __tablename__ = "data_migration_batches"
    __table_args__ = (Index("ix_migration_batches_company_status", "company_id", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    migration_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="VALIDATED", server_default=text("'VALIDATED'"))
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    valid_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    error_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    payload_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    validation_errors_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rollback_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    records: Mapped[list[DataMigrationRecord]] = relationship(
        "DataMigrationRecord", back_populates="batch", cascade="all, delete-orphan", lazy="select"
    )


class DataMigrationRecord(TenantMixin, TimestampMixin, Base):
    __tablename__ = "data_migration_records"
    __table_args__ = (Index("ix_migration_records_batch_row", "batch_id", "row_number"),)

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("data_migration_batches.id", ondelete="CASCADE"), nullable=False)
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    action: Mapped[str] = mapped_column(String(20), nullable=False)  # CREATE | UPDATE
    before_snapshot_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after_snapshot_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="COMMITTED", server_default=text("'COMMITTED'"))
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    batch: Mapped[DataMigrationBatch] = relationship("DataMigrationBatch", back_populates="records")


__all__ = ["DataMigrationBatch", "DataMigrationRecord"]
