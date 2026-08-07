"""Employee utility functions: ID generation, email generation, token and password helpers."""

from datetime import datetime, timezone
import logging
import re
import secrets
import string
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Activation token
# ---------------------------------------------------------------------------


def generate_activation_token() -> str:
    """Generate a cryptographically secure 48-byte URL-safe activation token."""
    return secrets.token_urlsafe(48)


# ---------------------------------------------------------------------------
# Temporary password
# ---------------------------------------------------------------------------


def generate_temp_password() -> str:
    """Generate a strong 12-character temporary password satisfying complexity rules.

    Format guarantees:
    - At least 2 uppercase, 2 lowercase, 2 digits, 1 special character
    - Length exactly 12 characters
    - No visually ambiguous characters (0, O, 1, l, I)
    - No $ character (avoids JSON/shell escaping issues in email templates)
    - Special chars: @ # ! % & * (safe in email bodies and JSON strings)
    - Always passes validate_password_strength() checks
    - No 4+ consecutive repeated characters
    """
    # Pools with ambiguous chars removed
    upper = "ABCDEFGHJKLMNPQRSTUVWXYZ"    # no O, I
    lower = "abcdefghjkmnpqrstuvwxyz"      # no l, i
    digits = "23456789"                     # no 0, 1
    specials = "@#!%&*"                     # no $ (JSON/shell safe)
    all_chars = upper + lower + digits + specials

    import re as _re
    from app.utils.validators import validate_password_strength

    while True:
        # Fixed structure: guaranteed minimum from each class
        core = [
            secrets.choice(upper),
            secrets.choice(upper),
            secrets.choice(lower),
            secrets.choice(lower),
            secrets.choice(digits),
            secrets.choice(digits),
            secrets.choice(specials),
        ]
        # Fill remaining 5 chars from full pool
        rest = [secrets.choice(all_chars) for _ in range(5)]
        chars = core + rest

        # Fisher-Yates shuffle
        for i in range(len(chars) - 1, 0, -1):
            j = secrets.randbelow(i + 1)
            chars[i], chars[j] = chars[j], chars[i]

        password = "".join(chars)

        # Reject if repeating-char pattern triggers the validator (4+ same chars in row)
        if _re.search(r"(.)\1{3,}", password):
            continue

        # Final safety net: run through the actual validator — retry on any failure
        try:
            validate_password_strength(password)
            return password
        except ValueError:
            continue


# ---------------------------------------------------------------------------
# Employee ID generation
# ---------------------------------------------------------------------------


async def generate_employee_id(session: AsyncSession) -> str:
    """Generate the next sequential employee ID in EMP-YYYYMM-NNNN format.

    Queries the employees table for the latest ID with the current year-month
    prefix and increments the sequence. Thread-safe within a single transaction.
    """
    from app.models.employee import Employee  # local import avoids circular deps

    year_month = datetime.now(timezone.utc).strftime("%Y%m")
    prefix = f"EMP-{year_month}-"

    # Use MAX on the numeric suffix to avoid alphabetical ordering bugs, bypassing tenant filter for a global check
    from sqlalchemy import func, cast, Integer
    result = await session.execute(
        select(
            func.max(
                cast(
                    func.regexp_replace(Employee.employee_id, r"^EMP-\d{6}-", ""),
                    Integer
                )
            )
        ).where(
            Employee.employee_id.like(prefix + "%"),
            Employee.employee_id.regexp_match(r"^EMP-\d{6}-\d+$"),
        ).execution_options(bypass_tenant=True)
    )
    max_seq = result.scalar_one_or_none()
    seq = (max_seq or 0) + 1

    while True:
        employee_id = f"{prefix}{seq:04d}"
        # Verify the generated ID doesn't already exist globally
        check_res = await session.execute(
            select(Employee.employee_id)
            .where(Employee.employee_id == employee_id)
            .execution_options(bypass_tenant=True, populate_existing=True)
        )
        if not check_res.scalar_one_or_none():
            break
        seq += 1

    logger.debug(
        "generate_employee_id: generated %s | file=employee.py | func=generate_employee_id",
        employee_id,
    )
    return employee_id


# ---------------------------------------------------------------------------
# Company email generation
# ---------------------------------------------------------------------------


def _sanitize_name_part(name: str) -> str:
    """Convert a name part to a lowercase email-safe slug."""
    sanitized = re.sub(r"[^a-z0-9]", "", name.lower().strip())
    return sanitized or "user"


async def generate_company_email(
    first_name: str,
    last_name: str,
    domain: str,
    session: AsyncSession,
) -> str:
    """Generate a unique company email, appending a numeric suffix on collision.

    Format: firstname.lastname@domain (or firstname.lastname1@domain etc.)
    """
    from app.models.employee import Employee  # local import avoids circular deps

    first = _sanitize_name_part(first_name)
    last = _sanitize_name_part(last_name)
    base_local = f"{first}.{last}"

    for suffix in [""] + [str(i) for i in range(1, 100)]:
        candidate = f"{base_local}{suffix}@{domain}"
        result = await session.execute(
            select(Employee.company_email).where(Employee.company_email == candidate)
        )
        if result.scalar_one_or_none() is None:
            logger.debug(
                "generate_company_email: allocated %s | file=employee.py | func=generate_company_email",
                candidate,
            )
            return candidate

    # Extremely unlikely fallback
    fallback = f"{base_local}.{uuid.uuid4().hex[:6]}@{domain}"
    logger.warning(
        "generate_company_email: collision exhausted, using fallback %s | file=employee.py",
        fallback,
    )
    return fallback
