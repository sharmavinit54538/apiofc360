"""Security Headers Middleware for OFC360."""

from __future__ import annotations

import logging
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import settings

logger = logging.getLogger(__name__)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""

    def __init__(self, app, *, csp_policy: Optional[str] = None):
        super().__init__(app)
        self.csp_policy = csp_policy or self._default_csp_policy()

    def _default_csp_policy(self) -> str:
        """Default CSP policy compatible with the OFC360 frontend."""
        return (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net https://unpkg.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net; "
            "font-src 'self' https://fonts.gstatic.com https://cdn.jsdelivr.net data:; "
            "img-src 'self' data: https: blob:; "
            "connect-src 'self' https://api.ofc360.com https://ofc360.com https://www.ofc360.com wss://api.ofc360.com wss://ofc360.com wss://www.ofc360.com; "
            "frame-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'; "
            "object-src 'none';"
        )

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)

        # Do not override or interfere with CORS preflight responses
        if request.method == "OPTIONS":
            return response

        # Content Security Policy
        response.headers["Content-Security-Policy"] = self.csp_policy

        # HSTS - only in production with HTTPS
        if settings.ENVIRONMENT.lower() in {"production", "prod", "staging"}:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"

        # Prevent clickjacking
        response.headers["X-Frame-Options"] = "DENY"

        # Prevent MIME type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"

        # Referrer Policy
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Permissions Policy
        response.headers["Permissions-Policy"] = (
            "geolocation=(), "
            "microphone=(), "
            "camera=(), "
            "payment=(), "
            "usb=(), "
            "magnetometer=(), "
            "gyroscope=(), "
            "accelerometer=()"
        )

        # Cross-Origin policies (allow cross-origin API resource sharing)
        response.headers["Cross-Origin-Resource-Policy"] = "cross-origin"

        return response