"""Resume Parser API v2 — Upload, OCR, and AI extraction endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Query, UploadFile, status, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.auth import APIResponse
from app.llm.client import get_llm_client, LLMClient
from app.ocr.engine_selector import get_ocr_selector
from app.agents.resume_parser import ResumeParserAgent
from app.core.config import settings

import logging
import os
import shutil

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/resume-parser", tags=["AI Resume Parser v2"])

ALLOWED_EXTENSIONS = set(settings.ALLOWED_RESUME_EXTENSIONS)
MAX_SIZE = settings.MAX_RESUME_SIZE_MB * 1024 * 1024


@router.post(
    "/upload-and-parse",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[dict],
    summary="Upload resume and run full AI parsing pipeline",
    description="""
Upload a resume file (PDF, DOCX, DOC, JPG, PNG, JPEG, TIFF).

**Pipeline:**
1. File validation and secure storage
2. OCR extraction (images) or document parsing (PDF/DOCX)
3. AI-powered structured data extraction via Ollama
4. Store parsed data in database
5. Return structured JSON with all extracted fields

**Extracted fields:** name, email, mobile, address, LinkedIn, GitHub, portfolio,
skills taxonomy, experience timeline, education, certifications, projects,
publications, awards, achievements, salary, notice period.
""",
)
async def upload_and_parse_resume(
    request: Request,
    file: UploadFile,
    candidate_id: str | None = Form(None, description="Optional existing candidate UUID"),
    application_id: str | None = Form(None, description="Optional application UUID"),
    model: str | None = Form(None, description="Ollama model override (e.g. llama3, qwen2.5)"),
    generate_embedding: bool = Form(True, description="Index in vector store after parsing"),
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Upload and AI-parse a candidate resume."""
    # Validate file extension
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"File type '{ext}' not allowed. Accepted: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    # Read and validate file size
    content = await file.read()
    if len(content) > MAX_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File size exceeds {settings.MAX_RESUME_SIZE_MB}MB limit",
        )

    # Save file to disk
    doc_id = uuid.uuid4()
    os.makedirs(settings.RESUME_UPLOAD_DIR, exist_ok=True)
    safe_filename = f"{doc_id}{ext}"
    file_path = os.path.join(settings.RESUME_UPLOAD_DIR, safe_filename)

    with open(file_path, "wb") as f:
        f.write(content)

    # Create DB record
    from app.models.ai_recruitment import AIResumeDocument
    from sqlalchemy import select

    doc = AIResumeDocument(
        id=doc_id,
        file_path=file_path,
        file_name=file.filename or safe_filename,
        file_size=len(content),
        file_type=ext.lstrip("."),
        parse_status="PROCESSING",
        uploaded_by=uuid.UUID(claims["sub"]) if claims else None,
    )
    if candidate_id:
        doc.candidate_id = uuid.UUID(candidate_id)
    if application_id:
        doc.application_id = uuid.UUID(application_id)

    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    # Parse resume
    try:
        llm = get_llm_client()
        ocr = get_ocr_selector()
        agent = ResumeParserAgent(llm_client=llm, ocr_selector=ocr)
        parsed = await agent.parse_file(file_path, model=model)

        # Update record
        from sqlalchemy import update
        await db.execute(
            update(AIResumeDocument)
            .where(AIResumeDocument.id == doc_id)
            .values(
                parsed_data=parsed.to_dict(),
                raw_text=(parsed.raw_text or "")[:10000],
                parse_status="COMPLETED",
                ocr_engine_used=parsed.engine_used,
                candidate_name=parsed.name,
                candidate_email=parsed.email,
                years_experience=parsed.years_experience,
            )
        )
        await db.commit()

        # Auto-create or link Candidate profile
        from app.models.recruitment import Candidate
        cand = None
        email_clean = (parsed.email or "").lower().strip()
        if candidate_id:
            cand_res = await db.execute(select(Candidate).where(Candidate.id == uuid.UUID(candidate_id)))
            cand = cand_res.scalar_one_or_none()
        elif email_clean:
            cand_res = await db.execute(select(Candidate).where(Candidate.email == email_clean))
            cand = cand_res.scalar_one_or_none()

        if not cand:
            names = (parsed.name or "New Candidate").split(" ")
            first_name = names[0]
            last_name = " ".join(names[1:]) if len(names) > 1 else "Candidate"
            cand = Candidate(
                first_name=first_name,
                last_name=last_name,
                email=email_clean or f"no_email_{uuid.uuid4().hex[:6]}@example.com",
                phone=parsed.phone or "0000000000",
                location=parsed.address or "Unknown",
                years_experience=parsed.years_experience or 0.0,
                current_company=parsed.current_company or "",
                current_role=parsed.current_designation or "",
                expected_salary=parsed.expected_salary or 0.0,
                resume_path=file_path,
                resume_name=file.filename or safe_filename,
                source="Resume Intelligence",
                is_talent_pool=True,
            )
            db.add(cand)
            await db.commit()
            await db.refresh(cand)

        # Link document to Candidate
        await db.execute(
            update(AIResumeDocument)
            .where(AIResumeDocument.id == doc_id)
            .values(candidate_id=cand.id)
        )
        # Update candidate summary and skills if empty
        if cand:
            if not cand.summary:
                cand.summary = parsed.summary
            if not cand.skills and parsed.all_skills_flat:
                cand.skills = parsed.all_skills_flat[:30]
        await db.commit()

        # Generate embedding if requested
        embedding_status = "skipped"
        if generate_embedding and parsed.raw_text:
            from app.workers.resume_tasks import dispatch_generate_embedding
            cid = candidate_id or str(doc_id)
            skills = parsed.all_skills_flat
            await dispatch_generate_embedding(cid, parsed.raw_text, parsed.name or "Unknown", skills)
            embedding_status = "indexed"

            # Update flag
            await db.execute(
                update(AIResumeDocument)
                .where(AIResumeDocument.id == doc_id)
                .values(embedding_indexed=True)
            )
            await db.commit()

        # Match candidate against all open jobs in the background
        import asyncio
        from app.services.recruitment_service import RecruitmentService
        # The background task creates its own session internally via AsyncSessionLocal,
        # so we use a throwaway service instance without the request-scoped db session.
        service = RecruitmentService(
            session=None,
            repo=None,
            auth_repo=None,
            employee_repo=None,
            email_service=None
        )
        asyncio.create_task(
            service.match_candidate_against_jobs_task(
                candidate_id=cand.id,
                doc_id=doc_id,
                raw_text=parsed.raw_text or "",
                candidate_metadata={
                    "expected_salary": parsed.to_dict().get("expected_salary"),
                    "notice_period": parsed.to_dict().get("notice_period"),
                    "location": parsed.to_dict().get("address"),
                }
            )
        )

        return APIResponse[dict](
            success=True,
            message="Resume uploaded and parsed successfully.",
            data={
                "resume_document_id": str(doc_id),
                "parse_status": "COMPLETED",
                "ocr_engine_used": parsed.engine_used,
                "embedding_status": embedding_status,
                "parsed_data": parsed.to_dict(),
            },
            errors=None,
        )

    except Exception as exc:
        logger.error("Resume parsing failed for doc %s: %s", doc_id, exc)
        from sqlalchemy import update
        await db.execute(
            update(AIResumeDocument)
            .where(AIResumeDocument.id == doc_id)
            .values(parse_status="FAILED")
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Resume parsing failed: {str(exc)}",
        )


