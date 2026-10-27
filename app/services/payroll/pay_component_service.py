"""Service for Pay Components catalogue, default Indian component templates, and safe formula validation."""

from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Any, List, Optional
from decimal import Decimal
from fastapi import HTTPException, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payroll_models import PayComponent
from app.schemas.payroll_v2.pay_components import PayComponentCreateRequest
from app.services.payroll.formula_evaluator import SafeFormulaEvaluator

logger = logging.getLogger(__name__)

DEFAULT_INDIAN_COMPONENTS = [
    {
        "code": "BASIC",
        "name": "Basic Salary",
        "type": "earning",
        "taxable": True,
        "statutory": False,
        "calculation_method": "percentage_of_ctc",
        "default_percentage": Decimal("0.50"),
        "formula_expr": None,
        "description": "Fundamental taxable wage component (50% of monthly CTC as per Indian Wage Code guidelines)",
    },
    {
        "code": "HRA",
        "name": "House Rent Allowance",
        "type": "earning",
        "taxable": True,
        "statutory": False,
        "calculation_method": "percentage_of_basic",
        "default_percentage": Decimal("0.40"),
        "formula_expr": "basic * 0.40",
        "description": "Housing allowance eligible for Section 10(13A) exemption under Old Tax Regime",
    },
    {
        "code": "SPECIAL_ALLOWANCE",
        "name": "Special Allowance",
        "type": "earning",
        "taxable": True,
        "statutory": False,
        "calculation_method": "formula",
        "default_percentage": None,
        "formula_expr": "max(0, (ctc / 12) - (basic + hra))",
        "description": "Balancing monthly taxable allowance to bridge total CTC",
    },
    {
        "code": "CONVEYANCE",
        "name": "Conveyance Allowance",
        "type": "earning",
        "taxable": True,
        "statutory": False,
        "calculation_method": "flat",
        "default_percentage": None,
        "formula_expr": None,
        "description": "Fixed transport and commute assistance",
    },
    {
        "code": "MEDICAL",
        "name": "Medical Allowance",
        "type": "earning",
        "taxable": True,
        "statutory": False,
        "calculation_method": "flat",
        "default_percentage": None,
        "formula_expr": None,
        "description": "Health and wellness monthly allowance",
    },
    {
        "code": "BONUS",
        "name": "Performance Bonus",
        "type": "earning",
        "taxable": True,
        "statutory": False,
        "calculation_method": "flat",
        "default_percentage": None,
        "formula_expr": None,
        "description": "Variable incentive or statutory bonus",
    },
    {
        "code": "PF_EMPLOYEE",
        "name": "Provident Fund (Employee)",
        "type": "deduction",
        "taxable": False,
        "statutory": True,
        "calculation_method": "formula",
        "default_percentage": Decimal("0.12"),
        "formula_expr": "min(basic, 15000) * 0.12",
        "description": "Mandatory EPFO employee contribution under EPF & MP Act 1952",
    },
    {
        "code": "ESI_EMPLOYEE",
        "name": "Employee State Insurance (Employee)",
        "type": "deduction",
        "taxable": False,
        "statutory": True,
        "calculation_method": "formula",
        "default_percentage": Decimal("0.0075"),
        "formula_expr": "round(gross * 0.0075)",
        "description": "ESIC employee contribution applicable for gross wages <= ₹21,000",
    },
    {
        "code": "PT",
        "name": "Professional Tax",
        "type": "deduction",
        "taxable": False,
        "statutory": True,
        "calculation_method": "flat",
        "default_percentage": None,
        "formula_expr": None,
        "description": "State-level profession tax deduction (e.g. Maharashtra ₹200/₹300)",
    },
    {
        "code": "LWF",
        "name": "Labour Welfare Fund (Employee)",
        "type": "deduction",
        "taxable": False,
        "statutory": True,
        "calculation_method": "flat",
        "default_percentage": None,
        "formula_expr": None,
        "description": "State labour board welfare contribution",
    },
    {
        "code": "TDS",
        "name": "Income Tax (TDS)",
        "type": "deduction",
        "taxable": False,
        "statutory": True,
        "calculation_method": "flat",
        "default_percentage": None,
        "formula_expr": None,
        "description": "Withholding tax deducted at source under Section 192",
    },
    {
        "code": "LOAN_RECOVERY",
        "name": "Salary Advance / Loan Recovery",
        "type": "deduction",
        "taxable": False,
        "statutory": False,
        "calculation_method": "flat",
        "default_percentage": None,
        "formula_expr": None,
        "description": "Monthly EMI recovery for company advances and loans",
    },
]


