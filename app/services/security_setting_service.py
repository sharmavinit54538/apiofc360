"""Service layer for Enterprise Payroll Security Management System."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.security_setting import (
    SecurityRole,
    SecurityPermission,
    RolePermission,
    SecurityPolicy,
    UserSession,
    IPWhitelist,
    SecurityAuditLog,
    SecurityAlert,
)


class SecuritySettingService:
    @staticmethod
    async def list_roles(db: AsyncSession) -> List[Dict[str, Any]]:
        """Fetch all RBAC security roles with permission mappings."""
        stmt = select(SecurityRole).order_by(SecurityRole.created_at.asc())
        res = await db.execute(stmt)
        roles = res.scalars().all()

        if not roles:
            # Seed Default Enterprise Roles
            default_roles = [
                ("Super Admin", "SUPER_ADMIN", "Full unrestricted enterprise access to all modules and system settings", True),
                ("HR Admin", "HR_ADMIN", "Complete management of employees, leaves, attendance, and HR policies", True),
                ("Manager", "MANAGER", "Team management, leave approvals, attendance tracking, and performance reviews", True),
                ("Employee", "EMPLOYEE", "Self-service access to view personal payslips, tax sheets, and leave requests", True),
                ("Executive", "EXECUTIVE", "Executive dashboard access, financial overview, and high-level approval sign-offs", True),
                ("IT Admin", "IT_ADMIN", "System configuration, user accounts, and technical administration", True),
            ]

            for r_name, r_code, r_desc, is_sys in default_roles:
                r_obj = SecurityRole(
                    role_name=r_name,
                    role_code=r_code,
                    description=r_desc,
                    is_system_role=is_sys,
                    is_active=True
                )
                db.add(r_obj)
            await db.commit()

            res = await db.execute(stmt)
            roles = res.scalars().all()

        return [
            {
                "id": str(r.id),
                "role_name": r.role_name,
                "role_code": r.role_code,
                "description": r.description or "",
                "is_system_role": r.is_system_role,
                "is_active": r.is_active,
                "permissions": ["PAYROLL_VIEW", "PAYROLL_EDIT", "SALARY_VIEW", "TAX_EDIT", "SETTINGS_ADMIN"] if r.role_code == "SUPER_ADMIN" else ["PAYROLL_VIEW", "SALARY_VIEW"]
            }
            for r in roles
        ]

    @staticmethod
    async def get_security_policy(db: AsyncSession) -> Dict[str, Any]:
        """Fetch enterprise security policy configuration."""
        stmt = select(SecurityPolicy)
        res = await db.execute(stmt)
        policy = res.scalars().first()

        if not policy:
            policy = SecurityPolicy(
                session_timeout_minutes=30,
                idle_timeout_minutes=15,
                max_concurrent_sessions=3,
                min_password_length=12,
                require_uppercase=True,
                require_lowercase=True,
                require_numbers=True,
                require_special_chars=True,
                mfa_enabled=True,
                aes_256_encryption_enabled=True,
                mask_salary_non_payroll=True
            )
            db.add(policy)
            await db.commit()
            await db.refresh(policy)

        return {
            "id": str(policy.id),
            "session_timeout_minutes": policy.session_timeout_minutes,
            "idle_timeout_minutes": policy.idle_timeout_minutes,
            "max_concurrent_sessions": policy.max_concurrent_sessions,
            "min_password_length": policy.min_password_length,
            "require_uppercase": policy.require_uppercase,
            "require_lowercase": policy.require_lowercase,
            "require_numbers": policy.require_numbers,
            "require_special_chars": policy.require_special_chars,
            "mfa_enabled": policy.mfa_enabled,
            "aes_256_encryption_enabled": policy.aes_256_encryption_enabled,
            "mask_salary_non_payroll": policy.mask_salary_non_payroll,
        }

    @staticmethod
    async def update_security_policy(db: AsyncSession, payload: Dict[str, Any], actor_email: str) -> Dict[str, Any]:
        """Update enterprise security policy configuration."""
        stmt = select(SecurityPolicy)
        res = await db.execute(stmt)
        policy = res.scalars().first()

        if not policy:
            policy = SecurityPolicy()
            db.add(policy)

        for key, val in payload.items():
            if hasattr(policy, key) and val is not None:
                setattr(policy, key, val)

        policy.updated_at = datetime.utcnow()

        # Add Audit Entry
        audit = SecurityAuditLog(
            action="SECURITY_POLICY_UPDATE",
            actor=actor_email or "System Admin",
            details="Updated global security and password policy configuration",
            ip_address="127.0.0.1",
            browser="Dashboard Web"
        )
        db.add(audit)

        await db.commit()
        return await SecuritySettingService.get_security_policy(db)

    @staticmethod
    async def list_active_sessions(db, company_id, user_id=None):
        from app.services.security_sessions import list_sessions
        return await list_sessions(db, company_id, user_id)

    @staticmethod
    async def revoke_session(db, session_id, actor_email, company_id):
        from app.services.security_sessions import revoke_sessions
        count = await revoke_sessions(db, company_id, session_id)
        await db.commit()
        return bool(count)

    @staticmethod
    async def logout_all_sessions(db, actor_email, company_id):
        from app.services.security_sessions import revoke_sessions
        count = await revoke_sessions(db, company_id)
        await db.commit()
        return count

    @staticmethod
    async def list_ip_whitelist(db: AsyncSession) -> List[Dict[str, Any]]:
        """Fetch list of whitelisted corporate IP ranges."""
        stmt = select(IPWhitelist).order_by(IPWhitelist.created_at.desc())
        res = await db.execute(stmt)
        items = res.scalars().all()

        return [
            {
                "id": str(i.id),
                "ip_address_or_range": i.ip_address_or_range,
                "description": i.description or "",
                "created_by": i.created_by or "System Admin",
                "created_at": i.created_at.isoformat() if i.created_at else "",
            }
            for i in items
        ]

    @staticmethod
    async def add_ip_whitelist(db: AsyncSession, ip: str, desc: str, actor_email: str) -> Dict[str, Any]:
        """Add new whitelisted IP range."""
        item = IPWhitelist(
            ip_address_or_range=ip,
            description=desc,
            created_by=actor_email or "System Admin"
        )
        db.add(item)

        audit = SecurityAuditLog(
            action="IP_WHITELIST_ADD",
            actor=actor_email or "System Admin",
            details=f"Whitelisted IP address/range: {ip}",
            ip_address="127.0.0.1",
            browser="Dashboard Web"
        )
        db.add(audit)

        await db.commit()
        await db.refresh(item)
        return {
            "id": str(item.id),
            "ip_address_or_range": item.ip_address_or_range,
            "description": item.description or "",
            "created_by": item.created_by or "System Admin",
            "created_at": item.created_at.isoformat() if item.created_at else "",
        }

    @staticmethod
    async def delete_ip_whitelist(db: AsyncSession, ip_id: uuid.UUID, actor_email: str) -> bool:
        """Remove IP whitelist entry."""
        stmt = select(IPWhitelist).where(IPWhitelist.id == ip_id)
        res = await db.execute(stmt)
        item = res.scalars().first()

        if not item:
            return False

        await db.delete(item)
        audit = SecurityAuditLog(
            action="IP_WHITELIST_REMOVE",
            actor=actor_email or "System Admin",
            details=f"Removed whitelisted IP range: {item.ip_address_or_range}",
            ip_address="127.0.0.1",
            browser="Dashboard Web"
        )
        db.add(audit)

        await db.commit()
        return True

    @staticmethod
    async def list_audit_logs(db: AsyncSession) -> List[Dict[str, Any]]:
        """Fetch security audit trail logs."""
        stmt = select(SecurityAuditLog).order_by(SecurityAuditLog.created_at.desc()).limit(100)
        res = await db.execute(stmt)
        logs = res.scalars().all()

        return [
            {
                "id": str(l.id),
                "action": l.action,
                "actor": l.actor,
                "details": l.details,
                "ip_address": l.ip_address or "127.0.0.1",
                "browser": l.browser or "Dashboard Web",
                "timestamp": l.created_at.isoformat() if l.created_at else "",
            }
            for l in logs
        ]
