"""Service handling statutory compliance, Form 16, and tax declarations."""
from __future__ import annotations

import uuid
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession


class ComplianceService:
    """Business logic for statutory rules, PF/ESI/PT, and Form 16."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_statutory_config(self) -> dict:
        """Fetch current statutory compliance configuration."""
        return {
            "pf_enabled": True,
            "esi_enabled": True,
            "pt_enabled": True,
            "tds_enabled": True,
        }

    async def get_compliance_dashboard(self) -> dict:
        """Fetch statutory compliance dashboard summary and module statuses."""
        return {
            "summary": {
                "overallScore": 98.5,
                "status": "COMPLIANT",
                "activeModules": 8,
                "pendingFilings": 1,
                "nextFilingDue": "15 Aug 2026",
                "lastAuditDate": "25 Jul 2026",
            },
            "statutoryModules": [
                {
                    "id": "epf",
                    "title": "Employees' Provident Fund (EPF)",
                    "code": "EPF / EPS",
                    "description": "12% Basic contribution with ₹1,800 capping options and Form 5A/10D filing.",
                    "status": "COMPLIANT",
                    "statusLabel": "Active & Verified",
                    "category": "Statutory Deduction",
                    "lastFiling": "15 Jul 2026 (ECR Filed)",
                    "nextDue": "15 Aug 2026",
                    "complianceScore": 100,
                    "details": {
                        "employeeRate": "12.0%",
                        "employerRate": "12.0% (3.67% EPF + 8.33% EPS)",
                        "wageCap": "₹15,000 / Month",
                        "adminCharges": "0.50%",
                        "edliCharges": "0.50%",
                        "establishmentCode": "DL/CPM/0094812/000",
                    },
                },
                {
                    "id": "esic",
                    "title": "Employee State Insurance (ESIC)",
                    "code": "ESI Act 1948",
                    "description": "Medical & disability benefit scheme applicable for gross salary up to ₹21,000.",
                    "status": "COMPLIANT",
                    "statusLabel": "Active & Verified",
                    "category": "Social Security",
                    "lastFiling": "15 Jul 2026 (Challan Paid)",
                    "nextDue": "15 Aug 2026",
                    "complianceScore": 100,
                    "details": {
                        "employeeRate": "0.75%",
                        "employerRate": "3.25%",
                        "grossLimit": "₹21,000 / Month",
                        "codeNumber": "31000948120001001",
                    },
                },
                {
                    "id": "pt",
                    "title": "Professional Tax (PT)",
                    "code": "State PT Slabs",
                    "description": "State-specific slab deductions based on monthly gross pay schedule.",
                    "status": "COMPLIANT",
                    "statusLabel": "Active & Verified",
                    "category": "State Tax",
                    "lastFiling": "20 Jul 2026",
                    "nextDue": "20 Aug 2026",
                    "complianceScore": 98,
                    "details": {
                        "statesCovered": ["MH", "KA", "WB", "TN", "TS"],
                        "maxCap": "₹2,500 / Year",
                        "registrationNo": "PT-DEL-8849201",
                    },
                },
                {
                    "id": "tds",
                    "title": "Tax Deducted at Source (TDS 192)",
                    "code": "Section 192",
                    "description": "Income Tax Slabs (New & Old Regime), 24Q quarterly returns and Form 16 issuance.",
                    "status": "ATTENTION_REQUIRED",
                    "statusLabel": "Q1 Return Due Soon",
                    "category": "Direct Tax",
                    "lastFiling": "30 Apr 2026 (24Q Q4)",
                    "nextDue": "31 Jul 2026 (24Q Q1)",
                    "complianceScore": 92,
                    "details": {
                        "tanNumber": "DELA90124F",
                        "defaultRegime": "NEW_REGIME",
                        "form16Deadline": "15 Jun 2026",
                    },
                },
                {
                    "id": "lwf",
                    "title": "Labour Welfare Fund (LWF)",
                    "code": "LWF Rules",
                    "description": "Nominal semi-annual or annual employee & employer contributions.",
                    "status": "COMPLIANT",
                    "statusLabel": "Active & Verified",
                    "category": "Welfare",
                    "lastFiling": "30 Jun 2026",
                    "nextDue": "31 Dec 2026",
                    "complianceScore": 100,
                    "details": {
                        "frequency": "Semi-Annual (June / Dec)",
                        "employeeContribution": "₹25 / 6-months",
                        "employerContribution": "₹50 / 6-months",
                    },
                },
                {
                    "id": "gratuity",
                    "title": "Payment of Gratuity",
                    "code": "Gratuity Act 1972",
                    "description": "Accrual calculation (15/26 days basic) for employees with 5+ years tenure.",
                    "status": "COMPLIANT",
                    "statusLabel": "Provisioned",
                    "category": "Retirement Benefit",
                    "lastFiling": "Valuation Report Q1 2026",
                    "nextDue": "Annual Audit 2027",
                    "complianceScore": 100,
                    "details": {
                        "maxTaxExempt": "₹20,000,000 (₹20 Lakhs)",
                        "eligibility": "5 Years Continuous Service",
                        "formula": "15/26 * Last Basic Pay * Years",
                    },
                },
                {
                    "id": "minwages",
                    "title": "Minimum Wages Act",
                    "code": "Min Wages 1948",
                    "description": "Ensures all employee pay structures comply with latest state minimum wage rates.",
                    "status": "COMPLIANT",
                    "statusLabel": "Verified & Aligned",
                    "category": "Statutory Floor",
                    "lastFiling": "Wage Audit Jul 2026",
                    "nextDue": "Oct 2026 Revision",
                    "complianceScore": 100,
                    "details": {
                        "delhiUnskilled": "₹17,494 / Month",
                        "delhiSemiSkilled": "₹19,279 / Month",
                        "delhiSkilled": "₹21,215 / Month",
                    },
                },
                {
                    "id": "auditlogs",
                    "title": "Compliance Audit Trail & Logs",
                    "code": "ISO / SOC2",
                    "description": "Immutable log of all tax declarations, PF rate overrides, and compliance changes.",
                    "status": "COMPLIANT",
                    "statusLabel": "Real-time Tracking",
                    "category": "Audit & Security",
                    "lastFiling": "Real-time Stream",
                    "nextDue": "Continuous Monitoring",
                    "complianceScore": 100,
                    "details": {
                        "totalLogsRecorded": 1420,
                        "encryption": "AES-256 GCM",
                        "retentionPeriod": "7 Years",
                    },
                },
            ],
        }
