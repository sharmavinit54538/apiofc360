"""Unified API v2 Router - Consolidates all v2 endpoints from fragmented router trees.

This module aggregates endpoints from:
- app/api/v2/ (versioned routes)
- app/api/v2/payroll/ (payroll submodule)

All routes are mounted under /api/v2 prefix in main.py
"""

from fastapi import APIRouter

# ── v2 Core Routers (from app/api/v2/) ───────────────────────────────────────
from app.api.v2.document_intelligence import router as doc_intel_router
from app.api.v2.employee_support import router as emp_support_router
from app.api.v2.interview_bot import router as interview_bot_router
from app.api.v2.hr_analytics_api import router as hr_analytics_router
from app.api.v2.hr_workflow_api import router as hr_workflow_router
from app.api.v2.payroll_api import router as payroll_router
from app.api.v2.tax_api import router as tax_router
from app.api.v2.performance_api import router as performance_router
from app.api.v2.policy_api import router as policy_router
from app.api.v2.wellness_api import router as wellness_router
from app.api.v2.travel_api import router as travel_router
from app.api.v2.reports_api import router as reports_router
from app.api.v2.productivity_api import router as productivity_router
from app.api.v2.goal_generator_api import router as goals_router
from app.api.v2.compensation_api import router as compensation_router
from app.api.v2.behavioural_api import router as behavioural_router
from app.api.v2.email_generator_api import router as email_router
from app.api.v2.emotion_chatbot_api import router as emotions_router
from app.api.v2.org_intelligence_apis import (
    org_map_router, 
    skill_gap_router, 
    shift_router, 
    digital_twin_router,
    org_twin_router
)
from app.api.v2.employee_intelligence_apis import (
    voice_router, 
    mood_router, 
    career_router, 
    learning_router
)
from app.api.v2.enterprise_intelligence_apis import (
    workforce_router, 
    talent_router, 
    meetings_router, 
    compliance_router, 
    risk_router, 
    copilot_router
)
from app.api.v2.hr_copilot import router as hr_copilot_router, ai_router as ai_decision_support_router
from app.api.v2.candidate_matching import router as candidate_matching_router
from app.api.v2.coding_assessment import router as coding_assessment_router
from app.api.v2.ranking import router as ranking_router
from app.api.v2.resume_parser import router as resume_parser_router
from app.api.v2.screening import router as screening_router
from app.api.v2.offer_letters import router as offer_letters_router
from app.api.v2.interview_agent import router as interview_agent_router
from app.api.v2.analytics import router as analytics_v2_router
from app.api.v2.resume_ats_checker import router as resume_ats_checker_router
from app.api.v2.dpdp_api import router as dpdp_router, employee_pii_router as dpdp_employee_pii_router
from app.api.v2.employee_bulk_api import router as employee_bulk_router
from app.api.v2.document_esign_api import router as document_esign_router
from app.api.v2.fnf_workflow_api import router as fnf_workflow_router
from app.api.v2.data_migration_api import router as data_migration_router
from app.api.v2.whatsapp_api import router as whatsapp_router
from app.api.v2.mobile_pwa_api import router as mobile_pwa_router
from app.api.v2.grievance_posh_api import router as grievance_posh_router
from app.api.v2.bgv_api import router as bgv_v2_router
from app.api.v2.succession_api import router as succession_v2_router
from app.api.v2.lms_api import router as lms_v2_router
from app.api.v2.engagement_api import router as engagement_v2_router
from app.api.v2.developer_api import router as developer_v2_router
from app.api.v2.scim_api import admin_router as scim_admin_v2_router
from app.api.v2.enterprise_intelligence_apis import ijp_router
from app.api.v2.marketplace_api import router as marketplace_v2_router
from app.api.v2.whitelabel_api import router as whitelabel_v2_router

# ── v2 Payroll Submodule ──────────────────────────────────────────────────────
from app.api.v2.payroll.router import router as payroll_v2_router


def get_v2_router() -> APIRouter:
    """Build and return the unified v2 router with all endpoints."""
    from fastapi import APIRouter
    
    router = APIRouter(prefix="/api/v2")
    
    # Main v2 endpoints
    for r in (
        doc_intel_router,
        emp_support_router,
        interview_bot_router,
        hr_analytics_router,
        hr_workflow_router,
        payroll_router,
        tax_router,
        performance_router,
        policy_router,
        wellness_router,
        travel_router,
        reports_router,
        productivity_router,
        goals_router,
        compensation_router,
        behavioural_router,
        email_router,
        emotions_router,
        org_map_router,
        skill_gap_router,
        shift_router,
        digital_twin_router,
        org_twin_router,
        voice_router,
        mood_router,
        career_router,
        learning_router,
        workforce_router,
        talent_router,
        meetings_router,
        compliance_router,
        risk_router,
        copilot_router,
        hr_copilot_router,
        ai_decision_support_router,
        candidate_matching_router,
        coding_assessment_router,
        ranking_router,
        resume_parser_router,
        screening_router,
        offer_letters_router,
        interview_agent_router,
        analytics_v2_router,
        resume_ats_checker_router,
        dpdp_router,
        dpdp_employee_pii_router,
        employee_bulk_router,
        document_esign_router,
        fnf_workflow_router,
        data_migration_router,
        whatsapp_router,
        mobile_pwa_router,
        grievance_posh_router,
        bgv_v2_router,
        succession_v2_router,
        lms_v2_router,
        engagement_v2_router,
        developer_v2_router,
        scim_admin_v2_router,
        ijp_router,
        marketplace_v2_router,
        whitelabel_v2_router,
    ):
        router.include_router(r)
    
    # Payroll v2 submodule
    router.include_router(payroll_v2_router, prefix="/payroll")
    
    return router


# ─────────────────────────────────────────────────────────────────────────────
# Module-level router instance for direct import
# ─────────────────────────────────────────────────────────────────────────────

v2_router = get_v2_router()

__all__ = ["v2_router", "get_v2_router"]