"""Authentication request and response schemas."""

from datetime import datetime
from typing import Any, Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.utils.validators import normalize_email, validate_name, validate_password_strength, validate_phone

DataT = TypeVar("DataT")


class ErrorDetail(BaseModel):
    """Machine-readable error detail."""

    field: str | None = None
    message: str


class APIResponse(BaseModel, Generic[DataT]):
    """Common response envelope for success and error responses."""

    success: bool
    message: str
    data: DataT | None = None
    errors: list[ErrorDetail] | None = None


class RegisterRequest(BaseModel):
    """Register API request payload for new organization and HR Admin."""

    model_config = ConfigDict(extra="ignore")

    name: str = Field(default="", examples=["John Doe"])
    email: EmailStr = Field(..., examples=["john@example.com"])
    phone: str = Field(..., examples=["9876543210"])
    password: str = Field(..., min_length=8, max_length=64, examples=["Password@123"], repr=False)
    company_name: str = Field(..., examples=["Acme Corp"])

    @model_validator(mode="before")
    @classmethod
    def preprocess_register_payload(cls, data: Any) -> Any:
        """Support field aliases (phone_number, contact_number, mobile) and name components (first_name, last_name, full_name). Strips any client-provided role."""
        if isinstance(data, dict):
            # SECURITY: Strip/ignore any client-provided role
            data.pop("role", None)
            data.pop("user_role", None)
            data.pop("is_super_admin", None)

            # Normalize phone field alias if phone not provided
            if not data.get("phone"):
                if data.get("phone_number"):
                    data["phone"] = data["phone_number"]
                elif data.get("contact_number"):
                    data["phone"] = data["contact_number"]
                elif data.get("mobile"):
                    data["phone"] = data["mobile"]

            # Normalize company_name alias
            if not data.get("company_name"):
                if data.get("company"):
                    data["company_name"] = data["company"]
                elif data.get("organization_name"):
                    data["company_name"] = data["organization_name"]
                elif data.get("organization"):
                    data["company_name"] = data["organization"]

            # Normalize name if name is empty or not provided
            current_name = str(data.get("name") or "").strip()
            if not current_name:
                if data.get("full_name") and str(data.get("full_name")).strip():
                    data["name"] = str(data.get("full_name")).strip()
                else:
                    first = str(data.get("first_name") or "").strip()
                    last = str(data.get("last_name") or "").strip()
                    full_name = f"{first} {last}".strip()
                    if full_name:
                        data["name"] = full_name
            else:
                data["name"] = current_name
        return data

    @field_validator("name")
    @classmethod
    def validate_name_field(cls, value: str) -> str:
        """Validate and sanitize the user's name."""

        return validate_name(value)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email_field(cls, value: str) -> str:
        """Lowercase and trim email before RFC validation."""

        return normalize_email(value)

    @field_validator("phone", mode="before")
    @classmethod
    def validate_phone_field(cls, value: Any) -> str:
        """Validate and normalize the phone number."""

        return validate_phone(value)

    @model_validator(mode="after")
    def validate_password_field(self) -> "RegisterRequest":
        """Validate password strength after contextual fields are available."""

        self.password = validate_password_strength(
            self.password,
            email=str(self.email),
            name=self.name,
            phone=self.phone,
        )
        return self


