"""Travel Management API v1 — Alias to v2 Travel API."""

from __future__ import annotations

from fastapi import APIRouter

# Re-export the v2 travel router under v1 prefix
from app.api.v2.travel_api import router as travel_v2_router

router = APIRouter(prefix="/travel", tags=["Travel Management v1"])

# Include the v2 travel router
router.include_router(travel_v2_router)