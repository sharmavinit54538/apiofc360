"""Job Management API routes."""

import uuid
from typing import Annotated
from decimal import Decimal
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, status, Request, Response, HTTPException

from app.api.departments import require_admin_or_hr, require_admin_or_hr_or_manager
from app.core.rbac import require_admin
from app.middleware.auth import get_current_user_claims
from app.db.database import get_db_session
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.audit_log import AuditLog
from app.schemas.auth import APIResponse
from app.schemas.recruitment import (
    JobCreate,
    JobListResponse,
    JobResponse,
    JobUpdate,
    JobPublishResponse,
    JobPublishRequest,
    JobDuplicateRequest,
)
from app.services.recruitment_service import RecruitmentService, get_recruitment_service

# Helper dependency to enforce Recruiter or HR or Admin
async def require_recruiter_or_higher(claims: Annotated[dict, Depends(get_current_user_claims)]) -> dict:
    role = claims.get("role", "").lower()
    if role not in {"admin", "hr", "recruiter", "super_admin", "hr_manager"}:
        from app.core.exceptions import AppException
        raise AppException(message="Access denied. Recruiter, HR or Admin permission required.", status_code=status.HTTP_403_FORBIDDEN)
    return claims


router = APIRouter(prefix="/jobs", tags=["Job Management"])

@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[JobResponse],
    summary="Create a new job posting",
)
async def create_job(
    payload: JobCreate,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
) -> APIResponse[JobResponse]:
    """Create a new job posting in DRAFT state. Admin and HR only."""
    user_id = uuid.UUID(claims["sub"])
    job = await service.create_job(user_id, payload)
    return APIResponse[JobResponse](
        success=True,
        message="Job posting created successfully.",
        data=job,
        errors=None,
    )

