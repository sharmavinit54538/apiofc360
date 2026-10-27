"""Authenticated field-level encryption and tenant-scoped blind indexing.

The database only ever receives versioned AES-256-GCM envelopes for columns that
use :class:`EncryptedString`.  The first configured key is used for writes;
additional keys are retained for reads so key rotation does not make historical
rows unreadable.  Configure rotation as a JSON list or a comma-separated value,
for example::

    FIELD_ENCRYPTION_KEY="new-32-byte-secret,old-32-byte-secret"

Fernet keys (URL-safe base64 encoded 32-byte keys), 64-character hexadecimal
keys, and ordinary high-entropy passphrases are accepted.  Ordinary passphrases
are domain-separated and hashed to a 256-bit AES key.

Legacy plaintext is readable during the migration window.  It is never silently
written by this type: new/updated values are encrypted, while
``scripts/backfill_encrypted_pii.py`` converts existing rows idempotently.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import unicodedata
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy.types import Text, TypeDecorator

from app.core.config import settings


ENCRYPTED_VALUE_PREFIX = "ofc360:v1:"
_ENCRYPTION_AAD = b"ofc360:field-encryption:v1"
_BLIND_INDEX_DOMAIN = b"ofc360:blind-index:v1\x00"


class FieldEncryptionError(RuntimeError):
    """Raised when encrypted field configuration or ciphertext is invalid."""


def _secret_text(value: Any) -> Any:
    """Unwrap Pydantic ``SecretStr`` without assuming its concrete type."""

    if hasattr(value, "get_secret_value"):
        return value.get_secret_value()
    return value


def _configured_keys() -> list[str]:
    raw = _secret_text(getattr(settings, "FIELD_ENCRYPTION_KEY", ""))
    # Reading the environment as a fallback also supports secret-manager
    # refreshes and tests that rotate keys without rebuilding Settings.
    if not raw:
        raw = os.getenv("FIELD_ENCRYPTION_KEY", "")
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        candidates = [str(item).strip() for item in raw]
    else:
        text = str(raw).strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError as exc:
                raise FieldEncryptionError(
                    "FIELD_ENCRYPTION_KEY must be a key, comma-separated keys, or a JSON key list."
                ) from exc
            if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
                raise FieldEncryptionError("FIELD_ENCRYPTION_KEY JSON value must be a list of strings.")
            candidates = [item.strip() for item in parsed]
        else:
            candidates = [item.strip() for item in text.split(",")]

    # Preserve order: index zero is always the write key.
    return list(dict.fromkeys(item for item in candidates if item))


def _decode_key_material(material: str) -> bytes:
    """Convert supported key representations into an AES-256 key."""

    encoded = material.encode("utf-8")

    # A Fernet key is URL-safe base64 containing exactly 32 bytes.  Using its
    # decoded bytes with AES-GCM lets deployments reuse existing key inventory.
    try:
        decoded = base64.urlsafe_b64decode(encoded)
        if len(decoded) == 32 and base64.urlsafe_b64encode(decoded).decode("ascii") == material:
            return decoded
    except Exception:
        pass

    if len(material) == 64:
        try:
            decoded = bytes.fromhex(material)
            if len(decoded) == 32:
                return decoded
        except ValueError:
            pass

    if len(encoded) < 32:
        raise FieldEncryptionError(
            "Each FIELD_ENCRYPTION_KEY must contain at least 32 bytes of high-entropy key material."
        )
    return hashlib.sha256(b"ofc360:field-key:v1\x00" + encoded).digest()


def _key_ring() -> list[tuple[str, bytes]]:
    ring: list[tuple[str, bytes]] = []
    for material in _configured_keys():
        key = _decode_key_material(material)
        # The key id is only a short fingerprint, never key material itself.
        key_id = hashlib.sha256(b"ofc360:key-id:v1\x00" + key).hexdigest()[:12]
        ring.append((key_id, key))
    if not ring:
        raise FieldEncryptionError(
            "FIELD_ENCRYPTION_KEY is required to read or write encrypted PII fields."
        )
    return ring


def encrypt_value(value: str | None) -> str | None:
    """Encrypt a string with the current key using AES-256-GCM.

    ``None`` remains ``None``.  Already enveloped values are returned unchanged,
    which makes administrative backfills and retry logic safe from accidental
    double encryption.
    """

    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    if is_encrypted_value(value):
        return value

    key_id, key = _key_ring()[0]
    nonce = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(nonce, value.encode("utf-8"), _ENCRYPTION_AAD)
    payload = base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")
    return f"{ENCRYPTED_VALUE_PREFIX}{key_id}:{payload}"


def decrypt_value(value: str | None) -> str | None:
    """Decrypt a versioned envelope with any configured key.

    Plaintext values are returned unchanged solely to support the explicit
    migration/backfill window.  Authentication failures never return ciphertext
    or partial plaintext to callers.
    """

    if value is None or not isinstance(value, str) or not is_encrypted_value(value):
        return value

    try:
        key_id, encoded_payload = value[len(ENCRYPTED_VALUE_PREFIX):].split(":", 1)
        matching_keys = [key for candidate_id, key in _key_ring() if candidate_id == key_id]
        if not matching_keys:
            raise FieldEncryptionError(
                "The key required by this encrypted field is not configured. Retain previous keys during rotation."
            )
        payload = base64.b64decode(encoded_payload.encode("ascii"), altchars=b"-_", validate=True)
        if len(payload) < 28:  # 12-byte nonce + 16-byte GCM authentication tag
            raise ValueError("invalid encrypted payload")
        nonce, ciphertext = payload[:12], payload[12:]
        plaintext = AESGCM(matching_keys[0]).decrypt(nonce, ciphertext, _ENCRYPTION_AAD)
        return plaintext.decode("utf-8")
    except FieldEncryptionError:
        raise
    except Exception as exc:
        raise FieldEncryptionError(
            "Encrypted field authentication failed; the value is corrupt or was encrypted with another key."
        ) from exc


def is_encrypted_value(value: Any) -> bool:
    """Return whether a value carries this module's authenticated envelope."""

    return isinstance(value, str) and value.startswith(ENCRYPTED_VALUE_PREFIX)


