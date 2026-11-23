"""Signed expiring token utilities for public offer actions.

Provides HMAC-based tokens bound to (offer_id, company_id, candidate_email)
with configurable expiry. Used for secure public offer accept/reject endpoints.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

from app.core.config import settings


def _get_signing_key() -> bytes:
    """Get the signing key from settings."""
    secret = settings.SECRET_KEY
    if hasattr(secret, "get_secret_value"):
        secret = secret.get_secret_value()
    return str(secret).encode("utf-8")


def _get_token_expiry_seconds() -> int:
    """Get token expiry from settings (default 7 days)."""
    return getattr(settings, "OFFER_ACTION_TOKEN_EXPIRY_DAYS", 7) * 86400


def create_offer_action_token(
    offer_id: str,
    company_id: str,
    candidate_email: str,
    action: str,  # "accept" or "reject"
) -> str:
    """Create a signed expiring token for offer action.

    Token payload: {
        "offer_id": str,
        "company_id": str,
        "candidate_email": str,
        "action": "accept" | "reject",
        "iat": int (timestamp),
        "exp": int (timestamp)
    }

    Returns: base64url-encoded token string
    """
    now = int(time.time())
    expiry_seconds = _get_token_expiry_seconds()

    payload = {
        "offer_id": offer_id,
        "company_id": company_id,
        "candidate_email": candidate_email,
        "action": action,
        "iat": now,
        "exp": now + expiry_seconds,
    }

    # Encode payload as base64url JSON
    payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    payload_b64 = base64.urlsafe_b64encode(payload_json.encode("utf-8")).decode("ascii").rstrip("=")

    # Create HMAC signature
    signing_key = _get_signing_key()
    signature = hmac.new(signing_key, payload_b64.encode("ascii"), hashlib.sha256).digest()
    signature_b64 = base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")

    # Combine payload and signature
    token = f"{payload_b64}.{signature_b64}"
    return token


def verify_offer_action_token(token: str) -> dict[str, Any] | None:
    """Verify a signed offer action token.

    Returns the decoded payload if valid, None if invalid/expired/tampered.
    """
    try:
        # Split token into payload and signature
        parts = token.split(".")
        if len(parts) != 2:
            return None

        payload_b64, signature_b64 = parts

        # Verify signature
        signing_key = _get_signing_key()
        expected_signature = hmac.new(signing_key, payload_b64.encode("ascii"), hashlib.sha256).digest()
        expected_signature_b64 = base64.urlsafe_b64encode(expected_signature).decode("ascii").rstrip("=")

        if not hmac.compare_digest(signature_b64, expected_signature_b64):
            return None  # Tampered

        # Decode payload
        # Add padding back if needed
        padding = "=" * (-len(payload_b64) % 4)
        payload_json = base64.urlsafe_b64decode(payload_b64 + padding).decode("utf-8")
        payload = json.loads(payload_json)

        # Check expiry
        now = int(time.time())
        if payload.get("exp", 0) < now:
            return None  # Expired

        # Check required fields
        required = ("offer_id", "company_id", "candidate_email", "action")
        if not all(k in payload for k in required):
            return None

        if payload["action"] not in ("accept", "reject"):
            return None

        return payload

    except Exception:
        return None


def create_offer_action_urls(
    base_url: str,
    offer_id: str,
    company_id: str,
    candidate_email: str,
) -> dict[str, str]:
    """Create accept/reject URLs with signed tokens for offer email."""
    accept_token = create_offer_action_token(offer_id, company_id, candidate_email, "accept")
    reject_token = create_offer_action_token(offer_id, company_id, candidate_email, "reject")

    return {
        "accept_url": f"{base_url}/offers/{offer_id}/accept?token={accept_token}",
        "reject_url": f"{base_url}/offers/{offer_id}/reject?token={reject_token}",
    }