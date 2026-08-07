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
