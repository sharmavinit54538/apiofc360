"""Authentication API routes."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, status

from app.middleware.auth import get_current_user_claims, get_current_user_claims_optional
from app.schemas.auth import (
    APIResponse,
    ChangeEmailRequest,
    ChangePasswordRequest,
    ChangePhoneRequest,
    ForgotPasswordRequest,
    GoogleAuthRequest,
    LoginRequest,
    LoginResponse,
    LoginResponseData,
    RegisterRequest,
    RegisterResponse,
    RefreshTokenRequest,
    RefreshTokenResponse,
    RefreshTokenResponseData,
    ResendOTPRequest,
    ResendOTPResponse,
    ResetPasswordRequest,
    UserLoginPublic,
    UserProfileData,
    UserProfileResponse,
    VerifyEmailRequest,
    VerifyEmailResponse,
    VerifyNewEmailRequest,
    VerifyResetOTPRequest,
    VerifyResetOTPResponse,
)
from app.services.account_service import AccountService, get_account_service
from app.services.auth_service import AuthService, get_auth_service
from app.services.token_service import TokenService, get_token_service
from app.core.rate_limiter import (
    check_forgot_password_rate_limit,
    check_login_rate_limit,
    check_otp_rate_limit,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    response_model=RegisterResponse,
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": APIResponse[None], "description": "Validation failed"},
        status.HTTP_409_CONFLICT: {"model": APIResponse[None], "description": "Email or phone already exists"},
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"model": APIResponse[None], "description": "Invalid input"},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": APIResponse[None], "description": "Internal server error"},
    },
)
async def register_user(
    payload: RegisterRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> RegisterResponse:
    """Register a new user account."""

    await auth_service.register_user(payload)
    return RegisterResponse(
        success=True,
        message="Registration successful. Welcome to HRMS!",
        data=None,
        errors=None,
    )


@router.post(
    "/verify-email",
    status_code=status.HTTP_200_OK,
    response_model=VerifyEmailResponse,
    dependencies=[Depends(check_otp_rate_limit)],
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": APIResponse[None], "description": "Verification failed"},
        status.HTTP_404_NOT_FOUND: {"model": APIResponse[None], "description": "User not found"},
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"model": APIResponse[None], "description": "Invalid input"},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": APIResponse[None], "description": "Internal server error"},
    },
)
async def verify_email(
    payload: VerifyEmailRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> VerifyEmailResponse:
    """Verify email address using OTP code."""

    await auth_service.verify_email(payload)
    return VerifyEmailResponse(
        success=True,
        message="Email verified successfully.",
        data=None,
        errors=None,
    )


@router.post(
    "/resend-verification",
    status_code=status.HTTP_200_OK,
    response_model=ResendOTPResponse,
    dependencies=[Depends(check_otp_rate_limit)],
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": APIResponse[None], "description": "Resend failed"},
        status.HTTP_404_NOT_FOUND: {"model": APIResponse[None], "description": "User not found"},
        status.HTTP_429_TOO_MANY_REQUESTS: {"model": APIResponse[None], "description": "Too many requests"},
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"model": APIResponse[None], "description": "Invalid input"},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": APIResponse[None], "description": "Internal server error"},
    },
)
@router.post(
    "/resend-otp",
    status_code=status.HTTP_200_OK,
    response_model=ResendOTPResponse,
    dependencies=[Depends(check_otp_rate_limit)],
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": APIResponse[None], "description": "Resend failed"},
        status.HTTP_404_NOT_FOUND: {"model": APIResponse[None], "description": "User not found"},
        status.HTTP_429_TOO_MANY_REQUESTS: {"model": APIResponse[None], "description": "Too many requests"},
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"model": APIResponse[None], "description": "Invalid input"},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": APIResponse[None], "description": "Internal server error"},
    },
)
async def resend_otp(
    payload: ResendOTPRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> ResendOTPResponse:
    """Request a new email verification link and OTP code."""

    await auth_service.resend_otp(payload)
    return ResendOTPResponse(
        success=True,
        message="OTP sent successfully.",
        data=None,
        errors=None,
    )


@router.post(
    "/login",
    status_code=status.HTTP_200_OK,
    response_model=LoginResponse,
    dependencies=[Depends(check_login_rate_limit)],
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": APIResponse[None], "description": "Login failed"},
        status.HTTP_401_UNAUTHORIZED: {"model": APIResponse[None], "description": "Invalid credentials"},
        status.HTTP_429_TOO_MANY_REQUESTS: {"model": APIResponse[None], "description": "Too many requests"},
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"model": APIResponse[None], "description": "Invalid input"},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": APIResponse[None], "description": "Internal server error"},
    },
)
async def login(
    payload: LoginRequest,
    request: Request,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> LoginResponse:
    """Verify credentials and issue access and refresh tokens."""

    ip_address = request.client.host if request.client else None
    device = request.headers.get("User-Agent")

    user, access_token, refresh_token, expires_in = await auth_service.login(
        payload=payload,
        ip_address=ip_address,
        device=device,
    )

    effective_role = user.role.value if hasattr(user.role, "value") else str(user.role)
    user_role_str = str(effective_role).lower()

    # Sync onboarding_completed flag safely
    if user_role_str == "super_admin":
        onboarding_completed = True
    elif user_role_str == "hr_admin":
        if getattr(user, "company", None) and getattr(user.company, "onboarding_completed", False) and not user.onboarding_completed:
            try:
                user.onboarding_completed = True
                user.onboarding_step = 7
                auth_service.session.add(user)
                await auth_service.session.commit()
            except Exception as err:
                logger.warning("Failed to sync admin onboarding status: %s", err)
        onboarding_completed = bool(user.onboarding_completed)
    elif user_role_str == "employee":
        onboarding_completed = bool(user.onboarding_completed)
        try:
            from sqlalchemy import select
            from app.models.employee import Employee
            stmt = select(Employee).where(
                (Employee.user_id == user.id) |
                (Employee.personal_email == user.email.lower().strip()) |
                (Employee.company_email == user.email.lower().strip())
            ).execution_options(bypass_tenant=True)
            emp_res = await auth_service.session.execute(stmt)
            emp = emp_res.scalars().first()
            if emp and hasattr(emp, "employee_onboarding_completed"):
                onboarding_completed = bool(emp.employee_onboarding_completed)
        except Exception as err:
            logger.warning("Failed to check employee onboarding status: %s", err)
    else:
        onboarding_completed = bool(user.onboarding_completed)

    # Safely resolve company name without triggering lazy-load errors
    company_name = None
    if getattr(user, "company", None):
        try:
            company_name = user.company.name
        except Exception:
            company_name = None

    if not company_name and user.company_id:
        try:
            from sqlalchemy import select
            from app.models.company import Company
            comp_res = await auth_service.session.execute(
                select(Company.name).where(Company.id == user.company_id).execution_options(bypass_tenant=True)
            )
            company_name = comp_res.scalar_one_or_none()
        except Exception:
            company_name = None

    user_data = UserLoginPublic(
        id=user.id,
        name=user.name or "User",
        email=user.email,
        phone=user.phone or None,
        role=effective_role,
        is_verified=bool(user.is_verified),
        email_verified=bool(user.is_verified),
        account_status=str(getattr(user, "account_status", "ACTIVE") or "ACTIVE"),
        must_change_password=bool(getattr(user, "must_change_password", False)),
        onboarding_completed=onboarding_completed,
        company_id=user.company_id,
        company_name=company_name,
    )

    return LoginResponse(
        success=True,
        message="Login successful.",
        data=LoginResponseData(
            user=user_data,
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="Bearer",
            expires_in=expires_in,
        ),
        errors=None,
    )


@router.post(
    "/google",
    status_code=status.HTTP_200_OK,
    response_model=LoginResponse,
    summary="Google SSO for Company Admin Only",
    dependencies=[Depends(check_login_rate_limit)],
    responses={
        status.HTTP_403_FORBIDDEN: {"model": APIResponse[None], "description": "Employees not allowed"},
        status.HTTP_404_NOT_FOUND: {"model": APIResponse[None], "description": "Admin user not found"},
    },
)
async def google_auth(
    payload: GoogleAuthRequest,
    request: Request,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> LoginResponse:
    """Authenticate a Company Admin via Google SSO (Strictly restricted to Company Admins)."""

    ip_address = request.client.host if request.client else None
    device = request.headers.get("User-Agent")

    user, access_token, refresh_token, expires_in = await auth_service.login_google(
        email=str(payload.email),
        name=payload.name,
        ip_address=ip_address,
        device=device,
    )

    effective_role = user.role.value if hasattr(user.role, "value") else str(user.role)

    # Safely resolve company name without triggering lazy-load errors
    company_name = None
    if getattr(user, "company", None):
        try:
            company_name = user.company.name
        except Exception:
            company_name = None

    if not company_name and user.company_id:
        try:
            from sqlalchemy import select
            from app.models.company import Company
            comp_res = await auth_service.session.execute(
                select(Company.name).where(Company.id == user.company_id).execution_options(bypass_tenant=True)
            )
            company_name = comp_res.scalar_one_or_none()
        except Exception:
            company_name = None

    user_data = UserLoginPublic(
        id=user.id,
        name=user.name or "User",
        email=user.email,
        phone=user.phone or None,
        role=effective_role,
        is_verified=bool(user.is_verified),
        email_verified=bool(user.is_verified),
        account_status=str(getattr(user, "account_status", "ACTIVE") or "ACTIVE"),
        must_change_password=bool(getattr(user, "must_change_password", False)),
        onboarding_completed=bool(getattr(user, "onboarding_completed", True)),
        company_id=user.company_id,
        company_name=company_name,
    )

    return LoginResponse(
        success=True,
        message="Google login successful.",
        data=LoginResponseData(
            user=user_data,
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="Bearer",
            expires_in=expires_in,
        ),
        errors=None,
    )



@router.post(
    "/refresh-token",
    status_code=status.HTTP_200_OK,
    response_model=RefreshTokenResponse,
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": APIResponse[None], "description": "Invalid or expired token"},
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"model": APIResponse[None], "description": "Invalid input"},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": APIResponse[None], "description": "Internal server error"},
    },
)
async def refresh_token(
    payload: RefreshTokenRequest,
    request: Request,
    token_service: Annotated[TokenService, Depends(get_token_service)],
) -> RefreshTokenResponse:
    """Rotate an active refresh token for a new access and refresh token pair."""

    ip_address = request.client.host if request.client else None
    device = request.headers.get("User-Agent")

    access_token, refresh_token, expires_in = await token_service.rotate_refresh_token(
        refresh_token=payload.refresh_token,
        ip_address=ip_address,
        device=device,
    )

    return RefreshTokenResponse(
        success=True,
        message="Token refreshed successfully.",
        data=RefreshTokenResponseData(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="Bearer",
            expires_in=expires_in,
        ),
        errors=None,
    )


@router.post(
    "/refresh",
    status_code=status.HTTP_200_OK,
    response_model=RefreshTokenResponse,
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": APIResponse[None], "description": "Invalid or expired token"},
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"model": APIResponse[None], "description": "Invalid input"},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": APIResponse[None], "description": "Internal server error"},
    },
)
async def refresh(
    payload: RefreshTokenRequest,
    request: Request,
    token_service: Annotated[TokenService, Depends(get_token_service)],
) -> RefreshTokenResponse:
    """Rotate an active refresh token for a new access and refresh token pair."""

    ip_address = request.client.host if request.client else None
    device = request.headers.get("User-Agent")

    access_token, refresh_token, expires_in = await token_service.rotate_refresh_token(
        refresh_token=payload.refresh_token,
        ip_address=ip_address,
        device=device,
    )

    return RefreshTokenResponse(
        success=True,
        message="Token refreshed successfully.",
        data=RefreshTokenResponseData(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="Bearer",
            expires_in=expires_in,
        ),
        errors=None,
    )


@router.post(
    "/logout",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[None],
    responses={
        status.HTTP_200_OK: {"model": APIResponse[None], "description": "Logged out successfully"},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": APIResponse[None], "description": "Internal server error"},
    },
)
async def logout(
    payload: RefreshTokenRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    claims: Annotated[dict | None, Depends(get_current_user_claims_optional)] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> APIResponse[None]:
    """Revoke user session and blacklist access token without failing if access token has expired."""

    # Extract raw access token from authorization header
    access_token = ""
    if authorization and authorization.lower().startswith("bearer "):
        access_token = authorization.split(" ", 1)[1]

    await auth_service.logout(
        access_token=access_token,
        refresh_token=payload.refresh_token,
    )

    return APIResponse[None](
        success=True,
        message="Logged out successfully.",
        data=None,
        errors=None,
    )


@router.post(
    "/forgot-password",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[None],
    dependencies=[Depends(check_forgot_password_rate_limit)],
    responses={
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"model": APIResponse[None], "description": "Invalid input"},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": APIResponse[None], "description": "Internal server error"},
    },
)
async def forgot_password(
    payload: ForgotPasswordRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> APIResponse[None]:
    """Send a secure password reset link to user's email if the account exists."""

    await auth_service.forgot_password(payload)
    return APIResponse[None](
        success=True,
        message="If an account exists, a password reset email has been sent.",
        data=None,
        errors=None,
    )


