"""Session views are backed exclusively by issued refresh-token records."""
from datetime import datetime, timezone
from sqlalchemy import select, update, or_
from app.models.refresh_token import RefreshToken
from app.models.user import User


def active_sessions(company_id, user_id=None):
    if company_id is None:
        raise ValueError("Company scope is required")
    stmt = select(RefreshToken, User).join(User, User.id == RefreshToken.user_id).where(
        User.company_id == company_id, RefreshToken.revoked.is_(False),
        RefreshToken.expires_at > datetime.now(timezone.utc))
    if user_id:
        stmt = stmt.where(User.id == user_id)
    return stmt.order_by(RefreshToken.created_at.desc())


async def list_sessions(db, company_id, user_id=None):
    rows = (await db.execute(active_sessions(company_id, user_id))).all()
    return [{"id": str(token.id), "user_email": user.email,
             "device_info": token.device or "", "browser": token.device or "",
             "ip_address": token.ip_address or "", "is_active": True,
             "login_time": token.created_at.isoformat(),
             "last_activity": token.updated_at.isoformat()} for token, user in rows]


async def revoke_sessions(db, company_id, session_id=None):
    stmt = active_sessions(company_id)
    if session_id:
        stmt = stmt.where(RefreshToken.id == session_id)
    rows = (await db.execute(stmt)).all()
    now = datetime.now(timezone.utc)
    for token, _ in rows:
        token.revoked = True
        token.revoked_at = now
        token.revoked_reason = "ADMIN_REVOKED"
    from app.models.audit_log import AuditLog
    if rows:
        db.add(AuditLog(company_id=company_id, action="SECURITY_SESSIONS_REVOKED",
                        details=f"Revoked {len(rows)} issued login sessions"))
    await db.flush()
    return len(rows)
