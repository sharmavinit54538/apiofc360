"""Deterministic culture, diversity and retention analytics for Batch 7.

All methods require a tenant ID.  Metrics expose sample sizes and coverage so
missing surveys, bands or diversity self-identification are not presented as
facts.  Recommendations are decision support and never execute HR actions.
"""
from __future__ import annotations

import json
import uuid
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_employee_support import SupportTicket
from app.models.compensation import CompensationBand, EmployeeCompensationBand
from app.models.employee import Employee
from app.models.employee_leave_policy import EmployeeLeavePolicy
from app.models.employee_risk import EmployeeRiskAssessment
from app.models.engagement import EngagementAnswer, EngagementQuestion, EngagementResponse
from app.models.payroll import OvertimeEntry
from app.models.recruitment import Application


def _pct(numerator: int | float, denominator: int | float) -> float | None:
    if not denominator:
        return None
    return round(float(numerator) * 100 / float(denominator), 2)


def _clamp(value: float, low: float = 0, high: float = 100) -> float:
    return round(max(low, min(high, value)), 2)


def _counts(values: list[str]) -> dict[str, dict[str, Any]]:
    counts: dict[str, int] = defaultdict(int)
    for value in values:
        counts[value or "UNKNOWN"] += 1
    total = len(values)
    return {
        key: {"count": count, "percentage": _pct(count, total)}
        for key, count in sorted(counts.items())
    }


