"""Document Management API routes."""

from __future__ import annotations

from datetime import date
import logging
import os
from typing import Annotated, Any
import uuid

from fastapi import APIRouter, Depends, Form, Query, Request, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.departments import require_admin_or_hr
from app.core.exceptions import AppException
from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.repositories.document_ocr_repository import DocumentOCRRepository
from app.repositories.employee_repository import EmployeeRepository
from app.schemas.auth import APIResponse
from app.schemas.document import (
    AuditLogResponse,
    CategoryResponse,
    CompanyDocumentCreate,
    CompanyDocumentResponse,
    CompanyDocumentUpdate,
    EmployeeDocumentCreate,
    EmployeeDocumentResponse,
    EmployeeDocumentUpdate,
    RejectPayload,
    ReuploadRequestPayload,
    SignatureRequest,
    SignatureResponse,
    SignDocumentPayload,
    VerificationPayload,
    VersionResponse,
)
from app.schemas.document_ocr import (
    DocumentOCRDetailResponse,
    DocumentOCRListItem,
    DocumentOCRResponse,
)
from app.services.document_access import (
    assert_can_access_company_doc,
    assert_can_access_employee_doc,
    resolve_visible_employee_ids,
)
from app.services.document_service import DocumentService, get_document_service
from app.services.storage_service import StorageService
from app.services.upload_service import DocumentUploadService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["Document Management"])


async def get_upload_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> DocumentUploadService:
    repo = DocumentOCRRepository(session)
    return DocumentUploadService(repo=repo)


def _extract_company_id(claims: dict) -> uuid.UUID | None:
    role = (claims.get("role") or "").lower()
    company_id_raw = claims.get("company_id")
    if role != "super_admin" and not company_id_raw:
        raise AppException(message="Tenant context required.", status_code=status.HTTP_403_FORBIDDEN)
    return uuid.UUID(str(company_id_raw)) if company_id_raw else None


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------

