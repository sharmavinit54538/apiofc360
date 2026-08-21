from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, new_uuid


class School(Base, TimestampMixin):
    """
    Each School IS the tenant (single-school-per-tenant model, matching the
    frontend's tenant_id/school_id pair, which are always equal in practice).
    tenant_id and school_id both reference this row's id — kept as two
    columns only so every other table can carry both names the frontend
    already expects, without implying multi-school tenants exist yet.
    """

    __tablename__ = "schools"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    school_code: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    school_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)  # active | suspended

    users = relationship("User", back_populates="school", foreign_keys="User.school_id", cascade="all, delete-orphan")

    @property
    def tenant_id(self) -> str:
        return self.id

    @property
    def school_id(self) -> str:
        return self.id
