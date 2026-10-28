"""Enterprise OIDC/SAML identity mappings and SCIM 2.0 provisioning models."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, JSON, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.field_encryption import EncryptedString
from app.db.base import Base
from app.models.enterprise_common import EnterpriseModelMixin


class IdentityProvider(EnterpriseModelMixin, Base):
    __tablename__ = "identity_providers"
    __table_args__ = (UniqueConstraint("company_id", "provider_type", name="uq_identity_provider_company_type"),)

    provider_type: Mapped[str] = mapped_column(String(30), nullable=False)
    client_id: Mapped[str | None] = mapped_column(String(300), nullable=True)
    client_secret: Mapped[str | None] = mapped_column(EncryptedString(), nullable=True)
    issuer: Mapped[str | None] = mapped_column(String(500), nullable=True)
    authorization_endpoint: Mapped[str | None] = mapped_column(String(500), nullable=True)
    token_endpoint: Mapped[str | None] = mapped_column(String(500), nullable=True)
    jwks_uri: Mapped[str | None] = mapped_column(String(500), nullable=True)
    saml_sso_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    sp_entity_id: Mapped[str | None] = mapped_column(String(500), nullable=True)
    x509_certificate: Mapped[str | None] = mapped_column(Text, nullable=True)
    allowed_domains: Mapped[list] = mapped_column(JSON, nullable=False, default=list, server_default=text("'[]'"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))


class ExternalIdentity(EnterpriseModelMixin, Base):
    __tablename__ = "external_identities"
    __table_args__ = (
        UniqueConstraint("company_id", "provider_type", "external_id", name="uq_external_identity_provider_id"),
        Index("ix_external_identities_company_user", "company_id", "user_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(30), nullable=False)
    external_id: Mapped[str] = mapped_column(String(300), nullable=False)
    attributes_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default=text("'{}'"))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SSOAssertion(EnterpriseModelMixin, Base):
    """Consumed SAML assertion IDs for replay prevention."""

    __tablename__ = "sso_assertions"
    __table_args__ = (UniqueConstraint("company_id", "assertion_id", name="uq_sso_assertion_company_id"),)

    assertion_id: Mapped[str] = mapped_column(String(300), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SCIMToken(EnterpriseModelMixin, Base):
    __tablename__ = "scim_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_scim_token_hash"),
        Index("ix_scim_tokens_company_active", "company_id", "is_active"),
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    prefix: Mapped[str] = mapped_column(String(20), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    scopes: Mapped[list] = mapped_column(JSON, nullable=False, default=list, server_default=text("'[]'"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class SCIMGroup(EnterpriseModelMixin, Base):
    __tablename__ = "scim_groups"
    __table_args__ = (UniqueConstraint("company_id", "display_name", name="uq_scim_group_company_name"),)

    display_name: Mapped[str] = mapped_column(String(150), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(150), nullable=True)

    members: Mapped[list[SCIMGroupMember]] = relationship(
        "SCIMGroupMember", back_populates="group", cascade="all, delete-orphan", lazy="select",
    )


class SCIMGroupMember(EnterpriseModelMixin, Base):
    __tablename__ = "scim_group_members"
    __table_args__ = (UniqueConstraint("group_id", "user_id", name="uq_scim_group_member"),)

    group_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("scim_groups.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    group: Mapped[SCIMGroup] = relationship("SCIMGroup", back_populates="members", lazy="select")
