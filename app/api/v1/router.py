"""Unified API v1 Router - Consolidates all v1 endpoints from fragmented router trees.

This module aggregates endpoints from:
- app/api/ (legacy flat routes)
- app/api/v1/ (versioned routes)
- app/routers/ (core HRMS modules)
- app/attendance/routers/ (attendance module)
- app/api/v1/ai_hub/ (AI Hub Gateway)

All routes are mounted under /api/v1 prefix in main.py
"""

from fastapi import APIRouter

# ── Core HRMS Routers (from app/routers/) ──────────────────────────────────────
from app.routers import (
    attendance as core_attendance_router,
    analytics as core_analytics_router,
    settings as core_settings_router,
    performance as core_performance_router,
    users as core_users_router,
    profile as core_profile_router,
    departments as core_departments_router,
    compliance as core_compliance_router,
    employee_health as core_employee_health_router,
    leave_assistant as core_leave_assistant_router,
    meeting_intelligence as core_meeting_intelligence_router,
    performance_coach as core_performance_coach_router,
    recruiter as core_recruiter_router,
    workforce_insights as core_workforce_insights_router,
    managers as core_managers_router,
    policy_assistant as core_policy_assistant_router,
    reports as core_reports_router,
    notifications as core_notifications_router,
    documents as core_documents_router,
    assets as core_assets_router,
    holidays as core_holidays_router,
    dashboard as core_dashboard_router,
)

# ── Legacy Flat API Routers (from app/api/) ───────────────────────────────────
from app.api.auth import router as auth_router
from app.api.hr_admin import router as hr_admin_router
from app.api.employees import router as employees_router
from app.api.managers import router as managers_router
from app.api.exports import router as exports_router
from app.api.departments import router as departments_router
from app.api.jobs import router as jobs_router
from app.api.assets import router as assets_router
from app.api.timesheets import router as timesheets_router
from app.api.leaves import router as leaves_router
from app.api.careers import router as careers_router
from app.api.applications import router as applications_router
from app.api.interviews import router as interviews_router
from app.api.offers import router as offers_router
from app.api.exits import router as exits_router
from app.api.calendar import router as calendar_router
from app.api.documents import router as documents_router
from app.api.templates import router as templates_router
from app.api.announcements import router as announcements_router
from app.api.news import router as news_router
from app.api.events import router as events_router
from app.api.polls import router as polls_router
from app.api.internal_dashboard import router as internal_dashboard_router

# ── AI Module Routers (from app/api/v1/) ──────────────────────────────────────
from app.api.v1.ai import router as ai_router
from app.api.v1.ai_recruiter import router as ai_recruiter_router
from app.api.v1.ai_attendance import router as ai_attendance_router
from app.api.v1.ai_performance import router as ai_performance_router
from app.api.v1.ai_leave import router as ai_leave_router
from app.api.v1.ai_payroll import router as ai_payroll_router
from app.api.v1.ai_workforce import router as ai_workforce_router, ai_workforce_direct_router
from app.api.v1.employee_health import router as employee_health_router
from app.api.v1.policy_ai import router as policy_ai_router
from app.api.v1.meeting_ai import router as meeting_ai_router
from app.api.v1.compliance_monitor import router as compliance_monitor_router
from app.api.v1.reports import router as reports_v1_router
from app.api.v1.chat_assistant import router as chat_assistant_router
from app.api.v1.analytics_center import router as analytics_center_router
from app.api.v1.ai_brain import router as ai_brain_router
from app.api.v1.intelligence import router as intelligence_router
from app.api.v1.admissions import router as admissions_router
from app.api.v1.attendance import router as attendance_v1_router
from app.api.v1.cctv import router as cctv_router
from app.api.v1.dashboard import router as dashboard_router
from app.api.v1.documents import router as documents_v1_router
from app.api.v1.employee_health import router as employee_health_v1_router
from app.api.v1.face import router as face_router
from app.api.v1.fees import router as fees_router
from app.api.v1.intelligence import router as intelligence_v1_router
from app.api.v1.meeting_ai import router as meeting_ai_v1_router
from app.api.v1.parent import router as parent_router
from app.api.v1.policy_ai import router as policy_ai_v1_router
from app.api.v1.recognition import router as recognition_router
from app.api.v1.reports import router as reports_v1_router_alt
from app.api.v1.students import router as students_router
from app.api.v1.teachers import router as teachers_router
from app.api.v1.users import router as users_v1_router

