from datetime import date as date_type, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import permission_denied
from app.db.dependencies import CurrentUser, get_current_user
from app.db.session import get_db
from app.models.misc import RecognitionLog
from app.schemas.misc import RecognitionLogOut

router = APIRouter(prefix="/recognition", tags=["Face Recognition"])


@router.get("/logs", response_model=list[RecognitionLogOut])
async def list_logs(
    date: date_type | None = None,
    student_id: str | None = None,
    source: str | None = None,
    min_confidence: float | None = None,
    current: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current.role not in {"admin", "teacher"}:
        raise permission_denied()
    q = select(RecognitionLog).where(RecognitionLog.tenant_id == current.tenant_id)
    if date:
        q = q.where(RecognitionLog.recognition_time >= date, RecognitionLog.recognition_time < date + timedelta(days=1))
    if student_id:
        q = q.where(RecognitionLog.student_id == student_id)
    if source:
        q = q.where(RecognitionLog.source == source)
    if min_confidence is not None:
        q = q.where(RecognitionLog.confidence >= min_confidence)
    return (await db.execute(q.order_by(RecognitionLog.recognition_time.desc()))).scalars().all()
