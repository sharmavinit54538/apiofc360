"""Offboarding API v1 — Aliases to existing Exit Management endpoints."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/offboarding", tags=["Offboarding (Exit Management Aliases)"])

# Re-export the exits router under /offboarding prefix
# This provides compatibility aliases for frontend expecting /api/v1/offboarding
from app.api.exits import router as exits_router

# The exits router already has all the required endpoints:
# GET  /exits              -> GET  /offboarding (list)
# POST /exits/hr-initiate  -> POST /offboarding (initiate)
# GET  /exits/{id}         -> GET  /offboarding/{id}
# PATCH /exits/{id}/approve, /reject, /start-notice-period, /complete
# PATCH /exits/{id}/manager-approve, /manager-reject
# PATCH /exits/{id}/knowledge-transfer-complete
# PATCH /exits/{id}/asset-return, /clearance
# POST /exits/{id}/exit-interview
# GET  /exits/{id}/fnf-preview
# PATCH /exits/{id}/fnf, /fnf/confirm-payment
# GET  /exits/{id}/documents
# POST /exits/{id}/generate-documents

# Include the exits router with /offboarding prefix
router.include_router(exits_router, prefix="")

# Additional offboarding-specific endpoints can be added here if needed
# For now, the existing exits router provides full functionality