@router.get(
    "/categories",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[list[CategoryResponse]],
    summary="List document categories",
)
async def list_categories(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> APIResponse[list[CategoryResponse]]:
    """List document categories from canonical source. Read-only without inline seeding (Rule 2.5)."""
    cats = await service.repo.list_categories()
    data = [CategoryResponse.model_validate(c) for c in cats]
    return APIResponse[list[CategoryResponse]](
        success=True,
        message="Document categories retrieved.",
        data=data,
        errors=None,
    )


# ---------------------------------------------------------------------------
# Employee Documents
# ---------------------------------------------------------------------------

@router.post(
    "/employees",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[EmployeeDocumentResponse],
    summary="Upload employee document",
)
async def upload_employee_document(
    request: Request,
    file: UploadFile,
    employee_id: uuid.UUID = Form(...),
    category_id: uuid.UUID = Form(...),
    title: str = Form(...),
    description: str | None = Form(None),
    issue_date: date | None = Form(None),
    expiry_date: date | None = Form(None),
    visibility: str = Form("PRIVATE"),
    status_field: str = Form("PENDING"),
    tags: str | None = Form(None),
    auto_verify: bool = Form(False),
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    service: Annotated[DocumentService, Depends(get_document_service)] = None,
) -> APIResponse[EmployeeDocumentResponse]:
    """Upload employee document. Allows HR/Admin and Employee Self-Service (Rule 2.7)."""
    company_id = _extract_company_id(claims)
    uploader_id = uuid.UUID(claims["sub"])
    role = (claims.get("role") or "").lower()

    # Employee Self-Service logic (Rule 2.7)
    if role not in {"super_admin", "hr_admin", "it_admin", "executive"}:
        emp_repo = EmployeeRepository(service.session)
        caller_emp = await emp_repo.get_by_user_id(uploader_id)
        if not caller_emp:
            raise AppException(message="Employee profile not found.", status_code=status.HTTP_403_FORBIDDEN)
        if employee_id != caller_emp.id:
            raise AppException(
                message="Employees can only upload documents for their own profile.",
                status_code=status.HTTP_403_FORBIDDEN,
            )
        status_field = "PENDING"
        auto_verify = False
        allowed_vis = {"PRIVATE", "MANAGER_ONLY", "HR_ONLY"}
        if visibility.upper() not in allowed_vis:
            visibility = "PRIVATE"

    # Input validation (Rule 3.4)
    if expiry_date and issue_date and expiry_date < issue_date:
        raise AppException(message="expiry_date cannot be earlier than issue_date.", status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)

    payload = EmployeeDocumentCreate(
        employee_id=employee_id,
        category_id=category_id,
        title=title,
        description=description,
        issue_date=issue_date,
        expiry_date=expiry_date,
        visibility=visibility,
        status=status_field,
        tags=tags,
    )

    ip_addr = request.client.host if request.client else None
    res = await service.upload_employee_document(
        uploader_id=uploader_id,
        payload=payload,
        file=file,
        company_id=company_id,
        ip_address=ip_addr,
        auto_verify=auto_verify,
    )
    return APIResponse[EmployeeDocumentResponse](
        success=True,
        message="Employee document uploaded successfully.",
        data=res,
        errors=None,
    )


@router.get(
    "/employees",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[list[EmployeeDocumentResponse]],
    summary="List employee documents",
)
async def list_employee_documents(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[DocumentService, Depends(get_document_service)],
    employee_id: uuid.UUID | None = Query(None),
    category_id: uuid.UUID | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    visibility: str | None = Query(None),
    search: str | None = Query(None),
    sort_by: str = Query("created_at"),
    order: str = Query("desc"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
) -> APIResponse[list[EmployeeDocumentResponse]]:
    """List employee documents with centralized RBAC and total count (Rules 1.2, 1.3, 2.3)."""
    company_id = _extract_company_id(claims)

    # Centralized access control (Rule 1.2 & 1.3)
    visible_employee_ids = await resolve_visible_employee_ids(claims, service.session)
    if visible_employee_ids is not None:
        if employee_id is not None:
            if employee_id not in visible_employee_ids:
                raise AppException(message="Access denied to requested employee documents.", status_code=status.HTTP_403_FORBIDDEN)
            allowed_employee_ids = [employee_id]
        else:
            allowed_employee_ids = visible_employee_ids
    else:
        allowed_employee_ids = [employee_id] if employee_id else None

    offset = (page - 1) * limit
    docs, total = await service.list_employee_documents(
        company_id=company_id,
        employee_ids=allowed_employee_ids,
        category_id=category_id,
        status=status_filter,
        visibility=visibility,
        search=search,
        limit=limit,
        offset=offset,
        sort_by=sort_by,
        order=order,
        is_super_admin=(claims.get("role") or "").lower() == "super_admin",
    )

    return APIResponse[list[EmployeeDocumentResponse]](
        success=True,
        message="Employee documents retrieved.",
        data=docs,
        meta={
            "total": total,
            "page": page,
            "limit": limit,
            "has_more": (page * limit) < total,
        },
        errors=None,
    )


@router.get(
    "/employees/{id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[EmployeeDocumentResponse],
    summary="Get employee document details",
)
async def get_employee_document(
    id: uuid.UUID,
    request: Request,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> APIResponse[EmployeeDocumentResponse]:
    """Retrieve details of an employee document with permission check before audit log (Rule 1.6)."""
    company_id = _extract_company_id(claims)
    user_id = uuid.UUID(claims["sub"])
    ip_addr = request.client.host if request.client else None

    res = await service.get_employee_document(
        user_id=user_id,
        doc_uuid=id,
        claims=claims,
        company_id=company_id,
        ip_address=ip_addr,
        action="VIEW",
    )
    return APIResponse[EmployeeDocumentResponse](
        success=True,
        message="Document details retrieved.",
        data=res,
        errors=None,
    )


@router.get(
    "/employees/{id}/download",
    summary="Download employee document file stream",
)
async def download_employee_document(
    id: uuid.UUID,
    request: Request,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[DocumentService, Depends(get_document_service)],
    download: bool = Query(False, description="Set to true to force attachment download"),
) -> FileResponse:
    """Download document file stream safely (Rule 3.3). Never exposes direct server paths."""
    company_id = _extract_company_id(claims)
    user_id = uuid.UUID(claims["sub"])
    ip_addr = request.client.host if request.client else None

    # Verifies access BEFORE download audit log, raises 404 if unauthorized (Rule 1.6)
    await service.get_employee_document(
        user_id=user_id,
        doc_uuid=id,
        claims=claims,
        company_id=company_id,
        ip_address=ip_addr,
        action="DOWNLOAD",
    )

    doc = await service.repo.get_employee_document_by_id(id, company_id=company_id)
    safe_path = service.storage.verify_safe_path(doc.file_path)
    if not os.path.exists(safe_path):
        logger.error("Download employee doc %s: file missing from storage at %s", id, doc.file_path)
        raise AppException(message="File missing from storage.", status_code=status.HTTP_404_NOT_FOUND)

    ext = os.path.splitext(doc.file_name or "")[1].lower()
    media_type = StorageService.infer_mime_type(ext)
    is_inline = not download and (media_type in ["application/pdf", "image/png", "image/jpeg"])
    disposition = "inline" if is_inline else "attachment"
    filename = doc.file_name or f"document{ext or '.pdf'}"

    headers = {
        "Content-Disposition": f'{disposition}; filename="{filename}"',
        "X-Content-Type-Options": "nosniff",
    }
    return FileResponse(
        path=safe_path,
        filename=filename,
        media_type=media_type,
        headers=headers,
    )


@router.put(
    "/employees/{id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[EmployeeDocumentResponse],
    summary="Update employee document / upload revisions",
)
async def update_employee_document(
    id: uuid.UUID,
    request: Request,
    file: UploadFile | None = None,
    title: str | None = Form(None),
    description: str | None = Form(None),
    issue_date: date | None = Form(None),
    expiry_date: date | None = Form(None),
    visibility: str | None = Form(None),
    status_field: str | None = Form(None),
    tags: str | None = Form(None),
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    service: Annotated[DocumentService, Depends(get_document_service)] = None,
) -> APIResponse[EmployeeDocumentResponse]:
    """Update employee document metadata or re-upload revision (Rules 2.2, 2.7)."""
    company_id = _extract_company_id(claims)
    uploader_id = uuid.UUID(claims["sub"])

    if expiry_date and issue_date and expiry_date < issue_date:
        raise AppException(message="expiry_date cannot be earlier than issue_date.", status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)

    payload = EmployeeDocumentUpdate(
        title=title,
        description=description,
        issue_date=issue_date,
        expiry_date=expiry_date,
        visibility=visibility,
        status=status_field,
        tags=tags,
    )

    ip_addr = request.client.host if request.client else None
    res = await service.update_employee_document(
        uploader_id=uploader_id,
        doc_uuid=id,
        payload=payload,
        claims=claims,
        file=file,
        company_id=company_id,
        ip_address=ip_addr,
    )
    return APIResponse[EmployeeDocumentResponse](
        success=True,
        message="Employee document updated.",
        data=res,
        errors=None,
    )


@router.delete(
    "/employees/{id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[None],
    summary="Soft delete employee document",
)
async def delete_employee_document(
    id: uuid.UUID,
    request: Request,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> APIResponse[None]:
    """Soft delete employee document (Rule 2.7)."""
    company_id = _extract_company_id(claims)
    uploader_id = uuid.UUID(claims["sub"])
    ip_addr = request.client.host if request.client else None

    await service.delete_employee_document(
        uploader_id=uploader_id,
        doc_uuid=id,
        claims=claims,
        company_id=company_id,
        ip_address=ip_addr,
    )
    return APIResponse[None](
        success=True,
        message="Document deleted successfully.",
        data=None,
        errors=None,
    )


# ---------------------------------------------------------------------------
# Versions & History Endpoints (Rule 2.8)
# ---------------------------------------------------------------------------

@router.get(
    "/employees/{id}/versions",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[list[VersionResponse]],
    summary="List versions of an employee document",
)
async def list_document_versions(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> APIResponse[list[VersionResponse]]:
    """Get all file revisions for a document (never exposes raw server file paths)."""
    company_id = _extract_company_id(claims)
    versions = await service.list_document_versions(id, claims, company_id=company_id)
    return APIResponse[list[VersionResponse]](
        success=True,
        message="Document versions retrieved.",
        data=versions,
        errors=None,
    )


@router.get(
    "/employees/{id}/versions/{version_number}/download",
    summary="Download specific version of an employee document",
)
async def download_document_version(
    id: uuid.UUID,
    version_number: int,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[DocumentService, Depends(get_document_service)],
    download: bool = Query(False),
) -> FileResponse:
    """Download historical version file stream safely."""
    company_id = _extract_company_id(claims)
    safe_path, filename = await service.get_document_version_file(
        doc_uuid=id,
        version_number=version_number,
        claims=claims,
        company_id=company_id,
    )

    ext = os.path.splitext(filename)[1].lower()
    media_type = StorageService.infer_mime_type(ext)
    is_inline = not download and (media_type in ["application/pdf", "image/png", "image/jpeg"])
    disposition = "inline" if is_inline else "attachment"

    headers = {
        "Content-Disposition": f'{disposition}; filename="{filename}"',
        "X-Content-Type-Options": "nosniff",
    }
    return FileResponse(
        path=safe_path,
        filename=filename,
        media_type=media_type,
        headers=headers,
    )


@router.get(
    "/employees/{id}/history",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[list[AuditLogResponse]],
    summary="Get document audit history",
)
async def get_document_history(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> APIResponse[list[AuditLogResponse]]:
    """Retrieve complete audit trail for a document. Admin and HR only (Rule 2.8)."""
    company_id = _extract_company_id(claims)
    logs = await service.list_document_history(id, claims, company_id=company_id)
    return APIResponse[list[AuditLogResponse]](
        success=True,
        message="Document history retrieved.",
        data=logs,
        errors=None,
    )


# ---------------------------------------------------------------------------
# Company Documents
# ---------------------------------------------------------------------------

@router.post(
    "/company",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[CompanyDocumentResponse],
    summary="Upload company document",
)
async def upload_company_document(
    request: Request,
    file: UploadFile,
    category_id: uuid.UUID = Form(...),
    title: str = Form(...),
    description: str | None = Form(None),
    department: str | None = Form(None),
    branch: str | None = Form(None),
    visibility: str = Form("PUBLIC"),
    claims: Annotated[dict, Depends(require_admin_or_hr)] = None,
    service: Annotated[DocumentService, Depends(get_document_service)] = None,
) -> APIResponse[CompanyDocumentResponse]:
    """Upload company wide document or policy manual. Admin and HR only."""
    company_id = _extract_company_id(claims)
    uploader_id = uuid.UUID(claims["sub"])

    payload = CompanyDocumentCreate(
        category_id=category_id,
        title=title,
        description=description,
        department=department,
        branch=branch,
        visibility=visibility,
    )

    ip_addr = request.client.host if request.client else None
    res = await service.upload_company_document(
        uploader_id=uploader_id,
        payload=payload,
        file=file,
        company_id=company_id,
        ip_address=ip_addr,
    )
    return APIResponse[CompanyDocumentResponse](
        success=True,
        message="Company document uploaded successfully.",
        data=res,
        errors=None,
    )


@router.get(
    "/company",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[list[CompanyDocumentResponse]],
    summary="List company documents",
)
async def list_company_documents(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[DocumentService, Depends(get_document_service)],
    category_id: uuid.UUID | None = Query(None),
    department: str | None = Query(None),
    branch: str | None = Query(None),
    visibility: str | None = Query(None),
    search: str | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
) -> APIResponse[list[CompanyDocumentResponse]]:
    """List company documents with server-side visibility and tenant scoping (Rules 1.4, 1.5, 2.3)."""
    company_id = _extract_company_id(claims)
    role = (claims.get("role") or "").lower()
    is_admin = role in {"super_admin", "hr_admin", "it_admin", "executive"}

    viewer_dept = None
    viewer_branch = None
    if not is_admin:
        emp_repo = EmployeeRepository(service.session)
        emp = await emp_repo.get_by_user_id(uuid.UUID(claims["sub"]))
        if emp:
            viewer_dept = emp.department
            viewer_branch = emp.branch

    offset = (page - 1) * limit
    docs, total = await service.list_company_documents(
        company_id=company_id,
        category_id=category_id,
        department=department,
        branch=branch,
        visibility=visibility,
        search=search,
        limit=limit,
        offset=offset,
        caller_role=role,
        viewer_dept=viewer_dept,
        viewer_branch=viewer_branch,
        is_admin=is_admin,
    )

    return APIResponse[list[CompanyDocumentResponse]](
        success=True,
        message="Company documents retrieved.",
        data=docs,
        meta={
            "total": total,
            "page": page,
            "limit": limit,
            "has_more": (page * limit) < total,
        },
        errors=None,
    )


@router.get(
    "/company/{id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[CompanyDocumentResponse],
    summary="Get company document details",
)
async def get_company_document(
    id: uuid.UUID,
    request: Request,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> APIResponse[CompanyDocumentResponse]:
    """Retrieve details of a company document with scoping check before audit log (Rules 1.5, 1.6)."""
    company_id = _extract_company_id(claims)
    user_id = uuid.UUID(claims["sub"])
    ip_addr = request.client.host if request.client else None

    res = await service.get_company_document(
        user_id=user_id,
        doc_uuid=id,
        claims=claims,
        company_id=company_id,
        ip_address=ip_addr,
        action="VIEW",
    )
    return APIResponse[CompanyDocumentResponse](
        success=True,
        message="Company document details retrieved.",
        data=res,
        errors=None,
    )


@router.get(
    "/company/{id}/download",
    summary="Download company document file stream",
)
async def download_company_document(
    id: uuid.UUID,
    request: Request,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[DocumentService, Depends(get_document_service)],
    download: bool = Query(False),
) -> FileResponse:
    """Download company policy document file stream safely (Rules 1.5, 3.3)."""
    company_id = _extract_company_id(claims)
    user_id = uuid.UUID(claims["sub"])
    ip_addr = request.client.host if request.client else None

    await service.get_company_document(
        user_id=user_id,
        doc_uuid=id,
        claims=claims,
        company_id=company_id,
        ip_address=ip_addr,
        action="DOWNLOAD",
    )

    doc = await service.repo.get_company_document_by_id(id, company_id=company_id)
    safe_path = service.storage.verify_safe_path(doc.file_path)
    if not os.path.exists(safe_path):
        logger.error("Download company doc %s: file missing from storage at %s", id, doc.file_path)
        raise AppException(message="File missing from storage.", status_code=status.HTTP_404_NOT_FOUND)

    ext = os.path.splitext(doc.file_name or "")[1].lower()
    media_type = StorageService.infer_mime_type(ext)
    is_inline = not download and (media_type in ["application/pdf", "image/png", "image/jpeg"])
    disposition = "inline" if is_inline else "attachment"
    filename = doc.file_name or f"document{ext or '.pdf'}"

    headers = {
        "Content-Disposition": f'{disposition}; filename="{filename}"',
        "X-Content-Type-Options": "nosniff",
    }
    return FileResponse(
        path=safe_path,
        filename=filename,
        media_type=media_type,
        headers=headers,
    )


@router.put(
    "/company/{id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[CompanyDocumentResponse],
    summary="Update company document / upload new revision",
)
async def update_company_document(
    id: uuid.UUID,
    request: Request,
    file: UploadFile | None = None,
    title: str | None = Form(None),
    description: str | None = Form(None),
    department: str | None = Form(None),
    branch: str | None = Form(None),
    visibility: str | None = Form(None),
    claims: Annotated[dict, Depends(require_admin_or_hr)] = None,
    service: Annotated[DocumentService, Depends(get_document_service)] = None,
) -> APIResponse[CompanyDocumentResponse]:
    """Update company document metadata or upload revised version file. Admin and HR only (Rule 2.8)."""
    company_id = _extract_company_id(claims)
    uploader_id = uuid.UUID(claims["sub"])
    ip_addr = request.client.host if request.client else None

    payload = CompanyDocumentUpdate(
        title=title,
        description=description,
        department=department,
        branch=branch,
        visibility=visibility,
    )

    res = await service.update_company_document(
        uploader_id=uploader_id,
        doc_uuid=id,
        payload=payload,
        file=file,
        company_id=company_id,
        ip_address=ip_addr,
    )
    return APIResponse[CompanyDocumentResponse](
        success=True,
        message="Company document updated.",
        data=res,
        errors=None,
    )


@router.delete(
    "/company/{id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[None],
    summary="Soft delete company document",
)
async def delete_company_document(
    id: uuid.UUID,
    request: Request,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> APIResponse[None]:
    """Soft delete company document. Admin and HR only."""
    company_id = _extract_company_id(claims)
    uploader_id = uuid.UUID(claims["sub"])
    ip_addr = request.client.host if request.client else None

    await service.delete_company_document(
        uploader_id=uploader_id,
        doc_uuid=id,
        company_id=company_id,
        ip_address=ip_addr,
    )
    return APIResponse[None](
        success=True,
        message="Company document deleted successfully.",
        data=None,
        errors=None,
    )


# ---------------------------------------------------------------------------
# Digital Signatures (Rule 1.8)
# ---------------------------------------------------------------------------

@router.post(
    "/{id}/request-signature",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[SignatureResponse],
    summary="Request signature on a document",
)
async def request_signature(
    id: uuid.UUID,
    payload: SignatureRequest,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> APIResponse[SignatureResponse]:
    """Request digital signature from an employee. Admin and HR only."""
    company_id = _extract_company_id(claims)
    user_id = uuid.UUID(claims["sub"])

    res = await service.request_signature(
        user_id=user_id,
        doc_uuid=id,
        signer_user_id=payload.signer_user_id,
        company_id=company_id,
    )
    return APIResponse[SignatureResponse](
        success=True,
        message="Signature request created successfully.",
        data=res,
        errors=None,
    )


@router.post(
    "/{id}/sign",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[SignatureResponse],
    summary="Sign a document digitally",
)
async def sign_document(
    id: uuid.UUID,
    payload: SignDocumentPayload,
    request: Request,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> APIResponse[SignatureResponse]:
    """Digitally sign a document with anti-tampering hash verification."""
    signer_id = uuid.UUID(claims["sub"])
    ip_addr = request.client.host if request.client else None

    res = await service.sign_document(
        signer_id=signer_id,
        doc_uuid=id,
        device_info=payload.device_info,
        ip_address=ip_addr,
    )
    return APIResponse[SignatureResponse](
        success=True,
        message="Document digitally signed successfully.",
        data=res,
        errors=None,
    )


@router.get(
    "/{id}/signature-status",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[SignatureResponse],
    summary="Get signature status",
)
async def get_signature_status(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> APIResponse[SignatureResponse]:
    """Get status details of signature request with RBAC validation (Rule 1.8)."""
    company_id = _extract_company_id(claims)
    user_id = uuid.UUID(claims["sub"])
    role = (claims.get("role") or "").lower()

    doc = await service.repo.get_employee_document_by_id(id, company_id=company_id)
    if not doc or doc.is_deleted:
        raise AppException(message="Document not found.", status_code=status.HTTP_404_NOT_FOUND)

    sig = await service.repo.get_active_signature_request(id)
    if not sig:
        raise AppException(message="No pending signature request found.", status_code=status.HTTP_404_NOT_FOUND)

    # Authorization: assigned signer, HR/Admin, or viewer with doc access
    is_signer = sig.signer_user_id == user_id
    is_admin = role in {"super_admin", "hr_admin", "it_admin", "executive"}
    if not (is_signer or is_admin):
        await assert_can_access_employee_doc(claims, doc, service.session)

    return APIResponse[SignatureResponse](
        success=True,
        message="Signature status retrieved.",
        data=SignatureResponse.model_validate(sig),
        errors=None,
    )


# ---------------------------------------------------------------------------
# Verification & Re-upload Endpoints (Rule 2.6)
# ---------------------------------------------------------------------------

@router.patch(
    "/{id}/verify",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[EmployeeDocumentResponse],
    summary="Verify / approve employee document",
)
async def verify_document(
    id: uuid.UUID,
    payload: VerificationPayload,
    request: Request,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> APIResponse[EmployeeDocumentResponse]:
    """Verify and approve uploaded employee document. Admin and HR only."""
    company_id = _extract_company_id(claims)
    verifier_id = uuid.UUID(claims["sub"])
    ip_addr = request.client.host if request.client else None

    res = await service.verify_document(
        verifier_id=verifier_id,
        doc_uuid=id,
        action="APPROVED",
        comments=payload.comments,
        company_id=company_id,
        ip_address=ip_addr,
    )
    return APIResponse[EmployeeDocumentResponse](
        success=True,
        message="Document verified and approved.",
        data=res,
        errors=None,
    )


@router.patch(
    "/{id}/reject",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[EmployeeDocumentResponse],
    summary="Reject employee document",
)
async def reject_document(
    id: uuid.UUID,
    payload: RejectPayload,
    request: Request,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> APIResponse[EmployeeDocumentResponse]:
    """Reject uploaded employee document. Comments strictly required (Rule 2.6)."""
    company_id = _extract_company_id(claims)
    verifier_id = uuid.UUID(claims["sub"])
    ip_addr = request.client.host if request.client else None

    res = await service.verify_document(
        verifier_id=verifier_id,
        doc_uuid=id,
        action="REJECTED",
        comments=payload.comments,
        company_id=company_id,
        ip_address=ip_addr,
    )
    return APIResponse[EmployeeDocumentResponse](
        success=True,
        message="Document rejected successfully.",
        data=res,
        errors=None,
    )


@router.patch(
    "/{id}/request-reupload",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[EmployeeDocumentResponse],
    summary="Request re-upload of employee document",
)
async def request_reupload(
    id: uuid.UUID,
    payload: ReuploadRequestPayload,
    request: Request,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> APIResponse[EmployeeDocumentResponse]:
    """Request document re-upload with required comments (Rule 2.6)."""
    company_id = _extract_company_id(claims)
    verifier_id = uuid.UUID(claims["sub"])
    ip_addr = request.client.host if request.client else None

    res = await service.verify_document(
        verifier_id=verifier_id,
        doc_uuid=id,
        action="RE_UPLOAD_REQUESTED",
        comments=payload.comments,
        company_id=company_id,
        ip_address=ip_addr,
    )
    return APIResponse[EmployeeDocumentResponse](
        success=True,
        message="Document re-upload requested.",
        data=res,
        errors=None,
    )


# ---------------------------------------------------------------------------
# Expiry Tracking Endpoints (Rules 2.3, 2.4, 3.6)
# ---------------------------------------------------------------------------

@router.get(
    "/expiring",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[list[EmployeeDocumentResponse]],
    summary="Get documents expiring soon",
)
async def list_expiring_documents(
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[DocumentService, Depends(get_document_service)],
    days: int | None = Query(None, description="Days threshold, defaults to 30"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
) -> APIResponse[list[EmployeeDocumentResponse]]:
    """List documents expiring within configured warning days (30d default). Admin and HR only."""
    company_id = _extract_company_id(claims)
    offset = (page - 1) * limit

    docs, total = await service.list_expiring_documents(
        company_id=company_id,
        days=days,
        limit=limit,
        offset=offset,
    )
    return APIResponse[list[EmployeeDocumentResponse]](
        success=True,
        message="Expiring documents list retrieved.",
        data=docs,
        meta={
            "total": total,
            "page": page,
            "limit": limit,
            "has_more": (page * limit) < total,
        },
        errors=None,
    )


@router.get(
    "/expired",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[list[EmployeeDocumentResponse]],
    summary="Get already expired documents",
)
async def list_expired_documents(
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[DocumentService, Depends(get_document_service)],
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
) -> APIResponse[list[EmployeeDocumentResponse]]:
    """List expired documents. Admin and HR only."""
    company_id = _extract_company_id(claims)
    offset = (page - 1) * limit

    docs, total = await service.list_expired_documents(
        company_id=company_id,
        limit=limit,
        offset=offset,
    )
    return APIResponse[list[EmployeeDocumentResponse]](
        success=True,
        message="Expired documents list retrieved.",
        data=docs,
        meta={
            "total": total,
            "page": page,
            "limit": limit,
            "has_more": (page * limit) < total,
        },
        errors=None,
    )


# ---------------------------------------------------------------------------
# Summary Statistics (Rule 2.4)
# ---------------------------------------------------------------------------

@router.get(
    "/summary",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict[str, int]],
    summary="Get document summary statistics",
)
async def get_document_summary(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> APIResponse[dict[str, int]]:
    """Retrieve document count metrics via a single grouped aggregate query (Rule 2.4)."""
    company_id = _extract_company_id(claims)
    visible_employee_ids = await resolve_visible_employee_ids(claims, service.session)

    summary_metrics = await service.get_summary(
        company_id=company_id,
        employee_ids=visible_employee_ids,
    )
    return APIResponse[dict[str, int]](
        success=True,
        message="Document summary statistics retrieved successfully.",
        data=summary_metrics,
        errors=None,
    )


# ---------------------------------------------------------------------------
# Google Document AI OCR Endpoints (Rule 1.7)
# ---------------------------------------------------------------------------

@router.post(
    "/upload",
    status_code=status.HTTP_201_CREATED,
    response_model=DocumentOCRResponse,
    summary="Upload document for Google Document AI OCR processing",
)
async def upload_document_ocr(
    file: UploadFile,
    document_type: str = Form("generic"),
    claims: Annotated[dict, Depends(require_admin_or_hr)] = None,
    service: Annotated[DocumentUploadService, Depends(get_upload_service)] = None,
) -> DocumentOCRResponse:
    """Upload document file for Document AI OCR processing. Restricted to Admin and HR (Rule 1.7)."""
    company_id = _extract_company_id(claims)
    user_id = uuid.UUID(claims["sub"])

    res = await service.upload_and_process(
        file=file,
        document_type=document_type,
        company_id=company_id,
        uploaded_by=user_id,
    )
    return res


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict[str, Any]],
    summary="List all uploaded OCR documents (OCR History)",
)
async def list_documents_ocr(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[DocumentUploadService, Depends(get_upload_service)],
    document_type: str | None = Query(None, description="Filter by document type"),
    status_filter: str | None = Query(None, alias="status", description="Filter by status"),
    search: str | None = Query(None, description="Search across filename and extracted text"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
) -> APIResponse[dict[str, Any]]:
    """Retrieve list of processed OCR documents. User-scoped for non-admins (Rule 1.7)."""
    role = (claims.get("role") or "").lower()
    is_super_admin = role == "super_admin"
    is_admin = role in {"super_admin", "hr_admin", "it_admin", "executive"}
    company_id = _extract_company_id(claims)

    user_scope = None if is_admin else uuid.UUID(claims["sub"])
    offset = (page - 1) * limit

    records, total = await service.list_documents(
        company_id=company_id,
        document_type=document_type,
        status_filter=status_filter,
        search=search,
        limit=limit,
        offset=offset,
        is_super_admin=is_super_admin,
        user_id=user_scope,
    )

    items = [DocumentOCRListItem.model_validate(r).model_dump(mode="json") for r in records]
    return APIResponse[dict[str, Any]](
        success=True,
        message="OCR history retrieved successfully.",
        data={
            "items": items,
            "total": total,
            "page": page,
            "limit": limit,
        },
        meta={
            "total": total,
            "page": page,
            "limit": limit,
            "has_more": (page * limit) < total,
        },
        errors=None,
    )


@router.get(
    "/{document_id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[DocumentOCRDetailResponse],
    summary="Get document OCR details",
)
async def get_document_ocr_detail(
    document_id: uuid.UUID,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[DocumentUploadService, Depends(get_upload_service)],
) -> APIResponse[DocumentOCRDetailResponse]:
    """Retrieve OCR details. Scoped by user_id for non-admin viewers (Rule 1.7)."""
    role = (claims.get("role") or "").lower()
    is_super_admin = role == "super_admin"
    is_admin = role in {"super_admin", "hr_admin", "it_admin", "executive"}
    company_id = _extract_company_id(claims)
    user_scope = None if is_admin else uuid.UUID(claims["sub"])

    record = await service.get_document_details(
        document_id=document_id,
        company_id=company_id,
        is_super_admin=is_super_admin,
        user_id=user_scope,
    )
    return APIResponse[DocumentOCRDetailResponse](
        success=True,
        message="Document OCR details retrieved successfully.",
        data=DocumentOCRDetailResponse.model_validate(record),
        errors=None,
    )


@router.get(
    "/{document_id}/json",
    status_code=status.HTTP_200_OK,
    summary="Download full OCR JSON response",
)
async def download_document_ocr_json(
    document_id: uuid.UUID,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[DocumentUploadService, Depends(get_upload_service)],
):
    """Download full Google Document AI JSON extraction payload. User-scoped (Rule 1.7)."""
    role = (claims.get("role") or "").lower()
    is_super_admin = role == "super_admin"
    is_admin = role in {"super_admin", "hr_admin", "it_admin", "executive"}
    company_id = _extract_company_id(claims)
    user_scope = None if is_admin else uuid.UUID(claims["sub"])

    record = await service.get_document_details(
        document_id=document_id,
        company_id=company_id,
        is_super_admin=is_super_admin,
        user_id=user_scope,
    )
    export_payload = {
        "document_id": str(record.id),
        "original_filename": record.original_filename,
        "document_type": record.document_type,
        "status": record.status,
        "page_count": record.page_count,
        "text": record.extracted_text,
        "confidence": record.confidence,
        "entities": record.entities or [],
        "tables": record.tables or [],
        "form_fields": record.form_fields or [],
        "pages": record.pages or [],
        "raw_response": record.raw_response or {},
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }
    return JSONResponse(
        content=export_payload,
        headers={
            "Content-Disposition": f'attachment; filename="ocr_{record.id}.json"',
            "X-Content-Type-Options": "nosniff",
        },
    )
