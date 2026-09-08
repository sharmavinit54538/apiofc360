from sqlalchemy import Date, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, new_uuid


class Fee(Base, TimestampMixin):
    __tablename__ = "fees"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("schools.id"), index=True, nullable=False)
    school_id: Mapped[str] = mapped_column(String(36), ForeignKey("schools.id"), index=True, nullable=False)

    student_id: Mapped[str] = mapped_column(String(36), ForeignKey("students.id"), index=True, nullable=False)
    academic_year: Mapped[str] = mapped_column(String(16), nullable=False)
    fee_type: Mapped[str] = mapped_column(String(64), nullable=False)

    amount: Mapped[Numeric] = mapped_column(Numeric(12, 2), nullable=False)
    paid_amount: Mapped[Numeric] = mapped_column(Numeric(12, 2), default=0, nullable=False)

    due_date: Mapped[Date | None] = mapped_column(Date, nullable=True)
    payment_date: Mapped[Date | None] = mapped_column(Date, nullable=True)
    payment_status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    # pending | partial | paid | overdue

    receipt_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payment_method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    transaction_reference: Mapped[str | None] = mapped_column(String(128), nullable=True)
    remarks: Mapped[str | None] = mapped_column(String(512), nullable=True)

    @property
    def pending_amount(self):
        return self.amount - self.paid_amount
