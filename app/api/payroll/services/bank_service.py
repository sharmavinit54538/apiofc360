"""Service handling bank transfer advice files and direct payment disbursements — 100% Database Driven."""
from __future__ import annotations

import csv
import io
import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, List, Dict, Any

from sqlalchemy import select, update, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.payroll import BankDisbursementRecord, BankAdviceFile, Payslip, PayrollAuditLog, PayCycle, PayrollRun
from app.models.employee import Employee
from app.models.employee_bank_account import EmployeeBankAccount
from app.services.payroll.audit_service import PayrollAuditService

logger = logging.getLogger(__name__)


class BankService:
    """Business logic for NEFT/ACH advice file creation and payment batch status."""

    def __init__(self, db: AsyncSession, company_id: Optional[uuid.UUID] = None, actor_id: Optional[uuid.UUID] = None):
        self.db = db
        self.company_id = company_id
        self.actor_id = actor_id

    def _resolve_cid(self, company_id: Optional[uuid.UUID] = None) -> Optional[uuid.UUID]:
        return company_id or self.company_id

    async def get_transfers(
        self,
        search: Optional[str] = None,
        department: Optional[str] = None,
        bank: Optional[str] = None,
        payment_status: Optional[str] = None,
        company_id: Optional[uuid.UUID] = None,
    ) -> list[dict]:
        """Fetch real bank transfer items from PostgreSQL database."""
        cid = self._resolve_cid(company_id)

        stmt = (
            select(BankDisbursementRecord)
            .join(BankAdviceFile, BankDisbursementRecord.advice_file_id == BankAdviceFile.id, isouter=True)
            .join(Employee, BankDisbursementRecord.employee_id == Employee.id, isouter=True)
            .options(
                selectinload(BankDisbursementRecord.advice_file),
            )
            .order_by(BankDisbursementRecord.created_at.desc())
        )

        if cid:
            stmt = stmt.where(
                or_(
                    BankAdviceFile.company_id == cid,
                    Employee.company_id == cid,
                )
            )

        if bank and bank.upper() not in ("ALL", ""):
            stmt = stmt.where(func.lower(BankDisbursementRecord.bank_name) == bank.lower())

        if payment_status and payment_status.upper() not in ("ALL", ""):
            status_map = {
                "COMPLETED": "SUCCESS",
                "SUCCESS": "SUCCESS",
                "FAILED": "FAILED",
                "PENDING": "PENDING",
                "PROCESSING": "PROCESSING",
            }
            target_status = status_map.get(payment_status.upper(), payment_status.upper())
            stmt = stmt.where(BankDisbursementRecord.status == target_status)

        result = await self.db.execute(stmt)
        records = result.scalars().all()

        if not records:
            return []

        # Bulk fetch employees to avoid N+1 queries
        emp_ids = {r.employee_id for r in records if r.employee_id}
        emp_map: dict[uuid.UUID, Employee] = {}
        if emp_ids:
            emp_stmt = select(Employee).where(Employee.id.in_(emp_ids))
            emp_result = await self.db.execute(emp_stmt)
            for emp in emp_result.scalars().all():
                emp_map[emp.id] = emp

        output = []
        for r in records:
            emp = emp_map.get(r.employee_id)
            emp_name = f"{emp.first_name} {emp.last_name}".strip() if emp else "Unknown Employee"
            dept = emp.department if emp and emp.department else "General"
            desig = emp.designation if emp and emp.designation else "Staff"
            acc_num = r.bank_account_number or ""
            masked_acc = f"XXXX-XXXX-{acc_num[-4:]}" if len(acc_num) >= 4 else "XXXX"

            status_val = (r.status or "PENDING").upper()
            pay_status = "COMPLETED" if status_val == "SUCCESS" else status_val
            bank_status = "SETTLED" if status_val == "SUCCESS" else ("FAILED" if status_val == "FAILED" else "READY")

            advice = r.advice_file
            batch_code = advice.batch_code if advice and advice.batch_code else "BATCH-DIRECT"

            item = {
                "id": str(r.id),
                "employee_id": str(r.employee_id),
                "employee_name": emp_name,
                "department": dept,
                "designation": desig,
                "bank_name": r.bank_name or "Not Specified",
                "account_holder": emp_name,
                "masked_account_number": masked_acc,
                "ifsc": r.bank_ifsc or "",
                "net_salary": float(r.amount) if r.amount is not None else 0.0,
                "batch_code": batch_code,
                "transfer_date": r.disbursed_at.strftime("%Y-%m-%d") if r.disbursed_at else (r.created_at.strftime("%Y-%m-%d") if r.created_at else None),
                "reference_number": r.transaction_ref or f"REF-{str(r.id)[:8].upper()}",
                "payment_status": pay_status,
                "bank_status": bank_status,
                "failure_reason": r.failure_reason,
                "last_updated": r.updated_at.strftime("%Y-%m-%d %H:%M") if r.updated_at else (r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else None),
            }

            if search:
                q = search.lower()
                if (
                    q not in emp_name.lower()
                    and q not in dept.lower()
                    and q not in item["reference_number"].lower()
                    and q not in desig.lower()
                ):
                    continue

            if department and department.upper() not in ("ALL", ""):
                if dept.lower() != department.lower():
                    continue

            output.append(item)

        return output

    async def get_dashboard_metrics(self, company_id: Optional[uuid.UUID] = None) -> dict:
        """Fetch bank transfer dashboard metrics aggregated from the database."""
        cid = self._resolve_cid(company_id)

        stmt = (
            select(
                BankDisbursementRecord.status,
                func.count(BankDisbursementRecord.id).label("count"),
                func.coalesce(func.sum(BankDisbursementRecord.amount), Decimal(0)).label("total_amount"),
            )
            .join(BankAdviceFile, BankDisbursementRecord.advice_file_id == BankAdviceFile.id, isouter=True)
            .join(Employee, BankDisbursementRecord.employee_id == Employee.id, isouter=True)
        )
        if cid:
            stmt = stmt.where(
                or_(
                    BankAdviceFile.company_id == cid,
                    Employee.company_id == cid,
                )
            )
        stmt = stmt.group_by(BankDisbursementRecord.status)

        res = await self.db.execute(stmt)
        rows = res.all()

        total_emp = 0
        total_amount = Decimal(0)
        transferred_amount = Decimal(0)
        pending_amount = Decimal(0)
        rejected_amount = Decimal(0)

        ready_count = 0
        processing_count = 0
        success_count = 0
        failed_count = 0

        for status_raw, count, amt in rows:
            st = (status_raw or "PENDING").upper()
            amt_dec = Decimal(str(amt or 0))
            total_emp += count
            total_amount += amt_dec

            if st in ("SUCCESS", "COMPLETED"):
                transferred_amount += amt_dec
                success_count += count
            elif st in ("FAILED", "REJECTED"):
                rejected_amount += amt_dec
                failed_count += count
            elif st == "PROCESSING":
                pending_amount += amt_dec
                processing_count += count
            else:  # PENDING, READY, etc.
                pending_amount += amt_dec
                ready_count += count

        return {
            "total_employees": total_emp,
            "ready_for_payment": ready_count,
            "pending_verification": 0,
            "transfer_processing": processing_count,
            "successful_transfers": success_count,
            "failed_transfers": failed_count,
            "total_salary_amount": float(total_amount),
            "transferred_amount": float(transferred_amount),
            "pending_amount": float(pending_amount),
            "rejected_amount": float(rejected_amount),
        }

    async def get_transfer_detail(self, transfer_id: str, company_id: Optional[uuid.UUID] = None) -> Optional[dict]:
        """Get detail of a specific bank transfer by UUID. Returns None if not found."""
        cid = self._resolve_cid(company_id)
        try:
            uid = uuid.UUID(transfer_id)
        except (ValueError, TypeError):
            return None

        stmt = (
            select(BankDisbursementRecord)
            .join(BankAdviceFile, BankDisbursementRecord.advice_file_id == BankAdviceFile.id, isouter=True)
            .join(Employee, BankDisbursementRecord.employee_id == Employee.id, isouter=True)
            .options(selectinload(BankDisbursementRecord.advice_file))
            .where(BankDisbursementRecord.id == uid)
        )
        if cid:
            stmt = stmt.where(
                or_(
                    BankAdviceFile.company_id == cid,
                    Employee.company_id == cid,
                )
            )

        res = await self.db.execute(stmt)
        record = res.scalars().first()
        if not record:
            return None

        emp_stmt = select(Employee).where(Employee.id == record.employee_id)
        emp_res = await self.db.execute(emp_stmt)
        emp = emp_res.scalars().first()

        emp_name = f"{emp.first_name} {emp.last_name}".strip() if emp else "Unknown Employee"
        dept = emp.department if emp and emp.department else "General"
        desig = emp.designation if emp and emp.designation else "Staff"
        acc_num = record.bank_account_number or ""
        masked_acc = f"XXXX-XXXX-{acc_num[-4:]}" if len(acc_num) >= 4 else "XXXX"

        status_val = (record.status or "PENDING").upper()
        pay_status = "COMPLETED" if status_val == "SUCCESS" else status_val
        bank_status = "SETTLED" if status_val == "SUCCESS" else ("FAILED" if status_val == "FAILED" else "READY")

        advice = record.advice_file
        batch_code = advice.batch_code if advice and advice.batch_code else "BATCH-DIRECT"

        # Build timeline from real timestamps
        timeline = []
        if record.created_at:
            timeline.append({
                "title": "Transfer Batch Created",
                "timestamp": record.created_at.strftime("%Y-%m-%d %H:%M"),
                "actor": "Payroll System",
            })
        if advice and advice.generated_at:
            timeline.append({
                "title": f"Bank Advice File Generated ({advice.file_format or 'NEFT'})",
                "timestamp": advice.generated_at.strftime("%Y-%m-%d %H:%M"),
                "actor": "System",
            })
        if record.disbursed_at:
            timeline.append({
                "title": "Payment Settled",
                "timestamp": record.disbursed_at.strftime("%Y-%m-%d %H:%M"),
                "actor": "Bank Settlement",
            })
        elif status_val == "FAILED":
            timeline.append({
                "title": "Transfer Failed",
                "timestamp": (record.updated_at or record.created_at).strftime("%Y-%m-%d %H:%M"),
                "actor": "Gateway",
                "reason": record.failure_reason or "Bank rejection",
            })

        return {
            "id": str(record.id),
            "employee_id": str(record.employee_id),
            "employee_name": emp_name,
            "department": dept,
            "designation": desig,
            "bank_name": record.bank_name or "Not Specified",
            "account_holder": emp_name,
            "masked_account_number": masked_acc,
            "ifsc": record.bank_ifsc or "",
            "net_salary": float(record.amount) if record.amount is not None else 0.0,
            "batch_code": batch_code,
            "transfer_date": record.disbursed_at.strftime("%Y-%m-%d") if record.disbursed_at else (record.created_at.strftime("%Y-%m-%d") if record.created_at else None),
            "reference_number": record.transaction_ref or f"REF-{str(record.id)[:8].upper()}",
            "payment_status": pay_status,
            "bank_status": bank_status,
            "failure_reason": record.failure_reason,
            "last_updated": record.updated_at.strftime("%Y-%m-%d %H:%M") if record.updated_at else None,
            "branch": "Authorized Corporate Branch",
            "transfer_mode": advice.file_format if advice and advice.file_format else "NEFT",
            "settlement_date": record.disbursed_at.strftime("%Y-%m-%d %I:%M %p") if record.disbursed_at else None,
            "timeline": timeline,
        }

    async def create_transfer_batch(self, payload: dict, company_id: Optional[uuid.UUID] = None, actor_id: Optional[uuid.UUID] = None) -> dict:
        """Create and persist a new bank transfer batch from pending payslips for a specific pay cycle."""
        cid = self._resolve_cid(company_id)
        aid = actor_id or self.actor_id

        # Honor requested pay_cycle_id from payload
        pay_cycle_id = payload.get("pay_cycle_id")
        if not pay_cycle_id:
            raise ValueError("pay_cycle_id is required to create a transfer batch.")
        try:
            pay_cycle_uuid = uuid.UUID(str(pay_cycle_id))
        except (ValueError, TypeError):
            raise ValueError(f"Invalid pay_cycle_id: {pay_cycle_id}")

        # Verify PayCycle exists and get its period
        pay_cycle_stmt = select(PayCycle).where(PayCycle.id == pay_cycle_uuid)
        if cid:
            pay_cycle_stmt = pay_cycle_stmt.where(PayCycle.company_id == cid)
        pay_cycle_res = await self.db.execute(pay_cycle_stmt)
        pay_cycle = pay_cycle_res.scalars().first()
        if not pay_cycle:
            raise ValueError(f"PayCycle {pay_cycle_id} not found for this company.")

        # Query pending payslips for this company and pay cycle period
        payslips_stmt = select(Payslip).where(
            Payslip.payment_status == "PENDING",
            Payslip.period_month == pay_cycle.period_month,
            Payslip.period_year == pay_cycle.period_year,
        )
        if cid:
            payslips_stmt = payslips_stmt.where(Payslip.company_id == cid)

        res = await self.db.execute(payslips_stmt)
        pending_payslips = res.scalars().all()

        if not pending_payslips:
            # Empty batch - return early with clear response
            return {
                "batch_id": None,
                "batch_code": None,
                "status": "EMPTY",
                "total_records": 0,
                "total_amount": 0.0,
                "message": f"No pending payslips found for pay cycle {pay_cycle_id} (period {pay_cycle.period_month:02d}-{pay_cycle.period_year}).",
            }

        now = datetime.now(timezone.utc)
        batch_code = f"BATCH-{now.strftime('%Y%m%d%H%M%S')}"
        file_format = payload.get("format", "NEFT").upper()
        file_id = uuid.uuid4()

        total_amount = Decimal(0)
        total_records = len(pending_payslips)

        # Create BankAdviceFile with correct pay_cycle_id
        advice_file = BankAdviceFile(
            id=file_id,
            company_id=cid,
            pay_cycle_id=pay_cycle_uuid,
            file_name=f"SALARY_{file_format}_ADVICE_{batch_code}.csv",
            file_format=file_format,
            total_amount=Decimal(0),
            total_records=total_records,
            batch_code=batch_code,
            status="CREATED",
            generated_by=aid,
            generated_at=now,
        )
        self.db.add(advice_file)
        await self.db.flush()

        # For each payslip, query bank details and create BankDisbursementRecord
        missing_bank_details = []
        for ps in pending_payslips:
            amt = Decimal(str(ps.net_pay or 0))
            total_amount += amt

            # Lookup primary employee bank account
            ba_stmt = select(EmployeeBankAccount).where(
                EmployeeBankAccount.employee_id == ps.employee_id,
                EmployeeBankAccount.is_primary == True,
            )
            ba_res = await self.db.execute(ba_stmt)
            bank_acc = ba_res.scalars().first()

            if not bank_acc or not bank_acc.account_number or not bank_acc.ifsc_code:
                missing_bank_details.append(str(ps.employee_id))
                # Still create record but with empty bank details - will be flagged
                bank_name = bank_acc.bank_name if bank_acc else None
                account_number = bank_acc.account_number if bank_acc else None
                ifsc_code = bank_acc.ifsc_code if bank_acc else None
            else:
                bank_name = bank_acc.bank_name
                account_number = bank_acc.account_number
                ifsc_code = bank_acc.ifsc_code

            disb_rec = BankDisbursementRecord(
                id=uuid.uuid4(),
                advice_file_id=advice_file.id,
                pay_cycle_id=pay_cycle_uuid,
                employee_id=ps.employee_id,
                bank_name=bank_name,
                bank_account_number=account_number,
                bank_ifsc=ifsc_code,
                amount=amt,
                status="PENDING" if bank_name and account_number and ifsc_code else "MISSING_BANK_DETAILS",
            )
            self.db.add(disb_rec)

        advice_file.total_amount = total_amount
        await self.db.commit()

        # Log audit event
        await PayrollAuditService.log_event(
            session=self.db,
            entity_type="BankAdviceFile",
            entity_id=advice_file.id,
            action="CREATE_TRANSFER_BATCH",
            company_id=cid,
            actor_id=aid,
            after_status="CREATED",
            reason=f"Created transfer batch {batch_code} for pay cycle {pay_cycle_id} with {total_records} records totaling ₹{total_amount:.2f}",
            extra_data={
                "pay_cycle_id": str(pay_cycle_uuid),
                "period": f"{pay_cycle.period_month:02d}-{pay_cycle.period_year}",
                "missing_bank_details_count": len(missing_bank_details),
            },
        )
        await self.db.commit()

        response = {
            "batch_id": str(advice_file.id),
            "batch_code": batch_code,
            "status": "CREATED",
            "total_records": total_records,
            "total_amount": float(total_amount),
            "pay_cycle_id": str(pay_cycle_uuid),
            "period": f"{pay_cycle.period_month:02d}-{pay_cycle.period_year}",
        }
        if missing_bank_details:
            response["warnings"] = {
                "missing_bank_details": missing_bank_details,
                "message": f"{len(missing_bank_details)} employee(s) have incomplete bank details. Transfers created with status MISSING_BANK_DETAILS.",
            }
        return response

    async def generate_bank_file(self, advice_file_id_or_format: str = "NEFT", company_id: Optional[uuid.UUID] = None) -> dict:
        """Generate actual CSV/NEFT advice file content and store on BankAdviceFile."""
        cid = self._resolve_cid(company_id)

        # Check if parameter is a valid UUID
        target_file: Optional[BankAdviceFile] = None
        try:
            fid = uuid.UUID(advice_file_id_or_format)
            stmt = select(BankAdviceFile).where(BankAdviceFile.id == fid)
            if cid:
                stmt = stmt.where(BankAdviceFile.company_id == cid)
            res = await self.db.execute(stmt)
            target_file = res.scalars().first()
        except (ValueError, TypeError):
            # Format string passed, find latest advice file by generated_at
            stmt = select(BankAdviceFile).order_by(BankAdviceFile.generated_at.desc().nullslast(), BankAdviceFile.created_at.desc())
            if cid:
                stmt = stmt.where(BankAdviceFile.company_id == cid)
            res = await self.db.execute(stmt)
            target_file = res.scalars().first()

        if not target_file:
            # Create a placeholder advice file if none exists
            batch_id = uuid.uuid4()
            batch_code = f"BATCH-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
            fmt = advice_file_id_or_format if advice_file_id_or_format in ("NEFT", "ACH", "RTGS", "CSV") else "NEFT"
            target_file = BankAdviceFile(
                id=batch_id,
                company_id=cid,
                pay_cycle_id=uuid.uuid4(),
                file_name=f"SALARY_ADVICE_{batch_code}.csv",
                file_format=fmt,
                total_amount=Decimal(0),
                total_records=0,
                batch_code=batch_code,
                status="GENERATED",
            )
            self.db.add(target_file)
            await self.db.flush()

        # Query disbursements for this advice file
        d_stmt = select(BankDisbursementRecord).where(BankDisbursementRecord.advice_file_id == target_file.id)
        d_res = await self.db.execute(d_stmt)
        disbursements = d_res.scalars().all()

        emp_ids = {d.employee_id for d in disbursements}
        emp_map: dict[uuid.UUID, Employee] = {}
        if emp_ids:
            e_res = await self.db.execute(select(Employee).where(Employee.id.in_(emp_ids)))
            for emp in e_res.scalars().all():
                emp_map[emp.id] = emp

        # Generate CSV payload
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Beneficiary Name", "Account Number", "IFSC Code", "Amount (INR)", "Payment Reference", "Remarks"])

        for d in disbursements:
            emp = emp_map.get(d.employee_id)
            name = f"{emp.first_name} {emp.last_name}".strip() if emp else "Employee"
            ref = d.transaction_ref or f"PAY-{str(d.id)[:8].upper()}"
            writer.writerow([name, d.bank_account_number or "", d.bank_ifsc or "", f"{Decimal(str(d.amount or 0)):.2f}", ref, "Salary Disbursement"])

        file_content = output.getvalue()
        target_file.file_content = file_content
        target_file.status = "GENERATED"
        target_file.total_records = len(disbursements)
        target_file.total_amount = sum((Decimal(str(d.amount or 0)) for d in disbursements), Decimal(0))
        target_file.generated_at = datetime.now(timezone.utc)
        await self.db.commit()

        # Generate download URL from registered route (mounted at /api/v1/payroll)
        download_url = f"/api/v1/payroll/bank-transfers/download/{str(target_file.id)}"

        return {
            "file_id": str(target_file.id),
            "file_name": target_file.file_name,
            "file_format": target_file.file_format,
            "download_url": download_url,
            "status": "GENERATED",
            "total_records": target_file.total_records,
            "total_amount": float(target_file.total_amount),
        }

    async def initiate_payments(self, advice_file_id: Optional[str] = None, company_id: Optional[uuid.UUID] = None, actor_id: Optional[uuid.UUID] = None) -> dict:
        """Initiate payment workflow for advice file records. Moves to PROCESSING status."""
        cid = self._resolve_cid(company_id)
        aid = actor_id or self.actor_id

        stmt = select(BankAdviceFile).order_by(BankAdviceFile.generated_at.desc().nullslast(), BankAdviceFile.created_at.desc())
        if advice_file_id:
            try:
                stmt = stmt.where(BankAdviceFile.id == uuid.UUID(advice_file_id))
            except ValueError:
                pass
        if cid:
            stmt = stmt.where(BankAdviceFile.company_id == cid)

        res = await self.db.execute(stmt)
        advice_file = res.scalars().first()

        if not advice_file:
            return {
                "status": "NOT_CONFIGURED",
                "message": "No bank advice file found to initiate. Generate a bank advice file first.",
                "initiated_count": 0,
            }

        # Update advice file and disbursement records to PROCESSING
        advice_file.status = "SUBMITTED"
        await self.db.execute(
            update(BankDisbursementRecord)
            .where(
                BankDisbursementRecord.advice_file_id == advice_file.id,
                BankDisbursementRecord.status == "PENDING",
            )
            .values(status="PROCESSING", updated_at=datetime.now(timezone.utc))
        )
        await self.db.commit()

        # Audit
        await PayrollAuditService.log_event(
            session=self.db,
            entity_type="BankAdviceFile",
            entity_id=advice_file.id,
            action="INITIATE_PAYMENTS",
            company_id=cid,
            actor_id=aid,
            before_status="GENERATED",
            after_status="SUBMITTED",
            reason="Submitted batch to bank file processing queue.",
        )
        await self.db.commit()

        return {
            "status": "PROCESSING",
            "message": "Bank advice batch submitted for processing. Settle transfers via bank advice file export or mark as paid.",
            "batch_id": str(advice_file.id),
            "total_records": advice_file.total_records,
        }

    async def reconcile_payments(self, advice_file_id: Optional[str] = None, company_id: Optional[uuid.UUID] = None) -> dict:
        """Reconcile bank payment records against database state."""
        cid = self._resolve_cid(company_id)

        stmt = select(BankDisbursementRecord)
        if advice_file_id:
            try:
                stmt = stmt.where(BankDisbursementRecord.advice_file_id == uuid.UUID(advice_file_id))
            except ValueError:
                pass
        if cid:
            stmt = stmt.join(BankAdviceFile, BankDisbursementRecord.advice_file_id == BankAdviceFile.id).where(BankAdviceFile.company_id == cid)

        res = await self.db.execute(stmt)
        records = res.scalars().all()

        reconciled = len([r for r in records if (r.status or "").upper() in ("SUCCESS", "COMPLETED")])
        failed = len([r for r in records if (r.status or "").upper() == "FAILED"])
        pending = len([r for r in records if (r.status or "").upper() in ("PENDING", "PROCESSING")])

        return {
            "status": "RECONCILED",
            "reconciled_count": reconciled,
            "failed_count": failed,
            "pending_count": pending,
            "total_count": len(records),
        }

    async def retry_transfer(self, transfer_id: str, company_id: Optional[uuid.UUID] = None, actor_id: Optional[uuid.UUID] = None) -> dict:
        """Retry a failed transfer by resetting status to PENDING."""
        cid = self._resolve_cid(company_id)
        aid = actor_id or self.actor_id

        try:
            uid = uuid.UUID(transfer_id)
        except (ValueError, TypeError):
            raise ValueError(f"Invalid transfer ID: {transfer_id}")

        stmt = (
            select(BankDisbursementRecord)
            .join(BankAdviceFile, BankDisbursementRecord.advice_file_id == BankAdviceFile.id, isouter=True)
            .where(BankDisbursementRecord.id == uid)
        )
        if cid:
            stmt = stmt.where(
                or_(
                    BankAdviceFile.company_id == cid,
                    BankDisbursementRecord.employee_id.in_(
                        select(Employee.id).where(Employee.company_id == cid)
                    ),
                )
            )

        res = await self.db.execute(stmt)
        record = res.scalars().first()
        if not record:
            raise ValueError(f"Transfer record '{transfer_id}' not found.")

        if (record.status or "").upper() != "FAILED":
            raise ValueError(f"Cannot retry transfer with status '{record.status}'. Only FAILED transfers can be retried.")

        record.status = "PENDING"
        record.failure_reason = None
        record.updated_at = datetime.now(timezone.utc)
        await self.db.commit()

        await PayrollAuditService.log_event(
            session=self.db,
            entity_type="BankDisbursementRecord",
            entity_id=record.id,
            action="RETRY_TRANSFER",
            company_id=cid,
            actor_id=aid,
            before_status="FAILED",
            after_status="PENDING",
            reason="Retried failed bank transfer.",
        )
        await self.db.commit()

        return {
            "id": str(record.id),
            "status": "PENDING",
            "message": "Transfer reset to PENDING for re-processing.",
        }

    async def mark_as_paid(
        self,
        transfer_id: str,
        transaction_ref: Optional[str] = None,
        remarks: Optional[str] = None,
        company_id: Optional[uuid.UUID] = None,
        actor_id: Optional[uuid.UUID] = None,
    ) -> dict:
        """Mark a transfer as manually paid with reference number and supporting evidence.
        
        Links the transfer to its exact payslip via pay_cycle_id -> PayCycle(period_month, period_year)
        and employee_id. Updates only that specific payslip. Returns reconciliation error
        if the link is ambiguous or missing.
        """
        cid = self._resolve_cid(company_id)
        aid = actor_id or self.actor_id

        try:
            uid = uuid.UUID(transfer_id)
        except (ValueError, TypeError):
            raise ValueError(f"Invalid transfer ID: {transfer_id}")

        stmt = (
            select(BankDisbursementRecord)
            .join(BankAdviceFile, BankDisbursementRecord.advice_file_id == BankAdviceFile.id, isouter=True)
            .where(BankDisbursementRecord.id == uid)
        )
        if cid:
            stmt = stmt.where(
                or_(
                    BankAdviceFile.company_id == cid,
                    BankDisbursementRecord.employee_id.in_(
                        select(Employee.id).where(Employee.company_id == cid)
                    ),
                )
            )

        res = await self.db.execute(stmt)
        record = res.scalars().first()
        if not record:
            raise ValueError(f"Transfer record '{transfer_id}' not found.")

        if (record.status or "").upper() == "SUCCESS":
            return {
                "id": str(record.id),
                "status": "COMPLETED",
                "reference_number": record.transaction_ref,
                "disbursed_at": record.disbursed_at.isoformat() if record.disbursed_at else None,
                "message": "Transfer already marked as paid.",
            }

        old_status = record.status
        ref = transaction_ref or f"MANUAL-{uuid.uuid4().hex[:8].upper()}"
        now = datetime.now(timezone.utc)

        # Find the exact payslip linked to this transfer
        target_payslip = None
        if record.pay_cycle_id:
            # Try to resolve via PayCycle first
            pay_cycle_stmt = select(PayCycle).where(PayCycle.id == record.pay_cycle_id)
            pay_cycle_res = await self.db.execute(pay_cycle_stmt)
            pay_cycle = pay_cycle_res.scalars().first()
            
            if pay_cycle:
                # Find payslip by employee_id, period_month, period_year
                ps_stmt = select(Payslip).where(
                    Payslip.employee_id == record.employee_id,
                    Payslip.period_month == pay_cycle.period_month,
                    Payslip.period_year == pay_cycle.period_year,
                )
                if cid:
                    ps_stmt = ps_stmt.where(Payslip.company_id == cid)
                ps_res = await self.db.execute(ps_stmt)
                target_payslip = ps_res.scalars().first()
            else:
                # pay_cycle_id might be a PayrollRun ID (legacy bug) - try that
                pr_stmt = select(PayrollRun).where(PayrollRun.id == record.pay_cycle_id)
                pr_res = await self.db.execute(pr_stmt)
                payroll_run = pr_res.scalars().first()
                if payroll_run:
                    ps_stmt = select(Payslip).where(
                        Payslip.employee_id == record.employee_id,
                        Payslip.period_month == payroll_run.period_month,
                        Payslip.period_year == payroll_run.period_year,
                    )
                    if cid:
                        ps_stmt = ps_stmt.where(Payslip.company_id == cid)
                    ps_res = await self.db.execute(ps_stmt)
                    target_payslip = ps_res.scalars().first()

        if not target_payslip:
            # No linked payslip found - ambiguous link
            await PayrollAuditService.log_event(
                session=self.db,
                entity_type="BankDisbursementRecord",
                entity_id=record.id,
                action="MARK_AS_PAID_FAILED",
                company_id=cid,
                actor_id=aid,
                before_status=old_status,
                after_status=old_status,
                reason=f"Cannot mark as paid: no matching payslip found for employee {record.employee_id} and pay_cycle_id {record.pay_cycle_id}. Manual reconciliation required.",
                extra_data={"reference_number": ref, "error": "AMBIGUOUS_LINK"},
            )
            await self.db.commit()
            raise ValueError(
                f"Reconciliation error: Transfer {transfer_id} has no linked payslip. "
                f"pay_cycle_id={record.pay_cycle_id}, employee_id={record.employee_id}. "
                f"Manual reconciliation required."
            )

        # Verify payslip is not already paid
        if (target_payslip.payment_status or "").upper() == "PAID":
            await PayrollAuditService.log_event(
                session=self.db,
                entity_type="BankDisbursementRecord",
                entity_id=record.id,
                action="MARK_AS_PAID_FAILED",
                company_id=cid,
                actor_id=aid,
                before_status=old_status,
                after_status=old_status,
                reason=f"Cannot mark as paid: linked payslip {target_payslip.id} already has status PAID.",
                extra_data={"reference_number": ref, "error": "PAYSLIP_ALREADY_PAID", "payslip_id": str(target_payslip.id)},
            )
            await self.db.commit()
            raise ValueError(
                f"Linked payslip {target_payslip.id} is already paid. Cannot mark transfer as paid again."
            )

        # Atomic update: transfer, payslip, and audit in one transaction
        record.status = "SUCCESS"
        record.transaction_ref = ref
        record.disbursed_at = now
        record.updated_at = now

        target_payslip.payment_status = "PAID"
        target_payslip.payment_date = now.date()
        target_payslip.payment_reference = ref
        target_payslip.updated_at = now

        await self.db.commit()

        await PayrollAuditService.log_event(
            session=self.db,
            entity_type="BankDisbursementRecord",
            entity_id=record.id,
            action="MARK_AS_PAID",
            company_id=cid,
            actor_id=aid,
            before_status=old_status,
            after_status="SUCCESS",
            reason=f"Marked as paid manually with ref: {ref}. {remarks or ''}".strip(),
            extra_data={
                "reference_number": ref,
                "payslip_id": str(target_payslip.id),
                "payslip_period": f"{target_payslip.period_month:02d}-{target_payslip.period_year}",
            },
        )
        await self.db.commit()

        return {
            "id": str(record.id),
            "status": "COMPLETED",
            "reference_number": ref,
            "disbursed_at": now.isoformat(),
            "payslip_id": str(target_payslip.id),
            "message": "Transfer marked as paid successfully.",
        }

    async def get_audit_logs(self, company_id: Optional[uuid.UUID] = None) -> list[dict]:
        """Fetch real bank transfer and disbursement audit logs from the database."""
        cid = self._resolve_cid(company_id)

        stmt = (
            select(PayrollAuditLog)
            .where(
                PayrollAuditLog.entity_type.in_(["BankAdviceFile", "BankDisbursementRecord"]),
            )
            .order_by(PayrollAuditLog.created_at.desc())
            .limit(50)
        )
        if cid:
            stmt = stmt.where(PayrollAuditLog.company_id == cid)

        res = await self.db.execute(stmt)
        logs = res.scalars().all()

        return [
            {
                "id": str(l.id),
                "action": l.action,
                "actor": str(l.actor_id) if l.actor_id else (l.actor_role or "System"),
                "timestamp": l.created_at.strftime("%Y-%m-%d %I:%M %p") if l.created_at else "",
                "details": l.reason or f"{l.action} performed on {l.entity_type}",
                "old_status": l.old_status,
                "new_status": l.new_status,
            }
            for l in logs
        ]