@router.post(
    "/reset-password",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[None],
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": APIResponse[None], "description": "Reset failed / invalid token"},
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"model": APIResponse[None], "description": "Invalid input"},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": APIResponse[None], "description": "Internal server error"},
    },
)
async def reset_password(
    payload: ResetPasswordRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> APIResponse[None]:
    """Reset password credentials using the secure reset token."""

    await auth_service.reset_password(payload)
    return APIResponse[None](
        success=True,
        message="Password reset successfully. Please login again.",
        data=None,
        errors=None,
    )


# ---------------------------------------------------------------------------
# Auth Status Check
# ---------------------------------------------------------------------------


@router.get(
    "/status",
    status_code=status.HTTP_200_OK,
    summary="Check auth status",
)
async def get_auth_status(request: Request) -> APIResponse[dict]:
    """Check if current session has valid authentication without throwing 401."""
    auth_header = request.headers.get("authorization") or request.headers.get("Authorization")
    token = None
    if auth_header and auth_header.strip().lower().startswith("bearer "):
        token = auth_header.strip().split(" ", 1)[1].strip()

    if not token:
        return APIResponse[dict](
            success=True,
            message="Unauthenticated",
            data={"authenticated": False, "user": None},
            errors=None,
        )

    try:
        from app.utils.jwt import decode_token
        from app.services.token_service import is_access_token_blacklisted

        if is_access_token_blacklisted(token):
            return APIResponse[dict](
                success=True,
                message="Token blacklisted",
                data={"authenticated": False, "user": None},
                errors=None,
            )

        claims = decode_token(token)
        if claims.get("type") != "access":
            return APIResponse[dict](
                success=True,
                message="Invalid token type",
                data={"authenticated": False, "user": None},
                errors=None,
            )

        return APIResponse[dict](
            success=True,
            message="Authenticated",
            data={
                "authenticated": True,
                "user_id": claims.get("sub"),
                "email": claims.get("email"),
                "role": claims.get("role"),
                "company_id": claims.get("company_id"),
            },
            errors=None,
        )
    except Exception:
        return APIResponse[dict](
            success=True,
            message="Invalid or expired token",
            data={"authenticated": False, "user": None},
            errors=None,
        )


# ---------------------------------------------------------------------------
# Account Management Routes (JWT required)
# ---------------------------------------------------------------------------



@router.get(
    "/me",
    status_code=status.HTTP_200_OK,
    response_model=UserProfileResponse,
    summary="Get current user profile",
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": APIResponse[None], "description": "Invalid or expired token"},
        status.HTTP_404_NOT_FOUND: {"model": APIResponse[None], "description": "User not found"},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": APIResponse[None], "description": "Internal server error"},
    },
)
async def get_me(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    account_service: Annotated[AccountService, Depends(get_account_service)],
) -> UserProfileResponse:
    """Return the profile of the currently authenticated user."""

    user_id = uuid.UUID(claims["sub"])
    profile = await account_service.get_profile(user_id)
    return UserProfileResponse(
        success=True,
        message="Profile retrieved successfully.",
        data=profile,
        errors=None,
    )


