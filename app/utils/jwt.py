"""JWT generation, decoding, and hashing utilities.

Supports both HS256 (symmetric, using SECRET_KEY) and RS256 (asymmetric,
using RSA PEM keys) based on the configured JWT_ALGORITHM setting.
"""

from datetime import datetime, timedelta, timezone
import hashlib
from typing import Any
import uuid

from jose import jwt
from jose.exceptions import ExpiredSignatureError, JWSSignatureError, JWTClaimsError, JWTError

from app.core.config import settings


_JWT_ALGORITHM: str = settings.JWT_ALGORITHM
_IS_SYMMETRIC: bool = _JWT_ALGORITHM.upper().startswith("HS")

# ---------------------------------------------------------------------------
# Key helpers — lazy-loaded once on first use
# ---------------------------------------------------------------------------

# Symmetric (HS256): signing key is the SECRET_KEY string
_SYMMETRIC_KEY: str | None = None

# Asymmetric (RS256): signing key is an RSA private key object
_PRIVATE_KEY: Any = None
_PUBLIC_KEY: Any = None


def _get_signing_key() -> Any:
    """Return the key used to *sign* tokens (private RSA key or SECRET_KEY)."""
    if _IS_SYMMETRIC:
        global _SYMMETRIC_KEY
        if _SYMMETRIC_KEY is None:
            _SYMMETRIC_KEY = settings.SECRET_KEY.get_secret_value()
        return _SYMMETRIC_KEY

    global _PRIVATE_KEY
    if _PRIVATE_KEY is None:
        from cryptography.hazmat.primitives import serialization
        pem = settings.JWT_PRIVATE_KEY.get_secret_value()
        _PRIVATE_KEY = serialization.load_pem_private_key(
            pem.encode("utf-8"),
            password=None,
        )
    return _PRIVATE_KEY


def _get_verification_key() -> Any:
    """Return the key used to *verify* tokens (public RSA key or SECRET_KEY)."""
    if _IS_SYMMETRIC:
        global _SYMMETRIC_KEY
        if _SYMMETRIC_KEY is None:
            _SYMMETRIC_KEY = settings.SECRET_KEY.get_secret_value()
        return _SYMMETRIC_KEY

    global _PUBLIC_KEY
    if _PUBLIC_KEY is None:
        from cryptography.hazmat.primitives import serialization
        pem = settings.JWT_PUBLIC_KEY.get_secret_value()
        _PUBLIC_KEY = serialization.load_pem_public_key(
            pem.encode("utf-8"),
        )
    return _PUBLIC_KEY


# ---------------------------------------------------------------------------
# Token creation
# ---------------------------------------------------------------------------


def create_access_token(
    user_id: Any,
    role: str,
    company_id: Any | None = None,
    email: str | None = None,
) -> str:
    """Create a signed JWT access token valid for configured minutes."""

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
    return jwt.encode(payload, _get_signing_key(), algorithm=_JWT_ALGORITHM)


def create_refresh_token(user_id: Any) -> str:
    """Create a signed JWT refresh token valid for configured days."""

    now = datetime.now(timezone.utc)
    expire = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {
        "sub": str(user_id),
        "type": "refresh",
        "exp": int(expire.timestamp()),
        "iat": int(now.timestamp()),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, _get_signing_key(), algorithm=_JWT_ALGORITHM)


# ---------------------------------------------------------------------------
# Token decoding / verification
# ---------------------------------------------------------------------------


def decode_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT token; returns token claims.

    Accepts only the configured algorithm (HS256 or RS256).
    """

    try:
        return jwt.decode(
            token,
            _get_verification_key(),
            algorithms=[_JWT_ALGORITHM],
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


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


def hash_token(token: str) -> str:
    """Return a SHA-256 hash of a token string for safe DB storage."""

    return hashlib.sha256(token.encode("utf-8")).hexdigest()