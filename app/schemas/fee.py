from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel


class FeeCreate(BaseModel):
    student_id: str
    academic_year: str
    fee_type: str
    amount: Decimal
    due_date: date | None = None
    remarks: str | None = None


class FeeUpdate(BaseModel):
    academic_year: str | None = None
    fee_type: str | None = None
    amount: Decimal | None = None
    due_date: date | None = None
    remarks: str | None = None


class FeePaymentIn(BaseModel):
    amount: Decimal
    payment_method: str
    transaction_reference: str | None = None
    payment_date: date | None = None


class FeeOut(BaseModel):
    id: str
    tenant_id: str
    school_id: str
    student_id: str
    academic_year: str
    fee_type: str
    amount: Decimal
    paid_amount: Decimal
    pending_amount: Decimal
    due_date: date | None
    payment_date: date | None
    payment_status: str
    receipt_number: str | None
    payment_method: str | None
    transaction_reference: str | None
    remarks: str | None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class FeeSummary(BaseModel):
    total_billed: Decimal
    total_collected: Decimal
    total_pending: Decimal
    total_overdue: Decimal
