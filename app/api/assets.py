"""Asset Management API Router."""
# Config reload: Cloudinary credentials loaded from .env

from __future__ import annotations
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, UploadFile, File, status

from app.api.departments import require_admin_or_hr
from app.schemas.auth import APIResponse
from app.schemas.asset import (
    AssetCreate,
    AssetUpdate,
    AssetAssignRequest,
    AssetMaintenanceCreate,
    AssetResponse,
    AssetListResponse,
    AssetAnalyticsResponse,
    AssetFilterOptionsResponse,
)
from app.services.asset_service import AssetService, get_asset_service

router = APIRouter(prefix="/assets", tags=["Asset Management"])


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
    result = await service.list_assets(
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
    result = await service.get_analytics()
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
    result = await service.get_filter_options()
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
    user_id = uuid.UUID(claims["sub"])
    result = await service.create_asset(payload, user_id)
    return APIResponse[AssetResponse](
        success=True,
        message="Asset created successfully.",
        data=result,
        errors=None,
    )


@router.get(
    "/public/{id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[AssetResponse],
    summary="Get public details of a single asset for QR scanning",
)
async def get_public_asset(
    id: uuid.UUID,
    service: Annotated[AssetService, Depends(get_asset_service)],
) -> APIResponse[AssetResponse]:
    """Get public details of a specific asset by UUID for QR scanning, without authentication."""
    result = await service.get_asset(id)
    return APIResponse[AssetResponse](
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
    result = await service.get_asset(id)
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
    user_id = uuid.UUID(claims["sub"])
    result = await service.update_asset(id, payload, user_id)
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
    summary="Delete an asset record",
)
async def delete_asset(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[AssetService, Depends(get_asset_service)],
) -> APIResponse[None]:
    """Remove asset from inventory system."""
    await service.delete_asset(id)
    return APIResponse[None](
        success=True,
        message="Asset deleted successfully.",
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
    """Assign available asset to active employee."""
    user_id = uuid.UUID(claims["sub"])
    result = await service.assign_asset(id, payload, user_id)
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
    user_id = uuid.UUID(claims["sub"])
    result = await service.return_asset(id, user_id)
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
    payload: AssetAssignRequest,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[AssetService, Depends(get_asset_service)],
) -> APIResponse[AssetResponse]:
    """Reassign asset assignment seamlessly from current employee to new employee."""
    user_id = uuid.UUID(claims["sub"])
    result = await service.transfer_asset(id, payload, user_id)
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
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[AssetService, Depends(get_asset_service)],
) -> APIResponse[AssetResponse]:
    """Flag status as lost."""
    user_id = uuid.UUID(claims["sub"])
    result = await service.mark_lost(id, user_id)
    return APIResponse[AssetResponse](
        success=True,
        message="Asset marked as lost.",
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
    user_id = uuid.UUID(claims["sub"])
    result = await service.mark_retired(id, user_id)
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
    summary="Add a maintenance log entry",
)
async def add_maintenance(
    id: uuid.UUID,
    payload: AssetMaintenanceCreate,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[AssetService, Depends(get_asset_service)],
) -> APIResponse[AssetResponse]:
    """Send asset to repair and record service cost."""
    user_id = uuid.UUID(claims["sub"])
    result = await service.add_maintenance(id, payload, user_id)
    return APIResponse[AssetResponse](
        success=True,
        message="Asset maintenance recorded.",
        data=result,
        errors=None,
    )
