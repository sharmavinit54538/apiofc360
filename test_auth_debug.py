#!/usr/bin/env python3
"""
Auth Debug Test Script - Tests auth logic with mocked database
to identify exact root causes of 401/422/500 errors.
"""

import asyncio
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.schemas.auth import (
    LoginRequest, RegisterRequest, ForgotPasswordRequest,
    VerifyEmailRequest, ResendOTPRequest, VerifyResetOTPRequest,
    ResetPasswordRequest, ChangePasswordRequest
)
from app.services.auth_service import AuthService
from app.core.security import hash_password, verify_password
from app.models.user import User, UserRole, UserAccountStatus
from app.models.company import Company
from app.models.employee import Employee
from app.core.exceptions import AppException, ConflictException


async def test_login_user_not_found():
    """Test login with non-existent user returns 401."""
    print("\n=== TEST: Login - User Not Found ===")
    
    mock_session = AsyncMock()
    mock_repo = AsyncMock()
    mock_email_svc = AsyncMock()
    mock_token_svc = AsyncMock()
    
    # User not found
    mock_repo.get_user_by_identifier.return_value = None
    
    service = AuthService(
        session=mock_session,
        auth_repository=mock_repo,
        email_service=mock_email_svc,
        token_service=mock_token_svc,
    )
    
    payload = LoginRequest(identifier="nonexistent@example.com", password="Password@123")
    
    try:
        await service.login(payload, ip_address="127.0.0.1", device="test")
        print("FAIL: Should have raised AppException")
        return False
    except AppException as e:
        print(f"Status: {e.status_code}")
        print(f"Message: {e.message}")
        if e.status_code == 401 and "Invalid email or password" in e.message:
            print("PASS: Correctly returns 401 for non-existent user")
            return True
        else:
            print(f"FAIL: Expected 401, got {e.status_code}")
            return False
    except Exception as e:
        print(f"FAIL: Unexpected exception: {type(e).__name__}: {e}")
        return False


async def test_login_wrong_password():
    """Test login with wrong password returns 401."""
    print("\n=== TEST: Login - Wrong Password ===")
    
    mock_session = AsyncMock()
    mock_repo = AsyncMock()
    mock_email_svc = AsyncMock()
    mock_token_svc = AsyncMock()
    
    # User exists
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.email = "test@example.com"
    user.password_hash = hash_password("CorrectPassword@123")
    user.is_verified = True
    user.is_active = True
    user.account_status = "ACTIVE"
    user.role = UserRole.HR_ADMIN
    user.company_id = uuid.uuid4()
    user.failed_login_attempts = 0
    user.locked_until = None
    
    mock_repo.get_user_by_identifier.return_value = user
    
    service = AuthService(
        session=mock_session,
        auth_repository=mock_repo,
        email_service=mock_email_svc,
        token_service=mock_token_svc,
    )
    
    payload = LoginRequest(identifier="test@example.com", password="WrongPassword@123")
    
    try:
        await service.login(payload, ip_address="127.0.0.1", device="test")
        print("FAIL: Should have raised AppException")
        return False
    except AppException as e:
        print(f"Status: {e.status_code}")
        print(f"Message: {e.message}")
        if e.status_code == 401 and "Invalid email or password" in e.message:
            print("PASS: Correctly returns 401 for wrong password")
            return True
        else:
            print(f"FAIL: Expected 401, got {e.status_code}")
            return False
    except Exception as e:
        print(f"FAIL: Unexpected exception: {type(e).__name__}: {e}")
        return False


async def test_login_unverified_user():
    """Test login with unverified user returns 403."""
    print("\n=== TEST: Login - Unverified User ===")
    
    mock_session = AsyncMock()
    mock_repo = AsyncMock()
    mock_email_svc = AsyncMock()
    mock_token_svc = AsyncMock()
    
    # User exists but not verified
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.email = "test@example.com"
    user.password_hash = hash_password("CorrectPassword@123")
    user.is_verified = False
    user.is_active = True
    user.account_status = "PENDING_EMAIL_VERIFICATION"
    user.role = UserRole.HR_ADMIN
    user.company_id = uuid.uuid4()
    user.failed_login_attempts = 0
    user.locked_until = None
    
    mock_repo.get_user_by_identifier.return_value = user
    
    service = AuthService(
        session=mock_session,
        auth_repository=mock_repo,
        email_service=mock_email_svc,
        token_service=mock_token_svc,
    )
    
    payload = LoginRequest(identifier="test@example.com", password="CorrectPassword@123")
    
    try:
        await service.login(payload, ip_address="127.0.0.1", device="test")
        print("FAIL: Should have raised AppException")
        return False
    except AppException as e:
        print(f"Status: {e.status_code}")
        print(f"Message: {e.message}")
        print(f"Errors: {e.errors}")
        if e.status_code == 403 and "EMAIL_NOT_VERIFIED" in str(e.errors):
            print("PASS: Correctly returns 403 for unverified user")
            return True
        else:
            print(f"FAIL: Expected 403 with EMAIL_NOT_VERIFIED, got {e.status_code}")
            return False
    except Exception as e:
        print(f"FAIL: Unexpected exception: {type(e).__name__}: {e}")
        return False


