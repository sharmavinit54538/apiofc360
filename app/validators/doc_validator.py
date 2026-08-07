"""Verification validator class for structured business documents.

Implements rule-based validation logic:
- Aadhaar card checksum using Verhoeff algorithm
- Permanent Account Number (PAN) pattern checks
- Goods and Services Tax Identification Number (GSTIN) checks
- Date integrity checks (issue vs expiry)
- Email & Mobile pattern checking
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, date

logger = logging.getLogger(__name__)

# Verhoeff Algorithm Tables
_VERHOEFF_D = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
    [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
    [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
    [4, 0, 1, 2, 3, 9, 5, 6, 7, 8],
    [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
    [6, 5, 9, 8, 7, 1, 0, 4, 3, 2],
    [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
    [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
    [9, 8, 7, 6, 5, 4, 3, 2, 1, 0]
]

_VERHOEFF_P = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
    [5, 8, 0, 3, 7, 9, 1, 4, 6, 2],
    [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
    [9, 4, 5, 3, 1, 2, 6, 8, 7, 0],
    [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
    [2, 7, 9, 3, 8, 0, 6, 4, 1, 5],
    [7, 0, 4, 6, 9, 1, 3, 2, 5, 8]
]

_VERHOEFF_INV = [0, 4, 3, 2, 1, 5, 6, 7, 8, 9]


def validate_verhoeff(num: str) -> bool:
    """Validate standard Verhoeff checksum (used for Aadhaar)."""
    if not num.isdigit():
        return False
    
    # Reverse number string to compute checksum
    digits = list(map(int, reversed(num)))
    c = 0
    for i, digit in enumerate(digits):
        c = _VERHOEFF_D[c][_VERHOEFF_P[i % 8][digit]]
    return c == 0


class DocumentValidator:
    """Validation utility containing rule sets for multiple ID and tax formats."""

    @staticmethod
    def validate_aadhaar(aadhaar: str) -> dict[str, bool | str]:
        """Validate 12-digit Aadhaar number using Verhoeff check."""
        clean_aadhaar = str(aadhaar).replace(" ", "").replace("-", "")
        if not re.match(r"^[2-9][0-9]{11}$", clean_aadhaar):
            return {"valid": False, "error": "Aadhaar must be 12 digits and cannot start with 0 or 1"}
        
        is_valid = validate_verhoeff(clean_aadhaar)
        return {
            "valid": is_valid,
            "error": "" if is_valid else "Aadhaar failed checksum validation"
        }

    @staticmethod
    def validate_pan(pan: str) -> dict[str, bool | str]:
        """Validate Indian PAN format (e.g. ABCDE1234F)."""
        clean_pan = str(pan).strip().upper()
        if not re.match(r"^[A-Z]{5}[0-9]{4}[A-Z]$", clean_pan):
            return {"valid": False, "error": "PAN must match standard format (5 letters, 4 numbers, 1 letter)"}
        
        # Fourth character represents status of holder:
        # P - Individual, C - Company, H - HUF, A - AOP, B - BOI, F - Firm, G - Govt, J - Artificial Judicial, L - Local, T - Trust
        fourth_char = clean_pan[3]
        valid_status_chars = {"P", "C", "H", "A", "B", "F", "G", "J", "L", "T"}
        if fourth_char not in valid_status_chars:
            logger.warning("PAN holder status '%s' is non-standard but format is valid", fourth_char)

        return {"valid": True, "error": ""}

    @staticmethod
    def validate_gstin(gst: str) -> dict[str, bool | str]:
        """Validate Indian GST Identification Number."""
        clean_gst = str(gst).strip().upper()
        # Format: 2 digits state code, 10 characters PAN, 1 digit entity number, 1 character 'Z', 1 character check-digit
        if not re.match(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$", clean_gst):
            return {"valid": False, "error": "GSTIN must match standard 15-character format"}
        
        # Cross check PAN embedded in GSTIN
        pan_part = clean_gst[2:12]
        pan_val = DocumentValidator.validate_pan(pan_part)
        if not pan_val["valid"]:
            return {"valid": False, "error": f"GSTIN contains invalid PAN structure: {pan_val['error']}"}

        return {"valid": True, "error": ""}

    @staticmethod
    def validate_email(email: str) -> dict[str, bool | str]:
        clean_email = str(email).strip().lower()
        if not re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", clean_email):
            return {"valid": False, "error": "Invalid email address format"}
        return {"valid": True, "error": ""}

    @staticmethod
    def validate_phone(phone: str) -> dict[str, bool | str]:
        clean_phone = re.sub(r"[ \-\(\)\+]", "", str(phone))
        # Match standard phone length: 8 to 15 digits
        if not re.match(r"^[0-9]{8,15}$", clean_phone):
            return {"valid": False, "error": "Phone number must be between 8 and 15 digits"}
        return {"valid": True, "error": ""}

    @staticmethod
    def validate_dates(issue_date_str: str | None, expiry_date_str: str | None) -> dict[str, bool | str]:
        """Ensure issue date is in the past and expiry date is in the future relative to issue."""
        if not issue_date_str and not expiry_date_str:
            return {"valid": True, "error": ""}

        def parse_date(d_str: str) -> date | None:
            for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d"):
                try:
                    return datetime.strptime(d_str, fmt).date()
                except ValueError:
                    continue
            return None

        issue_d = parse_date(issue_date_str) if issue_date_str else None
        expiry_d = parse_date(expiry_date_str) if expiry_date_str else None

        if issue_date_str and not issue_d:
            return {"valid": False, "error": f"Invalid issue date format: {issue_date_str}"}
        if expiry_date_str and not expiry_d:
            return {"valid": False, "error": f"Invalid expiry date format: {expiry_date_str}"}

        if issue_d and issue_d > date.today():
            return {"valid": False, "error": "Issue date cannot be in the future"}

        if issue_d and expiry_d and expiry_d < issue_d:
            return {"valid": False, "error": "Expiry date must be after the issue date"}

        return {"valid": True, "error": ""}

    @classmethod
    def validate_extracted_fields(cls, doc_type: str, data: dict) -> dict[str, dict]:
        """Run all matching checks on extracted fields based on document type."""
        results: dict[str, dict] = {}
        dtype = doc_type.upper()

        # Aadhaar specific
        if dtype == "AADHAAR" and "aadhaar_number" in data:
            results["aadhaar_number"] = cls.validate_aadhaar(data["aadhaar_number"])
        
        # PAN specific
        if dtype == "PAN_CARD" and "pan_number" in data:
            results["pan_number"] = cls.validate_pan(data["pan_number"])

        # GST specific
        if dtype == "GST_DOCUMENT" and "gstin" in data:
            results["gstin"] = cls.validate_gstin(data["gstin"])
        elif "gst_number" in data and data["gst_number"]:
            results["gst_number"] = cls.validate_gstin(data["gst_number"])

        # Date validations
        if "issue_date" in data or "expiry_date" in data:
            results["date_integrity"] = cls.validate_dates(
                data.get("issue_date"),
                data.get("expiry_date")
            )

        # Phone/Email validation
        if "email" in data and data["email"]:
            results["email"] = cls.validate_email(data["email"])
        if "phone" in data and data["phone"]:
            results["phone"] = cls.validate_phone(data["phone"])
        elif "mobile" in data and data["mobile"]:
            results["mobile"] = cls.validate_phone(data["mobile"])

        return results
