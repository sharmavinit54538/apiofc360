"""Request ID and Correlation ID middleware for end-to-end API tracing.

Pure ASGI middleware that extracts or generates `X-Request-ID` and
`X-Correlation-ID`, binds them to ContextVars for structured logging,
attaches them to `scope["state"]`, and returns them on outgoing responses.
"""

from __future__ import annotations

import contextvars
import uuid
from typing import Any

request_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)
correlation_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar("correlation_id", default=None)


def get_current_request_id() -> str | None:
    return request_id_ctx.get()


def get_current_correlation_id() -> str | None:
    return correlation_id_ctx.get()


class RequestIDMiddleware:
    """Pure ASGI middleware attaching request_id and correlation_id to scope state and headers."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        req_id: str | None = None
        corr_id: str | None = None
        for key, value in scope.get("headers") or ():
            lower_key = key.lower()
            if lower_key == b"x-request-id" and not req_id:
                req_id = value.decode("latin-1").strip()[:128] or None
            elif lower_key == b"x-correlation-id" and not corr_id:
                corr_id = value.decode("latin-1").strip()[:128] or None

        req_id = req_id or str(uuid.uuid4())
        corr_id = corr_id or req_id

        state = scope.setdefault("state", {})
        if isinstance(state, dict):
            state["request_id"] = req_id
            state["correlation_id"] = corr_id

        tok_req = request_id_ctx.set(req_id)
        tok_corr = correlation_id_ctx.set(corr_id)

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", req_id.encode("latin-1")))
                headers.append((b"x-correlation-id", corr_id.encode("latin-1")))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            request_id_ctx.reset(tok_req)
            correlation_id_ctx.reset(tok_corr)
