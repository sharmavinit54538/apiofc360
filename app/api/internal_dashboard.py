"""Internal Communication Dashboard API routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.middleware.auth import get_current_user_claims
from app.schemas.auth import APIResponse
from app.schemas.communication import CommunicationDashboardView
from app.services.communication_service import CommunicationService, get_communication_service

router = APIRouter(prefix="/internal/dashboard", tags=["Communication Dashboard"])




@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[CommunicationDashboardView],
    summary="Get unified internal communication dashboard feed",
)
async def get_dashboard(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[CommunicationService, Depends(get_communication_service)],
) -> APIResponse[CommunicationDashboardView]:
    """Retrieve full feeds dashboard (pinned/recent announcements, news articles, company events, active polls)."""
    res = await service.get_dashboard()
    return APIResponse[CommunicationDashboardView](
        success=True,
        message="Communication dashboard retrieved.",
        data=res,
        errors=None,
    )