class PayComponentService:
    """Business logic for Pay Component definitions."""

    @classmethod
    async def list_components(
        cls, session: AsyncSession, company_id: Optional[uuid.UUID] = None
    ) -> List[PayComponent]:
        stmt = select(PayComponent).where(PayComponent.is_active == True)
        if company_id:
            stmt = stmt.where(
                (PayComponent.company_id == company_id) | (PayComponent.company_id.is_(None))
            )
        stmt = stmt.order_by(desc(PayComponent.created_at))
        components = list((await session.execute(stmt)).scalars().all())

        # If empty, seed standard default Indian components
        if not components:
            components = await cls.seed_default_indian_components(session, company_id=company_id)

        return components

    @classmethod
    async def get_component(
        cls, session: AsyncSession, component_id: uuid.UUID
    ) -> PayComponent:
        stmt = select(PayComponent).where(PayComponent.id == component_id)
        comp = (await session.execute(stmt)).scalar_one_or_none()
        if not comp:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Pay component '{component_id}' not found.",
            )
        return comp

    @classmethod
    async def create_component(
        cls,
        session: AsyncSession,
        payload: PayComponentCreateRequest,
        company_id: Optional[uuid.UUID] = None,
    ) -> PayComponent:
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

    @classmethod
    async def update_component(
        cls,
        session: AsyncSession,
        component_id: uuid.UUID,
        payload: dict[str, Any],
    ) -> PayComponent:
        comp = await cls.get_component(session, component_id)

        if "formula_expr" in payload and payload.get("calculation_method") == "formula":
            expr = payload.get("formula_expr") or ""
            is_valid, err_msg = SafeFormulaEvaluator.validate_formula(expr)
            if not is_valid:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid formula expression: {err_msg}",
                )

        for key, value in payload.items():
            if hasattr(comp, key) and value is not None:
                setattr(comp, key, value)

        await session.commit()
        await session.refresh(comp)
        return comp

    @classmethod
    async def delete_component(
        cls, session: AsyncSession, component_id: uuid.UUID
    ) -> dict[str, str]:
        comp = await cls.get_component(session, component_id)
        comp.is_active = False
        await session.commit()
        return {"message": f"Component {comp.code} deactivated successfully."}

    @classmethod
    async def seed_default_indian_components(
        cls, session: AsyncSession, company_id: Optional[uuid.UUID] = None
    ) -> List[PayComponent]:
        created: List[PayComponent] = []
        for item in DEFAULT_INDIAN_COMPONENTS:
            # Check if exists
            stmt = select(PayComponent).where(
                PayComponent.code == item["code"],
                (PayComponent.company_id == company_id) | (PayComponent.company_id.is_(None)),
            )
            existing = (await session.execute(stmt)).scalar_one_or_none()
            if not existing:
                comp = PayComponent(
                    id=uuid.uuid4(),
                    company_id=company_id,
                    code=item["code"],
                    name=item["name"],
                    type=item["type"],
                    taxable=item["taxable"],
                    statutory=item["statutory"],
                    calculation_method=item["calculation_method"],
                    default_percentage=item["default_percentage"],
                    formula_expr=item["formula_expr"],
                    description=item["description"],
                    effective_date=date.today(),
                    is_active=True,
                )
                session.add(comp)
                created.append(comp)

        if created:
            await session.commit()
            for c in created:
                await session.refresh(c)

        # Return full list
        return await cls.list_components(session, company_id=company_id)
