"""Travel Management API v1 — Standalone v1 routes (no double prefix with v2)."""

from __future__ import annotations

from fastapi import APIRouter

# Import handlers from v2 to avoid code duplication
from app.api.v2.travel_api import (
    list_travel_requests,
    get_travel_stats,
    create_travel_request,
    update_travel_request,
    advance_travel_request,
    delete_travel_request,
)

router = APIRouter(prefix="/travel", tags=["Travel Management v1"])

# Re-declare v1 routes using v2 handlers
router.get(
    "",
    status_code=200,
    summary="List all travel requests with filtering and searching"
)(list_travel_requests)

router.get(
    "/stats",
    status_code=200,
    summary="Get travel request summary statistics"
)(get_travel_stats)

router.post(
    "",
    status_code=201,
    summary="Create a new travel request"
)(create_travel_request)

router.put(
    "/{id}",
    status_code=200,
    summary="Update travel request details"
)(update_travel_request)

router.post(
    "/{id}/advance",
    status_code=200,
    summary="Advance travel request to the next workflow stage"
)(advance_travel_request)

router.delete(
    "/{id}",
    status_code=200,
    summary="Delete a travel request"
)(delete_travel_request)