"""Service for Accounting exports and Journal Voucher generation."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payroll import Payslip
from app.models.payroll_models import PayrollPeriod

logger = logging.getLogger(__name__)


class AccountingService:
    """Generates double-entry general ledger journal entries for payroll periods."""

    @classmethod
    async def export_accounting_entries(
        cls,
        session: AsyncSession,
        period_id: uuid.UUID,
        company_id: Optional[uuid.UUID] = None,
    ) -> dict[str, Any]:
        p_stmt = select(PayrollPeriod).where(PayrollPeriod.id == period_id)
        period = (await session.execute(p_stmt)).scalar_one_or_none()
        if not period:
            raise HTTPException(status_code=404, detail="Payroll period not found.")

        ps_stmt = select(Payslip).where(
            Payslip.period_month == period.period_month,
            Payslip.period_year == period.period_year,
        )
        if company_id:
            ps_stmt = ps_stmt.where(Payslip.company_id == company_id)
        payslips = (await session.execute(ps_stmt)).scalars().all()

        total_gross = sum(float(ps.gross_earnings) for ps in payslips)
        total_net = sum(float(ps.net_pay) for ps in payslips)
        total_pf_emp = sum(float(ps.employee_pf) for ps in payslips)
        total_pf_empr = sum(float(ps.employer_pf) for ps in payslips)
        total_esi_emp = sum(float(ps.employee_esi) for ps in payslips)
        total_esi_empr = sum(float(ps.employer_esi) for ps in payslips)
        total_pt = sum(float(ps.professional_tax) for ps in payslips)
        total_tds = sum(float(ps.tds) for ps in payslips)

        journal_entries = [
            # Debits (Expenses)
            {"account_code": "5001", "account_name": "Salaries & Wages Expense", "debit": round(total_gross, 2), "credit": 0.0},
            {"account_code": "5002", "account_name": "Employer PF Contribution", "debit": round(total_pf_empr, 2), "credit": 0.0},
            {"account_code": "5003", "account_name": "Employer ESI Contribution", "debit": round(total_esi_empr, 2), "credit": 0.0},
            # Credits (Liabilities)
            {"account_code": "2001", "account_name": "Net Salaries Payable", "debit": 0.0, "credit": round(total_net, 2)},
            {"account_code": "2002", "account_name": "PF Payable (Employee + Employer)", "debit": 0.0, "credit": round(total_pf_emp + total_pf_empr, 2)},
            {"account_code": "2003", "account_name": "ESI Payable (Employee + Employer)", "debit": 0.0, "credit": round(total_esi_emp + total_esi_empr, 2)},
            {"account_code": "2004", "account_name": "Professional Tax Payable", "debit": 0.0, "credit": round(total_pt, 2)},
            {"account_code": "2005", "account_name": "TDS on Salaries Payable", "debit": 0.0, "credit": round(total_tds, 2)},
        ]

        total_debits = sum(e["debit"] for e in journal_entries)
        total_credits = sum(e["credit"] for e in journal_entries)

        return {
            "period_id": str(period_id),
            "period_name": period.name,
            "period_month": period.period_month,
            "period_year": period.period_year,
            "currency": "INR",
            "is_balanced": abs(total_debits - total_credits) < 1.0,
            "total_debits": round(total_debits, 2),
            "total_credits": round(total_credits, 2),
            "entries": journal_entries,
        }


class EnterpriseAccountingService:
    """Tenant-scoped, exact-paise ERP journals and reconciliation."""

    DEFAULT_ACCOUNTS = {
        "SALARIES_EXPENSE": ("5001", "Salaries & Wages Expense", "EXPENSE"),
        "EMPLOYER_PF_EXPENSE": ("5002", "Employer PF Contribution", "EXPENSE"),
        "EMPLOYER_ESI_EXPENSE": ("5003", "Employer ESI Contribution", "EXPENSE"),
        "NET_SALARIES_PAYABLE": ("2001", "Net Salaries Payable", "LIABILITY"),
        "PF_PAYABLE": ("2002", "PF Payable", "LIABILITY"),
        "ESI_PAYABLE": ("2003", "ESI Payable", "LIABILITY"),
        "PT_PAYABLE": ("2004", "Professional Tax Payable", "LIABILITY"),
        "TDS_PAYABLE": ("2005", "TDS on Salaries Payable", "LIABILITY"),
        "OTHER_DEDUCTIONS_PAYABLE": ("2006", "Other Payroll Deductions Payable", "LIABILITY"),
        "EMPLOYEE_EXPENSE": ("5100", "Employee Expense", "EXPENSE"),
        "EXPENSE_PAYABLE": ("2100", "Expense Reimbursement Payable", "LIABILITY"),
    }

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def _paise(value) -> int:
        from decimal import Decimal, ROUND_HALF_UP
        return int((Decimal(str(value or 0)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    async def upsert_mapping(
        self, *, company_id: uuid.UUID, provider: str, source_key: str,
        account_code: str, account_name: str, account_type: str,
    ):
        from app.models.accounting import GLAccountMapping
        provider, source_key = provider.upper(), source_key.upper()
        if provider not in {"TALLY", "ZOHO", "GENERIC"} or source_key not in self.DEFAULT_ACCOUNTS:
            raise ValueError("Unsupported accounting provider or source account key.")
        mapping = (await self.session.execute(select(GLAccountMapping).where(
            GLAccountMapping.company_id == company_id, GLAccountMapping.provider == provider,
            GLAccountMapping.source_key == source_key,
        ))).scalar_one_or_none()
        mapping = mapping or GLAccountMapping(id=uuid.uuid4(), company_id=company_id, provider=provider, source_key=source_key)
        mapping.account_code = account_code.strip()
        mapping.account_name = account_name.strip()
        mapping.account_type = account_type.upper()
        mapping.is_active = True
        self.session.add(mapping)
        await self.session.commit()
        return mapping

    async def _mappings(self, company_id: uuid.UUID, provider: str) -> dict:
        from app.models.accounting import GLAccountMapping
        rows = (await self.session.execute(select(GLAccountMapping).where(
            GLAccountMapping.company_id == company_id, GLAccountMapping.provider == provider,
            GLAccountMapping.is_active.is_(True),
        ))).scalars().all()
        return {row.source_key: row for row in rows}

    async def build_journal(self, *, company_id: uuid.UUID, period_id: uuid.UUID, provider: str = "GENERIC") -> dict[str, Any]:
        from app.models.accounting import GLAccountMapping
        from app.models.payroll import PayrollRun
        provider = provider.upper()
        period = (await self.session.execute(select(PayrollPeriod).where(
            PayrollPeriod.id == period_id, PayrollPeriod.company_id == company_id,
        ))).scalar_one_or_none()
        if period is None:
            raise LookupError("Payroll period not found in this tenant.")
        stmt = select(Payslip).join(PayrollRun, PayrollRun.id == Payslip.payroll_run_id).where(
            Payslip.company_id == company_id, Payslip.period_month == period.period_month,
            Payslip.period_year == period.period_year, PayrollRun.company_id == company_id,
        )
        if period.legal_entity_id is not None:
            stmt = stmt.where(PayrollRun.legal_entity_id == period.legal_entity_id)
        payslips = (await self.session.execute(stmt)).scalars().all()
        totals = {key: sum((self._paise(getattr(payslip, field)) for payslip in payslips), 0) for key, field in {
            "gross": "gross_earnings", "net": "net_pay", "employee_pf": "employee_pf",
            "employer_pf": "employer_pf", "employee_esi": "employee_esi", "employer_esi": "employer_esi",
            "pt": "professional_tax", "tds": "tds", "deductions": "total_deductions",
        }.items()}
        other_deductions = totals["deductions"] - totals["employee_pf"] - totals["employee_esi"] - totals["pt"] - totals["tds"]
        if other_deductions < 0:
            raise ValueError("Payslip deduction breakup exceeds total deductions.")
        raw_entries = [
            ("SALARIES_EXPENSE", totals["gross"], 0),
            ("EMPLOYER_PF_EXPENSE", totals["employer_pf"], 0),
            ("EMPLOYER_ESI_EXPENSE", totals["employer_esi"], 0),
            ("NET_SALARIES_PAYABLE", 0, totals["net"]),
            ("PF_PAYABLE", 0, totals["employee_pf"] + totals["employer_pf"]),
            ("ESI_PAYABLE", 0, totals["employee_esi"] + totals["employer_esi"]),
            ("PT_PAYABLE", 0, totals["pt"]), ("TDS_PAYABLE", 0, totals["tds"]),
            ("OTHER_DEDUCTIONS_PAYABLE", 0, other_deductions),
        ]
        mappings = await self._mappings(company_id, provider)
        entries = []
        for source_key, debit, credit in raw_entries:
            if debit == 0 and credit == 0:
                continue
            mapping = mappings.get(source_key)
            code, name, account_type = (
                (mapping.account_code, mapping.account_name, mapping.account_type)
                if mapping else self.DEFAULT_ACCOUNTS[source_key]
            )
            entries.append({
                "source_key": source_key, "account_code": code, "account_name": name,
                "account_type": account_type, "debit_paise": debit, "credit_paise": credit,
            })
        debit_total = sum(entry["debit_paise"] for entry in entries)
        credit_total = sum(entry["credit_paise"] for entry in entries)
        if debit_total != credit_total:
            raise ValueError("Payroll journal is not balanced; verify payslip net pay and deductions.")
        return {
            "period_id": str(period.id), "period_name": period.name, "provider": provider,
            "currency": "INR", "payslip_count": len(payslips), "entries": entries,
            "total_debit_paise": debit_total, "total_credit_paise": credit_total, "is_balanced": True,
        }

    async def export_journal(self, *, company_id: uuid.UUID, period_id: uuid.UUID, export_format: str) -> dict[str, Any]:
        import csv
        import io
        import xml.etree.ElementTree as ET
        export_format = export_format.upper()
        provider = "TALLY" if export_format.startswith("TALLY") else "ZOHO" if export_format.startswith("ZOHO") else "GENERIC"
        journal = await self.build_journal(company_id=company_id, period_id=period_id, provider=provider)
        if export_format == "TALLY_XML":
            envelope = ET.Element("ENVELOPE")
            header = ET.SubElement(envelope, "HEADER")
            ET.SubElement(header, "TALLYREQUEST").text = "Import Data"
            body = ET.SubElement(envelope, "BODY")
            data = ET.SubElement(ET.SubElement(body, "IMPORTDATA"), "REQUESTDATA")
            message = ET.SubElement(data, "TALLYMESSAGE")
            voucher = ET.SubElement(message, "VOUCHER", {"VCHTYPE": "Journal", "ACTION": "Create"})
            ET.SubElement(voucher, "DATE").text = journal["period_id"] and (await self.session.get(PayrollPeriod, period_id)).pay_date.strftime("%Y%m%d")
            ET.SubElement(voucher, "VOUCHERTYPENAME").text = "Journal"
            ET.SubElement(voucher, "NARRATION").text = f"Payroll {journal['period_name']}"
            for entry in journal["entries"]:
                line = ET.SubElement(voucher, "ALLLEDGERENTRIES.LIST")
                ET.SubElement(line, "LEDGERNAME").text = entry["account_name"]
                ET.SubElement(line, "ISDEEMEDPOSITIVE").text = "Yes" if entry["debit_paise"] else "No"
                amount = entry["debit_paise"] if entry["debit_paise"] else -entry["credit_paise"]
                ET.SubElement(line, "AMOUNT").text = f"{amount / 100:.2f}"
            content = ET.tostring(envelope, encoding="unicode")
            media_type, extension = "application/xml", "xml"
        elif export_format in {"TALLY_CSV", "ZOHO_CSV"}:
            output = io.StringIO()
            writer = csv.writer(output, lineterminator="\n")
            writer.writerow(["Period", "Account Code", "Account Name", "Debit", "Credit", "Currency"])
            for entry in journal["entries"]:
                writer.writerow([journal["period_name"], entry["account_code"], entry["account_name"],
                                 f"{entry['debit_paise'] / 100:.2f}", f"{entry['credit_paise'] / 100:.2f}", "INR"])
            content, media_type, extension = output.getvalue(), "text/csv", "csv"
        elif export_format == "ZOHO_JSON":
            import json
            content = json.dumps({
                "journal_entries": [{
                    "journal_date": (await self.session.get(PayrollPeriod, period_id)).pay_date.isoformat(),
                    "reference_number": f"PAYROLL-{period_id}", "notes": f"Payroll {journal['period_name']}",
                    "line_items": [{
                        "account_code": entry["account_code"], "description": entry["account_name"],
                        "debit": f"{entry['debit_paise'] / 100:.2f}", "credit": f"{entry['credit_paise'] / 100:.2f}",
                    } for entry in journal["entries"]],
                }], "currency_code": "INR",
            }, separators=(",", ":"))
            media_type, extension = "application/json", "json"
        else:
            raise ValueError("Export format must be TALLY_XML, TALLY_CSV, ZOHO_JSON, or ZOHO_CSV.")
        return {"content": content, "media_type": media_type, "file_name": f"payroll-{period_id}.{extension}", "journal": journal}

    async def post_expense(
        self, *, company_id: uuid.UUID, expense_date, category: str, amount_paise: int,
        description: str, idempotency_key: str, employee_id: uuid.UUID | None = None,
        external_reference: str | None = None,
    ):
        from app.models.accounting import ExpensePosting
        from app.models.employee import Employee
        existing = (await self.session.execute(select(ExpensePosting).where(
            ExpensePosting.company_id == company_id, ExpensePosting.idempotency_key == idempotency_key,
        ))).scalar_one_or_none()
        if existing:
            if (
                existing.amount_paise != int(amount_paise)
                or existing.category != category.strip().upper()
                or existing.employee_id != employee_id
            ):
                raise ValueError("Expense idempotency key was reused for a different payload.")
            return existing
        if amount_paise <= 0 or not description.strip() or not idempotency_key.strip():
            raise ValueError("Expense amount, description, and idempotency key are required.")
        if employee_id:
            employee = (await self.session.execute(select(Employee).where(
                Employee.id == employee_id, Employee.company_id == company_id, Employee.is_deleted.is_(False),
            ))).scalar_one_or_none()
            if employee is None:
                raise LookupError("Expense employee not found in this tenant.")
        expense = ExpensePosting(
            id=uuid.uuid4(), company_id=company_id, employee_id=employee_id, expense_date=expense_date,
            category=category.strip().upper(), amount_paise=int(amount_paise), description=description.strip(),
            idempotency_key=idempotency_key.strip(), external_reference=external_reference,
        )
        self.session.add(expense)
        await self.session.commit()
        return expense

    async def reconcile_gl(
        self, *, company_id: uuid.UUID, period_id: uuid.UUID,
        provider: str, external_entries: list[dict],
    ):
        from app.models.accounting import GLReconciliationReport
        journal = await self.build_journal(company_id=company_id, period_id=period_id, provider=provider)
        external_total = sum(int(entry.get("debit_paise", 0)) for entry in external_entries)
        external_credits = sum(int(entry.get("credit_paise", 0)) for entry in external_entries)
        internal_by_account = {
            entry["account_code"]: entry["debit_paise"] - entry["credit_paise"] for entry in journal["entries"]
        }
        external_by_account: dict[str, int] = {}
        for entry in external_entries:
            code = str(entry.get("account_code") or "")
            external_by_account[code] = external_by_account.get(code, 0) + int(entry.get("debit_paise", 0)) - int(entry.get("credit_paise", 0))
        account_differences = [{
            "account_code": code, "internal_net_paise": internal_by_account.get(code, 0),
            "external_net_paise": external_by_account.get(code, 0),
            "difference_paise": internal_by_account.get(code, 0) - external_by_account.get(code, 0),
        } for code in sorted(set(internal_by_account) | set(external_by_account))
        if internal_by_account.get(code, 0) != external_by_account.get(code, 0)]
        difference = journal["total_debit_paise"] - external_total
        balanced_external = external_total == external_credits
        status_value = "MATCHED" if difference == 0 and not account_differences and balanced_external else "MISMATCH"
        report = GLReconciliationReport(
            id=uuid.uuid4(), company_id=company_id, period_id=period_id, provider=provider.upper(),
            internal_total_paise=journal["total_debit_paise"], external_total_paise=external_total,
            difference_paise=difference, status=status_value,
            report_json={"account_differences": account_differences, "external_is_balanced": balanced_external},
        )
        self.session.add(report)
        await self.session.commit()
        return report
