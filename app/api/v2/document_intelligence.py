"""FastAPI API v2 router for the Document Analysis Intelligence Engine."""

from __future__ import annotations

import os
import uuid
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Query, UploadFile, status, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import require_admin_or_manager
from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.auth import APIResponse
from app.services.document_intelligence_service import DocumentIntelligenceService
from app.rag.doc_rag_pipeline import get_rag_pipeline
from app.core.config import settings

import logging

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/document-intelligence",
    tags=["Document Intelligence v2"],
    dependencies=[Depends(require_admin_or_manager)],
)

# Schema models
class ClassifyRequest(BaseModel):
    document_id: uuid.UUID
    model: Optional[str] = None

class ExtractRequest(BaseModel):
    document_id: uuid.UUID
    extraction_schema: str = Field(..., description="Target JSON extraction schema representation", alias="schema_json")
    model: Optional[str] = None

class AnalyzeRequest(BaseModel):
    document_id: uuid.UUID
    model: Optional[str] = None

class CompareRequest(BaseModel):
    left_document_id: uuid.UUID
    right_document_id: uuid.UUID
    model: Optional[str] = None

class ValidateRequest(BaseModel):
    document_id: uuid.UUID

class SearchRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=500)
    top_k: int = Field(10, ge=1, le=50)

class QueryRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=500)
    document_ids: list[uuid.UUID] = Field(..., min_items=1, max_items=20)
    model: Optional[str] = None


