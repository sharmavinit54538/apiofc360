"""Resume Parser API v1 — Alias to v2 Resume Parser API."""

from __future__ import annotations

from fastapi import APIRouter

# Re-export the v2 resume parser router under v1 prefix
from app.api.v2.resume_parser import router as resume_parser_v2_router

router = APIRouter(prefix="/resume-parser", tags=["Resume Parser v1"])

# Include the v2 resume parser router
router.include_router(resume_parser_v2_router)