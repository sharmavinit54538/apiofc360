"""Service for Variable Inputs (bonuses, overtime, LOP, reimbursements)."""

from __future__ import annotations

import csv
import io
import json
import logging
import uuid
from datetime import datetime
from typing import Any, List, Optional

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis_client import redis_client
from app.models.employee import Employee
from app.models.payroll_models import PayrollPeriod, VariableInput
from app.schemas.payroll_v2.variable_inputs import VariableInputCreateRequest
from app.services.payroll.audit_service import PayrollAuditService

logger = logging.getLogger(__name__)


class VariableInputService:
    """Business logic for variable compensation inputs."""

    PREVIEW_PREFIX = "payroll:var_preview:"

    @classmethod
    async def get_input(cls, session: AsyncSession, input_id: uuid.UUID) -> VariableInput:
        stmt = select(VariableInput).where(VariableInput.id == input_id)
        res = await session.execute(stmt)
        item = res.scalar_one_or_none()
        if not item:
            raise HTTPException(status_code=404, detail=f"Variable input '{input_id}' not found.")
        return item

    @classmethod
    async def list_inputs(
        cls,
        session: AsyncSession,
        period_id: Optional[str] = None,
        type_filter: Optional[str] = None,
        status_filter: Optional[str] = None,
        search: Optional[str] = None,
        page: int = 1,
        limit: int = 20,
        company_id: Optional[uuid.UUID] = None,
    ) -> dict[str, Any]:
        stmt = (
            select(VariableInput)
            .join(Employee, VariableInput.employee_id == Employee.id)
        )
        if company_id:
            stmt = stmt.where(VariableInput.company_id == company_id)
        if period_id:
            try:
                p_uuid = uuid.UUID(period_id)
                stmt = stmt.where(VariableInput.period_id == p_uuid)
            except ValueError:
                pass
        if type_filter:
            stmt = stmt.where(VariableInput.type == type_filter.lower())
        if status_filter:
            stmt = stmt.where(VariableInput.status == status_filter.upper())
        if search:
            stmt = stmt.where(
                or_(
                    VariableInput.description.ilike(f"%{search}%"),
                    Employee.first_name.ilike(f"%{search}%"),
                    Employee.last_name.ilike(f"%{search}%"),
                )
            )

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await session.execute(count_stmt)).scalar() or 0

        offset = max(0, (page - 1) * limit)
        stmt = stmt.order_by(desc(VariableInput.created_at)).offset(offset).limit(limit)
        items = (await session.execute(stmt)).scalars().all()

        return {
            "items": items,
            "total": total,
            "page": page,
            "limit": limit,
        }

    @classmethod
    async def create_input(
        cls,
        session: AsyncSession,
        payload: VariableInputCreateRequest,
        company_id: Optional[uuid.UUID] = None,
        user_id: Optional[uuid.UUID] = None,
    ) -> VariableInput:
        emp_id = uuid.UUID(payload.employee_id)
        p_id = uuid.UUID(payload.period_id)

        # Validate employee & period exist
        emp_exists = (
            await session.execute(select(Employee).where(Employee.id == emp_id))
        ).scalar_one_or_none()
        if not emp_exists:
            raise HTTPException(status_code=404, detail="Employee not found.")

        target_company_id = company_id or emp_exists.company_id

        var_input = VariableInput(
            id=uuid.uuid4(),
            employee_id=emp_id,
            period_id=p_id,
            company_id=target_company_id,
            type=payload.type,
            amount_paise=payload.amount_paise,
            units=payload.units,
            rate_per_unit_paise=payload.rate_per_unit_paise,
            description=payload.description,
            status="PENDING",
        )
        session.add(var_input)
        await session.commit()
        await session.refresh(var_input)

        await PayrollAuditService.log_event(
            session=session,
            entity_type="VariableInput",
            entity_id=var_input.id,
            action="CREATE",
            company_id=target_company_id,
            actor_id=user_id,
            before_status=None,
            after_status="PENDING",
            reason=f"Created {payload.type} variable input",
        )
        return var_input

    @classmethod
    async def approve_input(
        cls,
        session: AsyncSession,
        input_id: uuid.UUID,
        remarks: Optional[str] = None,
        user_id: Optional[uuid.UUID] = None,
        user_role: Optional[str] = None,
    ) -> VariableInput:
        item = await cls.get_input(session, input_id)
        old_status = item.status
        item.status = "APPROVED"
        item.approved_by = user_id
        item.approved_at = datetime.now()
        item.remarks = remarks

        await PayrollAuditService.log_event(
            session=session,
            entity_type="VariableInput",
            entity_id=item.id,
            action="APPROVE",
            company_id=item.company_id,
            actor_id=user_id,
            actor_role=user_role,
            before_status=old_status,
            after_status="APPROVED",
            reason=remarks or "Approved variable input",
        )
        await session.commit()
        await session.refresh(item)
        return item

    @classmethod
    async def reject_input(
        cls,
        session: AsyncSession,
        input_id: uuid.UUID,
        reason: str,
        user_id: Optional[uuid.UUID] = None,
        user_role: Optional[str] = None,
    ) -> VariableInput:
        item = await cls.get_input(session, input_id)
        old_status = item.status
        item.status = "REJECTED"
        item.rejected_by = user_id
        item.rejected_at = datetime.now()
        item.rejection_reason = reason

        await PayrollAuditService.log_event(
            session=session,
            entity_type="VariableInput",
            entity_id=item.id,
            action="REJECT",
            company_id=item.company_id,
            actor_id=user_id,
            actor_role=user_role,
            before_status=old_status,
            after_status="REJECTED",
            reason=reason,
        )
        await session.commit()
        await session.refresh(item)
        return item

    @classmethod
    async def preview_bulk_inputs(
        cls, session: AsyncSession, file: UploadFile, company_id: Optional[uuid.UUID] = None
    ) -> dict[str, Any]:
        content = await file.read()
        text_stream = io.StringIO(content.decode("utf-8-sig", errors="ignore"))
        reader = csv.DictReader(text_stream)

        rows = []
        valid_rows = []
        row_num = 1
        for r in reader:
            emp_id_str = r.get("employeeId") or r.get("employee_id") or ""
            period_id_str = r.get("periodId") or r.get("period_id") or ""
            type_str = r.get("type") or "bonus"
            amount_str = r.get("amountPaise") or r.get("amount") or "0"
            desc = r.get("description") or "Variable input"

            errors = []
            parsed_emp = None
            if not emp_id_str.strip():
                errors.append("Missing employeeId")
            else:
                try:
                    parsed_emp = uuid.UUID(emp_id_str.strip())
                except ValueError:
                    errors.append("Invalid employeeId UUID")

            parsed_period = None
            if not period_id_str.strip():
                errors.append("Missing periodId")
            else:
                try:
                    parsed_period = uuid.UUID(period_id_str.strip())
                except ValueError:
                    errors.append("Invalid periodId UUID")

            parsed_amount = 0
            try:
                parsed_amount = int(float(amount_str))
                if parsed_amount <= 0:
                    errors.append("Amount must be positive")
            except ValueError:
                errors.append("Invalid amount")

            is_valid = len(errors) == 0
            rows.append({
                "row_number": row_num,
                "is_valid": is_valid,
                "errors": errors,
            })
            if is_valid:
                valid_rows.append({
                    "employee_id": str(parsed_emp),
                    "period_id": str(parsed_period),
                    "type": type_str,
                    "amount_paise": parsed_amount,
                    "description": desc,
                })
            row_num += 1

        preview_token = f"var_tok_{uuid.uuid4().hex[:16]}"
        cache_data = {"company_id": str(company_id) if company_id else None, "rows": valid_rows}
        await redis_client.set(
            f"{cls.PREVIEW_PREFIX}{preview_token}", json.dumps(cache_data), ttl_seconds=1800
        )

        return {
            "previewToken": preview_token,
            "total_rows": len(rows),
            "valid_rows": len(valid_rows),
            "invalid_rows": len(rows) - len(valid_rows),
            "rows": rows,
        }

    @classmethod
    async def apply_bulk_inputs(
        cls, session: AsyncSession, preview_token: str, company_id: Optional[uuid.UUID] = None, user_id: Optional[uuid.UUID] = None
    ) -> dict[str, Any]:
        cached = await redis_client.get(f"{cls.PREVIEW_PREFIX}{preview_token}")
        if not cached:
            raise HTTPException(status_code=400, detail="Preview token has expired or is invalid.")

        data = json.loads(cached)
        valid_rows = data.get("rows", [])

        applied = 0
        for item in valid_rows:
            var_item = VariableInput(
                id=uuid.uuid4(),
                employee_id=uuid.UUID(item["employee_id"]),
                period_id=uuid.UUID(item["period_id"]),
                company_id=company_id,
                type=item["type"],
                amount_paise=item["amount_paise"],
                description=item["description"],
                status="APPROVED",
            )
            session.add(var_item)
            applied += 1

        await session.commit()
        await redis_client.delete(f"{cls.PREVIEW_PREFIX}{preview_token}")

        return {"message": f"Successfully applied {applied} variable inputs.", "applied_count": applied}
