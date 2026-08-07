"""Company News API routes."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.departments import require_admin_or_hr
from app.middleware.auth import get_current_user_claims
from app.schemas.auth import APIResponse
from app.schemas.communication import (
    CompanyNewsCreate,
    CompanyNewsResponse,
)
from app.services.communication_service import CommunicationService, get_communication_service

router = APIRouter(prefix="/news", tags=["Company News Management"])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[CompanyNewsResponse],
    summary="Create news article",
)
async def create_news(
    payload: CompanyNewsCreate,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[CommunicationService, Depends(get_communication_service)],
) -> APIResponse[CompanyNewsResponse]:
    """Create a new news article draft. Admin and HR only."""
    user_id = uuid.UUID(claims["sub"])
    res = await service.create_news(user_id, payload)
    return APIResponse[CompanyNewsResponse](
        success=True,
        message="News article draft created successfully.",
        data=res,
        errors=None,
    )

@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[list[CompanyNewsResponse]],
    summary="List news articles",
)
async def list_news(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[CommunicationService, Depends(get_communication_service)],
    status_filter: str | None = Query(None, alias="status"),
    category: str | None = Query(None),
    search: str | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
) -> APIResponse[list[CompanyNewsResponse]]:
    """List news articles with filters."""
    res = await service.list_news(
        status=status_filter,
        category=category,
        search=search,
        page=page,
        limit=limit,
    )
    return APIResponse[list[CompanyNewsResponse]](
        success=True,
        message="News articles list retrieved.",
        data=res,
        errors=None,
    )

@router.get(
    "/{id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[CompanyNewsResponse],
    summary="Get news article details",
)
async def get_news(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[CommunicationService, Depends(get_communication_service)],
) -> APIResponse[CompanyNewsResponse]:
    """Retrieve full details of a news article. Triggers views increment."""
    user_id = uuid.UUID(claims["sub"])
    res = await service.get_news(user_id, id)
    return APIResponse[CompanyNewsResponse](
        success=True,
        message="News article retrieved.",
        data=res,
        errors=None,
    )

@router.put(
    "/{id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[CompanyNewsResponse],
    summary="Update news article",
)
async def update_news(
    id: uuid.UUID,
    payload: CompanyNewsCreate,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[CommunicationService, Depends(get_communication_service)],
) -> APIResponse[CompanyNewsResponse]:
    """Update details of news article draft. Admin and HR only."""
    user_id = uuid.UUID(claims["sub"])
    res = await service.update_news(user_id, id, payload)
    return APIResponse[CompanyNewsResponse](
        success=True,
        message="News article updated.",
        data=res,
        errors=None,
    )

@router.delete(
    "/{id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[None],
    summary="Delete news article",
)
async def delete_news(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[CommunicationService, Depends(get_communication_service)],
) -> APIResponse[None]:
    """Soft delete news article. Admin and HR only."""
    user_id = uuid.UUID(claims["sub"])
    await service.delete_news(user_id, id)
    return APIResponse[None](
        success=True,
        message="News article deleted.",
        data=None,
        errors=None,
    )

@router.patch(
    "/{id}/publish",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[CompanyNewsResponse],
    summary="Publish news article",
)
async def publish_news(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[CommunicationService, Depends(get_communication_service)],
) -> APIResponse[CompanyNewsResponse]:
    """Publish news article draft. Admin and HR only."""
    user_id = uuid.UUID(claims["sub"])
    # Just update status to PUBLISHED
    article = await service.repo.get_news_by_id(id)
    if not article:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Article not found.")
    await service.repo.update_news(id, status="PUBLISHED", publish_date=date.today())
    
    await service.repo.create_audit_log(
        user_id=user_id,
        action="PUBLISH",
        target_type="NEWS",
        target_id=id,
        details="Published news article.",
    )
    
    await service.session.commit()
    updated = await service.repo.get_news_by_id(id)
    return APIResponse[CompanyNewsResponse](
        success=True,
        message="News article published successfully.",
        data=CompanyNewsResponse.model_validate(updated),
        errors=None,
    )