class UserPublic(BaseModel):
    """Safe user fields returned to clients."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    email: EmailStr
    phone: str
    role: str
    is_verified: bool
    email_verified: bool = False
    account_status: str = "PENDING_EMAIL_VERIFICATION"
    created_at: datetime


class RegisterResponse(APIResponse[None]):
    """Register API response envelope."""


class VerifyEmailRequest(BaseModel):
    """Verify Email API request payload supporting token or email + OTP."""

    model_config = ConfigDict(extra="ignore")

    token: str | None = Field(default=None, description="Secure email verification token from email link")
    email: EmailStr | None = Field(default=None, description="User email for OTP verification")
    otp: str | None = Field(default=None, description="6-digit OTP code")

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email_field(cls, value: str | None) -> str | None:
        """Lowercase and trim email before RFC validation."""
        if value is None:
            return None
        return normalize_email(value)

    @field_validator("otp")
    @classmethod
    def validate_otp_field(cls, value: str | None) -> str | None:
        """Validate OTP characters."""
        if value is None:
            return None
        clean_otp = value.strip()
        if not clean_otp.isdigit():
            raise ValueError("OTP must contain only digits.")
        if len(clean_otp) != 6:
            raise ValueError("OTP must be exactly 6 digits.")
        return clean_otp

    @model_validator(mode="after")
    def validate_token_or_otp(self) -> "VerifyEmailRequest":
        """Ensure either token or (email and otp) is supplied."""
        if not self.token and not (self.email and self.otp):
            raise ValueError("Either verification token or email and 6-digit OTP is required.")
        return self


class VerifyEmailResponse(APIResponse[None]):
    """Verify Email API response envelope."""


class ResendOTPRequest(BaseModel):
    """Resend verification email / OTP API request payload."""

    email: EmailStr

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email_field(cls, value: str) -> str:
        """Lowercase and trim email before RFC validation."""

        return normalize_email(value)


class ResendOTPResponse(APIResponse[None]):
    """Resend OTP API response envelope."""


class LoginRequest(BaseModel):
    """Login API request payload."""

    identifier: str = Field(..., examples=["john@example.com", "9876543210"])
    password: str = Field(..., examples=["Password@123"], repr=False)

    @model_validator(mode="before")
    @classmethod
    def populate_identifier(cls, data: Any) -> Any:
        """Allow 'email', 'phone', or 'phone_number' field to be used as 'identifier' for backwards compatibility."""
        if isinstance(data, dict):
            if not data.get("identifier"):
                if data.get("email"):
                    data["identifier"] = data["email"]
                elif data.get("phone"):
                    data["identifier"] = str(data["phone"])
                elif data.get("phone_number"):
                    data["identifier"] = str(data["phone_number"])
                elif data.get("contact_number"):
                    data["identifier"] = str(data["contact_number"])
        return data


class UserLoginPublic(BaseModel):
    """Safe user fields returned inside login response."""

    id: UUID
    name: str | None = "User"
    email: EmailStr
    phone: str | None = None
    role: str
    is_verified: bool
    email_verified: bool = True
    account_status: str = "ACTIVE"
    must_change_password: bool = False
    onboarding_completed: bool = True
    company_id: UUID | None = None
    company_name: str | None = None


class LoginResponseData(BaseModel):
    """Data payload for login response."""

    user: UserLoginPublic
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int = 900


class LoginResponse(APIResponse[LoginResponseData]):
    """Login API response envelope."""


class RefreshTokenRequest(BaseModel):
    """Refresh token rotation request payload."""

    refresh_token: str


class RefreshTokenResponseData(BaseModel):
    """Data payload for refresh token response."""

    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int = 900


class RefreshTokenResponse(APIResponse[RefreshTokenResponseData]):
    """Refresh token rotation response envelope."""


class ForgotPasswordRequest(BaseModel):
    """Forgot password request payload."""

    email: EmailStr

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email_field(cls, value: str) -> str:
        """Lowercase and trim email before RFC validation."""

        return normalize_email(value)


class ResetPasswordRequest(BaseModel):
    """Reset password request payload."""

    token: str = Field(..., examples=["secure-reset-token"])
    password: str = Field(..., min_length=8, max_length=64, examples=["NewPassword@123"], repr=False)
    confirm_password: str = Field(..., min_length=8, max_length=64, examples=["NewPassword@123"], repr=False)

    @model_validator(mode="after")
    def validate_passwords(self) -> "ResetPasswordRequest":
        """Validate passwords match and meet strength requirements."""

        if self.password != self.confirm_password:
            raise ValueError("Passwords do not match.")
        self.password = validate_password_strength(self.password)
        return self


class VerifyResetOTPRequest(BaseModel):
    """Verify reset OTP request payload."""

    email: EmailStr
    otp: str = Field(..., min_length=6, max_length=6, examples=["123456"])

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email_field(cls, value: str) -> str:
        return normalize_email(value)

    @field_validator("otp")
    @classmethod
    def validate_otp_field(cls, value: str) -> str:
        if not value.isdigit():
            raise ValueError("OTP must contain only digits.")
        return value


class VerifyResetOTPResponseData(BaseModel):
    """Data payload for verify reset OTP response."""

    email: EmailStr
    resetToken: str


class VerifyResetOTPResponse(APIResponse[VerifyResetOTPResponseData]):
    """Verify reset OTP response envelope."""


# ---------------------------------------------------------------------------
# Account Management Schemas
# ---------------------------------------------------------------------------


class UserProfileData(BaseModel):
    """Full user profile returned by GET /me."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    email: EmailStr
    phone: str
    role: str
    is_active: bool
    is_verified: bool
    email_verified: bool = True
    account_status: str = "ACTIVE"
    onboarding_completed: bool
    company_id: UUID | None = None
    company_name: str | None = None
    created_at: datetime


