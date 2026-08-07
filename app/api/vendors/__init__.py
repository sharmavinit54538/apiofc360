"""Recruitment Vendors router aggregator."""

from fastapi import APIRouter

from app.api.vendors.create import router as create_router
from app.api.vendors.read import router as read_router
from app.api.vendors.update import router as update_router
from app.api.vendors.delete import router as delete_router

router = APIRouter(tags=["Recruitment Vendors"])

# Include sub-routes
router.include_router(create_router)
router.include_router(read_router)
router.include_router(update_router)
router.include_router(delete_router)
