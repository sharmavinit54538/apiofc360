import json

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import conflict, not_found, permission_denied
from app.db.dependencies import CurrentUser, get_current_user, require_permission
from app.db.session import get_db
from app.models.teacher import Teacher
from app.schemas.common import Page
from app.schemas.teacher import TeacherCreate, TeacherOut, TeacherUpdate
from app.services.audit_service import log_action

router = APIRouter(prefix="/teachers", tags=["Teachers"])
WRITE_ROLES = {"admin"}


def _out(t: Teacher) -> TeacherOut:
    data = TeacherOut.model_validate(t, from_attributes=True).model_dump()
    data["class_assignments"] = json.loads(t.class_assignments) if t.class_assignments else []
    return TeacherOut(**data)


@router.get("", response_model=Page[TeacherOut])
async def list_teachers(search: str | None = None, status: str | None = None, page: int = 1, page_size: int = 20,
                         current: CurrentUser = Depends(require_permission("students:read")), db: AsyncSession = Depends(get_db)):
    q = select(Teacher).where(Teacher.tenant_id == current.tenant_id)
    if search:
        like = f"%{search}%"
        q = q.where(or_(Teacher.name.ilike(like), Teacher.employee_id.ilike(like), Teacher.email.ilike(like)))
    if status:
        q = q.where(Teacher.status == status)
    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    q = q.order_by(Teacher.name).offset((page - 1) * page_size).limit(page_size)
    items = [_out(t) for t in (await db.execute(q)).scalars().all()]
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/{teacher_id}", response_model=TeacherOut)
async def get_teacher(teacher_id: str, current: CurrentUser = Depends(require_permission("students:read")), db: AsyncSession = Depends(get_db)):
    t = await db.get(Teacher, teacher_id)
    if not t or t.tenant_id != current.tenant_id:
        raise not_found("Teacher")
    return _out(t)


@router.post("", response_model=TeacherOut, status_code=201)
async def create_teacher(payload: TeacherCreate, request: Request, current: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if current.role not in WRITE_ROLES:
        raise permission_denied()
    existing = (await db.execute(select(Teacher).where(Teacher.tenant_id == current.tenant_id, Teacher.employee_id == payload.employee_id))).scalar_one_or_none()
    if existing:
        raise conflict("A teacher with this employee ID already exists", "DUPLICATE_EMPLOYEE_ID")
    data = payload.model_dump()
    assignments = data.pop("class_assignments", None)
    t = Teacher(tenant_id=current.tenant_id, school_id=current.school_id, class_assignments=json.dumps(assignments) if assignments else None, **data)
    db.add(t)
    await db.flush()
    await log_action(db, request, current.tenant_id, current.id, "create", "teacher", t.id)
    await db.commit()
    await db.refresh(t)
    return _out(t)


@router.put("/{teacher_id}", response_model=TeacherOut)
async def update_teacher(teacher_id: str, payload: TeacherUpdate, request: Request, current: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if current.role not in WRITE_ROLES:
        raise permission_denied()
    t = await db.get(Teacher, teacher_id)
    if not t or t.tenant_id != current.tenant_id:
        raise not_found("Teacher")
    data = payload.model_dump(exclude_unset=True)
    if "class_assignments" in data:
        t.class_assignments = json.dumps(data.pop("class_assignments"))
    for field, value in data.items():
        setattr(t, field, value)
    await log_action(db, request, current.tenant_id, current.id, "update", "teacher", t.id)
    await db.commit()
    await db.refresh(t)
    return _out(t)


@router.delete("/{teacher_id}", status_code=204)
async def delete_teacher(teacher_id: str, request: Request, current: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if current.role not in WRITE_ROLES:
        raise permission_denied()
    t = await db.get(Teacher, teacher_id)
    if not t or t.tenant_id != current.tenant_id:
        raise not_found("Teacher")
    t.status = "inactive"
    await log_action(db, request, current.tenant_id, current.id, "delete", "teacher", t.id)
    await db.commit()
    return None
