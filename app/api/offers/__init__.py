"""Job offers API router aggregator."""

from fastapi import APIRouter

from app.api.offers.create import router as create_router
from app.api.offers.status import router as status_router
from app.api.offers.read import router as read_router

router = APIRouter(tags=["Offer Management"])

# Include sub-routes
router.include_router(create_router)
router.include_router(status_router)
router.include_router(read_router)
