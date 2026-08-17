"""RFC 6238 compliant TOTP (Time-Based One-Time Password) utilities for Multi-Factor Authentication."""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import secrets
import struct
import time
import urllib.parse
from typing import Optional

try:
    import qrcode
    HAS_QRCODE = True
except ImportError:
    HAS_QRCODE = False


def generate_totp_secret(num_bytes: int = 20) -> str:
    """
    Generate a cryptographically secure Base32 encoded secret for TOTP.
    Default 20 bytes (160 bits) produces a standard 32-character Base32 string.
    """
    random_bytes = secrets.token_bytes(num_bytes)
    return base64.b32encode(random_bytes).decode("ascii").rstrip("=")


def generate_provisioning_uri(
    secret: str,
    account_name: str,
    issuer_name: str = "OFC360",
) -> str:
    """
    Generate the standard otpauth URI compatible with authenticator apps.
    Format: otpauth://totp/{issuer}:{account}?secret={secret}&issuer={issuer}&algorithm=SHA1&digits=6&period=30
    """
    # Normalize secret (add padding if missing for standard readers)
    clean_secret = secret.strip().replace(" ", "").upper()
    label = f"{issuer_name}:{account_name}"
    encoded_label = urllib.parse.quote(label)
    
    params = {
        "secret": clean_secret,
        "issuer": issuer_name,
        "algorithm": "SHA1",
        "digits": "6",
        "period": "30",
    }
    query_string = urllib.parse.urlencode(params)
    return f"otpauth://totp/{encoded_label}?{query_string}"


def generate_qr_code_data_uri(provisioning_uri: str) -> str:
    """
    Generate a base64 encoded PNG data URI for the provisioning URI.
    Returns format: data:image/png;base64,...
    """
    if not HAS_QRCODE:
        # Fallback if qrcode module is not installed
        return f"https://api.qrserver.com/v1/create-qr-code/?size=250x250&data={urllib.parse.quote(provisioning_uri)}"

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=3,
    )
    qr.add_data(provisioning_uri)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    b64_img = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64_img}"


def _compute_totp(secret_bytes: bytes, time_step: int, digits: int = 6) -> str:
    """Compute the HMAC-SHA1 TOTP code for a given time step counter."""
    # Pack the 64-bit integer into 8 bytes in big-endian order
    msg = struct.pack(">Q", time_step)
    h = hmac.new(secret_bytes, msg, hashlib.sha1).digest()
    
    # Dynamic Truncation
    offset = h[-1] & 0x0F
    binary_code = struct.unpack(">I", h[offset : offset + 4])[0] & 0x7FFFFFFF
    otp = binary_code % (10 ** digits)
    return f"{otp:0{digits}d}"


def get_current_totp(secret: str, interval: int = 30, digits: int = 6) -> str:
    """Generate the current TOTP code for a secret."""
    clean_secret = secret.strip().replace(" ", "").upper()
    # Add padding if required for b32decode
    missing_padding = len(clean_secret) % 8
    if missing_padding:
        clean_secret += "=" * (8 - missing_padding)
    secret_bytes = base64.b32decode(clean_secret, casefold=True)
    
    current_time_step = int(time.time()) // interval
    return _compute_totp(secret_bytes, current_time_step, digits=digits)


def verify_totp_code(
    secret: str,
    code: str,
    interval: int = 30,
    digits: int = 6,
    window: int = 1,
) -> bool:
    """
    Verify a TOTP code against a secret with clock drift tolerance.
    window=1 checks [t-1, t, t+1] (30 seconds before and after).
    Returns True if valid, False otherwise. Constant-time comparison.
    """
    if not secret or not code:
        return False
        
    clean_code = str(code).strip().replace(" ", "")
    if len(clean_code) != digits or not clean_code.isdigit():
        return False

    clean_secret = secret.strip().replace(" ", "").upper()
    missing_padding = len(clean_secret) % 8
    if missing_padding:
        clean_secret += "=" * (8 - missing_padding)

    try:
        secret_bytes = base64.b32decode(clean_secret, casefold=True)
    except Exception:
        return False

    current_step = int(time.time()) // interval
    
    for step_offset in range(-window, window + 1):
        test_step = current_step + step_offset
        expected_code = _compute_totp(secret_bytes, test_step, digits=digits)
        if hmac.compare_digest(expected_code, clean_code):
            return True
            
    return False
