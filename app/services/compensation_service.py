"""AI Compensation Recommendation and Total Rewards analysis service.

Handles market benchmarks, internal pay equity auditing, and local LLM evaluations.
"""

from __future__ import annotations

import logging
import json
import uuid
from decimal import Decimal
from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.client import get_llm_client
from app.llm.prompts import PromptLibrary
from app.llm.response_parser import ResponseParser

# Models
from app.models.employee import Employee
from app.models.compensation import (
    MarketCompensationBenchmark,
    AICompensationRecommendation,
)

logger = logging.getLogger(__name__)


class CompensationService:
    """Enterprise AI Compensation and Total Rewards Service."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.llm = get_llm_client()

    async def register_market_benchmark(
        self,
        designation: str,
        experience_years: int,
        market_min_salary: Decimal,
        market_median_salary: Decimal,
        market_max_salary: Decimal,
        region: str = "Global",
    ) -> MarketCompensationBenchmark:
        """Upsert a market salary benchmark reference."""
        stmt = select(MarketCompensationBenchmark).where(
            MarketCompensationBenchmark.designation == designation,
            MarketCompensationBenchmark.experience_years == experience_years,
            MarketCompensationBenchmark.region == region
        )
        res = await self.db.execute(stmt)
        benchmark = res.scalar_one_or_none()

        if benchmark:
            benchmark.market_min_salary = market_min_salary
            benchmark.market_median_salary = market_median_salary
            benchmark.market_max_salary = market_max_salary
        else:
            benchmark = MarketCompensationBenchmark(
                id=uuid.uuid4(),
                designation=designation,
                experience_years=experience_years,
                market_min_salary=market_min_salary,
                market_median_salary=market_median_salary,
                market_max_salary=market_max_salary,
                region=region
            )
            self.db.add(benchmark)

        await self.db.commit()
        await self.db.refresh(benchmark)
        logger.info("Market benchmark registered: %s (%s yrs exp)", designation, experience_years)
        return benchmark

    async def compile_compensation_recommendation(
        self,
        employee_id: uuid.UUID,
        model: Optional[str] = None,
    ) -> AICompensationRecommendation:
        """Calculate peer equity metrics and invoke local LLM to recommend complete total rewards packages."""
        # 1. Fetch employee
        emp_stmt = select(Employee).where(Employee.id == employee_id)
        emp_res = await self.db.execute(emp_stmt)
        emp = emp_res.scalar_one_or_none()
        if not emp:
            raise ValueError("Employee not found.")

        current_ctc = emp.ctc or Decimal("0.00")
        exp_years = (date.today() - emp.joining_date).days // 365
        if exp_years < 0:
            exp_years = 0

        # 2. Query peer/internal average salary for same designation
        peer_stmt = (
            select(func.avg(Employee.ctc))
            .where(
                Employee.company_id == emp.company_id,
                Employee.designation == emp.designation,
                Employee.id != employee_id
            )
        )
        peer_res = await self.db.execute(peer_stmt)
        avg_peer_ctc_val = peer_res.scalar()
        avg_peer_ctc = Decimal(str(avg_peer_ctc_val)) if avg_peer_ctc_val else current_ctc

        # 3. Query market salary benchmarks
        bench_stmt = (
            select(MarketCompensationBenchmark)
            .where(MarketCompensationBenchmark.designation == emp.designation)
            .order_by(func.abs(MarketCompensationBenchmark.experience_years - exp_years).asc())
            .limit(1)
        )
        bench_res = await self.db.execute(bench_stmt)
        benchmark = bench_res.scalar_one_or_none()

        if benchmark:
            market_median = benchmark.market_median_salary
            benchmark_desc = (
                f"Min: {benchmark.market_min_salary}, Median: {benchmark.market_median_salary}, "
                f"Max: {benchmark.market_max_salary} (Region: {benchmark.region})"
            )
        else:
            market_median = current_ctc * Decimal("1.05")
            benchmark_desc = f"No benchmark matched. Approximate Median estimate: {market_median}"

        # 4. Formulate profiles summaries for LLM
        employee_details = (
            f"Name: {emp.first_name} {emp.last_name}\n"
            f"Title: {emp.designation}\n"
            f"Experience in Company: {exp_years} years\n"
            f"Current CTC: {current_ctc}"
        )
        internal_averages = f"Peer Average CTC for designation '{emp.designation}': {avg_peer_ctc}"

        try:
            prompt = PromptLibrary.ai_compensation_user(
                employee_details=employee_details,
                internal_averages=internal_averages,
                market_benchmark=benchmark_desc
            )
            res_text = await self.llm.complete(
                prompt=prompt,
                system=PromptLibrary.AI_COMPENSATION_RECOMMENDER,
                model=model,
                json_mode=True,
                temperature=0.3
            )
            rec = ResponseParser.extract_json_object(res_text)
        except Exception as exc:
            logger.error("AI Compensation recommendation failed: %s", exc)
            rec = {
                "recommended_salary": float(current_ctc * Decimal("1.05")),
                "recommended_bonus": 0.00,
                "recommended_incentives": 0.00,
                "recommended_retention_bonus": 0.00,
                "recommended_stock_options": 0,
                "recommend_promotion": False,
                "recommended_title": None,
                "recommended_increment_percentage": 5.00,
                "market_ratio": 1.00,
                "equity_status": "COMPLIANT",
                "justification": "Standard annual baseline increment recommended."
            }

        # Calculate exact ratio vs benchmark median
        ratio = current_ctc / market_median if market_median > 0 else Decimal("1.00")

        # 5. Save recommendation
        recommendation = AICompensationRecommendation(
            id=uuid.uuid4(),
            employee_id=employee_id,
            recommended_salary=Decimal(str(rec.get("recommended_salary", current_ctc))),
            recommended_bonus=Decimal(str(rec.get("recommended_bonus", 0.00))),
            recommended_incentives=Decimal(str(rec.get("recommended_incentives", 0.00))),
            recommended_retention_bonus=Decimal(str(rec.get("recommended_retention_bonus", 0.00))),
            recommended_stock_options=int(rec.get("recommended_stock_options", 0)),
            recommend_promotion=bool(rec.get("recommend_promotion", False)),
            recommended_title=rec.get("recommended_title"),
            recommended_increment_percentage=Decimal(str(rec.get("recommended_increment_percentage", 0.00))),
            market_ratio=ratio,
            equity_status=rec.get("equity_status", "COMPLIANT").upper(),
            justification=rec.get("justification", "Analysis completed."),
        )
        self.db.add(recommendation)
        await self.db.commit()
        await self.db.refresh(recommendation)
        logger.info("Compensation audit recommendations compiled for employee %s", employee_id)
        return recommendation


class CompensationBandService:
    """Exact-paise compensation bands, budgets, benchmarks, and equity analytics."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def _paise(value: int, name: str) -> int:
        result = int(value)
        if result < 0:
            raise ValueError(f"{name} cannot be negative.")
        return result

    async def _employee(self, employee_id: uuid.UUID, company_id: uuid.UUID) -> Employee:
        employee = (await self.session.execute(select(Employee).where(
            Employee.id == employee_id, Employee.company_id == company_id,
            Employee.is_deleted.is_(False), Employee.status == "ACTIVE",
        ))).scalar_one_or_none()
        if employee is None:
            raise LookupError("Active employee not found in this tenant.")
        return employee

    async def _band(self, band_id: uuid.UUID, company_id: uuid.UUID):
        from app.models.compensation import CompensationBand
        band = (await self.session.execute(select(CompensationBand).where(
            CompensationBand.id == band_id, CompensationBand.company_id == company_id,
        ))).scalar_one_or_none()
        if band is None:
            raise LookupError("Compensation band not found.")
        return band

    async def create_band(
        self, *, company_id: uuid.UUID, band_code: str, grade: str, name: str,
        min_paise: int, mid_paise: int, max_paise: int, effective_date: date,
        department: str | None = None, designation: str | None = None,
    ):
        from app.models.compensation import CompensationBand
        minimum, midpoint, maximum = (self._paise(v, label) for v, label in (
            (min_paise, "Minimum"), (mid_paise, "Midpoint"), (max_paise, "Maximum"),
        ))
        if not minimum < midpoint < maximum:
            raise ValueError("Compensation band must satisfy min_paise < mid_paise < max_paise.")
        band = CompensationBand(
            id=uuid.uuid4(), company_id=company_id, band_code=band_code.strip().upper(),
            grade=grade.strip().upper(), name=name.strip(), department=department,
            designation=designation, min_paise=minimum, mid_paise=midpoint, max_paise=maximum,
            effective_date=effective_date,
        )
        self.session.add(band)
        await self.session.commit()
        return band

    async def assign_employee_band(
        self, *, company_id: uuid.UUID, employee_id: uuid.UUID, band_id: uuid.UUID,
        annual_salary_paise: int, effective_date: date, change_reason: str | None = None,
    ):
        from app.models.compensation import EmployeeCompensationBand
        await self._employee(employee_id, company_id)
        await self._band(band_id, company_id)
        salary = self._paise(annual_salary_paise, "Annual salary")
        current = (await self.session.execute(select(EmployeeCompensationBand).where(
            EmployeeCompensationBand.company_id == company_id,
            EmployeeCompensationBand.employee_id == employee_id,
            EmployeeCompensationBand.is_current.is_(True),
        ))).scalars().all()
        for assignment in current:
            assignment.is_current = False
        assignment = EmployeeCompensationBand(
            id=uuid.uuid4(), company_id=company_id, employee_id=employee_id, band_id=band_id,
            annual_salary_paise=salary, effective_date=effective_date, is_current=True,
            change_reason=change_reason,
        )
        self.session.add(assignment)
        await self.session.commit()
        return assignment

    async def _current_assignment(self, employee_id: uuid.UUID, company_id: uuid.UUID):
        from app.models.compensation import EmployeeCompensationBand
        return (await self.session.execute(select(EmployeeCompensationBand).where(
            EmployeeCompensationBand.company_id == company_id,
            EmployeeCompensationBand.employee_id == employee_id,
            EmployeeCompensationBand.is_current.is_(True),
        ).order_by(EmployeeCompensationBand.effective_date.desc()).limit(1))).scalar_one_or_none()

    async def compa_ratio(self, *, company_id: uuid.UUID, employee_id: uuid.UUID) -> dict:
        from app.models.compensation import CompensationBand
        employee = await self._employee(employee_id, company_id)
        assignment = await self._current_assignment(employee_id, company_id)
        if assignment is None:
            raise LookupError("Employee has no current compensation-band assignment.")
        band = await self._band(assignment.band_id, company_id)
        salary = assignment.annual_salary_paise
        ratio = (Decimal(salary) / Decimal(band.mid_paise)).quantize(Decimal("0.0001")) if band.mid_paise else Decimal("0")
        position = "BELOW_BAND" if salary < band.min_paise else "ABOVE_BAND" if salary > band.max_paise else "WITHIN_BAND"
        return {
            "employee_id": str(employee.id), "band_id": str(band.id), "grade": band.grade,
            "annual_salary_paise": salary, "band_min_paise": band.min_paise,
            "band_mid_paise": band.mid_paise, "band_max_paise": band.max_paise,
            "compa_ratio": float(ratio), "band_position": position,
        }

    async def register_market_benchmark(
        self, *, company_id: uuid.UUID, grade: str, designation: str, region: str,
        min_paise: int, median_paise: int, max_paise: int, source: str, effective_date: date,
    ):
        from app.models.compensation import CompensationMarketBenchmark
        if not int(min_paise) <= int(median_paise) <= int(max_paise) or int(min_paise) < 0:
            raise ValueError("Market benchmark values are invalid.")
        benchmark = CompensationMarketBenchmark(
            id=uuid.uuid4(), company_id=company_id, grade=grade.upper(), designation=designation,
            region=region, min_paise=int(min_paise), median_paise=int(median_paise),
            max_paise=int(max_paise), source=source, effective_date=effective_date,
        )
        self.session.add(benchmark)
        await self.session.commit()
        return benchmark

    async def market_comparison(self, *, company_id: uuid.UUID, employee_id: uuid.UUID, region: str = "IN") -> dict:
        from app.models.compensation import CompensationMarketBenchmark
        employee = await self._employee(employee_id, company_id)
        internal = await self.compa_ratio(company_id=company_id, employee_id=employee_id)
        band = await self._band(uuid.UUID(internal["band_id"]), company_id)
        benchmark = (await self.session.execute(select(CompensationMarketBenchmark).where(
            CompensationMarketBenchmark.company_id == company_id,
            CompensationMarketBenchmark.grade == band.grade,
            CompensationMarketBenchmark.designation == employee.designation,
            CompensationMarketBenchmark.region == region,
        ).order_by(CompensationMarketBenchmark.effective_date.desc()).limit(1))).scalar_one_or_none()
        if benchmark is None:
            return {**internal, "benchmark_found": False, "market_ratio": None}
        ratio = Decimal(internal["annual_salary_paise"]) / Decimal(benchmark.median_paise) if benchmark.median_paise else Decimal("0")
        return {
            **internal, "benchmark_found": True, "benchmark_id": str(benchmark.id),
            "market_median_paise": benchmark.median_paise, "market_ratio": float(ratio.quantize(Decimal("0.0001"))),
            "market_position": "BELOW_MARKET" if ratio < Decimal("0.9") else "ABOVE_MARKET" if ratio > Decimal("1.1") else "AT_MARKET",
        }

    async def model_department_increment(
        self, *, company_id: uuid.UUID, department: str, fiscal_year: str,
        budget_paise: int, recommendations: dict[uuid.UUID, float],
    ):
        from app.models.compensation import DepartmentIncrementBudget
        budget_value = self._paise(budget_paise, "Increment budget")
        budget = (await self.session.execute(select(DepartmentIncrementBudget).where(
            DepartmentIncrementBudget.company_id == company_id,
            DepartmentIncrementBudget.department == department,
            DepartmentIncrementBudget.fiscal_year == fiscal_year,
        ))).scalar_one_or_none()
        if budget is None:
            budget = DepartmentIncrementBudget(
                id=uuid.uuid4(), company_id=company_id, department=department,
                fiscal_year=fiscal_year, budget_paise=budget_value,
            )
        budget.budget_paise = budget_value
        lines, total = [], 0
        for employee_id, percentage_value in recommendations.items():
            percentage = Decimal(str(percentage_value))
            if percentage < 0 or percentage > 50:
                raise ValueError("Increment percentages must be between 0 and 50.")
            employee = await self._employee(employee_id, company_id)
            if employee.department != department:
                raise ValueError("Budget recommendations must belong to the budget department.")
            assignment = await self._current_assignment(employee_id, company_id)
            if assignment is None:
                raise ValueError(f"Employee {employee_id} has no current band assignment.")
            increment = int((Decimal(assignment.annual_salary_paise) * percentage / Decimal(100)).quantize(Decimal("1")))
            total += increment
            lines.append({
                "employee_id": str(employee_id), "current_salary_paise": assignment.annual_salary_paise,
                "increment_percentage": float(percentage), "increment_paise": increment,
                "projected_salary_paise": assignment.annual_salary_paise + increment,
            })
        if total > budget_value:
            raise ValueError("Modeled increments exceed the department budget.")
        budget.modeled_increment_paise = total
        budget.scenario_json = {
            "lines": lines, "remaining_budget_paise": budget_value - total,
            "budget_utilization_percentage": float((Decimal(total) * 100 / Decimal(budget_value)).quantize(Decimal("0.01"))) if budget_value else 0.0,
        }
        budget.status = "MODELED"
        self.session.add(budget)
        await self.session.commit()
        return budget

    async def recommend_increment(self, *, company_id: uuid.UUID, employee_id: uuid.UUID, calibrated_rating: float) -> dict:
        """Deterministic recommendation linked to calibrated performance and current compa-ratio."""
        rating = Decimal(str(calibrated_rating))
        if rating < 0 or rating > 5:
            raise ValueError("Calibrated rating must be between 0 and 5.")
        metrics = await self.compa_ratio(company_id=company_id, employee_id=employee_id)
        percentage = Decimal("12") if rating >= Decimal("4.5") else Decimal("9") if rating >= Decimal("4") else Decimal("6") if rating >= Decimal("3.5") else Decimal("3") if rating >= Decimal("3") else Decimal("0")
        compa = Decimal(str(metrics["compa_ratio"]))
        if compa > Decimal("1.20"):
            percentage /= Decimal("2")
        elif compa < Decimal("0.80") and percentage > 0:
            percentage += Decimal("2")
        percentage = min(percentage, Decimal("15"))
        return {**metrics, "calibrated_rating": float(rating), "recommended_increment_percentage": float(percentage)}

    async def pay_equity_report(self, *, company_id: uuid.UUID, minimum_group_size: int = 2) -> dict:
        """Unadjusted gender/grade pay gaps; small groups are suppressed for privacy."""
        from app.models.compensation import CompensationBand, EmployeeCompensationBand
        if minimum_group_size < 2:
            raise ValueError("Pay-equity reports require a minimum group size of at least two.")
        rows = (await self.session.execute(
            select(Employee, EmployeeCompensationBand, CompensationBand)
            .join(EmployeeCompensationBand, EmployeeCompensationBand.employee_id == Employee.id)
            .join(CompensationBand, CompensationBand.id == EmployeeCompensationBand.band_id)
            .where(
                Employee.company_id == company_id, Employee.is_deleted.is_(False), Employee.status == "ACTIVE",
                EmployeeCompensationBand.company_id == company_id, EmployeeCompensationBand.is_current.is_(True),
                CompensationBand.company_id == company_id,
            )
        )).all()
        groups: dict[tuple[str, str], list[int]] = {}
        for employee, assignment, band in rows:
            gender = (employee.gender or "UNSPECIFIED").strip().upper()
            groups.setdefault((band.grade, gender), []).append(assignment.annual_salary_paise)
        summaries = {}
        for (grade, gender), salaries in groups.items():
            count = len(salaries)
            summaries[(grade, gender)] = {
                "sample_count": count, "suppressed": count < minimum_group_size,
                "average_salary_paise": None if count < minimum_group_size else sum(salaries) // count,
            }
        grades = []
        for grade in sorted({key[0] for key in groups}):
            male = summaries.get((grade, "MALE"))
            female = summaries.get((grade, "FEMALE"))
            gap = None
            if male and female and not male["suppressed"] and not female["suppressed"] and male["average_salary_paise"]:
                gap = float(((Decimal(male["average_salary_paise"] - female["average_salary_paise"]) * 100) / Decimal(male["average_salary_paise"])).quantize(Decimal("0.01")))
            grades.append({
                "grade": grade, "male": male, "female": female,
                "unadjusted_male_female_gap_percentage": gap,
                "other_genders": [
                    {"gender": gender, **summary} for (group_grade, gender), summary in sorted(summaries.items())
                    if group_grade == grade and gender not in {"MALE", "FEMALE"}
                ],
            })
        return {
            "methodology": "UNADJUSTED_AVERAGE_PAY_GAP",
            "minimum_group_size": minimum_group_size,
            "employee_count": len(rows), "grades": grades,
            "note": "Unadjusted averages do not establish discrimination or control for tenure, role, location, or performance.",
        }