@router.get(
    "/{document_id}",
    response_model=APIResponse[dict],
    summary="Get parsed resume document data",
)
async def get_parsed_resume(
    document_id: uuid.UUID,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Retrieve a previously parsed resume document."""
    from app.models.ai_recruitment import AIResumeDocument
    from sqlalchemy import select

    result = await db.execute(
        select(AIResumeDocument).where(AIResumeDocument.id == document_id)
    )
    doc = result.scalar_one_or_none()

    if not doc:
        raise HTTPException(status_code=404, detail="Resume document not found")

    return APIResponse[dict](
        success=True,
        message="Resume document retrieved.",
        data={
            "id": str(doc.id),
            "file_name": doc.file_name,
            "file_type": doc.file_type,
            "parse_status": doc.parse_status,
            "ocr_engine_used": doc.ocr_engine_used,
            "embedding_indexed": doc.embedding_indexed,
            "parsed_data": doc.parsed_data or {},
            "candidate_name": doc.candidate_name,
            "candidate_email": doc.candidate_email,
            "years_experience": doc.years_experience,
            "created_at": doc.created_at.isoformat(),
        },
        errors=None,
    )


@router.get(
    "/ocr/engines/status",
    response_model=APIResponse[dict],
    summary="Check OCR engine availability",
)
async def get_ocr_status(
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
) -> APIResponse[dict]:
    """Return availability status of all OCR engines."""
    ocr = get_ocr_selector()
    return APIResponse[dict](
        success=True,
        message="OCR engine status retrieved.",
        data=ocr.get_engine_status(),
        errors=None,
    )
