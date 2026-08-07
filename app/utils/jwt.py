"""JWT generation, decoding, and hashing utilities."""

from datetime import datetime, timedelta, timezone
import hashlib
from typing import Any
import uuid

from jose import jwt, JWTError, ExpiredSignatureError

from app.core.config import settings

# Cache secret key value at module level to avoid SecretStr unwrap overhead per request
_SECRET_KEY: str = settings.SECRET_KEY.get_secret_value()
_JWT_ALGORITHM: str = settings.JWT_ALGORITHM


def create_access_token(user_id: Any, role: str, company_id: Any | None = None) -> str:
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
    if company_id:
        payload["company_id"] = str(company_id)
    return jwt.encode(payload, _SECRET_KEY, algorithm=_JWT_ALGORITHM)


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
    return jwt.encode(payload, _SECRET_KEY, algorithm=_JWT_ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT token; returns token claims."""
    from jose.exceptions import ExpiredSignatureError, JWSSignatureError, JWTClaimsError, JWTError

    try:
        return jwt.decode(token, _SECRET_KEY, algorithms=[_JWT_ALGORITHM])
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
