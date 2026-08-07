"""User database model package exports."""

from __future__ import annotations

from sqlalchemy import Index

from app.db.base import Base
from app.models.user.role import UserRole
from app.models.user.mixins.columns import UserBasicColumnsMixin
from app.models.user.mixins.system import UserSystemColumnsMixin
from app.models.user.mixins.meta import UserMetaColumnsMixin
from app.models.user.mixins.relations import UserRelationshipsMixin


class User(
    UserBasicColumnsMixin,
    UserSystemColumnsMixin,
    UserMetaColumnsMixin,
    UserRelationshipsMixin,
    Base,
):
    """Application user account."""

    __tablename__ = "users"
    __table_args__ = (
        Index("ix_users_email", "email", unique=True),
        Index("ix_users_phone", "phone", unique=True),
    )


__all__ = ["User", "UserRole"]
