from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.dependencies import CurrentUser, require_permission
from app.db.session import get_db
from app.models.attendance import Attendance
from app.models.student import Student
from app.models.teacher import Teacher
from app.schemas.dashboard import AttendanceTrendPoint, ClassAttendancePoint, DashboardSummary

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/summary", response_model=DashboardSummary)
async def summary(current: CurrentUser = Depends(require_permission("students:read")), db: AsyncSession = Depends(get_db)):
    tenant = current.tenant_id
    total_students = (await db.execute(select(func.count()).select_from(Student).where(Student.tenant_id == tenant, Student.status == "active"))).scalar_one()
    total_teachers = (await db.execute(select(func.count()).select_from(Teacher).where(Teacher.tenant_id == tenant, Teacher.status == "active"))).scalar_one()

    today = date.today()
    present_today = (await db.execute(select(func.count()).select_from(Attendance).where(Attendance.tenant_id == tenant, Attendance.date == today, Attendance.status.in_(["present", "late"])))).scalar_one()
    marked_today = (await db.execute(select(func.count()).select_from(Attendance).where(Attendance.tenant_id == tenant, Attendance.date == today))).scalar_one()
    absent_today = (await db.execute(select(func.count()).select_from(Attendance).where(Attendance.tenant_id == tenant, Attendance.date == today, Attendance.status == "absent"))).scalar_one()

    rate = round((present_today / marked_today) * 100, 1) if marked_today else 0.0
    return DashboardSummary(totalStudents=total_students, totalTeachers=total_teachers, attendanceRate=rate, absentToday=absent_today)


@router.get("/attendance-trend", response_model=list[AttendanceTrendPoint])
async def attendance_trend(current: CurrentUser = Depends(require_permission("students:read")), db: AsyncSession = Depends(get_db)):
    tenant = current.tenant_id
    today = date.today()
    points: list[AttendanceTrendPoint] = []
    labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        present = (await db.execute(select(func.count()).select_from(Attendance).where(Attendance.tenant_id == tenant, Attendance.date == day, Attendance.status.in_(["present", "late"])))).scalar_one()
        marked = (await db.execute(select(func.count()).select_from(Attendance).where(Attendance.tenant_id == tenant, Attendance.date == day))).scalar_one()
        rate = round((present / marked) * 100, 1) if marked else 0.0
        points.append(AttendanceTrendPoint(day=labels[day.weekday()], rate=rate))
    return points


@router.get("/class-attendance", response_model=list[ClassAttendancePoint])
async def class_attendance(current: CurrentUser = Depends(require_permission("students:read")), db: AsyncSession = Depends(get_db)):
    tenant = current.tenant_id
    today = date.today()
    rows = (
        await db.execute(
            select(
                Attendance.class_name,
                Attendance.section,
                func.count().filter(Attendance.status.in_(["present", "late"])),
                func.count(),
            )
            .where(Attendance.tenant_id == tenant, Attendance.date == today)
            .group_by(Attendance.class_name, Attendance.section)
        )
    ).all()
    out = []
    for class_name, section, present, total in rows:
        label = f"{class_name} {section}".strip() if section else class_name
        out.append(ClassAttendancePoint(name=label, attendance=round((present / total) * 100, 1) if total else 0.0))
    return out