@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[JobListResponse],
    summary="List all job postings",
)
async def list_jobs(
    claims: Annotated[dict, Depends(require_admin_or_hr_or_manager)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
    status_filter: str | None = Query(None, alias="status", description="Filter by status (DRAFT/PUBLISHED/CLOSED)"),
    search: str | None = Query(None, description="Search by title or department"),
    department: str | None = Query(None, description="Filter by department"),
    location: str | None = Query(None, description="Filter by location"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
) -> APIResponse[JobListResponse]:
    """List job postings with pagination and filters. Admin, HR, and Managers."""
    result = await service.list_jobs(
        status=status_filter,
        search=search,
        department=department,
        location=location,
        page=page,
        limit=limit,
    )
    return APIResponse[JobListResponse](
        success=True,
        message="Job postings retrieved successfully.",
        data=result,
        errors=None,
    )

@router.get(
    "/{id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[JobResponse],
    summary="Get job posting by ID",
)
async def get_job(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin_or_hr_or_manager)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
) -> APIResponse[JobResponse]:
    """Retrieve details of a job posting. Admin and HR only."""
    job = await service.get_job(id)
    return APIResponse[JobResponse](
        success=True,
        message="Job details retrieved successfully.",
        data=job,
        errors=None,
    )

@router.put(
    "/{id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[JobResponse],
    summary="Update job posting",
)
async def update_job(
    id: uuid.UUID,
    payload: JobUpdate,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
) -> APIResponse[JobResponse]:
    """Update details of a job posting. Admin and HR only."""
    user_id = uuid.UUID(claims["sub"])
    job = await service.update_job(user_id, id, payload)
    return APIResponse[JobResponse](
        success=True,
        message="Job posting updated successfully.",
        data=job,
        errors=None,
    )

@router.delete(
    "/{id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[None],
    summary="Delete a job posting",
)
async def delete_job(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
) -> APIResponse[None]:
    """Soft delete a job posting. Admin only."""
    user_id = uuid.UUID(claims["sub"])
    await service.delete_job(user_id, id)
    return APIResponse[None](
        success=True,
        message="Job posting deleted successfully.",
        data=None,
        errors=None,
    )


@router.get(
    "/{id}/publish",
    response_model=APIResponse[list[JobPublishResponse]],
    summary="Get job publish channels",
)
async def get_publish_channels(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(require_recruiter_or_higher)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
) -> APIResponse[list[JobPublishResponse]]:
    """Retrieve all publish channels for a job posting. Recruiter, HR and Admin."""
    channels = await service.get_job_publish_channels(id)
    return APIResponse[list[JobPublishResponse]](
        success=True,
        message="Job publish channels retrieved successfully.",
        data=channels,
        errors=None,
    )


@router.post(
    "/{id}/publish",
    response_model=APIResponse[JobPublishResponse],
    summary="Publish job on a channel",
)
async def publish_job(
    id: uuid.UUID,
    payload: JobPublishRequest,
    request: Request,
    claims: Annotated[dict, Depends(require_recruiter_or_higher)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[JobPublishResponse]:
    """Publish a job posting to a specific channel. Recruiter, HR and Admin."""
    chan = await service.publish_job_channel(id, payload.channel_name, payload.is_active)
    
    # Sync job status based on active channels
    from app.models.recruitment import JobPublishChannel
    from sqlalchemy import select, and_
    
    stmt = select(JobPublishChannel).where(
        and_(JobPublishChannel.job_id == id, JobPublishChannel.is_active == True)
    )
    res = await db.execute(stmt)
    active_chans = res.scalars().all()
    
    job = await service.repo.get_job_by_id(id)
    if active_chans and job.status != "PUBLISHED":
        await service.update_job_status(id, "PUBLISHED")
    elif not active_chans and job.status == "PUBLISHED":
        await service.update_job_status(id, "DRAFT")

    # Log audit entry
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    user_email = claims.get("email")
    user_id = uuid.UUID(claims["sub"])
    audit = AuditLog(
        user_id=user_id,
        action="PUBLISHED_JOB",
        email=user_email,
        ip_address=ip_address,
        user_agent=user_agent,
        details=f"Channel: {payload.channel_name} status updated to {payload.is_active} for Job ID: {id}",
    )
    db.add(audit)
    await db.commit()

    return APIResponse[JobPublishResponse](
        success=True,
        message=f"Job published to {payload.channel_name} successfully." if payload.is_active else f"Job unpublished from {payload.channel_name} successfully.",
        data=chan,
        errors=None,
    )


@router.post(
    "/{id}/close",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[JobResponse],
    summary="Close job posting",
)
async def close_job(
    id: uuid.UUID,
    request: Request,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[JobResponse]:
    """Transition job status to CLOSED and deactivate publish links. Admin and HR only."""
    await service.close_job_position(id)
    job = await service.repo.get_job_by_id(id)
    
    # Log audit entry
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    user_email = claims.get("email")
    user_id = uuid.UUID(claims["sub"])
    audit = AuditLog(
        user_id=user_id,
        action="CLOSED_JOB",
        email=user_email,
        ip_address=ip_address,
        user_agent=user_agent,
        details=f"Closed Job ID: {id}",
    )
    db.add(audit)
    await db.commit()

    return APIResponse[JobResponse](
        success=True,
        message="Job posting closed successfully.",
        data=JobResponse.model_validate(job),
        errors=None,
    )

@router.post(
    "/{id}/draft",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[JobResponse],
    summary="Draft job posting",
)
async def draft_job(
    id: uuid.UUID,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
) -> APIResponse[JobResponse]:
    """Transition job status to DRAFT. Admin and HR only."""
    job = await service.update_job_status(id, "DRAFT")
    return APIResponse[JobResponse](
        success=True,
        message="Job posting set to draft successfully.",
        data=job,
        errors=None,
    )


from pydantic import BaseModel, Field, field_validator


class JobDescriptionGenRequest(BaseModel):
    title: str = Field(..., min_length=2, description="Job title is required")
    department: str | None = "Engineering"
    employment_type: str | None = "Full-time"
    location: str | None = "Remote"
    skills: list[str] = []
    experience: str | None = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        cleaned = v.strip() if v else ""
        if not cleaned:
            raise ValueError("Job title cannot be empty or blank whitespace.")
        return cleaned


@router.post(
    "/{id}/duplicate",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[JobResponse],
    summary="Duplicate a job posting",
)
async def duplicate_job(
    id: uuid.UUID,
    payload: JobDuplicateRequest,
    request: Request,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[JobResponse]:
    """Duplicate an existing job posting with optional overrides. Admin and HR only."""
    user_id = uuid.UUID(claims["sub"])
    job = await service.duplicate_job_custom(user_id, id, payload)
    
    # Log audit entry
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    user_email = claims.get("email")
    audit = AuditLog(
        user_id=user_id,
        action="DUPLICATED_JOB",
        email=user_email,
        ip_address=ip_address,
        user_agent=user_agent,
        details=f"Duplicated Job ID: {id} to new Job ID: {job.id}",
    )
    db.add(audit)
    await db.commit()

    return APIResponse[JobResponse](
        success=True,
        message="Job posting duplicated successfully.",
        data=job,
        errors=None,
    )


@router.post(
    "/generate-description",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[str],
    summary="Generate AI job description",
)
async def generate_description(
    payload: JobDescriptionGenRequest,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
) -> APIResponse[str]:
    """Generate a structured job description via local Ollama LLM. Admin and HR only."""
    from app.services.recruitment_ai_service import RecruitmentAIService
    ai_service = RecruitmentAIService.get_instance()
    text = await ai_service.get_or_generate_description(
        title=payload.title,
        department=payload.department,
        employment_type=payload.employment_type,
        location=payload.location,
        skills=payload.skills,
        experience=payload.experience,
    )
    return APIResponse[str](
        success=True,
        message="Job description generated successfully",
        data=text,
        errors=None,
    )


class JobAiAutofillRequest(BaseModel):
    title: str = Field(..., min_length=2, description="Job title is required")
    experience: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    currency: str | None = "USD"
    department: str | None = None
    location: str | None = None
    employment_type: str | None = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        cleaned = v.strip() if v else ""
        if not cleaned:
            raise ValueError("Job title cannot be empty or blank whitespace.")
        return cleaned


class JobAiAutofillResponse(BaseModel):
    department: str
    employment_type: str
    location: str
    work_mode: str
    vacancies: int
    skills: list[str]
    description: str
    responsibilities: list[str]
    requirements: list[str]
    benefits: list[str]


@router.post(
    "/ai-autofill",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[JobAiAutofillResponse],
    summary="One-click AI Auto-fill for Create Job",
)
async def ai_autofill(
    payload: JobAiAutofillRequest,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
) -> APIResponse[JobAiAutofillResponse]:
    """Auto-fill job posting fields using local Ollama LLM. Admin and HR only."""
    from app.services.recruitment_ai_service import RecruitmentAIService
    ai_service = RecruitmentAIService.get_instance()
    autofill_data = await ai_service.get_or_generate_autofill(
        title=payload.title,
        experience=payload.experience,
        salary_min=payload.salary_min,
        salary_max=payload.salary_max,
        currency=payload.currency,
    )
    return APIResponse[JobAiAutofillResponse](
        success=True,
        message="Job description generated successfully",
        data=JobAiAutofillResponse(**autofill_data),
        errors=None,
    )


class JobDescriptionModifyRequest(BaseModel):
    current_description: str
    action: str
    custom_instruction: str | None = None


@router.post(
    "/modify-description",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[str],
    summary="Modify AI job description",
)
async def modify_description(
    payload: JobDescriptionModifyRequest,
    claims: Annotated[dict, Depends(require_admin_or_hr)],
) -> APIResponse[str]:
    """Modify the job description using local Ollama LLM (improve, expand, shorten, professional tone, casual tone, custom instruction)."""
    from app.services.ollama_client import ollama_client
    from fastapi import HTTPException
    
    is_healthy = await ollama_client.check_health()
    if not is_healthy:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Local Ollama AI service is currently unavailable.",
        )
    
    action = payload.action.lower()
    desc = payload.current_description
    
    if action == "improve":
        action_prompt = "Improve the formatting, flow, structure and clarity of the job description. Keep the core information and length similar, but make it more polished, engaging, and professional."
    elif action == "expand":
        action_prompt = "Expand the job description. Add more descriptive details, responsibilities, skills, or benefits while preserving the original structure, headings, and formatting."
    elif action == "shorten":
        action_prompt = "Shorten the job description. Make it more concise and punchy, removing redundant information while retaining the essential details and original headings."
    elif action == "professional":
        action_prompt = "Rewrite the job description to have a formal, authoritative, and professional corporate tone."
    elif action == "casual":
        action_prompt = "Rewrite the job description to have a friendly, approachable, enthusiastic, and casual tone suitable for a modern startup."
    elif action == "custom" and payload.custom_instruction:
        action_prompt = f"Modify the job description by applying the following specific instruction: {payload.custom_instruction}"
    else:
        action_prompt = "Refine the job description."

    prompt = f"""You are an expert HR copywriter and technical recruiter.
Modify the following job description according to this instruction:
{action_prompt}

Ensure that you keep the markdown headings intact. Do not output any conversational introduction or conclusion (such as 'Here is the modified job description:'). Return ONLY the updated job description text.

Current Job Description:
{desc}
"""

    response = await ollama_client.generate_completion(
        prompt=prompt,
        system_prompt="You are a professional HR writing assistant. You must rewrite the provided job description text according to the instructions and return only the rewritten markdown text.",
        options={"num_predict": 1024, "temperature": 0.4}
    )
    
    if not response:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="AI failed to modify description. Please check local Ollama logs.",
        )
        
    return APIResponse[str](
        success=True,
        message=f"Job description modified successfully via {action} action.",
        data=response.strip(),
        errors=None,
    )


@router.get(
    "/{id}/sourcing-link",
    summary="Get or auto-generate unique sourcing link",
)
async def get_sourcing_link(
    id: uuid.UUID,
    request: Request,
    claims: Annotated[dict, Depends(require_recruiter_or_higher)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    """Retrieve or automatically generate a unique sourcing link. Recruiter, HR and Admin."""
    link = await service.get_or_create_sourcing_link(id)
    
    # Log audit entry
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    user_email = claims.get("email")
    user_id = uuid.UUID(claims["sub"])
    audit = AuditLog(
        user_id=user_id,
        action="COPIED_LINK",
        email=user_email,
        ip_address=ip_address,
        user_agent=user_agent,
        details=f"Copied sourcing link for Job ID: {id}",
    )
    db.add(audit)
    await db.commit()

    return {
        "url": link
    }


@router.get(
    "/{id}/qr",
    summary="Generate QR code for the job application URL",
)
async def generate_qr(
    id: uuid.UUID,
    request: Request,
    claims: Annotated[dict, Depends(require_recruiter_or_higher)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    """Generate PNG and SVG QR codes for the job application URL. Recruiter, HR and Admin."""
    job = await service.repo.get_job_by_id(id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    apply_url = await service.get_or_create_sourcing_link(id)

    import qrcode
    import qrcode.image.svg
    import os

    os.makedirs("uploads/qrcodes", exist_ok=True)
    png_path = f"uploads/qrcodes/{id}.png"
    svg_path = f"uploads/qrcodes/{id}.svg"

    # Save PNG
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(apply_url)
    qr.make(fit=True)
    img_png = qr.make_image(fill_color="black", back_color="white")
    img_png.save(png_path)

    # Save SVG
    factory = qrcode.image.svg.SvgImage
    img_svg = qrcode.make(apply_url, image_factory=factory)
    img_svg.save(svg_path)

    # Log audit entry
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    user_email = claims.get("email")
    user_id = uuid.UUID(claims["sub"])
    audit = AuditLog(
        user_id=user_id,
        action="GENERATED_QR",
        email=user_email,
        ip_address=ip_address,
        user_agent=user_agent,
        details=f"Generated Job QR Code for Job ID: {id}",
    )
    db.add(audit)
    await db.commit()

    return {
        "qr_png_url": f"/uploads/qrcodes/{id}.png",
        "qr_svg_url": f"/uploads/qrcodes/{id}.svg",
        "apply_url": apply_url
    }


@router.get(
    "/{id}/applicants/export",
    summary="Export job applicants report",
)
async def export_applicants(
    id: uuid.UUID,
    request: Request,
    claims: Annotated[dict, Depends(require_recruiter_or_higher)],
    service: Annotated[RecruitmentService, Depends(get_recruitment_service)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    format: str = Query("csv", description="Format (csv, excel, pdf)"),
    filter: str = Query("all", description="Filter stage (all, shortlisted, interviewed, rejected, selected)"),
):
    """Export the list of applicants for a job posting. Recruiter, HR and Admin."""
    from app.models.recruitment import Application
    from sqlalchemy import select
    
    job = await service.repo.get_job_by_id(id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    query = select(Application).where(Application.job_id == id)
    stage_filter = filter.lower()
    if stage_filter == "shortlisted":
        query = query.where(Application.status.in_(["SHORTLISTED", "shortlisted", "assessment", "interview", "technical", "hr"]))
    elif stage_filter == "interviewed":
        query = query.where(Application.status.in_(["INTERVIEWED", "interviewed", "interview", "technical"]))
    elif stage_filter == "rejected":
        query = query.where(Application.status.in_(["REJECTED", "rejected"]))
    elif stage_filter == "selected":
        query = query.where(Application.status.in_(["SELECTED", "selected", "hired", "HIRED"]))

    res = await db.execute(query)
    apps = res.scalars().all()

    # Log audit entry
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    user_email = claims.get("email")
    user_id = uuid.UUID(claims["sub"])
    audit = AuditLog(
        user_id=user_id,
        action="DOWNLOADED_APPLICANTS",
        email=user_email,
        ip_address=ip_address,
        user_agent=user_agent,
        details=f"Exported applicants for Job ID: {id} in {format.upper()} format. Filter: {stage_filter}.",
    )
    db.add(audit)
    await db.commit()

    import io
    if format.lower() == "csv":
        import csv
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Name", "Email", "Phone", "Location", "Experience (Years)", "Status", "Applied Date"])
        for app in apps:
            writer.writerow([
                f"{app.first_name} {app.last_name}",
                app.email,
                app.phone,
                f"{app.city}, {app.country}",
                float(app.experience_years),
                app.status,
                app.created_at.strftime("%Y-%m-%d") if app.created_at else ""
            ])
        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=job_{id}_applicants.csv"}
        )

    elif format.lower() == "excel":
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Applicants"
        
        # Headers
        headers = ["Name", "Email", "Phone", "Location", "Experience (Years)", "Status", "Applied Date"]
        ws.append(headers)
        
        for app in apps:
            ws.append([
                f"{app.first_name} {app.last_name}",
                app.email,
                app.phone,
                f"{app.city}, {app.country}",
                float(app.experience_years),
                app.status,
                app.created_at.strftime("%Y-%m-%d") if app.created_at else ""
            ])
            
        buffer = io.BytesIO()
        wb.save(buffer)
        buffer.seek(0)
        return Response(
            content=buffer.getvalue(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename=job_{id}_applicants.xlsx"}
        )

    elif format.lower() == "pdf":
        from reportlab.lib.pagesizes import letter, landscape
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib import colors

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=landscape(letter), rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
        elements = []

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'TitleStyle',
            parent=styles['Heading1'],
            fontSize=16,
            spaceAfter=15,
            textColor=colors.HexColor("#1E293B")
        )
        elements.append(Paragraph(f"Applicants Report - {job.title}", title_style))
        elements.append(Spacer(1, 10))

        data = [["Name", "Email", "Phone", "Location", "Exp (Yrs)", "Status", "Applied Date"]]
        for app in apps:
            data.append([
                f"{app.first_name} {app.last_name}",
                app.email,
                app.phone,
                f"{app.city}, {app.country}",
                str(app.experience_years),
                app.status,
                app.created_at.strftime("%Y-%m-%d") if app.created_at else ""
            ])

        t = Table(data)
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#F1F5F9")),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor("#1E293B")),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        elements.append(t)
        doc.build(elements)
        buffer.seek(0)
        return Response(
            content=buffer.getvalue(),
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=job_{id}_applicants.pdf"}
        )

    else:
        raise HTTPException(status_code=400, detail="Invalid format. Supported formats: csv, excel, pdf")


