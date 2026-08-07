"""API endpoints for employee self-service onboarding wizard."""
from __future__ import annotations
import logging
import uuid
import os
from typing import Any, Dict, List, Optional
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.models.employee import Employee
from app.models.employee_document import EmployeeDocument
from app.services.employee_onboarding_service import EmployeeOnboardingService
from app.schemas.employee_onboarding import (
    EmployeeOnboardingAPIResponse,
    EmployeeOnboardingStatus,
    PersonalInfoInput,
    IdentityVerificationInput,
    EmploymentDetailsInput,
    EducationDetailsInput,
    ExperienceDetailsInput,
    BankDetailsInput,
    TaxNomineeInput,
    PoliciesAcceptanceInput,
    EmployeeOnboardingDraft
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/employee-onboarding", tags=["Employee Onboarding"])

# Supported file configurations
ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".docx"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
UPLOAD_DIR = "uploads/onboarding_documents"

async def get_current_employee(
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db_session)
) -> Employee:
    """Helper dependency to retrieve employee profile from claims."""
    user_id = uuid.UUID(claims["sub"])
    svc = EmployeeOnboardingService(db)
    emp = await svc.get_employee_by_user_id(user_id)
    if not emp:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee profile not found for current authenticated user."
        )
    return emp

@router.get("/status", response_model=EmployeeOnboardingAPIResponse[EmployeeOnboardingStatus])
async def get_status(
    emp: Employee = Depends(get_current_employee),
    db: AsyncSession = Depends(get_db_session)
):
    """Retrieve completion status of onboarding steps."""
    svc = EmployeeOnboardingService(db)
    status_data = await svc.get_onboarding_status(emp)
    
    return EmployeeOnboardingAPIResponse(
        success=True,
        message="Onboarding status retrieved successfully.",
        current_step=emp.employee_onboarding_step,
        onboarding_completed=emp.employee_onboarding_completed,
        data=status_data
    )

@router.get("/progress", response_model=EmployeeOnboardingAPIResponse[Dict[str, Any]])
async def get_progress(
    emp: Employee = Depends(get_current_employee),
    db: AsyncSession = Depends(get_db_session)
):
    """Fetch current saved onboarding data for all steps."""
    svc = EmployeeOnboardingService(db)
    progress_data = await svc.get_onboarding_progress_data(emp)
    
    return EmployeeOnboardingAPIResponse(
        success=True,
        message="Onboarding progress data retrieved.",
        current_step=emp.employee_onboarding_step,
        onboarding_completed=emp.employee_onboarding_completed,
        data=progress_data
    )

@router.put("/step/1", response_model=EmployeeOnboardingAPIResponse[Dict[str, Any]])
async def save_step_1(
    payload: PersonalInfoInput,
    emp: Employee = Depends(get_current_employee),
    db: AsyncSession = Depends(get_db_session)
):
    """Step 1 - Save Personal Information."""
    svc = EmployeeOnboardingService(db)
    await svc.save_personal_info(emp, payload.dict())
    
    return EmployeeOnboardingAPIResponse(
        success=True,
        message="Personal information saved successfully.",
        current_step=emp.employee_onboarding_step,
        onboarding_completed=emp.employee_onboarding_completed,
        data={}
    )

@router.put("/step/2", response_model=EmployeeOnboardingAPIResponse[Dict[str, Any]])
async def save_step_2(
    payload: IdentityVerificationInput,
    emp: Employee = Depends(get_current_employee),
    db: AsyncSession = Depends(get_db_session)
):
    """Step 2 - Save Identity verification numbers."""
    svc = EmployeeOnboardingService(db)
    await svc.save_identity(emp, payload.dict())
    
    return EmployeeOnboardingAPIResponse(
        success=True,
        message="Identity details saved successfully.",
        current_step=emp.employee_onboarding_step,
        onboarding_completed=emp.employee_onboarding_completed,
        data={}
    )

@router.put("/step/3", response_model=EmployeeOnboardingAPIResponse[Dict[str, Any]])
async def save_step_3(
    payload: EmploymentDetailsInput,
    emp: Employee = Depends(get_current_employee),
    db: AsyncSession = Depends(get_db_session)
):
    """Step 3 - Prefills & updates employment information."""
    svc = EmployeeOnboardingService(db)
    await svc.save_employment_details(emp, payload.dict())
    
    return EmployeeOnboardingAPIResponse(
        success=True,
        message="Employment details updated.",
        current_step=emp.employee_onboarding_step,
        onboarding_completed=emp.employee_onboarding_completed,
        data={}
    )

