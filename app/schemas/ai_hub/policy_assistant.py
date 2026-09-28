"""Schemas for AI Hub Policy Assistant module."""

from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field


class PolicyAssistantOverview(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    totalPoliciesIndexed: int
    totalPolicyChunks: int
    recentQueriesCount: int
    coverageCategories: list[str] = Field(default_factory=list)
    topQueriedTopics: list[str] = Field(default_factory=list)


class AskPolicyRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    question: str
    department: Optional[str] = None
    jurisdiction: Optional[str] = None


class PolicyCitation(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    documentTitle: str
    section: Optional[str] = None
    page: Optional[int] = None
    similarity: float = 0.95


class AskPolicyResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    question: str
    answer: str
    department: Optional[str] = None
    jurisdiction: Optional[str] = None
    citations: list[PolicyCitation] = Field(default_factory=list)
    followUpSuggestions: list[str] = Field(default_factory=list)


class CheckPolicyComplianceRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    documentText: Optional[str] = None
    documentUrl: Optional[str] = None
    policyId: Optional[str] = None
    standard: Optional[str] = None


class PolicyComplianceFinding(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    clause: str
    status: str  # COMPLIANT, NON_COMPLIANT, PARTIAL
    finding: str
    recommendation: Optional[str] = None


class CheckPolicyComplianceResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    overallStatus: str  # COMPLIANT, WARNING, NON_COMPLIANT
    complianceScore: float
    standardOrPolicy: str
    findingsCount: int
    findings: list[PolicyComplianceFinding] = Field(default_factory=list)
    summary: str
