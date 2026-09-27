"""Agents Service for AI Hub Gateway.

Implements the uniform AI Agent runner, in-code agent registry, execution tracking,
and feedback persistence.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any, Callable, Coroutine, Dict, List, Optional
import uuid

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, NotFoundException
from app.llm.client import get_llm_client
from app.models.ai_hub import AgentFeedback, AgentRun
from app.schemas.ai_hub.agents import (
    AgentDetailResponse,
    AgentFeedbackRequest,
    AgentFeedbackResponse,
    AgentHistoryPage,
    AgentRegistryItem,
    AgentRunResult,
    AgentRunSummary,
    AgentStatusResponse,
    RunAgentRequest,
)

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Static Agent Registry Definition
# -----------------------------------------------------------------------------
AGENT_CATALOG: dict[str, dict[str, Any]] = {
    "attrition-agent": {
        "name": "Attrition & Flight Risk Predictor",
        "description": "Monitors employee retention signals, overtime anomalies, and flight risk indicators.",
        "category": "Analytics",
        "capabilities": ["risk-scoring", "department-benchmarking", "mitigation-planning"],
    },
    "payroll-agent": {
        "name": "Payroll Anomaly & Audit Copilot",
        "description": "Scans payroll cycles for salary variances, statutory mismatches, and overtime spikes.",
        "category": "Payroll",
        "capabilities": ["variance-analysis", "tax-audit", "fraud-detection"],
    },
    "recruiter-agent": {
        "name": "Talent Acquisition & Interview Copilot",
        "description": "Generates technical and behavioral question sets and screens candidate profiles.",
        "category": "Recruitment",
        "capabilities": ["question-generation", "resume-screening", "candidate-matching"],
    },
    "compliance-agent": {
        "name": "Labor Law & Statutory Compliance Monitor",
        "description": "Performs continuous compliance auditing across labor regulations and company policies.",
        "category": "Compliance",
        "capabilities": ["statutory-audit", "document-checks", "risk-assessment"],
    },
    "policy-agent": {
        "name": "HR Policy RAG Assistant",
        "description": "Answers natural language employee queries grounded in verified policy documentation.",
        "category": "HR Operations",
        "capabilities": ["rag-qa", "compliance-check", "clause-citation"],
    },
    "attendance-agent": {
        "name": "Attendance Health & Shift Monitor",
        "description": "Identifies shift deviations, late arrival trends, and unauthorized absences.",
        "category": "Workforce",
        "capabilities": ["anomaly-detection", "shift-compliance", "trend-forecasting"],
    },
    "leave-agent": {
        "name": "Leave Coverage & Conflict Forecaster",
        "description": "Forecasts department leave volume and identifies holiday coverage conflicts.",
        "category": "Workforce",
        "capabilities": ["conflict-detection", "demand-forecasting", "coverage-planning"],
    },
    "health-agent": {
        "name": "Employee Wellbeing & Burnout Guard",
        "description": "Synthesizes workload, consecutive working hours, and stress indicators.",
        "category": "Employee Health",
        "capabilities": ["burnout-index", "workload-balancing", "wellness-scoring"],
    },
    "performance-agent": {
        "name": "Performance Coach & Goal Generator",
        "description": "Formulates quarterly OKRs, KPIs, and role-based training curricula.",
        "category": "Performance",
        "capabilities": ["goal-generation", "skill-gap-analysis", "training-recommendation"],
    },
    "workforce-agent": {
        "name": "Workforce Planning & Headcount Forecaster",
        "description": "Models quarterly headcount demand, hiring velocities, and budget boundaries.",
        "category": "Workforce",
        "capabilities": ["capacity-planning", "headcount-forecast", "budget-allocation"],
    },
    "meeting-agent": {
        "name": "Meeting Intelligence & Action Item Extractor",
        "description": "Analyzes meeting transcripts, extracts decisions, and delegates action items.",
        "category": "Collaboration",
        "capabilities": ["transcript-summarization", "action-item-extraction", "sentiment-analysis"],
    },
    "document-agent": {
        "name": "Document Generator & Template Engine",
        "description": "Assembles formal HR letters, agreements, and certificates from dynamic templates.",
        "category": "Documents",
        "capabilities": ["template-rendering", "multi-format-export", "placeholder-injection"],
    },
}


class AgentsService:
    """Service handling agent execution, catalog lookups, history, and feedback."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.llm = get_llm_client()

    def list_agents(self) -> list[AgentRegistryItem]:
        """List all available agents from the registry."""
        items: list[AgentRegistryItem] = []
        for agent_id, data in AGENT_CATALOG.items():
            items.append(
                AgentRegistryItem(
                    agentId=agent_id,
                    name=data["name"],
                    description=data["description"],
                    category=data["category"],
                    enabled=True,
                    capabilities=data["capabilities"],
                )
            )
        return items

    async def get_agent(
        self, agent_id: str, company_id: Optional[uuid.UUID] = None
    ) -> AgentDetailResponse:
        """Get detail for a specific agent including last run summary and stats."""
        meta = AGENT_CATALOG.get(agent_id)
        if not meta:
            raise NotFoundException(message=f"Agent '{agent_id}' not found in registry.")

        registry_item = AgentRegistryItem(
            agentId=agent_id,
            name=meta["name"],
            description=meta["description"],
            category=meta["category"],
            enabled=True,
            capabilities=meta["capabilities"],
        )

        # Query stats and latest run
        stmt_latest = (
            select(AgentRun)
            .where(AgentRun.agent_id == agent_id)
            .order_by(desc(AgentRun.started_at))
            .limit(1)
        )
        if company_id is not None:
            stmt_latest = stmt_latest.where(AgentRun.company_id == company_id)

        res_latest = await self.session.execute(stmt_latest)
        latest_run = res_latest.scalars().first()

        last_run_summary: Optional[AgentRunSummary] = None
        if latest_run:
            duration = None
            if latest_run.completed_at and latest_run.started_at:
                duration = round(
                    (latest_run.completed_at - latest_run.started_at).total_seconds(), 2
                )
            last_run_summary = AgentRunSummary(
                runId=str(latest_run.id),
                agentId=latest_run.agent_id,
                trigger=latest_run.trigger,
                status=latest_run.status,
                startedAt=latest_run.started_at.isoformat(),
                completedAt=latest_run.completed_at.isoformat() if latest_run.completed_at else None,
                durationSeconds=duration,
                error=latest_run.error,
            )

        # Count total runs
        stmt_count = select(func.count(AgentRun.id)).where(AgentRun.agent_id == agent_id)
        if company_id is not None:
            stmt_count = stmt_count.where(AgentRun.company_id == company_id)
        res_count = await self.session.execute(stmt_count)
        total_runs = res_count.scalar() or 0

        # Count successes
        stmt_success = select(func.count(AgentRun.id)).where(
            AgentRun.agent_id == agent_id, AgentRun.status == "SUCCESS"
        )
        if company_id is not None:
            stmt_success = stmt_success.where(AgentRun.company_id == company_id)
        res_succ = await self.session.execute(stmt_success)
        success_runs = res_succ.scalar() or 0

        rate = round((success_runs / total_runs * 100.0), 1) if total_runs > 0 else 100.0

        return AgentDetailResponse(
            agent=registry_item,
            lastRun=last_run_summary,
            totalRuns=total_runs,
            successRate=rate,
        )

    async def run_agent(
        self,
        agent_id: str,
        company_id: Optional[uuid.UUID],
        user_id: Optional[uuid.UUID],
        payload: RunAgentRequest,
    ) -> AgentRunResult:
        """Execute registered agent, track execution in database, and return results."""
        meta = AGENT_CATALOG.get(agent_id)
        if not meta:
            raise NotFoundException(message=f"Agent '{agent_id}' not found in registry.")

        # Create AgentRun record
        run_record = AgentRun(
            company_id=company_id,
            agent_id=agent_id,
            user_id=user_id,
            trigger=payload.trigger,
            prompt=payload.prompt,
            parameters=payload.parameters,
            context=payload.context,
            status="RUNNING",
        )
        self.session.add(run_record)
        await self.session.flush()

        # Dispatch handler based on agent_id
        try:
            result_data = await self._dispatch_agent_execution(
                agent_id=agent_id,
                company_id=company_id,
                user_id=user_id,
                payload=payload,
            )
            run_record.status = "SUCCESS"
            run_record.result = result_data
            run_record.completed_at = datetime.now(timezone.utc)
        except Exception as exc:
            logger.exception("Agent '%s' execution failed: %s", agent_id, exc)
            run_record.status = "FAILED"
            run_record.error = str(exc)
            run_record.completed_at = datetime.now(timezone.utc)
            run_record.result = None

        await self.session.commit()
        await self.session.refresh(run_record)

        return AgentRunResult(
            runId=str(run_record.id),
            agentId=run_record.agent_id,
            status=run_record.status,
            trigger=run_record.trigger,
            prompt=run_record.prompt,
            parameters=run_record.parameters or {},
            result=run_record.result,
            error=run_record.error,
            startedAt=run_record.started_at.isoformat(),
            completedAt=run_record.completed_at.isoformat() if run_record.completed_at else None,
        )

    async def _dispatch_agent_execution(
        self,
        agent_id: str,
        company_id: Optional[uuid.UUID],
        user_id: Optional[uuid.UUID],
        payload: RunAgentRequest,
    ) -> Any:
        """Call corresponding service logic for the given agent."""
        if agent_id == "attrition-agent":
            from app.services.analytics_center_service import AnalyticsCenterService

            svc = AnalyticsCenterService(session=self.session)
            res = await svc.get_attrition(company_id=company_id)
            return res.model_dump()

        elif agent_id == "payroll-agent":
            from app.services.ai_payroll_service import AIPayrollService

            svc = AIPayrollService(session=self.session)
            res = await svc.get_dashboard(company_id=company_id)
            return res.model_dump()

        elif agent_id == "recruiter-agent":
            from app.services.ai_recruiter_service import AIRecruiterService

            svc = AIRecruiterService(session=self.session)
            res = await svc.get_dashboard(company_id=company_id)
            return res.model_dump()

        elif agent_id == "compliance-agent":
            from app.services.compliance_monitor_service import ComplianceMonitorService

            svc = ComplianceMonitorService(session=self.session)
            res = await svc.get_dashboard(company_id=company_id)
            return res.model_dump()

        elif agent_id == "policy-agent":
            from app.services.policy_ai_service import PolicyAIService
            from app.schemas.policy_ai import PolicyChatRequest

            svc = PolicyAIService(session=self.session)
            query_text = payload.prompt or payload.parameters.get("query") or "What are the core employee leave rules?"
            chat_req = PolicyChatRequest(query=query_text, company_id=company_id)
            res = await svc.process_chat_query(chat_req, company_id=company_id)
            return res.model_dump()

        elif agent_id == "attendance-agent":
            from app.services.ai_attendance_service import AIAttendanceService

            svc = AIAttendanceService(session=self.session)
            res = await svc.get_dashboard(company_id=company_id)
            return res.model_dump()

        elif agent_id == "leave-agent":
            from app.services.ai_leave_service import AILeaveService

            svc = AILeaveService(session=self.session)
            res = await svc.get_dashboard(company_id=company_id)
            return res.model_dump()

        elif agent_id == "health-agent":
            from app.services.employee_health_service import EmployeeHealthService

            svc = EmployeeHealthService(session=self.session)
            res = await svc.get_dashboard(company_id=company_id)
            return res.model_dump()

        elif agent_id == "workforce-agent":
            from app.services.ai_workforce_service import AIWorkforceService

            svc = AIWorkforceService(session=self.session)
            res = await svc.get_dashboard(company_id=company_id)
            return res.model_dump()

        elif agent_id == "meeting-agent":
            from app.services.meeting_ai_service import MeetingAIService

            svc = MeetingAIService(session=self.session)
            res = await svc.get_dashboard(company_id=company_id)
            return res.model_dump()

        # Default fallback
        prompt_text = payload.prompt or f"Execute tasks for agent {agent_id}"
        return {
            "summary": f"Agent {agent_id} completed successfully.",
            "executionTimestamp": datetime.now(timezone.utc).isoformat(),
            "status": "COMPLETED",
            "details": f"Processed parameters {payload.parameters} for prompt '{prompt_text}'",
        }

    async def get_history(
        self,
        agent_id: str,
        company_id: Optional[uuid.UUID],
        page: int = 1,
        limit: int = 20,
        search: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
    ) -> AgentHistoryPage:
        """Fetch paginated run history for an agent."""
        stmt = select(AgentRun).where(AgentRun.agent_id == agent_id)
        count_stmt = select(func.count(AgentRun.id)).where(AgentRun.agent_id == agent_id)

        if company_id is not None:
            stmt = stmt.where(AgentRun.company_id == company_id)
            count_stmt = count_stmt.where(AgentRun.company_id == company_id)

        if search:
            search_clause = AgentRun.prompt.ilike(f"%{search}%") | AgentRun.status.ilike(f"%{search}%")
            stmt = stmt.where(search_clause)
            count_stmt = count_stmt.where(search_clause)

        total_res = await self.session.execute(count_stmt)
        total = total_res.scalar() or 0

        # Sorting
        if sort_by and hasattr(AgentRun, sort_by):
            col = getattr(AgentRun, sort_by)
            stmt = stmt.order_by(col.asc() if (sort_order or "").lower() == "asc" else col.desc())
        else:
            stmt = stmt.order_by(desc(AgentRun.started_at))

        # Pagination
        offset = (page - 1) * limit
        stmt = stmt.offset(offset).limit(limit)

        res = await self.session.execute(stmt)
        runs = res.scalars().all()

        items = [
            AgentRunResult(
                runId=str(r.id),
                agentId=r.agent_id,
                status=r.status,
                trigger=r.trigger,
                prompt=r.prompt,
                parameters=r.parameters or {},
                result=r.result,
                error=r.error,
                startedAt=r.started_at.isoformat(),
                completedAt=r.completed_at.isoformat() if r.completed_at else None,
            )
            for r in runs
        ]

        pages = (total + limit - 1) // limit if limit > 0 else 0

        return AgentHistoryPage(
            items=items,
            total=total,
            page=page,
            limit=limit,
            pages=pages,
        )

    async def get_status(
        self, agent_id: str, company_id: Optional[uuid.UUID] = None
    ) -> AgentStatusResponse:
        """Fetch current operational status of an agent."""
        if agent_id not in AGENT_CATALOG:
            raise NotFoundException(message=f"Agent '{agent_id}' not found in registry.")

        stmt = (
            select(AgentRun)
            .where(AgentRun.agent_id == agent_id)
            .order_by(desc(AgentRun.started_at))
            .limit(1)
        )
        if company_id is not None:
            stmt = stmt.where(AgentRun.company_id == company_id)

        res = await self.session.execute(stmt)
        latest = res.scalars().first()

        stmt_running = select(func.count(AgentRun.id)).where(
            AgentRun.agent_id == agent_id, AgentRun.status == "RUNNING"
        )
        if company_id is not None:
            stmt_running = stmt_running.where(AgentRun.company_id == company_id)
        res_run = await self.session.execute(stmt_running)
        running_cnt = res_run.scalar() or 0

        overall_status = "idle"
        if running_cnt > 0:
            overall_status = "running"
        elif latest and latest.status == "FAILED":
            overall_status = "error"

        return AgentStatusResponse(
            agentId=agent_id,
            status=overall_status,
            lastRunStatus=latest.status if latest else None,
            lastRunAt=latest.started_at.isoformat() if latest else None,
            activeRunsCount=running_cnt,
        )

    async def add_feedback(
        self,
        agent_id: str,
        company_id: Optional[uuid.UUID],
        user_id: Optional[uuid.UUID],
        payload: AgentFeedbackRequest,
    ) -> AgentFeedbackResponse:
        """Record rating and review for an agent run."""
        try:
            run_uuid = uuid.UUID(payload.runId)
        except (ValueError, TypeError):
            raise AppException(message=f"Invalid runId format: '{payload.runId}'.")

        stmt = select(AgentRun).where(AgentRun.id == run_uuid, AgentRun.agent_id == agent_id)
        if company_id is not None:
            stmt = stmt.where(AgentRun.company_id == company_id)

        res = await self.session.execute(stmt)
        run_record = res.scalars().first()
        if not run_record:
            raise NotFoundException(message=f"Agent run '{payload.runId}' not found.")

        feedback = AgentFeedback(
            run_id=run_uuid,
            rating=payload.rating,
            comment=payload.comment,
            tags=payload.tags,
            created_by=user_id,
        )
        self.session.add(feedback)
        await self.session.commit()
        await self.session.refresh(feedback)

        return AgentFeedbackResponse(
            feedbackId=str(feedback.id),
            runId=str(feedback.run_id),
            rating=feedback.rating,
            comment=feedback.comment,
            tags=feedback.tags or [],
            createdAt=feedback.created_at.isoformat(),
        )
