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
    BANK_FORMAT_ALIASES = {
        "ICICI_CORPORATE": "ICICI_CORPORATE", "ICICI_CORPORATE_CSV": "ICICI_CORPORATE", "ICICI_EXCEL": "ICICI_CORPORATE",
        "HDFC_ENET_CSV": "HDFC_ENET_CSV", "HDFC_CSV": "HDFC_ENET_CSV",
        "SBI_CMP_TXT": "SBI_CMP_TXT", "SBI_TXT": "SBI_CMP_TXT",
        "GENERIC_NEFT_RTGS_CSV": "GENERIC_NEFT_RTGS_CSV", "GENERIC_NEFT_CSV": "GENERIC_NEFT_RTGS_CSV",
    }

    @classmethod
    def normalise_bank_format(cls, value: str) -> str:
        clean = str(value).strip().upper()
        if clean not in cls.BANK_FORMAT_ALIASES:
            raise HTTPException(status_code=400, detail=f"Unsupported bank format: {value}")
        return cls.BANK_FORMAT_ALIASES[clean]

    @staticmethod
    def assert_export_approved(batch: PaymentBatch) -> None:
        if (
            not batch.approved_by or not batch.approved_at or
            batch.status not in {"APPROVED", "SUBMITTED", "RECONCILED"}
        ):
            raise HTTPException(
                status_code=409,
                detail={"code": "BATCH_APPROVAL_REQUIRED", "message": "Maker-checker approval is required before bank file export."},
            )

    @staticmethod
    def maker_ids_for_batch(batch: PaymentBatch) -> list[uuid.UUID]:
        """Every user who initiated or processed this batch (the "makers")."""
        makers: list[uuid.UUID] = []
        for attr in ("created_by", "processed_by"):
            value = getattr(batch, attr, None)
            if value is None:
                continue
            try:
                parsed = value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
            except (ValueError, AttributeError, TypeError):
                continue
            if parsed not in makers:
                makers.append(parsed)
        return makers

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
    async def get_batch_details(
        cls,
        session: AsyncSession,
        batch_id: uuid.UUID,
        page: int = 1,
        limit: int = 50,
        status_filter: Optional[str] = None,
        search: Optional[str] = None,
    ) -> dict[str, Any]:
        batch = await cls.get_batch(session, batch_id)
        
        stmt = select(PaymentBatchItem).where(PaymentBatchItem.batch_id == batch_id)
        if status_filter:
            stmt = stmt.where(func.upper(PaymentBatchItem.status) == status_filter.upper())
        if search:
            stmt = stmt.where(
                PaymentBatchItem.account_number.ilike(f"%{search}%") |
                PaymentBatchItem.account_holder_name.ilike(f"%{search}%")
            )
        
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await session.execute(count_stmt)).scalar() or 0
        
        offset = max(0, (page - 1) * limit)
        stmt = stmt.order_by(PaymentBatchItem.created_at).offset(offset).limit(limit)
        items = (await session.execute(stmt)).scalars().all()
        
        return {
            "batch": batch,
            "items": {
                "items": items,
                "total": total,
                "page": page,
                "limit": limit,
            }
        }

    @classmethod
    async def list_batches(
        cls,
        session: AsyncSession,
        company_id: Optional[uuid.UUID] = None,
        run_id: Optional[uuid.UUID] = None,
        page: int = 1,
        limit: int = 20,
        status_filter: Optional[str] = None,
        period_id: Optional[str] = None,
        search: Optional[str] = None,
    ) -> dict[str, Any]:
        stmt = select(PaymentBatch)
        if company_id:
            stmt = stmt.where(PaymentBatch.company_id == company_id)
        if run_id:
            stmt = stmt.where(PaymentBatch.run_id == run_id)
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
        user_role: Optional[str] = None,
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
            # `source_account_id` is a VARCHAR column: always coerce to str so an
            # upstream UUID never reaches asyncpg as the wrong type.
            source_account_id=str(source_account_id),
            payment_mode=payment_mode,
            status="DRAFT",
            notes=notes,
            created_by=user_id,
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
            actor_role=user_role,
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

        # Strict maker-checker: the user who created/processed the batch may not
        # approve it.  Raises HTTP 403 with code MAKER_CHECKER_VIOLATION and writes
        # an immutable audit record when the tenant enforces the policy.
        from app.api.payroll.permissions import enforce_maker_checker

        await enforce_maker_checker(
            session,
            entity_type="PaymentBatch",
            entity_id=batch.id,
            company_id=batch.company_id,
            maker_ids=cls.maker_ids_for_batch(batch),
            approver_id=user_id,
            actor_role=user_role,
            action="APPROVE",
            before_status=old_status,
        )

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
        # Submitting a batch to the bank is "processing" it for maker-checker.
        if user_id is not None:
            batch.processed_by = user_id

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
    async def reconcile_batch(
        cls, session: AsyncSession, batch_id: uuid.UUID, user_id: Optional[uuid.UUID] = None, user_role: Optional[str] = None
    ) -> PaymentBatch:
        batch = await cls.get_batch(session, batch_id)
        old_status = batch.status
        batch.status = "RECONCILED"

        await PayrollAuditService.log_event(
            session=session,
            entity_type="PaymentBatch",
            entity_id=batch.id,
            action="RECONCILE",
            company_id=batch.company_id,
            actor_id=user_id,
            actor_role=user_role,
            before_status=old_status,
            after_status="RECONCILED",
        )
        await session.commit()
        await session.refresh(batch)
        return batch

    @classmethod
    async def hold_item(
        cls, session: AsyncSession, batch_id: uuid.UUID, item_id: uuid.UUID, reason: str, user_id: Optional[uuid.UUID] = None, user_role: Optional[str] = None
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
        cls, session: AsyncSession, batch_id: uuid.UUID, item_id: uuid.UUID, remarks: Optional[str] = None, user_id: Optional[uuid.UUID] = None, user_role: Optional[str] = None
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
        updated_bank_details: Optional[UpdatedBankDetails] = None,
        user_id: Optional[uuid.UUID] = None,
        user_role: Optional[str] = None,
    ) -> PaymentBatchItem:
        stmt = select(PaymentBatchItem).where(
            PaymentBatchItem.id == item_id, PaymentBatchItem.batch_id == batch_id
        )
        item = (await session.execute(stmt)).scalar_one_or_none()
        if not item:
            raise HTTPException(status_code=404, detail="Batch item not found.")

        if updated_bank_details:
            if updated_bank_details.account_number:
                item.account_number = updated_bank_details.account_number
            if updated_bank_details.ifsc_code:
                item.ifsc_code = updated_bank_details.ifsc_code
            if updated_bank_details.account_holder_name:
                item.account_holder_name = updated_bank_details.account_holder_name

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
        cls.assert_export_approved(batch)
        canonical_format = cls.normalise_bank_format(file_format)
        item_stmt = select(PaymentBatchItem).where(
            PaymentBatchItem.batch_id == batch.id,
            PaymentBatchItem.status.in_(("PENDING", "RELEASED", "SUCCESS")),
        ).order_by(PaymentBatchItem.created_at)
        items = (await session.execute(item_stmt)).scalars().all()
        if not items:
            raise HTTPException(status_code=409, detail="No exportable payout items remain in this batch.")

        output = io.StringIO()
        writer = csv.writer(output)
        if canonical_format == "HDFC_ENET_CSV":
            writer.writerow(["Debit_Account", "Beneficiary_Account", "IFSC", "Amount", "Beneficiary_Name", "Remarks"])
            for item in items:
                writer.writerow([batch.source_account_id, item.account_number or "", item.ifsc_code or "",
                                 f"{item.amount_paise / 100.0:.2f}", item.account_holder_name or "", f"Salary {batch.batch_number}"])
        elif canonical_format == "SBI_CMP_TXT":
            writer = csv.writer(output, delimiter="|", lineterminator="\n")
            for item in items:
                writer.writerow([batch.batch_number, item.account_number or "", item.ifsc_code or "",
                                 f"{item.amount_paise / 100.0:.2f}", item.account_holder_name or ""])
        elif canonical_format == "GENERIC_NEFT_RTGS_CSV":
            writer.writerow(["Payment_Mode", "Beneficiary_Account", "IFSC", "Amount", "Beneficiary_Name", "Remarks"])
            for item in items:
                writer.writerow(["RTGS" if batch.payment_mode == "RTGS" else "NEFT", item.account_number or "",
                                 item.ifsc_code or "", f"{item.amount_paise / 100.0:.2f}",
                                 item.account_holder_name or "", f"Salary {batch.batch_number}"])
        else:  # ICICI Corporate Internet Banking CSV (legacy ICICI_EXCEL alias)
            writer.writerow(["Debit Account", "Credit Account", "IFSC", "Amount", "Beneficiary Name", "Payment Details"])
            for item in items:
                writer.writerow([batch.source_account_id, item.account_number or "", item.ifsc_code or "",
                                 f"{item.amount_paise / 100.0:.2f}", item.account_holder_name or "", batch.batch_number])

        extension = "txt" if canonical_format == "SBI_CMP_TXT" else "csv"
        bank_file = PaymentBatchBankFile(
            id=uuid.uuid4(), batch_id=batch.id, company_id=batch.company_id,
            file_format=canonical_format, file_name=f"{batch.batch_number}_{canonical_format}.{extension}",
            file_content=output.getvalue(), status="GENERATED",
        )
        session.add(bank_file)
        await session.commit()
        await session.refresh(bank_file)
        return bank_file

    @classmethod
    async def get_latest_bank_file(
        cls, session: AsyncSession, batch_id: uuid.UUID
    ) -> tuple[bytes, str, str]:
        batch = await cls.get_batch(session, batch_id)
        cls.assert_export_approved(batch)
        stmt = (
            select(PaymentBatchBankFile)
            .where(PaymentBatchBankFile.batch_id == batch_id)
            .order_by(desc(PaymentBatchBankFile.created_at))
        )
        bank_file = (await session.execute(stmt)).scalars().first()
        if not bank_file:
            bank_file = await cls.generate_bank_file(session, batch_id, "GENERIC_NEFT_RTGS_CSV")
        content_bytes = bank_file.file_content.encode("utf-8") if bank_file.file_content else b""
        media_type = "text/plain" if bank_file.file_name.endswith(".txt") else "text/csv"
        return content_bytes, bank_file.file_name, media_type

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
        cls, session: AsyncSession, batch_id: uuid.UUID, preview_token: str, allow_partial: bool, user_id: Optional[uuid.UUID] = None, user_role: Optional[str] = None
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
        old_status = batch.status
        batch.status = "RECONCILED"

        await PayrollAuditService.log_event(
            session=session,
            entity_type="PaymentBatch",
            entity_id=batch.id,
            action="APPLY_BANK_RESPONSE",
            company_id=batch.company_id,
            actor_id=user_id,
            actor_role=user_role,
            before_status=old_status,
            after_status="RECONCILED",
            reason=f"Applied bank response, {updated} items updated",
        )

        await session.commit()
        await redis_client.delete(f"{cls.BANK_RESP_PREFIX}{preview_token}")

        return {"message": f"Bank response applied. {updated} items updated.", "updated_count": updated}

    @classmethod
    async def reconcile_bank_feed(
        cls, session: AsyncSession, batch_id: uuid.UUID, rows: list[dict[str, Any]],
        *, allow_partial: bool = False, company_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None, user_role: str | None = None,
    ) -> dict[str, Any]:
        """Apply a bank UTR reverse feed and create one linked re-payout batch.

        Rows may identify an item by item_id, transaction_ref, or account number.
        All rows are validated before any item is changed.  Replaying the same
        feed is safe and never creates a second re-payout for the original item.
        """
        if not rows:
            raise HTTPException(status_code=400, detail="At least one bank response row is required.")
        batch = await cls.get_batch(session, batch_id)
        if company_id is not None and batch.company_id != company_id:
            raise HTTPException(status_code=404, detail="Payment batch not found.")
        if batch.status not in {"APPROVED", "SUBMITTED", "RECONCILED"}:
            raise HTTPException(status_code=409, detail="Only an approved/submitted batch can be reconciled.")
        items = (await session.execute(select(PaymentBatchItem).where(
            PaymentBatchItem.batch_id == batch.id,
        ))).scalars().all()
        by_id = {str(item.id): item for item in items}
        by_account: dict[str, list[PaymentBatchItem]] = {}
        by_ref = {}
        for item in items:
            if item.account_number:
                by_account.setdefault(item.account_number, []).append(item)
            if item.transaction_ref:
                by_ref[item.transaction_ref] = item

        resolved: list[tuple[PaymentBatchItem, str, str | None, str | None, str | None]] = []
        errors: list[str] = []
        seen: set[uuid.UUID] = set()
        for index, row in enumerate(rows, start=1):
            item = None
            item_id = row.get("item_id") or row.get("itemId")
            account = row.get("account_number") or row.get("Account") or row.get("account")
            reference = row.get("transaction_ref") or row.get("TransactionRef") or row.get("Ref")
            if item_id:
                item = by_id.get(str(item_id))
            elif reference and reference in by_ref:
                item = by_ref[reference]
            elif account:
                matches = by_account.get(str(account), [])
                if len(matches) > 1:
                    errors.append(f"Row {index}: account number is ambiguous; supply item_id.")
                    continue
                item = matches[0] if matches else None
            if item is None:
                if not allow_partial:
                    errors.append(f"Row {index}: no matching payout item.")
                continue
            if item.id in seen:
                errors.append(f"Row {index}: duplicate payout item.")
                continue
            seen.add(item.id)
            raw_status = str(row.get("status") or row.get("Status") or "").strip().upper()
            if raw_status in {"SUCCESS", "COMPLETED", "PAID"}:
                canonical_status = "PAID"
            elif raw_status in {"FAILED", "FAILURE", "REJECTED", "RETURNED"}:
                canonical_status = "FAILED"
            else:
                errors.append(f"Row {index}: status must be PAID/SUCCESS or FAILED.")
                continue
            utr = row.get("utr_number") or row.get("utr") or row.get("UTR") or reference
            utr = str(utr).strip() if utr else None
            if canonical_status == "PAID" and not utr:
                errors.append(f"Row {index}: UTR is required for a paid payout.")
                continue
            if item.status == "PAID" and (canonical_status != "PAID" or (item.utr_number and item.utr_number != utr)):
                errors.append(f"Row {index}: a paid payout cannot be changed by a later feed.")
                continue
            error_message = row.get("error_message") or row.get("reason") or row.get("Error")
            resolved.append((item, canonical_status, utr, reference, error_message))
        if errors:
            raise HTTPException(status_code=400, detail={"code": "INVALID_BANK_FEED", "errors": errors})
        if not resolved:
            raise HTTPException(status_code=400, detail="No bank response rows matched this batch.")

        now = datetime.now()
        paid_count = failed_count = 0
        failed_items: list[PaymentBatchItem] = []
        for item, canonical_status, utr, reference, error_message in resolved:
            item.status = canonical_status
            item.utr_number = utr
            item.transaction_ref = reference or utr or item.transaction_ref
            item.reconciled_at = now
            item.error_message = str(error_message)[:500] if error_message else None
            if canonical_status == "PAID":
                paid_count += 1
            else:
                failed_count += 1
                failed_items.append(item)
            payslip = (await session.execute(select(Payslip).where(
                Payslip.payroll_run_id == batch.run_id, Payslip.employee_id == item.employee_id,
            ))).scalar_one_or_none()
            if payslip:
                payslip.payment_status = canonical_status
                payslip.payment_reference = utr
                payslip.payment_date = date.today() if canonical_status == "PAID" else None

        retry_batch = None
        pending_retry = [item for item in failed_items if item.repayout_batch_id is None]
        if pending_retry:
            retry_batch = PaymentBatch(
                id=uuid.uuid4(), company_id=batch.company_id, run_id=batch.run_id,
                batch_number=f"RP-{uuid.uuid4().hex[:18].upper()}",
                source_account_id=batch.source_account_id, payment_mode=batch.payment_mode,
                status="DRAFT", notes=f"Automatic re-payout for failed items in {batch.batch_number}",
                created_by=user_id, retry_of_batch_id=batch.id,
                total_amount_paise=sum(item.amount_paise for item in pending_retry), total_records=len(pending_retry),
            )
            session.add(retry_batch)
            await session.flush()
            for original in pending_retry:
                session.add(PaymentBatchItem(
                    id=uuid.uuid4(), batch_id=retry_batch.id, employee_id=original.employee_id,
                    company_id=original.company_id, amount_paise=original.amount_paise, status="PENDING",
                    account_number=original.account_number, ifsc_code=original.ifsc_code,
                    account_holder_name=original.account_holder_name,
                    remarks=f"Re-payout of original item {original.id}",
                ))
                original.repayout_batch_id = retry_batch.id
        else:
            retry_id = next((item.repayout_batch_id for item in failed_items if item.repayout_batch_id), None)
            if retry_id:
                retry_batch = await session.get(PaymentBatch, retry_id)

        old_status = batch.status
        batch.status = "RECONCILED"
        await PayrollAuditService.log_event(
            session=session, entity_type="PaymentBatch", entity_id=batch.id, action="BANK_UTR_RECONCILE",
            company_id=batch.company_id, actor_id=user_id, actor_role=user_role,
            before_status=old_status, after_status="RECONCILED",
            reason=f"UTR feed: {paid_count} paid, {failed_count} failed; re-payout {retry_batch.id if retry_batch else 'not required'}",
        )
        await session.commit()
        return {
            "batch_id": str(batch.id), "status": batch.status, "updated_count": len(resolved),
            "paid_count": paid_count, "failed_count": failed_count,
            "repayout_batch_id": str(retry_batch.id) if retry_batch else None,
            "re_payout_batch_id": str(retry_batch.id) if retry_batch else None,
            "items": [{"item_id": str(item.id), "status": item.status, "utr_number": item.utr_number} for item, *_ in resolved],
        }
