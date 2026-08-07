"""OTP generation and hashing helpers."""

import hashlib
import hmac
import secrets
import uuid

from app.core.config import settings
from app.utils.security import secure_compare

OTP_DIGITS = 6
OTP_PURPOSE_EMAIL_VERIFICATION = "email_verification"


def generate_otp() -> str:
    """Generate a cryptographically secure 6-digit OTP."""

    return f"{secrets.randbelow(1_000_000):06d}"


def hash_otp(*, otp: str, user_id: uuid.UUID, purpose: str) -> str:
    """Hash an OTP with a server-side secret and stable user context."""

    message = f"{user_id}:{purpose}:{otp}".encode("utf-8")
    secret = settings.SECRET_KEY.get_secret_value().encode("utf-8")
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def verify_otp_hash(*, otp: str, otp_hash: str, user_id: uuid.UUID, purpose: str) -> bool:
    """Verify a user-provided OTP against a stored OTP hash."""

    expected_hash = hash_otp(otp=otp, user_id=user_id, purpose=purpose)
    return secure_compare(expected_hash, otp_hash)