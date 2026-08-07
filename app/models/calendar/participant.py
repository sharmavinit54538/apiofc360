"""Meeting participant database model."""

from __future__ import annotations

from typing import TYPE_CHECKING
import uuid

from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.employee import Employee
    from app.models.calendar.meeting import Meeting


class MeetingParticipant(Base):
    """Participants invited to a meeting."""

    __tablename__ = "meeting_participants"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    meeting_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False)
    employee_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)

    meeting: Mapped[Meeting] = relationship("Meeting", back_populates="participants")
    employee: Mapped[Employee] = relationship("Employee", lazy="select")
