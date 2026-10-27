"""Service for Payslip and Provision Slip generation, retrieval, and PDF downloads."""

from __future__ import annotations

import calendar
import io
import logging
import os
import re
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, List, Optional

from fastapi import HTTPException, status
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employee import Employee
from app.models.payroll import PayrollRun, Payslip
from app.models.payroll_models import EmployeeYTDSalary, PayrollRunEmployee, ProvisionSlip
from app.services.email_service import send_email
from app.services.whatsapp_service import send_whatsapp_message

logger = logging.getLogger(__name__)


class PayslipService:
    """Business logic for Payslips and Provision Slips."""

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
        cls, session: AsyncSession, run_id: uuid.UUID, employee_id: uuid.UUID
    ) -> dict[str, Any]:
        stmt = select(Payslip).where(
            Payslip.payroll_run_id == run_id, Payslip.employee_id == employee_id
        )
        ps = (await session.execute(stmt)).scalar_one_or_none()
        if not ps:
            raise HTTPException(status_code=404, detail="Payslip not found for this employee and run.")

        emp_stmt = select(Employee).where(Employee.id == employee_id)
        emp = (await session.execute(emp_stmt)).scalar_one_or_none()
        emp_name = f"{emp.first_name} {emp.last_name}".strip() if emp else "Employee"

        return {
            "id": str(ps.id),
            "payslip_number": ps.payslip_number,
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
            "employee_esi": float(ps.employee_esi or 0),
            "professional_tax": float(ps.professional_tax or 0),
            "tds": float(ps.tds or 0),
            "gross_earnings_paise": int(ps.gross_earnings * 100),
            "total_deductions_paise": int(ps.total_deductions * 100),
            "net_pay_paise": int(ps.net_pay * 100),
            "payment_status": ps.payment_status,
            "pdf_path": ps.pdf_path,
            "created_at": ps.created_at,
        }

    @classmethod
    async def generate_batch_payslips(
        cls,
        session: AsyncSession,
        run_id: uuid.UUID,
        employee_ids: Optional[List[str]] = None,
        force: bool = False,
        format_type: str = "pdf",
    ) -> int:
        stmt = select(Payslip).where(Payslip.payroll_run_id == run_id)
        if employee_ids:
            emp_uuids = [uuid.UUID(e) for e in employee_ids]
            stmt = stmt.where(Payslip.employee_id.in_(emp_uuids))

        payslips = (await session.execute(stmt)).scalars().all()
        generated_count = 0
        from app.models.employee import Employee
        from app.services import notification_service

        for ps in payslips:
            if not ps.pdf_path or force:
                ps.pdf_path = f"uploads/payslips/{run_id}/{ps.employee_id}.pdf"
                ps.generated_at = datetime.now()
                generated_count += 1

                # Emit payslip published notification to employee
                try:
                    emp = await session.get(Employee, ps.employee_id)
                    if emp and emp.user_id and emp.company_id:
                        await notification_service.notify(
                            session,
                            company_id=emp.company_id,
                            recipient_ids=[emp.user_id],
                            type="payroll.payslip_published",
                            category="payroll",
                            module="payroll",
                            title=f"Payslip Published: {ps.period_month:02d}/{ps.period_year}",
                            body=f"Your payslip for {ps.period_month:02d}/{ps.period_year} is ready to view.",
                            link="/dashboard/payroll/payslips",
                            priority="normal",
                            entity={"type": "payslip", "id": str(ps.id)},
                            dedupe_key=f"payroll:payslip:{ps.id}:published",
                        )
                except Exception as e:
                    logger.warning("Failed to emit payslip notification for emp=%s: %s", ps.employee_id, e)

        await session.commit()
        return generated_count

    @staticmethod
    def _render_pdf(title: str, lines: list[tuple[str, str]], total_lines: list[tuple[str, str]]) -> bytes:
        """Render a compact, readable A4 PDF using the production PDF stack."""
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

        output = io.BytesIO()
        document = SimpleDocTemplate(
            output, pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm,
            topMargin=16 * mm, bottomMargin=16 * mm, title=title,
            author="OFC360 Payroll",
        )
        styles = getSampleStyleSheet()
        story = [Paragraph(title, styles["Title"]), Spacer(1, 5 * mm)]
        table_data = [["Description", "Amount / Value"]] + [[str(k), str(v)] for k, v in lines]
        table_data += [[str(k), str(v)] for k, v in total_lines]
        table = Table(table_data, colWidths=[105 * mm, 60 * mm], repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#17365D")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, len(lines) + 1), (-1, -1), "Helvetica-Bold"),
            ("BACKGROUND", (0, len(lines) + 1), (-1, -1), colors.HexColor("#EAF2F8")),
            ("ALIGN", (1, 1), (1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#B7C9D6")),
            ("ROWBACKGROUNDS", (0, 1), (-1, len(lines)), [colors.white, colors.HexColor("#F7FAFC")]),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]))
        story.append(table)
        story.append(Spacer(1, 5 * mm))
        story.append(Paragraph("Generated by OFC360 Payroll - All amounts are in INR.", styles["Normal"]))
        document.build(story)
        return output.getvalue()

    @staticmethod
    def derive_payslip_password(
        employee: Employee,
        payslip: Payslip | None = None,
        rule: str | None = None,
    ) -> str:
        """Derive a password without persisting it in the database.

        The default rule is ``FIRST4_NAME_UPPER_DDMM_DOB``.  Additional token
        forms are accepted for tenants that already use a different convention.
        A missing DOB uses ``0000`` as a compatibility fallback; tenants should
        supply DOB data for meaningful password entropy.
        """
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
        # Longest tokens first prevents DDMM_DOB being partially replaced by
        # a custom token containing the same prefix.
        password = rule
        for token in sorted(replacements, key=len, reverse=True):
            password = password.replace(token, replacements[token])
        return password

    @staticmethod
    def encrypt_pdf(content: bytes, password: str) -> bytes:
        """Return an encrypted PDF using the installed pypdf version."""
        from pypdf import PdfReader, PdfWriter

        reader = PdfReader(io.BytesIO(content))
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        try:
            writer.encrypt(user_password=password, owner_password=password, algorithm="AES-256")
        except TypeError:  # pypdf versions before the algorithm keyword
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

    @classmethod
    async def get_payslip_file(
        cls, session: AsyncSession, run_id: uuid.UUID, employee_id: uuid.UUID,
        password_protect: bool | None = None, password_rule: str | None = None,
    ) -> tuple[bytes, str]:
        detail = await cls.get_payslip_detail(session, run_id, employee_id)
        money = lambda key: f"Rs. {detail[key]:,.2f}"
        lines = [
            ("Payslip number", detail["payslip_number"]),
            ("Employee", detail["employee_name"]),
            ("Period", f"{detail['period_month']:02d}/{detail['period_year']}"),
            ("Paid days / LOP days", f"{detail['paid_days']} / {detail['lop_days']}"),
            ("Basic", money("basic")), ("HRA", money("hra")),
            ("Conveyance", money("conveyance")),
            ("Special allowance", money("special_allowance")),
            ("Other allowances / reimbursements", money("other_allowances_total")),
            ("Arrears", money("arrears")), ("Statutory bonus", money("bonus")),
            ("PF / ESI / PT / TDS", f"{money('employee_pf')} / {money('employee_esi')} / {money('professional_tax')} / {money('tds')}"),
            ("Other deductions", money("other_deductions")),
        ]
        totals = [("Gross earnings", money("gross_earnings")),
                  ("Total deductions", money("total_deductions")), ("NET PAY", money("net_pay"))]
        content = cls._render_pdf("OFC360 PAYSLIP", lines, totals)
        ps = (await session.execute(select(Payslip).where(
            Payslip.payroll_run_id == run_id, Payslip.employee_id == employee_id
        ))).scalar_one_or_none()
        emp = await session.get(Employee, employee_id)
        should_protect = bool(ps and ps.is_password_protected) if password_protect is None else password_protect
        if should_protect and emp is not None:
            content, _ = cls.protect_pdf(content, emp, ps, password_rule or (ps.password_rule if ps else None))
        filename = f"Payslip_{detail['period_year']}_{detail['period_month']:02d}_{detail['payslip_number']}.pdf"
        return content, filename

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
            # A canonical payslip always wins; imported history fills only gaps.
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

    @classmethod
    async def deliver_payslips(
        cls, session: AsyncSession, run_id: uuid.UUID,
        employee_ids: list[str] | None = None, channels: list[str] | None = None,
        password_rule: str | None = None, is_password_protected: bool = True,
    ) -> dict[str, Any]:
        """Generate and deliver selected payslips, recording each channel result."""
        selected_channels = [c.lower() for c in (channels or ["email", "whatsapp"])]
        selected_channels = [c for c in selected_channels if c in {"email", "whatsapp"}]
        if not selected_channels:
            raise ValueError("At least one of email or whatsapp must be selected")
        stmt = select(Payslip).where(Payslip.payroll_run_id == run_id)
        if employee_ids:
            stmt = stmt.where(Payslip.employee_id.in_([uuid.UUID(str(x)) for x in employee_ids]))
        payslips = list((await session.execute(stmt)).scalars().all())
        results: list[dict[str, Any]] = []
        for ps in payslips:
            emp = await session.get(Employee, ps.employee_id)
            if emp is None:
                ps.delivery_error = "Employee not found"
                ps.email_status = "FAILED" if "email" in selected_channels else ps.email_status
                ps.whatsapp_status = "FAILED" if "whatsapp" in selected_channels else ps.whatsapp_status
                results.append({"payslip_id": str(ps.id), "status": "FAILED", "error": ps.delivery_error})
                continue
            errors: list[str] = []
            try:
                content, filename = await cls.get_payslip_file(
                    session, run_id, ps.employee_id,
                    password_protect=is_password_protected, password_rule=password_rule,
                )
                ps.is_password_protected = is_password_protected
                ps.password_rule = password_rule or os.getenv("PAYSLIP_PASSWORD_RULE", "FIRST4_NAME_UPPER_DDMM_DOB")
                attachment = (filename, content, "application/pdf")
            except Exception as exc:
                content, filename, attachment = None, "", None
                errors.append(f"PDF: {exc}")
            now = datetime.utcnow()
            if "email" in selected_channels:
                try:
                    if attachment is None:
                        raise RuntimeError("PDF generation failed")
                    recipient = emp.company_email or emp.personal_email
                    if not recipient:
                        raise RuntimeError("Employee email is missing")
                    await send_email(
                        recipient, f"Your payslip for {ps.period_month:02d}/{ps.period_year}",
                        f"<p>Hello {emp.first_name},</p><p>Your payslip is attached.</p>",
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
                        emp.phone, f"Your payslip for {ps.period_month:02d}/{ps.period_year} is attached.",
                        attachment=attachment,
                    )
                    ps.whatsapp_status, ps.whatsapp_sent_at = "SENT", now
                except Exception as exc:
                    ps.whatsapp_status = "FAILED"
                    errors.append(f"WhatsApp: {exc}")
            ps.delivery_error = "; ".join(errors) or None
            if (ps.email_status == "SENT" or ps.whatsapp_status == "SENT") and not errors:
                ps.sent_at = now
            elif ps.email_status == "SENT" or ps.whatsapp_status == "SENT":
                ps.sent_at = now
            results.append({
                "payslip_id": str(ps.id), "employee_id": str(ps.employee_id),
                "email_status": ps.email_status, "whatsapp_status": ps.whatsapp_status,
                "sent_at": ps.sent_at.isoformat() if ps.sent_at else None,
                "delivery_error": ps.delivery_error,
            })
        await session.commit()
        return {"run_id": str(run_id), "total": len(results), "items": results,
                "failed": sum(1 for r in results if r.get("delivery_error"))}

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
        values = {
            "slip": slip.slip_number,
            "period": f"{slip.period_month:02d}/{slip.period_year}",
            "gross": float(slip.gross_earnings_paise) / 100,
            "deductions": float(slip.total_deductions_paise) / 100,
            "net": float(slip.net_pay_paise) / 100,
        }
        content = cls._render_pdf(
            "PROVISION PAYSLIP (ESTIMATE)",
            [("Slip number", values["slip"]), ("Period", values["period"])],
            [("Gross earnings", f"Rs. {values['gross']:,.2f}"),
             ("Total deductions", f"Rs. {values['deductions']:,.2f}"),
             ("NET PAY (ESTIMATE)", f"Rs. {values['net']:,.2f}")],
        )
        return content, f"ProvisionSlip_{slip.slip_number}.pdf"
