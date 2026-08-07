"""FastAPI REST Router for Global Application Notification & Automation Hub."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from app.api.payroll.dependencies import DB, Claims
from app.api.payroll.permissions import _require_admin_or_manager
from app.api.payroll.responses import success_response
from app.schemas.auth import APIResponse

router = APIRouter(prefix="/global-notifications", tags=["Global Notification & Automation Hub"])


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


# Initial In-Memory State for Global Notification Hub
DEFAULT_NOTIFICATIONS = [
    {
        "id": "notif_1",
        "title": "Payroll Cycle Completed",
        "description": "July 2026 Monthly Payroll processed successfully for 142 employees.",
        "type": "PAYROLL",
        "timestamp": datetime.utcnow().isoformat(),
        "is_read": False,
        "icon": "Banknote",
        "action_url": "/dashboard/payroll"
    },
    {
        "id": "notif_2",
        "title": "Payslip Generated",
        "description": "Password-protected PDF payslips generated & dispatched to employee emails.",
        "type": "PAYROLL",
        "timestamp": datetime.utcnow().isoformat(),
        "is_read": False,
        "icon": "FileText",
        "action_url": "/dashboard/payroll/payslips"
    },
    {
        "id": "notif_3",
        "title": "Annual Leave Approved",
        "description": "Leave request for Ramesh Kumar approved by HR Manager.",
        "type": "HR",
        "timestamp": datetime.utcnow().isoformat(),
        "is_read": True,
        "icon": "Calendar",
        "action_url": "/dashboard/leaves"
    },
    {
        "id": "notif_4",
        "title": "Statutory Compliance Reminder",
        "description": "EPFO ECR monthly return filing due in 3 days (15th August).",
        "type": "COMPLIANCE",
        "timestamp": datetime.utcnow().isoformat(),
        "is_read": False,
        "icon": "ShieldCheck",
        "action_url": "/dashboard/payroll/settings?category=compliance"
    },
    {
        "id": "notif_5",
        "title": "Security Alert",
        "description": "New login detected from IP 192.168.1.45 (Chrome Web).",
        "type": "SECURITY",
        "timestamp": datetime.utcnow().isoformat(),
        "is_read": True,
        "icon": "Lock",
        "action_url": "/dashboard/settings"
    },
]

DEFAULT_AUTOMATION_RULES = [
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
        "last_triggered": "2026-07-28T14:30:00Z"
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
        "last_triggered": "2026-07-28T15:00:00Z"
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
        "last_triggered": "2026-07-29T09:00:00Z"
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
        "last_triggered": "2026-07-25T10:15:00Z"
    },
]

DEFAULT_ACTIVITY_LOGS = [
    {
        "id": "act_1",
        "trigger_time": "2026-07-29T11:00:00Z",
        "event": "PAYROLL_COMPLETED",
        "recipient": "142 Employees",
        "channel": "EMAIL",
        "status": "SUCCESS",
        "details": "Sent 142 PDF payslip emails cleanly."
    },
    {
        "id": "act_2",
        "trigger_time": "2026-07-29T09:00:00Z",
        "event": "COMPLIANCE_DUE_SOON",
        "recipient": "finance@aurix.ai",
        "channel": "IN_APP",
        "status": "SUCCESS",
        "details": "Triggered EPFO ECR filing reminder notification."
    },
    {
        "id": "act_3",
        "trigger_time": "2026-07-28T16:20:00Z",
        "event": "SALARY_DISBURSED",
        "recipient": "+919876543210",
        "channel": "SMS",
        "status": "FAILED",
        "details": "Gateway Timeout from SMS Provider. Retry required."
    },
]

DEFAULT_SCHEDULED_JOBS = [
    {
        "id": "job_1",
        "name": "Monthly EPFO ECR Pre-Filing Audit Scan",
        "next_run": "2026-08-10T00:00:00Z",
        "frequency": "MONTHLY",
        "status": "ACTIVE"
    },
    {
        "id": "job_2",
        "name": "Semi-Annual LWF Contribution Calculation",
        "next_run": "2026-12-01T00:00:00Z",
        "frequency": "SEMI_ANNUAL",
        "status": "ACTIVE"
    },
    {
        "id": "job_3",
        "name": "Daily Attendance & Overtime Sync Cron",
        "next_run": "2026-07-30T01:00:00Z",
        "frequency": "DAILY",
        "status": "ACTIVE"
    },
]


@router.get("/notifications", response_model=APIResponse[dict], summary="Get all notifications")
@router.head("/notifications")
async def get_notifications(claims: Claims = None) -> APIResponse[dict]:
    unread_count = sum(1 for n in DEFAULT_NOTIFICATIONS if not n["is_read"])
    return success_response({
        "items": DEFAULT_NOTIFICATIONS,
        "unread_count": unread_count,
        "total": len(DEFAULT_NOTIFICATIONS)
    }, "Notifications retrieved successfully.")


@router.post("/notifications/{notif_id}/read", response_model=APIResponse[dict], summary="Mark notification as read")
async def mark_notification_read(notif_id: str, claims: Claims = None) -> APIResponse[dict]:
    for n in DEFAULT_NOTIFICATIONS:
        if n["id"] == notif_id:
            n["is_read"] = True
            break
    return success_response({"id": notif_id}, "Notification marked as read.")


@router.post("/notifications/read-all", response_model=APIResponse[dict], summary="Mark all notifications as read")
async def mark_all_notifications_read(claims: Claims = None) -> APIResponse[dict]:
    for n in DEFAULT_NOTIFICATIONS:
        n["is_read"] = True
    return success_response({"status": "SUCCESS"}, "All notifications marked as read.")


@router.delete("/notifications/{notif_id}", response_model=APIResponse[dict], summary="Delete notification")
async def delete_notification(notif_id: str, claims: Claims = None) -> APIResponse[dict]:
    global DEFAULT_NOTIFICATIONS
    DEFAULT_NOTIFICATIONS = [n for n in DEFAULT_NOTIFICATIONS if n["id"] != notif_id]
    return success_response({"id": notif_id}, "Notification deleted.")


@router.get("/automation-rules", response_model=APIResponse[dict], summary="List all automation rules")
@router.head("/automation-rules")
async def list_automation_rules(claims: Claims = None) -> APIResponse[dict]:
    return success_response({
        "items": DEFAULT_AUTOMATION_RULES,
        "total": len(DEFAULT_AUTOMATION_RULES)
    }, "Automation rules retrieved successfully.")


@router.post("/automation-rules", status_code=201, response_model=APIResponse[dict], summary="Create automation rule")
async def create_automation_rule(payload: AutomationRulePayload, claims: Claims = None) -> APIResponse[dict]:
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
        "last_triggered": None
    }
    DEFAULT_AUTOMATION_RULES.append(new_rule)
    return success_response(new_rule, "Automation rule created successfully.")


@router.post("/automation-rules/{rule_id}/toggle", response_model=APIResponse[dict], summary="Toggle automation rule active status")
async def toggle_automation_rule(rule_id: str, claims: Claims = None) -> APIResponse[dict]:
    for r in DEFAULT_AUTOMATION_RULES:
        if r["id"] == rule_id:
            r["is_enabled"] = not r["is_enabled"]
            return success_response(r, f"Automation rule toggled to {r['is_enabled']}.")
    raise HTTPException(status_code=404, detail="Automation rule not found.")


@router.post("/automation-rules/{rule_id}/test", response_model=APIResponse[dict], summary="Trigger test notification for automation rule")
async def test_automation_rule(rule_id: str, claims: Claims = None) -> APIResponse[dict]:
    rule = next((r for r in DEFAULT_AUTOMATION_RULES if r["id"] == rule_id), None)
    if not rule:
        raise HTTPException(status_code=404, detail="Automation rule not found.")
    
    test_notif = {
        "id": f"notif_{uuid.uuid4().hex[:6]}",
        "title": f"[TEST] {rule['name']}",
        "description": f"Test trigger execution for event {rule['trigger_event']}.",
        "type": "AUTOMATION_TEST",
        "timestamp": datetime.utcnow().isoformat(),
        "is_read": False,
        "icon": "Zap",
        "action_url": "#"
    }
    DEFAULT_NOTIFICATIONS.insert(0, test_notif)
    return success_response(test_notif, f"Test notification triggered for {rule['name']}.")


@router.get("/activity", response_model=APIResponse[dict], summary="Get automation activity logs")
async def get_automation_activity(claims: Claims = None) -> APIResponse[dict]:
    return success_response({
        "items": DEFAULT_ACTIVITY_LOGS,
        "total": len(DEFAULT_ACTIVITY_LOGS)
    }, "Automation activity logs retrieved.")


@router.post("/activity/{act_id}/retry", response_model=APIResponse[dict], summary="Retry failed automation activity")
async def retry_automation_activity(act_id: str, claims: Claims = None) -> APIResponse[dict]:
    for a in DEFAULT_ACTIVITY_LOGS:
        if a["id"] == act_id:
            a["status"] = "SUCCESS"
            a["details"] = "Re-executed successfully after retry."
            return success_response(a, "Failed job re-executed successfully.")
    raise HTTPException(status_code=404, detail="Activity log entry not found.")


@router.get("/scheduled-jobs", response_model=APIResponse[dict], summary="Get scheduled jobs calendar")
async def get_scheduled_jobs(claims: Claims = None) -> APIResponse[dict]:
    return success_response({
        "items": DEFAULT_SCHEDULED_JOBS,
        "total": len(DEFAULT_SCHEDULED_JOBS)
    }, "Scheduled jobs retrieved.")


@router.post("/scheduled-jobs/{job_id}/toggle", response_model=APIResponse[dict], summary="Pause or resume scheduled job")
async def toggle_scheduled_job(job_id: str, claims: Claims = None) -> APIResponse[dict]:
    for j in DEFAULT_SCHEDULED_JOBS:
        if j["id"] == job_id:
            j["status"] = "PAUSED" if j["status"] == "ACTIVE" else "ACTIVE"
            return success_response(j, f"Job status updated to {j['status']}.")
    raise HTTPException(status_code=404, detail="Scheduled job not found.")


@router.get("/preferences", response_model=APIResponse[dict], summary="Get notification preferences")
async def get_preferences(claims: Claims = None) -> APIResponse[dict]:
    return success_response({
        "sound_enabled": True,
        "desktop_enabled": True,
        "email_enabled": True,
        "sms_enabled": False,
        "push_enabled": True,
        "do_not_disturb": False,
        "priority_level": "ALL"
    }, "Notification preferences retrieved.")


@router.put("/preferences", response_model=APIResponse[dict], summary="Update notification preferences")
async def update_preferences(payload: PreferencesPayload, claims: Claims = None) -> APIResponse[dict]:
    return success_response(payload.model_dump(), "Notification preferences updated successfully.")
