"""User repository for database access."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


class UserRepository:
    """Repository for user persistence operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_email(self, email: str) -> User | None:
        """Return a user by email, if one exists."""

        if not email:
            return None
        from sqlalchemy import func
        result = await self.session.execute(
            select(User)
            .where(func.lower(User.email) == func.lower(email.strip()))
            .execution_options(bypass_tenant=True)
        )
        return result.scalar_one_or_none()

    async def get_by_phone(self, phone: str) -> User | None:
        """Return a user by phone number, if one exists."""

        if not phone:
            return None
        result = await self.session.execute(
            select(User)
            .where(User.phone == phone.strip())
            .execution_options(bypass_tenant=True)
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        name: str,
        email: str,
        phone: str,
        password_hash: str,
    ) -> User:
        """Create a user record in the current transaction."""

        user = User(
            name=name,
            email=email,
            phone=phone,
            password_hash=password_hash,
        )
        self.session.add(user)
        await self.session.flush()
        return user
