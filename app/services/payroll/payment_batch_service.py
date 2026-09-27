"""Service for Payment Batches and Bank Disbursals."""

from __future__ import annotations

import csv
import io
import json
import logging
import uuid
from datetime import date, datetime
from typing import Any, List, Optional

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.redis_client import redis_client
from app.models.employee import Employee
from app.models.payroll import PayrollRun, Payslip
from app.models.payroll_models import (
    PaymentBatch,
    PaymentBatchBankFile,
    PaymentBatchItem,
    PayrollRunEmployee,
)
from app.schemas.payroll_v2.runs import HeldEmployeeItem
from app.schemas.payroll_v2.payment_batches import UpdatedBankDetails
from app.services.payroll.audit_service import PayrollAuditService

logger = logging.getLogger(__name__)


class PaymentBatchService:
    """Disbursement batch lifecycle and bank advice generation."""

    BANK_RESP_PREFIX = "payroll:bank_resp:"

    @classmethod
    async def get_batch(
        cls, session: AsyncSession, batch_id: uuid.UUID
    ) -> PaymentBatch:
        stmt = (
            select(PaymentBatch)
            .options(selectinload(PaymentBatch.items))
            .where(PaymentBatch.id == batch_id)
        )
        res = await session.execute(stmt)
        batch = res.scalar_one_or_none()
        if not batch:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Payment batch '{batch_id}' not found.",
            )
        return batch

    @classmethod
    async def list_batches(
        cls,
        session: AsyncSession,
        company_id: Optional[uuid.UUID] = None,
        page: int = 1,
        limit: int = 20,
        status_filter: Optional[str] = None,
        period_id: Optional[str] = None,
        search: Optional[str] = None,
    ) -> dict[str, Any]:
        stmt = select(PaymentBatch)
        if company_id:
            stmt = stmt.where(PaymentBatch.company_id == company_id)
        if status_filter:
            stmt = stmt.where(func.upper(PaymentBatch.status) == status_filter.upper())
        if search:
            stmt = stmt.where(PaymentBatch.batch_number.ilike(f"%{search}%"))
        if period_id:
            try:
                p_uuid = uuid.UUID(period_id)
                stmt = stmt.join(PayrollRun, PaymentBatch.run_id == PayrollRun.id).where(
                    PayrollRun.period_id == p_uuid
                )
            except ValueError:
                pass

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await session.execute(count_stmt)).scalar() or 0

        offset = max(0, (page - 1) * limit)
        stmt = stmt.order_by(desc(PaymentBatch.created_at)).offset(offset).limit(limit)
        items = (await session.execute(stmt)).scalars().all()

        return {
            "items": items,
            "total": total,
            "page": page,
            "limit": limit,
        }

    @classmethod
    async def create_batch_from_run(
        cls,
        session: AsyncSession,
        run_id: uuid.UUID,
        source_account_id: str,
        payment_mode: str,
        held_employee_ids: Optional[List[HeldEmployeeItem]] = None,
        notes: Optional[str] = None,
        user_id: Optional[uuid.UUID] = None,
    ) -> PaymentBatch:
        run_stmt = select(PayrollRun).where(PayrollRun.id == run_id)
        run = (await session.execute(run_stmt)).scalar_one_or_none()
        if not run:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Payroll run '{run_id}' not found.",
            )

        held_map = {item.employee_id: item.reason for item in (held_employee_ids or [])}

        # Fetch employees from run
        emp_stmt = select(PayrollRunEmployee).where(PayrollRunEmployee.run_id == run_id)
        run_employees = (await session.execute(emp_stmt)).scalars().all()

        batch_number = f"PB-{run.period_year}{run.period_month:02d}-{uuid.uuid4().hex[:6].upper()}"
        batch = PaymentBatch(
            id=uuid.uuid4(),
            company_id=run.company_id,
            run_id=run.id,
            batch_number=batch_number,
            source_account_id=source_account_id,
            payment_mode=payment_mode,
            status="DRAFT",
            notes=notes,
        )
        session.add(batch)

        total_amount_paise = 0
        total_records = 0

        for re in run_employees:
            emp_id_str = str(re.employee_id)
            is_held = emp_id_str in held_map
            item_status = "HELD" if is_held else "PENDING"
            hold_reason = held_map.get(emp_id_str) if is_held else None

            # Fetch primary bank account details
            emp_info = (
                await session.execute(select(Employee).where(Employee.id == re.employee_id))
            ).scalar_one_or_none()
            acc_num = getattr(emp_info, "bank_account_number", "") or "000000000"
            ifsc = getattr(emp_info, "bank_ifsc", "") or "HDFC0001234"
            holder = f"{emp_info.first_name} {emp_info.last_name}".strip() if emp_info else "Employee"

            item = PaymentBatchItem(
                id=uuid.uuid4(),
                batch_id=batch.id,
                employee_id=re.employee_id,
                company_id=run.company_id,
                amount_paise=re.net_pay_paise,
                status=item_status,
                hold_reason=hold_reason,
                account_number=acc_num,
                ifsc_code=ifsc,
                account_holder_name=holder,
            )
            session.add(item)
            if not is_held:
                total_amount_paise += re.net_pay_paise
                total_records += 1

        batch.total_amount_paise = total_amount_paise
        batch.total_records = total_records

        await session.commit()
        await session.refresh(batch)

        await PayrollAuditService.log_event(
            session=session,
            entity_type="PaymentBatch",
            entity_id=batch.id,
            action="CREATE",
            company_id=batch.company_id,
            actor_id=user_id,
            before_status=None,
            after_status="DRAFT",
            reason=f"Created payment batch from run {run_id}",
        )
        return batch

    @classmethod
    async def approve_batch(
        cls,
        session: AsyncSession,
        batch_id: uuid.UUID,
        remarks: Optional[str] = None,
        user_id: Optional[uuid.UUID] = None,
        user_role: Optional[str] = None,
    ) -> PaymentBatch:
        batch = await cls.get_batch(session, batch_id)
        old_status = batch.status
        batch.status = "APPROVED"
        batch.approved_by = user_id
        batch.approved_at = datetime.now()
        batch.remarks = remarks

        await PayrollAuditService.log_event(
            session=session,
            entity_type="PaymentBatch",
            entity_id=batch.id,
            action="APPROVE",
            company_id=batch.company_id,
            actor_id=user_id,
            actor_role=user_role,
            before_status=old_status,
            after_status="APPROVED",
            reason=remarks or "Approved payment batch",
        )
        await session.commit()
        await session.refresh(batch)
        return batch

    @classmethod
    async def reject_batch(
        cls,
        session: AsyncSession,
        batch_id: uuid.UUID,
        reason: str,
        user_id: Optional[uuid.UUID] = None,
        user_role: Optional[str] = None,
    ) -> PaymentBatch:
        batch = await cls.get_batch(session, batch_id)
        old_status = batch.status
        batch.status = "REJECTED"
        batch.rejected_by = user_id
        batch.rejected_at = datetime.now()
        batch.rejection_reason = reason

        await PayrollAuditService.log_event(
            session=session,
            entity_type="PaymentBatch",
            entity_id=batch.id,
            action="REJECT",
            company_id=batch.company_id,
            actor_id=user_id,
            actor_role=user_role,
            before_status=old_status,
            after_status="REJECTED",
            reason=reason,
        )
        await session.commit()
        await session.refresh(batch)
        return batch

    @classmethod
    async def submit_batch(
        cls,
        session: AsyncSession,
        batch_id: uuid.UUID,
        bank_reference_number: str,
        submission_date: date,
        notes: Optional[str] = None,
        user_id: Optional[uuid.UUID] = None,
        user_role: Optional[str] = None,
    ) -> PaymentBatch:
        batch = await cls.get_batch(session, batch_id)
        old_status = batch.status
        batch.status = "SUBMITTED"
        batch.bank_reference_number = bank_reference_number
        batch.submission_date = submission_date
        batch.notes = notes

        # Update non-held items to SUCCESS / PROCESSING
        item_stmt = select(PaymentBatchItem).where(
            PaymentBatchItem.batch_id == batch.id, PaymentBatchItem.status == "PENDING"
        )
        items = (await session.execute(item_stmt)).scalars().all()
        for item in items:
            item.status = "SUCCESS"
            item.transaction_ref = f"{bank_reference_number}-{item.id.hex[:6]}"

        await PayrollAuditService.log_event(
            session=session,
            entity_type="PaymentBatch",
            entity_id=batch.id,
            action="SUBMIT",
            company_id=batch.company_id,
            actor_id=user_id,
            actor_role=user_role,
            before_status=old_status,
            after_status="SUBMITTED",
            reason=f"Submitted batch with bank ref: {bank_reference_number}",
        )
        await session.commit()
        await session.refresh(batch)
        return batch

    @classmethod
    async def validate_batch(cls, session: AsyncSession, batch_id: uuid.UUID) -> dict[str, Any]:
        batch = await cls.get_batch(session, batch_id)
        item_stmt = select(PaymentBatchItem).where(PaymentBatchItem.batch_id == batch.id)
        items = (await session.execute(item_stmt)).scalars().all()

        errors = []
        for item in items:
            if not item.account_number or len(item.account_number) < 5:
                errors.append({"item_id": str(item.id), "employee_id": str(item.employee_id), "issue": "Invalid account number"})
            if not item.ifsc_code or len(item.ifsc_code) != 11:
                errors.append({"item_id": str(item.id), "employee_id": str(item.employee_id), "issue": "Invalid IFSC code"})

        status_res = "VALID" if not errors else "WARNING"
        return {
            "batch_id": str(batch.id),
            "status": status_res,
            "total_items": len(items),
            "errors": errors,
        }

    @classmethod
    async def reconcile_batch(cls, session: AsyncSession, batch_id: uuid.UUID) -> PaymentBatch:
        batch = await cls.get_batch(session, batch_id)
        old_status = batch.status
        batch.status = "RECONCILED"

        await PayrollAuditService.log_event(
            session=session,
            entity_type="PaymentBatch",
            entity_id=batch.id,
            action="RECONCILE",
            company_id=batch.company_id,
            before_status=old_status,
            after_status="RECONCILED",
        )
        await session.commit()
        await session.refresh(batch)
        return batch

    @classmethod
    async def hold_item(
        cls, session: AsyncSession, batch_id: uuid.UUID, item_id: uuid.UUID, reason: str, user_id: Optional[uuid.UUID] = None
    ) -> PaymentBatchItem:
        stmt = select(PaymentBatchItem).where(
            PaymentBatchItem.id == item_id, PaymentBatchItem.batch_id == batch_id
        )
        item = (await session.execute(stmt)).scalar_one_or_none()
        if not item:
            raise HTTPException(status_code=404, detail="Batch item not found.")

        item.status = "HELD"
        item.hold_reason = reason
        await session.commit()
        await session.refresh(item)
        return item

    @classmethod
    async def release_item(
        cls, session: AsyncSession, batch_id: uuid.UUID, item_id: uuid.UUID, remarks: Optional[str] = None, user_id: Optional[uuid.UUID] = None
    ) -> PaymentBatchItem:
        stmt = select(PaymentBatchItem).where(
            PaymentBatchItem.id == item_id, PaymentBatchItem.batch_id == batch_id
        )
        item = (await session.execute(stmt)).scalar_one_or_none()
        if not item:
            raise HTTPException(status_code=404, detail="Batch item not found.")

        item.status = "RELEASED"
        item.remarks = remarks
        await session.commit()
        await session.refresh(item)
        return item

    @classmethod
    async def retry_item(
        cls,
        session: AsyncSession,
        batch_id: uuid.UUID,
        item_id: uuid.UUID,
        reason: str,
        updated_details: Optional[UpdatedBankDetails] = None,
        user_id: Optional[uuid.UUID] = None,
    ) -> PaymentBatchItem:
        stmt = select(PaymentBatchItem).where(
            PaymentBatchItem.id == item_id, PaymentBatchItem.batch_id == batch_id
        )
        item = (await session.execute(stmt)).scalar_one_or_none()
        if not item:
            raise HTTPException(status_code=404, detail="Batch item not found.")

        if updated_details:
            if updated_details.account_number:
                item.account_number = updated_details.account_number
            if updated_details.ifsc_code:
                item.ifsc_code = updated_details.ifsc_code
            if updated_details.account_holder_name:
                item.account_holder_name = updated_details.account_holder_name

        item.status = "RETRIED"
        item.retry_count += 1
        item.remarks = f"Retry reason: {reason}"
        await session.commit()
        await session.refresh(item)
        return item

    @classmethod
    async def generate_bank_file(
        cls, session: AsyncSession, batch_id: uuid.UUID, file_format: str
    ) -> PaymentBatchBankFile:
        batch = await cls.get_batch(session, batch_id)
        item_stmt = select(PaymentBatchItem).where(
            PaymentBatchItem.batch_id == batch.id,
            PaymentBatchItem.status.in_(("PENDING", "RELEASED", "SUCCESS")),
        )
        items = (await session.execute(item_stmt)).scalars().all()

        output = io.StringIO()
        if file_format in ("HDFC_CSV", "GENERIC_NEFT_CSV"):
            writer = csv.writer(output)
            writer.writerow(["Beneficiary_Account", "IFSC", "Amount", "Beneficiary_Name", "Remarks"])
            for it in items:
                writer.writerow([
                    it.account_number or "",
                    it.ifsc_code or "",
                    f"{it.amount_paise / 100.0:.2f}",
                    it.account_holder_name or "",
                    f"Salary {batch.batch_number}",
                ])
        elif file_format == "SBI_TXT":
            for it in items:
                output.write(
                    f"{it.account_number}|{it.ifsc_code}|{it.amount_paise / 100.0:.2f}|{it.account_holder_name}\n"
                )
        else:  # ICICI_EXCEL / default CSV
            writer = csv.writer(output)
            writer.writerow(["Debit Account", "Credit Account", "IFSC", "Amount", "Beneficiary Name"])
            for it in items:
                writer.writerow([
                    batch.source_account_id,
                    it.account_number or "",
                    it.ifsc_code or "",
                    f"{it.amount_paise / 100.0:.2f}",
                    it.account_holder_name or "",
                ])

        content_str = output.getvalue()
        file_name = f"{batch.batch_number}_{file_format}.csv"

        bank_file = PaymentBatchBankFile(
            id=uuid.uuid4(),
            batch_id=batch.id,
            company_id=batch.company_id,
            file_format=file_format,
            file_name=file_name,
            file_content=content_str,
            status="GENERATED",
        )
        session.add(bank_file)
        await session.commit()
        await session.refresh(bank_file)
        return bank_file

    @classmethod
    async def get_latest_bank_file(
        cls, session: AsyncSession, batch_id: uuid.UUID
    ) -> PaymentBatchBankFile:
        stmt = (
            select(PaymentBatchBankFile)
            .where(PaymentBatchBankFile.batch_id == batch_id)
            .order_by(desc(PaymentBatchBankFile.created_at))
        )
        bf = (await session.execute(stmt)).scalars().first()
        if not bf:
            # Auto-generate a generic NEFT file
            return await cls.generate_bank_file(session, batch_id, "GENERIC_NEFT_CSV")
        return bf

    @classmethod
    async def preview_bank_response(
        cls, session: AsyncSession, batch_id: uuid.UUID, file: UploadFile
    ) -> dict[str, Any]:
        content = await file.read()
        text_stream = io.StringIO(content.decode("utf-8-sig", errors="ignore"))
        reader = csv.DictReader(text_stream)

        rows = []
        valid_count = 0
        for r in reader:
            tx_ref = r.get("TransactionRef") or r.get("transaction_ref") or r.get("Ref") or ""
            status_val = r.get("Status") or r.get("status") or "SUCCESS"
            acc = r.get("Account") or r.get("account_number") or ""
            rows.append({
                "account_number": acc,
                "status": status_val.upper(),
                "transaction_ref": tx_ref,
            })
            valid_count += 1

        preview_token = f"bnk_tok_{uuid.uuid4().hex[:16]}"
        cache_data = {"batch_id": str(batch_id), "rows": rows}
        await redis_client.set(
            f"{cls.BANK_RESP_PREFIX}{preview_token}",
            json.dumps(cache_data),
            ttl_seconds=1800,
        )

        return {
            "previewToken": preview_token,
            "total_rows": len(rows),
            "matched_records": valid_count,
        }

    @classmethod
    async def apply_bank_response(
        cls, session: AsyncSession, batch_id: uuid.UUID, preview_token: str, allow_partial: bool
    ) -> dict[str, Any]:
        cached = await redis_client.get(f"{cls.BANK_RESP_PREFIX}{preview_token}")
        if not cached:
            raise HTTPException(status_code=400, detail="Preview token has expired or is invalid.")

        data = json.loads(cached)
        rows = data.get("rows", [])

        # Fetch batch items
        item_stmt = select(PaymentBatchItem).where(PaymentBatchItem.batch_id == batch_id)
        items = (await session.execute(item_stmt)).scalars().all()
        item_map = {it.account_number: it for it in items if it.account_number}

        updated = 0
        for r in rows:
            acc = r.get("account_number")
            st = r.get("status", "SUCCESS")
            ref = r.get("transaction_ref")
            if acc in item_map:
                item = item_map[acc]
                item.status = "SUCCESS" if st == "SUCCESS" else "FAILED"
                item.transaction_ref = ref
                updated += 1

        batch = await cls.get_batch(session, batch_id)
        batch.status = "RECONCILED"
        await session.commit()
        await redis_client.delete(f"{cls.BANK_RESP_PREFIX}{preview_token}")

        return {"message": f"Bank response applied. {updated} items updated.", "updated_count": updated}
