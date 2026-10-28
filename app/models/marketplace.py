"""Tenant-owned integration marketplace configuration and sync health."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.field_encryption import EncryptedString
from app.db.base import Base
from app.models.enterprise_common import EnterpriseModelMixin


class MarketplaceIntegration(EnterpriseModelMixin, Base):
    __tablename__ = "marketplace_integrations"
    __table_args__ = (
        UniqueConstraint("company_id", "connector_code", name="uq_marketplace_integration_company_connector"),
        Index("ix_marketplace_integrations_company_status", "company_id", "status"),
    )

    connector_code: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DISABLED", server_default=text("'DISABLED'"))
    # JSON-serialized credentials are encrypted by EncryptedString before they
    # reach the database driver.  Read APIs never include this column.
    credentials_encrypted: Mapped[str | None] = mapped_column(EncryptedString(), nullable=True)
    config_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default=text("'{}'"))
    enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_status: Mapped[str | None] = mapped_column(String(20), nullable=True)


class IntegrationSyncLog(EnterpriseModelMixin, Base):
    __tablename__ = "integration_sync_logs"
    __table_args__ = (
        Index("ix_integration_sync_logs_company_connector", "company_id", "connector_code", "created_at"),
        Index("ix_integration_sync_logs_integration", "integration_id", "created_at"),
    )

    integration_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("marketplace_integrations.id", ondelete="CASCADE"), nullable=False,
    )
    connector_code: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(20), nullable=False, default="MANUAL", server_default=text("'MANUAL'"))
    records_received: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    records_accepted: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    records_rejected: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    health_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default=text("'{}'"))
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# Descriptive aliases for callers that use connection/tenant terminology.
TenantIntegration = MarketplaceIntegration
IntegrationConnection = MarketplaceIntegration
