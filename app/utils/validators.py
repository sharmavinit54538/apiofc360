"""Reusable input validation and sanitization helpers."""

import re


NAME_PATTERN = re.compile(r"^[A-Za-z\s\.\'\-]+$")
PHONE_PATTERN = re.compile(r"^[6-9]\d{9}$")
BCRYPT_MAX_PASSWORD_BYTES = 72

WEAK_PASSWORDS = {
    "12345678",
    "123456789",
    "qwerty123",
    "admin1234",
    "letmein123",
    "welcome123",
    "changeme123",
    "qwerty@123",
    "admin@123",
    "welcome@123",
}


def ensure_string(value: object, field_name: str) -> str:
    """Validate that an incoming value is a string before sanitizing it."""

    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    return value


def normalize_spaces(value: str) -> str:
    """Trim external whitespace and collapse repeated internal spaces."""

    return " ".join(value.strip().split())


def validate_name(value: str) -> str:
    """Validate and normalize a human name (supporting spaces, hyphens, apostrophes, and dots)."""

    value = ensure_string(value, "Name")
    normalized = normalize_spaces(value)
    if not normalized:
        raise ValueError("Name is required")
    if not 2 <= len(normalized) <= 100:
        raise ValueError("Name must be between 2 and 100 characters")
    if not NAME_PATTERN.fullmatch(normalized) or not re.search(r"[A-Za-z]", normalized):
        raise ValueError("Name can contain only alphabetic characters, spaces, hyphens, apostrophes, and dots")
    return normalized


def normalize_email(value: str) -> str:
    """Trim and lowercase an email address before RFC validation."""

    value = ensure_string(value, "Email")
    normalized = value.strip().lower()
    if not normalized:
        raise ValueError("Email is required")
    return normalized


def validate_phone(value: object) -> str:
    """Validate and normalize an Indian mobile number to 10 digits.

    Supports strings and integers in formats such as:
    - 9876543210
    - +919876543210 / +91 9876543210 / +91-9876543210
    - 919876543210
    - 09876543210

    Returns the normalized 10-digit string starting with 6-9.
    """
    if value is None:
        raise ValueError("Phone is required")

    if isinstance(value, (int, float)):
        raw_str = str(int(value))
    elif isinstance(value, str):
        raw_str = value
    else:
        raise ValueError("Phone must be a string")

    normalized = raw_str.strip()
    if not normalized:
        raise ValueError("Phone is required")

    # Remove formatting characters (spaces, hyphens, parentheses, dots)
    cleaned = re.sub(r"[\s\-\(\)\.]+", "", normalized)

    # Normalize standard Indian country code / trunk prefixes
    if cleaned.startswith("+91"):
        cleaned = cleaned[3:]
    elif cleaned.startswith("91") and len(cleaned) == 12:
        cleaned = cleaned[2:]
    elif cleaned.startswith("0") and len(cleaned) == 11:
        cleaned = cleaned[1:]

    if not PHONE_PATTERN.fullmatch(cleaned):
        raise ValueError("Phone must be a valid 10-digit Indian mobile number (e.g. 9876543210 or +919876543210)")

    return cleaned


def validate_password_strength(
    password: str,
    *,
    email: str | None = None,
    name: str | None = None,
    phone: str | None = None,
) -> str:
    """Validate password complexity without mutating the password."""

    password = ensure_string(password, "Password")
    if not password:
        raise ValueError("Password is required")
    if password != password.strip():
        raise ValueError("Password must not start or end with spaces")
    if not 8 <= len(password) <= 64:
        raise ValueError("Password must be between 8 and 64 characters")
    if len(password.encode("utf-8")) > BCRYPT_MAX_PASSWORD_BYTES:
        raise ValueError("Password is too long for bcrypt hashing")
    if password.lower() in WEAK_PASSWORDS:
        raise ValueError("Password is too weak")
    if not re.search(r"[A-Z]", password):
        raise ValueError("Password must contain at least one uppercase letter")
    if not re.search(r"[a-z]", password):
        raise ValueError("Password must contain at least one lowercase letter")
    if not re.search(r"\d", password):
        raise ValueError("Password must contain at least one number")
    if not re.search(r"[^A-Za-z0-9]", password):
        raise ValueError("Password must contain at least one special character")
    if re.search(r"(.)\1{3,}", password):
        raise ValueError("Password must not contain long repeated character sequences")

    lowered_password = password.lower()
    if email:
        local_part = email.split("@", 1)[0].lower()
        if local_part and len(local_part) >= 5 and local_part in lowered_password:
            raise ValueError("Password must not contain your email username")
    if phone and phone in password:
        raise ValueError("Password must not contain your phone number")
    if name:
        for part in name.lower().split():
            if len(part) >= 5 and part in lowered_password:
                raise ValueError("Password must not contain your name")

    return password
