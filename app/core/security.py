"""Password hashing and JWT helper utilities."""

from datetime import UTC, datetime, timedelta
from typing import Any

from jose import jwt
from passlib.context import CryptContext

from app.core.config import settings


import bcrypt

from app.core.config import settings


def hash_password(password: str) -> str:
    """Hash a plaintext password using bcrypt."""

    # bcrypt max password limit is 72 bytes. Our validators ensure it's shorter.
    password_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt(rounds=settings.BCRYPT_ROUNDS)
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""

    try:
        password_bytes = plain_password.encode("utf-8")
        hash_bytes = password_hash.encode("utf-8")
        return bcrypt.checkpw(password_bytes, hash_bytes)
    except Exception:
        return False


def create_access_token(
    subject: str,
    *,
    expires_delta: timedelta | None = None,
    claims: dict[str, Any] | None = None,
) -> str:
    """Create a signed JWT access token."""

    now = datetime.now(UTC)
    expire_at = now + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    payload: dict[str, Any] = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": expire_at,
    }
    if claims:
        payload.update(claims)
    return jwt.encode(
        payload,
        settings.SECRET_KEY.get_secret_value(),
        algorithm=settings.JWT_ALGORITHM,
    )
