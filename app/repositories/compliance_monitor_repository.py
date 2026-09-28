"""AI Compliance Monitor Repository executing real PostgreSQL queries for compliance logs."""

from __future__ import annotations

from datetime import date, datetime
import json
import logging
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy import and_, case, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import Company
from app.models.compliance_monitor import ComplianceAuditLog
from app.models.core_modules import ComplianceRecord
from app.models.employee import Employee
from app.models.employee_document import EmployeeDocument
from app.models.employee_risk import EmployeeRiskAssessment
from app.models.payroll import ComplianceObligation, PayrollRun
from app.models.policy import CompanyPolicyDocument
from app.models.timesheet import Timesheet, TimesheetEntry

logger = logging.getLogger(__name__)


class ComplianceMonitorRepository:
    """Repository executing database queries for AI Compliance Monitor endpoints."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_dashboard_kpis(
        self, company_id: Optional[uuid.UUID] = None
    ) -> Dict[str, Any]:
        """Compute real, dynamic Compliance Monitor dashboard KPIs scoped by company_id.

        Compliance Score formula:
            Weight 1 (35%): Document & Identity Completeness
            Weight 2 (25%): Payroll Run Validation Health
            Weight 3 (25%): Statutory Obligation Timeliness
            Weight 4 (15%): Labor Law Standards (Minimum Wage + Overtime compliance)
        """
        today = date.today()

        # ── 1. Employees & Identity Documents ──────────────────────────────
        emp_filter = [Employee.is_deleted == False]
        if company_id:
            emp_filter.append(Employee.company_id == company_id)

        emp_stmt = select(
            func.count(Employee.id).label("total"),
            func.count(
                case((or_(Employee.pan_number == None, Employee.pan_number == ""), 1))
            ).label("missing_pan"),
            func.count(
                case((or_(Employee.aadhaar_number == None, Employee.aadhaar_number == ""), 1))
            ).label("missing_aadhaar"),
            func.count(
                case((Employee.verification_status != "VERIFIED", 1))
            ).label("unverified"),
            func.count(
                case((and_(Employee.basic_salary > 0, Employee.basic_salary < 10000), 1))
            ).label("below_min_wage"),
        ).where(*emp_filter)

        emp_row = (await self.session.execute(emp_stmt)).fetchone()
        total_emp = emp_row.total if emp_row else 0
        missing_pan = emp_row.missing_pan if emp_row else 0
        missing_aadhaar = emp_row.missing_aadhaar if emp_row else 0
        unverified_emp = emp_row.unverified if emp_row else 0
        below_min_wage = emp_row.below_min_wage if emp_row else 0

        # ── 2. Employee Documents (Expired & Pending) ──────────────────────
        doc_filter = [
            Employee.is_deleted == False,
            EmployeeDocument.is_deleted == False,
        ]
        if company_id:
            doc_filter.append(Employee.company_id == company_id)

        doc_stmt = (
            select(
                func.count(
                    case((and_(EmployeeDocument.expiry_date != None, EmployeeDocument.expiry_date < today), 1))
                ).label("expired"),
                func.count(
                    case((EmployeeDocument.status == "PENDING", 1))
                ).label("pending"),
            )
            .select_from(EmployeeDocument)
            .join(Employee, EmployeeDocument.employee_id == Employee.id)
            .where(*doc_filter)
        )
        doc_row = (await self.session.execute(doc_stmt)).fetchone()
        expired_docs = doc_row.expired if doc_row else 0
        pending_docs = doc_row.pending if doc_row else 0

        # ── 3. Payroll Runs ────────────────────────────────────────────────
        pr_filter = []
        if company_id:
            pr_filter.append(PayrollRun.company_id == company_id)

        pr_stmt = select(
            func.count(PayrollRun.id).label("total_runs"),
            func.count(
                case(
                    (
                        PayrollRun.status.in_(["FAILED", "REJECTED", "CANCELLED", "VOID"]),
                        1,
                    )
                )
            ).label("anomalous_runs"),
        )
        if pr_filter:
            pr_stmt = pr_stmt.where(*pr_filter)

        pr_row = (await self.session.execute(pr_stmt)).fetchone()
        total_runs = pr_row.total_runs if pr_row else 0
        anomalous_runs = pr_row.anomalous_runs if pr_row else 0

        # ── 4. Statutory Obligations ───────────────────────────────────────
        obl_filter = []
        if company_id:
            obl_filter.append(ComplianceObligation.company_id == company_id)

        obl_stmt = select(
            func.count(ComplianceObligation.id).label("total_obl"),
            func.count(
                case((ComplianceObligation.status == "OVERDUE", 1))
            ).label("overdue_obl"),
        )
        if obl_filter:
            obl_stmt = obl_stmt.where(*obl_filter)

        obl_row = (await self.session.execute(obl_stmt)).fetchone()
        total_obl = obl_row.total_obl if obl_row else 0
        overdue_obl = obl_row.overdue_obl if obl_row else 0

        # ── 5. Timesheet Overtime Violations (>48 hrs/week) ───────────────
        ot_stmt = (
            select(func.count(TimesheetEntry.id))
            .join(Timesheet, TimesheetEntry.timesheet_id == Timesheet.id)
            .join(Employee, Timesheet.employee_id == Employee.id)
            .where(
                Employee.is_deleted == False,
                (
                    TimesheetEntry.monday_hours
                    + TimesheetEntry.tuesday_hours
                    + TimesheetEntry.wednesday_hours
                    + TimesheetEntry.thursday_hours
                    + TimesheetEntry.friday_hours
                    + TimesheetEntry.saturday_hours
                    + TimesheetEntry.sunday_hours
                )
                > 48,
            )
        )
        if company_id:
            ot_stmt = ot_stmt.where(Employee.company_id == company_id)

        ot_violations = (await self.session.execute(ot_stmt)).scalar() or 0

        # ── 6. Employee Risk Engine Assessment ─────────────────────────────
        risk_filter = []
        if company_id:
            risk_filter.append(EmployeeRiskAssessment.company_id == company_id)

        risk_stmt = select(
            func.count(
                case((EmployeeRiskAssessment.overall_risk_level == "CRITICAL", 1))
            ).label("critical"),
            func.count(
                case((EmployeeRiskAssessment.overall_risk_level == "HIGH", 1))
            ).label("high"),
        )
        if risk_filter:
            risk_stmt = risk_stmt.where(*risk_filter)

        risk_row = (await self.session.execute(risk_stmt)).fetchone()
        critical_risk_cnt = risk_row.critical if risk_row else 0
        high_risk_cnt = risk_row.high if risk_row else 0

        # ── 7. Policy Documents ───────────────────────────────────────────
        pol_filter = []
        if company_id:
            pol_filter.append(CompanyPolicyDocument.company_id == company_id)
        pol_stmt = select(func.count(CompanyPolicyDocument.id))
        if pol_filter:
            pol_stmt = pol_stmt.where(*pol_filter)
        total_policies = (await self.session.execute(pol_stmt)).scalar() or 0

        # ── 8. Derived Counts & Composite Formulas ─────────────────────────
        missing_docs = missing_pan + missing_aadhaar + expired_docs
        open_risks = (
            anomalous_runs
            + overdue_obl
            + below_min_wage
            + ot_violations
            + critical_risk_cnt
            + high_risk_cnt
        )

        # Factor 1: Document completeness (35%)
        # Expected 2 core docs (PAN + Aadhaar) per active employee
        expected_docs = max(total_emp * 2, 1)
        doc_score = max(0.0, 100.0 - ((missing_docs / expected_docs) * 100.0)) if total_emp > 0 else 100.0

        # Factor 2: Payroll runs health (25%)
        payroll_score = (
            max(0.0, 100.0 - ((anomalous_runs / max(total_runs, 1)) * 100.0))
            if total_runs > 0
            else 100.0
        )

        # Factor 3: Statutory obligations timeliness (25%)
        statutory_score = (
            max(0.0, 100.0 - ((overdue_obl / max(total_obl, 1)) * 100.0))
            if total_obl > 0
            else 100.0
        )

        # Factor 4: Labor Law & Working Hours compliance (15%)
        labor_violations = below_min_wage + ot_violations
        labor_score = (
            max(0.0, 100.0 - ((labor_violations / max(total_emp, 1)) * 100.0))
            if total_emp > 0
            else 100.0
        )

        if total_emp == 0 and total_runs == 0 and total_obl == 0:
            compliance_score = 100.0
            audit_readiness_pct = 100.0
        else:
            compliance_score = round(
                0.35 * doc_score + 0.25 * payroll_score + 0.25 * statutory_score + 0.15 * labor_score,
                1,
            )
            audit_readiness_pct = round(
                0.40 * doc_score
                + 0.30 * statutory_score
                + 0.20 * payroll_score
                + 0.10 * (100.0 if total_policies > 0 else 50.0),
                1,
            )

        audit_readiness = f"{audit_readiness_pct:.1f}%"

        # ── 9. Real Historical Trend from ComplianceAuditLog ──────────────
        m_trunc = func.date_trunc('month', ComplianceAuditLog.created_at)
        trend_stmt = (
            select(
                func.to_char(m_trunc, 'Mon YYYY').label("month"),
                func.avg(
                    case(
                        (ComplianceAuditLog.risk_level == "LOW", 95.0),
                        (ComplianceAuditLog.risk_level == "MEDIUM", 82.0),
                        (ComplianceAuditLog.risk_level == "HIGH", 68.0),
                        else_=50.0,
                    )
                ).label("avg_score"),
            )
        )
        if company_id:
            trend_stmt = trend_stmt.where(ComplianceAuditLog.company_id == company_id)
        trend_stmt = trend_stmt.group_by(m_trunc).order_by(m_trunc)

        try:
            trend_res = await self.session.execute(trend_stmt)
            trend = [
                {"month": row.month, "compliance_score": round(float(row.avg_score), 1)}
                for row in trend_res.fetchall()
            ]
        except Exception as exc:
            logger.warning("Could not compute historical compliance trend: %s", exc)
            trend = []

        # ── 10. Real Risks by Category from DB ─────────────────────────────
        risks_by_cat = []
        payroll_risks = anomalous_runs + overdue_obl
        if payroll_risks > 0:
            risks_by_cat.append({"category": "Payroll & Tax", "risk_count": payroll_risks})
        doc_risks = missing_pan + missing_aadhaar + expired_docs
        if doc_risks > 0:
            risks_by_cat.append({"category": "Identity & Documentation", "risk_count": doc_risks})
        labor_risks = below_min_wage + ot_violations
        if labor_risks > 0:
            risks_by_cat.append({"category": "Working Hours & Labor Law", "risk_count": labor_risks})
        if critical_risk_cnt + high_risk_cnt > 0:
            risks_by_cat.append({"category": "Workforce & Operational Risk", "risk_count": critical_risk_cnt + high_risk_cnt})

        # ── 11. Dynamic Labor Law Status ──────────────────────────────────
        labor_law_status = {
            "working_hours": "NON_COMPLIANT" if ot_violations > 2 else ("WARNING" if ot_violations > 0 else "COMPLIANT"),
            "minimum_wage": "NON_COMPLIANT" if below_min_wage > 0 else "COMPLIANT",
            "statutory_pf_esic": "NON_COMPLIANT" if overdue_obl > 0 else "COMPLIANT",
            "equal_pay": "COMPLIANT",
        }

        # ── 12. Dynamic Recommendations ───────────────────────────────────
        recommendations = []
        if missing_pan > 0 or missing_aadhaar > 0:
            recommendations.append(
                f"Collect and verify statutory identity proofs for {missing_pan + missing_aadhaar} employee document requirement(s)."
            )
        if expired_docs > 0:
            recommendations.append(
                f"Renew {expired_docs} expired employee identification/visa document(s)."
            )
        if below_min_wage > 0:
            recommendations.append(
                f"Adjust base compensation for {below_min_wage} employee(s) falling below statutory minimum wage."
            )
        if overdue_obl > 0:
            recommendations.append(
                f"Clear {overdue_obl} overdue statutory contribution filing(s) to avoid penalty interest."
            )
        if anomalous_runs > 0:
            recommendations.append(
                f"Resolve validation discrepancies detected in {anomalous_runs} payroll run(s)."
            )
        if ot_violations > 0:
            recommendations.append(
                f"Enforce weekly working hour caps for {ot_violations} timesheet record(s) exceeding 48 hours."
            )
        if not recommendations:
            recommendations.append("All statutory compliance indicators are within normal parameters.")
            recommendations.append("Schedule regular quarterly compliance audit review.")

        # Total standard checks evaluated
        checks_evaluated = [
            ot_violations == 0,
            missing_docs == 0,
            below_min_wage == 0,
            anomalous_runs == 0 and overdue_obl == 0,
            unverified_emp == 0,
        ]
        passed_cnt = sum(1 for c in checks_evaluated if c)
        failed_cnt = sum(1 for c in checks_evaluated if not c)

        return {
            "complianceScore": compliance_score,
            "compliance_score": compliance_score,
            "openRisks": open_risks,
            "open_risks": open_risks,
            "missingDocs": missing_docs,
            "missing_docs": missing_docs,
            "auditReadiness": audit_readiness,
            "audit_readiness": audit_readiness,
            "audit_readiness_pct": audit_readiness_pct,
            "complianceTrend": trend,
            "compliance_trend": trend,
            "risksByCategory": risks_by_cat,
            "risks_by_category": risks_by_cat,
            "laborLawStatus": labor_law_status,
            "labor_law_status": labor_law_status,
            "recommendations": recommendations,
            "policy_violations": 0,
            "expired_documents": expired_docs,
            "critical_risks": critical_risk_cnt,
            "total_checks": len(checks_evaluated),
            "passed_checks": passed_cnt,
            "warning_checks": 0,
            "failed_checks": failed_cnt,
        }

    async def get_audit_logs(
        self, company_id: Optional[uuid.UUID] = None, audit_scope: Optional[str] = None
    ) -> List[ComplianceAuditLog]:
        """Fetch past compliance audit logs from the database."""
        try:
            stmt = select(ComplianceAuditLog).order_by(ComplianceAuditLog.created_at.desc()).limit(20)
            if company_id:
                stmt = stmt.where(ComplianceAuditLog.company_id == company_id)
            if audit_scope:
                stmt = stmt.where(ComplianceAuditLog.audit_scope.ilike(audit_scope))

            res = await self.session.execute(stmt)
            return list(res.scalars().all())
        except Exception as exc:
            logger.error("Error fetching compliance audit logs: %s", exc)
            return []

    async def save_audit_log(self, audit_log: ComplianceAuditLog) -> ComplianceAuditLog:
        """Persist a new compliance audit log entry."""
        self.session.add(audit_log)
        await self.session.flush()
        return audit_log

    async def get_missing_document_records(
        self, company_id: Optional[uuid.UUID] = None, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Fetch actual missing and expired employee documents from database."""
        today = date.today()
        items: List[Dict[str, Any]] = []

        # 1. Check for expired and pending uploaded documents
        doc_stmt = (
            select(EmployeeDocument, Employee)
            .join(Employee, EmployeeDocument.employee_id == Employee.id)
            .where(
                Employee.is_deleted == False,
                EmployeeDocument.is_deleted == False,
                or_(
                    and_(
                        EmployeeDocument.expiry_date != None,
                        EmployeeDocument.expiry_date < today,
                    ),
                    EmployeeDocument.status.in_(["PENDING", "REJECTED"]),
                ),
            )
        )
        if company_id:
            doc_stmt = doc_stmt.where(Employee.company_id == company_id)
        doc_stmt = doc_stmt.order_by(EmployeeDocument.created_at.desc()).limit(limit)

        doc_rows = (await self.session.execute(doc_stmt)).all()
        for doc, emp in doc_rows:
            emp_name = f"{emp.first_name or ''} {emp.last_name or ''}".strip() or "Employee"
            status = "EXPIRED" if doc.expiry_date and doc.expiry_date < today else "PENDING_VERIFICATION"
            due_d = str(doc.expiry_date) if doc.expiry_date else str(today)
            items.append(
                {
                    "id": str(doc.id),
                    "employee_id": emp.id,
                    "employee_name": emp_name,
                    "department": emp.department or "General",
                    "document_type": doc.document_type or "Identity Document",
                    "status": status,
                    "due_date": due_d,
                }
            )

        # 2. Check for missing statutory PAN or Aadhaar on employees
        if len(items) < limit:
            emp_stmt = select(Employee).where(
                Employee.is_deleted == False,
                or_(
                    Employee.pan_number == None,
                    Employee.pan_number == "",
                    Employee.aadhaar_number == None,
                    Employee.aadhaar_number == "",
                ),
            )
            if company_id:
                emp_stmt = emp_stmt.where(Employee.company_id == company_id)
            emp_stmt = emp_stmt.order_by(Employee.created_at.desc()).limit(limit - len(items))

            missing_emps = (await self.session.execute(emp_stmt)).scalars().all()
            for emp in missing_emps:
                emp_name = f"{emp.first_name or ''} {emp.last_name or ''}".strip() or "Employee"
                dept = emp.department or "General"
                due_d = str(today)

                if not emp.pan_number:
                    items.append(
                        {
                            "id": str(uuid.uuid4()),
                            "employee_id": emp.id,
                            "employee_name": emp_name,
                            "department": dept,
                            "document_type": "PAN Card",
                            "status": "MISSING",
                            "due_date": due_d,
                        }
                    )
                if not emp.aadhaar_number and len(items) < limit:
                    items.append(
                        {
                            "id": str(uuid.uuid4()),
                            "employee_id": emp.id,
                            "employee_name": emp_name,
                            "department": dept,
                            "document_type": "Aadhaar Card",
                            "status": "MISSING",
                            "due_date": due_d,
                        }
                    )

        return items[:limit]

    async def get_risk_records(
        self, company_id: Optional[uuid.UUID] = None
    ) -> List[Dict[str, Any]]:
        """Identify concrete compliance risk records from real DB conditions."""
        risks: List[Dict[str, Any]] = []

        # 1. Overdue Statutory Obligations
        obl_stmt = select(
            ComplianceObligation.id,
            ComplianceObligation.obligation_type,
            ComplianceObligation.period_label,
            ComplianceObligation.penalty_amount,
        ).where(ComplianceObligation.status == "OVERDUE")
        if company_id:
            obl_stmt = obl_stmt.where(ComplianceObligation.company_id == company_id)
        obl_rows = (await self.session.execute(obl_stmt)).all()
        for obl_id, obl_type, period_label, penalty in obl_rows:
            penalty_val = float(penalty or 0)
            risks.append(
                {
                    "id": str(obl_id),
                    "risk_category": "Statutory Compliance",
                    "title": f"Overdue {obl_type} Statutory Filing ({period_label})",
                    "severity": "CRITICAL" if penalty_val > 0 else "HIGH",
                    "department": "Finance & Payroll",
                    "impact_score": 85.0 if penalty_val > 0 else 75.0,
                    "recommendation": f"File overdue {obl_type} return to prevent statutory penalty interest.",
                }
            )

        # 2. Anomalous / Failed Payroll Runs
        pr_stmt = select(
            PayrollRun.id,
            PayrollRun.period_month,
            PayrollRun.period_year,
            PayrollRun.status,
        ).where(
            PayrollRun.status.in_(["FAILED", "REJECTED", "CANCELLED", "VOID"])
        )
        if company_id:
            pr_stmt = pr_stmt.where(PayrollRun.company_id == company_id)
        pr_rows = (await self.session.execute(pr_stmt)).all()
        for pr_id, p_month, p_year, pr_status in pr_rows:
            risks.append(
                {
                    "id": str(pr_id),
                    "risk_category": "Payroll Risk",
                    "title": f"Failed or Discrepant Payroll Run ({p_month}/{p_year})",
                    "severity": "HIGH",
                    "department": "Payroll",
                    "impact_score": 78.0,
                    "recommendation": "Review payroll calculation discrepancies and re-verify disbursements.",
                }
            )

        # 3. Minimum Wage Deficits
        min_wage_stmt = select(Employee).where(
            Employee.is_deleted == False,
            Employee.basic_salary > 0,
            Employee.basic_salary < 10000,
        )
        if company_id:
            min_wage_stmt = min_wage_stmt.where(Employee.company_id == company_id)
        min_wage_rows = (await self.session.execute(min_wage_stmt)).scalars().all()
        if min_wage_rows:
            risks.append(
                {
                    "id": str(uuid.uuid4()),
                    "risk_category": "Labor Law",
                    "title": f"{len(min_wage_rows)} Employee(s) Below Statutory Minimum Wage",
                    "severity": "CRITICAL",
                    "department": min_wage_rows[0].department or "Operations",
                    "impact_score": 90.0,
                    "recommendation": "Adjust base compensation tiers to meet statutory state minimum wage standards.",
                }
            )

        # 4. Excessive Overtime Violations
        ot_stmt = (
            select(
                Employee.department,
                func.count(TimesheetEntry.id).label("ot_cnt"),
            )
            .join(Timesheet, TimesheetEntry.timesheet_id == Timesheet.id)
            .join(Employee, Timesheet.employee_id == Employee.id)
            .where(
                Employee.is_deleted == False,
                (
                    TimesheetEntry.monday_hours
                    + TimesheetEntry.tuesday_hours
                    + TimesheetEntry.wednesday_hours
                    + TimesheetEntry.thursday_hours
                    + TimesheetEntry.friday_hours
                    + TimesheetEntry.saturday_hours
                    + TimesheetEntry.sunday_hours
                )
                > 48,
            )
        )
        if company_id:
            ot_stmt = ot_stmt.where(Employee.company_id == company_id)
        ot_stmt = ot_stmt.group_by(Employee.department)
        ot_rows = (await self.session.execute(ot_stmt)).all()
        for dept, cnt in ot_rows:
            risks.append(
                {
                    "id": str(uuid.uuid4()),
                    "risk_category": "Working Hours & Labor Law",
                    "title": f"{cnt} Weekly Overtime Violation(s) in {dept or 'Operations'}",
                    "severity": "HIGH" if cnt > 3 else "MEDIUM",
                    "department": dept or "Operations",
                    "impact_score": 65.0,
                    "recommendation": "Enforce 48-hour statutory weekly cap and assign additional shift coverage.",
                }
            )

        # 5. High / Critical Employee Risk Engine Assessments
        risk_eng_stmt = (
            select(EmployeeRiskAssessment, Employee)
            .join(Employee, EmployeeRiskAssessment.employee_id == Employee.id)
            .where(
                Employee.is_deleted == False,
                EmployeeRiskAssessment.overall_risk_level.in_(["HIGH", "CRITICAL"]),
            )
        )
        if company_id:
            risk_eng_stmt = risk_eng_stmt.where(EmployeeRiskAssessment.company_id == company_id)
        risk_eng_rows = (await self.session.execute(risk_eng_stmt)).all()
        for r_ass, emp in risk_eng_rows:
            emp_name = f"{emp.first_name or ''} {emp.last_name or ''}".strip()
            risks.append(
                {
                    "id": str(r_ass.id),
                    "risk_category": "Workforce Compliance Risk",
                    "title": f"Elevated Compliance Risk Indicator ({emp_name})",
                    "severity": r_ass.overall_risk_level,
                    "department": emp.department or "General",
                    "impact_score": float(r_ass.compliance_risk_score or 75),
                    "recommendation": r_ass.risk_narrative or "Conduct 1-on-1 compliance review with HR manager.",
                }
            )

        return risks

    async def get_department_analytics(
        self, company_id: Optional[uuid.UUID] = None
    ) -> List[Dict[str, Any]]:
        """Calculate real compliance percentage per department."""
        stmt = (
            select(
                Employee.department,
                func.count(Employee.id).label("total"),
                func.count(
                    case(
                        (
                            and_(
                                Employee.pan_number != None,
                                Employee.pan_number != "",
                                Employee.aadhaar_number != None,
                                Employee.aadhaar_number != "",
                            ),
                            1,
                        )
                    )
                ).label("compliant"),
            )
            .where(Employee.is_deleted == False)
        )
        if company_id:
            stmt = stmt.where(Employee.company_id == company_id)
        stmt = stmt.group_by(Employee.department).order_by(desc("total"))

        rows = (await self.session.execute(stmt)).all()
        result = []
        for dept, total, compliant in rows:
            d_name = dept or "General"
            pct = round((compliant / max(total, 1)) * 100.0, 1)
            result.append({"department": d_name, "compliance_pct": pct, "total_employees": total})
        return result

    async def get_employee_detail(
        self, employee_id: uuid.UUID
    ) -> Optional[Dict[str, Any]]:
        """Retrieve real compliance metrics for a single employee."""
        emp_stmt = select(Employee).where(Employee.id == employee_id, Employee.is_deleted == False)
        emp = (await self.session.execute(emp_stmt)).scalar_one_or_none()
        if not emp:
            return None

        emp_name = f"{emp.first_name or ''} {emp.last_name or ''}".strip() or f"Employee #{emp.id}"
        missing_docs: List[str] = []
        if not emp.pan_number:
            missing_docs.append("PAN Card")
        if not emp.aadhaar_number:
            missing_docs.append("Aadhaar Card")
        if not emp.uan_number and (emp.basic_salary or 0) > 0:
            missing_docs.append("UAN / EPF Number")

        # Check expired employee documents
        today = date.today()
        doc_stmt = select(EmployeeDocument).where(
            EmployeeDocument.employee_id == employee_id,
            EmployeeDocument.is_deleted == False,
            EmployeeDocument.expiry_date != None,
            EmployeeDocument.expiry_date < today,
        )
        expired_docs = (await self.session.execute(doc_stmt)).scalars().all()
        for ed in expired_docs:
            missing_docs.append(f"{ed.document_type or 'Identity Document'} (Expired)")

        # Check timesheet overtime
        ot_stmt = (
            select(func.count(TimesheetEntry.id))
            .join(Timesheet, TimesheetEntry.timesheet_id == Timesheet.id)
            .where(
                Timesheet.employee_id == employee_id,
                (
                    TimesheetEntry.monday_hours
                    + TimesheetEntry.tuesday_hours
                    + TimesheetEntry.wednesday_hours
                    + TimesheetEntry.thursday_hours
                    + TimesheetEntry.friday_hours
                    + TimesheetEntry.saturday_hours
                    + TimesheetEntry.sunday_hours
                )
                > 48,
            )
        )
        ot_cnt = (await self.session.execute(ot_stmt)).scalar() or 0

        violations_cnt = len(missing_docs) + ot_cnt
        if violations_cnt == 0:
            risk_level = "LOW"
            compliance_status = "COMPLIANT"
            recommendation = "Employee records and statutory documents are 100% compliant."
        elif violations_cnt <= 2:
            risk_level = "MEDIUM"
            compliance_status = "WARNING"
            recommendation = f"Collect pending records: {', '.join(missing_docs)}."
        else:
            risk_level = "HIGH"
            compliance_status = "NON_COMPLIANT"
            recommendation = f"Immediate action required for {violations_cnt} statutory non-compliance items."

        return {
            "employee_id": emp.id,
            "employee_name": emp_name,
            "department": emp.department or "General",
            "compliance_status": compliance_status,
            "missing_documents": missing_docs,
            "violations_count": violations_cnt,
            "risk_level": risk_level,
            "recommendation": recommendation,
        }
