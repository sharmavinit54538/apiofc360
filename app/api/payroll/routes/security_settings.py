"""FastAPI Route Handlers for Enterprise Payroll Security Management System."""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.api.payroll.dependencies import DB, Claims
from app.api.payroll.permissions import _require_admin_or_manager, _require_admin
from app.api.payroll.responses import success_response
from app.schemas.auth import APIResponse
from app.schemas.security_setting import (
    SecurityRoleSchema,
    RoleCreateSchema,
    SecurityPolicyUpdateSchema,
    IPWhitelistCreateSchema,
)
from app.services.security_setting_service import SecuritySettingService

router = APIRouter(prefix="/security", tags=["Enterprise Payroll Security"])


@router.get("/roles", response_model=APIResponse[List[dict]], summary="List all RBAC security roles")
@router.head("/roles")
async def list_security_roles(
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[List[dict]]:
    _require_admin_or_manager(claims)
    roles = await SecuritySettingService.list_roles(db)
    return success_response(roles, "Security roles retrieved successfully.")


@router.get("/policies", response_model=APIResponse[dict], summary="Get enterprise security policies")
@router.head("/policies")
async def get_security_policy(
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    policy = await SecuritySettingService.get_security_policy(db)
    return success_response(policy, "Security policy retrieved successfully.")


@router.put("/policies", response_model=APIResponse[dict], summary="Update enterprise security policies")
async def update_security_policy(
    payload: SecurityPolicyUpdateSchema,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin(claims)
    actor_email = claims.get("email") if claims else "admin@aurix.ai"
    updated = await SecuritySettingService.update_security_policy(db, payload.model_dump(exclude_none=True), actor_email)
    return success_response(updated, "Security policy updated successfully.")


@router.get("/sessions", response_model=APIResponse[List[dict]], summary="Get active user sessions")
async def get_active_sessions(
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[List[dict]]:
    _require_admin_or_manager(claims)
    sessions = await SecuritySettingService.list_active_sessions(db)
    return success_response(sessions, "Active user sessions retrieved.")


@router.delete("/sessions/{session_id}", response_model=APIResponse[dict], summary="Revoke active user session")
async def revoke_user_session(
    session_id: uuid.UUID,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin(claims)
    actor_email = claims.get("email") if claims else "admin@aurix.ai"
    revoked = await SecuritySettingService.revoke_session(db, session_id, actor_email)
    if not revoked:
        raise HTTPException(status_code=404, detail="Session not found.")
    return success_response({"session_id": str(session_id)}, "Session revoked successfully.")


@router.post("/logout-all", response_model=APIResponse[dict], summary="Force logout all active user sessions")
async def force_logout_all(
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin(claims)
    actor_email = claims.get("email") if claims else "admin@aurix.ai"
    count = await SecuritySettingService.logout_all_sessions(db, actor_email)
    return success_response({"revoked_count": count}, f"Force logged out {count} active sessions.")


@router.get("/ip-whitelist", response_model=APIResponse[List[dict]], summary="List whitelisted IP ranges")
async def get_ip_whitelist(
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[List[dict]]:
    _require_admin_or_manager(claims)
    items = await SecuritySettingService.list_ip_whitelist(db)
    return success_response(items, "IP whitelist retrieved.")


@router.post("/ip-whitelist", status_code=201, response_model=APIResponse[dict], summary="Add whitelisted IP range")
async def add_ip_whitelist(
    payload: IPWhitelistCreateSchema,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin(claims)
    actor_email = claims.get("email") if claims else "admin@aurix.ai"
    added = await SecuritySettingService.add_ip_whitelist(db, payload.ip_address_or_range, payload.description or "", actor_email)
    return success_response(added, "IP range whitelisted successfully.")


@router.delete("/ip-whitelist/{ip_id}", response_model=APIResponse[dict], summary="Remove whitelisted IP range")
async def delete_ip_whitelist(
    ip_id: uuid.UUID,
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[dict]:
    _require_admin(claims)
    actor_email = claims.get("email") if claims else "admin@aurix.ai"
    deleted = await SecuritySettingService.delete_ip_whitelist(db, ip_id, actor_email)
    if not deleted:
        raise HTTPException(status_code=404, detail="IP whitelist entry not found.")
    return success_response({"id": str(ip_id)}, "IP whitelist entry removed.")


@router.get("/audit", response_model=APIResponse[List[dict]], summary="Get security audit log")
async def get_security_audit(
    claims: Claims = None,
    db: DB = None,
) -> APIResponse[List[dict]]:
    _require_admin_or_manager(claims)
    logs = await SecuritySettingService.list_audit_logs(db)
    return success_response(logs, "Security audit log retrieved.")