# ── AI Hub Gateway Routers (from app/api/v1/ai_hub/) ──────────────────────────
from app.api.v1.ai_hub.root import router as ai_hub_root_router
from app.api.v1.ai_hub.agents import router as ai_hub_agents_router
from app.api.v1.ai_hub.analytics_center import router as ai_hub_analytics_router
from app.api.v1.ai_hub.attendance_monitor import router as ai_hub_attendance_router
from app.api.v1.ai_hub.chat_assistant import router as ai_hub_chat_router
from app.api.v1.ai_hub.compliance_monitor import router as ai_hub_compliance_router
from app.api.v1.ai_hub.document_generator import router as ai_hub_docgen_router
from app.api.v1.ai_hub.employee_health import router as ai_hub_health_router
from app.api.v1.ai_hub.leave_assistant import router as ai_hub_leave_router
from app.api.v1.ai_hub.meeting_intelligence import router as ai_hub_meeting_router
from app.api.v1.ai_hub.payroll_insights import router as ai_hub_payroll_router
from app.api.v1.ai_hub.performance_coach import router as ai_hub_performance_router
from app.api.v1.ai_hub.policy_assistant import router as ai_hub_policy_router
from app.api.v1.ai_hub.recruiter import router as ai_hub_recruiter_router
from app.api.v1.ai_hub.workforce import (
    insights_router as ai_hub_workforce_insights_router,
    planning_router as ai_hub_workforce_planning_router,
)

# ── Payroll Routers ────────────────────────────────────────────────────────────
from app.api.v1.payroll.router import router as v1_payroll_router
from app.api.payroll.router import router as full_payroll_router

# ── Additional v1 Routers ──────────────────────────────────────────────────────
from app.api.ai_copilot import router as ai_copilot_router
from app.api.ai_insights import router as ai_insights_router
from app.api.settings import router as settings_api_router
from app.api.billing import router as billing_router
from app.api.payments import router as payments_router
from app.api.sidebar import router as sidebar_router
from app.api.cto.dashboard import router as cto_dashboard_router
from app.api.super_admin import router as super_admin_router
from app.api.onboarding import router as onboarding_router
from app.api.employee_onboarding_api import router as employee_onboarding_api_router
from app.api.employee_onboarding_admin_api import router as employee_onboarding_admin_api_router
from app.api.hr_admin_onboarding import router as hr_admin_onboarding_router
from app.api.hierarchy import router as hierarchy_router
from app.api.talent_pool import router as talent_pool_router
from app.api.requisitions import router as requisitions_router
from app.api.vendors import router as vendors_router
from app.api.crm import router as crm_router
from app.api.referrals import router as referrals_router
from app.api.automation import router as automation_router
from app.api.scorecards import router as scorecards_router
from app.api.recruitment_analytics import router as recruitment_analytics_router
from app.api.recruitment import router as recruitment_router
from app.api.ats import router as ats_router
from app.api.global_notifications import router as global_notifications_router
from app.api.generate_api import router as generate_router
from app.api.connect import router as connect_router
from app.api.helpdesk import router as helpdesk_router

# ── Attendance Module Routers (from app/attendance/routers/) ───────────────────
from app.attendance.routers import router as attendance_router

# ─────────────────────────────────────────────────────────────────────────────
# Unified Router Assembly
# ─────────────────────────────────────────────────────────────────────────────