@router.put("/step/4", response_model=EmployeeOnboardingAPIResponse[Dict[str, Any]])
async def save_step_4(
    payload: EducationDetailsInput,
    emp: Employee = Depends(get_current_employee),
    db: AsyncSession = Depends(get_db_session)
):
    """Step 4 - Save Educational Details."""
    svc = EmployeeOnboardingService(db)
    await svc.save_education(emp, [r.dict() for r in payload.education_records])
    
    return EmployeeOnboardingAPIResponse(
        success=True,
        message="Educational details saved.",
        current_step=emp.employee_onboarding_step,
        onboarding_completed=emp.employee_onboarding_completed,
        data={}
    )

@router.put("/step/5", response_model=EmployeeOnboardingAPIResponse[Dict[str, Any]])
async def save_step_5(
    payload: ExperienceDetailsInput,
    emp: Employee = Depends(get_current_employee),
    db: AsyncSession = Depends(get_db_session)
):
    """Step 5 - Save Professional Experience."""
    svc = EmployeeOnboardingService(db)
    await svc.save_experience(emp, [r.dict() for r in payload.experience_records])
    
    return EmployeeOnboardingAPIResponse(
        success=True,
        message="Professional experience saved.",
        current_step=emp.employee_onboarding_step,
        onboarding_completed=emp.employee_onboarding_completed,
        data={}
    )

@router.put("/step/6", response_model=EmployeeOnboardingAPIResponse[Dict[str, Any]])
async def save_step_6(
    payload: BankDetailsInput,
    emp: Employee = Depends(get_current_employee),
    db: AsyncSession = Depends(get_db_session)
):
    """Step 6 - Save Bank Details."""
    svc = EmployeeOnboardingService(db)
    await svc.save_bank_details(emp, payload.dict())
    
    return EmployeeOnboardingAPIResponse(
        success=True,
        message="Salary bank details saved successfully.",
        current_step=emp.employee_onboarding_step,
        onboarding_completed=emp.employee_onboarding_completed,
        data={}
    )

@router.put("/step/7", response_model=EmployeeOnboardingAPIResponse[Dict[str, Any]])
async def save_step_7(
    payload: TaxNomineeInput,
    emp: Employee = Depends(get_current_employee),
    db: AsyncSession = Depends(get_db_session)
):
    """Step 7 - Save Tax regimes, statutory numbers and Nominee information."""
    svc = EmployeeOnboardingService(db)
    await svc.save_tax_payroll(emp, payload.dict())
    
    return EmployeeOnboardingAPIResponse(
        success=True,
        message="Tax and payroll details saved.",
        current_step=emp.employee_onboarding_step,
        onboarding_completed=emp.employee_onboarding_completed,
        data={}
    )