def _normalise_for_index(value: Any) -> str:
    """Canonicalise identifiers so harmless formatting differences match."""

    text = unicodedata.normalize("NFKC", str(value)).strip().upper()
    # Government and bank identifiers are frequently entered with spaces or
    # hyphens.  They are formatting, not part of the identifier's identity.
    return "".join(character for character in text if not character.isspace() and character != "-")


def _blind_index_key() -> bytes:
    # Blind indexes are recomputed by the backfill command when the write key is
    # rotated.  This avoids a deterministic, keyless hash of low-entropy PII.
    _, primary_key = _key_ring()[0]
    return hmac.new(primary_key, _BLIND_INDEX_DOMAIN, hashlib.sha256).digest()


def hmac_sha256_blind_index(value: Any, company_id: Any) -> str | None:
    """Return a deterministic, tenant-bound HMAC-SHA256 exact-match index.

    ``None`` and empty strings produce ``None`` so optional columns do not share
    a common index value.  A company/tenant identifier is mandatory; this keeps
    equal identifiers in different tenants from producing equal indexes.
    """

    if value is None or company_id is None:
        return None
    normalised = _normalise_for_index(value)
    if not normalised:
        return None
    tenant = unicodedata.normalize("NFKC", str(company_id)).strip().lower()
    if not tenant:
        raise ValueError("company_id is required for a tenant-scoped blind index")
    message = tenant.encode("utf-8") + b"\x00" + normalised.encode("utf-8")
    return hmac.new(_blind_index_key(), message, hashlib.sha256).hexdigest()


class EncryptedString(TypeDecorator[str]):
    """SQLAlchemy string type that stores only authenticated ciphertext.

    Use ``Text`` at the database layer because nonce, tag, version and key id
    overhead make ciphertext longer than the original identifier.
    """

    impl = Text
    cache_ok = True
    python_type = str

    def process_bind_param(self, value: str | None, dialect: Any) -> str | None:
        return encrypt_value(value)

    def process_result_value(self, value: str | None, dialect: Any) -> str | None:
        return decrypt_value(value)


__all__ = [
    "ENCRYPTED_VALUE_PREFIX",
    "EncryptedString",
    "FieldEncryptionError",
    "decrypt_value",
    "encrypt_value",
    "hmac_sha256_blind_index",
    "is_encrypted_value",
]
