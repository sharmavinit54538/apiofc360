"""Pure Decimal formatting, Indian currency grouping, words conversion, masking, and filename utilities for Payslips."""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

_ONES = (
    "",
    "One",
    "Two",
    "Three",
    "Four",
    "Five",
    "Six",
    "Seven",
    "Eight",
    "Nine",
    "Ten",
    "Eleven",
    "Twelve",
    "Thirteen",
    "Fourteen",
    "Fifteen",
    "Sixteen",
    "Seventeen",
    "Eighteen",
    "Nineteen",
)
_TENS = (
    "",
    "",
    "Twenty",
    "Thirty",
    "Forty",
    "Fifty",
    "Sixty",
    "Seventy",
    "Eighty",
    "Ninety",
)

_CURRENCY_SYMBOLS = {
    "INR": "₹",
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "AED": "AED ",
    "SGD": "S$",
}


def to_decimal(value: Any, default: str = "0.00") -> Decimal:
    """Safely convert any numeric input into a Decimal without float intermediate error."""
    if value is None or value == "":
        return Decimal(default)
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


def quantize_money(value: Any) -> Decimal:
    """Quantize a monetary value strictly to 2 decimal places using ROUND_HALF_UP."""
    return to_decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def to_paise_int(value: Any) -> int:
    """Convert rupee Decimal/string to exact integer paise."""
    return int((to_decimal(value) * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def paise_to_decimal(paise: int | Decimal | None) -> Decimal:
    """Convert integer paise cleanly to Decimal rupees (2 d.p.)."""
    return (to_decimal(paise or 0) / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def format_indian_number(amount: Any, *, include_decimals: bool = True) -> str:
    """Format a numeric amount using standard Indian digit grouping (e.g. 1,82,012.50)."""
    dec = quantize_money(amount)
    negative = dec < 0
    dec = abs(dec)
    fixed = f"{dec:.2f}"
    integer_part, decimal_part = fixed.split(".")

    if len(integer_part) <= 3:
        grouped = integer_part
    else:
        last_three = integer_part[-3:]
        remaining = integer_part[:-3]
        chunks: list[str] = []
        while len(remaining) > 2:
            chunks.append(remaining[-2:])
            remaining = remaining[:-2]
        if remaining:
            chunks.append(remaining)
        grouped = ",".join(reversed(chunks)) + "," + last_three

    result = f"{grouped}.{decimal_part}" if include_decimals else grouped
    return f"-{result}" if negative else result


def format_currency(amount: Any, currency: str = "INR", *, with_symbol: bool = True) -> str:
    """Format currency using Indian grouping for INR and international grouping otherwise."""
    code = str(currency or "INR").strip().upper()
    dec = quantize_money(amount)
    if code == "INR":
        formatted = format_indian_number(dec)
    else:
        negative = dec < 0
        formatted = f"{abs(dec):,.2f}"
        if negative:
            formatted = f"-{formatted}"

    if not with_symbol:
        return formatted
    sym = _CURRENCY_SYMBOLS.get(code, f"{code} ")
    if formatted.startswith("-"):
        return f"-{sym}{formatted[1:]}"
    return f"{sym}{formatted}"


def _two_digits_to_words(n: int) -> str:
    if n < 20:
        return _ONES[n]
    tens_word = _TENS[n // 10]
    ones_word = _ONES[n % 10]
    return f"{tens_word} {ones_word}".strip() if ones_word else tens_word


def _integer_indian_words(n: int) -> str:
    """Convert non-negative integer into Indian English numbering words (Crores/Lakhs/Thousands)."""
    if n == 0:
        return "Zero"

    parts: list[str] = []

    if n >= 10_000_000:
        crores = n // 10_000_000
        parts.append(f"{_integer_indian_words(crores)} Crore")
        n %= 10_000_000

    if n >= 100_000:
        lakhs = n // 100_000
        parts.append(f"{_two_digits_to_words(lakhs) if lakhs < 100 else _integer_indian_words(lakhs)} Lakh")
        n %= 100_000

    if n >= 1_000:
        thousands = n // 1_000
        parts.append(f"{_two_digits_to_words(thousands) if thousands < 100 else _integer_indian_words(thousands)} Thousand")
        n %= 1_000

    if n >= 100:
        hundreds = n // 100
        parts.append(f"{_ONES[hundreds]} Hundred")
        n %= 100

    if n > 0:
        parts.append(_two_digits_to_words(n))

    return " ".join(part for part in parts if part).strip()


def amount_in_words(amount: Any, currency: str = "INR") -> str:
    """Convert a Decimal amount into accurate legal currency words.

    Examples:
        Decimal('182012.50') -> 'Indian Rupees One Lakh Eighty-Two Thousand Twelve and Fifty Paise Only'
        Decimal('0.00') -> 'Indian Rupees Zero Only'
    """
    code = str(currency or "INR").strip().upper()
    dec = quantize_money(amount)
    negative = dec < 0
    dec = abs(dec)

    total_paise = int((dec * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    major = total_paise // 100
    minor = total_paise % 100

    # Format two-digit hyphenation consistently where standard English style reads nicely (e.g. Eighty-Two)
    major_words = _hyphenate_tens(_integer_indian_words(major))
    prefix = "Minus " if negative else ""

    if code == "INR":
        if major == 0 and minor == 0:
            return "Indian Rupees Zero Only"
        if major == 0 and minor > 0:
            return f"{prefix}{_hyphenate_tens(_two_digits_to_words(minor))} Paise Only"
        if minor > 0:
            minor_words = _hyphenate_tens(_two_digits_to_words(minor))
            return f"{prefix}Indian Rupees {major_words} and {minor_words} Paise Only"
        return f"{prefix}Indian Rupees {major_words} Only"

    unit_name = {
        "USD": ("US Dollars", "Cents"),
        "EUR": ("Euros", "Cents"),
        "GBP": ("British Pounds", "Pence"),
        "AED": ("UAE Dirhams", "Fils"),
        "SGD": ("Singapore Dollars", "Cents"),
    }.get(code, (code, "Subunits"))
    if minor > 0:
        minor_words = _hyphenate_tens(_two_digits_to_words(minor))
        return f"{prefix}{unit_name[0]} {major_words} and {minor_words} {unit_name[1]} Only"
    return f"{prefix}{unit_name[0]} {major_words} Only"


def _hyphenate_tens(text: str) -> str:
    return re.sub(
        r"\b(Twenty|Thirty|Forty|Fifty|Sixty|Seventy|Eighty|Ninety)\s+(One|Two|Three|Four|Five|Six|Seven|Eight|Nine)\b",
        r"\1-\2",
        text,
    )


def mask_account_number(account_number: str | None) -> str | None:
    """Return masked bank account number preserving only the last 4 digits (e.g. 'XXXXXXXXXX7890')."""
    if not account_number:
        return None
    clean = re.sub(r"\s+", "", str(account_number).strip())
    if not clean:
        return None
    if len(clean) <= 4:
        return "X" * len(clean)
    return ("X" * (len(clean) - 4)) + clean[-4:]


def mask_pan(pan: str | None) -> str | None:
    """Mask PAN retaining only the final 4 characters (e.g. 'XXXXXX321D'), None if missing."""
    if not pan:
        return None
    clean = re.sub(r"\s+", "", str(pan).strip().upper())
    if not clean:
        return None
    if len(clean) > 4:
        return ("X" * (len(clean) - 4)) + clean[-4:]
    return "XXXX"


def mask_uan(uan: str | None) -> str | None:
    """Mask 12-digit UAN preserving only the trailing 4 digits (e.g. 'XXXXXXXX4321')."""
    if not uan:
        return None
    clean = re.sub(r"\s+", "", str(uan).strip())
    if not clean:
        return None
    if len(clean) <= 4:
        return "X" * len(clean)
    return ("X" * (len(clean) - 4)) + clean[-4:]


def mask_pf_number(pf_number: str | None, *, enabled: bool = True) -> str | None:
    """Mask PF member identifier preserving establishment prefix/last 4 chars if privacy masking is enabled."""
    if not pf_number:
        return None
    clean = str(pf_number).strip()
    if not clean:
        return None
    if not enabled:
        return clean
    if "/" in clean:
        parts = clean.split("/")
        tail = parts[-1]
        masked_tail = ("X" * max(0, len(tail) - 4)) + tail[-4:] if len(tail) > 4 else tail
        return "/".join(parts[:-1] + [masked_tail])
    return mask_account_number(clean)


def sanitize_filename_part(value: str | None, fallback: str = "NA") -> str:
    """Sanitize a filename segment so paths and headers are strictly safe."""
    raw = str(value or "").strip()
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", raw).strip("._-")
    return cleaned[:64] or fallback


def build_payslip_filename(employee_code: str | None, month: int, year: int, payslip_number: str | None = None) -> str:
    """Build sanitized corporate download filename e.g. 'Payslip_EMP001_November_2026.pdf'."""
    import calendar

    code = sanitize_filename_part(employee_code or payslip_number, fallback="EMP")
    month_name = calendar.month_name[max(1, min(12, int(month)))]
    return f"Payslip_{code}_{month_name}_{int(year)}.pdf"
