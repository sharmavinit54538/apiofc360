"""Schemas for AI Hub Compliance Monitor module."""

from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field


class ComplianceMonitorOverview(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    complianceScore: float
    totalChecks: int
    passedChecks: int
    warningChecks: int
    failedChecks: int
    openRisksCount: int
    auditReadinessPct: float


class ComplianceCheckItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    category: str
    checkName: str
    status: str  # PASSED, WARNING, FAILED
    severity: str  # LOW, MEDIUM, HIGH, CRITICAL
    description: str
    affectedCount: int = 0
    recommendation: Optional[str] = None


class ComplianceChecklistResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    compliancePct: float
    passedChecks: int
    warningChecks: int
    failedChecks: int
    checks: list[ComplianceCheckItem] = Field(default_factory=list)


class ComplianceScoreResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    overallScore: float
    auditReadinessPct: float
    laborLawScore: float
    statutoryTaxScore: float
    dataPrivacyScore: float
    documentationScore: float
    keyFindings: list[str] = Field(default_factory=list)
    actionItems: list[str] = Field(default_factory=list)


class ScanComplianceRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    framework: str
    scope: str
    fullScan: bool = True


class ScanComplianceResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    scanId: str
    framework: str
    scope: str
    status: str
    score: float
    criticalIssuesCount: int
    warningsCount: int
    scannedAt: str
    summary: str
    findings: list[dict[str, Any]] = Field(default_factory=list)
    remediationSteps: list[str] = Field(default_factory=list)
