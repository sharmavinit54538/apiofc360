import random
import string
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import not_found, permission_denied, validation_error
from app.db.dependencies import CurrentUser, get_current_user, require_permission
from app.db.session import get_db
from app.models.fee import Fee
from app.models.student import Student
from app.schemas.fee import FeeCreate, FeeOut, FeePaymentIn, FeeSummary, FeeUpdate
from app.services.audit_service import log_action

router = APIRouter(prefix="/fees", tags=["Fees"])
WRITE_ROLES = {"admin", "accountant"}


def _out(f: Fee) -> FeeOut:
    paid = f.paid_amount if f.paid_amount is not None else Decimal(0)
    return FeeOut(
        id=f.id, tenant_id=f.tenant_id, school_id=f.school_id, student_id=f.student_id, academic_year=f.academic_year,
        fee_type=f.fee_type, amount=f.amount, paid_amount=paid, pending_amount=f.amount - paid,
        due_date=f.due_date, payment_date=f.payment_date, payment_status=f.payment_status, receipt_number=f.receipt_number,
        payment_method=f.payment_method, transaction_reference=f.transaction_reference, remarks=f.remarks,
        created_at=f.created_at, updated_at=f.updated_at,
    )


def _recompute_status(f: Fee):
    paid = f.paid_amount if f.paid_amount is not None else Decimal(0)
    f.paid_amount = paid
    if paid <= 0:
        f.payment_status = "overdue" if f.due_date and f.due_date < date.today() else "pending"
    elif paid < f.amount:
        f.payment_status = "partial"
    else:
        f.payment_status = "paid"


@router.get("", response_model=list[FeeOut])
async def list_fees(student_id: str | None = None, payment_status: str | None = None, academic_year: str | None = None,
                     current: CurrentUser = Depends(require_permission("fees:read")), db: AsyncSession = Depends(get_db)):
    q = select(Fee).where(Fee.tenant_id == current.tenant_id)
    if student_id:
        q = q.where(Fee.student_id == student_id)
    if payment_status:
        q = q.where(Fee.payment_status == payment_status)
    if academic_year:
        q = q.where(Fee.academic_year == academic_year)
    if current.role == "parent":
        my_children = (await db.execute(select(Student.id).where(Student.tenant_id == current.tenant_id, Student.parent_id == current.id))).scalars().all()
        q = q.where(Fee.student_id.in_(my_children or ["__none__"]))
    return [_out(f) for f in (await db.execute(q.order_by(Fee.due_date))).scalars().all()]


@router.get("/summary", response_model=FeeSummary)
async def fee_summary(current: CurrentUser = Depends(require_permission("fees:read")), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Fee.amount, Fee.paid_amount, Fee.payment_status).where(Fee.tenant_id == current.tenant_id))).all()
    billed = sum((r[0] for r in rows), Decimal(0))
    collected = sum((r[1] for r in rows), Decimal(0))
    overdue = sum((r[0] - r[1] for r in rows if r[2] == "overdue"), Decimal(0))
    return FeeSummary(total_billed=billed, total_collected=collected, total_pending=billed - collected, total_overdue=overdue)


@router.get("/{fee_id}", response_model=FeeOut)
async def get_fee(fee_id: str, current: CurrentUser = Depends(require_permission("fees:read")), db: AsyncSession = Depends(get_db)):
    f = await db.get(Fee, fee_id)
    if not f or f.tenant_id != current.tenant_id:
        raise not_found("Fee record")
    return _out(f)


@router.post("", response_model=FeeOut, status_code=201)
async def create_fee(payload: FeeCreate, request: Request, current: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if current.role not in WRITE_ROLES:
        raise permission_denied()
    student = await db.get(Student, payload.student_id)
    if not student or student.tenant_id != current.tenant_id:
        raise not_found("Student")
    f = Fee(tenant_id=current.tenant_id, school_id=current.school_id, **payload.model_dump())
    _recompute_status(f)
    db.add(f)
    await db.flush()
    await log_action(db, request, current.tenant_id, current.id, "create", "fee", f.id)
    await db.commit()
    await db.refresh(f)
    return _out(f)


@router.put("/{fee_id}", response_model=FeeOut)
async def update_fee(fee_id: str, payload: FeeUpdate, request: Request, current: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if current.role not in WRITE_ROLES:
        raise permission_denied()
    f = await db.get(Fee, fee_id)
    if not f or f.tenant_id != current.tenant_id:
        raise not_found("Fee record")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(f, field, value)
    _recompute_status(f)
    await log_action(db, request, current.tenant_id, current.id, "update", "fee", f.id)
    await db.commit()
    await db.refresh(f)
    return _out(f)


@router.post("/{fee_id}/payment", response_model=FeeOut)
async def record_payment(fee_id: str, payload: FeePaymentIn, request: Request, current: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if current.role not in WRITE_ROLES:
        raise permission_denied()
    f = await db.get(Fee, fee_id)
    if not f or f.tenant_id != current.tenant_id:
        raise not_found("Fee record")
    if payload.amount <= 0:
        raise validation_error("Payment amount must be positive")
    if f.paid_amount + payload.amount > f.amount:
        raise validation_error("Payment exceeds the outstanding amount")

    f.paid_amount = f.paid_amount + payload.amount
    f.payment_method = payload.payment_method
    f.transaction_reference = payload.transaction_reference
    f.payment_date = payload.payment_date or date.today()
    f.receipt_number = f.receipt_number or ("RCPT" + "".join(random.choices(string.digits, k=8)))
    _recompute_status(f)

    await log_action(db, request, current.tenant_id, current.id, "payment", "fee", f.id, {"amount": str(payload.amount)})
    await db.commit()
    await db.refresh(f)
    return _out(f)
