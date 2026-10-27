"""Security helpers shared by utility modules and API serializers."""

from __future__ import annotations

import hmac
from typing import Any

from app.core.security import hash_password, verify_password


REDACTED_PLACEHOLDER = "[REDACTED]"


def secure_compare(left: str, right: str) -> bool:
    """Compare two strings in constant time."""

    return hmac.compare_digest(left, right)


def redact_government_id(value: Any) -> str | None:
    """Replace a government identity number with a non-reversible placeholder."""

    if value is None:
        return None
    return REDACTED_PLACEHOLDER


def mask_identifier(
    value: Any,
    *,
    visible_prefix: int = 0,
    visible_suffix: int = 4,
    mask_character: str = "*",
) -> str | None:
    """Mask an identifier while retaining only explicitly allowed characters.

    The operation is idempotent so already masked values cannot be unmasked or
    repeatedly transformed by nested serializers.  Empty input stays empty.
    """

    if value is None:
        return None
    text = str(value).strip()
    if not text or text == REDACTED_PLACEHOLDER:
        return text
    if "*" in text:
        return text
    if len(mask_character) != 1:
        raise ValueError("mask_character must be one character")

    visible_prefix = max(0, visible_prefix)
    visible_suffix = max(0, visible_suffix)
    if visible_prefix + visible_suffix >= len(text):
        # Never return the original value merely because it is unusually short.
        keep = min(visible_suffix, max(0, len(text) - 1))
        visible_prefix = 0
        visible_suffix = keep
    masked_length = len(text) - visible_prefix - visible_suffix
    if masked_length <= 0:
        return mask_character * len(text)
    return (
        text[:visible_prefix]
        + mask_character * masked_length
        + (text[-visible_suffix:] if visible_suffix else "")
    )


def mask_pan(value: Any) -> str | None:
    """Mask a PAN for ordinary responses (for example ``ABCDE****F``)."""

    return mask_identifier(value, visible_prefix=5, visible_suffix=1)


def mask_uan(value: Any) -> str | None:
    """Mask a UAN, exposing at most its final four digits."""

    return mask_identifier(value, visible_suffix=4)


def mask_bank_account(value: Any) -> str | None:
    """Mask a bank account number, exposing at most its final four digits."""

    return mask_identifier(value, visible_suffix=4, mask_character="X")


# Descriptive aliases used by different serializer generations.
mask_account_number = mask_bank_account
mask_aadhaar = redact_government_id
mask_passport_number = redact_government_id
mask_voter_id = redact_government_id


__all__ = [
    "REDACTED_PLACEHOLDER",
    "hash_password",
    "mask_aadhaar",
    "mask_account_number",
    "mask_bank_account",
    "mask_identifier",
    "mask_pan",
    "mask_passport_number",
    "mask_uan",
    "mask_voter_id",
    "redact_government_id",
    "secure_compare",
    "verify_password",
]
