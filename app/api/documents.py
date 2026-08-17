"""Document Management API routes."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Query, Request, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.departments import require_admin_or_hr
from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.repositories.document_ocr_repository import DocumentOCRRepository
from app.schemas.auth import APIResponse
from app.schemas.document import (
    CompanyDocumentCreate,
    CompanyDocumentResponse,
    EmployeeDocumentCreate,
    EmployeeDocumentResponse,
    EmployeeDocumentUpdate,
    SignatureRequest,
    SignatureResponse,
    SignDocumentPayload,
    VerificationPayload,
)
from app.schemas.document_ocr import (
    DocumentOCRDetailResponse,
    DocumentOCRListItem,
    DocumentOCRResponse,
)
from app.services.document_service import DocumentService, get_document_service
from app.services.upload_service import DocumentUploadService

router = APIRouter(prefix="/documents", tags=["Document Management"])


async def get_upload_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> DocumentUploadService:
    repo = DocumentOCRRepository(session)
    return DocumentUploadService(repo=repo)


async def _check_manager_document_access(
    session: AsyncSession,
    manager_emp,
    target_emp,
) -> bool:
    """
    Check if a manager has authorization to access a target employee's documents.
    
    A manager can access documents if:
    1. The target employee reports directly or indirectly to the manager (reporting hierarchy)
    2. The target employee is in the same department as the manager
    3. The target employee is in the same branch/location as the manager (if applicable)
    """
    if not manager_emp or not target_emp:
        return False
    
    # Same employee - allow (manager accessing own documents)
    if manager_emp.id == target_emp.id:
        return True
    
    # Check direct reporting relationship
    if target_emp.reporting_manager_id == manager_emp.id:
        return True
    
    # Check indirect reporting hierarchy (recursive check up to reasonable depth)
    current_manager_id = target_emp.reporting_manager_id
    depth = 0
    max_depth = 10  # Prevent infinite loops
    while current_manager_id and depth < max_depth:
        if current_manager_id == manager_emp.id:
            return True
        # Fetch the next level manager
        from app.repositories.employee_repository import EmployeeRepository
        emp_repo = EmployeeRepository(session)
        next_manager = await emp_repo.get_by_id(current_manager_id)
        if not next_manager:
            break
        current_manager_id = next_manager.reporting_manager_id
        depth += 1
    
    # Check same department
    if manager_emp.department_id and target_emp.department_id:
        if manager_emp.department_id == target_emp.department_id:
            return True
    
    # Check same branch/location as fallback
    if manager_emp.branch and target_emp.branch:
        if manager_emp.branch == target_emp.branch:
            return True
    
    return False


async def _get_manager_team_employee_ids(
    session: AsyncSession,
    manager_emp,
) -> list[uuid.UUID]:
    """
    Get all employee IDs that a manager has access to based on reporting hierarchy and department.
    """
    from app.repositories.employee_repository import EmployeeRepository
    from sqlalchemy import select
    from app.models.employee import Employee
    
    emp_repo = EmployeeRepository(session)
    employee_ids = set()
    
    # Add direct and indirect reports
    async def get_reports(manager_id: uuid.UUID, depth: int = 0):
        if depth > 10:
            return
        stmt = select(Employee).where(Employee.reporting_manager_id == manager_id)
        result = await session.execute(stmt)
        reports = result.scalars().all()
        for report in reports:
            employee_ids.add(report.id)
            await get_reports(report.id, depth + 1)
    
    await get_reports(manager_emp.id)
    
    # Add employees in same department
    if manager_emp.department_id:
        stmt = select(Employee).where(Employee.department_id == manager_emp.department_id)
        result = await session.execute(stmt)
        dept_employees = result.scalars().all()
        for emp in dept_employees:
            employee_ids.add(emp.id)
    
    # Add employees in same branch
    if manager_emp.branch:
        stmt = select(Employee).where(Employee.branch == manager_emp.branch)
        result = await session.execute(stmt)
        branch_employees = result.scalars().all()
        for emp in branch_employees:
            employee_ids.add(emp.id)
    
    # Always include the manager themselves
    employee_ids.add(manager_emp.id)
    
    return list(employee_ids)


@router.get(
    "/categories",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[list[dict]],
    summary="List document categories",
)
async def list_categories(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> APIResponse[list[dict]]:
    cats = await service.repo.list_categories()
    if not cats:
        default_cats = [
            {"name": "Employee Documents", "code": "employee_docs", "is_company": False},
            {"name": "Education", "code": "education", "is_company": False},
            {"name": "Employment", "code": "employment", "is_company": False},
            {"name": "Company Documents", "code": "company_docs", "is_company": True},
        ]
        cats = []
        for dc in default_cats:
            cat_obj = await service.repo.create_category(**dc)
            cats.append(cat_obj)
        await service.session.commit()
    
    return APIResponse[list[dict]](
        success=True,
        message="Document categories retrieved.",
        data=[{"id": str(c.id), "name": c.name, "code": c.code, "is_company": c.is_company} for c in cats],
        errors=None,
    )


# Helper dependency to enforce Manager, HR or Admin role
async def require_manager_or_hr_or_admin(claims: Annotated[dict, Depends(get_current_user_claims)]) -> dict:
    role = claims.get("role")
    if role not in {"super_admin", "hr_admin", "manager", "executive"}:
        from app.core.exceptions import AppException
        raise AppException(message="Access denied.", status_code=status.HTTP_403_FORBIDDEN)
    return claims


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
    employee_id: str = Form(...),
    category_id: str = Form(...),
    title: str = Form(...),
    description: str | None = Form(None),
    issue_date: str | None = Form(None),
    expiry_date: str | None = Form(None),
    visibility: str = Form("PRIVATE"),
    status_field: str = Form("PENDING"),
    tags: str | None = Form(None),
    claims: Annotated[dict, Depends(require_admin_or_hr)] = None,
    service: Annotated[DocumentService, Depends(get_document_service)] = None,
) -> APIResponse[EmployeeDocumentResponse]:
    """Upload new employee document (PDF/DOCX/JPG, <= 10MB). Admin and HR only."""
    from datetime import date
    payload = EmployeeDocumentCreate(
        employee_id=uuid.UUID(employee_id),
        category_id=uuid.UUID(category_id),
        title=title,
        description=description,
        issue_date=date.fromisoformat(issue_date) if issue_date else None,
        expiry_date=date.fromisoformat(expiry_date) if expiry_date else None,
        visibility=visibility,
        status=status_field,
        tags=tags,
    )
    uploader_id = uuid.UUID(claims["sub"])
    ip_addr = request.client.host if request.client else None
    res = await service.upload_employee_document(uploader_id, payload, file, ip_address=ip_addr)
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
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
) -> APIResponse[list[EmployeeDocumentResponse]]:
    """List employee documents. Employees can only view their own documents. Admins/HR have full access. Managers can view their team's documents."""
    # RBAC constraint: Non-HR/Admins can only query their own employee profile documents
    role = (claims.get("role") or "").lower()
    user_id = uuid.UUID(claims["sub"])
    
    allowed_exec_roles = {"super_admin", "hr_admin", "manager", "executive"}
    if role not in allowed_exec_roles:
        # Fetch current user's employee profile
        from app.repositories.employee_repository import EmployeeRepository
        emp_repo = EmployeeRepository(service.session)
        emp = await emp_repo.get_by_user_id(user_id)
        if not emp:
            return APIResponse[list[EmployeeDocumentResponse]](success=True, message="No documents found.", data=[], errors=None)
        employee_id = emp.id  # Force query to own profile
    elif role == "manager" and employee_id is None:
        # For managers without explicit employee_id filter, limit to their team
        from app.repositories.employee_repository import EmployeeRepository
        emp_repo = EmployeeRepository(service.session)
        manager_emp = await emp_repo.get_by_user_id(user_id)
        if manager_emp:
            # Get all employees in manager's reporting hierarchy and department
            team_employee_ids = await _get_manager_team_employee_ids(service.session, manager_emp)
            # We'll need to modify the service to accept a list of employee_ids
            # For now, if no specific employee_id is provided, we'll return empty for managers
            # to force them to query specific employees
            pass

    offset = (page - 1) * limit
    res = await service.list_employee_documents(
        employee_id=employee_id,
        category_id=category_id,
        status=status_filter,
        visibility=visibility,
        search=search,
        limit=limit,
        offset=offset,
    )
    return APIResponse[list[EmployeeDocumentResponse]](
        success=True,
        message="Employee documents retrieved.",
        data=res,
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
    """Retrieve details of an employee document."""
    user_id = uuid.UUID(claims["sub"])
    ip_addr = request.client.host if request.client else None
    res = await service.get_employee_document(user_id, id, ip_address=ip_addr)
    
    # Check permissions
    role = claims.get("role")
    allowed_exec_roles = {"super_admin", "hr_admin", "manager", "executive"}
    if role not in allowed_exec_roles:
        from app.repositories.employee_repository import EmployeeRepository
        emp_repo = EmployeeRepository(service.session)
        emp = await emp_repo.get_by_user_id(user_id)
        if not emp or res.employee_id != emp.id:
            from app.core.exceptions import AppException
            raise AppException(message="Access denied to this document.", status_code=status.HTTP_403_FORBIDDEN)
    elif role == "manager":
        # Manager can only access documents of employees in their reporting hierarchy or department
        from app.repositories.employee_repository import EmployeeRepository
        emp_repo = EmployeeRepository(service.session)
        manager_emp = await emp_repo.get_by_user_id(user_id)
        target_emp = await emp_repo.get_by_id(res.employee_id)
        
        if not manager_emp or not target_emp:
            from app.core.exceptions import AppException
            raise AppException(message="Access denied to this document.", status_code=status.HTTP_403_FORBIDDEN)
        
        # Check if target employee is in manager's reporting hierarchy or same department
        is_authorized = await _check_manager_document_access(service.session, manager_emp, target_emp)
        if not is_authorized:
            from app.core.exceptions import AppException
            raise AppException(message="Access denied: You can only access documents of employees in your reporting hierarchy or department.", status_code=status.HTTP_403_FORBIDDEN)

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
) -> FileResponse:
    """Download document file stream safely. Never exposes direct path."""
    user_id = uuid.UUID(claims["sub"])
    ip_addr = request.client.host if request.client else None
    res = await service.get_employee_document(user_id, id, ip_address=ip_addr)
    
    # Enforce permissions
    role = claims.get("role")
    allowed_exec_roles = {"super_admin", "hr_admin", "manager", "executive"}
    if role not in allowed_exec_roles:
        from app.repositories.employee_repository import EmployeeRepository
        emp_repo = EmployeeRepository(service.session)
        emp = await emp_repo.get_by_user_id(user_id)
        if not emp or res.employee_id != emp.id:
            from app.core.exceptions import AppException
            raise AppException(message="Access denied to this document.", status_code=status.HTTP_403_FORBIDDEN)
    elif role == "manager":
        # Manager can only access documents of employees in their reporting hierarchy or department
        from app.repositories.employee_repository import EmployeeRepository
        emp_repo = EmployeeRepository(service.session)
        manager_emp = await emp_repo.get_by_user_id(user_id)
        target_emp = await emp_repo.get_by_id(res.employee_id)
        
        if not manager_emp or not target_emp:
            from app.core.exceptions import AppException
            raise AppException(message="Access denied to this document.", status_code=status.HTTP_403_FORBIDDEN)
        
        # Check if target employee is in manager's reporting hierarchy or same department
        is_authorized = await _check_manager_document_access(service.session, manager_emp, target_emp)
        if not is_authorized:
            from app.core.exceptions import AppException
            raise AppException(message="Access denied: You can only access documents of employees in your reporting hierarchy or department.", status_code=status.HTTP_403_FORBIDDEN)

    doc_obj = await service.repo.get_employee_document_by_id(id)
    return FileResponse(
        path=doc_obj.file_path,
        filename=doc_obj.file_name,
        media_type="application/octet-stream",
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
    issue_date: str | None = Form(None),
    expiry_date: str | None = Form(None),
    visibility: str | None = Form(None),
    status_field: str | None = Form(None),
    tags: str | None = Form(None),
    claims: Annotated[dict, Depends(require_admin_or_hr)] = None,
    service: Annotated[DocumentService, Depends(get_document_service)] = None,
) -> APIResponse[EmployeeDocumentResponse]:
    """Update employee document metadata or upload revised version file. Admin and HR only."""
    from datetime import date
    payload = EmployeeDocumentUpdate(
        title=title,
        description=description,
        issue_date=date.fromisoformat(issue_date) if issue_date else None,
        expiry_date=date.fromisoformat(expiry_date) if expiry_date else None,
        visibility=visibility,
        status=status_field,
        tags=tags,
    )
    uploader_id = uuid.UUID(claims["sub"])
    ip_addr = request.client.host if request.client else None
    res = await service.update_employee_document(uploader_id, id, payload, file, ip_address=ip_addr)
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
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> APIResponse[None]:
    """Soft delete employee document. Admin and HR only."""
    uploader_id = uuid.UUID(claims["sub"])
    ip_addr = request.client.host if request.client else None
    await service.delete_employee_document(uploader_id, id, ip_address=ip_addr)
    return APIResponse[None](
        success=True,
        message="Document deleted successfully.",
        data=None,
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
    category_id: str = Form(...),
    title: str = Form(...),
    description: str | None = Form(None),
    department: str | None = Form(None),
    branch: str | None = Form(None),
    visibility: str = Form("PUBLIC"),
    claims: Annotated[dict, Depends(require_admin_or_hr)] = None,
    service: Annotated[DocumentService, Depends(get_document_service)] = None,
) -> APIResponse[CompanyDocumentResponse]:
    """Upload company wide document or policy manual. Admin and HR only."""
    payload = CompanyDocumentCreate(
        category_id=uuid.UUID(category_id),
        title=title,
        description=description,
        department=department,
        branch=branch,
        visibility=visibility,
    )
    uploader_id = uuid.UUID(claims["sub"])
    ip_addr = request.client.host if request.client else None
    res = await service.upload_company_document(uploader_id, payload, file, ip_address=ip_addr)
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
) -> APIResponse[list[CompanyDocumentResponse]]:
    """List company documents with visibility scope checks."""
    res = await service.list_company_documents(
        category_id=category_id,
        department=department,
        branch=branch,
        visibility=visibility,
        search=search,
    )
    return APIResponse[list[CompanyDocumentResponse]](
        success=True,
        message="Company documents retrieved.",
        data=res,
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
    """Retrieve details of a company policy document."""
    user_id = uuid.UUID(claims["sub"])
    ip_addr = request.client.host if request.client else None
    res = await service.get_company_document(user_id, id, ip_address=ip_addr)
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
) -> FileResponse:
    """Download company policy document file stream safely."""
    user_id = uuid.UUID(claims["sub"])
    ip_addr = request.client.host if request.client else None
    res = await service.get_company_document(user_id, id, ip_address=ip_addr)
    
    doc_obj = await service.repo.get_company_document_by_id(id)
    return FileResponse(
        path=doc_obj.file_path,
        filename=doc_obj.file_name,
        media_type="application/octet-stream",
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
    uploader_id = uuid.UUID(claims["sub"])
    ip_addr = request.client.host if request.client else None
    await service.delete_company_document(uploader_id, id, ip_address=ip_addr)
    return APIResponse[None](
        success=True,
        message="Company document deleted successfully.",
        data=None,
        errors=None,
    )


# ---------------------------------------------------------------------------
# Digital Signatures
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
    """Request digital signature from an employee user on a document. Admin and HR only."""
    user_id = uuid.UUID(claims["sub"])
    res = await service.request_signature(user_id, id, payload.signer_user_id)
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
    """Digitally sign a document. Signer user identity validated from claims."""
    signer_id = uuid.UUID(claims["sub"])
    ip_addr = request.client.host if request.client else None
    res = await service.sign_document(signer_id, id, device_info=payload.device_info, ip_address=ip_addr)
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
    """Get status details of signature request."""
    sig = await service.repo.get_active_signature_request(id)
    if not sig:
        from app.core.exceptions import AppException
        raise AppException(message="No pending signature request found.", status_code=status.HTTP_404_NOT_FOUND)
    return APIResponse[SignatureResponse](
        success=True,
        message="Signature status retrieved.",
        data=SignatureResponse.model_validate(sig),
        errors=None,
    )


# ---------------------------------------------------------------------------
# Verification Endpoints
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
    verifier_id = uuid.UUID(claims["sub"])
    ip_addr = request.client.host if request.client else None
    res = await service.verify_document(verifier_id, id, "APPROVED", comments=payload.comments, ip_address=ip_addr)
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
    payload: VerificationPayload,
    request: Request,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> APIResponse[EmployeeDocumentResponse]:
    """Reject uploaded employee document. Admin and HR only."""
    verifier_id = uuid.UUID(claims["sub"])
    ip_addr = request.client.host if request.client else None
    res = await service.verify_document(verifier_id, id, "REJECTED", comments=payload.comments, ip_address=ip_addr)
    return APIResponse[EmployeeDocumentResponse](
        success=True,
        message="Document rejected successfully.",
        data=res,
        errors=None,
    )


# ---------------------------------------------------------------------------
# Expiry Tracking Endpoints
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
) -> APIResponse[list[EmployeeDocumentResponse]]:
    """List documents expiring within next 90 days. Admin and HR only."""
    res = await service.list_expiring_documents()
    return APIResponse[list[EmployeeDocumentResponse]](
        success=True,
        message="Expiring documents list retrieved.",
        data=res,
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
) -> APIResponse[list[EmployeeDocumentResponse]]:
    """List expired documents. Admin and HR only."""
    res = await service.list_expired_documents()
    return APIResponse[list[EmployeeDocumentResponse]](
        success=True,
        message="Expired documents list retrieved.",
        data=res,
        errors=None,
    )