@router.post(
    "/upload",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse[dict],
    summary="Upload and register business documents",
)
async def upload_documents(
    files: list[UploadFile],
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Upload documents (bulk supported). Triggers file deduplication (checksum validation)."""
    user_id = uuid.UUID(claims["sub"]) if claims else None
    company_id = uuid.UUID(claims.get("company_id")) if claims and claims.get("company_id") else None

    svc = DocumentIntelligenceService(db)
    results = []
    
    # Save folder
    os.makedirs(settings.RESUME_UPLOAD_DIR, exist_ok=True)  # Reuse configured uploads dir

    for file in files:
        doc_id = uuid.uuid4()
        _, ext = os.path.splitext(file.filename or "")
        safe_name = f"{doc_id}{ext}"
        file_path = os.path.join(settings.RESUME_UPLOAD_DIR, safe_name)

        # Read content
        content = await file.read()
        if len(content) > settings.MAX_RESUME_SIZE_MB * 1024 * 1024:
            results.append({
                "filename": file.filename,
                "status": "FAILED",
                "error": f"File size exceeds limit of {settings.MAX_RESUME_SIZE_MB}MB."
            })
            continue

        with open(file_path, "wb") as f:
            f.write(content)

        try:
            registered_id, is_duplicate = await svc.register_document(
                file_path=file_path,
                file_name=file.filename or safe_name,
                uploaded_by=user_id,
                company_id=company_id,
            )

            # Clean up current uploaded file if it was a duplicate of a previously stored path
            if is_duplicate:
                try:
                    os.unlink(file_path)
                except OSError:
                    pass

            results.append({
                "filename": file.filename,
                "document_id": registered_id,
                "status": "DUPLICATE" if is_duplicate else "REGISTERED",
                "message": "Duplicate document detected. Metadata referenced to existing copy." if is_duplicate else "Successfully registered."
            })
        except Exception as exc:
            logger.error("Failed to register document %s: %s", file.filename, exc)
            results.append({
                "filename": file.filename,
                "status": "FAILED",
                "error": str(exc)
            })

    return APIResponse[dict](
        success=True,
        message=f"Upload run complete. Processed {len(files)} files.",
        data={"results": results},
        errors=None
    )


@router.post(
    "/classify",
    response_model=APIResponse[dict],
    summary="Automatically classify document content type",
)
async def classify_document(
    body: ClassifyRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Execute classification checks (Resume, PAN, Aadhaar, Invoice, GST, Contract, etc.)."""
    user_id = uuid.UUID(claims["sub"]) if claims else None
    svc = DocumentIntelligenceService(db)

    try:
        # Run full process (extracts text, runs classification, extracts base fields)
        res = await svc.process_document(doc_uuid=body.document_id, model=body.model)

        # Index text in RAG vector store for QA & Search if successful
        if res.get("status") == "COMPLETED":
            from app.models.ai_document_analysis import AnalyzedDocument
            doc_res = await db.execute(select(AnalyzedDocument).where(AnalyzedDocument.id == body.document_id))
            doc = doc_res.scalar_one_or_none()
            if doc and doc.raw_text:
                rag = get_rag_pipeline()
                await rag.index_document_text(
                    doc_id=str(doc.id),
                    text=doc.raw_text,
                    metadata={
                        "file_name": doc.file_name,
                        "classification": doc.classification,
                        "company_id": str(doc.company_id) if doc.company_id else None
                    }
                )
                doc.embedding_indexed = True
                await db.commit()

        return APIResponse[dict](
            success=True,
            message="Document classified successfully.",
            data=res,
            errors=None
        )
    except Exception as exc:
        logger.error("Classification run failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Classification failed: {str(exc)}"
        )


@router.post(
    "/extract",
    response_model=APIResponse[dict],
    summary="Extract fields matching requested schema",
)
async def extract_document_fields(
    body: ExtractRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Perform JSON field extraction matching custom user schema specifications."""
    from app.models.ai_document_analysis import AnalyzedDocument
    user_id = uuid.UUID(claims["sub"]) if claims else None

    # Load doc
    res = await db.execute(select(AnalyzedDocument).where(AnalyzedDocument.id == body.document_id))
    doc = res.scalar_one_or_none()
    if not doc or not doc.raw_text:
        raise HTTPException(status_code=404, detail="Document not classified or processed yet.")

    svc = DocumentIntelligenceService(db)
    extracted = await svc.extract_fields(doc.raw_text, body.extraction_schema, body.model)

    # Save to DB
    doc.extracted_data = extracted
    await db.commit()

    await svc.log_audit(
        user_id=user_id,
        doc_id=doc.id,
        action="EXTRACT",
        details="Extracted custom JSON schema fields"
    )

    return APIResponse[dict](
        success=True,
        message="Fields extracted successfully.",
        data={"extracted_data": extracted},
        errors=None
    )


@router.post(
    "/analyze",
    response_model=APIResponse[dict],
    summary="Generate document summary, risk levels, compliance analysis",
)
async def analyze_document(
    body: AnalyzeRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Execute risk audit, executive summary, and recommendations generator."""
    svc = DocumentIntelligenceService(db)
    try:
        report = await svc.analyze_document_compliance(doc_uuid=body.document_id, model=body.model)
        return APIResponse[dict](
            success=True,
            message="Document compliance analysis complete.",
            data=report,
            errors=None
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post(
    "/compare",
    response_model=APIResponse[dict],
    summary="Compare two business documents for modifications",
)
async def compare_documents(
    body: CompareRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Analyze modifications, deletions, similarity score, and additions."""
    user_id = uuid.UUID(claims["sub"]) if claims else None
    svc = DocumentIntelligenceService(db)

    try:
        res = await svc.compare_documents(
            left_uuid=body.left_document_id,
            right_uuid=body.right_document_id,
            user_uuid=user_id,
            model=body.model
        )
        return APIResponse[dict](
            success=True,
            message="Document comparison successful.",
            data=res,
            errors=None
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post(
    "/validate",
    response_model=APIResponse[dict],
    summary="Run validation checks on extracted details",
)
async def validate_document_fields(
    body: ValidateRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Run integrity verification rules (Verhoeff Aadhaar, PAN, GSTIN regex)."""
    from app.models.ai_document_analysis import AnalyzedDocument
    user_id = uuid.UUID(claims["sub"]) if claims else None

    # Load document
    res = await db.execute(select(AnalyzedDocument).where(AnalyzedDocument.id == body.document_id))
    doc = res.scalar_one_or_none()
    if not doc or not doc.extracted_data:
        raise HTTPException(status_code=404, detail="Document extraction data not found.")

    val_results = DocumentValidator.validate_extracted_fields(doc.classification or "CUSTOM", doc.extracted_data)
    
    # Calculate state
    invalid_count = sum(1 for v in val_results.values() if not v.get("valid", True))
    status_str = "VALID" if invalid_count == 0 else "INVALID"

    doc.validation_results = val_results
    doc.validation_status = status_str
    await db.commit()

    svc = DocumentIntelligenceService(db)
    await svc.log_audit(
        user_id=user_id,
        doc_id=doc.id,
        action="VALIDATE",
        details=f"Executed validation. Verdict: {status_str}"
    )

    return APIResponse[dict](
        success=True,
        message=f"Validation run completed. Verdict: {status_str}",
        data={
            "document_id": str(body.document_id),
            "validation_status": status_str,
            "results": val_results
        },
        errors=None
    )


@router.post(
    "/search",
    response_model=APIResponse[dict],
    summary="Semantic vector search across candidate/business files",
)
async def semantic_search(
    body: SearchRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
) -> APIResponse[dict]:
    """Natural language vector search matches."""
    company_id = claims.get("company_id") if claims else None
    filter_meta = {"company_id": company_id} if company_id else None

    rag = get_rag_pipeline()
    matches = await rag.semantic_search(
        query=body.query,
        top_k=body.top_k,
        filter_metadata=filter_meta
    )

    formatted = [
        {
            "chunk_id": m["id"],
            "score": round(m["score"], 4),
            "document_id": m["metadata"].get("document_id"),
            "file_name": m["metadata"].get("file_name"),
            "classification": m["metadata"].get("classification"),
            "excerpt": m["metadata"].get("content", "")[:250],
        }
        for m in matches
    ]

    return APIResponse[dict](
        success=True,
        message="Semantic search queries completed.",
        data={"matches": formatted, "count": len(formatted)},
        errors=None
    )


@router.post(
    "/query",
    response_model=APIResponse[dict],
    summary="Natural language Question Answering RAG pipeline",
)
async def query_rag_doc(
    body: QueryRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
) -> APIResponse[dict]:
    """Retrieve top contextual matching blocks and compose an AI Q&A answer."""
    company_id = claims.get("company_id") if claims else None
    doc_ids_str = [str(uid) for uid in body.document_ids]

    rag = get_rag_pipeline()
    res = await rag.answer_question(
        question=body.question,
        document_ids=doc_ids_str,
        company_id=company_id,
        model=body.model
    )

    return APIResponse[dict](
        success=True,
        message="RAG Question Answering processed successfully.",
        data=res,
        errors=None
    )


@router.get(
    "/insights",
    response_model=APIResponse[dict],
    summary="Retrieve global intelligence insights for all documents",
)
async def get_insights(
    claims: Annotated[dict, Depends(get_current_user_claims)] = None,
    db: Annotated[AsyncSession, Depends(get_db_session)] = None,
) -> APIResponse[dict]:
    """Retrieve compliance stats, trends, risks, duplicate document lists, and health scores."""
    from app.models.ai_document_analysis import AnalyzedDocument

    # Get totals
    count_res = await db.execute(select(func.count(AnalyzedDocument.id)))
    total_docs = count_res.scalar() or 0

    # Get classification breakdown
    class_res = await db.execute(
        select(AnalyzedDocument.classification, func.count(AnalyzedDocument.id))
        .group_by(AnalyzedDocument.classification)
    )
    classifications = {row[0] or "UNCLASSIFIED": row[1] for row in class_res.all()}

    # Get health score average
    avg_health_res = await db.execute(select(func.avg(AnalyzedDocument.health_score)))
    avg_health = avg_health_res.scalar() or 1.0

    # Get validation status breakdown
    val_res = await db.execute(
        select(AnalyzedDocument.validation_status, func.count(AnalyzedDocument.id))
        .group_by(AnalyzedDocument.validation_status)
    )
    validation_stats = {row[0] or "UNVALIDATED": row[1] for row in val_res.all()}

    # Find duplicates count
    dup_res = await db.execute(
        select(AnalyzedDocument.file_checksum)
        .group_by(AnalyzedDocument.file_checksum)
        .having(func.count(AnalyzedDocument.id) > 1)
    )
    dup_checksums = dup_res.scalars().all()

    return APIResponse[dict](
        success=True,
        message="Intelligence insights metrics loaded.",
        data={
            "total_documents": total_docs,
            "average_health_score": round(float(avg_health), 3),
            "classifications": classifications,
            "validation_stats": validation_stats,
            "potential_duplicate_checksums_count": len(dup_checksums),
        },
        errors=None
    )
