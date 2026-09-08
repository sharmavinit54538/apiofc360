"""Full-featured Service and Repository for Payroll Cycle Management."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payroll import PayCycle, PayrollCycleHistory, PayrollCycleLog, PayrollAuditLog


class PayCycleFullService:
    @staticmethod
    async def list_cycles(db: AsyncSession, status_filter: Optional[str] = None) -> List[PayCycle]:
        """Fetch all payroll cycles ordered by period and start date."""
        stmt = select(PayCycle)
        if status_filter:
            stmt = stmt.where(PayCycle.status == status_filter.upper())
        stmt = stmt.order_by(PayCycle.period_year.desc(), PayCycle.period_month.desc(), PayCycle.created_at.desc())
        
        res = await db.execute(stmt)
        cycles = res.scalars().all()

        if not cycles:
            # Seed initial active payroll cycle if database is empty
            initial_cycle = PayCycle(
                name="July 2026 Regular Payroll Cycle",
                frequency="MONTHLY",
                period_month=7,
                period_year=2026,
                status="RUNNING",
                start_date=date(2026, 7, 1),
                end_date=date(2026, 7, 31),
                processing_date=date(2026, 7, 28),
                payment_date=date(2026, 7, 31),
                payslip_generation_date=date(2026, 7, 29),
                attendance_lock_date=date(2026, 7, 25),
                leave_lock_date=date(2026, 7, 25),
                overtime_lock_date=date(2026, 7, 26),
                tax_calculation_date=date(2026, 7, 27),
                bonus_processing_date=date(2026, 7, 26),
                is_active=True,
                is_locked=False,
                locks={
                    "attendance": True,
                    "leaves": True,
                    "overtime": False,
                    "components": False,
                    "tax": False,
                    "payslips": False
                },
                automation={
                    "auto_generation": True,
                    "auto_payslip": True,
                    "auto_calc": True,
                    "auto_email": True,
                    "auto_whatsapp": False,
                    "auto_rollover": True
                },
                total_employees=142,
                total_gross=1250000.00,
                total_deductions=185000.00,
                total_net=1065000.00,
                remarks="Current active regular monthly cycle"
            )
            db.add(initial_cycle)

            # Seed an upcoming scheduled cycle
            upcoming_cycle = PayCycle(
                name="August 2026 Regular Payroll Cycle",
                frequency="MONTHLY",
                period_month=8,
                period_year=2026,
                status="SCHEDULED",
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 31),
                processing_date=date(2026, 8, 28),
                payment_date=date(2026, 8, 31),
                payslip_generation_date=date(2026, 8, 29),
                attendance_lock_date=date(2026, 8, 25),
                leave_lock_date=date(2026, 8, 25),
                overtime_lock_date=date(2026, 8, 26),
                is_active=False,
                is_locked=False,
                locks={
                    "attendance": False,
                    "leaves": False,
                    "overtime": False,
                    "components": False,
                    "tax": False,
                    "payslips": False
                },
                automation={
                    "auto_generation": True,
                    "auto_payslip": True,
                    "auto_calc": True,
                    "auto_email": True,
                    "auto_whatsapp": False,
                    "auto_rollover": True
                },
                total_employees=145,
                total_gross=0.0,
                total_deductions=0.0,
                total_net=0.0,
                remarks="Upcoming scheduled cycle"
            )
            db.add(upcoming_cycle)
            await db.commit()

            res = await db.execute(stmt)
            cycles = res.scalars().all()

        return list(cycles)

    @staticmethod
    async def get_cycle_by_id(db: AsyncSession, cycle_id: uuid.UUID) -> Optional[PayCycle]:
        """Get single cycle by ID."""
        stmt = select(PayCycle).where(PayCycle.id == cycle_id)
        res = await db.execute(stmt)
        return res.scalars().first()

    @staticmethod
    async def create_cycle(
        db: AsyncSession,
        data: Dict[str, Any],
        actor_email: Optional[str] = None,
        ip_address: Optional[str] = None,
        browser: Optional[str] = None
    ) -> PayCycle:
        """Create new payroll cycle and log audit trail."""
        p_month = int(data.get("period_month", 1))
        p_year = int(data.get("period_year", 2026))

        # Check for duplicate cycle in same period
        existing_stmt = select(PayCycle).where(
            PayCycle.period_month == p_month,
            PayCycle.period_year == p_year,
        )
        res = await db.execute(existing_stmt)
        if res.scalars().first():
            from app.core.exceptions import ConflictException
            raise ConflictException(message=f"A payroll cycle for {p_month}/{p_year} already exists.")

        # Convert date strings if needed
        def parse_d(val):
            if isinstance(val, str) and val.strip():
                return date.fromisoformat(val.strip())
            return val if isinstance(val, date) else None

        new_cycle = PayCycle(
            name=data.get("name", "New Payroll Cycle"),
            frequency=data.get("frequency", "MONTHLY"),
            period_month=p_month,
            period_year=p_year,
            status="DRAFT",
            start_date=parse_d(data.get("start_date")),
            end_date=parse_d(data.get("end_date")),
            processing_date=parse_d(data.get("processing_date")),
            payment_date=parse_d(data.get("payment_date")),
            payslip_generation_date=parse_d(data.get("payslip_generation_date")),
            attendance_lock_date=parse_d(data.get("attendance_lock_date")),
            leave_lock_date=parse_d(data.get("leave_lock_date")),
            overtime_lock_date=parse_d(data.get("overtime_lock_date")),
            locks=data.get("locks") or {
                "attendance": False, "leaves": False, "overtime": False,
                "components": False, "tax": False, "payslips": False
            },
            automation=data.get("automation") or {
                "auto_generation": True, "auto_payslip": True, "auto_calc": True,
                "auto_email": True, "auto_whatsapp": False, "auto_rollover": True
            },
            remarks=data.get("remarks", "")
        )

        db.add(new_cycle)
        await db.flush()

        # Write cycle log
        log_entry = PayrollCycleLog(
            cycle_id=new_cycle.id,
            action="CREATED",
            actor=actor_email or "System Admin",
            previous_value=None,
            updated_value=new_cycle.status,
            ip_address=ip_address or "127.0.0.1",
            browser=browser or "Dashboard Web",
            reason="Created new payroll cycle"
        )
        db.add(log_entry)

        await db.commit()
        await db.refresh(new_cycle)
        return new_cycle

    @staticmethod
    async def update_cycle(
        db: AsyncSession,
        cycle_id: uuid.UUID,
        payload: Dict[str, Any],
        actor_email: Optional[str] = None,
        ip_address: Optional[str] = None,
        browser: Optional[str] = None
    ) -> Optional[PayCycle]:
        """Update cycle details with audit logging."""
        cycle = await PayCycleFullService.get_cycle_by_id(db, cycle_id)
        if not cycle:
            return None

        def parse_d(val):
            if isinstance(val, str) and val.strip():
                return date.fromisoformat(val.strip())
            return val if isinstance(val, date) else val

        for field, val in payload.items():
            if hasattr(cycle, field) and val is not None:
                if field.endswith("_date"):
                    setattr(cycle, field, parse_d(val))
                else:
                    setattr(cycle, field, val)

        cycle.updated_at = datetime.utcnow()
        db.add(cycle)

        # Write log
        log_entry = PayrollCycleLog(
            cycle_id=cycle.id,
            action="UPDATED",
            actor=actor_email or "System Admin",
            previous_value="Previous config",
            updated_value="Updated config",
            ip_address=ip_address or "127.0.0.1",
            browser=browser or "Dashboard Web",
            reason=payload.get("reason", "Updated payroll cycle settings")
        )
        db.add(log_entry)

        await db.commit()
        await db.refresh(cycle)
        return cycle

    @staticmethod
    async def activate_cycle(db: AsyncSession, cycle_id: uuid.UUID, actor_email: Optional[str] = None) -> Optional[PayCycle]:
        """Mark target cycle as sole Active cycle and set status to RUNNING."""
        # Deactivate all existing cycles
        await db.execute(update(PayCycle).values(is_active=False))

        cycle = await PayCycleFullService.get_cycle_by_id(db, cycle_id)
        if not cycle:
            return None

        cycle.is_active = True
        cycle.status = "RUNNING"
        cycle.updated_at = datetime.utcnow()
        db.add(cycle)

        log_entry = PayrollCycleLog(
            cycle_id=cycle.id,
            action="ACTIVATED",
            actor=actor_email or "System Admin",
            previous_value="INACTIVE",
            updated_value="ACTIVE (RUNNING)",
            reason="Activated payroll cycle as primary active run"
        )
        db.add(log_entry)

        await db.commit()
        await db.refresh(cycle)
        return cycle

    @staticmethod
    async def toggle_lock(
        db: AsyncSession,
        cycle_id: uuid.UUID,
        lock_state: bool,
        locks_data: Optional[Dict[str, bool]] = None,
        actor_email: Optional[str] = None
    ) -> Optional[PayCycle]:
        """Lock or unlock payroll cycle and its granular lock flags."""
        cycle = await PayCycleFullService.get_cycle_by_id(db, cycle_id)
        if not cycle:
            return None

        cycle.is_locked = lock_state
        if lock_state and cycle.status != "LOCKED":
            cycle.status = "LOCKED"
            cycle.locked_at = datetime.utcnow()
        elif not lock_state and cycle.status == "LOCKED":
            cycle.status = "RUNNING"

        if locks_data:
            current_locks = cycle.locks or {}
            current_locks.update(locks_data)
            cycle.locks = current_locks

        cycle.updated_at = datetime.utcnow()
        db.add(cycle)

        log_entry = PayrollCycleLog(
            cycle_id=cycle.id,
            action="LOCKED" if lock_state else "UNLOCKED",
            actor=actor_email or "System Admin",
            previous_value=str(not lock_state),
            updated_value=str(lock_state),
            reason=f"Cycle {'locked' if lock_state else 'unlocked'} by authorized role"
        )
        db.add(log_entry)

        await db.commit()
        await db.refresh(cycle)
        return cycle

    @staticmethod
    async def duplicate_cycle(db: AsyncSession, cycle_id: uuid.UUID, actor_email: Optional[str] = None) -> Optional[PayCycle]:
        """Duplicate an existing payroll cycle for future period."""
        existing = await PayCycleFullService.get_cycle_by_id(db, cycle_id)
        if not existing:
            return None

        next_month = (existing.period_month % 12) + 1
        next_year = existing.period_year + (1 if existing.period_month == 12 else 0)

        new_cycle = PayCycle(
            name=f"{existing.name} (Copy)",
            frequency=existing.frequency,
            period_month=next_month,
            period_year=next_year,
            status="DRAFT",
            start_date=existing.start_date,
            end_date=existing.end_date,
            processing_date=existing.processing_date,
            payment_date=existing.payment_date,
            is_active=False,
            is_locked=False,
            locks={
                "attendance": False, "leaves": False, "overtime": False,
                "components": False, "tax": False, "payslips": False
            },
            automation=existing.automation or {},
            remarks=f"Duplicated from {existing.name}"
        )

        db.add(new_cycle)
        await db.commit()
        await db.refresh(new_cycle)
        return new_cycle

    @staticmethod
    async def archive_cycle(db: AsyncSession, cycle_id: uuid.UUID, actor_email: Optional[str] = None) -> Optional[PayCycle]:
        """Archive a completed or old cycle."""
        cycle = await PayCycleFullService.get_cycle_by_id(db, cycle_id)
        if not cycle:
            return None

        cycle.status = "ARCHIVED"
        cycle.is_active = False
        cycle.updated_at = datetime.utcnow()
        db.add(cycle)

        await db.commit()
        await db.refresh(cycle)
        return cycle

    @staticmethod
    async def delete_cycle(db: AsyncSession, cycle_id: uuid.UUID) -> bool:
        """Delete draft or cancelled cycle."""
        cycle = await PayCycleFullService.get_cycle_by_id(db, cycle_id)
        if not cycle:
            return False

        await db.delete(cycle)
        await db.commit()
        return True

    @staticmethod
    async def get_logs(db: AsyncSession) -> List[Dict[str, Any]]:
        """Retrieve audit logs for payroll cycles."""
        stmt = select(PayrollCycleLog).order_by(PayrollCycleLog.created_at.desc()).limit(100)
        res = await db.execute(stmt)
        logs = res.scalars().all()
        return [
            {
                "id": str(l.id),
                "cycle_id": str(l.cycle_id) if l.cycle_id else None,
                "action": l.action,
                "actor": l.actor or "System Admin",
                "previous_value": l.previous_value or "None",
                "updated_value": l.updated_value or "Updated",
                "ip_address": l.ip_address or "127.0.0.1",
                "browser": l.browser or "Dashboard Web",
                "reason": l.reason or "Payroll cycle operation",
                "timestamp": l.created_at.isoformat() if l.created_at else ""
            }
            for l in logs
        ]
