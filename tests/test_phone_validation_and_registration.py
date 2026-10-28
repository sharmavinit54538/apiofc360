"""Unit and integration tests for phone number validation and registration flow."""

import pytest
from pydantic import ValidationError
from unittest.mock import AsyncMock, MagicMock, patch

from app.utils.validators import validate_phone
from app.schemas.auth import RegisterRequest, ChangePhoneRequest, LoginRequest
from app.core.exceptions import ConflictException
from app.services.auth_service import AuthService
from app.models.user import User


# ============================================================================
# 1. validate_phone Unit Tests
# ============================================================================

def test_validate_phone_valid_10_digit():
    """Test standard 10-digit Indian mobile numbers starting with 6, 7, 8, 9."""
    assert validate_phone("9876543210") == "9876543210"
    assert validate_phone("8123456789") == "8123456789"
    assert validate_phone("7000000000") == "7000000000"
    assert validate_phone("6999999999") == "6999999999"


def test_validate_phone_with_plus_91_prefix():
    """Test phone numbers with +91 country code prefix."""
    assert validate_phone("+919876543210") == "9876543210"
    assert validate_phone("+91 9876543210") == "9876543210"
    assert validate_phone("+91-9876543210") == "9876543210"
    assert validate_phone("+91 (987) 654-3210") == "9876543210"


def test_validate_phone_with_91_prefix():
    """Test 12-digit numbers starting with 91."""
    assert validate_phone("919876543210") == "9876543210"
    assert validate_phone("91 9876543210") == "9876543210"


def test_validate_phone_with_leading_zero():
    """Test 11-digit numbers with trunk prefix 0."""
    assert validate_phone("09876543210") == "9876543210"


def test_validate_phone_integer_coercion():
    """Test phone number passed as an integer."""
    assert validate_phone(9876543210) == "9876543210"


def test_validate_phone_invalid_starting_digit():
    """Test phone numbers not starting with 6, 7, 8, or 9."""
    for invalid in ["1234567890", "2345678901", "3456789012", "4567890123", "5678901234"]:
        with pytest.raises(ValueError, match="valid 10-digit Indian mobile number"):
            validate_phone(invalid)


def test_validate_phone_invalid_length():
    """Test phone numbers that are too short or too long."""
    with pytest.raises(ValueError, match="valid 10-digit Indian mobile number"):
        validate_phone("987654321")  # 9 digits
    with pytest.raises(ValueError, match="valid 10-digit Indian mobile number"):
        validate_phone("987654321000")  # 12 digits (not 91 prefix)


def test_validate_phone_invalid_characters():
    """Test phone numbers with letters or symbols."""
    with pytest.raises(ValueError, match="valid 10-digit Indian mobile number"):
        validate_phone("abcdefghij")
    with pytest.raises(ValueError, match="valid 10-digit Indian mobile number"):
        validate_phone("98765abc10")


def test_validate_phone_empty_or_none():
    """Test empty string and None."""
    with pytest.raises(ValueError, match="Phone is required"):
        validate_phone("")
    with pytest.raises(ValueError, match="Phone is required"):
        validate_phone("   ")
    with pytest.raises(ValueError, match="Phone is required"):
        validate_phone(None)


# ============================================================================
# 2. RegisterRequest Pydantic Schema Tests
# ============================================================================

def test_register_request_canonical_payload():
    """Test RegisterRequest with canonical fields (name, phone)."""
    payload = {
        "name": "Vinit Sharma",
        "email": "vinit@example.com",
        "phone": "9876543210",
        "password": "StrongPassword@123",
        "company_name": "EquinoxSphere",
    }
    req = RegisterRequest.model_validate(payload)
    assert req.name == "Vinit Sharma"
    assert req.email == "vinit@example.com"
    assert req.phone == "9876543210"
    assert req.company_name == "EquinoxSphere"


def test_register_request_with_plus_91_phone():
    """Test RegisterRequest normalizes +91 phone to 10 digits."""
    payload = {
        "name": "Vinit Sharma",
        "email": "vinit@example.com",
        "phone": "+919876543210",
        "password": "StrongPassword@123",
        "company_name": "EquinoxSphere",
    }
    req = RegisterRequest.model_validate(payload)
    assert req.phone == "9876543210"


def test_register_request_with_phone_number_alias():
    """Test RegisterRequest supports 'phone_number' alias from frontend."""
    payload = {
        "first_name": "Vinit",
        "last_name": "Sharma",
        "email": "vinit@example.com",
        "phone_number": "9876543210",
        "password": "StrongPassword@123",
        "company_name": "EquinoxSphere",
    }
    req = RegisterRequest.model_validate(payload)
    assert req.name == "Vinit Sharma"
    assert req.phone == "9876543210"


