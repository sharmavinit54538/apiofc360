"""Clearance-guarded FnF finalization, settlement PDFs and exit letters."""
from __future__ import annotations

import hashlib
import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset
from app.models.employee import Employee
from app.models.employee_document import EmployeeDocument
from app.models.exit import AssetReturn, ClearanceRequest, EmployeeExit, ExitDocument, FnfSettlement
from app.models.payroll_models import FullAndFinalSettlement
from app.services.fnf_calculation_service import FnfCalculationService
from app.services.letter_service import LetterService

CLEARANCE_FIELDS = (
    "it_clearance", "hr_clearance", "finance_clearance",
    "admin_clearance", "manager_clearance", "security_clearance",
)


class FnFWorkflowService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.letters = LetterService(session)

    async def _exit(self, exit_id: uuid.UUID) -> EmployeeExit:
        exit_obj = await self.session.get(EmployeeExit, exit_id)
        if exit_obj is None or exit_obj.is_deleted:
            raise ValueError("Exit request not found.")
        return exit_obj

    async def clearance_status(self, exit_id: uuid.UUID) -> dict[str, Any]:
        exit_obj = await self._exit(exit_id)
        returns = (await self.session.execute(select(AssetReturn).where(
            AssetReturn.exit_id == exit_id
        ))).scalars().all()
        outstanding_assets = (await self.session.execute(select(Asset).where(
            Asset.employee_id == exit_obj.employee_id
        ))).scalars().all()
        returned = sum(1 for item in returns if item.return_status in {"RETURNED", "NOT_APPLICABLE"})
        if outstanding_assets:
            asset_percentage = 0.0
        elif returns:
            asset_percentage = round(returned * 100 / len(returns), 2)
        else:
            asset_percentage = 100.0
        clearance = (await self.session.execute(select(ClearanceRequest).where(
            ClearanceRequest.exit_id == exit_id
        ))).scalars().first()
        completed_departments = sum(1 for field in CLEARANCE_FIELDS if clearance and getattr(clearance, field))
        department_percentage = round(completed_departments * 100 / len(CLEARANCE_FIELDS), 2)
        return {
            "exit_id": str(exit_id), "asset_clearance_percentage": asset_percentage,
            "department_clearance_percentage": department_percentage,
            "asset_returns_completed": returned, "asset_returns_total": len(returns),
            "outstanding_asset_ids": [str(asset.id) for asset in outstanding_assets],
            "departments_completed": completed_departments, "departments_total": len(CLEARANCE_FIELDS),
            "clearance_complete": asset_percentage == 100.0 and department_percentage == 100.0,
        }

    async def assert_clearances(self, exit_id: uuid.UUID) -> dict[str, Any]:
        status = await self.clearance_status(exit_id)
        if not status["clearance_complete"]:
            raise ValueError(
                "FnF requires 100% asset and department clearance: "
                f"assets={status['asset_clearance_percentage']}%, departments={status['department_clearance_percentage']}%."
            )
        return status

    async def finalize_exit_fnf(self, exit_id: uuid.UUID, *, actor_id: uuid.UUID) -> FnfSettlement:
        """Finalize the legacy exit FnF only after both clearances are complete."""
        exit_obj = await self._exit(exit_id)
        clearance = await self.assert_clearances(exit_id)
        preview = await FnfCalculationService(self.session).calculate_fnf_preview(exit_id)
        fnf = (await self.session.execute(select(FnfSettlement).where(
            FnfSettlement.exit_id == exit_id
        ))).scalars().first()
        if fnf is None:
            fnf = FnfSettlement(exit_id=exit_id)
            self.session.add(fnf)
        for field in (
            "last_salary", "pending_salary", "leave_encashment", "gratuity", "bonus",
            "incentives", "recoveries", "notice_recovery", "asset_recovery", "loan_recovery",
            "other_deductions", "net_payable_amount",
        ):
            setattr(fnf, field, Decimal(str(preview[field])))
        fnf.settlement_breakup = {**preview, "clearance": clearance}
        fnf.status = "FINALIZED"
        exit_obj.fnf_status = "FINALIZED"
        exit_obj.notice_period_days_required = preview["required_notice_days"]
        exit_obj.notice_period_days_served = preview["actual_notice_days"]
        exit_obj.notice_shortfall_days = preview["notice_shortfall_days"]
        exit_obj.notice_waived = preview["notice_waived"]
        exit_obj.notice_buyout = preview["notice_buyout"]
        await self.session.commit()
        return fnf

    async def _generate_settlement_sheet(
        self, *, exit_obj: EmployeeExit, employee: Employee, actor_id: uuid.UUID,
        breakup: dict[str, Any], settlement_id: uuid.UUID,
    ) -> EmployeeDocument:
        lines = [
            "FULL AND FINAL SETTLEMENT SHEET", f"Settlement ID: {settlement_id}",
            f"Employee: {employee.first_name} {employee.last_name} ({employee.employee_id})",
            f"Last working date: {exit_obj.last_working_date.isoformat()}", "",
        ]
        for key in (
            "pending_salary", "arrears", "leave_encashment", "gratuity", "bonus", "incentives",
            "notice_recovery", "loan_recovery", "asset_recovery", "other_deductions", "net_payable_amount",
        ):
            value = breakup.get(key, 0)
            if key == "net_payable_amount" and "net_payable_paise" in breakup:
                value = Decimal(str(breakup["net_payable_paise"])) / Decimal("100")
            lines.append(f"{key.replace('_', ' ').title()}: INR {value}")
        lines.extend(["", "Clearance: 100% assets and all departments", f"Generated at: {datetime.now(timezone.utc).isoformat()}"])
        pdf = self.letters.render_pdf("Full and Final Settlement Sheet", "\n".join(lines))
        doc = await self.letters.save_employee_pdf(
            employee=employee, title="Full and Final Settlement Sheet", document_type="FNF_SETTLEMENT_SHEET",
            pdf_bytes=pdf, actor_id=actor_id, description=f"Settlement sheet for exit {exit_obj.id}", commit=False,
        )
        doc.document_hash = hashlib.sha256(pdf).hexdigest()
        return doc

    async def _generate_exit_letters(
        self, exit_obj: EmployeeExit, employee: Employee, actor_id: uuid.UUID,
        created_paths: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        generated: list[dict[str, Any]] = []
        for letter_type in ("RELIEVING", "EXPERIENCE"):
            document_type = f"{letter_type}_LETTER"
            existing = (await self.session.execute(select(EmployeeDocument).where(
                EmployeeDocument.employee_id == employee.id,
                EmployeeDocument.document_type == document_type,
                EmployeeDocument.is_deleted == False,  # noqa: E712
            ))).scalars().first()
            if existing is not None:
                generated.append({"document_type": document_type, "document_id": str(existing.id), "file_path": existing.file_path})
            else:
                result = await self.letters.generate_letter(
                    letter_type, employee.id, company_id=employee.company_id,
                    fields={"last_working_day": exit_obj.last_working_date.isoformat()},
                    actor_id=actor_id, save=True, commit=False,
                )
                existing = await self.session.get(EmployeeDocument, uuid.UUID(result["document_id"]))
                if created_paths is not None:
                    created_paths.append(existing.file_path)
                generated.append({"document_type": document_type, "document_id": result["document_id"], "file_path": existing.file_path})
            exit_doc = (await self.session.execute(select(ExitDocument).where(
                ExitDocument.exit_id == exit_obj.id, ExitDocument.document_type == document_type,
            ))).scalars().first()
            if exit_doc is None:
                self.session.add(ExitDocument(exit_id=exit_obj.id, document_type=document_type, file_path=existing.file_path))
        await self.session.flush()
        return generated

    async def settle_exit_fnf(self, exit_id: uuid.UUID, *, actor_id: uuid.UUID) -> FnfSettlement:
        exit_obj = await self._exit(exit_id)
        fnf = (await self.session.execute(select(FnfSettlement).where(
            FnfSettlement.exit_id == exit_id
        ))).scalars().first()
        if fnf is None:
            raise ValueError("FnF settlement not found; calculate and finalize it first.")
        if fnf.status != "SETTLED":
            if fnf.status != "FINALIZED":
                raise ValueError("FnF must be FINALIZED before it can be SETTLED.")
            if fnf.payment_status != "PAID":
                raise ValueError("FnF payment must be marked PAID before settlement.")
            await self.assert_clearances(exit_id)
        employee = await self.session.get(Employee, exit_obj.employee_id)
        created_paths: list[str] = []
        try:
            if not fnf.statement_path:
                sheet = await self._generate_settlement_sheet(
                    exit_obj=exit_obj, employee=employee, actor_id=actor_id,
                    breakup=fnf.settlement_breakup or {}, settlement_id=fnf.id,
                )
                fnf.statement_path, fnf.statement_hash = sheet.file_path, sheet.document_hash
                created_paths.append(sheet.file_path)
            fnf.generated_letters_json = await self._generate_exit_letters(
                exit_obj, employee, actor_id, created_paths=created_paths,
            )
            fnf.status = "SETTLED"
            fnf.settled_at = datetime.now(timezone.utc)
            exit_obj.fnf_status = "SETTLED"
            exit_obj.status = "SETTLED"
            employee.status = "EXITED"
            employee.is_active = False
            await self.session.commit()
            return fnf
        except Exception:
            await self.session.rollback()
            for path in set(created_paths):
                try:
                    os.remove(path)
                except OSError:
                    pass
            raise

    async def settle_payroll_fnf(
        self, fnf_id: uuid.UUID, *, actor_id: uuid.UUID, actor_role: str | None = None,
    ) -> FullAndFinalSettlement:
        """Move a payroll FnF from FINALIZED to SETTLED without changing legacy finalize."""
        settlement = await self.session.get(FullAndFinalSettlement, fnf_id)
        if settlement is None:
            raise ValueError("Payroll FnF settlement not found.")
        if settlement.status != "SETTLED" and settlement.status != "FINALIZED":
            raise ValueError("Payroll FnF must be FINALIZED before it can be SETTLED.")
        exit_obj = await self.session.get(EmployeeExit, settlement.exit_id) if settlement.exit_id else None
        if exit_obj is None:
            exit_obj = (await self.session.execute(select(EmployeeExit).where(
                EmployeeExit.employee_id == settlement.employee_id, EmployeeExit.is_deleted == False,  # noqa: E712
            ).order_by(EmployeeExit.created_at.desc()))).scalars().first()
        if exit_obj is None:
            raise ValueError("A linked exit with asset/department clearance is required.")
        if settlement.status != "SETTLED":
            await self.assert_clearances(exit_obj.id)
        employee = await self.session.get(Employee, settlement.employee_id)
        created_paths: list[str] = []
        try:
            if not settlement.statement_path:
                breakup = dict(settlement.settlement_breakup or {})
                breakup["net_payable_paise"] = settlement.net_payable_paise
                sheet = await self._generate_settlement_sheet(
                    exit_obj=exit_obj, employee=employee, actor_id=actor_id,
                    breakup=breakup, settlement_id=settlement.id,
                )
                settlement.statement_path = sheet.file_path
                settlement.settlement_sheet_hash = sheet.document_hash
                created_paths.append(sheet.file_path)
            settlement.generated_letters_json = await self._generate_exit_letters(
                exit_obj, employee, actor_id, created_paths=created_paths,
            )
            old_status = settlement.status
            settlement.status = "SETTLED"
            settlement.settled_at = datetime.now(timezone.utc)
            settlement.exit_id = exit_obj.id
            exit_obj.status = "SETTLED"
            exit_obj.fnf_status = "SETTLED"
            employee.status = "EXITED"
            employee.is_active = False
            from app.services.payroll.audit_service import PayrollAuditService
            await PayrollAuditService.log_event(
                session=self.session, entity_type="FullAndFinalSettlement", entity_id=settlement.id,
                action="SETTLE", company_id=settlement.company_id, actor_id=actor_id, actor_role=actor_role,
                before_status=old_status, after_status="SETTLED", reason="Settlement paid; clearances complete and exit letters generated",
            )
            await self.session.commit()
            return settlement
        except Exception:
            await self.session.rollback()
            for path in set(created_paths):
                try:
                    os.remove(path)
                except OSError:
                    pass
            raise


__all__ = ["FnFWorkflowService", "CLEARANCE_FIELDS"]
