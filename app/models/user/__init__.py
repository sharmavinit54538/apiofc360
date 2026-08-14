"""User database model package exports."""

from __future__ import annotations

from typing import Any
from sqlalchemy import Index
from sqlalchemy.orm import validates

from app.db.base import Base
from app.models.user.role import UserRole, UserAccountStatus, OFFICIAL_SUPER_ADMIN_EMAIL
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

    @property
    def is_super_admin(self) -> bool:
        """Immutable Super Admin identity verification requiring official email and role."""
        email_clean = (self.email or "").strip().lower()
        role_val = self.role.value if hasattr(self.role, "value") else str(self.role).lower()
        return email_clean == OFFICIAL_SUPER_ADMIN_EMAIL and role_val == UserRole.SUPER_ADMIN.value

    @validates("role")
    def validate_user_role(self, key: str, value: Any) -> Any:
        """Enforce that SUPER_ADMIN can only be held by superadmin@ofc360.com."""
        if value is None:
            return value
        role_val = value.value if hasattr(value, "value") else str(value).lower()
        if role_val == UserRole.SUPER_ADMIN.value:
            current_email = (getattr(self, "email", None) or "").strip().lower()
            if current_email and current_email != OFFICIAL_SUPER_ADMIN_EMAIL:
                raise ValueError(
                    f"Security Lock Violation: Only {OFFICIAL_SUPER_ADMIN_EMAIL} is authorized to hold the SUPER_ADMIN role."
                )
        return value

    @validates("email")
    def validate_user_email(self, key: str, value: Any) -> Any:
        """Enforce that if role is SUPER_ADMIN, email cannot be changed away from superadmin@ofc360.com."""
        if value is None:
            return value
        clean_email = str(value).strip().lower()
        current_role = getattr(self, "role", None)
        role_val = current_role.value if hasattr(current_role, "value") else str(current_role or "").lower()
        if role_val == UserRole.SUPER_ADMIN.value and clean_email != OFFICIAL_SUPER_ADMIN_EMAIL:
            raise ValueError(
                f"Security Lock Violation: The SUPER_ADMIN account email must remain {OFFICIAL_SUPER_ADMIN_EMAIL}."
            )
        return clean_email


__all__ = ["User", "UserRole", "UserAccountStatus", "OFFICIAL_SUPER_ADMIN_EMAIL"]
