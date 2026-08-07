"""Job Requisitions router aggregator."""

from fastapi import APIRouter

from app.api.requisitions.create import router as create_router
from app.api.requisitions.read import router as read_router

router = APIRouter(tags=["Requisition Management"])

# Include sub-routes
router.include_router(create_router)
router.include_router(read_router)