@router.patch(
    "/change-password",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[None],
    summary="Change account password",
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": APIResponse[None], "description": "Passwords don't match or same password"},
        status.HTTP_401_UNAUTHORIZED: {"model": APIResponse[None], "description": "Current password incorrect or token invalid"},
        status.HTTP_404_NOT_FOUND: {"model": APIResponse[None], "description": "User not found"},
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"model": APIResponse[None], "description": "Invalid input"},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": APIResponse[None], "description": "Internal server error"},
    },
)
async def change_password(
    payload: ChangePasswordRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    account_service: Annotated[AccountService, Depends(get_account_service)],
) -> APIResponse[None]:
    """Update the authenticated user's password after verifying the current one."""

    user_id = uuid.UUID(claims["sub"])
    await account_service.change_password(user_id, payload)
    return APIResponse[None](
        success=True,
        message="Password changed successfully.",
        data=None,
        errors=None,
    )


@router.patch(
    "/change-email",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[None],
    summary="Initiate email change",
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": APIResponse[None], "description": "Validation failed or cooldown active"},
        status.HTTP_401_UNAUTHORIZED: {"model": APIResponse[None], "description": "Password incorrect or token invalid"},
        status.HTTP_404_NOT_FOUND: {"model": APIResponse[None], "description": "User not found"},
        status.HTTP_409_CONFLICT: {"model": APIResponse[None], "description": "Email already in use"},
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"model": APIResponse[None], "description": "Invalid input"},
        status.HTTP_429_TOO_MANY_REQUESTS: {"model": APIResponse[None], "description": "Max resend attempts reached"},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": APIResponse[None], "description": "Internal server error"},
    },
)
async def change_email(
    payload: ChangeEmailRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    account_service: Annotated[AccountService, Depends(get_account_service)],
) -> APIResponse[None]:
    """Verify password and send a 6-digit OTP to the new email address to initiate the change."""

    user_id = uuid.UUID(claims["sub"])
    await account_service.change_email(user_id, payload)
    return APIResponse[None](
        success=True,
        message="OTP sent to your new email address. Please verify within 10 minutes.",
        data=None,
        errors=None,
    )


