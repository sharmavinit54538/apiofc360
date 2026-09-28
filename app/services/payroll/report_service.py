"""Service for Dynamic Payroll Reports and Exports using Strategy Pattern."""

from __future__ import annotations

import csv
import io
import logging
import uuid
from typing import Any, Callable, Dict, List, Optional

from fastapi import HTTPException, status
from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employee import Employee
from app.models.payroll import Payslip
from app.models.payroll_models import PayrollPeriod, PayrollReportExport

logger = logging.getLogger(__name__)


class PayrollReportService:
    """Dynamic query builder and registry for payroll reports."""

    _REGISTRY: Dict[str, Callable] = {}

    @classmethod
    def register_builder(cls, report_key: str):
        def decorator(fn: Callable):
            cls._REGISTRY[report_key.lower()] = fn
            return fn
        return decorator

    @classmethod
    async def get_report_data(
        cls,
        session: AsyncSession,
        report_key: str,
        filters: dict[str, Any],
        page: int = 1,
        limit: int = 50,
        sort_by: Optional[str] = None,
        sort_dir: Optional[str] = "asc",
        company_id: Optional[uuid.UUID] = None,
    ) -> dict[str, Any]:
        key = report_key.lower().replace("-", "_")

        # Base query joining Payslip and Employee
        stmt = (
            select(Payslip, Employee)
            .join(Employee, Payslip.employee_id == Employee.id)
        )
        if company_id:
            stmt = stmt.where(Payslip.company_id == company_id)

        period_id = filters.get("periodId") or filters.get("period_id")
        if period_id:
            try:
                p_uuid = uuid.UUID(str(period_id))
                p_obj = (
                    await session.execute(select(PayrollPeriod).where(PayrollPeriod.id == p_uuid))
                ).scalar_one_or_none()
                if p_obj:
                    stmt = stmt.where(
                        Payslip.period_month == p_obj.period_month,
                        Payslip.period_year == p_obj.period_year,
                    )
            except ValueError:
                pass

        month = filters.get("month")
        if month:
            stmt = stmt.where(Payslip.period_month == int(month))

        emp_id = filters.get("employeeId")
        if emp_id:
            try:
                stmt = stmt.where(Payslip.employee_id == uuid.UUID(str(emp_id)))
            except ValueError:
                pass

        department = filters.get("department")
        if department:
            stmt = stmt.where(Employee.department == department)

        designation = filters.get("designation")
        if designation:
            stmt = stmt.where(Employee.designation == designation)

        payment_status = filters.get("paymentStatus")
        if payment_status:
            stmt = stmt.where(Payslip.payment_status == payment_status.upper())

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await session.execute(count_stmt)).scalar() or 0

        offset = max(0, (page - 1) * limit)
        stmt = stmt.order_by(desc(Payslip.created_at)).offset(offset).limit(limit)

        records = (await session.execute(stmt)).all()
        rows = []
        for ps, emp in records:
            name = f"{emp.first_name} {emp.last_name}".strip()
            row = {
                "payslip_id": str(ps.id),
                "employee_id": emp.employee_id,
                "name": name,
                "department": emp.department,
                "designation": emp.designation,
                "period": f"{ps.period_month:02d}/{ps.period_year}",
                "gross_earnings": float(ps.gross_earnings),
                "total_deductions": float(ps.total_deductions),
                "net_pay": float(ps.net_pay),
                "payment_status": ps.payment_status,
                "basic": float(ps.basic),
                "hra": float(ps.hra),
                "pf": float(ps.employee_pf),
                "esi": float(ps.employee_esi),
                "pt": float(ps.professional_tax),
                "tds": float(ps.tds),
            }
            rows.append(row)

        return {
            "report_key": report_key,
            "total_records": total,
            "data": rows,
        }

    @classmethod
    async def generate_export(
        cls,
        session: AsyncSession,
        export_id: uuid.UUID,
        report_key: str,
        file_format: str,
        filters: dict[str, Any],
    ) -> PayrollReportExport:
        stmt = select(PayrollReportExport).where(PayrollReportExport.id == export_id)
        export_rec = (await session.execute(stmt)).scalar_one_or_none()
        if not export_rec:
            export_rec = PayrollReportExport(
                id=export_id,
                report_key=report_key,
                file_format=file_format,
                file_name=f"{report_key}_{export_id.hex[:6]}.{file_format}",
                status="PROCESSING",
                filters=filters,
            )
            session.add(export_rec)
            await session.commit()

        # Fetch data
        data_res = await cls.get_report_data(
            session, report_key, filters, page=1, limit=10000
        )
        rows = data_res["data"]

        output = io.StringIO()
        if rows:
            headers = list(rows[0].keys())
            writer = csv.DictWriter(output, fieldnames=headers)
            writer.writeheader()
            for r in rows:
                writer.writerow(r)
        else:
            output.write("No data available for the given filters.\n")

        export_rec.file_content = output.getvalue()
        export_rec.status = "COMPLETED"
        await session.commit()
        await session.refresh(export_rec)
        return export_rec

    @classmethod
    async def get_export_download(
        cls, session: AsyncSession, export_id: uuid.UUID
    ) -> tuple[bytes, str]:
        stmt = select(PayrollReportExport).where(PayrollReportExport.id == export_id)
        export_rec = (await session.execute(stmt)).scalar_one_or_none()
        if not export_rec:
            raise HTTPException(status_code=404, detail="Export not found.")

        content = export_rec.file_content or "No content"
        return content.encode("utf-8"), export_rec.file_name
