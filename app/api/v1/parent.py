from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import not_found, permission_denied
from app.db.dependencies import CurrentUser, get_current_user
from app.db.session import get_db
from app.models.attendance import Attendance
from app.models.fee import Fee
from app.models.misc import Notification
from app.models.student import Student
from app.schemas.attendance import AttendanceOut
from app.schemas.fee import FeeOut
from app.schemas.misc import NotificationOut
from app.schemas.student import StudentOut

router = APIRouter(prefix="/parent", tags=["Parent Portal"])


async def _my_child_or_404(student_id: str, current: CurrentUser, db: AsyncSession) -> Student:
    student = await db.get(Student, student_id)
    # A parent may NEVER access another family's student by editing the ID —
    # ownership is verified against the authenticated parent's own user id,
    # scoped to their tenant, every time.
    if not student or student.tenant_id != current.tenant_id or student.parent_id != current.id:
        raise not_found("Student")
    return student


@router.get("/children", response_model=list[StudentOut])
async def my_children(current: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if current.role != "parent":
        raise permission_denied()
    q = select(Student).where(Student.tenant_id == current.tenant_id, Student.parent_id == current.id)
    return (await db.execute(q)).scalars().all()


@router.get("/children/{student_id}/attendance", response_model=list[AttendanceOut])
async def child_attendance(student_id: str, current: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if current.role != "parent":
        raise permission_denied()
    await _my_child_or_404(student_id, current, db)
    q = select(Attendance).where(Attendance.tenant_id == current.tenant_id, Attendance.student_id == student_id).order_by(Attendance.date.desc())
    return (await db.execute(q)).scalars().all()


@router.get("/children/{student_id}/fees", response_model=list[FeeOut])
async def child_fees(student_id: str, current: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if current.role != "parent":
        raise permission_denied()
    await _my_child_or_404(student_id, current, db)
    from app.api.v1.fees import _out
    q = select(Fee).where(Fee.tenant_id == current.tenant_id, Fee.student_id == student_id)
    return [_out(f) for f in (await db.execute(q)).scalars().all()]


@router.get("/children/{student_id}/notices", response_model=list[NotificationOut])
async def child_notices(student_id: str, current: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if current.role != "parent":
        raise permission_denied()
    await _my_child_or_404(student_id, current, db)
    # notices addressed to the parent themself, concerning this child context
    q = select(Notification).where(Notification.tenant_id == current.tenant_id, Notification.recipient_id == current.id).order_by(Notification.created_at.desc())
    return (await db.execute(q)).scalars().all()