@router.post("/step/8/upload", response_model=EmployeeOnboardingAPIResponse[Dict[str, Any]])
async def upload_document(
    file: UploadFile = File(...),
    document_type: str = Form(...),
    emp: Employee = Depends(get_current_employee),
    db: AsyncSession = Depends(get_db_session)
):
    """Step 8 - Upload Onboarding Verification Documents."""
    filename = file.filename or "upload"
    _, ext = os.path.splitext(filename.lower())
    
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file format. Supported: {', '.join(ALLOWED_EXTENSIONS)}"
        )
    
    file_bytes = await file.read()
    if len(file_bytes) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File size exceeds maximum allowed limit of 10MB."
        )
    
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    unique_id = uuid.uuid4().hex
    stored_name = f"{emp.id}_{document_type}_{unique_id}{ext}"
    file_path = os.path.join(UPLOAD_DIR, stored_name)
    
    with open(file_path, "wb") as f:
        f.write(file_bytes)
        
    # Check if there are existing active docs of same type
    existing_result = await db.execute(
        select(EmployeeDocument)
        .where(EmployeeDocument.employee_id == emp.id)
        .where(EmployeeDocument.document_type == document_type)
        .where(EmployeeDocument.is_deleted == False)
    )
    existing_docs = existing_result.scalars().all()
    for existing_doc in existing_docs:
        existing_doc.is_deleted = True
        db.add(existing_doc)
        
    safe_title = f"Doc: {document_type}"[:30]
    safe_type = document_type[:30]

    doc = EmployeeDocument(
        employee_id=emp.id,
        title=safe_title,
        document_type=safe_type,
        document_url=f"/uploads/onboarding_documents/{stored_name}",
        file_path=os.path.abspath(file_path),
        file_name=filename[:255] if filename else "upload",
        file_size=len(file_bytes),
        status="PENDING",
        visibility="PRIVATE"
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    
    return EmployeeOnboardingAPIResponse(
        success=True,
        message="Document uploaded successfully.",
        current_step=emp.employee_onboarding_step,
        onboarding_completed=emp.employee_onboarding_completed,
        data={"document_id": str(doc.id), "url": doc.document_url}
    )


@router.delete("/step/8/document/{doc_id}", response_model=EmployeeOnboardingAPIResponse[Dict[str, Any]])
async def delete_document(
    doc_id: uuid.UUID,
    emp: Employee = Depends(get_current_employee),
    db: AsyncSession = Depends(get_db_session)
):
    """Step 8 - Delete an uploaded document before final approval."""
    result = await db.execute(
        select(EmployeeDocument)
        .where(EmployeeDocument.id == doc_id)
        .where(EmployeeDocument.employee_id == emp.id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
        
    doc.is_deleted = True
    db.add(doc)
    await db.commit()
    
    return EmployeeOnboardingAPIResponse(
        success=True,
        message="Document deleted successfully.",
        current_step=emp.employee_onboarding_step,
        onboarding_completed=emp.employee_onboarding_completed,
        data={}
    )

@router.put("/step/8", response_model=EmployeeOnboardingAPIResponse[Dict[str, Any]])
async def save_step_8(
    emp: Employee = Depends(get_current_employee),
    db: AsyncSession = Depends(get_db_session)
):
    """Step 8 - Finalize document upload step."""
    svc = EmployeeOnboardingService(db)
    await svc.mark_documents_uploaded(emp.id)
    
    return EmployeeOnboardingAPIResponse(
        success=True,
        message="Documents finalized.",
        current_step=emp.employee_onboarding_step,
        onboarding_completed=emp.employee_onboarding_completed,
        data={}
    )

@router.put("/step/9", response_model=EmployeeOnboardingAPIResponse[Dict[str, Any]])
async def save_step_9(
    payload: PoliciesAcceptanceInput,
    request: Request,
    emp: Employee = Depends(get_current_employee),
    db: AsyncSession = Depends(get_db_session)
):
    """Step 9 - Policies acceptance signature log."""
    svc = EmployeeOnboardingService(db)
    ip_addr = request.client.host if request.client else None
    await svc.save_policies(emp, [a.dict() for a in payload.acceptances], ip_addr)
    
    return EmployeeOnboardingAPIResponse(
        success=True,
        message="Policies accepted.",
        current_step=emp.employee_onboarding_step,
        onboarding_completed=emp.employee_onboarding_completed,
        data={}
    )

@router.post("/complete", response_model=EmployeeOnboardingAPIResponse[Dict[str, Any]])
async def complete_flow(
    emp: Employee = Depends(get_current_employee),
    db: AsyncSession = Depends(get_db_session)
):
    """Step 10 - Click 'Complete Onboarding' for final validations and status update."""
    svc = EmployeeOnboardingService(db)
    try:
        res = await svc.complete_onboarding(emp)
        return EmployeeOnboardingAPIResponse(
            success=True,
            message="Onboarding workflow completed successfully.",
            current_step=10,
            onboarding_completed=True,
            data=res
        )
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(val_err)
        )

@router.post("/draft", response_model=EmployeeOnboardingAPIResponse[Dict[str, Any]])
async def save_draft_state(
    payload: EmployeeOnboardingDraft,
    emp: Employee = Depends(get_current_employee),
    db: AsyncSession = Depends(get_db_session)
):
    """Allows automatic draft saving from wizard form state."""
    svc = EmployeeOnboardingService(db)
    await svc.save_draft(emp, payload.current_step, payload.draft_data)
    
    return EmployeeOnboardingAPIResponse(
        success=True,
        message="Draft saved successfully.",
        current_step=emp.employee_onboarding_step,
        onboarding_completed=emp.employee_onboarding_completed,
        data={}
    )