def test_register_request_with_integer_phone():
    """Test RegisterRequest supports phone passed as integer."""
    payload = {
        "name": "Vinit Sharma",
        "email": "vinit@example.com",
        "phone": 9876543210,
        "password": "StrongPassword@123",
        "company_name": "EquinoxSphere",
    }
    req = RegisterRequest.model_validate(payload)
    assert req.phone == "9876543210"


def test_register_request_missing_phone_raises_422():
    """Test RegisterRequest raises validation error when phone is missing."""
    payload = {
        "name": "Vinit Sharma",
        "email": "vinit@example.com",
        "password": "StrongPassword@123",
        "company_name": "EquinoxSphere",
    }
    with pytest.raises(ValidationError) as exc_info:
        RegisterRequest.model_validate(payload)
    errors = exc_info.value.errors()
    assert any("phone" in str(e.get("loc", ())) for e in errors)


def test_register_request_invalid_phone_raises_clear_error():
    """Test RegisterRequest raises clear validation message for invalid phone."""
    payload = {
        "name": "Vinit Sharma",
        "email": "vinit@example.com",
        "phone": "1234567890",
        "password": "StrongPassword@123",
        "company_name": "EquinoxSphere",
    }
    with pytest.raises(ValidationError) as exc_info:
        RegisterRequest.model_validate(payload)
    errors = exc_info.value.errors()
    assert any("valid 10-digit Indian mobile number" in str(e.get("msg", "")) for e in errors)


# ============================================================================
# 3. ChangePhoneRequest & LoginRequest Schema Tests
# ============================================================================

def test_change_phone_request_supports_plus_91():
    """Test ChangePhoneRequest normalizes phone number."""
    req = ChangePhoneRequest.model_validate({"phone": "+919876543210", "password": "Password@123"})
    assert req.phone == "9876543210"


def test_login_request_supports_phone_alias():
    """Test LoginRequest accepts identifier, email, phone, or phone_number."""
    req1 = LoginRequest.model_validate({"identifier": "9876543210", "password": "Password@123"})
    assert req1.identifier == "9876543210"

    req2 = LoginRequest.model_validate({"phone": "9876543210", "password": "Password@123"})
    assert req2.identifier == "9876543210"

    req3 = LoginRequest.model_validate({"phone_number": "9876543210", "password": "Password@123"})
    assert req3.identifier == "9876543210"


# ============================================================================
# 4. Duplicate Email and Phone Conflict Tests in AuthService
# ============================================================================

@pytest.mark.asyncio(loop_scope="session")
async def test_auth_service_duplicate_email_conflict():
    """Test AuthService raises ConflictException when email is already registered and verified."""
    mock_session = AsyncMock()
    mock_repo = AsyncMock()
    mock_email_svc = AsyncMock()
    mock_token_svc = AsyncMock()

    # User exists and is verified
    mock_existing = MagicMock()
    mock_existing.is_verified = True
    mock_repo.get_user_by_email.return_value = mock_existing

    service = AuthService(
        session=mock_session,
        auth_repository=mock_repo,
        email_service=mock_email_svc,
        token_service=mock_token_svc,
    )

    payload = RegisterRequest.model_validate({
        "name": "Vinit Sharma",
        "email": "duplicate@example.com",
        "phone": "9876543210",
        "password": "StrongPassword@123",
        "company_name": "EquinoxSphere",
    })

    with pytest.raises(ConflictException, match="Email already exists"):
        await service.register_user(payload)


@pytest.mark.asyncio(loop_scope="session")
async def test_auth_service_duplicate_phone_conflict():
    """Test AuthService raises ConflictException when phone is already registered and verified."""
    mock_session = AsyncMock()
    mock_repo = AsyncMock()
    mock_email_svc = AsyncMock()
    mock_token_svc = AsyncMock()

    # Email does not exist, but phone exists and is verified
    mock_repo.get_user_by_email.return_value = None
    mock_existing_phone = MagicMock()
    mock_existing_phone.is_verified = True
    mock_repo.get_user_by_phone.return_value = mock_existing_phone

    service = AuthService(
        session=mock_session,
        auth_repository=mock_repo,
        email_service=mock_email_svc,
        token_service=mock_token_svc,
    )

    payload = RegisterRequest.model_validate({
        "name": "Vinit Sharma",
        "email": "newemail@example.com",
        "phone": "+919876543210",
        "password": "StrongPassword@123",
        "company_name": "EquinoxSphere",
    })

    with pytest.raises(ConflictException, match="Phone already exists"):
        await service.register_user(payload)
