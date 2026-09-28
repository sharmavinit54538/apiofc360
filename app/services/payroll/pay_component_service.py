"""Service for Pay Components catalogue and safe formula validation."""

from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import List, Optional
from fastapi import HTTPException, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payroll_models import PayComponent
from app.schemas.payroll_v2.pay_components import PayComponentCreateRequest
from app.services.payroll.formula_evaluator import SafeFormulaEvaluator

logger = logging.getLogger(__name__)


class PayComponentService:
    """Business logic for Pay Component definitions."""

    @classmethod
    async def list_components(
        cls, session: AsyncSession, company_id: Optional[uuid.UUID] = None
    ) -> List[PayComponent]:
        stmt = select(PayComponent).where(PayComponent.is_active == True)
        if company_id:
            stmt = stmt.where(PayComponent.company_id == company_id)
        stmt = stmt.order_by(desc(PayComponent.created_at))
        return list((await session.execute(stmt)).scalars().all())

    @classmethod
    async def create_component(
        cls,
        session: AsyncSession,
        payload: PayComponentCreateRequest,
        company_id: Optional[uuid.UUID] = None,
    ) -> PayComponent:
        # Check formula validity if calculation_method == 'formula'
        if payload.calculation_method == "formula":
            if not payload.formula_expr or not payload.formula_expr.strip():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="formulaExpr is required when calculationMethod is 'formula'.",
                )
            is_valid, err_msg = SafeFormulaEvaluator.validate_formula(payload.formula_expr)
            if not is_valid:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid formula expression: {err_msg}",
                )

        component = PayComponent(
            id=uuid.uuid4(),
            company_id=company_id,
            code=payload.code.upper(),
            name=payload.name,
            type=payload.type,
            taxable=payload.taxable,
            statutory=payload.statutory,
            calculation_method=payload.calculation_method,
            default_percentage=payload.default_percentage,
            formula_expr=payload.formula_expr,
            description=payload.description,
            effective_date=payload.effective_date or date.today(),
            is_active=True,
        )
        session.add(component)
        await session.commit()
        await session.refresh(component)
        return component
