"""Exit Management API routes."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.departments import require_admin_or_hr
from app.middleware.auth import get_current_user_claims
from app.schemas.auth import APIResponse
from app.schemas.exit import (
    AssetReturnCreate,
    AssetReturnResponse,
    ClearanceResponse,
    ClearanceUpdate,
    ExitDashboardStats,
    ExitDocumentResponse,
    ExitInterviewCreate,
    ExitInterviewResponse,
    ExitListResponse,
    ExitResponse,
    FnfCreate,
    FnfResponse,
    KTCreate,
    KTResponse,
    ResignationRequest,
)
from app.services.exit_service import ExitService, get_exit_service

router = APIRouter(prefix="/exits", tags=["Exit Management"])


# Helper dependency to enforce Manager, HR or Admin role
async def require_manager_or_hr_or_admin(claims: Annotated[dict, Depends(get_current_user_claims)]) -> dict:
    role = claims.get("role")
    if role not in {"super_admin", "hr_admin", "manager"}:
        from app.core.exceptions import AppException
        raise AppException(message="Access denied.", status_code=status.HTTP_403_FORBIDDEN)
    return claims


# ---------------------------------------------------------------------------
# Employee Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/resign",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[ExitResponse],
    summary="Submit employee resignation",
)
async def submit_resignation(
    payload: ResignationRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[ExitService, Depends(get_exit_service)],
) -> APIResponse[ExitResponse]:
    """Submit resignation request. Employee only. Enforces one active request rule."""
    user_id = uuid.UUID(claims["sub"])
    res = await service.submit_resignation(user_id, payload)
    return APIResponse[ExitResponse](
        success=True,
        message="Resignation request submitted successfully.",
        data=res,
        errors=None,
    )

@router.get(
    "/my-request",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ExitResponse],
    summary="Get currently logged in employee's resignation request",
)
async def get_my_request(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[ExitService, Depends(get_exit_service)],
) -> APIResponse[ExitResponse]:
    """Retrieve details of own resignation request."""
    user_id = uuid.UUID(claims["sub"])
    res = await service.get_my_request(user_id)
    return APIResponse[ExitResponse](
        success=True,
        message="Resignation request details retrieved successfully.",
        data=res,
        errors=None,
    )

@router.delete(
    "/my-request",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[None],
    summary="Cancel own resignation request",
)
async def cancel_my_request(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[ExitService, Depends(get_exit_service)],
) -> APIResponse[None]:
    """Cancel own active resignation request. Allowed only before HR/Notice period starts."""
    user_id = uuid.UUID(claims["sub"])
    await service.cancel_my_request(user_id)
    return APIResponse[None](
        success=True,
        message="Resignation request cancelled successfully.",
        data=None,
        errors=None,
    )


# ---------------------------------------------------------------------------
# HR Operations
# ---------------------------------------------------------------------------

@router.get(
    "/stats",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ExitDashboardStats],
    summary="Get exit dashboard statistics",
)
async def get_exit_stats(
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[ExitService, Depends(get_exit_service)],
) -> APIResponse[ExitDashboardStats]:
    """Retrieve offboarding metrics counts. Admin and HR only."""
    stats = await service.get_dashboard_stats()
    return APIResponse[ExitDashboardStats](
        success=True,
        message="Exit dashboard statistics retrieved successfully.",
        data=stats,
        errors=None,
    )

@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ExitListResponse],
    summary="List all exit requests",
)
async def list_exits(
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[ExitService, Depends(get_exit_service)],
    status_filter: str | None = Query(None, alias="status", description="Filter by exit status"),
    search: str | None = Query(None, description="Search by employee name or reason"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
) -> APIResponse[ExitListResponse]:
    """List exits. Admin and HR only."""
    result = await service.list_exits(
        status_filter=status_filter,
        search=search,
        page=page,
        limit=limit,
    )
    return APIResponse[ExitListResponse](
        success=True,
        message="Exit requests retrieved successfully.",
        data=result,
        errors=None,
    )

@router.get(
    "/{id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ExitResponse],
    summary="Get exit details by ID",
)
async def get_exit(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(require_manager_or_hr_or_admin)],
    service: Annotated[ExitService, Depends(get_exit_service)],
) -> APIResponse[ExitResponse]:
    """Retrieve full exit details. Manager, HR, and Admin only."""
    res = await service.get_exit(id)
    return APIResponse[ExitResponse](
        success=True,
        message="Exit details retrieved successfully.",
        data=res,
        errors=None,
    )

@router.patch(
    "/{id}/approve",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ExitResponse],
    summary="HR approves exit request",
)
async def hr_approve(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[ExitService, Depends(get_exit_service)],
    remarks: str | None = Query(None),
) -> APIResponse[ExitResponse]:
    """HR approves candidate resignation request. Admin and HR only."""
    res = await service.hr_approve(id, remarks)
    return APIResponse[ExitResponse](
        success=True,
        message="Exit request approved by HR successfully.",
        data=res,
        errors=None,
    )

@router.patch(
    "/{id}/reject",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ExitResponse],
    summary="HR rejects exit request",
)
async def hr_reject(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[ExitService, Depends(get_exit_service)],
    remarks: str | None = Query(None),
) -> APIResponse[ExitResponse]:
    """HR rejects resignation request. Admin and HR only."""
    res = await service.hr_reject(id, remarks)
    return APIResponse[ExitResponse](
        success=True,
        message="Exit request rejected by HR.",
        data=res,
        errors=None,
    )

@router.patch(
    "/{id}/start-notice-period",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ExitResponse],
    summary="Start notice period",
)
async def start_notice_period(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[ExitService, Depends(get_exit_service)],
) -> APIResponse[ExitResponse]:
    """HR triggers notice period status transition. Admin and HR only."""
    res = await service.start_notice_period(id)
    return APIResponse[ExitResponse](
        success=True,
        message="Notice period started successfully.",
        data=res,
        errors=None,
    )

@router.patch(
    "/{id}/complete",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ExitResponse],
    summary="Complete offboarding and deactivate account",
)
async def complete_exit(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[ExitService, Depends(get_exit_service)],
) -> APIResponse[ExitResponse]:
    """Trigger final exit completion. Validates KT, asset returns, clearances, and FNF payment. Deactivates employee login account. Admin and HR only."""
    res = await service.complete_exit(id)
    return APIResponse[ExitResponse](
        success=True,
        message="Offboarding completed. Employee account deactivated and archived.",
        data=res,
        errors=None,
    )


# ---------------------------------------------------------------------------
# Manager Operations
# ---------------------------------------------------------------------------

@router.patch(
    "/{id}/manager-approve",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ExitResponse],
    summary="Manager approves exit request",
)
async def manager_approve(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(require_manager_or_hr_or_admin)],
    service: Annotated[ExitService, Depends(get_exit_service)],
    remarks: str | None = Query(None),
) -> APIResponse[ExitResponse]:
    """Manager approves employee resignation. Manager/HR/Admin only."""
    res = await service.manager_approve(id, remarks)
    return APIResponse[ExitResponse](
        success=True,
        message="Exit request approved by manager.",
        data=res,
        errors=None,
    )

@router.patch(
    "/{id}/manager-reject",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ExitResponse],
    summary="Manager rejects exit request",
)
async def manager_reject(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(require_manager_or_hr_or_admin)],
    service: Annotated[ExitService, Depends(get_exit_service)],
    remarks: str | None = Query(None),
) -> APIResponse[ExitResponse]:
    """Manager rejects employee resignation. Manager/HR/Admin only."""
    res = await service.manager_reject(id, remarks)
    return APIResponse[ExitResponse](
        success=True,
        message="Exit request rejected by manager.",
        data=res,
        errors=None,
    )

@router.patch(
    "/{id}/knowledge-transfer-complete",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[KTResponse],
    summary="Complete Knowledge Transfer handover details",
)
async def knowledge_transfer_complete(
    id: uuid.UUID,
    payload: KTCreate,
    claims: Annotated[dict, Depends(require_manager_or_hr_or_admin)],
    service: Annotated[ExitService, Depends(get_exit_service)],
) -> APIResponse[KTResponse]:
    """Verify and complete candidate knowledge transfer details. Manager/HR/Admin only."""
    kt = await service.complete_kt(id, payload)
    return APIResponse[KTResponse](
        success=True,
        message="Knowledge Transfer handover details updated.",
        data=kt,
        errors=None,
    )


# ---------------------------------------------------------------------------
# Assets Operations
# ---------------------------------------------------------------------------

@router.get(
    "/{id}/assets",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[list[AssetReturnResponse]],
    summary="Get assets return checklist",
)
async def get_assets_checklist(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(require_manager_or_hr_or_admin)],
    service: Annotated[ExitService, Depends(get_exit_service)],
) -> APIResponse[list[AssetReturnResponse]]:
    """Get checklist details of assigned assets and return status."""
    res = await service.get_assets(id)
    return APIResponse[list[AssetReturnResponse]](
        success=True,
        message="Asset return checklist retrieved.",
        data=res,
        errors=None,
    )

@router.patch(
    "/{id}/asset-return",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[AssetReturnResponse],
    summary="Update asset return status",
)
async def return_asset(
    id: uuid.UUID,
    payload: AssetReturnCreate,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[ExitService, Depends(get_exit_service)],
) -> APIResponse[AssetReturnResponse]:
    """Verify and update company asset return status. Admin and HR only."""
    res = await service.return_asset(id, payload)
    return APIResponse[AssetReturnResponse](
        success=True,
        message="Asset return status updated.",
        data=res,
        errors=None,
    )


# ---------------------------------------------------------------------------
# No Dues & Clearances
# ---------------------------------------------------------------------------

@router.patch(
    "/{id}/clearance",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ClearanceResponse],
    summary="Update department dues clearance status",
)
async def update_clearance(
    id: uuid.UUID,
    payload: ClearanceUpdate,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[ExitService, Depends(get_exit_service)],
) -> APIResponse[ClearanceResponse]:
    """Verify and check IT, HR, Finance, Admin clearance statuses. Admin and HR only."""
    res = await service.update_clearance(id, payload)
    return APIResponse[ClearanceResponse](
        success=True,
        message="Department clearances status updated.",
        data=res,
        errors=None,
    )


# ---------------------------------------------------------------------------
# Exit Interview
# ---------------------------------------------------------------------------

@router.post(
    "/{id}/exit-interview",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[ExitInterviewResponse],
    summary="Submit Exit Interview details",
)
async def submit_exit_interview(
    id: uuid.UUID,
    payload: ExitInterviewCreate,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[ExitService, Depends(get_exit_service)],
) -> APIResponse[ExitInterviewResponse]:
    """Submit details of conducting exit interview. Admin and HR only."""
    res = await service.submit_exit_interview(id, payload)
    return APIResponse[ExitInterviewResponse](
        success=True,
        message="Exit interview submitted successfully.",
        data=res,
        errors=None,
    )


# ---------------------------------------------------------------------------
# Full & Final Settlement (FNF)
# ---------------------------------------------------------------------------

@router.patch(
    "/{id}/fnf",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[FnfResponse],
    summary="Submit FNF payroll settlement details",
)
async def submit_fnf(
    id: uuid.UUID,
    payload: FnfCreate,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[ExitService, Depends(get_exit_service)],
) -> APIResponse[FnfResponse]:
    """HR creates FNF settlement numbers and payouts. Admin and HR only."""
    res = await service.submit_fnf(id, payload)
    return APIResponse[FnfResponse](
        success=True,
        message="Full & Final settlement details updated.",
        data=res,
        errors=None,
    )


# ---------------------------------------------------------------------------
# Relieving Letters & Exit Documents
# ---------------------------------------------------------------------------

@router.get(
    "/{id}/documents",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[list[ExitDocumentResponse]],
    summary="Get generated exit documents",
)
async def get_exit_documents(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[ExitService, Depends(get_exit_service)],
) -> APIResponse[list[ExitDocumentResponse]]:
    """Retrieve experience, relieving letters, and salary certificates for the exit request."""
    res = await service.get_documents(id)
    return APIResponse[list[ExitDocumentResponse]](
        success=True,
        message="Generated exit documents retrieved.",
        data=res,
        errors=None,
    )

@router.post(
    "/{id}/generate-documents",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[list[ExitDocumentResponse]],
    summary="Generate exit documents",
)
async def generate_exit_documents(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[ExitService, Depends(get_exit_service)],
) -> APIResponse[list[ExitDocumentResponse]]:
    """Trigger generation of Relieving and Experience letters. Admin and HR only."""
    res = await service.generate_exit_documents(id)
    return APIResponse[list[ExitDocumentResponse]](
        success=True,
        message="Exit documents generated successfully.",
        data=res,
        errors=None,
    )
