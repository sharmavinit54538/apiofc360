"""Service layer and calculation engine for Enterprise Tax Management System."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tax_setting import PayrollTaxSetting, PayrollTaxSlab, PayrollTaxHistory, PayrollTaxAuditLog


class TaxSettingService:
    @staticmethod
    async def list_tax_settings(db: AsyncSession, type_filter: Optional[str] = None) -> List[PayrollTaxSetting]:
        """Fetch all tax settings ordered by display order."""
        stmt = select(PayrollTaxSetting)
        if type_filter and type_filter != "ALL":
            stmt = stmt.where(PayrollTaxSetting.tax_type == type_filter.upper())
        stmt = stmt.order_by(PayrollTaxSetting.display_order.asc(), PayrollTaxSetting.created_at.asc())

        res = await db.execute(stmt)
        tax_settings = res.scalars().all()

        if not tax_settings:
            # Seed Indian Statutory Tax Rules for FY 2026-27
            new_regime = PayrollTaxSetting(
                tax_name="Income Tax (New Tax Regime - FY 2026-27)",
                tax_code="TAX_NEW_REGIME_FY26",
                tax_type="INCOME_TAX_NEW",
                description="Default simplified tax regime with standard deduction of ₹75,000",
                financial_year="2026-2027",
                country="IND",
                calc_type="PROGRESSIVE_SLAB",
                std_deduction=Decimal("75000.00"),
                is_active=True,
                display_order=1
            )
            db.add(new_regime)
            await db.flush()

            # Seed New Regime Slabs
            new_slabs = [
                PayrollTaxSlab(tax_setting_id=new_regime.id, min_income=Decimal("0.00"), max_income=Decimal("300000.00"), tax_rate=Decimal("0.00")),
                PayrollTaxSlab(tax_setting_id=new_regime.id, min_income=Decimal("300000.00"), max_income=Decimal("700000.00"), tax_rate=Decimal("0.05")),
                PayrollTaxSlab(tax_setting_id=new_regime.id, min_income=Decimal("700000.00"), max_income=Decimal("1000000.00"), tax_rate=Decimal("0.10")),
                PayrollTaxSlab(tax_setting_id=new_regime.id, min_income=Decimal("1000000.00"), max_income=Decimal("1200000.00"), tax_rate=Decimal("0.15")),
                PayrollTaxSlab(tax_setting_id=new_regime.id, min_income=Decimal("1200000.00"), max_income=Decimal("1500000.00"), tax_rate=Decimal("0.20")),
                PayrollTaxSlab(tax_setting_id=new_regime.id, min_income=Decimal("1500000.00"), max_income=None, tax_rate=Decimal("0.30")),
            ]
            for s in new_slabs:
                db.add(s)

            # Seed Provident Fund (EPF)
            epf = PayrollTaxSetting(
                tax_name="Provident Fund (EPF)",
                tax_code="TAX_PF_EPF",
                tax_type="PF_EPF",
                description="Statutory EPF deduction (12% employee / 12% employer)",
                financial_year="2026-2027",
                country="IND",
                calc_type="PERCENTAGE",
                employee_rate=Decimal("0.1200"),
                employer_rate=Decimal("0.1200"),
                wage_ceiling=Decimal("15000.00"),
                is_active=True,
                display_order=2
            )
            db.add(epf)

            # Seed ESI
            esi = PayrollTaxSetting(
                tax_name="Employee State Insurance (ESI)",
                tax_code="TAX_ESI_STATUTORY",
                tax_type="ESI",
                description="Statutory social security contribution (0.75% employee / 3.25% employer)",
                financial_year="2026-2027",
                country="IND",
                calc_type="PERCENTAGE",
                employee_rate=Decimal("0.0075"),
                employer_rate=Decimal("0.0325"),
                wage_ceiling=Decimal("21000.00"),
                is_active=True,
                display_order=3
            )
            db.add(esi)

            # Seed Professional Tax (PT Telangana)
            pt = PayrollTaxSetting(
                tax_name="Professional Tax (Telangana)",
                tax_code="TAX_PT_TELANGANA",
                tax_type="PROFESSIONAL_TAX",
                description="State Professional Tax jurisdiction rule",
                financial_year="2026-2027",
                country="IND",
                state="TELANGANA",
                calc_type="FIXED",
                employee_rate=Decimal("0.00"),
                wage_ceiling=Decimal("200.00"),
                is_active=True,
                display_order=4
            )
            db.add(pt)

            await db.commit()

            res = await db.execute(stmt)
            tax_settings = res.scalars().all()

        return list(tax_settings)

    @staticmethod
    async def get_tax_setting_by_id(db: AsyncSession, tax_id: uuid.UUID) -> Optional[PayrollTaxSetting]:
        """Fetch single tax setting by ID with slabs."""
        stmt = select(PayrollTaxSetting).where(PayrollTaxSetting.id == tax_id)
        res = await db.execute(stmt)
        return res.scalars().first()

    @staticmethod
    async def create_tax_setting(
        db: AsyncSession,
        data: Dict[str, Any],
        actor_email: Optional[str] = None,
        ip_address: Optional[str] = None,
        browser: Optional[str] = None
    ) -> PayrollTaxSetting:
        """Create new tax setting and record audit log."""
        code = data.get("tax_code", "").strip().upper()
        existing = await db.execute(select(PayrollTaxSetting).where(PayrollTaxSetting.tax_code == code))
        if existing.scalars().first():
            raise ValueError(f"Tax code '{code}' already exists")

        new_item = PayrollTaxSetting(
            tax_name=data.get("tax_name", "New Tax Rule"),
            tax_code=code,
            tax_type=data.get("tax_type", "INCOME_TAX_NEW"),
            description=data.get("description", ""),
            financial_year=data.get("financial_year", "2026-2027"),
            country=data.get("country", "IND"),
            state=data.get("state", "TELANGANA"),
            calc_type=data.get("calc_type", "PROGRESSIVE_SLAB"),
            employee_rate=Decimal(str(data.get("employee_rate", 0.0))),
            employer_rate=Decimal(str(data.get("employer_rate", 0.0))),
            wage_ceiling=Decimal(str(data.get("wage_ceiling", 0.0))),
            std_deduction=Decimal(str(data.get("std_deduction", 75000.0))),
            is_active=bool(data.get("is_active", True)),
            display_order=int(data.get("display_order", 1))
        )

        db.add(new_item)
        await db.flush()

        slabs_data = data.get("slabs") or []
        for s in slabs_data:
            slab_item = PayrollTaxSlab(
                tax_setting_id=new_item.id,
                min_income=Decimal(str(s.get("min_income", 0.0))),
                max_income=Decimal(str(s["max_income"])) if s.get("max_income") is not None else None,
                tax_rate=Decimal(str(s.get("tax_rate", 0.0))),
                flat_amount=Decimal(str(s.get("flat_amount", 0.0)))
            )
            db.add(slab_item)

        audit_entry = PayrollTaxAuditLog(
            tax_setting_id=new_item.id,
            action="CREATED",
            actor=actor_email or "System Admin",
            previous_value=None,
            updated_value=new_item.tax_code,
            ip_address=ip_address or "127.0.0.1",
            browser=browser or "Dashboard Web",
            reason="Created new tax setting rule"
        )
        db.add(audit_entry)

        await db.commit()
        await db.refresh(new_item)
        return new_item

    @staticmethod
    async def update_tax_setting(
        db: AsyncSession,
        tax_id: uuid.UUID,
        payload: Dict[str, Any],
        actor_email: Optional[str] = None,
        ip_address: Optional[str] = None,
        browser: Optional[str] = None
    ) -> Optional[PayrollTaxSetting]:
        """Update tax setting and refresh slabs."""
        item = await TaxSettingService.get_tax_setting_by_id(db, tax_id)
        if not item:
            return None

        for key, val in payload.items():
            if hasattr(item, key) and val is not None and key != "slabs":
                if key in ("employee_rate", "employer_rate", "wage_ceiling", "std_deduction"):
                    setattr(item, key, Decimal(str(val)))
                else:
                    setattr(item, key, val)

        if "slabs" in payload and payload["slabs"] is not None:
            await db.execute(delete(PayrollTaxSlab).where(PayrollTaxSlab.tax_setting_id == item.id))
            for s in payload["slabs"]:
                slab_item = PayrollTaxSlab(
                    tax_setting_id=item.id,
                    min_income=Decimal(str(s.get("min_income", 0.0))),
                    max_income=Decimal(str(s["max_income"])) if s.get("max_income") is not None else None,
                    tax_rate=Decimal(str(s.get("tax_rate", 0.0))),
                    flat_amount=Decimal(str(s.get("flat_amount", 0.0)))
                )
                db.add(slab_item)

        item.updated_at = datetime.utcnow()
        db.add(item)

        audit_entry = PayrollTaxAuditLog(
            tax_setting_id=item.id,
            action="UPDATED",
            actor=actor_email or "System Admin",
            previous_value="Previous config",
            updated_value="Updated config",
            ip_address=ip_address or "127.0.0.1",
            browser=browser or "Dashboard Web",
            reason="Updated tax configuration and slabs"
        )
        db.add(audit_entry)

        await db.commit()
        await db.refresh(item)
        return item

    @staticmethod
    async def toggle_active(db: AsyncSession, tax_id: uuid.UUID, active_state: bool) -> Optional[PayrollTaxSetting]:
        """Activate or deactivate tax setting."""
        item = await TaxSettingService.get_tax_setting_by_id(db, tax_id)
        if not item:
            return None

        item.is_active = active_state
        item.updated_at = datetime.utcnow()
        db.add(item)
        await db.commit()
        await db.refresh(item)
        return item

    @staticmethod
    async def delete_tax_setting(db: AsyncSession, tax_id: uuid.UUID) -> bool:
        """Delete custom tax setting."""
        item = await TaxSettingService.get_tax_setting_by_id(db, tax_id)
        if not item:
            return False

        await db.delete(item)
        await db.commit()
        return True

    @staticmethod
    async def get_audit_logs(db: AsyncSession) -> List[Dict[str, Any]]:
        """Retrieve audit log entries for tax changes."""
        stmt = select(PayrollTaxAuditLog).order_by(PayrollTaxAuditLog.created_at.desc()).limit(100)
        res = await db.execute(stmt)
        logs = res.scalars().all()
        return [
            {
                "id": str(l.id),
                "tax_setting_id": str(l.tax_setting_id) if l.tax_setting_id else None,
                "action": l.action,
                "actor": l.actor or "System Admin",
                "previous_value": l.previous_value or "None",
                "updated_value": l.updated_value or "Updated",
                "ip_address": l.ip_address or "127.0.0.1",
                "browser": l.browser or "Dashboard Web",
                "reason": l.reason or "Tax configuration operation",
                "timestamp": l.created_at.isoformat() if l.created_at else ""
            }
            for l in logs
        ]
