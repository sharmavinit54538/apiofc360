"""Asset Management API Router."""
# Config reload: Cloudinary credentials loaded from .env

from __future__ import annotations
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, UploadFile, File, status, Request

from app.api.departments import require_admin_or_hr
from app.middleware.auth import get_current_user_claims
from app.schemas.auth import APIResponse
from app.schemas.asset import (
    AssetCreate,
    AssetUpdate,
    AssetAssignRequest,
    AssetTransferRequest,
    AssetMaintenanceCreate,
    AssetMaintenanceComplete,
    AssetResponse,
    AssetListResponse,
    AssetAnalyticsResponse,
    AssetFilterOptionsResponse,
    AssetPublicResponse,
    AssetRequestCreate,
    AssetRequestUpdate,
    AssetRequestResponse,
    AssetDamageReportCreate,
    AssetDamageReportResponse,
    AssetLostRequest,
)
from app.services.asset_service import AssetService, get_asset_service

router = APIRouter(prefix="/assets", tags=["Asset Management"])


def _get_cid(claims: dict) -> uuid.UUID:
    cid = claims.get("company_id")
    if not cid:
        from app.core.exceptions import BadRequestException
        raise BadRequestException("Company ID missing in user token/context.")
    try:
        return uuid.UUID(str(cid))
    except (ValueError, TypeError):
        from app.core.exceptions import BadRequestException
        raise BadRequestException("Invalid Company ID in user token/context.")


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[AssetListResponse],
    summary="List all company hardware assets",
)
async def list_assets(
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[AssetService, Depends(get_asset_service)],
    category: str | None = Query(None, description="Filter by asset category"),
    status_filter: str | None = Query(None, alias="status", description="Filter by asset status"),
    search: str | None = Query(None, description="Search tag, brand, serial, or employee name"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    vendor: str | None = Query(None, description="Filter by exact vendor name"),
    location: str | None = Query(None, description="Filter by exact location"),
    department: str | None = Query(None, description="Filter by assigned employee's department"),
    sort_by: str = Query("created_at", description="Column to sort by: tag, name, category, brand, serial, vendor, location, department, assignedTo, warranty_until, status, created_at"),
    sort_dir: str = Query("desc", description="asc or desc"),
) -> APIResponse[AssetListResponse]:
    """Retrieve list of company inventory assets with filtering and pagination."""
    cid = _get_cid(claims)
    result = await service.list_assets(
        company_id=cid,
        category=category,
        status=status_filter,
        search=search,
        page=page,
        limit=limit,
        vendor=vendor,
        location=location,
        department=department,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )
    return APIResponse[AssetListResponse](
        success=True,
        message="Assets retrieved successfully.",
        data=result,
        errors=None,
    )


@router.get(
    "/analytics",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[AssetAnalyticsResponse],
    summary="Get aggregated asset analytics data",
)
async def get_analytics(
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[AssetService, Depends(get_asset_service)],
) -> APIResponse[AssetAnalyticsResponse]:
    """Get statistics for categories, status divisions, valuations, and repair expenses."""
    cid = _get_cid(claims)
    result = await service.get_analytics(company_id=cid)
    return APIResponse[AssetAnalyticsResponse](
        success=True,
        message="Asset analytics retrieved successfully.",
        data=result,
        errors=None,
    )


@router.get(
    "/filter-options",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[AssetFilterOptionsResponse],
    summary="Get distinct filter option values for assets",
)
async def get_filter_options(
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[AssetService, Depends(get_asset_service)],
) -> APIResponse[AssetFilterOptionsResponse]:
    """Get distinct vendors, locations, and departments for filtering."""
    cid = _get_cid(claims)
    result = await service.get_filter_options(company_id=cid)
    return APIResponse[AssetFilterOptionsResponse](
        success=True,
        message="Filter options retrieved successfully.",
        data=result,
        errors=None,
    )


@router.get(
    "/upload-image",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Get asset upload image requirements",
)
async def get_upload_image_info(
    claims: Annotated[dict, Depends(require_admin_or_hr)],
) -> APIResponse[dict]:
    """Get requirements for the asset image upload endpoint. Use POST to upload files."""
    return APIResponse[dict](
        success=True,
        message="Asset image upload endpoint is active. Send a POST request with a multipart 'file' field to upload.",
        data={
            "allowed_types": ["image/jpeg", "image/jpg", "image/png", "image/webp", "image/gif"],
            "max_size_mb": 5,
        },
        errors=None,
    )


@router.post(
    "/upload-image",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Upload asset image to Cloudinary",
)
async def upload_asset_image(
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    file: Annotated[UploadFile, File(description="Image file to upload (jpg, jpeg, png, webp, gif)")],
) -> APIResponse[dict]:
    """Upload an image file to Cloudinary and return the secure URL.
    Use the returned `image_url` as the image_url field when creating or updating an asset.
    """
    import os
    import cloudinary
    import cloudinary.uploader
    from app.core.exceptions import BadRequestException, AppException
    from fastapi import status as http_status

    # Read Cloudinary credentials directly from env or fall back to parsed settings
    from app.core.config import settings

    cloud_name = os.environ.get("CLOUDINARY_CLOUD_NAME") or settings.CLOUDINARY_CLOUD_NAME or ""
    api_key = os.environ.get("CLOUDINARY_API_KEY") or settings.CLOUDINARY_API_KEY or ""
    api_secret = os.environ.get("CLOUDINARY_API_SECRET") or settings.CLOUDINARY_API_SECRET or ""

    # Strip surrounding quotes if any (some .env readers include them)
    cloud_name = cloud_name.strip('"').strip("'")
    api_key = api_key.strip('"').strip("'")
    api_secret = api_secret.strip('"').strip("'")

    # Validate Cloudinary is configured
    if not cloud_name or cloud_name in ("your_cloud_name", ""):
        raise AppException(
            message="Cloudinary is not configured. Please set CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, and CLOUDINARY_API_SECRET in your .env file.",
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    # Validate file type
    allowed_types = {"image/jpeg", "image/jpg", "image/png", "image/webp", "image/gif"}
    if file.content_type not in allowed_types:
        raise BadRequestException(
            f"Invalid file type '{file.content_type}'. Allowed: jpg, jpeg, png, webp, gif."
        )

    # Validate file size (max 5MB)
    MAX_SIZE = 5 * 1024 * 1024  # 5 MB
    contents = await file.read()
    if len(contents) > MAX_SIZE:
        raise BadRequestException("File size exceeds 5MB limit.")

    # Configure Cloudinary
    cloudinary.config(
        cloud_name=cloud_name,
        api_key=api_key,
        api_secret=api_secret,
        secure=True,
    )

    # Upload to Cloudinary
    try:
        upload_result = cloudinary.uploader.upload(
            contents,
            folder="hrms/assets",
            resource_type="image",
            overwrite=False,
            unique_filename=True,
        )
        image_url = upload_result.get("secure_url")
        public_id = upload_result.get("public_id")
    except Exception as exc:
        raise AppException(
            message=f"Cloudinary upload failed: {str(exc)}",
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    return APIResponse[dict](
        success=True,
        message="Image uploaded successfully.",
        data={"image_url": image_url, "public_id": public_id},
        errors=None,
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[AssetResponse],
    summary="Create a new asset record",
)
async def create_asset(
    payload: AssetCreate,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[AssetService, Depends(get_asset_service)],
) -> APIResponse[AssetResponse]:
    """Register a new hardware asset in the inventory."""
    cid = _get_cid(claims)
    user_id = uuid.UUID(claims["sub"])
    result = await service.create_asset(payload, user_id, cid)
    return APIResponse[AssetResponse](
        success=True,
        message="Asset created successfully.",
        data=result,
        errors=None,
    )


@router.get(
    "/public/{id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[AssetPublicResponse],
    summary="Get public details of a single asset for QR scanning",
)
async def get_public_asset(
    id: uuid.UUID,
    service: Annotated[AssetService, Depends(get_asset_service)],
    request: Request,
) -> APIResponse[AssetPublicResponse]:
    """Get public details of a specific asset by UUID for QR scanning, without authentication.
    
    Rate limited to prevent enumeration. Only exposes non-sensitive asset information.
    """
    # Rate limiting: 30 requests per minute per IP
    from app.core.rate_limiter import rate_limit_check
    await rate_limit_check("asset_public", request, limit=30, window_seconds=60)
    
    result = await service.get_public_asset(id)
    return APIResponse[AssetPublicResponse](
        success=True,
        message="Asset public details retrieved successfully.",
        data=result,
        errors=None,
    )


@router.get(
    "/{id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[AssetResponse],
    summary="Get details of a single asset",
)
async def get_asset(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[AssetService, Depends(get_asset_service)],
) -> APIResponse[AssetResponse]:
    """Get full details of a specific asset by UUID including timeline logs."""
    cid = _get_cid(claims)
    result = await service.get_asset(id, company_id=cid)
    return APIResponse[AssetResponse](
        success=True,
        message="Asset details retrieved successfully.",
        data=result,
        errors=None,
    )


@router.put(
    "/{id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[AssetResponse],
    summary="Update specifications of an asset",
)
async def update_asset(
    id: uuid.UUID,
    payload: AssetUpdate,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[AssetService, Depends(get_asset_service)],
) -> APIResponse[AssetResponse]:
    """Update hardware parameters or metadata on a target asset."""
    cid = _get_cid(claims)
    user_id = uuid.UUID(claims["sub"])
    result = await service.update_asset(id, payload, user_id, cid)
    return APIResponse[AssetResponse](
        success=True,
        message="Asset updated successfully.",
        data=result,
        errors=None,
    )


@router.delete(
    "/{id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[None],
    summary="Archive an asset record (soft delete)",
)
async def delete_asset(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[AssetService, Depends(get_asset_service)],
) -> APIResponse[None]:
    """Archive asset from inventory system (soft delete). Preserves all history."""
    cid = _get_cid(claims)
    user_id = uuid.UUID(claims["sub"])
    await service.delete_asset(id, cid, user_id)
    return APIResponse[None](
        success=True,
        message="Asset archived successfully.",
        data=None,
        errors=None,
    )


@router.post(
    "/{id}/assign",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[AssetResponse],
    summary="Assign an asset to an employee",
)
async def assign_asset(
    id: uuid.UUID,
    payload: AssetAssignRequest,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[AssetService, Depends(get_asset_service)],
) -> APIResponse[AssetResponse]:
    """Assign available asset to active employee by employee_id."""
    cid = _get_cid(claims)
    user_id = uuid.UUID(claims["sub"])
    result = await service.assign_asset(id, payload, user_id, cid)
    return APIResponse[AssetResponse](
        success=True,
        message="Asset assigned successfully.",
        data=result,
        errors=None,
    )


@router.post(
    "/{id}/return",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[AssetResponse],
    summary="Return asset to inventory stock room",
)
async def return_asset(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[AssetService, Depends(get_asset_service)],
) -> APIResponse[AssetResponse]:
    """Check back in assigned asset as available in stock room."""
    cid = _get_cid(claims)
    user_id = uuid.UUID(claims["sub"])
    result = await service.return_asset(id, user_id, cid)
    return APIResponse[AssetResponse](
        success=True,
        message="Asset returned successfully.",
        data=result,
        errors=None,
    )


@router.post(
    "/{id}/transfer",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[AssetResponse],
    summary="Transfer assignment to another employee",
)
async def transfer_asset(
    id: uuid.UUID,
    payload: AssetTransferRequest,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[AssetService, Depends(get_asset_service)],
) -> APIResponse[AssetResponse]:
    """Reassign asset assignment seamlessly from current employee to new employee by employee_id."""
    cid = _get_cid(claims)
    user_id = uuid.UUID(claims["sub"])
    result = await service.transfer_asset(id, payload, user_id, cid)
    return APIResponse[AssetResponse](
        success=True,
        message="Asset transferred successfully.",
        data=result,
        errors=None,
    )


@router.post(
    "/{id}/lost",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[AssetResponse],
    summary="Flag asset as lost",
)
async def mark_lost(
    id: uuid.UUID,
    payload: AssetLostRequest,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[AssetService, Depends(get_asset_service)],
) -> APIResponse[AssetResponse]:
    """Flag status as lost with reason and date."""
    cid = _get_cid(claims)
    user_id = uuid.UUID(claims["sub"])
    result = await service.mark_lost(id, payload, user_id, cid)
    return APIResponse[AssetResponse](
        success=True,
        message="Asset marked as lost.",
        data=result,
        errors=None,
    )


@router.post(
    "/{id}/recover",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[AssetResponse],
    summary="Recover a lost asset",
)
async def recover_lost_asset(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[AssetService, Depends(get_asset_service)],
) -> APIResponse[AssetResponse]:
    """Recover a lost asset - transitions back to available status."""
    cid = _get_cid(claims)
    user_id = uuid.UUID(claims["sub"])
    result = await service.recover_lost_asset(id, user_id, cid)
    return APIResponse[AssetResponse](
        success=True,
        message="Asset recovered successfully.",
        data=result,
        errors=None,
    )


@router.post(
    "/{id}/retired",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[AssetResponse],
    summary="Decommission and retire asset",
)
async def mark_retired(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[AssetService, Depends(get_asset_service)],
) -> APIResponse[AssetResponse]:
    """Decommission asset permanently."""
    cid = _get_cid(claims)
    user_id = uuid.UUID(claims["sub"])
    result = await service.mark_retired(id, user_id, cid)
    return APIResponse[AssetResponse](
        success=True,
        message="Asset marked as retired.",
        data=result,
        errors=None,
    )


@router.post(
    "/{id}/maintenance",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[AssetResponse],
    summary="Send asset for maintenance",
)
async def add_maintenance(
    id: uuid.UUID,
    payload: AssetMaintenanceCreate,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[AssetService, Depends(get_asset_service)],
) -> APIResponse[AssetResponse]:
    """Send asset for maintenance (marks as under-repair), record vendor/estimated cost."""
    cid = _get_cid(claims)
    user_id = uuid.UUID(claims["sub"])
    result = await service.add_maintenance(id, payload, user_id, cid)
    return APIResponse[AssetResponse](
        success=True,
        message="Asset sent for maintenance.",
        data=result,
        errors=None,
    )


@router.post(
    "/{id}/maintenance/{maintenance_id}/complete",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[AssetResponse],
    summary="Complete maintenance for an asset",
)
async def complete_maintenance(
    id: uuid.UUID,
    maintenance_id: uuid.UUID,
    payload: AssetMaintenanceComplete,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[AssetService, Depends(get_asset_service)],
) -> APIResponse[AssetResponse]:
    """Complete maintenance - marks asset as available and updates maintenance record with actual cost."""
    cid = _get_cid(claims)
    user_id = uuid.UUID(claims["sub"])
    result = await service.complete_maintenance(id, maintenance_id, payload, user_id, cid)
    return APIResponse[AssetResponse](
        success=True,
        message="Maintenance completed successfully.",
        data=result,
        errors=None,
    )


# Asset Request endpoints
@router.post(
    "/requests",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[AssetRequestResponse],
    summary="Create a new asset request",
)
async def create_asset_request(
    payload: AssetRequestCreate,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AssetService, Depends(get_asset_service)],
) -> APIResponse[AssetRequestResponse]:
    """Employee creates an asset request (NEW_ASSET, REPLACEMENT, PERIPHERAL, UPGRADE, ACCESSORY)."""
    cid = _get_cid(claims)
    employee_id = uuid.UUID(claims["sub"])
    result = await service.create_asset_request(payload, employee_id, cid)
    return APIResponse[AssetRequestResponse](
        success=True,
        message="Asset request created successfully.",
        data=result,
        errors=None,
    )


@router.get(
    "/requests",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[list[AssetRequestResponse]],
    summary="List asset requests",
)
async def list_asset_requests(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AssetService, Depends(get_asset_service)],
    status_filter: str | None = Query(None, alias="status", description="Filter by request status"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
) -> APIResponse[list[AssetRequestResponse]]:
    """List asset requests. Employees see own requests; admins see all."""
    cid = _get_cid(claims)
    role = claims.get("role", "").lower()
    employee_id = uuid.UUID(claims["sub"]) if role not in {"super_admin", "hr_admin", "it_admin", "manager", "executive"} else None
    items, total = await service.list_asset_requests(cid, employee_id=employee_id, status=status_filter, page=page, limit=limit)
    return APIResponse[list[AssetRequestResponse]](
        success=True,
        message="Asset requests retrieved successfully.",
        data=items,
        errors=None,
    )


@router.post(
    "/requests/{request_id}/approve",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[AssetRequestResponse],
    summary="Approve an asset request",
)
async def approve_asset_request(
    request_id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[AssetService, Depends(get_asset_service)],
) -> APIResponse[AssetRequestResponse]:
    """Approve a pending asset request (Admin/HR/IT only)."""
    cid = _get_cid(claims)
    approver_id = uuid.UUID(claims["sub"])
    result = await service.approve_asset_request(request_id, approver_id, cid)
    return APIResponse[AssetRequestResponse](
        success=True,
        message="Asset request approved successfully.",
        data=result,
        errors=None,
    )


@router.post(
    "/requests/{request_id}/reject",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[AssetRequestResponse],
    summary="Reject an asset request",
)
async def reject_asset_request(
    request_id: uuid.UUID,
    payload: AssetRequestUpdate,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[AssetService, Depends(get_asset_service)],
) -> APIResponse[AssetRequestResponse]:
    """Reject a pending asset request with reason (Admin/HR/IT only)."""
    cid = _get_cid(claims)
    approver_id = uuid.UUID(claims["sub"])
    rejection_reason = payload.rejection_reason or "No reason provided"
    result = await service.reject_asset_request(request_id, approver_id, rejection_reason, cid)
    return APIResponse[AssetRequestResponse](
        success=True,
        message="Asset request rejected.",
        data=result,
        errors=None,
    )


@router.post(
    "/requests/{request_id}/fulfill",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[AssetRequestResponse],
    summary="Fulfill an approved asset request by assigning an asset",
)
async def fulfill_asset_request(
    request_id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[AssetService, Depends(get_asset_service)],
    asset_id: uuid.UUID = Query(..., description="Asset ID to assign"),
) -> APIResponse[AssetRequestResponse]:
    """Fulfill an approved asset request by assigning a specific available asset (Admin/HR/IT only)."""
    cid = _get_cid(claims)
    result = await service.fulfill_asset_request(request_id, asset_id, cid)
    return APIResponse[AssetRequestResponse](
        success=True,
        message="Asset request fulfilled successfully.",
        data=result,
        errors=None,
    )


# Asset Damage Report endpoints
@router.post(
    "/damage-reports",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[AssetDamageReportResponse],
    summary="Report asset damage",
)
async def create_damage_report(
    payload: AssetDamageReportCreate,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AssetService, Depends(get_asset_service)],
) -> APIResponse[AssetDamageReportResponse]:
    """Employee reports damage to an assigned asset."""
    cid = _get_cid(claims)
    reported_by_id = uuid.UUID(claims["sub"])
    result = await service.create_damage_report(payload, reported_by_id, cid)
    return APIResponse[AssetDamageReportResponse](
        success=True,
        message="Damage report created successfully.",
        data=result,
        errors=None,
    )


@router.get(
    "/damage-reports",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[list[AssetDamageReportResponse]],
    summary="List damage reports",
)
async def list_damage_reports(
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[AssetService, Depends(get_asset_service)],
    asset_id: uuid.UUID | None = Query(None, description="Filter by asset ID"),
    status_filter: str | None = Query(None, alias="status", description="Filter by report status"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
) -> APIResponse[list[AssetDamageReportResponse]]:
    """List damage reports (Admin/HR/IT only)."""
    cid = _get_cid(claims)
    items, total = await service.list_damage_reports(cid, asset_id=asset_id, status=status_filter, page=page, limit=limit)
    return APIResponse[list[AssetDamageReportResponse]](
        success=True,
        message="Damage reports retrieved successfully.",
        data=items,
        errors=None,
    )


@router.post(
    "/damage-reports/{report_id}/status",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[AssetDamageReportResponse],
    summary="Update damage report status",
)
async def update_damage_report_status(
    report_id: uuid.UUID,
    status: str = Query(..., description="New status: UNDER_REVIEW, MAINTENANCE_SCHEDULED, REPAIRED, REPLACED, CLOSED"),
    resolution_notes: str | None = Query(None, description="Resolution notes"),
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[AssetService, Depends(get_asset_service)],
) -> APIResponse[AssetDamageReportResponse]:
    """Update damage report status (Admin/HR/IT only)."""
    cid = _get_cid(claims)
    result = await service.update_damage_report_status(report_id, status, resolution_notes, cid)
    return APIResponse[AssetDamageReportResponse](
        success=True,
        message="Damage report status updated successfully.",
        data=result,
        errors=None,
    )