async def test_login_inactive_user():
    """Test login with inactive user returns 403."""
    print("\n=== TEST: Login - Inactive User ===")
    
    mock_session = AsyncMock()
    mock_repo = AsyncMock()
    mock_email_svc = AsyncMock()
    mock_token_svc = AsyncMock()
    
    # User exists but inactive
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.email = "test@example.com"
    user.password_hash = hash_password("CorrectPassword@123")
    user.is_verified = True
    user.is_active = False
    user.account_status = "SUSPENDED"
    user.role = UserRole.HR_ADMIN
    user.company_id = uuid.uuid4()
    user.failed_login_attempts = 0
    user.locked_until = None
    
    mock_repo.get_user_by_identifier.return_value = user
    
    service = AuthService(
        session=mock_session,
        auth_repository=mock_repo,
        email_service=mock_email_svc,
        token_service=mock_token_svc,
    )
    
    payload = LoginRequest(identifier="test@example.com", password="CorrectPassword@123")
    
    try:
        await service.login(payload, ip_address="127.0.0.1", device="test")
        print("FAIL: Should have raised AppException")
        return False
    except AppException as e:
        print(f"Status: {e.status_code}")
        print(f"Message: {e.message}")
        print(f"Errors: {e.errors}")
        if e.status_code == 403 and "ACCOUNT_INACTIVE" in str(e.errors):
            print("PASS: Correctly returns 403 for inactive user")
            return True
        else:
            print(f"FAIL: Expected 403 with ACCOUNT_INACTIVE, got {e.status_code}")
            return False
    except Exception as e:
        print(f"FAIL: Unexpected exception: {type(e).__name__}: {e}")
        return False


async def test_register_valid_payload():
    """Test registration with valid payload including frontend aliases."""
    print("\n=== TEST: Register - Valid Payload with Frontend Aliases ===")
    
    # Test the schema validation with frontend payload
    frontend_payload = {
        "first_name": "John",
        "last_name": "Doe",
        "identifier": "john.doe@example.com",
        "phone": "9876543210",
        "password": "Password@123",
        "company_name": "Acme Corp",
        "role": "hr_admin"  # Should be ignored
    }
    
    try:
        req = RegisterRequest.model_validate(frontend_payload)
        print(f"Parsed name: {req.name}")
        print(f"Parsed email: {req.email}")
        print(f"Parsed phone: {req.phone}")
        print(f"Parsed company_name: {req.company_name}")
        print(f"Parsed password: {'*' * len(req.password)}")
        
        assert req.name == "John Doe", f"Expected 'John Doe', got '{req.name}'"
        assert req.email == "john.doe@example.com", f"Expected 'john.doe@example.com', got '{req.email}'"
        assert req.phone == "9876543210", f"Expected '9876543210', got '{req.phone}'"
        assert req.company_name == "Acme Corp", f"Expected 'Acme Corp', got '{req.company_name}'"
        
        print("PASS: Frontend payload correctly parsed with aliases")
        return True
    except Exception as e:
        print(f"FAIL: Schema validation failed: {type(e).__name__}: {e}")
        return False


async def test_register_missing_fields():
    """Test registration with missing required fields."""
    print("\n=== TEST: Register - Missing Required Fields ===")
    
    frontend_payload = {
        "first_name": "John",
        # missing last_name, identifier, phone, password, company_name
    }
    
    try:
        req = RegisterRequest.model_validate(frontend_payload)
        print(f"FAIL: Should have raised ValidationError, got: {req}")
        return False
    except Exception as e:
        print(f"ValidationError (expected): {type(e).__name__}")
        print("PASS: Correctly rejects missing required fields")
        return True


