"""Recruitment Automation API routes."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.departments import require_admin_or_hr
from app.schemas.auth import APIResponse
from app.schemas.recruitment import (
    RecruitmentAutomationRuleCreate,
    RecruitmentAutomationRuleResponse,
)
from app.services.recruitment_service import RecruitmentService, get_recruitment_service

router = APIRouter(prefix="/automations", tags=["Recruitment Automation"])


@router.post(
    "/rules",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[RecruitmentAutomationRuleResponse],
    summary="Create automation rule",
)
async def create_automation_rule(
    payload: RecruitmentAutomationRuleCreate,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
) -> APIResponse[RecruitmentAutomationRuleResponse]:
    """Create automation rule. Admin and HR only."""
    rule = await service.create_automation_rule(payload)
    return APIResponse[RecruitmentAutomationRuleResponse](
        success=True,
        message="Automation rule created successfully.",
        data=rule,
        errors=None,
    )


@router.get(
    "/rules",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[list[RecruitmentAutomationRuleResponse]],
    summary="List automation rules",
)
async def list_automation_rules(
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
    active_only: bool = Query(False),
) -> APIResponse[list[RecruitmentAutomationRuleResponse]]:
    """List automation rules. Admin and HR only."""
    rules = await service.list_automation_rules(active_only)
    return APIResponse[list[RecruitmentAutomationRuleResponse]](
        success=True,
        message="Automation rules retrieved successfully.",
        data=rules,
        errors=None,
    )
