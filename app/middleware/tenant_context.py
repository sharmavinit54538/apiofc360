"""Bound tenant context to one ASGI request, including exceptional exits."""
from app.db.base import tenant_id_ctx


class TenantContextMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        token = tenant_id_ctx.set(None)
        try:
            await self.app(scope, receive, send)
        finally:
            tenant_id_ctx.reset(token)
