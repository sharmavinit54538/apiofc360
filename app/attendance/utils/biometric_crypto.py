"""Biometric embedding encryption and sensitive data protection utilities.

Ensures that 128-dimensional facial biometric vectors are encrypted at rest,
never leaked in API responses, and handled with strict confidentiality.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
from typing import Any, List, Optional, Union

from cryptography.fernet import Fernet

from app.core.config import settings

logger = logging.getLogger(__name__)


def _get_fernet() -> Fernet:
    """Derive a deterministic 32-byte URL-safe base64 Fernet key from the app SECRET_KEY."""
    try:
        secret = settings.SECRET_KEY.get_secret_value() if hasattr(settings.SECRET_KEY, "get_secret_value") else str(settings.SECRET_KEY)
    except Exception:
        secret = "default-biometric-secure-salt-key-32bytes-minimum!"

    if not secret:
        secret = "default-biometric-secure-salt-key-32bytes-minimum!"

    # Derive 32 bytes key via SHA-256 and base64-url-encode it
    key_bytes = hashlib.sha256(secret.encode("utf-8")).digest()
    url_safe_key = base64.urlsafe_b64encode(key_bytes)
    return Fernet(url_safe_key)


def encrypt_face_embedding(embedding: List[float]) -> dict:
    """Encrypts a 128-dimensional face embedding into a secure encrypted dictionary wrapper.
    
    Structure:
    {
        "_enc": "fernet_aes256",
        "data": "<ciphertext_token>"
    }
    """
    if not embedding or not isinstance(embedding, list):
        raise ValueError("Valid face embedding list of floats is required.")

    fernet = _get_fernet()
    raw_json = json.dumps(embedding)
    encrypted_token = fernet.encrypt(raw_json.encode("utf-8")).decode("utf-8")

    return {
        "_enc": "fernet_aes256",
        "data": encrypted_token,
    }


def decrypt_face_embedding(payload: Any) -> Optional[List[float]]:
    """Decrypts stored face embedding payload.
    
    Supports:
    - Encrypted wrapper: {"_enc": "fernet_aes256", "data": "..."}
    - Raw token string
    - Legacy unencrypted list of floats (backward compatibility)
    """
    if not payload:
        return None

    # If already a list of floats (legacy stored format), return directly
    if isinstance(payload, list):
        try:
            return [float(x) for x in payload]
        except (ValueError, TypeError):
            logger.error("Failed converting legacy embedding elements to floats.")
            return None

    ciphertext: Optional[str] = None
    if isinstance(payload, dict):
        if payload.get("_enc") == "fernet_aes256" and "data" in payload:
            ciphertext = str(payload["data"])
        elif "ciphertext" in payload:
            ciphertext = str(payload["ciphertext"])
    elif isinstance(payload, str):
        # Could be JSON string or raw Fernet token
        try:
            parsed = json.loads(payload)
            if isinstance(parsed, dict) and "data" in parsed:
                ciphertext = str(parsed["data"])
            elif isinstance(parsed, list):
                return [float(x) for x in parsed]
        except Exception:
            # Assume it's a raw token string
            ciphertext = payload

    if not ciphertext:
        return None

    try:
        fernet = _get_fernet()
        decrypted_bytes = fernet.decrypt(ciphertext.encode("utf-8"))
        embedding_list = json.loads(decrypted_bytes.decode("utf-8"))
        if isinstance(embedding_list, list):
            return [float(x) for x in embedding_list]
    except Exception as exc:
        logger.error("Failed to decrypt face embedding: %s", exc)
        return None

    return None