def get_v1_router() -> APIRouter:
    """Build and return the unified v1 router with all endpoints."""
    from fastapi import APIRouter
    
    router = APIRouter(prefix="/api/v1")
    
    # Core HRMS Modules (from app/routers/)
    for r in (
        core_attendance_router.router,
        core_analytics_router.router,
        core_settings_router.router,
        core_performance_router.router,
        core_users_router.router,
        core_profile_router.router,
        core_departments_router.router,
        core_compliance_router.router,
        core_employee_health_router.router,
        core_leave_assistant_router.router,
        core_meeting_intelligence_router.router,
        core_performance_coach_router.router,
        core_recruiter_router.router,
        core_workforce_insights_router.router,
        core_managers_router.router,
        core_policy_assistant_router.router,
        core_reports_router.router,
        core_notifications_router.router,
        core_documents_router.router,
        core_assets_router.router,
        core_holidays_router.router,
        core_dashboard_router.router,
    ):
        router.include_router(r)
    
    # Legacy Flat API Routes
    for r in (
        auth_router,
        hr_admin_router,
        employees_router,
        managers_router,
        exports_router,
        departments_router,
        jobs_router,
        assets_router,
        timesheets_router,
        leaves_router,
        careers_router,
        applications_router,
        interviews_router,
        offers_router,
        exits_router,
        calendar_router,
        documents_router,
        templates_router,
        announcements_router,
        news_router,
        events_router,
        polls_router,
        internal_dashboard_router,
        attendance_router,  # from app/attendance/routers/
    ):
        router.include_router(r)
    
    # AI Module Routes
    router.include_router(chat_assistant_router, prefix="/ai/chat")
    for r in (
        ai_copilot_router,
        ai_router,
        ai_recruiter_router,
        ai_attendance_router,
        ai_performance_router,
        ai_leave_router,
        ai_payroll_router,
        v1_payroll_router,
        full_payroll_router,
        ai_workforce_router,
        ai_workforce_direct_router,
        employee_health_router,
        policy_ai_router,
        meeting_ai_router,
        compliance_monitor_router,
        analytics_center_router,
        ai_brain_router,
        ai_insights_router,
        intelligence_router,
        onboarding_router,
        employee_onboarding_api_router,
        employee_onboarding_admin_api_router,
        hr_admin_onboarding_router,
        hierarchy_router,
        talent_pool_router,
        requisitions_router,
        vendors_router,
        crm_router,
        referrals_router,
        automation_router,
        scorecards_router,
        recruitment_analytics_router,
        recruitment_router,
        ats_router,
        global_notifications_router,
        generate_router,
        connect_router,
        helpdesk_router,
        reports_v1_router,
    ):
        router.include_router(r)
    
    # AI Hub Gateway (/api/v1/ai-hub/*)
    for r in (
        ai_hub_root_router,
        ai_hub_agents_router,
        ai_hub_analytics_router,
        ai_hub_attendance_router,
        ai_hub_chat_router,
        ai_hub_compliance_router,
        ai_hub_docgen_router,
        ai_hub_health_router,
        ai_hub_leave_router,
        ai_hub_meeting_router,
        ai_hub_payroll_router,
        ai_hub_performance_router,
        ai_hub_policy_router,
        ai_hub_recruiter_router,
        ai_hub_workforce_insights_router,
        ai_hub_workforce_planning_router,
    ):
        router.include_router(r)
    
    # Additional v1 routes from app/api/v1/
    for r in (
        admissions_router,
        attendance_v1_router,
        cctv_router,
        dashboard_router,
        documents_v1_router,
        employee_health_v1_router,
        face_router,
        fees_router,
        intelligence_v1_router,
        meeting_ai_v1_router,
        parent_router,
        policy_ai_v1_router,
        recognition_router,
        reports_v1_router,
        students_router,
        teachers_router,
        users_v1_router,
    ):
        router.include_router(r)
    
    return router


# ─────────────────────────────────────────────────────────────────────────────
# Module-level router instance for direct import
# ─────────────────────────────────────────────────────────────────────────────

v1_router = get_v1_router()

__all__ = ["v1_router", "get_v1_router"]