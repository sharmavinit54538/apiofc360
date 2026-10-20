"""Password hashing and JWT helper utilities."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt

from app.core.config import settings
from app.utils.jwt import create_access_token as _create_access_token


def hash_password(password: str) -> str:
    """Hash a plaintext password using bcrypt (sync version)."""

    # bcrypt max password limit is 72 bytes. Our validators ensure it's shorter.
    password_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt(rounds=settings.BCRYPT_ROUNDS)
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Verify a plaintext password against a bcrypt hash (sync version)."""

    try:
        password_bytes = plain_password.encode("utf-8")
        hash_bytes = password_hash.encode("utf-8")
        return bcrypt.checkpw(password_bytes, hash_bytes)
    except Exception:
        return False


async def hash_password_async(password: str) -> str:
    """Hash a plaintext password using bcrypt in a thread pool (async version)."""
    return await asyncio.to_thread(hash_password, password)


async def verify_password_async(plain_password: str, password_hash: str) -> bool:
    """Verify a plaintext password against a bcrypt hash in a thread pool (async version)."""
    return await asyncio.to_thread(verify_password, plain_password, password_hash)


def create_access_token(
    subject: str,
    *,
    expires_delta: timedelta | None = None,
    claims: dict[str, Any] | None = None,
) -> str:
    """Create a signed JWT access token using RS256 via the centralized JWT utility."""
    # Extract user_id from subject for the utility function
    user_id = subject
    role = claims.get("role", "employee") if claims else "employee"
    company_id = claims.get("company_id") if claims else None
    email = claims.get("email") if claims else None

    # The utility function handles the actual token creation with RS256
    return _create_access_token(
        user_id=user_id,
        role=role,
        company_id=company_id,
        email=email,
    )