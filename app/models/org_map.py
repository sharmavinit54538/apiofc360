"""AI Organization Intelligence Map models."""
from __future__ import annotations
from datetime import datetime
from typing import TYPE_CHECKING
import uuid
from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base
if TYPE_CHECKING:
    from app.models.company import Company

class OrgHierarchySnapshot(Base):
    __tablename__ = "org_hierarchy_snapshots"
    __table_args__ = (Index("ix_org_snapshots_company_id", "company_id"),)
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    hierarchy_json: Mapped[str] = mapped_column(Text, nullable=False)  # Full org tree JSON
    department_structure: Mapped[str] = mapped_column(Text, nullable=False)
    leadership_map: Mapped[str] = mapped_column(Text, nullable=False)
    ai_insights: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    company: Mapped[Company] = relationship("Company", lazy="select")
