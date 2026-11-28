"""Enterprise Payslip Generation, Snapshot Preservation, Verification, and Delivery Service."""
from __future__ import annotations

import asyncio
import calendar
import hashlib
import hmac
import io
import logging
import os
import re
import secrets
import time
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, List, Optional

from fastapi import HTTPException, status
from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings as app_settings
from app.models.calendar.holiday import HolidayCalendar
from app.models.company import Company, LegalEntity
from app.models.employee import Employee
from app.models.employee_bank_account import EmployeeBankAccount
from app.models.leave import LeaveRequest
from app.models.payroll import (
    AdvanceLoan,
    OvertimeEntry,
    PayrollAttendanceInput,
    PayrollRun,
    Payslip,
    PayslipDocument,
    SalaryStructure,
    StatutoryComplianceConfig,
)
from app.models.payroll_models import (
    EmployeeYTDSalary,
    PaymentBatch,
    PaymentBatchItem,
    PayrollPeriod,
    PayrollRunEmployee,
    ProvisionSlip,
    VariableInput,
)
from app.services.email_service import send_email
from app.services.payroll.audit_service import PayrollAuditService
from app.services.payroll.payslip_formatter import (
    amount_in_words,
    build_payslip_filename,
    format_currency,
    mask_account_number,
    mask_pan,
    mask_pf_number,
    mask_uan,
    paise_to_decimal,
    quantize_money,
    sanitize_filename_part,
    to_decimal,
    to_paise_int,
)
from app.services.payroll.payslip_pdf_renderer import (
    render_compat_summary_pdf,
    render_enterprise_payslip_pdf,
    validate_financial_reconciliation,
)
from app.services.payroll.payslip_settings_service import PayslipSettingsService
from app.services.whatsapp_service import send_whatsapp_message

logger = logging.getLogger(__name__)

_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
_CONFIGURED_PAYSLIP_DIR = str(
    getattr(app_settings, "PAYSLIP_STORAGE_DIR", os.path.join("storage", "payslips"))
    or os.path.join("storage", "payslips")
)

# Stored outside public static /uploads to prevent unauthenticated access
PAYSLIP_STORAGE_ROOT = (
    os.path.abspath(_CONFIGURED_PAYSLIP_DIR)
    if os.path.isabs(_CONFIGURED_PAYSLIP_DIR)
    else os.path.abspath(os.path.join(_PROJECT_ROOT, _CONFIGURED_PAYSLIP_DIR))
)

FINALIZED_RUN_STATUSES = frozenset({"APPROVED", "FINALIZED", "LOCKED", "PAID", "COMPLETED"})

_VARIABLE_EARNING_LABELS = {
    "OVERTIME": "Overtime Payment",
    "STATUTORY_BONUS": "Bonus / Performance Award",
    "BONUS": "Bonus",
    "ONE_TIME_BONUS": "One-Time Bonus",
    "INCENTIVE": "Performance Incentive",
    "COMMISSION": "Commission",
    "REIMBURSEMENT": "Reimbursement (Cycle Payout)",
    "SHIFT_ALLOWANCE": "Shift Allowance",
    "COMP_OFF_ENCASHMENT": "Comp-Off Encashment",
    "LTA": "Leave Travel Allowance (LTA)",
    "TRAVEL": "Travel Allowance",
    "MEDICAL": "Medical Allowance",
    "FOOD": "Food Allowance",
    "COMMUNICATION": "Communication Allowance",
    "OTHER": "Other Earnings",
}


