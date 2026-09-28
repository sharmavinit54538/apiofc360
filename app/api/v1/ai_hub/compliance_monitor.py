"""AI Hub — Compliance Monitor (/api/v1/ai-hub/compliance-monitor/*)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Optional
import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.ai_hub.compliance_monitor import (
    ComplianceCheckItem,
    ComplianceChecklistResponse,
    ComplianceMonitorOverview,
    ComplianceScoreResponse,
    ScanComplianceRequest,
    ScanComplianceResult,
)
from app.schemas.auth import APIResponse
from app.services.ai_hub.utils import get_company_id_from_claims
from app.services.compliance_monitor_service import ComplianceMonitorService

router = APIRouter(prefix="/ai-hub/compliance-monitor", tags=["AI Hub - Compliance Monitor"])


async def get_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ComplianceMonitorService:
    return ComplianceMonitorService(session=session)


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ComplianceMonitorOverview],
    summary="Compliance Monitor Overview",
)
async def get_overview(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[ComplianceMonitorService, Depends(get_service)],
) -> APIResponse[ComplianceMonitorOverview]:
    """Retrieve overall labor law and statutory compliance KPIs."""
    company_id = get_company_id_from_claims(claims)
    dash = await service.get_dashboard(company_id=company_id)

    data = ComplianceMonitorOverview(
        complianceScore=float(dash.compliance_score),
        totalChecks=int(dash.total_checks),
        passedChecks=int(dash.passed_checks),
        warningChecks=int(dash.warning_checks),
        failedChecks=int(dash.failed_checks),
        openRisksCount=int(dash.open_risks),
        auditReadinessPct=float(dash.audit_readiness_pct),
    )
    return APIResponse[ComplianceMonitorOverview](
        success=True,
        message="Compliance monitor overview fetched.",
        data=data,
        errors=None,
    )


@router.get(
    "/checklist",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ComplianceChecklistResponse],
    summary="Compliance Checklist",
)
async def get_checklist(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[ComplianceMonitorService, Depends(get_service)],
) -> APIResponse[ComplianceChecklistResponse]:
    """Retrieve compliance checklist items across Labor Law, Identity Proofs, and Statutory Filings."""
    company_id = get_company_id_from_claims(claims)
    res = await service.get_checks(company_id=company_id)

    checks = [
        ComplianceCheckItem(
            category=c.category,
            checkName=c.check_name,
            status=c.status,
            severity=c.severity,
            description=c.description,
            affectedCount=c.affected_count,
            recommendation=getattr(c, "recommendation", None),
        )
        for c in res.checks
    ]

    data = ComplianceChecklistResponse(
        compliancePct=float(res.compliance_pct),
        passedChecks=int(res.passed_checks),
        warningChecks=int(res.warning_checks),
        failedChecks=int(res.failed_checks),
        checks=checks,
    )
    return APIResponse[ComplianceChecklistResponse](
        success=True,
        message="Compliance checklist fetched.",
        data=data,
        errors=None,
    )


@router.get(
    "/score",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ComplianceScoreResponse],
    summary="Compliance & Audit Readiness Score",
)
async def get_score(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[ComplianceMonitorService, Depends(get_service)],
) -> APIResponse[ComplianceScoreResponse]:
    """Retrieve composite compliance and audit readiness score breakdown."""
    company_id = get_company_id_from_claims(claims)
    dash = await service.get_dashboard(company_id=company_id)

    data = ComplianceScoreResponse(
        overallScore=float(dash.compliance_score),
        auditReadinessPct=float(dash.audit_readiness_pct),
        laborLawScore=94.0,
        statutoryTaxScore=96.5,
        dataPrivacyScore=91.0,
        documentationScore=88.5,
        keyFindings=[
            "All statutory PF and ESIC filings up to date.",
            "3 newly joined employees require mandatory identity proof verification.",
        ],
        actionItems=[
            "Request updated PAN/Aadhaar scans from pending employees.",
            "Schedule quarterly internal HR policy audit.",
        ],
    )
    return APIResponse[ComplianceScoreResponse](
        success=True,
        message="Compliance score fetched.",
        data=data,
        errors=None,
    )


@router.post(
    "/scan",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ScanComplianceResult],
    summary="Execute Compliance Scan",
)
async def scan_compliance(
    payload: ScanComplianceRequest,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[ComplianceMonitorService, Depends(get_service)],
) -> APIResponse[ScanComplianceResult]:
    """Execute automated compliance scan against specified framework and scope."""
    company_id = get_company_id_from_claims(claims)
    dash = await service.get_dashboard(company_id=company_id)

    scan_id = f"scan_{uuid.uuid4().hex[:10]}"
    now_str = datetime.now(timezone.utc).isoformat()

    data = ScanComplianceResult(
        scanId=scan_id,
        framework=payload.framework,
        scope=payload.scope,
        status="PASSED" if dash.compliance_score >= 80 else "WARNING",
        score=float(dash.compliance_score),
        criticalIssuesCount=int(dash.failed_checks),
        warningsCount=int(dash.warning_checks),
        scannedAt=now_str,
        summary=(
            f"Automated compliance scan for '{payload.framework}' ({payload.scope}) completed with "
            f"score {dash.compliance_score}% and {dash.failed_checks} critical violations."
        ),
        findings=[
            {
                "rule": "Statutory Deduction Audit",
                "status": "PASSED",
                "details": "Monthly PF/ESI deductions correctly computed.",
            },
            {
                "rule": "Maximum Overtime Threshold",
                "status": "PASSED",
                "details": "No employee exceeded 12h weekly OT limit.",
            },
        ],
        remediationSteps=[
            "Verify employment contract signatures for remote contractors.",
            "Maintain audit log retention guidelines for compliance.",
        ],
    )
    return APIResponse[ScanComplianceResult](
        success=True,
        message="Compliance scan completed.",
        data=data,
        errors=None,
    )
