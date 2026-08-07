"""Service and Repository layer for Payroll Settings operations."""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy import select, update, insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payroll import StatutoryComplianceConfig, PayrollSettingsHistory, PayrollAuditLog


class PayrollSettingsService:
    @staticmethod
    async def get_active_settings(db: AsyncSession, company_id: Optional[uuid.UUID] = None) -> StatutoryComplianceConfig:
        """Fetch active payroll settings or create default row if none exists."""
        stmt = select(StatutoryComplianceConfig).where(StatutoryComplianceConfig.is_active == True)
        if company_id:
            stmt = stmt.where(StatutoryComplianceConfig.company_id == company_id)
        
        result = await db.execute(stmt)
        config = result.scalars().first()

        if not config:
            # Seed initial active configuration row in DB
            config = StatutoryComplianceConfig(
                company_name="Aurix AI Enterprise",
                legal_business_name="Aurix AI Technologies Pvt Ltd",
                gst_number="36AAACA1234A1Z5",
                pan_number="AAACA1234A",
                tan_number="HYDA12345E",
                cin_number="U72200TG2026PTC123456",
                state="Telangana",
                currency="INR",
                country="India",
                timezone="Asia/Kolkata",
                financial_year_start="04-01",
                payroll_start_day=1,
                payroll_end_day=30,
                salary_payment_date=1,
                working_days_policy="EXCLUDE_WEEKENDS",
                salary_calc_method="MONTHLY_FIXED",
                attendance_source="FACE_BIOMETRIC",
                payslip_footer="Confidential Payroll Document — Aurix Enterprise",
                approval_levels=2,
                auto_lock_payroll=True,
                enable_draft_payroll=True,
                enable_retro_payroll=True,
                pay_cycle_type="MONTHLY",
                grace_period_days=3,
                cutoff_date=25,
                preview_days=5,
                pf_enabled=True,
                employee_pf_rate=0.12,
                employer_pf_rate=0.12,
                pf_wage_ceiling=15000.00,
                pf_on_full_basic=False,
                esi_enabled=True,
                employee_esi_rate=0.0075,
                employer_esi_rate=0.0325,
                esi_wage_ceiling=21000.00,
                pt_state="TELANGANA",
                pt_slabs=[
                  {"upto": 15000, "amount": 0},
                  {"upto": 20000, "amount": 150},
                  {"upto": None, "amount": 200}
                ],
                default_tax_regime="NEW",
                lop_basis="CALENDAR_DAYS",
                overtime_enabled=True,
                overtime_multiplier_holiday=2.0,
                overtime_multiplier_weekend=1.5,
                overtime_multiplier_night=1.25,
                bank_name="HDFC Bank",
                bank_ifsc="HDFC0001234",
                salary_transfer_format="NEFT",
                auto_email_payslips=True,
                auto_backup_payroll=True,
                is_active=True
            )
            db.add(config)
            await db.commit()
            await db.refresh(config)

        return config

    @staticmethod
    async def update_settings(
        db: AsyncSession,
        payload: Dict[str, Any],
        actor_id: Optional[uuid.UUID] = None,
        actor_role: Optional[str] = None,
        actor_email: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> StatutoryComplianceConfig:
        """Update active settings, write audit log, and create a version history snapshot."""
        config = await PayrollSettingsService.get_active_settings(db)
        
        # Build diff tracking
        diffs = {}
        for key, new_val in payload.items():
            if hasattr(config, key):
                old_val = getattr(config, key)
                if old_val != new_val:
                    diffs[key] = {
                        "old": str(old_val),
                        "new": str(new_val)
                    }
                    setattr(config, key, new_val)

        config.updated_at = datetime.utcnow()
        db.add(config)

        # Log audit entry
        reason = payload.get("reason", "Updated payroll configuration settings")
        audit_log = PayrollAuditLog(
            company_id=config.company_id,
            entity_type="StatutoryComplianceConfig",
            entity_id=config.id,
            action="UPDATED",
            actor_id=actor_id,
            actor_role=actor_role or "ADMIN",
            old_status="ACTIVE",
            new_status="ACTIVE",
            reason=reason,
            extra_data={
                "diffs": diffs,
                "changed_by": actor_email or "system_admin",
                "ip_address": ip_address or "127.0.0.1",
                "user_agent": user_agent or "Web Dashboard",
            }
        )
        db.add(audit_log)

        # Get latest version number
        hist_stmt = select(PayrollSettingsHistory.version_number).order_by(PayrollSettingsHistory.version_number.desc())
        latest_ver_res = await db.execute(hist_stmt)
        latest_ver = latest_ver_res.scalars().first() or 0
        new_version = latest_ver + 1

        # Snapshot current full config into History table
        snapshot = {
            "company_name": config.company_name,
            "legal_business_name": config.legal_business_name,
            "gst_number": config.gst_number,
            "pan_number": config.pan_number,
            "tan_number": config.tan_number,
            "cin_number": config.cin_number,
            "currency": config.currency,
            "country": config.country,
            "timezone": config.timezone,
            "financial_year_start": config.financial_year_start,
            "payroll_start_day": config.payroll_start_day,
            "salary_payment_date": config.salary_payment_date,
            "pay_cycle_type": config.pay_cycle_type,
            "pf_enabled": config.pf_enabled,
            "esi_enabled": config.esi_enabled,
            "default_tax_regime": config.default_tax_regime,
            "updated_at": config.updated_at.isoformat()
        }

        history_entry = PayrollSettingsHistory(
            company_id=config.company_id,
            version_number=new_version,
            config_data=snapshot,
            changed_by=actor_email or "Admin User",
            change_reason=reason,
            effective_from=date.today(),
            is_active=True
        )
        db.add(history_entry)

        await db.commit()
        await db.refresh(config)
        return config

    @staticmethod
    async def get_history(db: AsyncSession) -> List[Dict[str, Any]]:
        """Retrieve historical configuration version snapshots."""
        stmt = select(PayrollSettingsHistory).order_by(PayrollSettingsHistory.version_number.desc())
        res = await db.execute(stmt)
        rows = res.scalars().all()
        return [
            {
                "id": str(r.id),
                "version_number": r.version_number,
                "config_data": r.config_data,
                "changed_by": r.changed_by or "System Admin",
                "change_reason": r.change_reason or "Configuration update",
                "effective_from": r.effective_from.isoformat() if r.effective_from else "",
                "is_active": r.is_active,
                "created_at": r.created_at.isoformat() if r.created_at else "",
            }
            for r in rows
        ]

    @staticmethod
    async def get_audit_logs(db: AsyncSession) -> List[Dict[str, Any]]:
        """Retrieve audit log entries for settings changes."""
        stmt = select(PayrollAuditLog).where(
            PayrollAuditLog.entity_type == "StatutoryComplianceConfig"
        ).order_by(PayrollAuditLog.created_at.desc()).limit(100)
        
        res = await db.execute(stmt)
        logs = res.scalars().all()

        items = []
        for l in logs:
            extra = l.extra_data or {}
            diffs = extra.get("diffs", {})
            diff_summary = []
            for field, vals in diffs.items():
                diff_summary.append(f"{field}: '{vals.get('old')}' → '{vals.get('new')}'")

            items.append({
                "id": str(l.id),
                "action": l.action,
                "actor": extra.get("changed_by", l.actor_role or "System"),
                "timestamp": l.created_at.isoformat() if l.created_at else "",
                "category": "General Settings",
                "old_value": ", ".join([f"{k}: {v['old']}" for k, v in diffs.items()]) or "Initial state",
                "new_value": ", ".join([f"{k}: {v['new']}" for k, v in diffs.items()]) or "Updated state",
                "ip_address": extra.get("ip_address", "127.0.0.1"),
                "reason": l.reason or "Settings update"
            })
        return items

    @staticmethod
    async def reset_to_defaults(db: AsyncSession, reason: str = "Reset to statutory compliance presets") -> StatutoryComplianceConfig:
        """Reset settings to default compliance presets."""
        config = await PayrollSettingsService.get_active_settings(db)
        config.currency = "INR"
        config.country = "India"
        config.timezone = "Asia/Kolkata"
        config.financial_year_start = "04-01"
        config.payroll_start_day = 1
        config.payroll_end_day = 30
        config.salary_payment_date = 1
        config.auto_lock_payroll = True
        config.enable_draft_payroll = True
        config.enable_retro_payroll = True
        config.pf_enabled = True
        config.esi_enabled = True
        config.default_tax_regime = "NEW"
        config.updated_at = datetime.utcnow()

        db.add(config)
        await db.commit()
        await db.refresh(config)
        return config
