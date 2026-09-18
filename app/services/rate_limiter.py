"""Sliding window rate limiters for authentication and onboarding workflows."""

import logging
from fastapi import Request

from app.core.rate_limiter import (
    RateLimitExceeded,
    check_forgot_password_rate_limit,
    check_login_rate_limit,
    check_onboarding_rate_limit,
    check_otp_rate_limit,
    get_rate_limiter,
    rate_limiter,
)

logger = logging.getLogger(__name__)

__all__ = [
    "RateLimitExceeded",
    "check_forgot_password_rate_limit",
    "check_login_rate_limit",
    "check_onboarding_rate_limit",
    "check_otp_rate_limit",
    "get_rate_limiter",
    "rate_limiter",
]

