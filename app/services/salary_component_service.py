"""Service and Calculation Engine for Salary Components."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.salary_component import SalaryComponent, SalaryComponentHistory, SalaryComponentAuditLog


class SalaryComponentService:
    @staticmethod
    async def list_components(db: AsyncSession, category_filter: Optional[str] = None) -> List[SalaryComponent]:
        """Fetch all salary components ordered by display order."""
        stmt = select(SalaryComponent)
        if category_filter and category_filter != "ALL":
            stmt = stmt.where(SalaryComponent.component_type == category_filter.upper())
        stmt = stmt.order_by(SalaryComponent.display_order.asc(), SalaryComponent.created_at.asc())

        res = await db.execute(stmt)
        components = res.scalars().all()

        if not components:
            # Seed default statutory components
            defaults = [
                SalaryComponent(
                    name="Basic Salary",
                    code="BASIC",
                    component_type="EARNING",
                    category="BASIC",
                    description="Primary base wage forming foundation for PF & Gratuity",
                    display_name="Basic Salary",
                    payroll_code="BASIC_01",
                    display_order=1,
                    calc_type="PERCENTAGE_CTC",
                    percentage_value=Decimal("0.50"),
                    is_system=True,
                    is_mandatory=True,
                    is_taxable=True,
                    pf_applicable=True,
                    esi_applicable=True,
                    pt_applicable=True,
                    included_in_ctc=True,
                    included_in_gross=True,
                    included_in_net=True,
                    appears_on_payslip=True,
                    is_active=True
                ),
                SalaryComponent(
                    name="House Rent Allowance (HRA)",
                    code="HRA",
                    component_type="EARNING",
                    category="HRA",
                    description="Allowance for employee housing rental expenses",
                    display_name="House Rent Allowance",
                    payroll_code="HRA_02",
                    display_order=2,
                    calc_type="PERCENTAGE_BASIC",
                    percentage_value=Decimal("0.50"),
                    is_system=True,
                    is_mandatory=True,
                    is_taxable=True,
                    pf_applicable=False,
                    esi_applicable=True,
                    pt_applicable=True,
                    included_in_ctc=True,
                    included_in_gross=True,
                    included_in_net=True,
                    appears_on_payslip=True,
                    is_active=True
                ),
                SalaryComponent(
                    name="Special Allowance",
                    code="SPECIAL_ALLOWANCE",
                    component_type="EARNING",
                    category="SPECIAL",
                    description="Flexible balancing allowance in CTC structure",
                    display_name="Special Allowance",
                    payroll_code="SA_03",
                    display_order=3,
                    calc_type="FORMULA",
                    formula_expr="CTC - (BASIC + HRA + CONVEYANCE)",
                    is_system=True,
                    is_mandatory=False,
                    is_taxable=True,
                    pf_applicable=False,
                    esi_applicable=True,
                    pt_applicable=True,
                    included_in_ctc=True,
                    included_in_gross=True,
                    included_in_net=True,
                    appears_on_payslip=True,
                    is_active=True
                ),
                SalaryComponent(
                    name="Conveyance Allowance",
                    code="CONVEYANCE",
                    component_type="EARNING",
                    category="CONVEYANCE",
                    description="Travel and commute allowance",
                    display_name="Conveyance Allowance",
                    payroll_code="CA_04",
                    display_order=4,
                    calc_type="FIXED",
                    fixed_amount=Decimal("1600.00"),
                    is_system=False,
                    is_mandatory=False,
                    is_taxable=True,
                    pf_applicable=False,
                    esi_applicable=False,
                    pt_applicable=True,
                    included_in_ctc=True,
                    included_in_gross=True,
                    included_in_net=True,
                    appears_on_payslip=True,
                    is_active=True
                ),
                SalaryComponent(
                    name="Employee Provident Fund (EPF)",
                    code="PF_EMP",
                    component_type="DEDUCTION",
                    category="PF",
                    description="Statutory EPF deduction (12% of Basic)",
                    display_name="Provident Fund (PF)",
                    payroll_code="PF_05",
                    display_order=5,
                    calc_type="PERCENTAGE_BASIC",
                    percentage_value=Decimal("0.12"),
                    is_system=True,
                    is_mandatory=True,
                    is_taxable=False,
                    pf_applicable=False,
                    esi_applicable=False,
                    pt_applicable=False,
                    included_in_ctc=False,
                    included_in_gross=False,
                    included_in_net=True,
                    appears_on_payslip=True,
                    is_active=True
                ),
                SalaryComponent(
                    name="Professional Tax (PT)",
                    code="PT",
                    component_type="DEDUCTION",
                    category="PT",
                    description="State statutory professional tax slab deduction",
                    display_name="Professional Tax",
                    payroll_code="PT_06",
                    display_order=6,
                    calc_type="WORKING_DAYS",
                    fixed_amount=Decimal("200.00"),
                    is_system=True,
                    is_mandatory=True,
                    is_taxable=False,
                    pf_applicable=False,
                    esi_applicable=False,
                    pt_applicable=False,
                    included_in_ctc=False,
                    included_in_gross=False,
                    included_in_net=True,
                    appears_on_payslip=True,
                    is_active=True
                ),
            ]

            for comp in defaults:
                db.add(comp)
            await db.commit()

            res = await db.execute(stmt)
            components = res.scalars().all()

        return list(components)

    @staticmethod
    async def get_component_by_id(db: AsyncSession, component_id: uuid.UUID) -> Optional[SalaryComponent]:
        """Fetch single component by ID."""
        stmt = select(SalaryComponent).where(SalaryComponent.id == component_id)
        res = await db.execute(stmt)
        return res.scalars().first()

    @staticmethod
    async def create_component(
        db: AsyncSession,
        data: Dict[str, Any],
        actor_email: Optional[str] = None,
        ip_address: Optional[str] = None,
        browser: Optional[str] = None
    ) -> SalaryComponent:
        """Create new component and record audit log."""
        code = data.get("code", "").strip().upper()
        # Check duplicate code
        existing = await db.execute(select(SalaryComponent).where(SalaryComponent.code == code))
        if existing.scalars().first():
            raise ValueError(f"Component code '{code}' already exists")

        new_comp = SalaryComponent(
            name=data.get("name", "New Salary Component"),
            code=code,
            component_type=data.get("component_type", "EARNING"),
            category=data.get("category", "BASIC"),
            description=data.get("description", ""),
            display_name=data.get("display_name") or data.get("name"),
            payroll_code=data.get("payroll_code"),
            display_order=data.get("display_order", 1),
            calc_type=data.get("calc_type", "FIXED"),
            formula_expr=data.get("formula_expr"),
            fixed_amount=Decimal(str(data.get("fixed_amount", 0.0))),
            percentage_value=Decimal(str(data.get("percentage_value", 0.0))),
            is_system=False,
            is_mandatory=bool(data.get("is_mandatory", False)),
            is_taxable=bool(data.get("is_taxable", True)),
            pf_applicable=bool(data.get("pf_applicable", True)),
            esi_applicable=bool(data.get("esi_applicable", True)),
            pt_applicable=bool(data.get("pt_applicable", True)),
            included_in_ctc=bool(data.get("included_in_ctc", True)),
            included_in_gross=bool(data.get("included_in_gross", True)),
            included_in_net=bool(data.get("included_in_net", True)),
            appears_on_payslip=bool(data.get("appears_on_payslip", True)),
            is_active=bool(data.get("is_active", True)),
        )

        db.add(new_comp)
        await db.flush()

        audit_entry = SalaryComponentAuditLog(
            component_id=new_comp.id,
            action="CREATED",
            actor=actor_email or "System Admin",
            previous_value=None,
            updated_value=new_comp.code,
            ip_address=ip_address or "127.0.0.1",
            browser=browser or "Dashboard Web",
            reason="Created new salary component"
        )
        db.add(audit_entry)

        await db.commit()
        await db.refresh(new_comp)
        return new_comp

    @staticmethod
    async def update_component(
        db: AsyncSession,
        component_id: uuid.UUID,
        payload: Dict[str, Any],
        actor_email: Optional[str] = None,
        ip_address: Optional[str] = None,
        browser: Optional[str] = None
    ) -> Optional[SalaryComponent]:
        """Update component details with audit log."""
        comp = await SalaryComponentService.get_component_by_id(db, component_id)
        if not comp:
            return None

        for key, val in payload.items():
            if hasattr(comp, key) and val is not None:
                if key in ("fixed_amount", "percentage_value"):
                    setattr(comp, key, Decimal(str(val)))
                else:
                    setattr(comp, key, val)

        comp.updated_at = datetime.utcnow()
        db.add(comp)

        audit_entry = SalaryComponentAuditLog(
            component_id=comp.id,
            action="UPDATED",
            actor=actor_email or "System Admin",
            previous_value="Previous config",
            updated_value="Updated config",
            ip_address=ip_address or "127.0.0.1",
            browser=browser or "Dashboard Web",
            reason="Updated salary component configuration"
        )
        db.add(audit_entry)

        await db.commit()
        await db.refresh(comp)
        return comp

    @staticmethod
    async def toggle_active(db: AsyncSession, component_id: uuid.UUID, active_state: bool) -> Optional[SalaryComponent]:
        """Activate or deactivate salary component."""
        comp = await SalaryComponentService.get_component_by_id(db, component_id)
        if not comp:
            return None

        comp.is_active = active_state
        comp.updated_at = datetime.utcnow()
        db.add(comp)
        await db.commit()
        await db.refresh(comp)
        return comp

    @staticmethod
    async def duplicate_component(db: AsyncSession, component_id: uuid.UUID) -> Optional[SalaryComponent]:
        """Duplicate a salary component."""
        existing = await SalaryComponentService.get_component_by_id(db, component_id)
        if not existing:
            return None

        dup = SalaryComponent(
            name=f"{existing.name} (Copy)",
            code=f"{existing.code}_COPY",
            component_type=existing.component_type,
            category=existing.category,
            description=existing.description,
            display_name=existing.display_name,
            payroll_code=existing.payroll_code,
            display_order=existing.display_order + 1,
            calc_type=existing.calc_type,
            formula_expr=existing.formula_expr,
            fixed_amount=existing.fixed_amount,
            percentage_value=existing.percentage_value,
            is_system=False,
            is_mandatory=False,
            is_taxable=existing.is_taxable,
            pf_applicable=existing.pf_applicable,
            esi_applicable=existing.esi_applicable,
            pt_applicable=existing.pt_applicable,
            included_in_ctc=existing.included_in_ctc,
            included_in_gross=existing.included_in_gross,
            included_in_net=existing.included_in_net,
            appears_on_payslip=existing.appears_on_payslip,
            is_active=True
        )

        db.add(dup)
        await db.commit()
        await db.refresh(dup)
        return dup

    @staticmethod
    async def delete_component(db: AsyncSession, component_id: uuid.UUID) -> bool:
        """Delete custom component (system components protected)."""
        comp = await SalaryComponentService.get_component_by_id(db, component_id)
        if not comp:
            return False
        if comp.is_system:
            raise ValueError("System components cannot be deleted to preserve statutory compliance.")

        await db.delete(comp)
        await db.commit()
        return True

    @staticmethod
    async def get_audit_logs(db: AsyncSession) -> List[Dict[str, Any]]:
        """Retrieve audit log entries for component changes."""
        stmt = select(SalaryComponentAuditLog).order_by(SalaryComponentAuditLog.created_at.desc()).limit(100)
        res = await db.execute(stmt)
        logs = res.scalars().all()
        return [
            {
                "id": str(l.id),
                "component_id": str(l.component_id) if l.component_id else None,
                "action": l.action,
                "actor": l.actor or "System Admin",
                "previous_value": l.previous_value or "None",
                "updated_value": l.updated_value or "Updated",
                "ip_address": l.ip_address or "127.0.0.1",
                "browser": l.browser or "Dashboard Web",
                "reason": l.reason or "Salary component action",
                "timestamp": l.created_at.isoformat() if l.created_at else ""
            }
            for l in logs
        ]