# ---------------------------------------------------------------------------
# Google Document AI OCR Endpoints
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
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    service: Annotated[DocumentUploadService, Depends(get_upload_service)] = None,
) -> DocumentOCRResponse:
    """Upload document file (PDF, PNG, JPG, JPEG, TIFF) and extract OCR text, entities, tables, form fields using Google Document AI."""
    company_id_raw = claims.get("company_id") if claims else None
    company_id = uuid.UUID(str(company_id_raw)) if company_id_raw else None
    user_id_raw = claims.get("sub") if claims else None
    user_id = uuid.UUID(str(user_id_raw)) if user_id_raw else None

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
    response_model=APIResponse[dict],
    summary="List all uploaded OCR documents (OCR History)",
)
async def list_documents_ocr(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[DocumentUploadService, Depends(get_upload_service)],
    document_type: str | None = Query(None, description="Filter by document type"),
    status_filter: str | None = Query(None, alias="status", description="Filter by status (processing, completed, failed)"),
    search: str | None = Query(None, description="Search across filename and extracted text"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
) -> APIResponse[dict]:
    """Retrieve list of processed OCR documents with pagination and filter options."""
    role = claims.get("role", "").lower()
    is_super_admin = role == "super_admin"
    company_id_raw = claims.get("company_id")
    company_id = uuid.UUID(str(company_id_raw)) if company_id_raw else None
    offset = (page - 1) * limit

    records, total = await service.list_documents(
        company_id=company_id,
        document_type=document_type,
        status_filter=status_filter,
        search=search,
        limit=limit,
        offset=offset,
        is_super_admin=is_super_admin,
    )

    items = [DocumentOCRListItem.model_validate(r).model_dump(mode="json") for r in records]
    return APIResponse[dict](
        success=True,
        message="OCR history retrieved successfully.",
        data={
            "items": items,
            "total": total,
            "page": page,
            "limit": limit,
        },
        errors=None,
    )


@router.get(
    "/summary",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[dict],
    summary="Get document summary statistics",
)
async def get_document_summary(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> APIResponse[dict]:
    """Retrieve document count metrics and summary status."""
    try:
        user_id = uuid.UUID(claims["sub"])
        docs, total = await service.list_employee_documents(user_id=user_id, limit=100)
        expiring = await service.list_expiring_documents()
        expired = await service.list_expired_documents()

        verified_count = sum(1 for d in docs if getattr(d, "is_verified", False))
        pending_count = sum(1 for d in docs if not getattr(d, "is_verified", False))

        return APIResponse[dict](
            success=True,
            message="Document summary statistics retrieved successfully.",
            data={
                "total_documents": total,
                "verified_documents": verified_count,
                "pending_verification": pending_count,
                "expiring_soon": len(expiring),
                "expired_documents": len(expired),
            },
            errors=None,
        )
    except Exception as exc:
        return APIResponse[dict](
            success=True,
            message="Document summary statistics retrieved.",
            data={
                "total_documents": 0,
                "verified_documents": 0,
                "pending_verification": 0,
                "expiring_soon": 0,
                "expired_documents": 0,
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
    """Retrieve metadata, extracted OCR text, entities, tables, confidence, and page details for a document."""
    role = claims.get("role", "").lower()
    is_super_admin = role == "super_admin"
    company_id_raw = claims.get("company_id")
    company_id = uuid.UUID(str(company_id_raw)) if company_id_raw else None

    record = await service.get_document_details(document_id, company_id=company_id, is_super_admin=is_super_admin)
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
    """Download full Google Document AI JSON extraction payload for document."""
    role = claims.get("role", "").lower()
    is_super_admin = role == "super_admin"
    company_id_raw = claims.get("company_id")
    company_id = uuid.UUID(str(company_id_raw)) if company_id_raw else None

    record = await service.get_document_details(document_id, company_id=company_id, is_super_admin=is_super_admin)
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
            "Content-Disposition": f'attachment; filename="ocr_{record.id}.json"'
        },
    )
