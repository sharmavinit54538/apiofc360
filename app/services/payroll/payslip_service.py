"""Service for Payslip and Provision Slip generation, retrieval, and PDF downloads."""

from __future__ import annotations

import io
import logging
import uuid
from datetime import datetime
from typing import Any, List, Optional

from fastapi import HTTPException, status
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employee import Employee
from app.models.payroll import PayrollRun, Payslip
from app.models.payroll_models import PayrollRunEmployee, ProvisionSlip

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

    @classmethod
    async def get_payslip_file(
        cls, session: AsyncSession, run_id: uuid.UUID, employee_id: uuid.UUID
    ) -> tuple[bytes, str]:
        detail = await cls.get_payslip_detail(session, run_id, employee_id)
        money = lambda key: f"Rs. {detail[key]:,.2f}"
        lines = [
            ("Payslip number", detail["payslip_number"]),
            ("Employee", detail["employee_name"]),
            ("Period", f"{detail['period_month']:02d}/{detail['period_year']}"),
            ("Paid days / LOP days", f"{detail['paid_days']} / {detail['lop_days']}"),
            ("Basic", money("basic")),
            ("HRA", money("hra")),
            ("Conveyance", money("conveyance")),
            ("Special allowance", money("special_allowance")),
            ("Other allowances / reimbursements", money("other_allowances_total")),
            ("Arrears", money("arrears")),
            ("Statutory bonus", money("bonus")),
            ("PF / ESI / PT / TDS", f"{money('employee_pf')} / {money('employee_esi')} / {money('professional_tax')} / {money('tds')}"),
            ("Other deductions", money("other_deductions")),
        ]
        totals = [
            ("Gross earnings", money("gross_earnings")),
            ("Total deductions", money("total_deductions")),
            ("NET PAY", money("net_pay")),
        ]
        content = cls._render_pdf("OFC360 PAYSLIP", lines, totals)
        filename = f"Payslip_{detail['period_year']}_{detail['period_month']:02d}_{detail['payslip_number']}.pdf"
        return content, filename

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