class UserProfileResponse(APIResponse["UserProfileData"]):
    """GET /me response envelope."""


class ChangePasswordRequest(BaseModel):
    """PATCH /change-password request payload."""

    current_password: str = Field(..., examples=["OldPassword@123"], repr=False)
    new_password: str = Field(..., min_length=8, max_length=64, examples=["NewPassword@123"], repr=False)
    confirm_password: str = Field(..., min_length=8, max_length=64, examples=["NewPassword@123"], repr=False)

    @model_validator(mode="after")
    def validate_passwords(self) -> "ChangePasswordRequest":
        """Validate new password strength and confirm-password match."""

        if self.new_password != self.confirm_password:
            raise ValueError("New password and confirm password do not match.")
        self.new_password = validate_password_strength(self.new_password)
        return self


class ChangeEmailRequest(BaseModel):
    """PATCH /change-email request payload."""

    new_email: EmailStr = Field(..., examples=["newemail@example.com"])
    password: str = Field(..., examples=["CurrentPassword@123"], repr=False)

    @field_validator("new_email", mode="before")
    @classmethod
    def normalize_new_email(cls, value: str) -> str:
        """Lowercase and trim email before RFC validation."""

        return normalize_email(value)


class VerifyNewEmailRequest(BaseModel):
    """POST /verify-new-email request payload."""

    otp: str = Field(..., min_length=6, max_length=6, examples=["123456"])

    @field_validator("otp")
    @classmethod
    def validate_otp_field(cls, value: str) -> str:
        """Validate OTP contains only digits."""

        if not value.isdigit():
            raise ValueError("OTP must contain only digits.")
        return value


class ChangePhoneRequest(BaseModel):
    """PATCH /change-phone request payload."""

    phone: str = Field(..., examples=["9876543210"])
    password: str = Field(..., examples=["CurrentPassword@123"], repr=False)

    @model_validator(mode="before")
    @classmethod
    def preprocess_phone_payload(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if not data.get("phone"):
                if data.get("phone_number"):
                    data["phone"] = data["phone_number"]
                elif data.get("contact_number"):
                    data["phone"] = data["contact_number"]
        return data

    @field_validator("phone", mode="before")
    @classmethod
    def validate_phone_field(cls, value: Any) -> str:
        """Validate phone number format."""

        return validate_phone(value)


class GoogleAuthRequest(BaseModel):
    """Google SSO Auth API request payload."""

    email: EmailStr
    name: str | None = None
    credential: str | None = None
    action: str = Field(default="login", description="login or register")

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email_field(cls, value: str) -> str:
        return normalize_email(value)