def _date_value(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


class HRDifferentiatorAnalytics:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def _employees(self, company_id: uuid.UUID, *, include_terminated: bool = False) -> list[Employee]:
        stmt = select(Employee).where(
            Employee.company_id == company_id,
            Employee.is_deleted.is_(False),
        )
        if not include_terminated:
            stmt = stmt.where(Employee.status == "ACTIVE")
        return list((await self.session.execute(stmt)).scalars().all())

    async def culture(self, company_id: uuid.UUID) -> dict[str, Any]:
        employees = await self._employees(company_id)
        employee_by_id = {employee.id: employee for employee in employees}
        departments: dict[str, dict[str, Any]] = {}
        for employee in employees:
            name = employee.department or "UNASSIGNED"
            departments.setdefault(name, {
                "department": name, "headcount": 0, "enps_scores": [], "pulse_scores": [],
                "overtime_hours": 0.0, "leave_used_days": 0.0, "leave_total_days": 0.0,
                "sentiment_scores": [], "helpdesk_ticket_count": 0,
            })["headcount"] += 1

        answer_rows = (await self.session.execute(
            select(EngagementResponse, EngagementAnswer, EngagementQuestion)
            .join(EngagementAnswer, EngagementAnswer.response_id == EngagementResponse.id)
            .join(EngagementQuestion, EngagementQuestion.id == EngagementAnswer.question_id)
            .where(EngagementResponse.company_id == company_id)
        )).all()
        survey_response_count = 0
        seen_responses: set[uuid.UUID] = set()
        for response, answer, question in answer_rows:
            if answer.numeric_value is None:
                continue
            employee = employee_by_id.get(response.employee_id)
            department = response.department or (employee.department if employee else None) or "UNASSIGNED"
            if department not in departments:
                departments[department] = {
                    "department": department, "headcount": 0, "enps_scores": [], "pulse_scores": [],
                    "overtime_hours": 0.0, "leave_used_days": 0.0, "leave_total_days": 0.0,
                    "sentiment_scores": [], "helpdesk_ticket_count": 0,
                }
            value = float(answer.numeric_value)
            is_nps = str(question.question_type).upper() in {"NPS", "ENPS"} or "recommend" in question.question_text.lower()
            if is_nps and 0 <= value <= 10:
                departments[department]["enps_scores"].append(value)
            else:
                departments[department]["pulse_scores"].append(value)
            if response.id not in seen_responses:
                seen_responses.add(response.id)
                survey_response_count += 1

        overtime_rows = (await self.session.execute(select(OvertimeEntry).where(
            OvertimeEntry.company_id == company_id,
        ))).scalars().all()
        for entry in overtime_rows:
            employee = employee_by_id.get(entry.employee_id)
            if employee is None:
                continue
            department = employee.department or "UNASSIGNED"
            departments[department]["overtime_hours"] += float(entry.adjusted_hours if entry.adjusted_hours is not None else entry.ot_hours or 0)

        leave_rows = (await self.session.execute(
            select(EmployeeLeavePolicy)
            .join(Employee, Employee.id == EmployeeLeavePolicy.employee_id)
            .where(Employee.company_id == company_id, Employee.is_deleted.is_(False))
        )).scalars().all()
        for policy in leave_rows:
            employee = employee_by_id.get(policy.employee_id)
            if employee is None:
                continue
            department = employee.department or "UNASSIGNED"
            departments[department]["leave_used_days"] += float(policy.used_days or 0)
            departments[department]["leave_total_days"] += float(policy.total_days or 0)

        positive = {"good", "great", "excellent", "resolved", "helpful", "thanks", "happy", "satisfied"}
        negative = {"bad", "poor", "angry", "unresolved", "slow", "frustrated", "harassment", "unhappy", "terrible", "worst"}
        tickets = (await self.session.execute(select(SupportTicket).where(
            SupportTicket.company_id == company_id,
        ))).scalars().all()
        for ticket in tickets:
            employee = employee_by_id.get(ticket.employee_id)
            if employee is None:
                continue
            words = set(f"{ticket.title} {ticket.description}".lower().replace(".", " ").replace(",", " ").split())
            sentiment = max(-1.0, min(1.0, (len(words & positive) - len(words & negative)) / 3))
            department = employee.department or "UNASSIGNED"
            departments[department]["sentiment_scores"].append(sentiment)
            departments[department]["helpdesk_ticket_count"] += 1

        rows = []
        for name in sorted(departments):
            metric = departments[name]
            scores = metric.pop("enps_scores")
            promoters = sum(score >= 9 for score in scores)
            detractors = sum(score <= 6 for score in scores)
            enps = round((promoters - detractors) * 100 / len(scores), 2) if scores else None
            pulse_values = metric.pop("pulse_scores")
            pulse_average = round(sum(pulse_values) / len(pulse_values), 2) if pulse_values else None
            if pulse_values:
                # Five-point pulse scales and ten-point scales are both common.
                pulse_index = _clamp(((pulse_average - 1) / 4 * 100) if pulse_average <= 5 else pulse_average * 10)
            else:
                pulse_index = None
            sentiments = metric.pop("sentiment_scores")
            sentiment = round(sum(sentiments) / len(sentiments), 4) if sentiments else None
            headcount = metric["headcount"]
            average_overtime = round(metric["overtime_hours"] / headcount, 2) if headcount else None
            leave_utilization = _pct(metric["leave_used_days"], metric["leave_total_days"])
            overtime_component = min(40, (average_overtime or 0) / 40 * 40)
            pulse_component = (100 - pulse_index) * 0.35 if pulse_index is not None else 17.5
            sentiment_component = (1 - (sentiment or 0)) / 2 * 25
            leave_component = max(0, 50 - (leave_utilization or 0)) / 50 * 10
            burnout = _clamp(overtime_component + pulse_component + sentiment_component + leave_component)
            enps_component = ((enps + 100) / 2) if enps is not None else 50
            culture = _clamp(
                enps_component * 0.35 + (pulse_index if pulse_index is not None else 50) * 0.40
                + ((sentiment + 1) * 50 if sentiment is not None else 50) * 0.15
                + (100 - burnout) * 0.10
            )
            rows.append({
                "department": name, "headcount": headcount,
                "enps": enps, "enps_responses": len(scores),
                "pulse_average": pulse_average, "pulse_index": pulse_index,
                "pulse_answers": len(pulse_values),
                "overtime_hours_total": round(metric["overtime_hours"], 2),
                "average_overtime_hours_per_employee": average_overtime,
                "leave_used_days": round(metric["leave_used_days"], 2),
                "leave_total_days": round(metric["leave_total_days"], 2),
                "leave_utilization_pct": leave_utilization,
                "helpdesk_sentiment": sentiment,
                "helpdesk_ticket_count": metric["helpdesk_ticket_count"],
                "culture_index": culture, "burnout_index": burnout,
                "burnout_level": "LOW" if burnout < 30 else "MEDIUM" if burnout < 60 else "HIGH" if burnout < 80 else "CRITICAL",
            })
        total_headcount = sum(row["headcount"] for row in rows)
        weighted_culture = round(sum(row["culture_index"] * row["headcount"] for row in rows) / total_headcount, 2) if total_headcount else None
        weighted_burnout = round(sum(row["burnout_index"] * row["headcount"] for row in rows) / total_headcount, 2) if total_headcount else None
        return {
            "company_id": str(company_id), "departments": rows,
            "organization": {
                "headcount": total_headcount, "culture_index": weighted_culture,
                "burnout_index": weighted_burnout,
                "survey_response_count": survey_response_count,
                "helpdesk_ticket_count": len(tickets),
            },
            "data_coverage": {
                "employees": len(employees), "survey_responses": survey_response_count,
                "overtime_records": len(overtime_rows), "leave_policies": len(leave_rows),
                "helpdesk_tickets": len(tickets),
            },
            "methodology": "Culture and burnout indices are deterministic 0-100 decision-support indicators; null source metrics are not zero responses.",
        }

    async def diversity(self, company_id: uuid.UUID) -> dict[str, Any]:
        employees = await self._employees(company_id)
        today = date.today()
        genders = [str(employee.gender or "UNKNOWN").upper() for employee in employees]
        ages = []
        age_bands = []
        for employee in employees:
            if not employee.date_of_birth:
                age_bands.append("UNKNOWN")
                continue
            born = employee.date_of_birth
            age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
            ages.append(age)
            age_bands.append("UNDER_25" if age < 25 else "25_34" if age < 35 else "35_44" if age < 45 else "45_54" if age < 55 else "55_PLUS")

        assignments = (await self.session.execute(
            select(EmployeeCompensationBand, CompensationBand)
            .join(CompensationBand, CompensationBand.id == EmployeeCompensationBand.band_id)
            .where(
                EmployeeCompensationBand.company_id == company_id,
                EmployeeCompensationBand.is_current.is_(True),
                CompensationBand.company_id == company_id,
            )
        )).all()
        grade_by_employee = {assignment.employee_id: band.grade for assignment, band in assignments}
        grades = [grade_by_employee.get(employee.id, "UNASSIGNED") for employee in employees]

        leadership_terms = ("manager", "head", "director", "president", "vice president", "vp", "chief", "ceo", "cxo")
        leaders = [employee for employee in employees if any(term in (employee.designation or "").lower() for term in leadership_terms) or str(employee.role).lower() in {"manager", "executive", "hr_manager"}]
        leadership_genders = [str(employee.gender or "UNKNOWN").upper() for employee in leaders]
        female_leaders = sum(value in {"FEMALE", "WOMAN", "F"} for value in leadership_genders)

        applications = (await self.session.execute(select(Application).where(
            Application.company_id == company_id,
        ))).scalars().all()
        funnel: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        disclosed_applicants = 0
        for application in applications:
            attributes = getattr(application, "voluntary_demographics", None)
            consented = getattr(application, "diversity_consent_at", None) is not None
            gender = "NOT_DISCLOSED"
            if consented and isinstance(attributes, dict) and attributes.get("gender"):
                gender = str(attributes["gender"]).upper()
                disclosed_applicants += 1
            status = str(application.status or "APPLIED").upper()
            if status in {"INTERVIEW", "INTERVIEWING", "INTERVIEW_SCHEDULED"}:
                rank = 3
            elif status in {"OFFER", "OFFERED", "OFFER_SENT", "OFFER_ACCEPTED"}:
                rank = 4
            elif status in {"HIRED", "JOINED"}:
                rank = 5
            elif status in {"SHORTLISTED", "SCREENING", "SCREENED"}:
                rank = 2
            else:
                rank = 1
            funnel[gender]["applicants"] += 1
            if rank >= 2:
                funnel[gender]["shortlisted"] += 1
            if rank >= 3:
                funnel[gender]["interviewed"] += 1
            if rank >= 4:
                funnel[gender]["offered"] += 1
            if rank >= 5:
                funnel[gender]["hired"] += 1
        funnel_rows = []
        for gender in sorted(funnel):
            values = funnel[gender]
            funnel_rows.append({
                "gender": gender, **dict(values),
                "hire_rate_pct": _pct(values["hired"], values["applicants"]),
            })
        disclosed_rates = [row["hire_rate_pct"] for row in funnel_rows if row["gender"] != "NOT_DISCLOSED" and row["applicants"] >= 5 and row["hire_rate_pct"] is not None]
        parity_ratio = round(min(disclosed_rates) / max(disclosed_rates), 4) if disclosed_rates and max(disclosed_rates) > 0 else None
        return {
            "company_id": str(company_id), "headcount": len(employees),
            "gender": _counts(genders), "age_bands": _counts(age_bands),
            "average_age": round(sum(ages) / len(ages), 1) if ages else None,
            "grade": _counts(grades),
            "leadership": {
                "headcount": len(leaders),
                "leadership_ratio_pct": _pct(len(leaders), len(employees)),
                "gender": _counts(leadership_genders),
                "women_leadership_ratio_pct": _pct(female_leaders, len(leaders)),
            },
            "hiring_funnel_parity": {
                "rows": funnel_rows, "four_fifths_parity_ratio": parity_ratio,
                "parity_flag": None if parity_ratio is None else parity_ratio < 0.8,
                "disclosed_applicants": disclosed_applicants,
                "total_applicants": len(applications),
            },
            "privacy_note": "Hiring diversity uses only voluntary, consented self-identification. Gender is never inferred from names or other attributes.",
        }

    async def attrition_risk(
        self,
        company_id: uuid.UUID,
        *,
        as_of_date: date | None = None,
        persist: bool = False,
        limit: int = 100,
    ) -> dict[str, Any]:
        today = as_of_date or date.today()
        employees = await self._employees(company_id)
        all_employees = await self._employees(company_id, include_terminated=True)
        assignments = (await self.session.execute(
            select(EmployeeCompensationBand, CompensationBand)
            .join(CompensationBand, CompensationBand.id == EmployeeCompensationBand.band_id)
            .where(
                EmployeeCompensationBand.company_id == company_id,
                EmployeeCompensationBand.is_current.is_(True),
                CompensationBand.company_id == company_id,
            )
        )).all()
        band_by_employee = {assignment.employee_id: (assignment, band) for assignment, band in assignments}
        manager_groups: dict[uuid.UUID, list[Employee]] = defaultdict(list)
        for employee in all_employees:
            manager_id = employee.reporting_manager_id or employee.manager_id
            if manager_id:
                manager_groups[manager_id].append(employee)

        rows = []
        for employee in employees:
            tenure_days = max(0, (today - employee.joining_date).days)
            tenure_months = int(Decimal(tenure_days) / Decimal("30.4375"))
            assignment_band = band_by_employee.get(employee.id)
            assignment, band = assignment_band if assignment_band else (None, None)
            annual_salary_paise = int(assignment.annual_salary_paise) if assignment else int(Decimal(str(employee.ctc or 0)) * 100)
            compa_ratio = float(Decimal(annual_salary_paise) / Decimal(band.mid_paise)) if band and band.mid_paise else None
            metadata = employee.role_metadata if isinstance(employee.role_metadata, dict) else {}
            promotion_date = _date_value(getattr(employee, "last_promotion_date", None)) or _date_value(metadata.get("last_promotion_date"))
            months_since_promotion = int(Decimal(max(0, (today - promotion_date).days)) / Decimal("30.4375")) if promotion_date else None
            manager_id = employee.reporting_manager_id or employee.manager_id
            manager_team = manager_groups.get(manager_id, []) if manager_id else []
            manager_departures = sum(member.status == "TERMINATED" for member in manager_team)
            manager_attrition = _pct(manager_departures, len(manager_team)) if manager_team else None

            score = 0
            factors = []
            if tenure_months < 12:
                score += 15
                factors.append({"factor": "TENURE_UNDER_12_MONTHS", "points": 15})
            elif tenure_months < 24:
                score += 10
                factors.append({"factor": "TENURE_12_TO_24_MONTHS", "points": 10})
            if compa_ratio is not None and compa_ratio < 0.85:
                score += 25
                factors.append({"factor": "COMPA_RATIO_BELOW_0_85", "points": 25})
            elif compa_ratio is not None and compa_ratio < 0.95:
                score += 15
                factors.append({"factor": "COMPA_RATIO_BELOW_0_95", "points": 15})
            elif compa_ratio is not None and compa_ratio > 1.15:
                score += 5
                factors.append({"factor": "COMPA_RATIO_ABOVE_BAND", "points": 5})
            if months_since_promotion is None and tenure_months >= 36:
                score += 15
                factors.append({"factor": "NO_PROMOTION_RECORD", "points": 15})
            elif months_since_promotion is not None and months_since_promotion > 36:
                score += 20
                factors.append({"factor": "PROMOTION_OVER_36_MONTHS_AGO", "points": 20})
            elif months_since_promotion is not None and months_since_promotion > 24:
                score += 12
                factors.append({"factor": "PROMOTION_OVER_24_MONTHS_AGO", "points": 12})
            if manager_attrition is not None and manager_attrition >= 30:
                score += 20
                factors.append({"factor": "MANAGER_TEAM_ATTRITION_OVER_30_PCT", "points": 20})
            elif manager_attrition is not None and manager_attrition >= 15:
                score += 10
                factors.append({"factor": "MANAGER_TEAM_ATTRITION_OVER_15_PCT", "points": 10})
            score = int(_clamp(score))
            level = "LOW" if score < 30 else "MEDIUM" if score < 55 else "HIGH" if score < 80 else "CRITICAL"

            target_paise = int(Decimal(band.mid_paise) * Decimal("0.95")) if band else annual_salary_paise
            equity_gap = max(0, target_paise - annual_salary_paise)
            retention_bonus = min(equity_gap, int(Decimal(annual_salary_paise) * Decimal("0.15"))) if compa_ratio is not None and compa_ratio < 0.95 else 0
            playbook = {
                "retention_bonus": {
                    "recommended": retention_bonus > 0 and score >= 30,
                    "amount_paise": retention_bonus if score >= 30 else 0,
                    "currency": band.currency if band else "INR",
                    "guardrail": "One-time decision-support estimate capped at 15% of annual pay; requires rewards approval.",
                },
                "internal_transfer": {
                    "recommended": bool(manager_attrition is not None and manager_attrition >= 15 and score >= 30),
                    "action": "Assess skills and employee preferences before identifying an internal mobility option; never force a transfer.",
                },
                "stay_interview": {
                    "recommended": score >= 30,
                    "owner_employee_id": str(manager_id) if manager_id else None,
                    "timeline_days": 14 if score >= 55 else 30,
                    "questions": [
                        "What parts of your role currently give you energy or frustration?",
                        "What career move or learning opportunity would you like in the next year?",
                        "What could your manager or the organization change to improve your experience?",
                    ],
                },
            }
            row = {
                "employee_id": str(employee.id), "employee_code": employee.employee_id,
                "department": employee.department, "designation": employee.designation,
                "tenure_months": tenure_months, "compa_ratio": round(compa_ratio, 4) if compa_ratio is not None else None,
                "months_since_promotion": months_since_promotion,
                "manager_attrition_pct": manager_attrition,
                "flight_risk_score": score, "risk_level": level,
                "risk_factors": factors, "retention_playbook": playbook,
                "data_coverage": {
                    "compensation_band": assignment_band is not None,
                    "promotion_date": promotion_date is not None,
                    "manager_history": bool(manager_team),
                },
            }
            rows.append(row)
            if persist:
                self.session.add(EmployeeRiskAssessment(
                    id=uuid.uuid4(), company_id=company_id, employee_id=employee.id,
                    resignation_risk_score=score, overall_risk_level=level,
                    risk_narrative="Deterministic Batch 7 flight-risk assessment; human review required.",
                    recommended_actions=json.dumps(factors),
                    flight_risk_score=score, risk_factors_json=factors,
                    retention_playbook_json=playbook,
                    compa_ratio=Decimal(str(row["compa_ratio"])) if row["compa_ratio"] is not None else None,
                    tenure_months=tenure_months, months_since_promotion=months_since_promotion,
                    manager_attrition_pct=Decimal(str(manager_attrition)) if manager_attrition is not None else None,
                    model_version="BATCH7_DETERMINISTIC_V1",
                ))
        rows.sort(key=lambda row: (-row["flight_risk_score"], row["employee_code"], row["employee_id"]))
        if persist:
            await self.session.commit()
        counts = {level: sum(row["risk_level"] == level for row in rows) for level in ("LOW", "MEDIUM", "HIGH", "CRITICAL")}
        return {
            "company_id": str(company_id), "as_of_date": today.isoformat(),
            "employees": rows[: max(1, min(limit, 500))], "total_assessed": len(rows),
            "risk_counts": counts,
            "average_flight_risk_score": round(sum(row["flight_risk_score"] for row in rows) / len(rows), 2) if rows else None,
            "recommendations_require_human_review": True,
        }