async def test_register_weak_password():
    """Test registration with weak password."""
    print("\n=== TEST: Register - Weak Password ===")
    
    frontend_payload = {
        "first_name": "John",
        "last_name": "Doe",
        "identifier": "john.doe@example.com",
        "phone": "9876543210",
        "password": "12345678",  # Weak - no special char, no uppercase
        "company_name": "Acme Corp",
    }
    
    try:
        req = RegisterRequest.model_validate(frontend_payload)
        print(f"FAIL: Should have raised ValidationError for weak password")
        return False
    except Exception as e:
        print(f"ValidationError (expected): {type(e).__name__}")
        print("PASS: Correctly rejects weak password")
        return True


async def test_register_duplicate_email():
    """Test registration with duplicate verified email."""
    print("\n=== TEST: Register - Duplicate Verified Email ===")
    
    mock_session = AsyncMock()
    mock_repo = AsyncMock()
    mock_email_svc = AsyncMock()
    mock_token_svc = AsyncMock()
    
    # Existing verified user
    existing_user = MagicMock(spec=User)
    existing_user.is_verified = True
    mock_repo.get_user_by_email.return_value = existing_user
    mock_repo.get_user_by_phone.return_value = None
    
    service = AuthService(
        session=mock_session,
        auth_repository=mock_repo,
        email_service=mock_email_svc,
        token_service=mock_token_svc,
    )
    
    payload = RegisterRequest(
        name="John Doe",
        email="existing@example.com",
        phone="9876543210",
        password="Password@123",
        company_name="Acme Corp"
    )
    
    try:
        await service.register_user(payload)
        print("FAIL: Should have raised ConflictException")
        return False
    except ConflictException as e:
        print(f"Status: {e.status_code}")
        print(f"Message: {e.message}")
        if e.status_code == 409 and "Email already exists" in e.message:
            print("PASS: Correctly returns 409 for duplicate verified email")
            return True
        else:
            print(f"FAIL: Expected 409, got {e.status_code}")
            return False
    except Exception as e:
        print(f"FAIL: Unexpected exception: {type(e).__name__}: {e}")
        return False


async def test_forgot_password_identifier_support():
    """Test forgot password with identifier (email or phone)."""
    print("\n=== TEST: Forgot Password - Identifier Support ===")
    
    # Check if ForgotPasswordRequest accepts identifier
    try:
        req = ForgotPasswordRequest(identifier="test@example.com")
        print(f"Schema accepts identifier: {req.identifier}")
        
        # Also test with phone
        req2 = ForgotPasswordRequest(identifier="9876543210")
        print(f"Schema accepts phone as identifier: {req2.identifier}")
        
        # Test backwards compatibility with email field
        req3 = ForgotPasswordRequest(email="test@example.com")
        print(f"Schema accepts email field (backwards compat): {req3.identifier}")
        
        print("PASS: ForgotPasswordRequest correctly accepts identifier alias")
        return True
    except Exception as e:
        print(f"FAIL: {type(e).__name__}: {e}")
        return False


async def test_forgot_password_with_email():
    """Test forgot password with email."""
    print("\n=== TEST: Forgot Password - With Email ===")
    
    mock_session = AsyncMock()
    mock_repo = AsyncMock()
    mock_email_svc = AsyncMock()
    mock_token_svc = AsyncMock()
    
    # User exists
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.email = "test@example.com"
    user.name = "Test User"
    user.role = UserRole.HR_ADMIN
    user.is_deleted = False
    
    mock_repo.get_user_by_email.return_value = user
    mock_repo.create_password_reset_token.return_value = MagicMock()
    
    service = AuthService(
        session=mock_session,
        auth_repository=mock_repo,
        email_service=mock_email_svc,
        token_service=mock_token_svc,
    )
    
    payload = ForgotPasswordRequest(email="test@example.com")
    
    try:
        await service.forgot_password(payload)
        print("PASS: Forgot password with email works")
        print(f"  create_password_reset_token called: {mock_repo.create_password_reset_token.called}")
        print(f"  send_password_reset_email called: {mock_email_svc.send_password_reset_email.called}")
        return True
    except Exception as e:
        print(f"FAIL: {type(e).__name__}: {e}")
        return False


