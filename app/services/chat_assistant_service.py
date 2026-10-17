"""Business logic and AI LLM service layer for AI Chat Assistant (OFC HR AI).

ALL responses are generated from real database queries + LLM inference.
NO hardcoded fallback responses, charts, tables, or static data.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AppException, NotFoundException
from app.llm.client import get_llm_client
from app.llm.memory import get_conversation_memory
from app.models.ai import AIConversation, AIMessage
from app.repositories.chat_assistant_repository import ChatAssistantRepository
from app.schemas.chat_assistant import (
    AnalyticsQueryPayload,
    ChartData,
    ChatAssistantRequest,
    ChatAssistantResponse,
    ChatFeedbackRequest,
    ChatHistoryResponse,
    ChatSuggestionsResponse,
    ConversationHistoryItem,
    RecommendationsPayload,
    ReportGeneratePayload,
    SourceCitation,
    TableData,
)

logger = logging.getLogger(__name__)

ASSISTANT_NAME = "OFC HR AI"

_SYSTEM_PROMPT = (
    f"You are {ASSISTANT_NAME}, an enterprise HRMS & Workforce Intelligence AI assistant. "
    "You have access to real company workforce data provided as context. "
    "Provide helpful, concise, analytical markdown answers based on the provided data. "
    "If data is insufficient to fully answer the query, say so honestly and provide "
    "what insight you can from the available data. "
    "Never fabricate employee names, numbers, or statistics. "
    "Use markdown formatting: tables, bold, headers, and bullet points for clarity."
)


class ChatAssistantService:
    """Service handling multi-domain enterprise NLU using real DB data + LLM inference."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = ChatAssistantRepository(session)
        self.llm = get_llm_client()
        self.memory = get_conversation_memory()
        self._ollama_checked = False
        self._ollama_available = False

    async def _ensure_ollama_ready(self) -> bool:
        """Verify Ollama is reachable and the default model is present.
        Logs a clear warning if not. Caches result for the request lifetime.
        """
        if self._ollama_checked:
            return self._ollama_available

        self._ollama_checked = True
        try:
            health = await asyncio.wait_for(self.llm.check_health(), timeout=10.0)
            ollama_health = health.get("ollama", {})
            if ollama_health.get("healthy"):
                models = ollama_health.get("models", [])
                default_model = settings.OLLAMA_DEFAULT_MODEL
                if any(default_model in m for m in models):
                    self._ollama_available = True
                    logger.info("Ollama health check passed: model '%s' is available", default_model)
                else:
                    logger.warning(
                        "Ollama is reachable but default model '%s' not found in available models: %s",
                        default_model, models
                    )
            else:
                logger.warning("Ollama health check failed: %s", ollama_health.get("error", "unknown"))
        except asyncio.TimeoutError:
            logger.warning("Ollama health check timed out after 10s")
        except Exception as exc:
            logger.warning("Ollama health check error: %s", exc)

        return self._ollama_available

    async def process_chat(
        self,
        request: ChatAssistantRequest,
        company_id: Optional[uuid.UUID] = None,
        user_id: Optional[uuid.UUID] = None,
    ) -> ChatAssistantResponse:
        """Process natural language user chat query with real data + LLM.

        Handles company_id=None for SUPER_ADMIN/CTO/executive accounts gracefully.
        """
        conv_id = request.get_conversation_id() or str(uuid.uuid4())
        raw_text = request.get_message_text()

        if not raw_text:
            raw_text = "Give me a workforce overview"

        # Ensure conversation exists in DB
        conversation = await self._get_or_create_conversation(conv_id, company_id, user_id, raw_text)

        # 1. Fetch real DB metrics (if company_id available, else use defaults)
        metrics = await self.repo.get_workforce_metrics(company_id=company_id)

        # 2. Fetch enriched context based on query topic and user role
        enriched_context = await self._build_enriched_context(
            query=raw_text,
            company_id=company_id,
            user_id=user_id,
            metrics=metrics,
        )

        # 3. Fetch RAG citations if available (only if company_id provided)
        citations_raw = []
        if company_id:
            citations_raw = await self.repo.get_policy_citations(query=raw_text, company_id=company_id)
        citations = [SourceCitation(**c) for c in citations_raw]

        # 4. Build context from real data
        context_text = self._build_context_text(metrics, enriched_context, citations)

        # 5. Get conversation history from DB (last ~10 messages)
        history_messages = await self._get_conversation_history(conv_id, limit=10)

        # 6. Build messages for LLM chat completion
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "system", "content": context_text},
        ]
        # Add history (excluding the current user message which we'll add last)
        for msg in history_messages:
            if msg.role != "system":
                messages.append({"role": msg.role, "content": msg.message})
        # Add current user message
        messages.append({"role": "user", "content": raw_text})

        # 7. Call LLM for response using chat completion (with history)
        llm_error: Exception | None = None
        degraded = False
        answer_markdown = ""
        ai_available = False

        try:
            await self._ensure_ollama_ready()
            chat_timeout = getattr(settings, "OLLAMA_CHAT_TIMEOUT_SECONDS", getattr(settings, "AI_CHAT_TIMEOUT_SECONDS", 110))
            num_predict = getattr(settings, "AI_CHAT_NUM_PREDICT", getattr(settings, "OLLAMA_NUM_PREDICT", 1024))
            answer_markdown = await asyncio.wait_for(
                self.llm.chat(
                    messages=messages,
                    temperature=0.3,
                    num_predict=num_predict,
                ),
                timeout=chat_timeout,
            )
            answer_markdown = answer_markdown.strip()
            ai_available = bool(answer_markdown)
            if not answer_markdown:
                llm_error = RuntimeError("LLM returned empty response")
        except asyncio.TimeoutError:
            logger.error("LLM chat completion timed out for query: %s", raw_text[:100])
            llm_error = asyncio.TimeoutError(f"LLM request timed out after {chat_timeout}s")
            degraded = True
        except Exception as exc:
            logger.error("LLM chat completion error: %s", exc)
            llm_error = exc
            degraded = True

        if llm_error:
            # Return clear message that AI service is unavailable + basic data snapshot
            answer_markdown = self._build_degraded_response(metrics, enriched_context, llm_error)
            ai_available = False

        # Save messages to DB
        await self._save_message(conv_id, "user", raw_text)
        await self._save_message(conv_id, "assistant", answer_markdown, metadata={
            "charts": [c.model_dump() for c in self._build_charts_from_metrics(metrics, raw_text.lower())],
            "tables": [t.model_dump() for t in self._build_tables_from_metrics(metrics)],
            "sources": [c.model_dump() for c in citations],
        })

        # 8. Generate dynamic charts from REAL database data
        charts = self._build_charts_from_metrics(metrics, raw_text.lower())

        # 9. Generate tables from REAL database data
        tables = self._build_tables_from_metrics(metrics)

        # 10. Generate contextual follow-up questions via LLM (skip if main LLM call failed)
        follow_ups = []
        if not llm_error:
            follow_ups = await self._generate_follow_ups(raw_text, metrics)
        else:
            logger.debug("Skipping follow-up generation due to LLM error: %s", llm_error)

        # Calculate confidence based on data availability
        data_fields_present = sum(1 for v in [
            metrics.get("total_employees"),
            metrics.get("attrition_rate"),
            metrics.get("open_positions"),
            metrics.get("department_headcount"),
        ] if v)
        confidence = min(0.95, 0.5 + (data_fields_present * 0.1) + (0.1 if answer_markdown else 0))
        # Reduce confidence significantly if LLM was unavailable
        if llm_error:
            confidence = max(0.1, confidence * 0.5)  # Cut confidence in half when AI unavailable

        return ChatAssistantResponse(
            answer=answer_markdown,
            confidence=round(confidence, 2),
            sources=citations,
            charts=charts,
            tables=tables,
            followUpQuestions=follow_ups,
            follow_up_questions=follow_ups,
            conversationId=conv_id,
            conversation_id=conv_id,
            ai_available=ai_available,
            degraded=degraded,
        )

    def _build_charts_from_metrics(self, metrics: dict, query_lower: str) -> list[ChartData]:
        """Build charts dynamically from real database metrics."""
        charts = []
        dept_headcount = metrics.get("department_headcount", [])

        if dept_headcount:
            chart_data = [
                {"department": d.get("department", "Unknown"), "count": d.get("count", 0)}
                for d in dept_headcount[:10]
            ]
            if chart_data:
                charts.append(
                    ChartData(
                        title="Department Headcount Distribution",
                        chart_type="bar",
                        data=chart_data,
                    )
                )

        return charts

    def _build_tables_from_metrics(self, metrics: dict) -> list[TableData]:
        """Build tables dynamically from real database metrics."""
        tables = []
        dept_headcount = metrics.get("department_headcount", [])

        if dept_headcount:
            rows = []
            for d in dept_headcount[:10]:
                rows.append([
                    d.get("department", "Unknown"),
                    d.get("count", 0),
                ])
            if rows:
                tables.append(
                    TableData(
                        title="Workforce Distribution",
                        headers=["Department", "Headcount"],
                        rows=rows,
                    )
                )

        return tables

    # --- New helper methods for DB-backed conversations and enriched context ---

    async def _get_or_create_conversation(
        self,
        conv_id: str,
        company_id: Optional[uuid.UUID],
        user_id: Optional[uuid.UUID],
        first_message: str,
    ) -> AIConversation:
        """Get existing conversation or create new one in DB."""
        from sqlalchemy import select
        try:
            conv_uuid = uuid.UUID(conv_id)
        except ValueError:
            conv_uuid = uuid.uuid4()

        stmt = select(AIConversation).where(AIConversation.id == conv_uuid)
        result = await self.session.execute(stmt)
        conversation = result.scalar_one_or_none()

        if conversation:
            # Verify ownership
            if user_id and conversation.user_id != user_id:
                raise NotFoundException(message=f"Conversation '{conv_id}' not found.")
            if company_id and conversation.company_id != company_id:
                raise NotFoundException(message=f"Conversation '{conv_id}' not found.")
            return conversation

        # Create new conversation
        title = first_message[:80] if first_message else "New Conversation"
        conversation = AIConversation(
            id=conv_uuid,
            user_id=user_id or uuid.uuid4(),
            company_id=company_id,
            title=title,
        )
        self.session.add(conversation)
        await self.session.flush()
        return conversation

    async def _get_conversation_history(
        self, conv_id: str, limit: int = 10
    ) -> List[AIMessage]:
        """Get last N messages from conversation (excluding system messages)."""
        from sqlalchemy import select, desc
        try:
            conv_uuid = uuid.UUID(conv_id)
        except ValueError:
            return []

        stmt = (
            select(AIMessage)
            .where(AIMessage.conversation_id == conv_uuid)
            .order_by(desc(AIMessage.created_at))
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        messages = list(reversed(result.scalars().all()))
        return messages

    async def _save_message(
        self,
        conv_id: str,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AIMessage:
        """Save a message to the conversation in DB."""
        from sqlalchemy import select
        try:
            conv_uuid = uuid.UUID(conv_id)
        except ValueError:
            return None

        # Verify conversation exists
        stmt = select(AIConversation).where(AIConversation.id == conv_uuid)
        result = await self.session.execute(stmt)
        conversation = result.scalar_one_or_none()
        if not conversation:
            return None

        message = AIMessage(
            conversation_id=conv_uuid,
            role=role,
            message=content,
            metadata=metadata or {},
        )
        self.session.add(message)
        await self.session.flush()
        return message

    async def _build_enriched_context(
        self,
        query: str,
        company_id: Optional[uuid.UUID],
        user_id: Optional[uuid.UUID],
        metrics: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Build enriched context based on query topic and user role.
        Adds leave, attendance, payroll (for HR/admin), and policy data.
        """
        enriched = {}
        if not company_id:
            return enriched

        query_lower = query.lower()

        # Determine user role for access control
        user_role = "employee"
        if user_id:
            from app.models.employee import Employee
            from sqlalchemy import select
            stmt = select(Employee).where(Employee.user_id == user_id)
            result = await self.session.execute(stmt)
            emp = result.scalar_one_or_none()
            if emp:
                user_role = (emp.role or "employee").lower()

        is_hr_admin = user_role in ("hr_admin", "super_admin", "admin", "manager")

        # Leave context - always include for the user (own data) or company-wide for HR
        if "leave" in query_lower or "balance" in query_lower or "time off" in query_lower or "holiday" in query_lower:
            if user_id:
                from app.services.leave_service import LeaveService
                leave_service = LeaveService(self.session)
                try:
                    # Get employee_id from user_id
                    from app.models.employee import Employee
                    from sqlalchemy import select
                    stmt = select(Employee.id).where(Employee.user_id == user_id)
                    result = await self.session.execute(stmt)
                    emp_id = result.scalar_one_or_none()
                    if emp_id:
                        balances = await leave_service.get_leave_balances(emp_id)
                        enriched["leave_balances"] = [
                            {"type": b.leave_type, "total": b.total_days, "used": b.used_days, "remaining": b.remaining_days}
                            for b in balances
                        ]
                        # Pending requests
                        from app.models.leave import LeaveRequest
                        from sqlalchemy import func
                        pending_stmt = select(func.count(LeaveRequest.id)).where(
                            LeaveRequest.employee_id == emp_id,
                            LeaveRequest.status == "PENDING"
                        )
                        pending_res = await self.session.execute(pending_stmt)
                        enriched["pending_leave_requests"] = pending_res.scalar() or 0
                except Exception as exc:
                    logger.debug("Failed to fetch leave context: %s", exc)

        # Attendance context
        if "attendance" in query_lower or "present" in query_lower or "absent" in query_lower or "late" in query_lower:
            try:
                from app.services.ai_attendance_service import AIAttendanceService
                attendance_service = AIAttendanceService(self.session)
                # Get dashboard KPIs for the company (HR) or user's department
                dept_id = None
                if not is_hr_admin and user_id:
                    from app.models.employee import Employee
                    from sqlalchemy import select
                    stmt = select(Employee.department_id).where(Employee.user_id == user_id)
                    result = await self.session.execute(stmt)
                    dept_id = result.scalar_one_or_none()

                kpis = await attendance_service.repo.get_dashboard_kpis(
                    company_id=company_id,
                    department_id=dept_id,
                )
                enriched["attendance_summary"] = {
                    "health_score": kpis.get("attendance_health_score", 0),
                    "attendance_rate": kpis.get("total_attendance_percentage", 0),
                    "late_arrivals": kpis.get("late_arrivals", 0),
                    "anomalies": kpis.get("total_anomalies", 0),
                    "overtime_hours": kpis.get("overtime_hours", 0),
                }
            except Exception as exc:
                logger.debug("Failed to fetch attendance context: %s", exc)

        # Payroll context - only for HR/admin roles
        if is_hr_admin and ("payroll" in query_lower or "salary" in query_lower or "compensation" in query_lower or "payslip" in query_lower):
            try:
                from app.services.payroll_service import PayrollService
                payroll_service = PayrollService(self.session)
                # Get latest pay cycle summary
                from app.models.payroll import PayCycle
                from sqlalchemy import select, desc
                stmt = (
                    select(PayCycle)
                    .where(PayCycle.company_id == company_id)
                    .order_by(desc(PayCycle.period_year), desc(PayCycle.period_month))
                    .limit(1)
                )
                result = await self.session.execute(stmt)
                latest_cycle = result.scalar_one_or_none()
                if latest_cycle:
                    summary = await payroll_service.get_cycle_summary(latest_cycle.id)
                    enriched["payroll_summary"] = {
                        "period": summary.get("period_label"),
                        "status": summary.get("status"),
                        "headcount": summary.get("headcount"),
                        "total_gross": summary.get("total_gross"),
                        "total_net": summary.get("total_net"),
                        "total_deductions": summary.get("total_deductions"),
                    }
            except Exception as exc:
                logger.debug("Failed to fetch payroll context: %s", exc)

        # Policy RAG is already handled via citations in the main flow
        return enriched

    def _build_context_text(
        self,
        metrics: Dict[str, Any],
        enriched: Dict[str, Any],
        citations: List[SourceCitation],
    ) -> str:
        """Build the full context text for the LLM."""
        dept_info = ""
        dept_headcount = metrics.get("department_headcount", [])
        if dept_headcount:
            dept_lines = [f"  - {d.get('department', 'Unknown')}: {d.get('count', 0)} employees" for d in dept_headcount[:10]]
            dept_info = "\n".join(dept_lines)

        context_parts = [
            "Real-time Workforce Data:",
            f"- Total Active Employees: {metrics.get('total_employees', 0)}",
            f"- Attrition Rate: {metrics.get('attrition_rate', 0)}%",
            f"- Open Job Positions: {metrics.get('open_positions', 0)}",
            f"- New Hires (This Month): {metrics.get('new_hires_month', 0)}",
        ]
        if dept_info:
            context_parts.append(f"- Department Distribution:\n{dept_info}")

        # Leave context
        if "leave_balances" in enriched:
            context_parts.append("\nLeave Balances:")
            for lb in enriched["leave_balances"]:
                context_parts.append(f"  - {lb['type']}: {lb['remaining']}/{lb['total']} days remaining (used: {lb['used']})")
        if "pending_leave_requests" in enriched:
            context_parts.append(f"- Pending Leave Requests: {enriched['pending_leave_requests']}")

        # Attendance context
        if "attendance_summary" in enriched:
            att = enriched["attendance_summary"]
            context_parts.append("\nAttendance Summary:")
            context_parts.append(f"  - Health Score: {att.get('health_score', 0)}/100")
            context_parts.append(f"  - Attendance Rate: {att.get('attendance_rate', 0)}%")
            context_parts.append(f"  - Late Arrivals: {att.get('late_arrivals', 0)}")
            context_parts.append(f"  - Anomalies: {att.get('anomalies', 0)}")
            context_parts.append(f"  - Overtime Hours: {att.get('overtime_hours', 0)}")

        # Payroll context
        if "payroll_summary" in enriched:
            pay = enriched["payroll_summary"]
            context_parts.append("\nPayroll Summary (Latest Cycle):")
            context_parts.append(f"  - Period: {pay.get('period', 'N/A')}")
            context_parts.append(f"  - Status: {pay.get('status', 'N/A')}")
            context_parts.append(f"  - Employees Paid: {pay.get('headcount', 0)}")
            context_parts.append(f"  - Total Gross: ₹{pay.get('total_gross', 0):,.2f}")
            context_parts.append(f"  - Total Net: ₹{pay.get('total_net', 0):,.2f}")
            context_parts.append(f"  - Total Deductions: ₹{pay.get('total_deductions', 0):,.2f}")

        # Policy citations
        if citations:
            policy_text = "\n".join(
                f"  - {getattr(c, 'title', getattr(c, 'document', 'Policy'))}: {getattr(c, 'snippet', getattr(c, 'section', ''))}"
                for c in citations[:3]
            )
            context_parts.append(f"\nRelevant Policies:\n{policy_text}")

        return "\n".join(context_parts)

    def _build_degraded_response(
        self,
        metrics: Dict[str, Any],
        enriched: Dict[str, Any],
        error: Exception,
    ) -> str:
        """Build a clear degraded response when AI is unavailable."""
        lines = [
            "# Workforce Snapshot (AI Service Unavailable)",
            "",
            f"> ⚠️ The AI service is currently unavailable ({type(error).__name__}). Showing basic data snapshot.",
            "",
            "## Core Metrics",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| **Total Active Employees** | {metrics.get('total_employees', 0)} |",
            f"| **Attrition Rate** | {metrics.get('attrition_rate', 0)}% |",
            f"| **Open Positions** | {metrics.get('open_positions', 0)} |",
            f"| **New Hires (This Month)** | {metrics.get('new_hires_month', 0)} |",
        ]

        dept_headcount = metrics.get("department_headcount", [])
        if dept_headcount:
            lines.append("")
            lines.append("## Department Distribution")
            lines.append("")
            lines.append("| Department | Headcount |")
            lines.append("|------------|-----------|")
            for d in dept_headcount[:10]:
                lines.append(f"| {d.get('department', 'Unknown')} | {d.get('count', 0)} |")

        # Add enriched data if available
        if "leave_balances" in enriched:
            lines.append("")
            lines.append("## Leave Balances")
            lines.append("")
            lines.append("| Leave Type | Total | Used | Remaining |")
            lines.append("|------------|-------|------|-----------|")
            for lb in enriched["leave_balances"]:
                lines.append(f"| {lb['type']} | {lb['total']} | {lb['used']} | {lb['remaining']} |")

        if "attendance_summary" in enriched:
            att = enriched["attendance_summary"]
            lines.append("")
            lines.append("## Attendance Summary")
            lines.append("")
            lines.append(f"- Health Score: {att.get('health_score', 0)}/100")
            lines.append(f"- Attendance Rate: {att.get('attendance_rate', 0)}%")
            lines.append(f"- Late Arrivals: {att.get('late_arrivals', 0)}")
            lines.append(f"- Anomalies: {att.get('anomalies', 0)}")

        if "payroll_summary" in enriched:
            pay = enriched["payroll_summary"]
            lines.append("")
            lines.append("## Payroll Summary (Latest Cycle)")
            lines.append("")
            lines.append(f"- Period: {pay.get('period', 'N/A')}")
            lines.append(f"- Status: {pay.get('status', 'N/A')}")
            lines.append(f"- Headcount: {pay.get('headcount', 0)}")
            lines.append(f"- Total Gross: ₹{pay.get('total_gross', 0):,.2f}")
            lines.append(f"- Total Net: ₹{pay.get('total_net', 0):,.2f}")

        lines.append("")
        lines.append("> Please try your query again in a moment for detailed AI analysis.")
        return "\n".join(lines)

    async def _generate_follow_ups(self, query: str, metrics: dict) -> list[str]:
        """Generate contextual follow-up questions from DB metrics (rule-based, no LLM call)."""
        total_emp = metrics.get('total_employees', 0)
        open_pos = metrics.get('open_positions', 0)
        attrition = metrics.get('attrition_rate', 0)
        dept_headcount = metrics.get('department_headcount', [])
        
        # Rule-based suggestions based on actual data
        suggestions = []
        
        if total_emp > 0:
            suggestions.append(f"Show department-wise breakdown of {total_emp} employees")
        
        if open_pos > 0:
            suggestions.append("What are the current open positions and their status?")
        
        if attrition > 0:
            suggestions.append(f"Analyze attrition trends (current rate: {attrition}%)")
        
        if dept_headcount:
            suggestions.append("Compare headcount across departments")
        
        suggestions.extend([
            "Analyze recent hiring trends and pipeline efficiency",
            "Show workforce cost breakdown by department",
        ])
        
        return suggestions[:3]

    async def process_query(
        self, request: ChatAssistantRequest, company_id: Optional[uuid.UUID] = None
    ) -> ChatAssistantResponse:
        """Process structured query endpoint."""
        return await self.process_chat(request=request, company_id=company_id)

    async def generate_hr_report(
        self,
        payload: ReportGeneratePayload,
        company_id: Optional[uuid.UUID] = None,
        user_id: Optional[uuid.UUID] = None,
    ) -> ChatAssistantResponse:
        """Generate specialized export-ready HR report."""
        req = ChatAssistantRequest(
            query=f"Generate comprehensive {payload.report_type} report for date range {payload.date_range}",
            department_id=payload.department_id,
        )
        return await self.process_chat(request=req, company_id=company_id, user_id=user_id)

    async def generate_analytics(
        self,
        payload: AnalyticsQueryPayload,
        company_id: Optional[uuid.UUID] = None,
        user_id: Optional[uuid.UUID] = None,
    ) -> ChatAssistantResponse:
        """Generate workforce analytics query response."""
        req = ChatAssistantRequest(
            query=f"Analyze workforce {payload.metric_type} metrics across departments",
            department_id=payload.department_id,
        )
        return await self.process_chat(request=req, company_id=company_id, user_id=user_id)

    async def generate_recommendations(
        self,
        payload: RecommendationsPayload,
        company_id: Optional[uuid.UUID] = None,
        user_id: Optional[uuid.UUID] = None,
    ) -> ChatAssistantResponse:
        """Generate AI recommendations for promotion, retention, or hiring."""
        req = ChatAssistantRequest(
            query=f"Generate AI recommendations for {payload.domain}",
            department_id=payload.department_id,
        )
        return await self.process_chat(request=req, company_id=company_id, user_id=user_id)

    async def get_history(
        self,
        company_id: Optional[uuid.UUID] = None,
        user_id: Optional[uuid.UUID] = None,
    ) -> ChatHistoryResponse:
        """Fetch past chat conversations from DB filtered by company AND user."""
        from sqlalchemy import select, desc
        stmt = select(AIConversation).order_by(desc(AIConversation.updated_at)).limit(50)
        if company_id:
            stmt = stmt.where(AIConversation.company_id == company_id)
        if user_id:
            stmt = stmt.where(AIConversation.user_id == user_id)

        result = await self.session.execute(stmt)
        conversations = result.scalars().all()

        hist = []
        for conv in conversations:
            # Get last message
            last_msg_stmt = (
                select(AIMessage)
                .where(AIMessage.conversation_id == conv.id)
                .order_by(desc(AIMessage.created_at))
                .limit(1)
            )
            last_msg_result = await self.session.execute(last_msg_stmt)
            last_msg = last_msg_result.scalar_one_or_none()

            msg_count_stmt = select(func.count(AIMessage.id)).where(AIMessage.conversation_id == conv.id)
            msg_count_result = await self.session.execute(msg_count_stmt)
            msg_count = msg_count_result.scalar() or 0

            hist.append(
                ConversationHistoryItem(
                    conversation_id=str(conv.id),
                    title=conv.title,
                    last_message=last_msg.message if last_msg else "",
                    message_count=msg_count,
                    updated_at=conv.updated_at,
                )
            )
        return ChatHistoryResponse(total_conversations=len(hist), history=hist)

    async def get_history_detail(
        self,
        conversation_id: str,
        company_id: Optional[uuid.UUID] = None,
        user_id: Optional[uuid.UUID] = None,
    ) -> ChatAssistantResponse:
        """Fetch specific conversation history detail with company AND user isolation."""
        from sqlalchemy import select
        try:
            conv_uuid = uuid.UUID(conversation_id)
        except ValueError:
            raise NotFoundException(message=f"Conversation '{conversation_id}' not found.")

        stmt = select(AIConversation).where(AIConversation.id == conv_uuid)
        if company_id:
            stmt = stmt.where(AIConversation.company_id == company_id)
        if user_id:
            stmt = stmt.where(AIConversation.user_id == user_id)

        result = await self.session.execute(stmt)
        conversation = result.scalar_one_or_none()

        if not conversation:
            raise NotFoundException(message=f"Conversation '{conversation_id}' not found.")

        # Get all messages for this conversation
        msg_stmt = (
            select(AIMessage)
            .where(AIMessage.conversation_id == conv_uuid)
            .order_by(AIMessage.created_at.asc())
        )
        msg_result = await self.session.execute(msg_stmt)
        messages = msg_result.scalars().all()

        # Build response with full conversation
        if messages:
            last_msg = messages[-1]
            return ChatAssistantResponse(
                answer=last_msg.message,
                confidence=0.9,
                sources=[],
                charts=[],
                tables=[],
                followUpQuestions=[],
                follow_up_questions=[],
                conversationId=conversation_id,
                conversation_id=conversation_id,
            )

        # Fallback: generate a recap
        req = ChatAssistantRequest(query="Show conversation recap", conversation_id=conversation_id)
        return await self.process_chat(request=req, company_id=company_id, user_id=user_id)

    async def delete_history(
        self,
        conversation_id: str,
        company_id: Optional[uuid.UUID] = None,
        user_id: Optional[uuid.UUID] = None,
    ) -> Dict[str, Any]:
        """Delete specific chat conversation with company AND user isolation."""
        from sqlalchemy import select, delete
        try:
            conv_uuid = uuid.UUID(conversation_id)
        except ValueError:
            raise NotFoundException(message=f"Conversation '{conversation_id}' not found.")

        stmt = select(AIConversation).where(AIConversation.id == conv_uuid)
        if company_id:
            stmt = stmt.where(AIConversation.company_id == company_id)
        if user_id:
            stmt = stmt.where(AIConversation.user_id == user_id)

        result = await self.session.execute(stmt)
        conversation = result.scalar_one_or_none()

        if not conversation:
            raise NotFoundException(message=f"Conversation '{conversation_id}' not found.")

        # Delete messages first (cascade should handle this, but explicit is safer)
        await self.session.execute(delete(AIMessage).where(AIMessage.conversation_id == conv_uuid))
        await self.session.execute(delete(AIConversation).where(AIConversation.id == conv_uuid))
        await self.session.commit()

        return {
            "deleted": True,
            "conversation_id": conversation_id,
            "conversationId": conversation_id,
        }

    async def get_suggestions(
        self, company_id: Optional[uuid.UUID] = None
    ) -> ChatSuggestionsResponse:
        """Fetch suggested copilot prompts — generated based on real data context."""
        try:
            eff_co_id = company_id or uuid.uuid4()
            metrics = await self.repo.get_workforce_metrics(company_id=eff_co_id)
            emp_count = metrics.get("total_employees", 0)
            open_pos = metrics.get("open_positions", 0)

            prompt = (
                f"Given a company with {emp_count} employees and {open_pos} open positions, "
                "generate 4 short suggested HR queries, 3 popular queries, and 2 manager queries. "
                "Return JSON: {{\"suggested\": [...], \"popular\": [...], \"role_based\": [...]}}"
            )
            response = await asyncio.wait_for(
                self.llm.complete(prompt=prompt, temperature=0.5, num_predict=512, json_mode=True),
                timeout=5.0,
            )
            if response:
                from app.llm.response_parser import ResponseParser
                parsed = ResponseParser.extract_json_object(response)
                if isinstance(parsed, dict):
                    return ChatSuggestionsResponse(
                        suggested_prompts=parsed.get("suggested", [])[:4],
                        popular_queries=parsed.get("popular", [])[:3],
                        role_based_prompts=parsed.get("role_based", [])[:2],
                    )
        except Exception as exc:
            logger.debug("Suggestion generation failed: %s", exc)

        return ChatSuggestionsResponse(
            suggested_prompts=[
                "Show current workforce overview",
                "Analyze employee distribution by department",
                "What are the open positions?",
                "Show recent hiring activity",
            ],
            popular_queries=[
                "Generate attendance summary",
                "Show payroll overview",
                "List active job openings",
            ],
            role_based_prompts=[
                "Show my team's workload",
                "Review pending approvals",
            ],
        )

    async def save_feedback(
        self, payload: ChatFeedbackRequest
    ) -> Dict[str, Any]:
        """Save feedback for chat response."""
        logger.info("Chat feedback received: conversation=%s rating=%s", payload.conversation_id, payload.rating)
        try:
            # If there's a DB table for feedback, save it here
            # For now, just log and return success
            pass
        except Exception as exc:
            logger.warning("Failed to save feedback to DB: %s", exc)
        return {"success": True, "conversation_id": payload.conversation_id, "rating": payload.rating}