class PayslipService:
    """Enterprise business logic for Payslips, Versioned PDFs, Snapshots, and Verification."""

    # ── Storage Safety Helpers ────────────────────────────────────────────────

    @classmethod
    def _ensure_safe_storage_path(cls, rel_or_abs: str) -> str:
        os.makedirs(PAYSLIP_STORAGE_ROOT, exist_ok=True)
        abs_root = os.path.realpath(PAYSLIP_STORAGE_ROOT)
        if not rel_or_abs or ".." in str(rel_or_abs).replace("\\", "/").split("/"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid payslip storage path.",
            )
        candidate = (
            os.path.abspath(rel_or_abs)
            if os.path.isabs(rel_or_abs)
            else os.path.abspath(os.path.join(abs_root, rel_or_abs))
        )
        # Resolve existing parent chain first so uncreated leaf directories cannot trigger OS-specific path drift
        probe = candidate
        while not os.path.exists(probe):
            parent = os.path.dirname(probe)
            if parent == probe:
                break
            probe = parent
        resolved_probe = os.path.realpath(probe)
        try:
            norm_root = os.path.normcase(abs_root)
            is_inside = os.path.commonpath([norm_root, os.path.normcase(candidate)]) == norm_root
            probe_inside = os.path.commonpath([norm_root, os.path.normcase(resolved_probe)]) == norm_root
        except ValueError:
            is_inside = False
            probe_inside = False
        if not (is_inside and probe_inside):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid payslip storage path.",
            )
        return candidate

    @classmethod
    def _read_stored_pdf_bytes(cls, file_path: str | None) -> Optional[bytes]:
        if not file_path:
            return None
        try:
            safe_path = cls._ensure_safe_storage_path(file_path)
        except HTTPException:
            return None
        if not os.path.isfile(safe_path):
            return None
        with open(safe_path, "rb") as fh:
            data = fh.read()
        return data if data.startswith(b"%PDF") else None

    @classmethod
    def _write_pdf_bytes_sync(cls, rel_path: str, pdf_bytes: bytes) -> tuple[str, int, str]:
        os.makedirs(PAYSLIP_STORAGE_ROOT, exist_ok=True)
        safe_path = cls._ensure_safe_storage_path(rel_path)
        os.makedirs(os.path.dirname(safe_path), exist_ok=True)
        with open(safe_path, "wb") as fh:
            fh.write(pdf_bytes)
        sha256_hex = hashlib.sha256(pdf_bytes).hexdigest()
        return rel_path, len(pdf_bytes), sha256_hex

    # ── Signed Expiring Download Token Helpers ────────────────────────────────

    @staticmethod
    def _signing_secret() -> bytes:
        secret = getattr(app_settings, "SECRET_KEY", None)
        if hasattr(secret, "get_secret_value"):
            secret = secret.get_secret_value()
        return str(secret or "ofc360-payslip-signing").encode("utf-8")

    @classmethod
    def create_signed_download_token(
        cls,
        *,
        payslip_id: uuid.UUID,
        company_id: uuid.UUID | None,
        ttl_seconds: int = 300,
    ) -> dict[str, Any]:
        exp = int(time.time()) + max(30, min(3600, int(ttl_seconds)))
        msg = f"{payslip_id}:{company_id or ''}:{exp}".encode("utf-8")
        sig = hmac.new(cls._signing_secret(), msg, hashlib.sha256).hexdigest()
        return {
            "token": f"{exp}.{sig}",
            "expires_at": datetime.fromtimestamp(exp, tz=timezone.utc).isoformat(),
            "expires_in_seconds": exp - int(time.time()),
        }

    @classmethod
    def verify_signed_download_token(
        cls,
        *,
        payslip_id: uuid.UUID,
        company_id: uuid.UUID | None,
        token: str,
    ) -> bool:
        try:
            exp_str, sig = str(token).split(".", 1)
            exp = int(exp_str)
        except Exception:
            return False
        if exp < int(time.time()):
            return False
        msg = f"{payslip_id}:{company_id or ''}:{exp}".encode("utf-8")
        expected = hmac.new(cls._signing_secret(), msg, hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, expected)

    # ── Backward-Compatible Query APIs ────────────────────────────────────────

    @classmethod
    async def get_employee_payslips(
        cls, session: AsyncSession, employee_id: uuid.UUID, page: int = 1, limit: int = 20
    ) -> dict[str, Any]:
        stmt = select(Payslip).where(Payslip.employee_id == employee_id)
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await session.execute(count_stmt)).scalar() or 0

        offset = max(0, (page - 1) * limit)
        stmt = stmt.order_by(desc(Payslip.period_year), desc(Payslip.period_month)).offset(offset).limit(limit)
        items = (await session.execute(stmt)).scalars().all()

        return {"items": items, "total": total, "page": page, "limit": limit}

    @classmethod
    async def get_payslip_detail(
        cls,
        session: AsyncSession,
        run_id: uuid.UUID,
        employee_id: uuid.UUID,
        company_id: Optional[uuid.UUID] = None,
    ) -> dict[str, Any]:
        stmt = select(Payslip).where(
            Payslip.payroll_run_id == run_id, Payslip.employee_id == employee_id
        )
        if company_id is not None:
            stmt = stmt.where(Payslip.company_id == company_id)
        ps = (await session.execute(stmt)).scalar_one_or_none()
        if not ps:
            raise HTTPException(status_code=404, detail="Payslip not found for this employee and run.")

        emp = (await session.execute(select(Employee).where(Employee.id == employee_id))).scalar_one_or_none()
        emp_name = f"{emp.first_name} {emp.last_name}".strip() if emp else "Employee"
        snapshot = ps.snapshot_json if isinstance(ps.snapshot_json, dict) else None
        if snapshot is None and isinstance(ps, Payslip):
            ctx = await cls._load_bulk_context(session, [ps])
            snapshot = cls._assemble_snapshot(
                ps,
                ctx,
                document_id=ps.document_id or f"PREVIEW-{ps.payslip_number}",
                version_number=int(getattr(ps, "document_version", 1) or 1),
                verification_token=ps.verification_token or "",
                generated_at=ps.generated_at or datetime.now(timezone.utc),
            )

        return {
            "id": str(ps.id),
            "company_id": str(ps.company_id) if ps.company_id else None,
            "payroll_run_id": str(ps.payroll_run_id),
            "run_id": str(ps.payroll_run_id),
            "payslip_number": ps.payslip_number,
            "document_id": ps.document_id,
            "document_version": int(getattr(ps, "document_version", 1) or 1),
            "status": getattr(ps, "status", "GENERATED"),
            "sha256_hash": getattr(ps, "sha256_hash", None),
            "employee_id": str(ps.employee_id),
            "employee_name": emp_name,
            "period_month": ps.period_month,
            "period_year": ps.period_year,
            "paid_days": float(ps.paid_days),
            "lop_days": float(ps.lop_days),
            "gross_earnings": float(ps.gross_earnings),
            "total_deductions": float(ps.total_deductions),
            "net_pay": float(ps.net_pay),
            "basic": float(ps.basic or 0),
            "hra": float(ps.hra or 0),
            "conveyance": float(ps.conveyance or 0),
            "special_allowance": float(ps.special_allowance or 0),
            "other_allowances_total": float(ps.other_allowances_total or 0),
            "arrears": float(ps.arrears or 0),
            "bonus": float(ps.bonus or 0),
            "lop_deduction": float(ps.lop_deduction or 0),
            "other_deductions": float(ps.other_deductions or 0),
            "employee_pf": float(ps.employee_pf or 0),
            "employer_pf": float(ps.employer_pf or 0),
            "employee_esi": float(ps.employee_esi or 0),
            "employer_esi": float(ps.employer_esi or 0),
            "professional_tax": float(ps.professional_tax or 0),
            "tds": float(ps.tds or 0),
            "gross_earnings_paise": to_paise_int(ps.gross_earnings),
            "total_deductions_paise": to_paise_int(ps.total_deductions),
            "net_pay_paise": to_paise_int(ps.net_pay),
            "net_pay_words": ps.net_pay_words or amount_in_words(ps.net_pay, getattr(ps, "currency", "INR")),
            "payment_status": ps.payment_status,
            "payment_date": ps.payment_date.isoformat() if ps.payment_date else None,
            "payment_reference": ps.payment_reference,
            "pdf_path": ps.pdf_path,
            "generated_at": ps.generated_at,
            "released_at": getattr(ps, "released_at", None),
            "created_at": ps.created_at,
            "snapshot": snapshot,
        }

    @classmethod
    async def get_payslip_preview(
        cls,
        session: AsyncSession,
        payslip_id: uuid.UUID,
        *,
        company_id: Optional[uuid.UUID] = None,
    ) -> dict[str, Any]:
        """Return database-backed preview snapshot for an existing payslip without hardcoding."""
        stmt = select(Payslip).where(Payslip.id == payslip_id)
        if company_id is not None:
            stmt = stmt.where(Payslip.company_id == company_id)
        ps = (await session.execute(stmt)).scalar_one_or_none()
        if not ps:
            raise HTTPException(status_code=404, detail="Payslip not found.")
        snapshot = ps.snapshot_json if isinstance(ps.snapshot_json, dict) else None
        if snapshot is None and isinstance(ps, Payslip):
            ctx = await cls._load_bulk_context(session, [ps])
            snapshot = cls._assemble_snapshot(
                ps,
                ctx,
                document_id=ps.document_id or f"PREVIEW-{ps.payslip_number}",
                version_number=int(getattr(ps, "document_version", 1) or 1),
                verification_token=ps.verification_token or "",
                generated_at=ps.generated_at or datetime.now(timezone.utc),
            )
        return snapshot

    # ── Legacy / Compatibility _render_pdf ────────────────────────────────────

    @staticmethod
    def _render_pdf(
        title: str,
        lines: list[tuple[str, str]],
        total_lines: list[tuple[str, str]],
        branding: dict | None = None,
        currency: str = "INR",
    ) -> bytes:
        """Render a compact branded A4 summary PDF (backward-compatible entrypoint)."""
        return render_compat_summary_pdf(
            title=title, lines=lines, total_lines=total_lines, branding=branding, currency=currency,
        )

    # ── Password Derivation & AES-256 PDF Encryption ──────────────────────────

    @staticmethod
    def derive_payslip_password(
        employee: Employee,
        payslip: Payslip | None = None,
        rule: str | None = None,
    ) -> str:
        """Derive a deterministic PDF password without storing plaintext secrets."""
        rule = rule or os.getenv("PAYSLIP_PASSWORD_RULE", "FIRST4_NAME_UPPER_DDMM_DOB")
        full_name = f"{getattr(employee, 'first_name', '') or ''} {getattr(employee, 'last_name', '') or ''}".strip()
        letters = re.sub(r"[^A-Za-z]", "", full_name).upper()
        first4 = (letters or "USER")[:4].ljust(4, "X")
        dob = getattr(employee, "date_of_birth", None)
        ddmm = dob.strftime("%d%m") if dob else "0000"
        ddmmyyyy = dob.strftime("%d%m%Y") if dob else "00000000"
        employee_code = str(getattr(employee, "employee_id", None) or getattr(employee, "id", ""))
        replacements = {
            "FIRST4_NAME_UPPER": first4,
            "FIRST4_NAME": first4,
            "NAME_FIRST4": first4,
            "DDMMYYYY_DOB": ddmmyyyy,
            "DDMM_DOB": ddmm,
            "DOB_DDMM": ddmm,
            "DOB": ddmmyyyy,
            "EMPLOYEE_ID": employee_code,
        }
        password = rule
        for token in sorted(replacements, key=len, reverse=True):
            password = password.replace(token, replacements[token])
        return password

    @staticmethod
    def encrypt_pdf(content: bytes, password: str) -> bytes:
        """Return an AES-256 password-encrypted PDF."""
        from pypdf import PdfReader, PdfWriter

        reader = PdfReader(io.BytesIO(content))
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        try:
            writer.encrypt(user_password=password, owner_password=password, algorithm="AES-256")
        except TypeError:
            writer.encrypt(password)
        output = io.BytesIO()
        writer.write(output)
        return output.getvalue()

    @classmethod
    def protect_pdf(
        cls, content: bytes, employee: Employee, payslip: Payslip | None = None,
        password_rule: str | None = None,
    ) -> tuple[bytes, str]:
        password = cls.derive_payslip_password(employee, payslip, password_rule)
        return cls.encrypt_pdf(content, password), password

    # ── Bulk Context Loader (Zero N+1) & Snapshot Builder ─────────────────────

    @staticmethod
    def _build_earnings_and_deductions(
        ps: Payslip,
        run_emp: PayrollRunEmployee | None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        """Build itemized earnings, deductions, and employer contributions strictly matching paise totals."""
        earnings: list[dict[str, Any]] = []
        deductions: list[dict[str, Any]] = []
        employer_contribs: list[dict[str, Any]] = []

        eb = (run_emp.earnings_breakup or {}) if run_emp and isinstance(run_emp.earnings_breakup, dict) else None
        db = (run_emp.deductions_breakup or {}) if run_emp and isinstance(run_emp.deductions_breakup, dict) else None

        ps_gross_dec = quantize_money(ps.gross_earnings)
        ps_ded_dec = quantize_money(ps.total_deductions)
        ps_earn_cols_sum = quantize_money(
            quantize_money(ps.basic)
            + quantize_money(ps.hra)
            + quantize_money(ps.conveyance)
            + quantize_money(ps.special_allowance)
            + quantize_money(ps.other_allowances_total)
            + quantize_money(ps.bonus)
            + quantize_money(ps.arrears)
        )
        ps_ded_cols_sum = quantize_money(
            quantize_money(ps.employee_pf)
            + quantize_money(ps.employee_esi)
            + quantize_money(ps.professional_tax)
            + quantize_money(ps.tds)
            + quantize_money(ps.other_deductions)
        )

        use_eb = (
            eb is not None
            and "gross_paise" in eb
            and (
                int(eb.get("gross_paise") or 0) == to_paise_int(ps_gross_dec)
                or ps_earn_cols_sum != ps_gross_dec
            )
        )

        if use_eb:
            def _add_earn(label: str, paise_val: int, *, required: bool = False) -> None:
                earnings.append({"label": label, "amount": str(paise_to_decimal(paise_val)), "required": required})

            _add_earn("Basic Salary", int(eb.get("basic_paise") or 0), required=True)
            _add_earn("Dearness Allowance (DA)", int(eb.get("da_paise") or 0))
            _add_earn("House Rent Allowance (HRA)", int(eb.get("hra_paise") or 0))
            _add_earn("Conveyance Allowance", int(eb.get("conveyance_paise") or 0))
            _add_earn("Special Allowance", int(eb.get("special_paise") or 0))
            _add_earn("Leave Travel Allowance (LTA)", int(eb.get("lta_paise") or 0))
            _add_earn("Statutory Bonus", int(eb.get("statutory_bonus_paise") or 0))
            _add_earn("Fixed Reimbursements", int(eb.get("reimbursement_paise") or 0))

            for k, v in (eb.get("other_fixed_paise") or {}).items():
                _add_earn(str(k), int(v or 0))
            for k, v in (eb.get("custom_paise") or {}).items():
                _add_earn(str(k).replace("_", " ").title(), int(v or 0))

            var_map = eb.get("variable_components_paise") or {}
            mapped_var_sum = 0
            for code, v in var_map.items():
                amt_p = int(v or 0)
                mapped_var_sum += amt_p
                label = _VARIABLE_EARNING_LABELS.get(str(code).upper(), str(code).replace("_", " ").title())
                _add_earn(label, amt_p)
            unmapped_var = int(eb.get("variable_paise") or 0) - mapped_var_sum
            if unmapped_var != 0:
                _add_earn("Other Variable Pay", unmapped_var)

            _add_earn("One-Time Bonus", int(eb.get("one_time_bonus_paise") or 0))
            _add_earn("Arrears", int(eb.get("arrears_paise") or 0))
        else:
            # Compatibility & revision path when PayrollRunEmployee breakup is unavailable or superseded by Payslip updates
            earnings = [
                {"label": "Basic Salary", "amount": str(quantize_money(ps.basic)), "required": True},
                {"label": "House Rent Allowance (HRA)", "amount": str(quantize_money(ps.hra))},
                {"label": "Conveyance Allowance", "amount": str(quantize_money(ps.conveyance))},
                {"label": "Special Allowance", "amount": str(quantize_money(ps.special_allowance))},
                {"label": "Other Allowances", "amount": str(quantize_money(ps.other_allowances_total))},
                {"label": "Bonus", "amount": str(quantize_money(ps.bonus))},
                {"label": "Arrears", "amount": str(quantize_money(ps.arrears))},
            ]

        use_db = (
            db is not None
            and "total_deductions_paise" in db
            and (
                int(db.get("total_deductions_paise") or 0) == to_paise_int(ps_ded_dec)
                or ps_ded_cols_sum != ps_ded_dec
            )
        )

        if use_db:
            def _add_ded(label: str, paise_val: int, *, required: bool = False) -> None:
                deductions.append({"label": label, "amount": str(paise_to_decimal(paise_val)), "required": required})

            _add_ded("Employee Provident Fund (EPF)", int(db.get("pf_paise") or 0), required=True)
            _add_ded("Employee State Insurance (ESI)", int(db.get("esi_paise") or 0))
            _add_ded("Professional Tax (PT)", int(db.get("pt_paise") or 0), required=True)
            _add_ded("Labour Welfare Fund (LWF)", int(db.get("lwf_paise") or 0))
            _add_ded("Income Tax (TDS u/s 192)", int(db.get("tds_paise") or 0))
            _add_ded("Loan EMI / Salary Advance Recovery", int(db.get("advance_recovery_paise") or 0))
            _add_ded("Other Deductions", int(db.get("variable_deductions_paise") or 0))
            for k, v in (db.get("custom_paise") or db.get("custom") or {}).items():
                val_p = to_paise_int(v) if isinstance(v, (float, Decimal, str)) and not isinstance(k, int) and k not in {"custom_deductions_paise"} else int(v or 0)
                # db["custom"] stores rupee floats while db["custom_deductions_paise"] holds sum
                if "custom" in db and isinstance(db["custom"], dict) and db["custom"].get(k) == v:
                    val_p = to_paise_int(v)
                _add_ded(str(k).replace("_", " ").title(), val_p)
            country_ded = int(db.get("country_employee_deductions_paise") or 0)
            if country_ded:
                _add_ded("Statutory / Social Security", country_ded)

            # Handle rounding residuals only if custom breakup wasn't stored in paise
            sum_ded_p = sum(to_paise_int(d["amount"]) for d in deductions)
            expected_ded_p = int(db.get("total_deductions_paise") or 0)
            if sum_ded_p != expected_ded_p and int(db.get("custom_deductions_paise") or 0) > 0 and not (db.get("custom")):
                _add_ded("Custom Deductions", int(db.get("custom_deductions_paise") or 0))

            # Employer contributions (informational only — never deducted from Net Pay)
            for label, val in [
                ("Employer Provident Fund (EPF + EPS)", quantize_money(db.get("employer_pf"))),
                ("Employer ESI Contribution", quantize_money(db.get("employer_esi"))),
                ("Employer Labour Welfare Fund (LWF)", quantize_money(db.get("employer_lwf"))),
                ("Gratuity Provision", quantize_money(db.get("gratuity_provision"))),
                ("Other Employer Contributions", quantize_money(db.get("employer_custom"))),
            ]:
                if val > Decimal("0.00"):
                    employer_contribs.append({"label": label, "amount": str(val)})
        else:
            deductions = [
                {"label": "Employee Provident Fund (EPF)", "amount": str(quantize_money(ps.employee_pf)), "required": True},
                {"label": "Employee State Insurance (ESI)", "amount": str(quantize_money(ps.employee_esi))},
                {"label": "Professional Tax (PT)", "amount": str(quantize_money(ps.professional_tax)), "required": True},
                {"label": "Income Tax (TDS)", "amount": str(quantize_money(ps.tds))},
                {"label": "Other Deductions", "amount": str(quantize_money(ps.other_deductions))},
            ]
            for label, val in [
                ("Employer PF Contribution", quantize_money(ps.employer_pf)),
                ("Employer ESI Contribution", quantize_money(ps.employer_esi)),
            ]:
                if val > Decimal("0.00"):
                    employer_contribs.append({"label": label, "amount": str(val)})

        return earnings, deductions, employer_contribs

    @classmethod
    async def _load_bulk_context(
        cls,
        session: AsyncSession,
        payslips: list[Payslip],
    ) -> dict[str, Any]:
        """Batch load every related entity needed for PDF generation with zero N+1 queries."""
        if not payslips:
            return {}

        company_ids = {p.company_id for p in payslips if p.company_id}
        run_ids = {p.payroll_run_id for p in payslips if p.payroll_run_id}
        emp_ids = {p.employee_id for p in payslips if p.employee_id}
        sal_ids = {p.salary_structure_id for p in payslips if p.salary_structure_id}

        companies: dict[uuid.UUID, Company] = {}
        if company_ids:
            for c in (await session.execute(select(Company).where(Company.id.in_(company_ids)))).scalars().all():
                companies[c.id] = c

        configs: dict[uuid.UUID, StatutoryComplianceConfig] = {}
        if company_ids:
            for cfg in (await session.execute(
                select(StatutoryComplianceConfig).where(
                    StatutoryComplianceConfig.company_id.in_(company_ids),
                    StatutoryComplianceConfig.is_active == True,  # noqa: E712
                )
            )).scalars().all():
                if cfg.company_id and cfg.company_id not in configs:
                    configs[cfg.company_id] = cfg

        runs: dict[uuid.UUID, PayrollRun] = {}
        period_ids: set[uuid.UUID] = set()
        entity_ids: set[uuid.UUID] = set()
        if run_ids:
            for r in (await session.execute(select(PayrollRun).where(PayrollRun.id.in_(run_ids)))).scalars().all():
                runs[r.id] = r
                if r.period_id:
                    period_ids.add(r.period_id)
                if r.legal_entity_id:
                    entity_ids.add(r.legal_entity_id)

        periods: dict[uuid.UUID, PayrollPeriod] = {}
        if period_ids:
            for per in (await session.execute(select(PayrollPeriod).where(PayrollPeriod.id.in_(period_ids)))).scalars().all():
                periods[per.id] = per

        legal_entities: dict[uuid.UUID, LegalEntity] = {}
        if entity_ids:
            for le in (await session.execute(select(LegalEntity).where(LegalEntity.id.in_(entity_ids)))).scalars().all():
                legal_entities[le.id] = le

        employees: dict[uuid.UUID, Employee] = {}
        bank_by_emp: dict[uuid.UUID, EmployeeBankAccount] = {}
        if emp_ids:
            for emp in (await session.execute(
                select(Employee)
                .options(selectinload(Employee.bank_accounts))
                .where(Employee.id.in_(emp_ids))
            )).scalars().all():
                employees[emp.id] = emp
                accts = list(emp.bank_accounts or [])
                primary = next((a for a in accts if a.is_primary), accts[0] if accts else None)
                if primary:
                    bank_by_emp[emp.id] = primary

        run_emps: dict[tuple[uuid.UUID, uuid.UUID], PayrollRunEmployee] = {}
        if run_ids and emp_ids:
            for re_row in (await session.execute(
                select(PayrollRunEmployee).where(
                    PayrollRunEmployee.run_id.in_(run_ids),
                    PayrollRunEmployee.employee_id.in_(emp_ids),
                )
            )).scalars().all():
                run_emps[(re_row.run_id, re_row.employee_id)] = re_row

        sal_structs: dict[uuid.UUID, SalaryStructure] = {}
        if sal_ids:
            for s in (await session.execute(select(SalaryStructure).where(SalaryStructure.id.in_(sal_ids)))).scalars().all():
                sal_structs[s.id] = s

        # Batch PaymentBatch + PaymentBatchItem to retrieve confirmed payment mode/reference
        payment_mode_by_run: dict[uuid.UUID, str] = {}
        batch_item_by_run_emp: dict[tuple[uuid.UUID, uuid.UUID], PaymentBatchItem] = {}
        if run_ids:
            batches = (await session.execute(
                select(PaymentBatch)
                .where(PaymentBatch.run_id.in_(run_ids), PaymentBatch.status != "REJECTED")
                .order_by(desc(PaymentBatch.created_at))
            )).scalars().all()
            batch_run_map: dict[uuid.UUID, uuid.UUID] = {}
            for b in batches:
                if b.run_id not in payment_mode_by_run:
                    payment_mode_by_run[b.run_id] = b.payment_mode
                batch_run_map[b.id] = b.run_id
            if batch_run_map:
                items = (await session.execute(
                    select(PaymentBatchItem).where(
                        PaymentBatchItem.batch_id.in_(batch_run_map.keys()),
                        PaymentBatchItem.employee_id.in_(emp_ids),
                    )
                )).scalars().all()
                for item in items:
                    r_id = batch_run_map[item.batch_id]
                    batch_item_by_run_emp.setdefault((r_id, item.employee_id), item)

        # Batch Overtime hours (OvertimeEntry or VariableInput overtime units)
        ot_hours_by_key: dict[tuple[uuid.UUID, int, int], Decimal] = {}
        periods_ym = {(p.period_month, p.period_year) for p in payslips}
        if emp_ids and periods_ym:
            months_set = {m for m, _ in periods_ym}
            years_set = {y for _, y in periods_ym}
            ot_rows = (await session.execute(
                select(OvertimeEntry).where(
                    OvertimeEntry.employee_id.in_(emp_ids),
                    OvertimeEntry.period_month.in_(months_set),
                    OvertimeEntry.period_year.in_(years_set),
                )
            )).scalars().all()
            for ot in ot_rows:
                hrs = to_decimal(ot.adjusted_hours if ot.adjusted_hours is not None else ot.ot_hours)
                k = (ot.employee_id, ot.period_month, ot.period_year)
                ot_hours_by_key[k] = ot_hours_by_key.get(k, Decimal("0")) + hrs

        # FY YTD bulk compute via Payslip & EmployeeYTDSalary
        ytd_by_payslip_id: dict[uuid.UUID, dict[str, Any]] = {}
        if emp_ids:
            all_slips = (await session.execute(select(Payslip).where(Payslip.employee_id.in_(emp_ids)))).scalars().all()
            all_imported = (await session.execute(
                select(EmployeeYTDSalary).where(EmployeeYTDSalary.employee_id.in_(emp_ids))
            )).scalars().all()
            slips_by_emp: dict[uuid.UUID, list[Payslip]] = {}
            for s in all_slips:
                slips_by_emp.setdefault(s.employee_id, []).append(s)
            imp_by_emp: dict[uuid.UUID, list[EmployeeYTDSalary]] = {}
            for im in all_imported:
                imp_by_emp.setdefault(im.employee_id, []).append(im)

            for p in payslips:
                fy_start = p.period_year if p.period_month >= 4 else p.period_year - 1
                fy_end_short = str(fy_start + 1)[-2:]
                fy_full = f"{fy_start}-{fy_start + 1}"
                # Include Apr..target period within same FY cleanly
                def _in_fy_up_to(m: int, y: int) -> bool:
                    row_fy = y if m >= 4 else y - 1
                    if row_fy != fy_start:
                        return False
                    row_idx = m - 4 if m >= 4 else m + 8
                    target_idx = p.period_month - 4 if p.period_month >= 4 else p.period_month + 8
                    return row_idx <= target_idx

                seen_periods: set[tuple[int, int]] = set()
                ytd_gross = Decimal("0.00")
                ytd_pf = Decimal("0.00")
                ytd_pt = Decimal("0.00")
                ytd_tds = Decimal("0.00")
                ytd_ded = Decimal("0.00")
                ytd_net = Decimal("0.00")
                has_data = False

                for s in slips_by_emp.get(p.employee_id, []):
                    if _in_fy_up_to(s.period_month, s.period_year):
                        seen_periods.add((s.period_month, s.period_year))
                        ytd_gross += quantize_money(s.gross_earnings)
                        ytd_pf += quantize_money(s.employee_pf)
                        ytd_pt += quantize_money(s.professional_tax)
                        ytd_tds += quantize_money(s.tds)
                        ytd_ded += quantize_money(s.total_deductions)
                        ytd_net += quantize_money(s.net_pay)
                        has_data = True

                for im in imp_by_emp.get(p.employee_id, []):
                    if im.financial_year in (fy_full, f"{fy_start}-{fy_end_short}") and (im.period_month, im.period_year) not in seen_periods and _in_fy_up_to(im.period_month, im.period_year):
                        ytd_gross += paise_to_decimal(im.gross_earnings_paise)
                        ytd_pf += paise_to_decimal(im.pf_paise)
                        ytd_pt += paise_to_decimal(im.pt_paise)
                        ytd_tds += paise_to_decimal(im.tds_paise)
                        ytd_ded += paise_to_decimal(im.total_deductions_paise)
                        ytd_net += paise_to_decimal(im.net_pay_paise)
                        has_data = True

                ytd_by_payslip_id[p.id] = {
                    "has_data": has_data,
                    "financial_year": f"{fy_start}-{fy_end_short}",
                    "gross_earnings": str(quantize_money(ytd_gross)),
                    "employee_pf": str(quantize_money(ytd_pf)),
                    "professional_tax": str(quantize_money(ytd_pt)),
                    "tds": str(quantize_money(ytd_tds)),
                    "total_deductions": str(quantize_money(ytd_ded)),
                    "net_pay": str(quantize_money(ytd_net)),
                }

        # Batch Attendance / Holiday counts per company & period
        holidays_by_co_ym: dict[tuple[uuid.UUID | None, int, int], int] = {}
        if company_ids:
            try:
                async with session.begin_nested():
                    hols = (
                        await session.execute(
                            select(HolidayCalendar).where(HolidayCalendar.company_id.in_(company_ids))
                        )
                    ).scalars().all()
                for h in hols:
                    if h.holiday_date:
                        k = (h.company_id, h.holiday_date.month, h.holiday_date.year)
                        holidays_by_co_ym[k] = holidays_by_co_ym.get(k, 0) + 1
            except Exception:
                pass

        return {
            "companies": companies,
            "configs": configs,
            "runs": runs,
            "periods": periods,
            "legal_entities": legal_entities,
            "employees": employees,
            "bank_by_emp": bank_by_emp,
            "run_emps": run_emps,
            "sal_structs": sal_structs,
            "payment_mode_by_run": payment_mode_by_run,
            "batch_item_by_run_emp": batch_item_by_run_emp,
            "ot_hours_by_key": ot_hours_by_key,
            "ytd_by_payslip_id": ytd_by_payslip_id,
            "holidays_by_co_ym": holidays_by_co_ym,
        }

    @classmethod
    def _assemble_snapshot(
        cls,
        ps: Payslip,
        ctx: dict[str, Any],
        *,
        document_id: str,
        version_number: int,
        verification_token: str,
        generated_at: datetime,
        verification_base_url: str | None = None,
    ) -> dict[str, Any]:
        company = ctx.get("companies", {}).get(ps.company_id) if ps.company_id else None
        config = ctx.get("configs", {}).get(ps.company_id) if ps.company_id else None
        run = ctx.get("runs", {}).get(ps.payroll_run_id)
        period = ctx.get("periods", {}).get(run.period_id) if (run and run.period_id) else None
        legal_entity = ctx.get("legal_entities", {}).get(run.legal_entity_id) if (run and run.legal_entity_id) else None
        emp = ctx.get("employees", {}).get(ps.employee_id) or getattr(ps, "employee", None)
        bank = ctx.get("bank_by_emp", {}).get(ps.employee_id)
        run_emp = ctx.get("run_emps", {}).get((ps.payroll_run_id, ps.employee_id))
        sal = ctx.get("sal_structs", {}).get(ps.salary_structure_id) if ps.salary_structure_id else None

        eff = PayslipSettingsService.resolve_effective_settings(company, config, legal_entity)

        # Period boundaries & month display
        last_dom = calendar.monthrange(ps.period_year, ps.period_month)[1]
        p_start = period.start_date if period and period.start_date else date(ps.period_year, ps.period_month, 1)
        p_end = period.end_date if period and period.end_date else date(ps.period_year, ps.period_month, last_dom)
        month_name = calendar.month_name[max(1, min(12, ps.period_month))]
        period_label = f"{month_name} {ps.period_year}"
        pay_period_range = f"{p_start.strftime('%d %b %Y')} - {p_end.strftime('%d %b %Y')}"

        run_status = str(getattr(run, "status", "") or "").upper()
        is_draft = bool(run is not None and run_status and run_status not in FINALIZED_RUN_STATUSES)

        # Confirmed payment date only shown when actually PAID
        batch_item = ctx.get("batch_item_by_run_emp", {}).get((ps.payroll_run_id, ps.employee_id))
        is_actually_paid = str(ps.payment_status or "").upper() == "PAID" or (batch_item is not None and str(batch_item.status or "").upper() == "SUCCESS")
        payment_date_display = (
            ps.payment_date.strftime("%d %b %Y")
            if (is_actually_paid and ps.payment_date)
            else ("Confirmed on Payment" if is_actually_paid else "Pending Disbursement")
        )
        pay_st_upper = str(ps.payment_status or "PENDING").upper()
        payment_status_display = {
            "PAID": "PAID",
            "HOLD": "ON HOLD",
            "FAILED": "FAILED",
            "PENDING": "PENDING",
        }.get(pay_st_upper, pay_st_upper)

        payment_mode = (
            ctx.get("payment_mode_by_run", {}).get(ps.payroll_run_id)
            or eff.get("default_payment_mode")
            or "NEFT"
        )

        # Attendance summary (uses finalized PayrollRunEmployee / Payslip + calendar weekly offs)
        hr_cfg = (company.hr_settings if company and isinstance(company.hr_settings, dict) else {})
        working_weekdays = hr_cfg.get("working_days") or ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
        day_name_to_idx = {
            "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
            "friday": 4, "saturday": 5, "sunday": 6,
        }
        allowed_idx = {day_name_to_idx[str(d).strip().lower()] for d in working_weekdays if str(d).strip().lower() in day_name_to_idx}
        if not allowed_idx:
            allowed_idx = {0, 1, 2, 3, 4}

        cal_days = int((p_end - p_start).days + 1)
        weekly_offs = 0
        cur_d = p_start
        while cur_d <= p_end:
            if cur_d.weekday() not in allowed_idx:
                weekly_offs += 1
            cur_d = date.fromordinal(cur_d.toordinal() + 1)
        holidays = int(ctx.get("holidays_by_co_ym", {}).get((ps.company_id, ps.period_month, ps.period_year), 0))
        scheduled_working = max(0, cal_days - weekly_offs - holidays)

        paid_days = to_decimal(run_emp.paid_days if run_emp else ps.paid_days, str(cal_days))
        lop_days = to_decimal(run_emp.lop_days if run_emp else ps.lop_days, "0.0")
        unpaid_leave = lop_days
        paid_leave = Decimal("0.0")
        present_days = max(Decimal("0.0"), Decimal(scheduled_working) - lop_days)
        ot_hours = ctx.get("ot_hours_by_key", {}).get((ps.employee_id, ps.period_month, ps.period_year), Decimal("0.0"))

        # Bank & Statutory masking (strictly no fabricated bank/statutory data)
        bank_name = (bank.bank_name if bank else None) or getattr(emp, "bank_name", None)
        raw_acc = (bank.account_number if bank else None) or getattr(emp, "bank_account_number", None)
        raw_pan = getattr(emp, "pan_number", None) if emp else None
        raw_uan = getattr(emp, "uan_number", None) if emp else None
        raw_pf = getattr(emp, "pf_number", None) if emp else None
        raw_esi = (getattr(emp, "esic_number", None) or getattr(emp, "esi_number", None)) if emp else None
        tax_regime = None
        if run_emp and isinstance(run_emp.deductions_breakup, dict) and run_emp.deductions_breakup.get("tax_regime"):
            tax_regime = str(run_emp.deductions_breakup["tax_regime"])
        elif emp and getattr(emp, "tax_regime", None):
            tax_regime = str(emp.tax_regime)
        elif sal and getattr(sal, "tax_regime", None):
            tax_regime = str(sal.tax_regime)

        earnings, deductions, employer_contribs = cls._build_earnings_and_deductions(ps, run_emp)
        currency = str(getattr(ps, "currency", None) or getattr(run, "currency", None) or "INR").upper()
        gross_dec = quantize_money(ps.gross_earnings)
        ded_dec = quantize_money(ps.total_deductions)
        net_dec = quantize_money(ps.net_pay)

        checksum_seed = (
            f"{ps.payslip_number}|{document_id}|{version_number}|{ps.employee_id}|"
            f"{gross_dec}|{ded_dec}|{net_dec}|{ps.period_month}/{ps.period_year}"
        )
        checksum_short = hashlib.sha256(checksum_seed.encode("utf-8")).hexdigest()[:12].upper()

        base_api = str(verification_base_url or getattr(app_settings, "BACKEND_PUBLIC_URL", "") or "").rstrip("/")
        verify_path = f"/api/v2/payroll/payslips/verify/{verification_token}"
        verification_url = f"{base_api}{verify_path}" if base_api else verify_path

        snapshot = {
            "company": {
                "name": eff.get("company_name") or (company.name if company else "Organization"),
                "legal_name": eff.get("company_legal_name"),
                "registered_address": eff.get("registered_address"),
                "city": eff.get("city"),
                "state": eff.get("state"),
                "postal_code": eff.get("postal_code"),
                "country": eff.get("country"),
                "official_email": eff.get("official_email"),
                "official_phone": eff.get("official_phone"),
                "website": eff.get("website"),
                "cin_number": eff.get("cin_number"),
                "gstin": eff.get("gstin"),
                "pf_establishment_code": eff.get("pf_establishment_code"),
                "esic_registration_number": eff.get("esic_registration_number"),
                "logo_url": eff.get("company_logo_url"),
                "primary_color": eff.get("primary_color"),
                "secondary_color": eff.get("secondary_color"),
                "accent_color": eff.get("accent_color"),
                "footer_declaration": eff.get("footer_declaration"),
            },
            "employee": {
                "full_name": f"{emp.first_name} {emp.last_name}".strip() if emp else "Employee",
                "employee_code": emp.employee_id if emp else str(ps.employee_id),
                "department": getattr(emp, "department", None) or "—",
                "designation": getattr(emp, "designation", None) or "—",
                "employment_type": str(getattr(emp, "employment_type", None) or "Full Time").replace("_", " ").title(),
                "joining_date_display": emp.joining_date.strftime("%d %b %Y") if (emp and getattr(emp, "joining_date", None)) else "—",
                "work_location": getattr(emp, "work_location", None) or getattr(emp, "branch", None) or eff.get("city") or "—",
                "period_label": period_label,
                "pay_period_range": pay_period_range,
                "payment_date_display": payment_date_display,
                "payment_mode": payment_mode,
                "payment_status_display": payment_status_display,
                "payslip_number": ps.payslip_number,
            },
            "bank_statutory": {
                "bank_name": bank_name,
                "masked_account_number": mask_account_number(raw_acc),
                "masked_pan": mask_pan(raw_pan),
                "masked_uan": mask_uan(raw_uan),
                "pf_member_number": mask_pf_number(raw_pf, enabled=bool(eff.get("mask_pf_number", True))),
                "esic_number": raw_esi,
                "tax_regime": tax_regime,
            },
            "attendance": {
                "calendar_days": cal_days,
                "scheduled_working_days": scheduled_working,
                "present_days": f"{present_days:.1f}",
                "paid_leave_days": f"{paid_leave:.1f}",
                "holidays": holidays,
                "weekly_offs": weekly_offs,
                "lop_days": f"{lop_days:.1f}",
                "unpaid_leave_days": f"{unpaid_leave:.1f}",
                "paid_days": f"{paid_days:.1f}",
                "overtime_hours": f"{ot_hours:.1f}",
            },
            "earnings": earnings,
            "deductions": deductions,
            "employer_contributions": employer_contribs,
            "totals": {
                "currency": currency,
                "gross_earnings": str(gross_dec),
                "total_deductions": str(ded_dec),
                "net_pay": str(net_dec),
                "net_pay_words": amount_in_words(net_dec, currency),
            },
            "ytd_summary": ctx.get("ytd_by_payslip_id", {}).get(ps.id),
            "hr_support": {
                "hr_contact_name": eff.get("hr_contact_name"),
                "hr_designation": eff.get("hr_designation"),
                "hr_department": eff.get("hr_department"),
                "hr_email": eff.get("hr_email"),
                "hr_phone": eff.get("hr_phone"),
                "payroll_support_email": eff.get("payroll_support_email"),
                "office_extension": eff.get("office_extension"),
            },
            "signatory": {
                "signatory_name": eff.get("signatory_name"),
                "signatory_designation": eff.get("signatory_designation"),
                "signatory_department": eff.get("signatory_department"),
                "signature_image_url": eff.get("signature_image_url"),
                "company_seal_url": eff.get("company_seal_url"),
                "unsigned_declaration": eff.get("unsigned_declaration"),
                "issue_date_display": generated_at.strftime("%d %b %Y"),
            },
            "verification": {
                "payslip_number": ps.payslip_number,
                "document_id": document_id,
                "version_number": version_number,
                "verification_token": verification_token,
                "verification_url": verification_url,
                "generated_display": generated_at.strftime("%d %b %Y, %I:%M %p"),
                "is_draft": is_draft,
                "checksum_short": checksum_short,
                "sha256_hash": None,  # Populated post-PDF-render inside storage step if persisted
            },
            "display_options": {
                "show_zero_components": bool(eff.get("show_zero_components", False)),
                "show_ytd_summary": bool(eff.get("show_ytd_summary", True)),
                "show_employer_contributions": bool(eff.get("show_employer_contributions", True)),
                "enable_qr_verification": bool(eff.get("enable_qr_verification", True)),
                "show_ofc360_footer": bool(eff.get("show_ofc360_footer", True)),
            },
        }
        return snapshot

    # ── Enterprise Generation, Versioning & Retrieval ─────────────────────────

    @classmethod
    async def generate_and_store_payslip(
        cls,
        session: AsyncSession,
        *,
        payslip_id: Optional[uuid.UUID] = None,
        run_id: Optional[uuid.UUID] = None,
        employee_id: Optional[uuid.UUID] = None,
        company_id: Optional[uuid.UUID] = None,
        actor_id: Optional[uuid.UUID] = None,
        actor_role: Optional[str] = None,
        force: bool = False,
        require_finalized: bool = False,
        release: bool = False,
        ctx: Optional[dict[str, Any]] = None,
    ) -> tuple[bytes, str, Payslip, PayslipDocument | None]:
        """Generate, reconcile, SHA-256 hash, store, version, and audit-log an enterprise payslip PDF."""
        stmt = select(Payslip)
        if payslip_id is not None:
            stmt = stmt.where(Payslip.id == payslip_id)
        else:
            stmt = stmt.where(Payslip.payroll_run_id == run_id, Payslip.employee_id == employee_id)
        if company_id is not None:
            stmt = stmt.where(Payslip.company_id == company_id)
        ps = (await session.execute(stmt)).scalar_one_or_none()
        if not ps:
            raise HTTPException(status_code=404, detail="Payslip not found.")

        if ctx is None:
            ctx = await cls._load_bulk_context(session, [ps])

        run = ctx.get("runs", {}).get(ps.payroll_run_id)
        emp = ctx.get("employees", {}).get(ps.employee_id)
        run_status = str(getattr(run, "status", "") or "").upper()
        is_draft = bool(run is not None and run_status and run_status not in FINALIZED_RUN_STATUSES)

        if require_finalized and is_draft:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Official payslips require an approved or finalized payroll run (current: {run_status}).",
            )

        # Reuse active immutable document if already issued (non-draft) and not forcing regeneration
        existing_doc = (
            await session.execute(
                select(PayslipDocument)
                .where(PayslipDocument.payslip_id == ps.id, PayslipDocument.is_active == True)  # noqa: E712
                .order_by(desc(PayslipDocument.version_number))
                .limit(1)
            )
        ).scalar_one_or_none()

        filename = build_payslip_filename(
            emp.employee_id if emp else None, ps.period_month, ps.period_year, ps.payslip_number,
        )

        # Preserve previously issued finalized document verbatim unless force=True or financial correction detected
        if existing_doc is not None and not force and existing_doc.is_draft == is_draft:
            # Verify whether finalized amounts changed cleanly via snapshot comparison
            old_totals = (existing_doc.snapshot_json or {}).get("totals", {})
            amounts_unchanged = (
                quantize_money(old_totals.get("gross_earnings")) == quantize_money(ps.gross_earnings)
                and quantize_money(old_totals.get("total_deductions")) == quantize_money(ps.total_deductions)
                and quantize_money(old_totals.get("net_pay")) == quantize_money(ps.net_pay)
            )
            if amounts_unchanged:
                cached_bytes = await asyncio.to_thread(cls._read_stored_pdf_bytes, existing_doc.file_path)
                if cached_bytes is not None:
                    if release and not ps.released_at:
                        now_dt = datetime.now(timezone.utc)
                        ps.released_at = now_dt
                        ps.released_by = actor_id
                        ps.status = "RELEASED"
                        existing_doc.status = "RELEASED"
                        existing_doc.released_at = now_dt
                        await session.commit()
                    return cached_bytes, filename, ps, existing_doc

        now_dt = datetime.now(timezone.utc)
        next_version = (int(existing_doc.version_number) + 1) if existing_doc is not None else 1
        doc_id = f"DOC-{sanitize_filename_part(ps.payslip_number)}-V{next_version}-{secrets.token_hex(3).upper()}"
        ver_token = secrets.token_urlsafe(24)

        snapshot = cls._assemble_snapshot(
            ps,
            ctx,
            document_id=doc_id,
            version_number=next_version,
            verification_token=ver_token,
            generated_at=now_dt,
        )

        # Render outside event loop, reconcile strictly before disk write
        try:
            validate_financial_reconciliation(snapshot)
            pdf_bytes = await asyncio.to_thread(render_enterprise_payslip_pdf, snapshot)
        except ValueError as rec_err:
            logger.error("Payslip financial reconciliation failed for payslip_id=%s: %s", ps.id, rec_err)
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(rec_err),
            ) from rec_err
        except Exception as pdf_err:
            logger.error(
                "Payslip PDF rendering failed | payslip_id=%s | company_id=%s | error_type=%s | error=%s",
                ps.id,
                ps.company_id,
                type(pdf_err).__name__,
                pdf_err,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Payslip PDF generation failed. Please check branding/font configuration or retry.",
            ) from pdf_err

        sha256_hex = hashlib.sha256(pdf_bytes).hexdigest()
        snapshot["verification"]["sha256_hash"] = sha256_hex

        # Re-render with exact final SHA-256 embedded cleanly (optional visual checksum matches PDF? Note: embedding hash inside PDF alters bytes unless verified against stored hash of final bytes! Keeping exact stored SHA-256 of persisted bytes as verification checksum guarantees byte-for-byte hash verification!)
        rel_path = os.path.join(
            str(ps.company_id or "global"),
            str(ps.payroll_run_id),
            f"{sanitize_filename_part(ps.payslip_number)}_v{next_version}.pdf",
        )
        stored_rel_path, size_bytes, final_sha256 = await asyncio.to_thread(
            cls._write_pdf_bytes_sync, rel_path, pdf_bytes
        )

        if existing_doc is not None:
            existing_doc.is_active = False
            if not existing_doc.is_draft:
                existing_doc.status = "SUPERSEDED"

        doc_status = "DRAFT" if is_draft else ("RELEASED" if release else "FINAL")
        doc_record = PayslipDocument(
            id=uuid.uuid4(),
            company_id=ps.company_id,
            payslip_id=ps.id,
            payroll_run_id=ps.payroll_run_id,
            employee_id=ps.employee_id,
            document_id=doc_id,
            payslip_number=ps.payslip_number,
            version_number=next_version,
            status=doc_status,
            is_draft=is_draft,
            is_active=True,
            file_path=stored_rel_path,
            file_size_bytes=size_bytes,
            sha256_hash=final_sha256,
            verification_token=ver_token,
            snapshot_json=snapshot,
            generated_by=actor_id,
            generated_at=now_dt,
            released_at=now_dt if (release and not is_draft) else None,
        )
        session.add(doc_record)

        # Sync canonical metadata onto Payslip row cleanly
        ps.pdf_path = stored_rel_path
        ps.generated_at = now_dt
        ps.document_id = doc_id
        ps.document_version = next_version
        ps.status = doc_status
        ps.sha256_hash = final_sha256
        ps.verification_token = ver_token
        ps.snapshot_json = snapshot
        ps.net_pay_words = snapshot["totals"]["net_pay_words"]
        if release and not is_draft:
            ps.released_at = now_dt
            ps.released_by = actor_id

        await PayrollAuditService.log_event(
            session=session,
            entity_type="PayslipDocument",
            entity_id=ps.id,
            action="PAYSLIP_REVISED" if next_version > 1 else ("PAYSLIP_RELEASED" if release else "PAYSLIP_GENERATED"),
            company_id=ps.company_id,
            actor_id=actor_id,
            actor_role=actor_role,
            before_status=existing_doc.status if existing_doc else None,
            after_status=doc_status,
            reason=f"Payslip {ps.payslip_number} v{next_version} generated",
            extra_data={"document_id": doc_id, "version": next_version, "is_draft": is_draft},
        )
        await session.commit()
        return pdf_bytes, filename, ps, doc_record

    @classmethod
    async def get_payslip_file(
        cls,
        session: AsyncSession,
        run_id: uuid.UUID,
        employee_id: uuid.UUID,
        password_protect: bool | None = None,
        password_rule: str | None = None,
        company_id: Optional[uuid.UUID] = None,
        force_regenerate: bool = False,
        actor_id: Optional[uuid.UUID] = None,
        actor_role: Optional[str] = None,
    ) -> tuple[bytes, str]:
        """Retrieve or render the enterprise A4 Payslip PDF with optional AES-256 password encryption."""
        pdf_bytes, filename, ps, _ = await cls.generate_and_store_payslip(
            session,
            run_id=run_id,
            employee_id=employee_id,
            company_id=company_id,
            actor_id=actor_id,
            actor_role=actor_role,
            force=force_regenerate,
            require_finalized=False,
        )
        emp = await session.get(Employee, employee_id)
        should_protect = bool(ps and ps.is_password_protected) if password_protect is None else password_protect
        if should_protect and emp is not None:
            pdf_bytes, _ = await asyncio.to_thread(
                cls.protect_pdf, pdf_bytes, emp, ps, password_rule or (ps.password_rule if ps else None)
            )
        return pdf_bytes, filename

    @classmethod
    async def generate_batch_payslips(
        cls,
        session: AsyncSession,
        run_id: uuid.UUID,
        employee_ids: Optional[List[str]] = None,
        force: bool = False,
        format_type: str = "pdf",
        *,
        company_id: Optional[uuid.UUID] = None,
        actor_id: Optional[uuid.UUID] = None,
        actor_role: Optional[str] = None,
        require_finalized: bool = False,
        release: bool = True,
    ) -> int:
        """Bulk generate corporate payslips in bounded threadpool batches with zero N+1 queries."""
        stmt = select(Payslip).where(Payslip.payroll_run_id == run_id)
        if company_id is not None:
            stmt = stmt.where(Payslip.company_id == company_id)
        if employee_ids:
            emp_uuids = [uuid.UUID(str(e)) for e in employee_ids]
            stmt = stmt.where(Payslip.employee_id.in_(emp_uuids))

        payslips = list((await session.execute(stmt)).scalars().all())
        if not payslips:
            return 0

        ctx = await cls._load_bulk_context(session, payslips)
        run = ctx.get("runs", {}).get(run_id)
        if require_finalized and run is not None and str(run.status or "").upper() not in FINALIZED_RUN_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Bulk official payslip generation requires an approved or finalized payroll run (current: {run.status}).",
            )

        existing_docs = {
            d.payslip_id: d
            for d in (
                await session.execute(
                    select(PayslipDocument)
                    .where(
                        PayslipDocument.payroll_run_id == run_id,
                        PayslipDocument.is_active == True,  # noqa: E712
                    )
                )
            ).scalars().all()
        }

        sem = asyncio.Semaphore(8)
        now_dt = datetime.now(timezone.utc)
        pending_render: list[tuple[Payslip, PayslipDocument | None, dict[str, Any], int, str, str, bool]] = []

        run_status = str(getattr(run, "status", "") or "").upper()
        is_draft = bool(run is not None and run_status and run_status not in FINALIZED_RUN_STATUSES)

        for ps in payslips:
            existing_doc = existing_docs.get(ps.id)
            if existing_doc is not None and not force and existing_doc.is_draft == is_draft:
                old_totals = (existing_doc.snapshot_json or {}).get("totals", {})
                amounts_unchanged = (
                    quantize_money(old_totals.get("gross_earnings")) == quantize_money(ps.gross_earnings)
                    and quantize_money(old_totals.get("total_deductions")) == quantize_money(ps.total_deductions)
                    and quantize_money(old_totals.get("net_pay")) == quantize_money(ps.net_pay)
                )
                if amounts_unchanged and cls._read_stored_pdf_bytes(existing_doc.file_path) is not None:
                    continue
            next_version = (int(existing_doc.version_number) + 1) if existing_doc is not None else 1
            doc_id = f"DOC-{sanitize_filename_part(ps.payslip_number)}-V{next_version}-{secrets.token_hex(3).upper()}"
            ver_token = secrets.token_urlsafe(24)
            snap = cls._assemble_snapshot(
                ps, ctx, document_id=doc_id, version_number=next_version, verification_token=ver_token, generated_at=now_dt,
            )
            validate_financial_reconciliation(snap)
            pending_render.append((ps, existing_doc, snap, next_version, doc_id, ver_token, is_draft))

        async def _render_one(snap: dict[str, Any], ps_num: str, ver: int, co_id: uuid.UUID | None) -> tuple[str, int, str]:
            async with sem:
                pdf_bytes = await asyncio.to_thread(render_enterprise_payslip_pdf, snap)
                rel = os.path.join(
                    str(co_id or "global"),
                    str(run_id),
                    f"{sanitize_filename_part(ps_num)}_v{ver}.pdf",
                )
                return await asyncio.to_thread(cls._write_pdf_bytes_sync, rel, pdf_bytes)

        render_results = await asyncio.gather(
            *[_render_one(item[2], item[0].payslip_number, item[3], item[0].company_id) for item in pending_render]
        )

        from app.services import notification_service

        generated_count = 0
        for (ps, existing_doc, snap, next_version, doc_id, ver_token, row_is_draft), (stored_rel, size_bytes, sha256_hex) in zip(
            pending_render, render_results
        ):
            snap["verification"]["sha256_hash"] = sha256_hex
            if existing_doc is not None:
                existing_doc.is_active = False
                if not existing_doc.is_draft:
                    existing_doc.status = "SUPERSEDED"

            doc_status = "DRAFT" if row_is_draft else ("RELEASED" if release else "FINAL")
            session.add(
                PayslipDocument(
                    id=uuid.uuid4(),
                    company_id=ps.company_id,
                    payslip_id=ps.id,
                    payroll_run_id=ps.payroll_run_id,
                    employee_id=ps.employee_id,
                    document_id=doc_id,
                    payslip_number=ps.payslip_number,
                    version_number=next_version,
                    status=doc_status,
                    is_draft=row_is_draft,
                    is_active=True,
                    file_path=stored_rel,
                    file_size_bytes=size_bytes,
                    sha256_hash=sha256_hex,
                    verification_token=ver_token,
                    snapshot_json=snap,
                    generated_by=actor_id,
                    generated_at=now_dt,
                    released_at=now_dt if (release and not row_is_draft) else None,
                )
            )
            ps.pdf_path = stored_rel
            ps.generated_at = now_dt
            ps.document_id = doc_id
            ps.document_version = next_version
            ps.status = doc_status
            ps.sha256_hash = sha256_hex
            ps.verification_token = ver_token
            ps.snapshot_json = snap
            ps.net_pay_words = snap["totals"]["net_pay_words"]
            if release and not row_is_draft:
                ps.released_at = now_dt
                ps.released_by = actor_id
            generated_count += 1

            try:
                emp = ctx.get("employees", {}).get(ps.employee_id)
                if emp and emp.user_id and emp.company_id:
                    await notification_service.notify(
                        session,
                        company_id=emp.company_id,
                        recipient_ids=[emp.user_id],
                        type="payroll.payslip_published",
                        category="payroll",
                        module="payroll",
                        title=f"Payslip Published: {ps.period_month:02d}/{ps.period_year}",
                        body=f"Your salary slip ({ps.payslip_number}) for {ps.period_month:02d}/{ps.period_year} is ready.",
                        link="/dashboard/payroll/payslips",
                        priority="normal",
                        entity={"type": "payslip", "id": str(ps.id)},
                        dedupe_key=f"payroll:payslip:{ps.id}:v{next_version}:published",
                    )
            except Exception as exc:
                logger.warning("Failed emitting payslip notification for emp=%s: %s", ps.employee_id, exc)

        if generated_count > 0:
            await PayrollAuditService.log_event(
                session=session,
                entity_type="PayrollRun",
                entity_id=run_id,
                action="BULK_PAYSLIP_GENERATE",
                company_id=payslips[0].company_id,
                actor_id=actor_id,
                actor_role=actor_role,
                reason=f"Bulk generated {generated_count} corporate payslip PDF(s)",
                extra_data={"generated_count": generated_count},
            )
        await session.commit()
        return generated_count

    # ── Public Minimal Authenticity Verification (Section 15) ──────────────────

    @classmethod
    async def verify_document_token(
        cls,
        session: AsyncSession,
        token: str,
        *,
        payslip_number: Optional[str] = None,
    ) -> dict[str, Any]:
        """Verify payslip authenticity without exposing salary, bank, PAN, or personal PII."""
        clean_token = str(token or "").strip()
        if not clean_token:
            return {"valid": False, "status": "INVALID_TOKEN", "message": "Verification token is required."}

        doc = (
            await session.execute(
                select(PayslipDocument).where(PayslipDocument.verification_token == clean_token).limit(1)
            )
        ).scalar_one_or_none()

        if doc is None:
            return {"valid": False, "status": "NOT_FOUND", "message": "Payslip verification record not found."}

        if payslip_number and doc.payslip_number.strip().upper() != payslip_number.strip().upper():
            return {"valid": False, "status": "MISMATCH", "message": "Payslip number does not match token."}

        snap = doc.snapshot_json if isinstance(doc.snapshot_json, dict) else {}
        co_name = (snap.get("company") or {}).get("name") or "Authorized Organization"
        period_lbl = (snap.get("employee") or {}).get("period_label") or ""
        stored_bytes = await asyncio.to_thread(cls._read_stored_pdf_bytes, doc.file_path)
        file_integrity_ok = (
            hashlib.sha256(stored_bytes).hexdigest() == doc.sha256_hash
            if stored_bytes is not None
            else True
        )

        return {
            "valid": bool(file_integrity_ok and not doc.is_draft),
            "is_draft": bool(doc.is_draft),
            "integrity_verified": file_integrity_ok,
            "status": doc.status,
            "document_id": doc.document_id,
            "payslip_number": doc.payslip_number,
            "version_number": doc.version_number,
            "company_name": co_name,
            "period_label": period_lbl,
            "issued_at": doc.generated_at.isoformat() if doc.generated_at else None,
            "sha256_prefix": doc.sha256_hash[:16],
        }

    # ── YTD Financial Summary (Preserved) ─────────────────────────────────────

    @staticmethod
    def _financial_year_start(financial_year: str | int | None) -> int:
        if financial_year is None:
            today = date.today()
            return today.year if today.month >= 4 else today.year - 1
        if isinstance(financial_year, int):
            return financial_year
        value = str(financial_year).strip()
        match = re.match(r"^(\d{4})(?:\s*[-/]\s*(\d{2,4}))?$", value)
        if not match:
            raise ValueError("financial_year must be YYYY, YYYY-YY or YYYY-YYYY")
        return int(match.group(1))

    @classmethod
    async def get_ytd_summary(
        cls, session: AsyncSession, employee_id: uuid.UUID,
        financial_year: str | int | None = None, company_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Build a complete April-March financial-year payslip summary."""
        start_year = cls._financial_year_start(financial_year)
        month_numbers = list(range(4, 13)) + list(range(1, 4))
        stmt = select(Payslip).where(Payslip.employee_id == employee_id)
        if company_id is not None:
            stmt = stmt.where(Payslip.company_id == company_id)
        payslips = (await session.execute(stmt)).scalars().all()
        by_period = {(p.period_year, p.period_month): p for p in payslips}
        imported_stmt = select(EmployeeYTDSalary).where(
            EmployeeYTDSalary.employee_id == employee_id,
            EmployeeYTDSalary.financial_year == f"{start_year}-{start_year + 1}",
        )
        if company_id is not None:
            imported_stmt = imported_stmt.where(EmployeeYTDSalary.company_id == company_id)
        imported_rows = (await session.execute(imported_stmt)).scalars().all()
        imported_by_period = {(row.period_year, row.period_month): row for row in imported_rows}
        run_ids = [p.payroll_run_id for p in payslips]
        breakups: dict[tuple[uuid.UUID, uuid.UUID], dict] = {}
        if run_ids:
            run_emps = (await session.execute(select(PayrollRunEmployee).where(
                PayrollRunEmployee.run_id.in_(run_ids),
                PayrollRunEmployee.employee_id == employee_id,
            ))).scalars().all()
            breakups = {(r.run_id, r.employee_id): (r.deductions_breakup or {}) for r in run_emps}

        def amount(row: Payslip | None, field: str) -> float:
            return float(getattr(row, field, 0) or 0) if row is not None else 0.0

        def period_amount(ps: Payslip | None, imported: EmployeeYTDSalary | None, field: str, imported_field: str) -> float:
            if ps is not None:
                return amount(ps, field)
            if imported is not None:
                return int(getattr(imported, imported_field, 0) or 0) / 100.0
            return 0.0

        rows: list[dict[str, Any]] = []
        for month in month_numbers:
            year = start_year if month >= 4 else start_year + 1
            ps = by_period.get((year, month))
            imported = imported_by_period.get((year, month)) if ps is None else None
            breakup = breakups.get((ps.payroll_run_id, ps.employee_id), {}) if ps else {}
            lwf = float(breakup.get("lwf", 0) or 0)
            if not lwf and breakup.get("lwf_paise") is not None:
                lwf = float(breakup["lwf_paise"] or 0) / 100
            if not lwf and ps is not None:
                lwf = float(getattr(ps, "lwf", 0) or 0)
            if imported is not None:
                lwf = int(imported.lwf_paise or 0) / 100.0
            row = {
                "month": month, "month_number": month, "month_name": calendar.month_name[month],
                "period_month": month, "period_year": year, "period": f"{year}-{month:02d}",
                "gross_earnings": period_amount(ps, imported, "gross_earnings", "gross_earnings_paise"),
                "arrears": period_amount(ps, imported, "arrears", "arrears_paise"),
                "pf": period_amount(ps, imported, "employee_pf", "pf_paise"),
                "employee_pf": period_amount(ps, imported, "employee_pf", "pf_paise"),
                "esi": period_amount(ps, imported, "employee_esi", "esi_paise"),
                "employee_esi": period_amount(ps, imported, "employee_esi", "esi_paise"),
                "pt": period_amount(ps, imported, "professional_tax", "pt_paise"),
                "professional_tax": period_amount(ps, imported, "professional_tax", "pt_paise"),
                "lwf": lwf, "tds": period_amount(ps, imported, "tds", "tds_paise"),
                "total_deductions": period_amount(ps, imported, "total_deductions", "total_deductions_paise"),
                "net_pay": period_amount(ps, imported, "net_pay", "net_pay_paise"),
                "payslip_id": str(ps.id) if ps else None,
                "source": "PAYSLIP" if ps else "MIGRATION" if imported else "EMPTY",
                "migration_batch_id": str(imported.migration_batch_id) if imported and imported.migration_batch_id else None,
            }
            for key in ("gross_earnings", "arrears", "pf", "employee_pf", "esi", "employee_esi", "pt", "professional_tax", "lwf", "tds", "total_deductions", "net_pay"):
                row[f"{key}_paise"] = int(round(row[key] * 100))
            rows.append(row)
        totals = {key: round(sum(row[key] for row in rows), 2) for key in (
            "gross_earnings", "arrears", "pf", "employee_pf", "esi", "employee_esi",
            "pt", "professional_tax", "lwf", "tds", "total_deductions", "net_pay",
        )}
        for key, value in list(totals.items()):
            totals[f"{key}_paise"] = int(round(value * 100))
        fy_label = f"{start_year}-{str(start_year + 1)[-2:]}"
        return {
            "employee_id": str(employee_id), "financial_year": fy_label,
            "financial_year_start_year": start_year, "months": rows,
            "month_breakdown": rows, "totals": totals, "ytd_totals": totals,
        }

    # ── Email & WhatsApp Delivery ─────────────────────────────────────────────

    @classmethod
    async def deliver_payslips(
        cls,
        session: AsyncSession,
        run_id: uuid.UUID,
        employee_ids: list[str] | None = None,
        channels: list[str] | None = None,
        password_rule: str | None = None,
        is_password_protected: bool = True,
        company_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Generate official payslips (batch context) and deliver via selected channels."""
        selected_channels = [c.lower() for c in (channels or ["email", "whatsapp"])]
        selected_channels = [c for c in selected_channels if c in {"email", "whatsapp"}]
        if not selected_channels:
            raise ValueError("At least one of email or whatsapp must be selected")

        stmt = select(Payslip).where(Payslip.payroll_run_id == run_id)
        if company_id is not None:
            stmt = stmt.where(Payslip.company_id == company_id)
        if employee_ids:
            stmt = stmt.where(Payslip.employee_id.in_([uuid.UUID(str(x)) for x in employee_ids]))
        payslips = list((await session.execute(stmt)).scalars().all())
        ctx = await cls._load_bulk_context(session, payslips)

        results: list[dict[str, Any]] = []
        for ps in payslips:
            emp = ctx.get("employees", {}).get(ps.employee_id)
            if emp is None:
                ps.delivery_error = "Employee not found"
                ps.email_status = "FAILED" if "email" in selected_channels else ps.email_status
                ps.whatsapp_status = "FAILED" if "whatsapp" in selected_channels else ps.whatsapp_status
                results.append({"payslip_id": str(ps.id), "status": "FAILED", "error": ps.delivery_error})
                continue

            errors: list[str] = []
            try:
                content, filename, _, _ = await cls.generate_and_store_payslip(
                    session, payslip_id=ps.id, company_id=ps.company_id, release=True, ctx=ctx,
                )
                resolved_rule = password_rule or ps.password_rule or os.getenv("PAYSLIP_PASSWORD_RULE", "FIRST4_NAME_UPPER_DDMM_DOB")
                if is_password_protected:
                    content, _ = await asyncio.to_thread(
                        cls.protect_pdf, content, emp, ps, resolved_rule
                    )
                ps.is_password_protected = is_password_protected
                ps.password_rule = resolved_rule
                attachment = (filename, content, "application/pdf")
            except Exception as exc:
                content, filename, attachment = None, "", None
                errors.append(f"PDF: {exc}")

            now = datetime.now(timezone.utc)
            company = ctx.get("companies", {}).get(ps.company_id)
            co_name = company.name if company else "Your Employer"
            month_name = calendar.month_name[max(1, min(12, ps.period_month))]

            if "email" in selected_channels:
                try:
                    if attachment is None:
                        raise RuntimeError("PDF generation failed")
                    recipient = emp.company_email or emp.personal_email
                    if not recipient:
                        raise RuntimeError("Employee email is missing")
                    await send_email(
                        recipient,
                        f"{co_name} — Salary Slip for {month_name} {ps.period_year} ({ps.payslip_number})",
                        (
                            f"<p>Dear {emp.first_name},</p>"
                            f"<p>Please find attached your salary slip (<b>{ps.payslip_number}</b>) for "
                            f"<b>{month_name} {ps.period_year}</b> from {co_name}.</p>"
                            "<p>This document is password-protected if configured per your organization's payroll security policy.</p>"
                        ),
                        attachments=[attachment],
                    )
                    ps.email_status, ps.email_sent_at = "SENT", now
                except Exception as exc:
                    ps.email_status = "FAILED"
                    errors.append(f"Email: {exc}")

            if "whatsapp" in selected_channels:
                try:
                    if attachment is None:
                        raise RuntimeError("PDF generation failed")
                    if not emp.phone:
                        raise RuntimeError("Employee phone is missing")
                    await send_whatsapp_message(
                        emp.phone,
                        f"{co_name}: Your salary slip ({ps.payslip_number}) for {month_name} {ps.period_year} is attached.",
                        attachment=attachment,
                    )
                    ps.whatsapp_status, ps.whatsapp_sent_at = "SENT", now
                except Exception as exc:
                    ps.whatsapp_status = "FAILED"
                    errors.append(f"WhatsApp: {exc}")

            ps.delivery_error = "; ".join(errors) or None
            if ps.email_status == "SENT" or ps.whatsapp_status == "SENT":
                ps.sent_at = now
            results.append({
                "payslip_id": str(ps.id),
                "employee_id": str(ps.employee_id),
                "email_status": ps.email_status,
                "whatsapp_status": ps.whatsapp_status,
                "sent_at": ps.sent_at.isoformat() if ps.sent_at else None,
                "delivery_error": ps.delivery_error,
            })

        await session.commit()
        return {
            "run_id": str(run_id),
            "total": len(results),
            "items": results,
            "failed": sum(1 for r in results if r.get("delivery_error")),
        }

    # ── Provision Slips (Preserved) ───────────────────────────────────────────

    @classmethod
    async def list_provision_slips(
        cls, session: AsyncSession, employee_id: uuid.UUID
    ) -> List[ProvisionSlip]:
        stmt = (
            select(ProvisionSlip)
            .where(ProvisionSlip.employee_id == employee_id)
            .order_by(desc(ProvisionSlip.period_year), desc(ProvisionSlip.period_month))
        )
        return list((await session.execute(stmt)).scalars().all())

    @classmethod
    async def get_provision_slip_pdf(
        cls, session: AsyncSession, slip_id: uuid.UUID
    ) -> tuple[bytes, str]:
        stmt = select(ProvisionSlip).where(ProvisionSlip.id == slip_id)
        slip = (await session.execute(stmt)).scalar_one_or_none()
        if not slip:
            raise HTTPException(status_code=404, detail="Provision slip not found.")
        gross = paise_to_decimal(slip.gross_earnings_paise)
        ded = paise_to_decimal(slip.total_deductions_paise)
        net = paise_to_decimal(slip.net_pay_paise)
        content = cls._render_pdf(
            "PROVISION PAYSLIP (ESTIMATE)",
            [("Slip number", slip.slip_number), ("Period", f"{slip.period_month:02d}/{slip.period_year}")],
            [
                ("Gross earnings", format_currency(gross, "INR")),
                ("Total deductions", format_currency(ded, "INR")),
                ("NET PAY (ESTIMATE)", format_currency(net, "INR")),
            ],
        )
        return content, f"ProvisionSlip_{sanitize_filename_part(slip.slip_number)}.pdf"