@router.post(
    "/verify-new-email",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[None],
    summary="Verify new email OTP",
    dependencies=[Depends(check_otp_rate_limit)],
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": APIResponse[None], "description": "Invalid, expired, or exhausted OTP"},
        status.HTTP_401_UNAUTHORIZED: {"model": APIResponse[None], "description": "Invalid or expired token"},
        status.HTTP_404_NOT_FOUND: {"model": APIResponse[None], "description": "User or pending email not found"},
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"model": APIResponse[None], "description": "Invalid input"},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": APIResponse[None], "description": "Internal server error"},
    },
)
async def verify_new_email(
    payload: VerifyNewEmailRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    account_service: Annotated[AccountService, Depends(get_account_service)],
) -> APIResponse[None]:
    """Submit the OTP received on the new email to complete the email change."""

    user_id = uuid.UUID(claims["sub"])
    await account_service.verify_new_email(user_id, payload)
    return APIResponse[None](
        success=True,
        message="Email updated successfully.",
        data=None,
        errors=None,
    )


@router.patch(
    "/change-phone",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[None],
    summary="Change phone number",
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": APIResponse[None], "description": "Same phone or validation failed"},
        status.HTTP_401_UNAUTHORIZED: {"model": APIResponse[None], "description": "Password incorrect or token invalid"},
        status.HTTP_404_NOT_FOUND: {"model": APIResponse[None], "description": "User not found"},
        status.HTTP_409_CONFLICT: {"model": APIResponse[None], "description": "Phone already in use"},
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"model": APIResponse[None], "description": "Invalid input"},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": APIResponse[None], "description": "Internal server error"},
    },
)
async def change_phone(
    payload: ChangePhoneRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    account_service: Annotated[AccountService, Depends(get_account_service)],
) -> APIResponse[None]:
    """Verify password and immediately update the authenticated user's phone number."""

    user_id = uuid.UUID(claims["sub"])
    await account_service.change_phone(user_id, payload)
    return APIResponse[None](
        success=True,
        message="Phone number updated successfully.",
        data=None,
        errors=None,
    )
