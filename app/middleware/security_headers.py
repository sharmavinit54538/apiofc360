"""Security Headers Middleware for OFC360.
ASGI middleware for lower overhead."""

from __future__ import annotations

import logging
from typing import Optional

from starlette.responses import Response

from app.core.config import settings

logger = logging.getLogger(__name__)


class SecurityHeadersMiddleware:
    """Add security headers to all responses."""

    def __init__(self, app, *, csp_policy: Optional[str] = None):
        self.app = app
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

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "")

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                # Do not override or interfere with CORS preflight responses
                if method != "OPTIONS":
                    headers = list(message.get("headers", []))

                    # Content Security Policy
                    headers.append((b"content-security-policy", self.csp_policy.encode()))

                    # HSTS - only in production with HTTPS
                    if settings.ENVIRONMENT.lower() in {"production", "prod", "staging"}:
                        headers.append((b"strict-transport-security", b"max-age=31536000; includeSubDomains; preload"))

                    # Prevent clickjacking
                    headers.append((b"x-frame-options", b"DENY"))

                    # Prevent MIME type sniffing
                    headers.append((b"x-content-type-options", b"nosniff"))

                    # Referrer Policy
                    headers.append((b"referrer-policy", b"strict-origin-when-cross-origin"))

                    # Permissions Policy
                    headers.append((b"permissions-policy", b"geolocation=(), microphone=(), camera=(), payment=(), usb=(), magnetometer=(), gyroscope=(), accelerometer=()"))

                    # Cross-Origin policies
                    headers.append((b"cross-origin-resource-policy", b"cross-origin"))

                    message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)