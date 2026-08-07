"""Service layer for Allowance Management System."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.allowance import Allowance, AllowanceHistory, AllowanceAuditLog


class AllowanceService:
    @staticmethod
    async def list_allowances(db: AsyncSession, category_filter: Optional[str] = None) -> List[Allowance]:
        """Fetch all allowances ordered by display order."""
        stmt = select(Allowance)
        if category_filter and category_filter != "ALL":
            stmt = stmt.where(Allowance.category == category_filter.upper())
        stmt = stmt.order_by(Allowance.display_order.asc(), Allowance.created_at.asc())

        res = await db.execute(stmt)
        allowances = res.scalars().all()

        if not allowances:
            # Seed default predefined allowances
            defaults = [
                Allowance(
                    name="House Rent Allowance (HRA)",
                    display_name="HRA",
                    code="ALLOWANCE_HRA",
                    category="HRA",
                    description="Exempt housing allowance under Section 10(13A)",
                    calc_type="PERCENTAGE_BASIC",
                    formula_expr="BASIC * 0.50",
                    default_amount=Decimal("15000.00"),
                    taxability_type="PARTIALLY_TAXABLE",
                    exemption_limit_annual=Decimal("180000.00"),
                    pf_applicable=False,
                    esi_applicable=True,
                    pt_applicable=True,
                    included_in_ctc=True,
                    included_in_gross=True,
                    appears_on_payslip=True,
                    is_mandatory=True,
                    is_active=True,
                    display_order=1
                ),
                Allowance(
                    name="Conveyance Allowance",
                    display_name="Conveyance",
                    code="ALLOWANCE_CONVEYANCE",
                    category="CONVEYANCE",
                    description="Monthly commute allowance",
                    calc_type="FIXED",
                    default_amount=Decimal("1600.00"),
                    taxability_type="TAXABLE",
                    pf_applicable=False,
                    esi_applicable=True,
                    pt_applicable=True,
                    included_in_ctc=True,
                    included_in_gross=True,
                    appears_on_payslip=True,
                    is_mandatory=False,
                    is_active=True,
                    display_order=2
                ),
                Allowance(
                    name="Medical Reimbursement",
                    display_name="Medical",
                    code="ALLOWANCE_MEDICAL",
                    category="MEDICAL",
                    description="Medical expense reimbursement up to ₹15,000 / year",
                    calc_type="FIXED",
                    default_amount=Decimal("1250.00"),
                    taxability_type="PARTIALLY_TAXABLE",
                    exemption_limit_monthly=Decimal("1250.00"),
                    exemption_limit_annual=Decimal("15000.00"),
                    pf_applicable=False,
                    esi_applicable=False,
                    pt_applicable=True,
                    included_in_ctc=True,
                    included_in_gross=True,
                    appears_on_payslip=True,
                    is_mandatory=False,
                    is_active=True,
                    display_order=3
                ),
                Allowance(
                    name="Leave Travel Allowance (LTA)",
                    display_name="LTA",
                    code="ALLOWANCE_LTA",
                    category="TRAVEL",
                    description="Exempt travel allowance for 2 journeys in a 4-year block",
                    calc_type="FIXED",
                    default_amount=Decimal("5000.00"),
                    taxability_type="PARTIALLY_TAXABLE",
                    exemption_limit_annual=Decimal("60000.00"),
                    pf_applicable=False,
                    esi_applicable=False,
                    pt_applicable=True,
                    included_in_ctc=True,
                    included_in_gross=True,
                    appears_on_payslip=True,
                    is_mandatory=False,
                    is_active=True,
                    display_order=4
                ),
                Allowance(
                    name="Food & Meal Allowance",
                    display_name="Food Coupon",
                    code="ALLOWANCE_FOOD",
                    category="FOOD",
                    description="Tax-free meal coupons (₹50/meal, 22 working days)",
                    calc_type="FIXED",
                    default_amount=Decimal("2200.00"),
                    taxability_type="NON_TAXABLE",
                    exemption_limit_monthly=Decimal("2200.00"),
                    pf_applicable=False,
                    esi_applicable=False,
                    pt_applicable=False,
                    included_in_ctc=True,
                    included_in_gross=True,
                    appears_on_payslip=True,
                    is_mandatory=False,
                    is_active=True,
                    display_order=5
                ),
                Allowance(
                    name="Internet & Telephone Reimbursement",
                    display_name="Internet Allowance",
                    code="ALLOWANCE_INTERNET",
                    category="INTERNET",
                    description="Reimbursement against submitted bills for remote work",
                    calc_type="FIXED",
                    default_amount=Decimal("2000.00"),
                    taxability_type="NON_TAXABLE",
                    exemption_limit_monthly=Decimal("2000.00"),
                    pf_applicable=False,
                    esi_applicable=False,
                    pt_applicable=False,
                    included_in_ctc=True,
                    included_in_gross=True,
                    appears_on_payslip=True,
                    is_mandatory=False,
                    is_active=True,
                    display_order=6
                ),
                Allowance(
                    name="Night Shift Differential Allowance",
                    display_name="Shift Allowance",
                    code="ALLOWANCE_SHIFT",
                    category="SHIFT",
                    description="Per-shift premium for night rotation rosters",
                    calc_type="ATTENDANCE_BASED",
                    default_amount=Decimal("3500.00"),
                    taxability_type="TAXABLE",
                    pf_applicable=False,
                    esi_applicable=True,
                    pt_applicable=True,
                    included_in_ctc=True,
                    included_in_gross=True,
                    appears_on_payslip=True,
                    is_mandatory=False,
                    is_active=True,
                    display_order=7
                ),
            ]

            for item in defaults:
                db.add(item)
            await db.commit()

            res = await db.execute(stmt)
            allowances = res.scalars().all()

        return list(allowances)

    @staticmethod
    async def get_allowance_by_id(db: AsyncSession, allowance_id: uuid.UUID) -> Optional[Allowance]:
        """Fetch single allowance by ID."""
        stmt = select(Allowance).where(Allowance.id == allowance_id)
        res = await db.execute(stmt)
        return res.scalars().first()

    @staticmethod
    async def create_allowance(
        db: AsyncSession,
        data: Dict[str, Any],
        actor_email: Optional[str] = None,
        ip_address: Optional[str] = None,
        browser: Optional[str] = None
    ) -> Allowance:
        """Create new allowance definition and log audit entry."""
        code = data.get("code", "").strip().upper()
        existing = await db.execute(select(Allowance).where(Allowance.code == code))
        if existing.scalars().first():
            raise ValueError(f"Allowance code '{code}' already exists")

        new_item = Allowance(
            name=data.get("name", "New Allowance"),
            display_name=data.get("display_name") or data.get("name"),
            code=code,
            description=data.get("description", ""),
            category=data.get("category", "SPECIAL"),
            earning_type=data.get("earning_type", "FIXED"),
            is_variable=bool(data.get("is_variable", False)),
            frequency=data.get("frequency", "MONTHLY"),
            is_recurring=bool(data.get("is_recurring", True)),
            calc_type=data.get("calc_type", "FIXED"),
            formula_expr=data.get("formula_expr"),
            default_amount=Decimal(str(data.get("default_amount", 0.0))),
            min_limit=Decimal(str(data.get("min_limit", 0.0))),
            max_limit=Decimal(str(data.get("max_limit", 0.0))),
            currency=data.get("currency", "INR"),
            taxability_type=data.get("taxability_type", "TAXABLE"),
            exemption_limit_monthly=Decimal(str(data.get("exemption_limit_monthly", 0.0))),
            exemption_limit_annual=Decimal(str(data.get("exemption_limit_annual", 0.0))),
            pf_applicable=bool(data.get("pf_applicable", False)),
            esi_applicable=bool(data.get("esi_applicable", True)),
            pt_applicable=bool(data.get("pt_applicable", True)),
            lwf_applicable=bool(data.get("lwf_applicable", False)),
            included_in_ctc=bool(data.get("included_in_ctc", True)),
            included_in_gross=bool(data.get("included_in_gross", True)),
            included_in_net=bool(data.get("included_in_net", True)),
            appears_on_payslip=bool(data.get("appears_on_payslip", True)),
            is_mandatory=bool(data.get("is_mandatory", False)),
            is_active=bool(data.get("is_active", True)),
            display_order=int(data.get("display_order", 1))
        )

        db.add(new_item)
        await db.flush()

        audit_entry = AllowanceAuditLog(
            allowance_id=new_item.id,
            action="CREATED",
            actor=actor_email or "System Admin",
            previous_value=None,
            updated_value=new_item.code,
            ip_address=ip_address or "127.0.0.1",
            browser=browser or "Dashboard Web",
            reason="Created new allowance definition"
        )
        db.add(audit_entry)

        await db.commit()
        await db.refresh(new_item)
        return new_item

    @staticmethod
    async def update_allowance(
        db: AsyncSession,
        allowance_id: uuid.UUID,
        payload: Dict[str, Any],
        actor_email: Optional[str] = None,
        ip_address: Optional[str] = None,
        browser: Optional[str] = None
    ) -> Optional[Allowance]:
        """Update allowance definition with audit log."""
        item = await AllowanceService.get_allowance_by_id(db, allowance_id)
        if not item:
            return None

        for key, val in payload.items():
            if hasattr(item, key) and val is not None:
                if key in ("default_amount", "min_limit", "max_limit", "exemption_limit_monthly", "exemption_limit_annual"):
                    setattr(item, key, Decimal(str(val)))
                else:
                    setattr(item, key, val)

        item.updated_at = datetime.utcnow()
        db.add(item)

        audit_entry = AllowanceAuditLog(
            allowance_id=item.id,
            action="UPDATED",
            actor=actor_email or "System Admin",
            previous_value="Previous config",
            updated_value="Updated config",
            ip_address=ip_address or "127.0.0.1",
            browser=browser or "Dashboard Web",
            reason="Updated allowance rule settings"
        )
        db.add(audit_entry)

        await db.commit()
        await db.refresh(item)
        return item

    @staticmethod
    async def toggle_active(db: AsyncSession, allowance_id: uuid.UUID, active_state: bool) -> Optional[Allowance]:
        """Activate or deactivate allowance."""
        item = await AllowanceService.get_allowance_by_id(db, allowance_id)
        if not item:
            return None

        item.is_active = active_state
        item.updated_at = datetime.utcnow()
        db.add(item)
        await db.commit()
        await db.refresh(item)
        return item

    @staticmethod
    async def duplicate_allowance(db: AsyncSession, allowance_id: uuid.UUID) -> Optional[Allowance]:
        """Duplicate an allowance definition."""
        existing = await AllowanceService.get_allowance_by_id(db, allowance_id)
        if not existing:
            return None

        dup = Allowance(
            name=f"{existing.name} (Copy)",
            display_name=existing.display_name,
            code=f"{existing.code}_COPY",
            category=existing.category,
            description=existing.description,
            earning_type=existing.earning_type,
            calc_type=existing.calc_type,
            formula_expr=existing.formula_expr,
            default_amount=existing.default_amount,
            taxability_type=existing.taxability_type,
            exemption_limit_monthly=existing.exemption_limit_monthly,
            exemption_limit_annual=existing.exemption_limit_annual,
            pf_applicable=existing.pf_applicable,
            esi_applicable=existing.esi_applicable,
            pt_applicable=existing.pt_applicable,
            included_in_ctc=existing.included_in_ctc,
            appears_on_payslip=existing.appears_on_payslip,
            is_mandatory=False,
            is_active=True,
            display_order=existing.display_order + 1
        )

        db.add(dup)
        await db.commit()
        await db.refresh(dup)
        return dup

    @staticmethod
    async def delete_allowance(db: AsyncSession, allowance_id: uuid.UUID) -> bool:
        """Delete custom allowance."""
        item = await AllowanceService.get_allowance_by_id(db, allowance_id)
        if not item:
            return False
        if item.is_mandatory:
            raise ValueError("Mandatory statutory allowances (such as HRA) cannot be deleted.")

        await db.delete(item)
        await db.commit()
        return True

    @staticmethod
    async def get_audit_logs(db: AsyncSession) -> List[Dict[str, Any]]:
        """Retrieve audit log entries for allowance changes."""
        stmt = select(AllowanceAuditLog).order_by(AllowanceAuditLog.created_at.desc()).limit(100)
        res = await db.execute(stmt)
        logs = res.scalars().all()
        return [
            {
                "id": str(l.id),
                "allowance_id": str(l.allowance_id) if l.allowance_id else None,
                "action": l.action,
                "actor": l.actor or "System Admin",
                "previous_value": l.previous_value or "None",
                "updated_value": l.updated_value or "Updated",
                "ip_address": l.ip_address or "127.0.0.1",
                "browser": l.browser or "Dashboard Web",
                "reason": l.reason or "Allowance operation",
                "timestamp": l.created_at.isoformat() if l.created_at else ""
            }
            for l in logs
        ]
