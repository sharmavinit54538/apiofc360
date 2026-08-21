from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.dependencies import CurrentUser, require_permission
from app.db.session import get_db
from app.models.admission import Admission
from app.models.attendance import Attendance
from app.models.fee import Fee
from app.models.student import Student

router = APIRouter(prefix="/ai-insights", tags=["AI Insights"])


@router.get("")
async def ai_insights(current: CurrentUser = Depends(require_permission("reports:read")), db: AsyncSession = Depends(get_db)):
    """
    Real, database-derived analytics. No AI provider is configured by
    default, so this returns deterministic statistics rather than
    fabricated "AI-generated" text. Wire an LLM provider behind a service
    abstraction (e.g. app/services/ai_provider.py) to add narrative
    summaries on top of this data — never in place of it.
    """
    tenant = current.tenant_id
    today = date.today()
    since = today - timedelta(days=30)

    # Attendance trend (last 30 days)
    trend_rows = (
        await db.execute(
            select(Attendance.date, func.count().filter(Attendance.status.in_(["present", "late"])), func.count())
            .where(Attendance.tenant_id == tenant, Attendance.date >= since)
            .group_by(Attendance.date)
            .order_by(Attendance.date)
        )
    ).all()
    attendance_trend = [{"date": str(d), "rate": round((p / t) * 100, 1) if t else 0.0} for d, p, t in trend_rows]

    # Students with low attendance (below 75%) over the last 30 days
    per_student = (
        await db.execute(
            select(Attendance.student_id, func.count().filter(Attendance.status.in_(["present", "late"])), func.count())
            .where(Attendance.tenant_id == tenant, Attendance.date >= since)
            .group_by(Attendance.student_id)
        )
    ).all()
    low_attendance = []
    for student_id, present, total in per_student:
        rate = (present / total) * 100 if total else 0.0
        if total >= 5 and rate < 75:
            student = await db.get(Student, student_id)
            low_attendance.append({"student_id": student_id, "student_name": student.full_name if student else None, "attendance_rate": round(rate, 1)})
    low_attendance.sort(key=lambda r: r["attendance_rate"])

    # Class performance (attendance by class, last 30 days)
    class_rows = (
        await db.execute(
            select(Attendance.class_name, func.count().filter(Attendance.status.in_(["present", "late"])), func.count())
            .where(Attendance.tenant_id == tenant, Attendance.date >= since)
            .group_by(Attendance.class_name)
        )
    ).all()
    class_performance = [{"class_name": c, "attendance_rate": round((p / t) * 100, 1) if t else 0.0} for c, p, t in class_rows]

    # Fee collection trend
    fee_rows = (await db.execute(select(Fee.amount, Fee.paid_amount).where(Fee.tenant_id == tenant))).all()
    total_billed = sum((r[0] for r in fee_rows), 0)
    total_collected = sum((r[1] for r in fee_rows), 0)
    fee_collection = {
        "total_billed": float(total_billed),
        "total_collected": float(total_collected),
        "collection_rate": round((float(total_collected) / float(total_billed)) * 100, 1) if total_billed else 0.0,
    }

    # Admission trend (last 90 days, by status)
    admission_rows = (
        await db.execute(
            select(Admission.status, func.count())
            .where(Admission.tenant_id == tenant, Admission.created_at >= today - timedelta(days=90))
            .group_by(Admission.status)
        )
    ).all()
    admission_trend = {status: count for status, count in admission_rows}

    return {
        "attendance_trend": attendance_trend,
        "students_with_low_attendance": low_attendance[:25],
        "class_performance": class_performance,
        "fee_collection_trend": fee_collection,
        "admission_trend": admission_trend,
        "ai_provider_configured": False,
    }
