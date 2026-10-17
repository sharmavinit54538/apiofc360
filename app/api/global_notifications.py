"""# MOCK DATA - not production: Demonstration automation rules, activity logs, and scheduled jobs.
Notifications endpoints are backed by real tenant-scoped UserNotification database records.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.api.payroll.permissions import _require_admin_or_manager
from app.api.payroll.responses import success_response
from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.models.company import Company
from app.schemas.auth import APIResponse
from app.services import notification_service

router = APIRouter(prefix="/global-notifications", tags=["Global Notification & Automation Hub"])


def _get_cid(claims: dict | None) -> uuid.UUID:
    if not claims:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")
    co_id = claims.get("company_id")
    if not co_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No company association found in token.")
    try:
        return uuid.UUID(str(co_id))
    except (ValueError, TypeError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid company ID.")


def _get_uid(claims: dict | None) -> uuid.UUID:
    if not claims:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")
    raw_uid = claims.get("sub") or claims.get("user_id") or claims.get("id")
    if not raw_uid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User identity missing in token.")
    try:
        return uuid.UUID(str(raw_uid))
    except (ValueError, TypeError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid user ID.")


class AutomationRulePayload(BaseModel):
    name: str
    trigger_event: str
    channels: List[str] = ["IN_APP", "EMAIL"]
    recipients: List[str] = ["ALL_EMPLOYEES"]
    template: str
    is_enabled: bool = True
    delay_minutes: int = 0
    retry_count: int = 3


class PreferencesPayload(BaseModel):
    sound_enabled: bool = True
    desktop_enabled: bool = True
    email_enabled: bool = True
    sms_enabled: bool = False
    push_enabled: bool = True
    do_not_disturb: bool = False
    priority_level: str = "ALL"


# Static Demonstration Mock Data
BASE_AUTOMATION_RULES = [
    {
        "id": "rule_1",
        "name": "Auto PDF Payslip Email Dispatch",
        "trigger_event": "PAYROLL_COMPLETED",
        "channels": ["IN_APP", "EMAIL"],
        "recipients": ["ALL_EMPLOYEES"],
        "template": "Hello {{employee_name}}, your payslip for {{month}} is ready.",
        "is_enabled": True,
        "delay_minutes": 0,
        "retry_count": 3,
        "last_triggered": "2026-07-28T14:30:00Z",
    },
    {
        "id": "rule_2",
        "name": "Salary Credit SMS Advice Alert",
        "trigger_event": "SALARY_DISBURSED",
        "channels": ["SMS", "PUSH"],
        "recipients": ["ALL_EMPLOYEES"],
        "template": "Dear {{employee_name}}, salary for {{month}} credited to your bank account.",
        "is_enabled": True,
        "delay_minutes": 5,
        "retry_count": 2,
        "last_triggered": "2026-07-28T15:00:00Z",
    },
    {
        "id": "rule_3",
        "name": "Statutory Filing Deadline Reminder",
        "trigger_event": "COMPLIANCE_DUE_SOON",
        "channels": ["IN_APP", "EMAIL"],
        "recipients": ["PAYROLL_ADMIN", "FINANCE_HEAD"],
        "template": "Reminder: Statutory {{compliance_name}} filing is due on {{due_date}}.",
        "is_enabled": True,
        "delay_minutes": 0,
        "retry_count": 3,
        "last_triggered": "2026-07-29T09:00:00Z",
    },
    {
        "id": "rule_4",
        "name": "Employee Onboarding Welcome Kit",
        "trigger_event": "EMPLOYEE_JOINED",
        "channels": ["EMAIL", "IN_APP"],
        "recipients": ["NEW_JOINER"],
        "template": "Welcome to Aurix AI, {{employee_name}}! Here is your onboarding portal guide.",
        "is_enabled": True,
        "delay_minutes": 0,
        "retry_count": 1,
        "last_triggered": "2026-07-25T10:15:00Z",
    },
]

BASE_ACTIVITY_LOGS = [
    {
        "id": "act_1",
        "trigger_time": "2026-07-29T11:00:00Z",
        "event": "PAYROLL_COMPLETED",
        "recipient": "142 Employees",
        "channel": "EMAIL",
        "status": "SUCCESS",
        "details": "Sent 142 PDF payslip emails cleanly.",
    },
    {
        "id": "act_2",
        "trigger_time": "2026-07-29T09:00:00Z",
        "event": "COMPLIANCE_DUE_SOON",
        "recipient": "finance@aurix.ai",
        "channel": "IN_APP",
        "status": "SUCCESS",
        "details": "Triggered EPFO ECR filing reminder notification.",
    },
    {
        "id": "act_3",
        "trigger_time": "2026-07-28T16:20:00Z",
        "event": "SALARY_DISBURSED",
        "recipient": "+919876543210",
        "channel": "SMS",
        "status": "FAILED",
        "details": "Gateway Timeout from SMS Provider. Retry required.",
    },
]

BASE_SCHEDULED_JOBS = [
    {
        "id": "job_1",
        "name": "Monthly EPFO ECR Pre-Filing Audit Scan",
        "next_run": "2026-08-10T00:00:00Z",
        "frequency": "MONTHLY",
        "status": "ACTIVE",
    },
    {
        "id": "job_2",
        "name": "Semi-Annual LWF Contribution Calculation",
        "next_run": "2026-12-01T00:00:00Z",
        "frequency": "SEMI_ANNUAL",
        "status": "ACTIVE",
    },
    {
        "id": "job_3",
        "name": "Daily Attendance & Overtime Sync Cron",
        "next_run": "2026-07-30T01:00:00Z",
        "frequency": "DAILY",
        "status": "ACTIVE",
    },
]


# ── DB-Backed Notification Endpoints (Thin Wrappers over notification_service) ─


@router.get("/notifications", response_model=APIResponse[dict], summary="Get all notifications")
@router.head("/notifications")
async def get_notifications(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
) -> APIResponse[dict]:
    cid = _get_cid(claims)
    uid = _get_uid(claims)
    res = await notification_service.list_notifications(
        session,
        company_id=cid,
        recipient_id=uid,
        limit=50,
    )
    return success_response(
        {
            "items": res["items"],
            "unread_count": res["totalUnread"],
            "total": len(res["items"]),
        },
        "Notifications retrieved successfully.",
    )


@router.post("/notifications/{notif_id}/read", response_model=APIResponse[dict], summary="Mark notification as read")
async def mark_notification_read(
    notif_id: str,
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
) -> APIResponse[dict]:
    cid = _get_cid(claims)
    uid = _get_uid(claims)
    try:
        nid = uuid.UUID(notif_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid notification ID.")
    item = await notification_service.mark_read(
        session,
        company_id=cid,
        recipient_id=uid,
        notification_id=nid,
    )
    return success_response({"id": notif_id}, "Notification marked as read.")


@router.post("/notifications/read-all", response_model=APIResponse[dict], summary="Mark all notifications as read")
async def mark_all_notifications_read(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
) -> APIResponse[dict]:
    cid = _get_cid(claims)
    uid = _get_uid(claims)
    res = await notification_service.mark_all_read(
        session,
        company_id=cid,
        recipient_id=uid,
    )
    return success_response({"status": "SUCCESS", "updatedCount": res["updatedCount"]}, "All notifications marked as read.")


@router.delete("/notifications/{notif_id}", response_model=APIResponse[dict], summary="Delete/Archive notification")
async def delete_notification(
    notif_id: str,
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
) -> APIResponse[dict]:
    cid = _get_cid(claims)
    uid = _get_uid(claims)
    try:
        nid = uuid.UUID(notif_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid notification ID.")
    await notification_service.archive_notification(
        session,
        company_id=cid,
        recipient_id=uid,
        notification_id=nid,
    )
    return success_response({"id": notif_id}, "Notification archived.")


# ── Automation Rules (Isolated mock data, admin-protected mutations) ─────────


@router.get("/automation-rules", response_model=APIResponse[dict], summary="List all automation rules")
@router.head("/automation-rules")
async def list_automation_rules(
    claims: dict = Depends(get_current_user_claims),
) -> APIResponse[dict]:
    return success_response({
        "items": copy.deepcopy(BASE_AUTOMATION_RULES),
        "total": len(BASE_AUTOMATION_RULES),
    }, "Automation rules retrieved successfully.")


@router.post("/automation-rules", status_code=201, response_model=APIResponse[dict], summary="Create automation rule")
async def create_automation_rule(
    payload: AutomationRulePayload,
    claims: dict = Depends(get_current_user_claims),
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    new_rule = {
        "id": f"rule_{uuid.uuid4().hex[:6]}",
        "name": payload.name,
        "trigger_event": payload.trigger_event,
        "channels": payload.channels,
        "recipients": payload.recipients,
        "template": payload.template,
        "is_enabled": payload.is_enabled,
        "delay_minutes": payload.delay_minutes,
        "retry_count": payload.retry_count,
        "last_triggered": None,
    }
    return success_response(new_rule, "Automation rule created successfully.")


@router.post("/automation-rules/{rule_id}/toggle", response_model=APIResponse[dict], summary="Toggle automation rule active status")
async def toggle_automation_rule(
    rule_id: str,
    claims: dict = Depends(get_current_user_claims),
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    rule = next((r for r in BASE_AUTOMATION_RULES if r["id"] == rule_id), None)
    if not rule:
        raise HTTPException(status_code=404, detail="Automation rule not found.")
    toggled = copy.deepcopy(rule)
    toggled["is_enabled"] = not toggled["is_enabled"]
    return success_response(toggled, f"Automation rule toggled to {toggled['is_enabled']}.")


@router.post("/automation-rules/{rule_id}/test", response_model=APIResponse[dict], summary="Trigger test notification for automation rule")
async def test_automation_rule(
    rule_id: str,
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    cid = _get_cid(claims)
    uid = _get_uid(claims)
    rule = next((r for r in BASE_AUTOMATION_RULES if r["id"] == rule_id), None)
    if not rule:
        raise HTTPException(status_code=404, detail="Automation rule not found.")

    created = await notification_service.notify(
        session,
        company_id=cid,
        recipient_ids=[uid],
        type="system.automation_test",
        category="system",
        module="automation",
        title=f"[TEST] {rule['name']}",
        body=f"Test trigger execution for event {rule['trigger_event']}.",
        link="/dashboard/settings",
        priority="low",
    )
    test_notif = notification_service.serialize_notification(created[0]) if created else {
        "id": f"notif_{uuid.uuid4().hex[:6]}",
        "title": f"[TEST] {rule['name']}",
        "body": f"Test trigger execution for event {rule['trigger_event']}.",
    }
    return success_response(test_notif, f"Test notification triggered for {rule['name']}.")


# ── Activity Logs ──────────────────────────────────────────────────────────


@router.get("/activity", response_model=APIResponse[dict], summary="Get automation activity logs")
async def get_automation_activity(
    claims: dict = Depends(get_current_user_claims),
) -> APIResponse[dict]:
    return success_response({
        "items": copy.deepcopy(BASE_ACTIVITY_LOGS),
        "total": len(BASE_ACTIVITY_LOGS),
    }, "Automation activity logs retrieved.")


@router.post("/activity/{act_id}/retry", response_model=APIResponse[dict], summary="Retry failed automation activity")
async def retry_automation_activity(
    act_id: str,
    claims: dict = Depends(get_current_user_claims),
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    act = next((a for a in BASE_ACTIVITY_LOGS if a["id"] == act_id), None)
    if not act:
        raise HTTPException(status_code=404, detail="Activity log entry not found.")

    # Return accurate retry queued response without falsely claiming production success
    retry_status = copy.deepcopy(act)
    retry_status["status"] = "RETRY_QUEUED"
    retry_status["details"] = "Retry request queued in mock test environment."
    return success_response(
        retry_status,
        "Retry request acknowledged (Mock environment - action not executed in production).",
    )


# ── Scheduled Jobs ─────────────────────────────────────────────────────────


@router.get("/scheduled-jobs", response_model=APIResponse[dict], summary="Get scheduled jobs calendar")
async def get_scheduled_jobs(
    claims: dict = Depends(get_current_user_claims),
) -> APIResponse[dict]:
    return success_response({
        "items": copy.deepcopy(BASE_SCHEDULED_JOBS),
        "total": len(BASE_SCHEDULED_JOBS),
    }, "Scheduled jobs retrieved.")


@router.post("/scheduled-jobs/{job_id}/toggle", response_model=APIResponse[dict], summary="Pause or resume scheduled job")
async def toggle_scheduled_job(
    job_id: str,
    claims: dict = Depends(get_current_user_claims),
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    job = next((j for j in BASE_SCHEDULED_JOBS if j["id"] == job_id), None)
    if not job:
        raise HTTPException(status_code=404, detail="Scheduled job not found.")
    toggled = copy.deepcopy(job)
    toggled["status"] = "PAUSED" if toggled["status"] == "ACTIVE" else "ACTIVE"
    return success_response(toggled, f"Job status updated to {toggled['status']}.")


# ── Notification Preferences ───────────────────────────────────────────────


@router.get("/preferences", response_model=APIResponse[dict], summary="Get notification preferences")
async def get_preferences(
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
) -> APIResponse[dict]:
    cid = _get_cid(claims)
    comp = await session.get(Company, cid)
    hr_settings = comp.hr_settings or {} if comp else {}
    prefs = hr_settings.get("global_notification_preferences") or {
        "sound_enabled": True,
        "desktop_enabled": True,
        "email_enabled": True,
        "sms_enabled": False,
        "push_enabled": True,
        "do_not_disturb": False,
        "priority_level": "ALL",
    }
    return success_response(prefs, "Notification preferences retrieved.")


@router.put("/preferences", response_model=APIResponse[dict], summary="Update notification preferences")
async def update_preferences(
    payload: PreferencesPayload,
    claims: dict = Depends(get_current_user_claims),
    session: AsyncSession = Depends(get_db_session),
) -> APIResponse[dict]:
    _require_admin_or_manager(claims)
    cid = _get_cid(claims)
    comp = await session.get(Company, cid)
    if not comp:
        raise HTTPException(status_code=404, detail="Company not found.")

    hr_settings = comp.hr_settings or {}
    hr_settings["global_notification_preferences"] = payload.model_dump()
    comp.hr_settings = hr_settings
    flag_modified(comp, "hr_settings")
    await session.commit()

    return success_response(payload.model_dump(), "Notification preferences updated successfully.")
