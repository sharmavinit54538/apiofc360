"""API endpoints for HR Admins to track and verify employee onboarding progress."""
from __future__ import annotations
import logging
import uuid
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.db.database import get_db_session
from app.api.departments import require_admin_or_hr
from app.services.employee_onboarding_service import EmployeeOnboardingService
from app.schemas.auth import APIResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/employee-onboarding", tags=["Admin Employee Onboarding"])

class VerifyDocumentPayload(BaseModel):
    status: str  # "VERIFIED" or "REJECTED"
    comments: Optional[str] = None

@router.get("", response_model=APIResponse[List[Dict[str, Any]]])
async def list_progress(
    claims: dict = Depends(require_admin_or_hr),
    db: AsyncSession = Depends(get_db_session),
    department: Optional[str] = Query(None),
    location: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    search: Optional[str] = Query(None)
):
    """List onboarding status of all employees with optional filters."""
    svc = EmployeeOnboardingService(db)
    records = await svc.list_onboarding_progress(
        department=department,
        location=location,
        status_filter=status_filter,
        search=search
    )
    return APIResponse(
        success=True,
        message="Onboarding progress list retrieved successfully.",
        data=records,
        errors=None
    )

@router.get("/{employee_id}", response_model=APIResponse[Dict[str, Any]])
async def get_progress_details(
    employee_id: uuid.UUID,
    claims: dict = Depends(require_admin_or_hr),
    db: AsyncSession = Depends(get_db_session)
):
    """Retrieve full onboarding data for a specific employee."""
    svc = EmployeeOnboardingService(db)
    emp = await svc.get_employee_by_id(employee_id)
    if not emp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found.")
        
    progress_data = await svc.get_onboarding_progress_data(emp)
    status_data = await svc.get_onboarding_status(emp)
    
    return APIResponse(
        success=True,
        message="Employee onboarding details retrieved.",
        data={
            **progress_data,
            "status": status_data
        },
        errors=None
    )

@router.put("/{employee_id}/document/{doc_id}/verify", response_model=APIResponse[Dict[str, Any]])
async def verify_onboarding_document(
    employee_id: uuid.UUID,
    doc_id: uuid.UUID,
    payload: VerifyDocumentPayload,
    claims: dict = Depends(require_admin_or_hr),
    db: AsyncSession = Depends(get_db_session)
):
    """HR/Admin updates document verification status (VERIFIED/REJECTED) with comments."""
    svc = EmployeeOnboardingService(db)
    verifier_id = uuid.UUID(claims["sub"])
    
    if payload.status not in {"VERIFIED", "REJECTED"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid status. Allowed values: VERIFIED, REJECTED"
        )
        
    try:
        doc = await svc.verify_document(
            employee_id=employee_id,
            document_id=doc_id,
            status=payload.status,
            verifier_id=verifier_id,
            comments=payload.comments
        )
        
        # Send Notification Hooks (simulated)
        logger.info(
            "Document %s for employee %s updated to %s by admin %s", 
            doc_id, employee_id, payload.status, verifier_id
        )
        
        return APIResponse(
            success=True,
            message=f"Document verification status updated to {payload.status}.",
            data={
                "document_id": str(doc.id),
                "status": doc.status,
                "is_verified": doc.is_verified,
                "verified_at": doc.verified_at.isoformat() if doc.verified_at else None
            },
            errors=None
        )
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(val_err)
        )
