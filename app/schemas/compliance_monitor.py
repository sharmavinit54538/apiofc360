"""Pydantic schemas for AI Compliance Monitor module APIs."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class ComplianceCheckItem(BaseModel):
    """Specific compliance check result."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    category: str = Field("Labor Law", description="Check category e.g. Labor Law, Payroll, Attendance")
    check_name: str = Field("Working Hours & Overtime Limit", description="Check title")
    status: str = Field("PASSED", description="PASSED | FAILED | WARNING")
    description: str = Field("All employees are compliant with max 48 hours weekly limit.")
    affected_count: int = Field(0, description="Count of affected employees")
    severity: str = Field("LOW", description="LOW | MEDIUM | HIGH | CRITICAL")

    model_config = ConfigDict(from_attributes=True)


class LaborLawRule(BaseModel):
    """Labor law rule compliance status."""

    rule_name: str = Field("Minimum Wage Compliance", description="Rule title")
    jurisdiction: str = Field("Federal / State", description="Governing body")
    status: str = Field("COMPLIANT", description="COMPLIANT | NON_COMPLIANT | UNDER_REVIEW")
    details: str = Field("All active employee salaries exceed minimum wage thresholds.")
    recommendation: str = Field("Regular quarterly audit scheduled.")

    model_config = ConfigDict(from_attributes=True)


class MissingDocumentItem(BaseModel):
    """Missing or expired document item."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    employee_id: uuid.UUID
    employee_name: str
    department: str
    document_type: str = Field("Aadhaar / ID Proof", description="Document category")
    status: str = Field("MISSING", description="MISSING | EXPIRED | PENDING_VERIFICATION")
    due_date: str = Field("2026-08-01", description="Required upload date")

    model_config = ConfigDict(from_attributes=True)


class RiskItem(BaseModel):
    """Detected compliance risk item."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    risk_category: str = Field("Payroll Risk", description="Category of risk")
    title: str = Field("Unclaimed Statutory PF Contributions", description="Title")
    severity: str = Field("HIGH", description="LOW | MEDIUM | HIGH | CRITICAL")
    department: str = Field("Operations", description="Affected department")
    impact_score: float = Field(78.5, description="Impact score 0-100")
    recommendation: str = Field("Reconcile PF contribution statements with bank transfers.")

    model_config = ConfigDict(from_attributes=True)


class ComplianceAlertItem(BaseModel):
    """Critical compliance alert item."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str = Field("Contract Renewal Pending", description="Alert title")
    severity: str = Field("HIGH", description="CRITICAL | HIGH | MEDIUM | LOW")
    category: str = Field("Contracts", description="Alert category")
    message: str = Field("3 vendor employment contracts expire in less than 7 days.")
    timestamp: datetime = Field(default_factory=datetime.now)

    model_config = ConfigDict(from_attributes=True)


class ComplianceDashboardResponse(BaseModel):
    """Compliance Monitor Dashboard KPIs supporting dual camelCase and snake_case for frontend thunk fetchComplianceReport."""

    # camelCase properties for frontend thunk compatibility
    complianceScore: float = Field(92.5, description="Overall Compliance Score (0-100)")
    openRisks: int = Field(4, description="Open Compliance Risks Count")
    missingDocs: int = Field(12, description="Missing / Expired Documents Count")
    auditReadiness: str = Field("94.0%", description="Audit Readiness Percentage")
    complianceTrend: list[dict[str, Any]] = Field(default_factory=list)
    risksByCategory: list[dict[str, Any]] = Field(default_factory=list)
    complianceChecks: list[ComplianceCheckItem] = Field(default_factory=list)
    laborLawStatus: dict[str, Any] = Field(default_factory=dict)
    recommendations: list[str] = Field(default_factory=list)
    alerts: list[ComplianceAlertItem] = Field(default_factory=list)

    # Standard snake_case properties
    compliance_score: float = Field(92.5, description="Overall Compliance Score")
    open_risks: int = Field(4, description="Open Compliance Risks Count")
    missing_docs: int = Field(12, description="Missing / Expired Documents Count")
    audit_readiness: str = Field("94.0%", description="Audit Readiness Percentage")
    compliance_trend: list[dict[str, Any]] = Field(default_factory=list)
    risks_by_category: list[dict[str, Any]] = Field(default_factory=list)
    compliance_checks: list[ComplianceCheckItem] = Field(default_factory=list)
    labor_law_status: dict[str, Any] = Field(default_factory=dict)

    # Additional KPIs
    policy_violations: int = Field(1, description="Active Policy Violations")
    expired_documents: int = Field(3, description="Expired Documents Count")
    critical_risks: int = Field(1, description="Critical Severity Risks Count")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class ComplianceChecksResponse(BaseModel):
    """Compliance checks summary."""

    passed_checks: int = 18
    failed_checks: int = 2
    warning_checks: int = 4
    compliance_pct: float = 90.0
    checks: list[ComplianceCheckItem] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class LaborLawsResponse(BaseModel):
    """Labor law monitoring status."""

    overall_status: str = "COMPLIANT"
    violations_count: int = 1
    violations: list[dict[str, Any]] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    applicable_rules: list[LaborLawRule] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class MissingDocumentsResponse(BaseModel):
    """Missing & expired documents breakdown."""

    expired_count: int = 3
    missing_count: int = 9
    pending_verification_count: int = 4
    items: list[MissingDocumentItem] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class RiskDetectionResponse(BaseModel):
    """Compliance risk detection summary."""

    overall_risk_score: float = 14.5
    critical_risks_count: int = 1
    risks: list[RiskItem] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class AuditReadinessResponse(BaseModel):
    """Audit readiness breakdown."""

    readiness_pct: float = 94.0
    missing_evidence: list[str] = Field(default_factory=list)
    pending_actions: list[str] = Field(default_factory=list)
    checklist: list[dict[str, Any]] = Field(default_factory=list)
    timeline: list[dict[str, Any]] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class ComplianceAnalyticsResponse(BaseModel):
    """Compliance analytics across time and departments."""

    monthly_trend: list[dict[str, Any]] = Field(default_factory=list)
    department_compliance: list[dict[str, Any]] = Field(default_factory=list)
    policy_compliance: list[dict[str, Any]] = Field(default_factory=list)
    document_compliance: list[dict[str, Any]] = Field(default_factory=list)
    audit_performance: list[dict[str, Any]] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class ComplianceAlertsResponse(BaseModel):
    """List of compliance alerts."""

    alerts: list[ComplianceAlertItem] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class EmployeeComplianceDetailResponse(BaseModel):
    """Individual employee compliance detail."""

    employee_id: uuid.UUID
    employee_name: str
    department: str
    compliance_status: str = "COMPLIANT"
    missing_documents: list[str] = Field(default_factory=list)
    violations_count: int = 0
    risk_level: str = "LOW"
    recommendation: str = "Employee profile is 100% compliant."

    model_config = ConfigDict(from_attributes=True)


# Request Payloads
class AnalyzeCompliancePayload(BaseModel):
    """Payload to analyze organizational compliance."""

    department_id: Optional[uuid.UUID] = None


class AuditCompliancePayload(BaseModel):
    """Payload to run compliance audit."""

    audit_scope: str = Field("HR_POLICY", description="HR_POLICY | ATTENDANCE | PAYROLL | LABOR_LAW | DATA_PRIVACY")


class RiskAnalysisPayload(BaseModel):
    """Payload to run risk analysis."""

    department_id: Optional[uuid.UUID] = None
