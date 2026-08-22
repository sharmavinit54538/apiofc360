from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import not_found, permission_denied, validation_error
from app.db.dependencies import CurrentUser, get_current_user
from app.db.session import get_db
from app.models.attendance import Attendance
from app.models.misc import FaceProfile, RecognitionLog
from app.models.student import Student
from app.schemas.misc import FaceEnrollResponse, FaceRecognizeResponse
from app.services.audit_service import log_action
from app.services.face_service import average_embeddings, cosine_similarity, deserialize, generate_embedding, serialize, FACE_MODEL_NAME

router = APIRouter(prefix="/face", tags=["Face Recognition"])
MAX_BYTES = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}


async def _read_validated(file: UploadFile) -> bytes:
    if file.content_type not in ALLOWED_TYPES:
        raise validation_error("Only JPEG, PNG, or WEBP images are accepted")
    data = await file.read()
    if not data:
        raise validation_error("No face detected in the provided image")
    if len(data) > MAX_BYTES:
        raise validation_error(f"Image exceeds the {settings.MAX_UPLOAD_SIZE_MB}MB limit")
    return data


@router.post("/enroll", response_model=FaceEnrollResponse)
async def enroll(
    request: Request,
    student_id: str = Form(...),
    samples: list[UploadFile] = File(...),
    current: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current.role not in {"admin", "teacher"}:
        raise permission_denied()

    student = await db.get(Student, student_id)
    if not student or student.tenant_id != current.tenant_id:
        raise not_found("Student")
    if not samples:
        raise validation_error("At least one face sample image is required")

    embeddings = []
    for f in samples:
        raw = await _read_validated(f)
        try:
            embeddings.append(generate_embedding(raw))
        except ValueError:
            raise validation_error(f"No valid single face detected in '{f.filename}'")
        # raw image bytes are discarded once the embedding is derived — never persisted to disk.

    avg = average_embeddings(embeddings)

    profile = (await db.execute(select(FaceProfile).where(FaceProfile.student_id == student_id))).scalar_one_or_none()
    if profile:
        profile.embedding = serialize(avg)
        profile.model_name = FACE_MODEL_NAME
        profile.sample_count = len(embeddings)
    else:
        profile = FaceProfile(tenant_id=current.tenant_id, school_id=current.school_id, student_id=student_id, embedding=serialize(avg), model_name=FACE_MODEL_NAME, sample_count=len(embeddings))
        db.add(profile)

    await log_action(db, request, current.tenant_id, current.id, "enroll", "face_profile", student_id, {"sample_count": len(embeddings)})
    await db.commit()
    return FaceEnrollResponse(student_id=student_id, enrolled=True, sample_count=len(embeddings), model_name=FACE_MODEL_NAME)


@router.post("/recognize", response_model=FaceRecognizeResponse)
async def recognize(
    request: Request,
    frame: UploadFile = File(...),
    mark_attendance: bool = Form(default=True),
    class_name: str | None = Form(default=None),
    section: str | None = Form(default=None),
    current: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current.role not in {"admin", "teacher"}:
        raise permission_denied()

    raw = await _read_validated(frame)
    probe = generate_embedding(raw)

    # Recognition is strictly scoped to this tenant's own enrolled profiles —
    # never compared against another school's embeddings.
    profiles = (await db.execute(select(FaceProfile).where(FaceProfile.tenant_id == current.tenant_id))).scalars().all()

    best_student_id, best_score = None, 0.0
    for p in profiles:
        score = cosine_similarity(probe, deserialize(p.embedding))
        if score > best_score:
            best_score, best_student_id = score, p.student_id

    recognized = best_student_id is not None and best_score >= settings.FACE_RECOGNITION_THRESHOLD
    attendance_marked = False
    student_name = None

    if recognized:
        student = await db.get(Student, best_student_id)
        student_name = student.full_name if student else None
        if mark_attendance and student:
            today = datetime.now(timezone.utc).date()
            existing = (await db.execute(select(Attendance).where(Attendance.tenant_id == current.tenant_id, Attendance.student_id == student.id, Attendance.date == today))).scalar_one_or_none()
            if not existing:
                db.add(Attendance(
                    tenant_id=current.tenant_id, school_id=current.school_id, student_id=student.id, date=today,
                    class_name=class_name or student.class_name, section=section or student.section,
                    status="present", source="face", confidence=best_score, marked_by=current.id,
                    check_in_time=datetime.now(timezone.utc),
                ))
                attendance_marked = True

    db.add(RecognitionLog(
        tenant_id=current.tenant_id, school_id=current.school_id, student_id=best_student_id if recognized else None,
        recognition_time=datetime.now(timezone.utc), confidence=best_score, source="webcam", attendance_marked=attendance_marked,
    ))
    await log_action(db, request, current.tenant_id, current.id, "recognize", "face_profile", best_student_id, {"confidence": best_score, "recognized": recognized})
    await db.commit()

    return FaceRecognizeResponse(recognized=recognized, student_id=best_student_id if recognized else None, student_name=student_name if recognized else None, confidence=round(best_score, 4), attendance_marked=attendance_marked)
