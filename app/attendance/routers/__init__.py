"""Unified Face Attendance routers export aggregator."""

from fastapi import APIRouter

from app.attendance.routers.checkin import router as checkin_router
from app.attendance.routers.checkout import router as checkout_router
from app.attendance.routers.me import router as me_router
from app.attendance.routers.history import router as history_router
from app.attendance.routers.team import router as team_router
from app.attendance.routers.company import router as company_router
from app.attendance.routers.analytics import router as analytics_router

router = APIRouter(prefix="/attendance", tags=["Face Attendance"])

# Include sub-routes
router.include_router(checkin_router)
router.include_router(checkout_router)
router.include_router(me_router)
router.include_router(history_router)
router.include_router(team_router)
router.include_router(company_router)
router.include_router(analytics_router)
