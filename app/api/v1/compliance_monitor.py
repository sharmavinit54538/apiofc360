"""FastAPI router for AI Compliance Monitor endpoints (/api/v1/ai/compliance/*)."""

from __future__ import annotations

import uuid
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.auth import APIResponse
from app.schemas.compliance_monitor import (
    AnalyzeCompliancePayload,
    AuditCompliancePayload,
    AuditReadinessResponse,
    ComplianceAlertsResponse,
    ComplianceAnalyticsResponse,
    ComplianceChecksResponse,
    ComplianceDashboardResponse,
    EmployeeComplianceDetailResponse,
    LaborLawsResponse,
    MissingDocumentsResponse,
    RiskAnalysisPayload,
    RiskDetectionResponse,
)
from app.services.compliance_monitor_service import ComplianceMonitorService

router = APIRouter(prefix="/ai/compliance", tags=["AI Compliance Monitor"])


async def get_compliance_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ComplianceMonitorService:
    return ComplianceMonitorService(session=session)


def get_company_id_from_claims(claims: dict) -> Optional[uuid.UUID]:
    co_id_str = claims.get("company_id") if isinstance(claims, dict) else None
    return uuid.UUID(str(co_id_str)) if co_id_str else None


@router.get(
    "/dashboard",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ComplianceDashboardResponse],
    summary="Get AI Compliance Monitor Dashboard KPIs",
)
async def get_compliance_dashboard(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[ComplianceMonitorService, Depends(get_compliance_service)],
) -> APIResponse[ComplianceDashboardResponse]:
    """Retrieve dynamic compliance KPIs: Compliance Score, Open Risks, Missing Documents, Audit Readiness %, Labor Law status, and frontend thunk fields (complianceScore, openRisks, missingDocs, auditReadiness)."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_dashboard(company_id=company_id)
    return APIResponse[ComplianceDashboardResponse](
        success=True,
        message="Compliance monitor dashboard fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/checks",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ComplianceChecksResponse],
    summary="Get Compliance Checks Status",
)
async def get_compliance_checks(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[ComplianceMonitorService, Depends(get_compliance_service)],
) -> APIResponse[ComplianceChecksResponse]:
    """Retrieve passed, failed, warning compliance checks count and breakdown."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_checks(company_id=company_id)
    return APIResponse[ComplianceChecksResponse](
        success=True,
        message="Compliance checks fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/labor-laws",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[LaborLawsResponse],
    summary="Get Labor Law Monitoring",
)
async def get_labor_laws(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[ComplianceMonitorService, Depends(get_compliance_service)],
) -> APIResponse[LaborLawsResponse]:
    """Retrieve labor law rule checks, minimum wage compliance, overtime caps, and statutory benefit rules."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_labor_laws(company_id=company_id)
    return APIResponse[LaborLawsResponse](
        success=True,
        message="Labor law monitoring status fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/missing-documents",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[MissingDocumentsResponse],
    summary="Get Missing & Expired Documents",
)
async def get_missing_documents(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[ComplianceMonitorService, Depends(get_compliance_service)],
) -> APIResponse[MissingDocumentsResponse]:
    """Detect expired, missing, or pending verification employee identity & contract documents."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_missing_documents(company_id=company_id)
    return APIResponse[MissingDocumentsResponse](
        success=True,
        message="Missing documents detected successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/risks",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[RiskDetectionResponse],
    summary="Get Compliance Risk Detection",
)
async def get_compliance_risks(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[ComplianceMonitorService, Depends(get_compliance_service)],
) -> APIResponse[RiskDetectionResponse]:
    """Retrieve AI-detected compliance risks across payroll, attendance, missing documents, and policy gaps."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_risks(company_id=company_id)
    return APIResponse[RiskDetectionResponse](
        success=True,
        message="Compliance risks fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/audit-readiness",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[AuditReadinessResponse],
    summary="Get Audit Readiness",
)
async def get_audit_readiness(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[ComplianceMonitorService, Depends(get_compliance_service)],
) -> APIResponse[AuditReadinessResponse]:
    """Retrieve audit readiness %, missing evidence list, pending actions, and audit timeline."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_audit_readiness(company_id=company_id)
    return APIResponse[AuditReadinessResponse](
        success=True,
        message="Audit readiness fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/analytics",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ComplianceAnalyticsResponse],
    summary="Get Compliance Analytics",
)
async def get_compliance_analytics(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[ComplianceMonitorService, Depends(get_compliance_service)],
) -> APIResponse[ComplianceAnalyticsResponse]:
    """Retrieve monthly compliance score trends, department compliance, policy compliance, and audit scores."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_analytics(company_id=company_id)
    return APIResponse[ComplianceAnalyticsResponse](
        success=True,
        message="Compliance analytics fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/alerts",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ComplianceAlertsResponse],
    summary="Get Critical Compliance Alerts",
)
async def get_compliance_alerts(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[ComplianceMonitorService, Depends(get_compliance_service)],
) -> APIResponse[ComplianceAlertsResponse]:
    """Retrieve critical compliance alerts, document expiration notices, and high risk notifications."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_alerts(company_id=company_id)
    return APIResponse[ComplianceAlertsResponse](
        success=True,
        message="Compliance alerts fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/report",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ComplianceDashboardResponse],
    summary="Get Comprehensive Compliance Report",
)
async def get_compliance_report(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[ComplianceMonitorService, Depends(get_compliance_service)],
) -> APIResponse[ComplianceDashboardResponse]:
    """Retrieve full compliance report matching frontend thunk fetchComplianceReport."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_report(company_id=company_id)
    return APIResponse[ComplianceDashboardResponse](
        success=True,
        message="Compliance report fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/employee/{employee_id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[EmployeeComplianceDetailResponse],
    summary="Get Employee Compliance Details",
)
async def get_employee_compliance_detail(
    employee_id: uuid.UUID,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[ComplianceMonitorService, Depends(get_compliance_service)],
) -> APIResponse[EmployeeComplianceDetailResponse]:
    """Retrieve specific employee document compliance, violation history, and risk level."""
    data = await service.get_employee_compliance_detail(employee_id=employee_id)
    return APIResponse[EmployeeComplianceDetailResponse](
        success=True,
        message="Employee compliance details fetched successfully.",
        data=data,
        errors=None,
    )


@router.post(
    "/analyze",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ComplianceDashboardResponse],
    summary="Analyze Compliance via AI Engine",
)
async def analyze_compliance(
    payload: AnalyzeCompliancePayload,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[ComplianceMonitorService, Depends(get_compliance_service)],
) -> APIResponse[ComplianceDashboardResponse]:
    """Trigger AI LLM organizational compliance analysis."""
    company_id = get_company_id_from_claims(claims)
    data = await service.analyze_compliance(company_id=company_id)
    return APIResponse[ComplianceDashboardResponse](
        success=True,
        message="Compliance analysis completed successfully.",
        data=data,
        errors=None,
    )


@router.post(
    "/audit",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ComplianceDashboardResponse],
    summary="Run AI Compliance Audit",
)
async def run_compliance_audit(
    payload: AuditCompliancePayload,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[ComplianceMonitorService, Depends(get_compliance_service)],
) -> APIResponse[ComplianceDashboardResponse]:
    """Run automated compliance audit for specified audit scope."""
    company_id = get_company_id_from_claims(claims)
    data = await service.run_audit(payload=payload, company_id=company_id)
    return APIResponse[ComplianceDashboardResponse](
        success=True,
        message="Compliance audit completed successfully.",
        data=data,
        errors=None,
    )


@router.post(
    "/risk-analysis",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[RiskDetectionResponse],
    summary="Run AI Risk Analysis",
)
async def run_risk_analysis(
    payload: RiskAnalysisPayload,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[ComplianceMonitorService, Depends(get_compliance_service)],
) -> APIResponse[RiskDetectionResponse]:
    """Run AI risk detection engine across company departments."""
    company_id = get_company_id_from_claims(claims)
    data = await service.run_risk_analysis(company_id=company_id)
    return APIResponse[RiskDetectionResponse](
        success=True,
        message="Risk analysis completed successfully.",
        data=data,
        errors=None,
    )
