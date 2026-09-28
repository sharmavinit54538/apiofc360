import csv
import io
from datetime import date

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import permission_denied
from app.db.dependencies import CurrentUser, get_current_user, require_permission
from app.db.session import get_db
from app.models.attendance import Attendance
from app.models.student import Student
from app.schemas.attendance import AttendanceOut, AttendanceReportRow, BulkAttendanceIn
from app.services.audit_service import log_action

router = APIRouter(prefix="/attendance", tags=["Attendance"])
MARK_ROLES = {"admin", "teacher"}


@router.get("", response_model=list[AttendanceOut])
async def list_attendance(date: date | None = None, class_name: str | None = Query(default=None, alias="class"),
                           section: str | None = None, student_id: str | None = None,
                           current: CurrentUser = Depends(require_permission("attendance:read")), db: AsyncSession = Depends(get_db)):
    q = select(Attendance).where(Attendance.tenant_id == current.tenant_id)
    if date:
        q = q.where(Attendance.date == date)
    if class_name:
        q = q.where(Attendance.class_name == class_name)
    if section:
        q = q.where(Attendance.section == section)
    if student_id:
        q = q.where(Attendance.student_id == student_id)
    if current.role == "student":
        # self-service: students only ever see their own records regardless of filters
        my_student = (await db.execute(select(Student).where(Student.tenant_id == current.tenant_id, Student.user_id == current.id))).scalar_one_or_none()
        q = q.where(Attendance.student_id == (my_student.id if my_student else "__none__"))
    return (await db.execute(q.order_by(Attendance.date.desc()))).scalars().all()


@router.post("", status_code=201)
async def mark_attendance(payload: BulkAttendanceIn, request: Request, current: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if current.role not in MARK_ROLES:
        raise permission_denied()

    created, updated = 0, 0
    for rec in payload.records:
        existing = (await db.execute(select(Attendance).where(Attendance.tenant_id == current.tenant_id, Attendance.student_id == rec.student_id, Attendance.date == payload.date))).scalar_one_or_none()
        if existing:
            existing.status = rec.status
            existing.remarks = rec.remarks
            existing.marked_by = current.id
            existing.source = "manual"
            updated += 1
        else:
            db.add(Attendance(
                tenant_id=current.tenant_id, school_id=current.school_id, student_id=rec.student_id,
                date=payload.date, class_name=payload.class_name, section=payload.section,
                status=rec.status, source="manual", remarks=rec.remarks, marked_by=current.id,
            ))
            created += 1
    await log_action(db, request, current.tenant_id, current.id, "mark", "attendance", None, {"date": str(payload.date), "created": created, "updated": updated})
    await db.commit()
    return {"success": True, "created": created, "updated": updated}


@router.get("/report", response_model=list[AttendanceReportRow])
async def attendance_report(start_date: date | None = None, end_date: date | None = None, class_name: str | None = Query(default=None, alias="class"),
                             section: str | None = None, student_id: str | None = None,
                             current: CurrentUser = Depends(require_permission("attendance:read")), db: AsyncSession = Depends(get_db)):
    q = select(Attendance, Student).join(Student, Student.id == Attendance.student_id).where(Attendance.tenant_id == current.tenant_id)
    if start_date:
        q = q.where(Attendance.date >= start_date)
    if end_date:
        q = q.where(Attendance.date <= end_date)
    if class_name:
        q = q.where(Attendance.class_name == class_name)
    if section:
        q = q.where(Attendance.section == section)
    if student_id:
        q = q.where(Attendance.student_id == student_id)

    rows = (await db.execute(q)).all()
    agg: dict[str, dict] = {}
    for att, student in rows:
        bucket = agg.setdefault(student.id, {"student_id": student.id, "student_name": student.full_name, "class_name": student.class_name, "section": student.section, "present": 0, "absent": 0, "late": 0, "excused": 0})
        bucket[att.status] = bucket.get(att.status, 0) + 1

    out = []
    for b in agg.values():
        total = b["present"] + b["absent"] + b["late"] + b["excused"]
        rate = round(((b["present"] + b["late"]) / total) * 100, 1) if total else 0.0
        out.append(AttendanceReportRow(total=total, attendance_rate=rate, **b))
    return out


@router.get("/export/csv")
async def export_csv(start_date: date | None = None, end_date: date | None = None,
                      current: CurrentUser = Depends(require_permission("attendance:read")), db: AsyncSession = Depends(get_db)):
    rows = await attendance_report(start_date=start_date, end_date=end_date, class_name=None, section=None, student_id=None, current=current, db=db)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Student", "Class", "Section", "Present", "Absent", "Late", "Excused", "Total", "Attendance Rate %"])
    for r in rows:
        writer.writerow([r.student_name, r.class_name, r.section or "", r.present, r.absent, r.late, r.excused, r.total, r.attendance_rate])
    buf.seek(0)
    return StreamingResponse(buf, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=attendance_report.csv"})


@router.get("/export/pdf")
async def export_pdf(start_date: date | None = None, end_date: date | None = None,
                      current: CurrentUser = Depends(require_permission("attendance:read")), db: AsyncSession = Depends(get_db)):
    # Minimal dependency-free PDF export (plain text report). Swap for a
    # proper PDF renderer (e.g. reportlab/weasyprint) if richer layout is needed.
    rows = await attendance_report(start_date=start_date, end_date=end_date, class_name=None, section=None, student_id=None, current=current, db=db)
    lines = ["Attendance Report", "-" * 40]
    for r in rows:
        lines.append(f"{r.student_name} ({r.class_name} {r.section or ''}) - {r.attendance_rate}% ({r.present}/{r.total})")
    content = "\n".join(lines).encode("utf-8")
    return StreamingResponse(io.BytesIO(content), media_type="application/pdf", headers={"Content-Disposition": "attachment; filename=attendance_report.pdf"})
