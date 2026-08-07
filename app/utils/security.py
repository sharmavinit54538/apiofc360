"""Security helpers shared by utility modules."""

import hmac

from app.core.security import hash_password, verify_password


def secure_compare(left: str, right: str) -> bool:
    """Compare two strings in constant time."""

    return hmac.compare_digest(left, right)