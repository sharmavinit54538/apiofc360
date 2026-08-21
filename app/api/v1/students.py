from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import conflict, not_found, permission_denied
from app.db.dependencies import CurrentUser, get_current_user, require_permission
from app.db.session import get_db
from app.models.student import Student
from app.schemas.common import Page
from app.schemas.student import StudentCreate, StudentOut, StudentUpdate
from app.services.audit_service import log_action

router = APIRouter(prefix="/students", tags=["Students"])

WRITE_ROLES = {"admin"}


@router.get("", response_model=Page[StudentOut])
async def list_students(
    search: str | None = None,
    class_name: str | None = Query(default=None, alias="class"),
    section: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
    current: CurrentUser = Depends(require_permission("students:read")),
    db: AsyncSession = Depends(get_db),
):
    q = select(Student).where(Student.tenant_id == current.tenant_id)
    if search:
        like = f"%{search}%"
        q = q.where(or_(Student.first_name.ilike(like), Student.last_name.ilike(like), Student.admission_number.ilike(like), Student.roll_number.ilike(like)))
    if class_name:
        q = q.where(Student.class_name == class_name)
    if section:
        q = q.where(Student.section == section)
    if status:
        q = q.where(Student.status == status)

    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    q = q.order_by(Student.class_name, Student.roll_number).offset((page - 1) * page_size).limit(page_size)
    items = (await db.execute(q)).scalars().all()
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/{student_id}", response_model=StudentOut)
async def get_student(student_id: str, current: CurrentUser = Depends(require_permission("students:read")), db: AsyncSession = Depends(get_db)):
    student = await db.get(Student, student_id)
    if not student or student.tenant_id != current.tenant_id:
        raise not_found("Student")
    return student


@router.post("", response_model=StudentOut, status_code=201)
async def create_student(payload: StudentCreate, request: Request, current: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if current.role not in WRITE_ROLES:
        raise permission_denied()
    existing = (await db.execute(select(Student).where(Student.tenant_id == current.tenant_id, Student.admission_number == payload.admission_number))).scalar_one_or_none()
    if existing:
        raise conflict("A student with this admission number already exists", "DUPLICATE_ADMISSION_NUMBER")

    student = Student(tenant_id=current.tenant_id, school_id=current.school_id, **payload.model_dump())
    db.add(student)
    await db.flush()
    await log_action(db, request, current.tenant_id, current.id, "create", "student", student.id)
    await db.commit()
    await db.refresh(student)
    return student


@router.put("/{student_id}", response_model=StudentOut)
async def update_student(student_id: str, payload: StudentUpdate, request: Request, current: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if current.role not in WRITE_ROLES:
        raise permission_denied()
    student = await db.get(Student, student_id)
    if not student or student.tenant_id != current.tenant_id:
        raise not_found("Student")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(student, field, value)
    await log_action(db, request, current.tenant_id, current.id, "update", "student", student.id)
    await db.commit()
    await db.refresh(student)
    return student


@router.delete("/{student_id}", status_code=204)
async def delete_student(student_id: str, request: Request, current: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if current.role not in WRITE_ROLES:
        raise permission_denied()
    student = await db.get(Student, student_id)
    if not student or student.tenant_id != current.tenant_id:
        raise not_found("Student")
    # soft delete — never hard-delete academic records
    student.status = "inactive"
    await log_action(db, request, current.tenant_id, current.id, "delete", "student", student.id)
    await db.commit()
    return None
