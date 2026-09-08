import json

from sqlalchemy import ForeignKey, String, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.permissions import permissions_for_role
from app.db.base import Base, TimestampMixin, new_uuid


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("schools.id"), index=True, nullable=False)
    school_id: Mapped[str] = mapped_column(String(36), ForeignKey("schools.id"), index=True, nullable=False)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)  # admin|teacher|student|parent|accountant
    avatar: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)  # active | inactive
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_login_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # extra permissions granted beyond the role default, stored as JSON list
    extra_permissions: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    school = relationship("School", back_populates="users", foreign_keys=[school_id])

    def permissions_list(self) -> list[str]:
        base = permissions_for_role(self.role)
        if self.extra_permissions:
            try:
                extra = json.loads(self.extra_permissions)
                return sorted(set(base) | set(extra))
            except Exception:
                return base
        return base
