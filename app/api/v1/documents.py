import os
import uuid

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import not_found, validation_error
from app.db.dependencies import CurrentUser, get_current_user, require_permission
from app.db.session import get_db
from app.models.misc import Document
from app.schemas.misc import DocumentOut
from app.services.audit_service import log_action

router = APIRouter(prefix="/documents", tags=["Documents"])

ALLOWED_MIME = {"application/pdf", "image/jpeg", "image/png", "image/webp"}
ALLOWED_EXT = {".pdf", ".jpg", ".jpeg", ".png", ".webp"}


@router.get("", response_model=list[DocumentOut])
async def list_documents(student_id: str | None = None, admission_id: str | None = None,
                          current: CurrentUser = Depends(require_permission("documents:read")), db: AsyncSession = Depends(get_db)):
    q = select(Document).where(Document.tenant_id == current.tenant_id)
    if student_id:
        q = q.where(Document.student_id == student_id)
    if admission_id:
        q = q.where(Document.admission_id == admission_id)
    return (await db.execute(q.order_by(Document.created_at.desc()))).scalars().all()


@router.post("", response_model=DocumentOut, status_code=201)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    document_type: str = Form(...),
    student_id: str | None = Form(default=None),
    admission_id: str | None = Form(default=None),
    current: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXT or (file.content_type not in ALLOWED_MIME):
        raise validation_error("Unsupported file type. Allowed: PDF, JPG, PNG, WEBP")

    body = await file.read()
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if len(body) > max_bytes:
        raise validation_error(f"File exceeds the {settings.MAX_UPLOAD_SIZE_MB}MB limit")

    tenant_dir = os.path.join(settings.UPLOAD_DIR, current.tenant_id)
    os.makedirs(tenant_dir, exist_ok=True)
    storage_key = os.path.join(tenant_dir, f"{uuid.uuid4()}{ext}")
    with open(storage_key, "wb") as f:
        f.write(body)

    doc = Document(
        tenant_id=current.tenant_id, school_id=current.school_id, document_type=document_type,
        student_id=student_id, admission_id=admission_id, file_name=file.filename or "upload",
        storage_key=storage_key, mime_type=file.content_type or "application/octet-stream",
        size=len(body), uploaded_by=current.id,
    )
    db.add(doc)
    await db.flush()
    await log_action(db, request, current.tenant_id, current.id, "upload", "document", doc.id)
    await db.commit()
    await db.refresh(doc)
    return doc


@router.delete("/{document_id}", status_code=204)
async def delete_document(document_id: str, request: Request, current: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    doc = await db.get(Document, document_id)
    if not doc or doc.tenant_id != current.tenant_id:
        raise not_found("Document")
    if current.role != "admin" and doc.uploaded_by != current.id:
        from app.core.exceptions import permission_denied
        raise permission_denied()
    try:
        if os.path.exists(doc.storage_key):
            os.remove(doc.storage_key)
    except OSError:
        pass
    await db.delete(doc)
    await log_action(db, request, current.tenant_id, current.id, "delete", "document", document_id)
    await db.commit()
    return None
