"""Service layer and calculation engine for Enterprise Overtime Management System."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.overtime_setting import (
    PayrollOvertimeSetting,
    OvertimeRule,
    PayrollOvertimeHistory,
    PayrollOvertimeAuditLog,
)


class OvertimeSettingService:
    @staticmethod
    async def get_settings(db: AsyncSession) -> PayrollOvertimeSetting:
        """Fetch or initialize company overtime policy settings."""
        stmt = select(PayrollOvertimeSetting).order_by(PayrollOvertimeSetting.created_at.asc())
        res = await db.execute(stmt)
        setting = res.scalars().first()

        if not setting:
            setting = PayrollOvertimeSetting(
                overtime_enabled=True,
                overtime_code="OT_POLICY_STD",
                calc_method="HOURLY_MULTIPLIER",
                standard_multiplier=Decimal("1.50"),
                weekend_multiplier=Decimal("1.50"),
                holiday_multiplier=Decimal("2.00"),
                night_shift_multiplier=Decimal("1.25"),
                emergency_multiplier=Decimal("2.50"),
                min_hours_per_day=Decimal("1.00"),
                max_hours_per_day=Decimal("4.00"),
                max_hours_per_week=Decimal("16.00"),
                max_hours_per_month=Decimal("50.00"),
                auto_approval_enabled=False,
                auto_approval_threshold_hours=Decimal("2.00"),
                require_manager_approval=True,
                comp_off_enabled=True,
                comp_off_expiry_days=90
            )
            db.add(setting)
            await db.commit()
            await db.refresh(setting)

        return setting

    @staticmethod
    async def update_settings(
        db: AsyncSession,
        payload: Dict[str, Any],
        actor_email: Optional[str] = None,
        ip_address: Optional[str] = None,
        browser: Optional[str] = None
    ) -> PayrollOvertimeSetting:
        """Update overtime settings with audit log."""
        setting = await OvertimeSettingService.get_settings(db)

        for key, val in payload.items():
            if hasattr(setting, key) and val is not None:
                if key.endswith("_multiplier") or key.endswith("_hours") or key.startswith("max_") or key.startswith("min_"):
                    setattr(setting, key, Decimal(str(val)))
                else:
                    setattr(setting, key, val)

        setting.updated_at = datetime.utcnow()
        db.add(setting)

        audit_entry = PayrollOvertimeAuditLog(
            setting_id=setting.id,
            action="UPDATED",
            actor=actor_email or "System Admin",
            previous_value="Previous policy",
            updated_value="Updated policy",
            ip_address=ip_address or "127.0.0.1",
            browser=browser or "Dashboard Web",
            reason="Updated overtime calculation rules & policy multipliers"
        )
        db.add(audit_entry)

        await db.commit()
        await db.refresh(setting)
        return setting

    @staticmethod
    async def calculate_overtime_pay(
        db: AsyncSession,
        basic_salary: float,
        overtime_hours: float,
        ot_type: str = "STANDARD",
        working_days: int = 26,
        hours_per_day: int = 8
    ) -> Dict[str, Any]:
        """Calculate overtime payout based on basic salary, hours, and OT type multiplier."""
        setting = await OvertimeSettingService.get_settings(db)

        hourly_rate = basic_salary / (working_days * hours_per_day)

        multiplier = float(setting.standard_multiplier)
        if ot_type.upper() == "WEEKEND":
            multiplier = float(setting.weekend_multiplier)
        elif ot_type.upper() == "HOLIDAY":
            multiplier = float(setting.holiday_multiplier)
        elif ot_type.upper() in ("NIGHT_SHIFT", "NIGHT"):
            multiplier = float(setting.night_shift_multiplier)
        elif ot_type.upper() == "EMERGENCY":
            multiplier = float(setting.emergency_multiplier)

        overtime_pay = round(hourly_rate * overtime_hours * multiplier, 2)

        return {
            "basic_salary": basic_salary,
            "overtime_hours": overtime_hours,
            "ot_type": ot_type.upper(),
            "hourly_rate": round(hourly_rate, 2),
            "multiplier": multiplier,
            "total_overtime_pay": overtime_pay,
            "formula": f"({basic_salary} / ({working_days} * {hours_per_day})) * {overtime_hours} hrs * {multiplier}x"
        }

    @staticmethod
    async def get_audit_logs(db: AsyncSession) -> List[Dict[str, Any]]:
        """Retrieve audit log entries for overtime policy changes."""
        stmt = select(PayrollOvertimeAuditLog).order_by(PayrollOvertimeAuditLog.created_at.desc()).limit(100)
        res = await db.execute(stmt)
        logs = res.scalars().all()
        return [
            {
                "id": str(l.id),
                "setting_id": str(l.setting_id) if l.setting_id else None,
                "action": l.action,
                "actor": l.actor or "System Admin",
                "previous_value": l.previous_value or "None",
                "updated_value": l.updated_value or "Updated",
                "ip_address": l.ip_address or "127.0.0.1",
                "browser": l.browser or "Dashboard Web",
                "reason": l.reason or "Overtime policy action",
                "timestamp": l.created_at.isoformat() if l.created_at else ""
            }
            for l in logs
        ]
