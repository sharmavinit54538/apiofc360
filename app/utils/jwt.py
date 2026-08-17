"""JWT generation, decoding, and hashing utilities."""

from datetime import datetime, timedelta, timezone
import hashlib
from typing import Any
import uuid

from cryptography.hazmat.primitives import serialization
from jose import jwt
from jose.exceptions import ExpiredSignatureError, JWSSignatureError, JWTClaimsError, JWTError

from app.core.config import settings


# Cache key values at module level to avoid SecretStr unwrap overhead per request
_PRIVATE_KEY_PEM: str = settings.JWT_PRIVATE_KEY.get_secret_value()
_PUBLIC_KEY_PEM: str = settings.JWT_PUBLIC_KEY.get_secret_value()
_JWT_ALGORITHM: str = settings.JWT_ALGORITHM


def _load_private_key() -> Any:
    """Load RSA private key from PEM string."""
    return serialization.load_pem_private_key(
        _PRIVATE_KEY_PEM.encode("utf-8"),
        password=None,
    )


def _load_public_key() -> Any:
    """Load RSA public key from PEM string."""
    return serialization.load_pem_public_key(
        _PUBLIC_KEY_PEM.encode("utf-8"),
    )


# Lazy-load keys to allow configuration validation at startup
_PRIVATE_KEY: Any = None
_PUBLIC_KEY: Any = None


def _get_private_key() -> Any:
    global _PRIVATE_KEY
    if _PRIVATE_KEY is None:
        _PRIVATE_KEY = _load_private_key()
    return _PRIVATE_KEY


def _get_public_key() -> Any:
    global _PUBLIC_KEY
    if _PUBLIC_KEY is None:
        _PUBLIC_KEY = _load_public_key()
    return _PUBLIC_KEY


def create_access_token(
    user_id: Any,
    role: str,
    company_id: Any | None = None,
    email: str | None = None,
) -> str:
    """Create a signed JWT access token valid for configured minutes using RS256."""

    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),
        "role": role,
        "type": "access",
        "exp": int(expire.timestamp()),
        "iat": int(now.timestamp()),
        "jti": str(uuid.uuid4()),
    }
    if email:
        payload["email"] = str(email).strip().lower()
    if company_id:
        payload["company_id"] = str(company_id)
    return jwt.encode(payload, _get_private_key(), algorithm=_JWT_ALGORITHM)


def create_refresh_token(user_id: Any) -> str:
    """Create a signed JWT refresh token valid for configured days using RS256."""

    now = datetime.now(timezone.utc)
    expire = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {
        "sub": str(user_id),
        "type": "refresh",
        "exp": int(expire.timestamp()),
        "iat": int(now.timestamp()),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, _get_private_key(), algorithm=_JWT_ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT token; returns token claims.
    
    Only accepts RS256 algorithm. Rejects HS256 and other algorithms.
    """

    try:
        return jwt.decode(
            token,
            _get_public_key(),
            algorithms=[_JWT_ALGORITHM],  # Only allow RS256
            options={"verify_signature": True, "verify_exp": True, "verify_iat": True},
        )
    except ExpiredSignatureError as exc:
        raise ValueError("Token has expired.") from exc
    except JWSSignatureError as exc:
        raise ValueError("JWT signature invalid.") from exc
    except JWTClaimsError as exc:
        raise ValueError(f"JWT claims invalid: {str(exc)}") from exc
    except JWTError as exc:
        raise ValueError("JWT decoding failed.") from exc


def hash_token(token: str) -> str:
    """Return a SHA-256 hash of a token string for safe DB storage."""

    return hashlib.sha256(token.encode("utf-8")).hexdigest()