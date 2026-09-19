import random
import string

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import conflict, not_found, permission_denied, validation_error
from app.db.dependencies import CurrentUser, get_current_user, require_permission
from app.db.session import get_db
from app.models.admission import Admission
from app.schemas.admission import AdmissionCreate, AdmissionOut, AdmissionStatusUpdate, AdmissionUpdate
from app.schemas.common import Page
from app.services.audit_service import log_action

router = APIRouter(prefix="/admissions", tags=["Admissions"])

VALID_TRANSITIONS = {
    "pending": {"verified", "rejected"},
    "verified": {"approved", "rejected"},
    "approved": set(),
    "rejected": set(),
}


def _gen_form_number() -> str:
    return "ADM" + "".join(random.choices(string.digits, k=8))


@router.get("", response_model=Page[AdmissionOut])
async def list_admissions(search: str | None = None, status: str | None = None, class_applying_for: str | None = Query(default=None, alias="class"),
                           page: int = 1, page_size: int = 20,
                           current: CurrentUser = Depends(require_permission("students:read")), db: AsyncSession = Depends(get_db)):
    q = select(Admission).where(Admission.tenant_id == current.tenant_id)
    if search:
        like = f"%{search}%"
        q = q.where(or_(Admission.student_name.ilike(like), Admission.form_number.ilike(like)))
    if status:
        q = q.where(Admission.status == status)
    if class_applying_for:
        q = q.where(Admission.class_applying_for == class_applying_for)
    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    q = q.order_by(Admission.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    items = (await db.execute(q)).scalars().all()
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/{admission_id}", response_model=AdmissionOut)
async def get_admission(admission_id: str, current: CurrentUser = Depends(require_permission("students:read")), db: AsyncSession = Depends(get_db)):
    a = await db.get(Admission, admission_id)
    if not a or a.tenant_id != current.tenant_id:
        raise not_found("Admission")
    return a


@router.post("", response_model=AdmissionOut, status_code=201)
async def create_admission(payload: AdmissionCreate, request: Request, current: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    for _ in range(5):
        form_number = _gen_form_number()
        exists = (await db.execute(select(Admission).where(Admission.form_number == form_number))).scalar_one_or_none()
        if not exists:
            break
    else:
        raise conflict("Could not generate a unique form number, try again", "FORM_NUMBER_COLLISION")

    dup = (await db.execute(select(Admission).where(
        Admission.tenant_id == current.tenant_id, Admission.student_name == payload.student_name,
        Admission.contact == payload.contact, Admission.status != "rejected",
    ))).scalar_one_or_none()
    if dup:
        raise conflict("A similar application already exists for this applicant", "DUPLICATE_APPLICATION")

    a = Admission(tenant_id=current.tenant_id, school_id=current.school_id, form_number=form_number, created_by=current.id, **payload.model_dump())
    db.add(a)
    await db.flush()
    await log_action(db, request, current.tenant_id, current.id, "create", "admission", a.id)
    await db.commit()
    await db.refresh(a)
    return a


@router.put("/{admission_id}", response_model=AdmissionOut)
async def update_admission(admission_id: str, payload: AdmissionUpdate, request: Request, current: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    a = await db.get(Admission, admission_id)
    if not a or a.tenant_id != current.tenant_id:
        raise not_found("Admission")
    if a.status in ("approved", "rejected"):
        raise validation_error("Cannot edit an admission that has already been finalized")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(a, field, value)
    await log_action(db, request, current.tenant_id, current.id, "update", "admission", a.id)
    await db.commit()
    await db.refresh(a)
    return a


@router.patch("/{admission_id}/status", response_model=AdmissionOut)
async def update_status(admission_id: str, payload: AdmissionStatusUpdate, request: Request, current: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if current.role != "admin":
        raise permission_denied()
    a = await db.get(Admission, admission_id)
    if not a or a.tenant_id != current.tenant_id:
        raise not_found("Admission")
    if payload.status not in VALID_TRANSITIONS.get(a.status, set()):
        raise validation_error(f"Cannot transition admission from '{a.status}' to '{payload.status}'")

    a.status = payload.status
    if payload.status == "verified":
        a.verified_by = current.id
    elif payload.status == "approved":
        a.approved_by = current.id

    await log_action(db, request, current.tenant_id, current.id, f"admission:{payload.status}", "admission", a.id, {"remarks": payload.remarks})
    await db.commit()
    await db.refresh(a)
    return a