async def test_verify_reset_otp_missing_method():
    """Check if verify_reset_otp method exists in AuthService."""
    print("\n=== TEST: Verify Reset OTP - Method Exists ===")
    
    mock_session = AsyncMock()
    mock_repo = AsyncMock()
    mock_email_svc = AsyncMock()
    mock_token_svc = AsyncMock()
    
    service = AuthService(
        session=mock_session,
        auth_repository=mock_repo,
        email_service=mock_email_svc,
        token_service=mock_token_svc,
    )
    
    if hasattr(service, 'verify_reset_otp'):
        print("PASS: verify_reset_otp method exists")
        return True
    else:
        print("FAIL: verify_reset_otp method MISSING from AuthService!")
        print("  This will cause 500 when frontend calls /verify-reset-otp")
        return False


async def test_reset_password_otp_vs_token():
    """Test reset password - check if backend uses token or OTP flow."""
    print("\n=== TEST: Reset Password - Flow Type ===")
    
    # Check ResetPasswordRequest schema supports both token and OTP
    try:
        # Test with reset_token (new flow)
        req = ResetPasswordRequest(
            email="test@example.com",
            reset_token="reset-token-from-verify-step",
            new_password="NewPassword@123",
            confirm_password="NewPassword@123"
        )
        print(f"Backend accepts reset_token flow:")
        print(f"  email: {req.email}")
        print(f"  reset_token: {req.reset_token}")
        print(f"  new_password: {'*' * len(req.new_password)}")
        
        # Test with OTP (backward compat flow)
        req2 = ResetPasswordRequest(
            email="test@example.com",
            otp="123456",
            new_password="NewPassword@123",
            confirm_password="NewPassword@123"
        )
        print(f"Backend accepts OTP flow (backward compat):")
        print(f"  email: {req2.email}")
        print(f"  otp: {req2.otp}")
        print(f"  new_password: {'*' * len(req2.new_password)}")
        
        print("PASS: ResetPasswordRequest supports both token and OTP flows")
        return True
    except Exception as e:
        print(f"FAIL: {type(e).__name__}: {e}")
        return False


async def test_logout_no_body():
    """Test logout with no body (frontend sends void)."""
    print("\n=== TEST: Logout - No Body Support ===")
    
    # Check if logout endpoint accepts optional body
    from app.schemas.auth import RefreshTokenRequest
    
    try:
        # Empty body
        req = RefreshTokenRequest.model_validate({})
        print(f"Empty body validation: refresh_token={req.refresh_token}")
        
        # With refresh_token
        req2 = RefreshTokenRequest.model_validate({"refresh_token": "token123"})
        print(f"With refresh_token: {req2.refresh_token}")
        
        # With refreshToken (camelCase)
        req3 = RefreshTokenRequest.model_validate({"refreshToken": "token123"})
        print(f"With refreshToken (camelCase): {req3.refresh_token}")
        
        print("PASS: RefreshTokenRequest accepts optional refresh_token")
        return True
    except Exception as e:
        print(f"FAIL: {type(e).__name__}: {e}")
        return False


async def run_all_tests():
    """Run all auth tests and report results."""
    print("=" * 60)
    print("AUTH DEBUG TEST SUITE")
    print("=" * 60)
    
    tests = [
        ("Login - User Not Found", test_login_user_not_found),
        ("Login - Wrong Password", test_login_wrong_password),
        ("Login - Unverified User", test_login_unverified_user),
        ("Login - Inactive User", test_login_inactive_user),
        ("Register - Valid Frontend Payload", test_register_valid_payload),
        ("Register - Missing Fields", test_register_missing_fields),
        ("Register - Weak Password", test_register_weak_password),
        ("Register - Duplicate Email", test_register_duplicate_email),
        ("Forgot Password - Identifier Support", test_forgot_password_identifier_support),
        ("Forgot Password - With Email", test_forgot_password_with_email),
        ("Verify Reset OTP - Method Exists", test_verify_reset_otp_missing_method),
        ("Reset Password - OTP vs Token Flow", test_reset_password_otp_vs_token),
        ("Logout - No Body", test_logout_no_body),
    ]
    
    results = {}
    for name, test_func in tests:
        try:
            result = await test_func()
            results[name] = result
        except Exception as e:
            print(f"\nERROR in {name}: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            results[name] = False
    
    print("\n" + "=" * 60)
    print("TEST RESULTS SUMMARY")
    print("=" * 60)
    
    passed = sum(1 for v in results.values() if v)
    failed = sum(1 for v in results.values() if not v)
    
    for name, result in results.items():
        status = "PASS" if result else "FAIL"
        print(f"  {status}: {name}")
    
    print(f"\nTotal: {len(results)} | Passed: {passed} | Failed: {failed}")
    
    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)