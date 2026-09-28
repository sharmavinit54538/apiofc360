"""Service for Employee Compensation, Salary Revisions, and Bulk Imports."""

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

from app.core.redis_client import redis_client
from app.models.employee import Employee
from app.models.payroll_models import Compensation, CompensationRevision
from app.services.payroll.audit_service import PayrollAuditService

logger = logging.getLogger(__name__)


class CompensationService:
    """Business logic for employee compensation packages and revisions."""

    PREVIEW_PREFIX = "payroll:comp_preview:"

    @classmethod
    async def list_compensations(
        cls,
        session: AsyncSession,
        company_id: Optional[uuid.UUID] = None,
        page: int = 1,
        limit: int = 20,
        department: Optional[str] = None,
        search: Optional[str] = None,
    ) -> dict[str, Any]:
        stmt = (
            select(Compensation)
            .join(Employee, Compensation.employee_id == Employee.id)
            .where(Compensation.status == "ACTIVE")
        )
        if company_id:
            stmt = stmt.where(Compensation.company_id == company_id)
        if department:
            stmt = stmt.where(Employee.department == department)
        if search:
            stmt = stmt.where(
                or_(
                    Employee.first_name.ilike(f"%{search}%"),
                    Employee.last_name.ilike(f"%{search}%"),
                    Employee.employee_id.ilike(f"%{search}%"),
                )
            )

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await session.execute(count_stmt)).scalar() or 0

        offset = max(0, (page - 1) * limit)
        stmt = stmt.order_by(desc(Compensation.created_at)).offset(offset).limit(limit)
        items = (await session.execute(stmt)).scalars().all()

        return {
            "items": items,
            "total": total,
            "page": page,
            "limit": limit,
        }

    @classmethod
    async def get_employee_compensation(
        cls, session: AsyncSession, employee_id: uuid.UUID
    ) -> Compensation:
        stmt = select(Compensation).where(
            Compensation.employee_id == employee_id,
            Compensation.status == "ACTIVE",
        )
        comp = (await session.execute(stmt)).scalar_one_or_none()
        if not comp:
            # Check if employee exists
            emp_stmt = select(Employee).where(Employee.id == employee_id)
            emp = (await session.execute(emp_stmt)).scalar_one_or_none()
            if not emp:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Employee '{employee_id}' not found.",
                )
            # Create default baseline compensation
            comp = Compensation(
                id=uuid.uuid4(),
                employee_id=employee_id,
                company_id=emp.company_id,
                ctc_annual_paise=600000 * 100,
                basic_monthly_paise=25000 * 100,
                hra_monthly_paise=10000 * 100,
                special_allowance_monthly_paise=15000 * 100,
                effective_date=date.today(),
                status="ACTIVE",
            )
            session.add(comp)
            await session.commit()
            await session.refresh(comp)
        return comp

    @classmethod
    async def create_compensation_revision(
        cls,
        session: AsyncSession,
        employee_id: uuid.UUID,
        new_ctc_annual_paise: int,
        effective_date: date,
        reason: str,
        notes: Optional[str] = None,
        user_id: Optional[uuid.UUID] = None,
    ) -> CompensationRevision:
        # Fetch current CTC
        curr_comp = await cls.get_employee_compensation(session, employee_id)
        current_ctc = curr_comp.ctc_annual_paise if curr_comp else 0

        revision = CompensationRevision(
            id=uuid.uuid4(),
            employee_id=employee_id,
            company_id=curr_comp.company_id if curr_comp else None,
            current_ctc_annual_paise=current_ctc,
            new_ctc_annual_paise=new_ctc_annual_paise,
            effective_date=effective_date,
            reason=reason,
            notes=notes,
            status="PENDING",
        )
        session.add(revision)
        await session.commit()
        await session.refresh(revision)

        await PayrollAuditService.log_event(
            session=session,
            entity_type="CompensationRevision",
            entity_id=revision.id,
            action="CREATE",
            company_id=revision.company_id,
            actor_id=user_id,
            before_status=None,
            after_status="PENDING",
            reason=reason,
        )
        return revision

    @classmethod
    async def approve_compensation_revision(
        cls,
        session: AsyncSession,
        revision_id: uuid.UUID,
        remarks: Optional[str] = None,
        user_id: Optional[uuid.UUID] = None,
        user_role: Optional[str] = None,
    ) -> CompensationRevision:
        stmt = select(CompensationRevision).where(CompensationRevision.id == revision_id)
        revision = (await session.execute(stmt)).scalar_one_or_none()
        if not revision:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Compensation revision '{revision_id}' not found.",
            )
        if revision.status != "PENDING":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Revision cannot be approved in '{revision.status}' state.",
            )

        old_status = revision.status
        revision.status = "APPROVED"
        revision.approved_by = user_id
        revision.approved_at = datetime.now()
        revision.remarks = remarks

        # Supersede existing active compensation
        curr_stmt = select(Compensation).where(
            Compensation.employee_id == revision.employee_id,
            Compensation.status == "ACTIVE",
        )
        curr = (await session.execute(curr_stmt)).scalar_one_or_none()
        if curr:
            curr.status = "SUPERSEDED"

        # Apply new active compensation
        basic_paise = int((revision.new_ctc_annual_paise // 12) * 0.5)
        hra_paise = int(basic_paise * 0.4)
        special_paise = max(0, (revision.new_ctc_annual_paise // 12) - (basic_paise + hra_paise))

        new_comp = Compensation(
            id=uuid.uuid4(),
            employee_id=revision.employee_id,
            company_id=revision.company_id,
            ctc_annual_paise=revision.new_ctc_annual_paise,
            basic_monthly_paise=basic_paise,
            hra_monthly_paise=hra_paise,
            special_allowance_monthly_paise=special_paise,
            effective_date=revision.effective_date,
            status="ACTIVE",
            remarks=remarks or f"Revision applied from request {revision.id}",
        )
        session.add(new_comp)

        await PayrollAuditService.log_event(
            session=session,
            entity_type="CompensationRevision",
            entity_id=revision.id,
            action="APPROVE",
            company_id=revision.company_id,
            actor_id=user_id,
            actor_role=user_role,
            before_status=old_status,
            after_status="APPROVED",
            reason=remarks or "Approved revision",
        )
        await session.commit()
        await session.refresh(revision)
        return revision

    @classmethod
    async def reject_compensation_revision(
        cls,
        session: AsyncSession,
        revision_id: uuid.UUID,
        reason: str,
        user_id: Optional[uuid.UUID] = None,
        user_role: Optional[str] = None,
    ) -> CompensationRevision:
        stmt = select(CompensationRevision).where(CompensationRevision.id == revision_id)
        revision = (await session.execute(stmt)).scalar_one_or_none()
        if not revision:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Compensation revision '{revision_id}' not found.",
            )
        if revision.status != "PENDING":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Revision cannot be rejected in '{revision.status}' state.",
            )

        old_status = revision.status
        revision.status = "REJECTED"
        revision.rejected_by = user_id
        revision.rejected_at = datetime.now()
        revision.rejection_reason = reason

        await PayrollAuditService.log_event(
            session=session,
            entity_type="CompensationRevision",
            entity_id=revision.id,
            action="REJECT",
            company_id=revision.company_id,
            actor_id=user_id,
            actor_role=user_role,
            before_status=old_status,
            after_status="REJECTED",
            reason=reason,
        )
        await session.commit()
        await session.refresh(revision)
        return revision

    @classmethod
    async def preview_bulk_import(
        cls, session: AsyncSession, file: UploadFile, company_id: Optional[uuid.UUID] = None
    ) -> dict[str, Any]:
        content = await file.read()
        text_stream = io.StringIO(content.decode("utf-8-sig", errors="ignore"))
        reader = csv.DictReader(text_stream)

        rows = []
        valid_rows = []
        row_num = 1
        for r in reader:
            emp_id_str = r.get("employeeId") or r.get("employee_id") or r.get("Employee ID") or ""
            ctc_str = r.get("ctcAnnualPaise") or r.get("ctc_annual_paise") or r.get("annual_ctc") or r.get("CTC") or ""

            errors = []
            parsed_emp_id = None
            if not emp_id_str.strip():
                errors.append("Missing employeeId")
            else:
                try:
                    parsed_emp_id = uuid.UUID(emp_id_str.strip())
                    emp_exists = (
                        await session.execute(select(Employee).where(Employee.id == parsed_emp_id))
                    ).scalar_one_or_none()
                    if not emp_exists:
                        errors.append(f"Employee '{emp_id_str}' does not exist")
                except ValueError:
                    errors.append(f"Invalid UUID for employeeId: '{emp_id_str}'")

            parsed_ctc = 0
            if not ctc_str.strip():
                errors.append("Missing CTC")
            else:
                try:
                    parsed_ctc = int(float(ctc_str.strip()))
                    if parsed_ctc <= 0:
                        errors.append("CTC must be greater than zero")
                except ValueError:
                    errors.append(f"Invalid integer CTC: '{ctc_str}'")

            is_valid = len(errors) == 0
            row_data = {
                "row_number": row_num,
                "employee_id": str(parsed_emp_id) if parsed_emp_id else emp_id_str,
                "ctc_annual_paise": parsed_ctc,
                "is_valid": is_valid,
                "errors": errors,
            }
            rows.append(row_data)
            if is_valid:
                valid_rows.append({
                    "employee_id": str(parsed_emp_id),
                    "ctc_annual_paise": parsed_ctc,
                })
            row_num += 1

        preview_token = f"tok_{uuid.uuid4().hex[:16]}"
        cache_data = {
            "company_id": str(company_id) if company_id else None,
            "valid_rows": valid_rows,
        }
        await redis_client.set(
            f"{cls.PREVIEW_PREFIX}{preview_token}",
            json.dumps(cache_data),
            ttl_seconds=1800,  # 30 mins TTL
        )

        return {
            "previewToken": preview_token,
            "total_rows": len(rows),
            "valid_rows": len(valid_rows),
            "invalid_rows": len(rows) - len(valid_rows),
            "rows": rows,
        }

    @classmethod
    async def apply_bulk_import(
        cls,
        session: AsyncSession,
        preview_token: str,
        company_id: Optional[uuid.UUID] = None,
        user_id: Optional[uuid.UUID] = None,
    ) -> dict[str, Any]:
        cached = await redis_client.get(f"{cls.PREVIEW_PREFIX}{preview_token}")
        if not cached:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Preview token has expired or is invalid. Please upload the file again to preview.",
            )

        data = json.loads(cached)
        valid_rows = data.get("valid_rows", [])

        applied_count = 0
        for item in valid_rows:
            emp_id = uuid.UUID(item["employee_id"])
            ctc_paise = int(item["ctc_annual_paise"])

            # Supersede current
            curr_stmt = select(Compensation).where(
                Compensation.employee_id == emp_id, Compensation.status == "ACTIVE"
            )
            curr = (await session.execute(curr_stmt)).scalar_one_or_none()
            if curr:
                curr.status = "SUPERSEDED"

            basic_paise = int((ctc_paise // 12) * 0.5)
            hra_paise = int(basic_paise * 0.4)
            special_paise = max(0, (ctc_paise // 12) - (basic_paise + hra_paise))

            new_comp = Compensation(
                id=uuid.uuid4(),
                employee_id=emp_id,
                company_id=company_id,
                ctc_annual_paise=ctc_paise,
                basic_monthly_paise=basic_paise,
                hra_monthly_paise=hra_paise,
                special_allowance_monthly_paise=special_paise,
                effective_date=date.today(),
                status="ACTIVE",
                remarks="Applied via bulk import",
            )
            session.add(new_comp)
            applied_count += 1

        await session.commit()
        # Invalidate token
        await redis_client.delete(f"{cls.PREVIEW_PREFIX}{preview_token}")

        return {
            "message": f"Successfully applied compensation for {applied_count} employees.",
            "applied_count": applied_count,
        }
