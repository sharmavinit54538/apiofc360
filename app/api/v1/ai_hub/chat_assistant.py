"""AI Hub — Chat Assistant Gateway (/api/v1/ai-hub/chat-assistant/*).

COMPATIBILITY ROUTER:
This router redirects to the canonical /api/v1/ai/chat/* endpoints
to ensure backward compatibility for frontend clients.
"""

from fastapi import APIRouter
from app.api.v1.chat_assistant import router as chat_router

router = APIRouter(prefix="/ai-hub/chat-assistant", tags=["AI Hub - Chat Assistant (Compatibility)"])

# Redirect all routes to canonical /api/v1/ai/chat/* endpoints
router.include_router(chat_router, prefix="")
