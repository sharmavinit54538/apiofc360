"""Business logic and AI LLM service layer for AI Chat Assistant (OFC HR AI).

ALL responses are generated from real database queries + LLM inference.
NO hardcoded fallback responses, charts, tables, or static data.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import logging
import re
import time
from typing import Any, AsyncGenerator, Callable, Coroutine, Dict, List, Optional, Tuple
import uuid

from fastapi import HTTPException, status
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AppException, NotFoundException
from app.db.base import tenant_id_ctx
from app.db.database import AsyncSessionLocal
from app.llm.client import get_llm_client
from app.llm.memory import get_conversation_memory
from app.llm.providers.base import ProviderRequestError
from app.middleware.request_id import get_current_request_id
from app.models.ai import AIConversation, AIMessage
from app.repositories.chat_assistant_repository import ChatAssistantRepository
from app.schemas.chat_assistant import (
    AnalyticsQueryPayload,
    ChartData,
    ChatAssistantRequest,
    ChatAssistantResponse,
    ChatFeedbackRequest,
    ChatHistoryResponse,
    ChatMessageItem,
    ChatSuggestionsResponse,
    ConversationHistoryItem,
    MessageDeliveryStatusResponse,
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
    "Use markdown formatting: headers, bold text, bullet points, and tables (always place each markdown table row on its own separate line). "
    "Only include a full department table when the user asks for an overview, breakdown, headcount, or department details."
)

_COMPACT_GREETING_SYSTEM_PROMPT = (
    f"You are {ASSISTANT_NAME}, the OFC360 enterprise HR assistant. "
    "Respond warmly and concisely in 1-2 sentences, and offer help with workforce analytics, "
    "HR policies, leave, attendance, or payroll."
)

_GREETING_RE = re.compile(
    r"^(hi+|hii+|hey+|hello+|yo|hola|namaste|howdy|good\s+(morning|afternoon|evening)|"
    r"thanks|thank\s+you|thx|ok|okay|bye|goodbye|how\s+are\s+you[?!.\s]*)[!.,?\s]*$",
    re.IGNORECASE,
)

_HR_TOPIC_KEYWORDS = (
    "leave",
    "holiday",
    "pto",
    "attendance",
    "present",
    "absent",
    "late",
    "payroll",
    "salary",
    "compensation",
    "payslip",
    "policy",
    "policies",
    "headcount",
    "attrition",
    "hiring",
    "recruit",
    "employee",
    "department",
    "workforce",
    "report",
    "analytics",
    "performance",
)

# Bounded in-memory caches (strictly keyed by tenant/user scope where applicable)
_OLLAMA_READY_TTL_SECONDS = 30.0
_OLLAMA_READY_CACHE: dict[str, Any] = {"checked_at": 0.0, "available": False}

_SUGGESTIONS_TTL_SECONDS = 300.0
_SUGGESTIONS_CACHE: dict[str, tuple[float, ChatSuggestionsResponse]] = {}

_IDEMPOTENCY_TTL_SECONDS = 300.0
_IDEMPOTENCY_MAX_ENTRIES = 512
_IDEMPOTENCY_CACHE: dict[tuple[str, str, str], dict[str, Any]] = {}

# Active SSE / async generations indexed by (scope_key, client_message_id) and conv_id
_ACTIVE_STREAMS: dict[tuple[str, str, str], dict[str, Any]] = {}

_MAX_HISTORY_MSG_CHARS = 1500
_HEARTBEAT_INTERVAL_SECONDS = 10.0


def _sse_event(event_name: str, payload: dict[str, Any]) -> str:
    """Format a Server-Sent Event frame with JSON payload."""
    return f"event: {event_name}\ndata: {json.dumps(payload, default=str)}\n\n"


def _tenant_scope(company_id: Optional[uuid.UUID], user_id: Optional[uuid.UUID]) -> tuple[str, str]:
    return (str(company_id or "global"), str(user_id or "anon"))


def _prune_idempotency_cache(now: float) -> None:
    if len(_IDEMPOTENCY_CACHE) < _IDEMPOTENCY_MAX_ENTRIES and not _IDEMPOTENCY_CACHE:
        return
    expired = [k for k, v in _IDEMPOTENCY_CACHE.items() if (now - v.get("ts", 0.0)) > _IDEMPOTENCY_TTL_SECONDS]
    for k in expired:
        _IDEMPOTENCY_CACHE.pop(k, None)
    while len(_IDEMPOTENCY_CACHE) > _IDEMPOTENCY_MAX_ENTRIES:
        oldest_key = next(iter(_IDEMPOTENCY_CACHE))
        _IDEMPOTENCY_CACHE.pop(oldest_key, None)


def _normalize_metrics(metrics: Optional[dict[str, Any]]) -> dict[str, Any]:
    raw = metrics or {}
    return {
        "total_employees": int(raw.get("total_employees") or 0),
        "attrition_rate": float(raw.get("attrition_rate") or 0.0),
        "open_positions": int(raw.get("open_positions") or 0),
        "open_jobs": list(raw.get("open_jobs") or []),
        "new_hires_month": int(raw.get("new_hires_month") or 0),
        "department_headcount": list(raw.get("department_headcount") or []),
    }


def _is_simple_conversational_message(text: str) -> bool:
    cleaned = (text or "").strip()
    if not cleaned or len(cleaned) > 64:
        return False
    lowered = cleaned.lower()
    if any(kw in lowered for kw in _HR_TOPIC_KEYWORDS):
        return False
    return bool(_GREETING_RE.match(cleaned))


def _trim_history_content(text: str) -> str:
    cleaned = (text or "").strip()
    if len(cleaned) <= _MAX_HISTORY_MSG_CHARS:
        return cleaned
    return f"{cleaned[:_MAX_HISTORY_MSG_CHARS]}... [truncated]"


def _safe_error_payload(exc: Exception) -> tuple[int, str, str, bool]:
    """Map an exception into `(status_code, error_code, user_safe_message, retryable)`."""
    if isinstance(exc, ProviderRequestError):
        if exc.status_code in (401, 403):
            return (
                502,
                "invalid_api_key",
                "Unable to generate a response due to an AI configuration issue. Please contact your administrator.",
                False,
            )
        if exc.status_code == 429:
            return (
                429,
                "rate_limited",
                "The assistant is receiving high demand right now. Please wait a moment and retry.",
                True,
            )
        if exc.status_code == 504:
            return (
                504,
                "provider_timeout",
                "The assistant is taking longer than expected. Please try again.",
                True,
            )
        if exc.status_code == 503:
            return (
                503,
                "service_unavailable",
                "The AI service is temporarily unavailable. Please try again shortly.",
                True,
            )
        return (
            exc.status_code if exc.status_code >= 500 else 502,
            exc.code,
            exc.message or "Unable to generate a response. Please try again.",
            exc.retryable,
        )
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return (
            504,
            "provider_timeout",
            "The assistant is taking longer than expected. Please try again.",
            True,
        )
    if isinstance(exc, HTTPException):
        if exc.status_code == 401:
            return (401, "unauthorized", "Your session has expired. Please sign in again.", False)
        if exc.status_code == 403:
            return (403, "forbidden", "You do not have permission to perform this action.", False)
        return (
            exc.status_code,
            f"http_{exc.status_code}",
            str(exc.detail or "Unable to generate a response. Please try again."),
            exc.status_code in (429, 502, 503, 504),
        )
    return (
        500,
        "internal_error",
        "Unable to generate a response. Please try again.",
        True,
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

    def _is_real_session(self) -> bool:
        return isinstance(self.session, AsyncSession)

    async def _commit_if_supported(self, session: Optional[AsyncSession] = None) -> None:
        target = session or self.session
        commit_fn = getattr(target, "commit", None)
        if callable(commit_fn):
            await commit_fn()

    @asynccontextmanager
    async def _short_lived_session(
        self,
        company_id: Optional[uuid.UUID],
    ) -> AsyncGenerator[AsyncSession, None]:
        """Acquire a brief independent DB session for SSE persistence without holding pooled connections during LLM streaming."""
        if not self._is_real_session():
            yield self.session
            return

        tok = tenant_id_ctx.set(company_id)
        try:
            async with AsyncSessionLocal() as db:
                try:
                    yield db
                except Exception:
                    if db.is_active:
                        await db.rollback()
                    raise
        finally:
            tenant_id_ctx.reset(tok)

    async def _ensure_ollama_ready(self) -> bool:
        """Verify Ollama is reachable and a chat model is available (30s module cache)."""
        now = time.monotonic()
        if self._ollama_checked:
            return self._ollama_available
        if _OLLAMA_READY_CACHE["checked_at"] > 0 and (now - _OLLAMA_READY_CACHE["checked_at"]) < _OLLAMA_READY_TTL_SECONDS:
            self._ollama_checked = True
            self._ollama_available = bool(_OLLAMA_READY_CACHE["available"])
            return self._ollama_available

        self._ollama_checked = True
        try:
            health = await asyncio.wait_for(self.llm.check_health(), timeout=8.0)
            providers_map = health.get("providers") if isinstance(health, dict) else None
            ollama_health = (
                (providers_map.get("ollama") if isinstance(providers_map, dict) else None)
                or health.get("ollama")
                or {}
            )
            if ollama_health.get("healthy"):
                models = ollama_health.get("installed_models") or ollama_health.get("models") or []
                default_model = getattr(settings, "OLLAMA_DEFAULT_MODEL", None) or getattr(settings, "OLLAMA_MODEL", "llama3.2:3b")
                req_base = default_model.lower().split(":")[0]
                if (
                    ollama_health.get("model_available")
                    or any(default_model.lower() == m.lower() or req_base == m.lower().split(":")[0] for m in models)
                    or len(models) > 0
                ):
                    self._ollama_available = True
                    logger.info("Ollama health check passed: model='%s'", default_model)
                else:
                    logger.warning(
                        "Ollama reachable but model '%s' missing from installed models: %s",
                        default_model,
                        models,
                    )
            else:
                logger.warning("Ollama health check reported unhealthy: %s", ollama_health.get("error", "unavailable"))
        except asyncio.TimeoutError:
            logger.warning("Ollama health check timed out after 8s")
        except Exception as exc:
            logger.warning("Ollama health check error: %s", exc)

        _OLLAMA_READY_CACHE["checked_at"] = now
        _OLLAMA_READY_CACHE["available"] = self._ollama_available
        return self._ollama_available

    async def _find_messages_by_client_id(
        self,
        conv_uuid: uuid.UUID,
        client_message_id: str,
        session: Optional[AsyncSession] = None,
    ) -> tuple[Optional[AIMessage], Optional[AIMessage]]:
        """Locate existing user/assistant messages associated with a client_message_id."""
        db = session or self.session
        stmt = (
            select(AIMessage)
            .where(AIMessage.conversation_id == conv_uuid)
            .order_by(AIMessage.created_at.asc())
        )
        res = await db.execute(stmt)
        rows = res.scalars().all()
        user_msg: Optional[AIMessage] = None
        assistant_msg: Optional[AIMessage] = None
        for msg in rows:
            meta = getattr(msg, "message_metadata", None) or {}
            if isinstance(meta, dict) and meta.get("client_message_id") == client_message_id:
                if msg.role == "user":
                    user_msg = msg
                elif msg.role == "assistant":
                    assistant_msg = msg
        return user_msg, assistant_msg

    def _serialize_message(self, msg: AIMessage, conv_id: str) -> ChatMessageItem:
        meta = dict(getattr(msg, "message_metadata", None) or {})
        raw_charts = meta.get("charts") or []
        raw_tables = meta.get("tables") or []
        raw_sources = meta.get("sources") or []
        raw_suggestions = meta.get("suggestions") or []

        charts = [ChartData(**c) if isinstance(c, dict) else c for c in raw_charts]
        tables = [TableData(**t) if isinstance(t, dict) else t for t in raw_tables]
        sources = [SourceCitation(**s) if isinstance(s, dict) else s for s in raw_sources]

        ts_val = getattr(msg, "created_at", None)
        ts_iso = ts_val.isoformat() if hasattr(ts_val, "isoformat") else datetime.now(timezone.utc).isoformat()
        sender = "user" if msg.role == "user" else "ai"
        status_val = str(meta.get("status") or ("completed" if sender == "ai" else "accepted"))

        return ChatMessageItem(
            id=str(msg.id),
            conversationId=conv_id,
            role=msg.role,
            sender=sender,
            content=msg.message or "",
            timestamp=ts_iso,
            status=status_val,
            clientMessageId=meta.get("client_message_id"),
            sources=sources,
            charts=charts,
            tables=tables,
            suggestions=[str(s) for s in raw_suggestions],
            metadata=meta,
        )

    async def _prepare_chat_turn(
        self,
        request: ChatAssistantRequest,
        company_id: Optional[uuid.UUID],
        user_id: Optional[uuid.UUID],
        *,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """Shared preparation phase for both sync and streaming chat turns."""
        t_start = time.perf_counter()
        request_id = request.request_id or get_current_request_id() or str(uuid.uuid4())
        client_message_id = request.get_client_message_id() or str(uuid.uuid4())
        requested_conv_id = request.get_conversation_id()
        conv_id = requested_conv_id or str(uuid.uuid4())
        raw_text = request.get_message_text()
        if not raw_text:
            raise AppException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                code="EMPTY_MESSAGE",
                message="Please enter a message before sending.",
            )

        logger.info(
            "chat.request_received | request_id=%s | client_message_id=%s | company_id=%s | user_id=%s | chars=%d",
            request_id,
            client_message_id,
            company_id,
            user_id,
            len(raw_text),
        )

        # Idempotency check in bounded cache (scoped to tenant+user)
        now_mono = time.monotonic()
        _prune_idempotency_cache(now_mono)
        scope = _tenant_scope(company_id, user_id)
        idem_key = (*scope, client_message_id)
        if request.get_client_message_id() and idem_key in _IDEMPOTENCY_CACHE:
            cached = _IDEMPOTENCY_CACHE[idem_key]
            if (now_mono - cached.get("ts", 0.0)) < _IDEMPOTENCY_TTL_SECONDS and cached.get("response"):
                logger.info(
                    "chat.idempotent_hit | request_id=%s | client_message_id=%s | cache=memory",
                    request_id,
                    client_message_id,
                )
                return {"cached_response": cached["response"], "request_id": request_id, "client_message_id": client_message_id}

        conversation = await self._get_or_create_conversation(
            conv_id,
            company_id,
            user_id,
            raw_text,
            session=db,
        )
        conv_id = str(conversation.id)
        t_conv = (time.perf_counter() - t_start) * 1000
        logger.info(
            "chat.conversation_retrieved | request_id=%s | conversation_id=%s | duration_ms=%.1f",
            request_id,
            conv_id,
            t_conv,
        )

        existing_user_msg: Optional[AIMessage] = None
        existing_ai_msg: Optional[AIMessage] = None
        if request.get_client_message_id():
            existing_user_msg, existing_ai_msg = await self._find_messages_by_client_id(
                conversation.id,
                client_message_id,
                session=db,
            )
            if existing_ai_msg and (existing_ai_msg.message or "").strip():
                meta = getattr(existing_ai_msg, "message_metadata", None) or {}
                if meta.get("status", "completed") == "completed":
                    cached_resp = ChatAssistantResponse(
                        answer=existing_ai_msg.message,
                        confidence=float(meta.get("confidence", 0.9)),
                        sources=[SourceCitation(**s) for s in (meta.get("sources") or [])],
                        charts=[ChartData(**c) for c in (meta.get("charts") or [])],
                        tables=[TableData(**t) for t in (meta.get("tables") or [])],
                        followUpQuestions=list(meta.get("suggestions") or []),
                        follow_up_questions=list(meta.get("suggestions") or []),
                        conversationId=conv_id,
                        conversation_id=conv_id,
                        messageId=str(existing_ai_msg.id),
                        clientMessageId=client_message_id,
                        status="completed",
                        requestId=request_id,
                        model=meta.get("model"),
                        provider=meta.get("provider"),
                        ai_available=True,
                        degraded=False,
                    )
                    _IDEMPOTENCY_CACHE[idem_key] = {"ts": now_mono, "response": cached_resp}
                    logger.info(
                        "chat.idempotent_hit | request_id=%s | client_message_id=%s | cache=db",
                        request_id,
                        client_message_id,
                    )
                    return {"cached_response": cached_resp, "request_id": request_id, "client_message_id": client_message_id}

        is_greeting = _is_simple_conversational_message(raw_text)
        max_ctx = max(2, int(getattr(settings, "AI_MAX_CONTEXT_MESSAGES", 10) or 10))
        history_messages = await self._get_conversation_history(conv_id, limit=max_ctx, session=db)

        if is_greeting:
            metrics: dict[str, Any] = _normalize_metrics(None)
            enriched_context: dict[str, Any] = {}
            citations: list[SourceCitation] = []
            messages = [{"role": "system", "content": _COMPACT_GREETING_SYSTEM_PROMPT}]
            for msg in history_messages[-4:]:
                if msg.role in ("user", "assistant") and (msg.message or "").strip():
                    if existing_user_msg and msg.id == existing_user_msg.id:
                        continue
                    messages.append({"role": msg.role, "content": _trim_history_content(msg.message)})
            messages.append({"role": "user", "content": raw_text})
            num_predict = min(192, int(getattr(settings, "AI_CHAT_NUM_PREDICT", 512) or 512))
            temperature = 0.3
        else:
            raw_metrics = await self.repo.get_workforce_metrics(company_id=company_id)
            metrics = _normalize_metrics(raw_metrics)
            enriched_context = await self._build_enriched_context(
                query=raw_text,
                company_id=company_id,
                user_id=user_id,
                metrics=metrics,
                session=db,
            )
            citations_raw = (
                await self.repo.get_policy_citations(query=raw_text, company_id=company_id)
                if company_id
                else []
            )
            citations = [SourceCitation(**c) for c in citations_raw]
            context_text = self._build_context_text(metrics, enriched_context, citations)
            messages = [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "system", "content": context_text},
            ]
            for msg in history_messages:
                if msg.role != "system" and (msg.message or "").strip():
                    if existing_user_msg and msg.id == existing_user_msg.id:
                        continue
                    messages.append({"role": msg.role, "content": _trim_history_content(msg.message)})
            messages.append({"role": "user", "content": raw_text})
            base_num_predict = int(
                getattr(settings, "AI_CHAT_NUM_PREDICT", getattr(settings, "OLLAMA_NUM_PREDICT", 512)) or 512
            )
            q_lower = raw_text.lower()
            is_detailed_prompt = len(raw_text) > 140 or any(
                kw in q_lower
                for kw in ("detailed", "strategy", "comprehensive", "quarterly", "roadmap", "step-by-step", "full report")
            )
            num_predict = max(base_num_predict, 1024) if is_detailed_prompt else base_num_predict
            temperature = float(getattr(settings, "AI_CHAT_TEMPERATURE", 0.2) or 0.2)

        return {
            "cached_response": None,
            "t_start": t_start,
            "request_id": request_id,
            "client_message_id": client_message_id,
            "scope": scope,
            "idem_key": idem_key,
            "conv_id": conv_id,
            "conversation": conversation,
            "raw_text": raw_text,
            "is_greeting": is_greeting,
            "metrics": metrics,
            "enriched_context": enriched_context,
            "citations": citations,
            "messages": messages,
            "num_predict": num_predict,
            "temperature": temperature,
            "existing_user_msg": existing_user_msg,
            "existing_ai_msg": existing_ai_msg,
        }

    async def process_chat(
        self,
        request: ChatAssistantRequest,
        company_id: Optional[uuid.UUID] = None,
        user_id: Optional[uuid.UUID] = None,
    ) -> ChatAssistantResponse:
        """Process natural language user chat query with real DB data + LLM inference."""
        prep = await self._prepare_chat_turn(request, company_id, user_id, db=self.session)
        if prep["cached_response"] is not None:
            return prep["cached_response"]

        t_start = prep["t_start"]
        request_id = prep["request_id"]
        client_message_id = prep["client_message_id"]
        conv_id = prep["conv_id"]
        raw_text = prep["raw_text"]
        is_greeting = prep["is_greeting"]
        metrics = prep["metrics"]
        enriched_context = prep["enriched_context"]
        citations = prep["citations"]
        messages = prep["messages"]
        num_predict = prep["num_predict"]
        temperature = prep["temperature"]

        user_msg = prep["existing_user_msg"]
        if user_msg is None:
            user_msg = await self._save_message(
                conv_id,
                "user",
                raw_text,
                metadata={
                    "client_message_id": client_message_id,
                    "status": "accepted",
                    "request_id": request_id,
                },
                session=self.session,
            )

        llm_error: Exception | None = None
        degraded = False
        answer_markdown = ""
        ai_available = False
        status_state = "completed"
        chat_timeout = float(
            getattr(settings, "OLLAMA_CHAT_TIMEOUT_SECONDS", getattr(settings, "AI_CHAT_TIMEOUT_SECONDS", 120))
        )

        t_llm_start = time.perf_counter()
        logger.info(
            "chat.ai_provider_started | request_id=%s | client_message_id=%s | conversation_id=%s | greeting=%s | num_predict=%d",
            request_id,
            client_message_id,
            conv_id,
            is_greeting,
            num_predict,
        )

        try:
            await self._ensure_ollama_ready()
            answer_markdown = await asyncio.wait_for(
                self.llm.chat(
                    messages=messages,
                    temperature=temperature,
                    num_predict=num_predict,
                ),
                timeout=chat_timeout,
            )
            answer_markdown = (answer_markdown or "").strip()
            ai_available = bool(answer_markdown)
            if not answer_markdown:
                llm_error = RuntimeError("LLM returned empty response")
                degraded = True
                status_state = "failed"
        except asyncio.TimeoutError:
            logger.error(
                "chat.ai_timeout | request_id=%s | conversation_id=%s | timeout_s=%.1f",
                request_id,
                conv_id,
                chat_timeout,
            )
            llm_error = asyncio.TimeoutError(f"LLM request timed out after {chat_timeout}s")
            degraded = True
            status_state = "failed"
        except Exception as exc:
            logger.error(
                "chat.ai_error | request_id=%s | conversation_id=%s | error=%s",
                request_id,
                conv_id,
                exc,
            )
            llm_error = exc
            degraded = True
            status_state = "failed"

        t_llm_ms = (time.perf_counter() - t_llm_start) * 1000
        logger.info(
            "chat.ai_generation_completed | request_id=%s | conversation_id=%s | duration_ms=%.1f | degraded=%s",
            request_id,
            conv_id,
            t_llm_ms,
            degraded,
        )

        if llm_error and isinstance(llm_error, ProviderRequestError) and llm_error.status_code in (401, 403):
            if user_msg is not None:
                user_msg.message_metadata = {
                    **(getattr(user_msg, "message_metadata", None) or {}),
                    "status": "failed",
                    "error_code": "invalid_api_key",
                }
            await self._commit_if_supported(self.session)
            _, _, safe_msg, _ = _safe_error_payload(llm_error)
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=safe_msg)

        if llm_error:
            answer_markdown = self._build_degraded_response(metrics, enriched_context, llm_error)
            ai_available = False

        charts = [] if is_greeting else self._build_charts_from_metrics(metrics, raw_text.lower())
        tables = [] if is_greeting else self._build_tables_from_metrics(metrics, raw_text.lower())
        follow_ups = (
            await self._generate_follow_ups(raw_text, metrics)
            if (not llm_error and not is_greeting)
            else []
        )

        if user_msg is not None:
            user_msg.message_metadata = {
                **(getattr(user_msg, "message_metadata", None) or {}),
                "status": "completed" if not llm_error else "failed",
            }

        assistant_meta = {
            "charts": [c.model_dump() for c in charts],
            "tables": [t.model_dump() for t in tables],
            "sources": [c.model_dump() for c in citations],
            "suggestions": follow_ups,
            "client_message_id": client_message_id,
            "request_id": request_id,
            "status": status_state,
            "timing_ms": round((time.perf_counter() - t_start) * 1000, 1),
            "model": getattr(settings, "OLLAMA_DEFAULT_MODEL", getattr(settings, "OLLAMA_MODEL", "llama3.2:3b")),
            "provider": "ollama",
        }
        ai_msg = await self._save_message(
            conv_id,
            "assistant",
            answer_markdown,
            metadata=assistant_meta,
            session=self.session,
        )
        await self._commit_if_supported(self.session)

        t_total_ms = (time.perf_counter() - t_start) * 1000
        logger.info(
            "chat.response_delivered | request_id=%s | client_message_id=%s | conversation_id=%s | total_ms=%.1f",
            request_id,
            client_message_id,
            conv_id,
            t_total_ms,
        )

        data_fields_present = sum(
            1
            for v in (
                metrics.get("total_employees"),
                metrics.get("attrition_rate"),
                metrics.get("open_positions"),
                metrics.get("department_headcount"),
            )
            if v
        )
        confidence = min(0.95, 0.5 + (data_fields_present * 0.1) + (0.1 if answer_markdown else 0))
        if llm_error:
            confidence = max(0.1, confidence * 0.5)

        response = ChatAssistantResponse(
            answer=answer_markdown,
            confidence=round(confidence, 2),
            sources=citations,
            charts=charts,
            tables=tables,
            followUpQuestions=follow_ups,
            follow_up_questions=follow_ups,
            suggestions=follow_ups,
            conversationId=conv_id,
            conversation_id=conv_id,
            title=getattr(prep["conversation"], "title", None),
            messageId=str(ai_msg.id) if ai_msg else None,
            clientMessageId=client_message_id,
            status=status_state,
            requestId=request_id,
            timingMs=round(t_total_ms, 1),
            model=assistant_meta["model"],
            provider="ollama",
            ai_available=ai_available,
            degraded=degraded,
        )
        if not llm_error:
            _IDEMPOTENCY_CACHE[prep["idem_key"]] = {"ts": time.monotonic(), "response": response}
        return response

    async def process_chat_stream(
        self,
        request: ChatAssistantRequest,
        company_id: Optional[uuid.UUID] = None,
        user_id: Optional[uuid.UUID] = None,
        is_disconnected: Optional[Callable[[], Coroutine[Any, Any, bool]]] = None,
    ) -> AsyncGenerator[str, None]:
        """Stream real LLM chunks over SSE without blocking the event loop or holding DB connections."""
        t_start = time.perf_counter()
        scope = _tenant_scope(company_id, user_id)

        async with self._short_lived_session(company_id) as db:
            prep = await self._prepare_chat_turn(request, company_id, user_id, db=db)
            if prep["cached_response"] is not None:
                cached: ChatAssistantResponse = prep["cached_response"]
                yield _sse_event(
                    "status",
                    {
                        "type": "status",
                        "status": "completed",
                        "conversationId": cached.conversationId,
                        "clientMessageId": prep["client_message_id"],
                        "requestId": prep["request_id"],
                        "messageId": cached.messageId,
                    },
                )
                yield _sse_event("complete", cached.model_dump())
                return

            conv_id = prep["conv_id"]
            request_id = prep["request_id"]
            client_message_id = prep["client_message_id"]
            raw_text = prep["raw_text"]

            user_msg = prep["existing_user_msg"]
            if user_msg is None:
                user_msg = await self._save_message(
                    conv_id,
                    "user",
                    raw_text,
                    metadata={
                        "client_message_id": client_message_id,
                        "status": "accepted",
                        "request_id": request_id,
                    },
                    session=db,
                )
            await self._commit_if_supported(db)
            user_msg_id = str(user_msg.id) if user_msg else None

        active_key = (*scope, client_message_id)
        cancel_event = asyncio.Event()
        stream_record: dict[str, Any] = {
            "cancel_event": cancel_event,
            "conversation_id": conv_id,
            "client_message_id": client_message_id,
            "status": "accepted",
            "partial_content": "",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "error": None,
        }
        _ACTIVE_STREAMS[active_key] = stream_record

        is_greeting = prep["is_greeting"]
        metrics = prep["metrics"]
        citations = prep["citations"]
        messages = prep["messages"]
        num_predict = prep["num_predict"]
        temperature = prep["temperature"]

        charts = [] if is_greeting else self._build_charts_from_metrics(metrics, raw_text.lower())
        tables = [] if is_greeting else self._build_tables_from_metrics(metrics, raw_text.lower())
        follow_ups = (
            await self._generate_follow_ups(raw_text, metrics)
            if not is_greeting
            else []
        )

        yield _sse_event(
            "status",
            {
                "type": "status",
                "status": "accepted",
                "conversationId": conv_id,
                "clientMessageId": client_message_id,
                "requestId": request_id,
                "userMessageId": user_msg_id,
            },
        )

        overall_timeout = float(
            getattr(settings, "OLLAMA_CHAT_TIMEOUT_SECONDS", getattr(settings, "AI_CHAT_TIMEOUT_SECONDS", 120))
        )
        idle_timeout = min(45.0, overall_timeout)
        accumulated: list[str] = []
        used_model = getattr(settings, "OLLAMA_DEFAULT_MODEL", getattr(settings, "OLLAMA_MODEL", "llama3.2:3b"))
        used_provider = "ollama"
        final_status = "failed"
        error_payload: Optional[dict[str, Any]] = None
        first_chunk_logged = False
        prompt_tokens = 0
        completion_tokens = 0

        stream_gen = None
        try:
            await self._ensure_ollama_ready()
            stream_record["status"] = "generating"
            yield _sse_event(
                "status",
                {
                    "type": "status",
                    "status": "generating",
                    "conversationId": conv_id,
                    "clientMessageId": client_message_id,
                    "requestId": request_id,
                },
            )

            logger.info(
                "chat.ai_provider_started | request_id=%s | client_message_id=%s | conversation_id=%s | mode=stream",
                request_id,
                client_message_id,
                conv_id,
            )
            t_stream_start = time.perf_counter()
            stream_gen = self.llm.stream_chat_events(
                messages=messages,
                temperature=temperature,
                max_tokens=num_predict,
            )

            next_task: Optional[asyncio.Task] = None
            last_activity = time.monotonic()

            while True:
                if cancel_event.is_set() or (is_disconnected and await is_disconnected()):
                    final_status = "cancelled"
                    cancel_event.set()
                    break

                elapsed_total = time.monotonic() - last_activity
                if (time.perf_counter() - t_start) > overall_timeout:
                    raise TimeoutError("Stream overall timeout exceeded")
                if elapsed_total > idle_timeout:
                    raise TimeoutError("Stream idle timeout exceeded")

                if next_task is None:
                    next_task = asyncio.create_task(stream_gen.__anext__())

                wait_slice = min(_HEARTBEAT_INTERVAL_SECONDS, max(0.5, idle_timeout - elapsed_total))
                done_set, _ = await asyncio.wait({next_task}, timeout=wait_slice)

                if not done_set:
                    if cancel_event.is_set() or (is_disconnected and await is_disconnected()):
                        next_task.cancel()
                        final_status = "cancelled"
                        cancel_event.set()
                        break
                    yield _sse_event(
                        "heartbeat",
                        {
                            "type": "heartbeat",
                            "conversationId": conv_id,
                            "clientMessageId": client_message_id,
                            "ts": time.time(),
                        },
                    )
                    continue

                try:
                    event = next_task.result()
                except StopAsyncIteration:
                    next_task = None
                    final_status = "completed"
                    break
                finally:
                    next_task = None

                last_activity = time.monotonic()
                evt_type = event.get("type")

                if evt_type == "token":
                    token = event.get("content", "")
                    if not token:
                        continue
                    used_model = event.get("model") or used_model
                    used_provider = event.get("provider") or used_provider
                    if not first_chunk_logged:
                        first_chunk_logged = True
                        stream_record["status"] = "streaming"
                        logger.info(
                            "chat.first_chunk_received | request_id=%s | client_message_id=%s | ttft_ms=%.1f",
                            request_id,
                            client_message_id,
                            (time.perf_counter() - t_stream_start) * 1000,
                        )
                    accumulated.append(token)
                    current_text = "".join(accumulated)
                    stream_record["partial_content"] = current_text
                    stream_record["updated_at"] = datetime.now(timezone.utc).isoformat()

                    yield _sse_event(
                        "chunk",
                        {
                            "type": "chunk",
                            "delta": token,
                            "content": current_text,
                            "status": "streaming",
                            "conversationId": conv_id,
                            "clientMessageId": client_message_id,
                            "requestId": request_id,
                            "model": used_model,
                            "provider": used_provider,
                        },
                    )
                elif evt_type == "done":
                    used_model = event.get("model") or used_model
                    used_provider = event.get("provider") or used_provider
                    prompt_tokens = int(event.get("prompt_tokens") or 0)
                    completion_tokens = int(event.get("completion_tokens") or 0)
                    final_status = "completed"
                    break

            if final_status == "cancelled":
                partial_str = "".join(accumulated)
                stream_record["status"] = "cancelled"
                yield _sse_event(
                    "cancelled",
                    {
                        "type": "cancelled",
                        "status": "cancelled",
                        "partialContent": partial_str,
                        "conversationId": conv_id,
                        "clientMessageId": client_message_id,
                        "requestId": request_id,
                    },
                )
            else:
                full_text = "".join(accumulated).strip()
                if not full_text:
                    raise ProviderRequestError(
                        502,
                        "empty_response",
                        "Unable to generate a response. Please try again.",
                        retryable=True,
                        provider=used_provider,
                    )
                final_status = "completed"

        except asyncio.CancelledError:
            final_status = "cancelled"
            stream_record["status"] = "cancelled"
            logger.info("chat.stream_cancelled | request_id=%s | client_message_id=%s", request_id, client_message_id)
        except Exception as exc:
            status_code, err_code, safe_msg, retryable = _safe_error_payload(exc)
            partial_str = "".join(accumulated)
            final_status = "interrupted" if partial_str else "failed"
            stream_record["status"] = final_status
            stream_record["error"] = safe_msg
            error_payload = {
                "type": "error",
                "status": final_status,
                "statusCode": status_code,
                "code": err_code,
                "message": safe_msg,
                "retryable": retryable,
                "partialContent": partial_str,
                "conversationId": conv_id,
                "clientMessageId": client_message_id,
                "requestId": request_id,
            }
            logger.warning(
                "chat.stream_error | request_id=%s | client_message_id=%s | code=%s | partial_chars=%d",
                request_id,
                client_message_id,
                err_code,
                len(partial_str),
            )
            yield _sse_event("error", error_payload)
        finally:
            if stream_gen is not None:
                try:
                    await stream_gen.aclose()
                except Exception:
                    pass

            final_text = "".join(accumulated).strip()
            total_ms = round((time.perf_counter() - t_start) * 1000, 1)
            stream_record["status"] = final_status
            stream_record["partial_content"] = final_text
            stream_record["updated_at"] = datetime.now(timezone.utc).isoformat()

            saved_ai_id: Optional[str] = None
            try:
                async with self._short_lived_session(company_id) as persist_db:
                    u_msg, _ = await self._find_messages_by_client_id(
                        uuid.UUID(conv_id),
                        client_message_id,
                        session=persist_db,
                    )
                    if u_msg is not None:
                        u_msg.message_metadata = {
                            **(getattr(u_msg, "message_metadata", None) or {}),
                            "status": final_status,
                        }
                    if final_text:
                        assistant_meta = {
                            "charts": [c.model_dump() for c in charts],
                            "tables": [t.model_dump() for t in tables],
                            "sources": [c.model_dump() for c in citations],
                            "suggestions": follow_ups,
                            "client_message_id": client_message_id,
                            "request_id": request_id,
                            "status": final_status,
                            "is_partial": final_status in ("interrupted", "cancelled"),
                            "timing_ms": total_ms,
                            "model": used_model,
                            "provider": used_provider,
                            "prompt_tokens": prompt_tokens,
                            "completion_tokens": completion_tokens,
                        }
                        saved_msg = await self._save_message(
                            conv_id,
                            "assistant",
                            final_text,
                            metadata=assistant_meta,
                            session=persist_db,
                        )
                        if saved_msg:
                            saved_ai_id = str(saved_msg.id)
                    await self._commit_if_supported(persist_db)
            except Exception as persist_exc:
                logger.error(
                    "chat.stream_persist_failed | request_id=%s | conversation_id=%s | error=%s",
                    request_id,
                    conv_id,
                    persist_exc,
                )

            _ACTIVE_STREAMS.pop(active_key, None)

        if final_status == "completed" and error_payload is None:
            response_obj = ChatAssistantResponse(
                answer=final_text,
                confidence=0.92,
                sources=citations,
                charts=charts,
                tables=tables,
                followUpQuestions=follow_ups,
                follow_up_questions=follow_ups,
                suggestions=follow_ups,
                conversationId=conv_id,
                conversation_id=conv_id,
                title=getattr(prep["conversation"], "title", None),
                messageId=saved_ai_id,
                clientMessageId=client_message_id,
                status="completed",
                requestId=request_id,
                timingMs=total_ms,
                model=used_model,
                provider=used_provider,
                ai_available=True,
                degraded=False,
            )
            _IDEMPOTENCY_CACHE[prep["idem_key"]] = {"ts": time.monotonic(), "response": response_obj}
            logger.info(
                "chat.response_delivered | request_id=%s | client_message_id=%s | conversation_id=%s | total_ms=%.1f | chars=%d",
                request_id,
                client_message_id,
                conv_id,
                total_ms,
                len(final_text),
            )
            yield _sse_event("complete", response_obj.model_dump())

    async def get_message_status(
        self,
        conversation_id: str,
        client_message_id: str,
        company_id: Optional[uuid.UUID] = None,
        user_id: Optional[uuid.UUID] = None,
    ) -> MessageDeliveryStatusResponse:
        """Reconcile message delivery state across active stream, cache, and DB."""
        try:
            conv_uuid = uuid.UUID(conversation_id)
        except ValueError:
            raise NotFoundException(message=f"Conversation '{conversation_id}' not found.")

        stmt = select(AIConversation).where(AIConversation.id == conv_uuid)
        if company_id:
            stmt = stmt.where(AIConversation.company_id == company_id)
        if user_id:
            stmt = stmt.where(AIConversation.user_id == user_id)
        conv = (await self.session.execute(stmt)).scalar_one_or_none()
        if not conv:
            raise NotFoundException(message=f"Conversation '{conversation_id}' not found.")

        scope = _tenant_scope(company_id, user_id)
        active = _ACTIVE_STREAMS.get((*scope, client_message_id))
        if active and active.get("conversation_id") == str(conv.id):
            return MessageDeliveryStatusResponse(
                conversationId=str(conv.id),
                conversation_id=str(conv.id),
                clientMessageId=client_message_id,
                client_message_id=client_message_id,
                status=active["status"],
                found=True,
                partialContent=active.get("partial_content") or None,
                error=active.get("error"),
                updatedAt=active.get("updated_at"),
            )

        cached = _IDEMPOTENCY_CACHE.get((*scope, client_message_id))
        if cached and cached.get("response") and cached["response"].conversationId == str(conv.id):
            return MessageDeliveryStatusResponse(
                conversationId=str(conv.id),
                conversation_id=str(conv.id),
                clientMessageId=client_message_id,
                client_message_id=client_message_id,
                status="completed",
                found=True,
                response=cached["response"],
                updatedAt=datetime.now(timezone.utc).isoformat(),
            )

        user_msg, ai_msg = await self._find_messages_by_client_id(conv.id, client_message_id, session=self.session)
        if ai_msg:
            meta = getattr(ai_msg, "message_metadata", None) or {}
            status_val = str(meta.get("status") or "completed")
            msg_item = self._serialize_message(ai_msg, str(conv.id))
            resp_obj = None
            if status_val == "completed":
                resp_obj = ChatAssistantResponse(
                    answer=ai_msg.message,
                    confidence=0.9,
                    sources=msg_item.sources,
                    charts=msg_item.charts,
                    tables=msg_item.tables,
                    followUpQuestions=msg_item.suggestions,
                    follow_up_questions=msg_item.suggestions,
                    suggestions=msg_item.suggestions,
                    conversationId=str(conv.id),
                    conversation_id=str(conv.id),
                    messageId=str(ai_msg.id),
                    clientMessageId=client_message_id,
                    status=status_val,
                )
            return MessageDeliveryStatusResponse(
                conversationId=str(conv.id),
                conversation_id=str(conv.id),
                clientMessageId=client_message_id,
                client_message_id=client_message_id,
                status=status_val,
                found=True,
                message=msg_item,
                response=resp_obj,
                partialContent=ai_msg.message if status_val in ("interrupted", "cancelled") else None,
                updatedAt=msg_item.timestamp,
            )

        if user_msg:
            meta = getattr(user_msg, "message_metadata", None) or {}
            return MessageDeliveryStatusResponse(
                conversationId=str(conv.id),
                conversation_id=str(conv.id),
                clientMessageId=client_message_id,
                client_message_id=client_message_id,
                status=str(meta.get("status") or "accepted"),
                found=True,
                message=self._serialize_message(user_msg, str(conv.id)),
            )

        return MessageDeliveryStatusResponse(
            conversationId=str(conv.id),
            conversation_id=str(conv.id),
            clientMessageId=client_message_id,
            client_message_id=client_message_id,
            status="not_found",
            found=False,
        )

    async def cancel_message_generation(
        self,
        conversation_id: str,
        client_message_id: Optional[str] = None,
        company_id: Optional[uuid.UUID] = None,
        user_id: Optional[uuid.UUID] = None,
    ) -> Dict[str, Any]:
        """Cancel an in-flight streaming generation owned by the current user/tenant."""
        try:
            conv_uuid = uuid.UUID(conversation_id)
        except ValueError:
            raise NotFoundException(message=f"Conversation '{conversation_id}' not found.")

        stmt = select(AIConversation).where(AIConversation.id == conv_uuid)
        if company_id:
            stmt = stmt.where(AIConversation.company_id == company_id)
        if user_id:
            stmt = stmt.where(AIConversation.user_id == user_id)
        conv = (await self.session.execute(stmt)).scalar_one_or_none()
        if not conv:
            raise NotFoundException(message=f"Conversation '{conversation_id}' not found.")

        scope = _tenant_scope(company_id, user_id)
        cancelled_ids: list[str] = []
        for key, rec in list(_ACTIVE_STREAMS.items()):
            if key[0] != scope[0] or key[1] != scope[1]:
                continue
            if rec.get("conversation_id") != str(conv.id):
                continue
            if client_message_id and rec.get("client_message_id") != client_message_id:
                continue
            rec["cancel_event"].set()
            rec["status"] = "cancelled"
            cancelled_ids.append(rec["client_message_id"])

        return {
            "cancelled": len(cancelled_ids) > 0,
            "conversation_id": str(conv.id),
            "conversationId": str(conv.id),
            "cancelledMessageIds": cancelled_ids,
        }

    @staticmethod
    def _wants_department_visuals(query_lower: str) -> bool:
        """Return True when department breakdown charts/tables add direct value to the query."""
        q = (query_lower or "").lower()
        department_cues = (
            "overview",
            "headcount",
            "department",
            "distribution",
            "breakdown",
            "compare",
            "across",
            "workforce",
            "analytics",
            "dashboard",
        )
        return any(cue in q for cue in department_cues)

    def _build_charts_from_metrics(self, metrics: dict, query_lower: str) -> list[ChartData]:
        """Build charts dynamically from real database metrics when relevant to the prompt."""
        if not self._wants_department_visuals(query_lower):
            return []

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

    def _build_tables_from_metrics(self, metrics: dict, query_lower: str = "") -> list[TableData]:
        """Build tables dynamically from real database metrics when relevant to the prompt."""
        if query_lower and not self._wants_department_visuals(query_lower):
            return []

        tables = []
        dept_headcount = metrics.get("department_headcount", [])

        if dept_headcount:
            rows = [
                [d.get("department", "Unknown"), d.get("count", 0)]
                for d in dept_headcount[:10]
            ]
            if rows:
                tables.append(
                    TableData(
                        title="Workforce Distribution",
                        headers=["Department", "Headcount"],
                        rows=rows,
                    )
                )

        return tables

    async def _get_or_create_conversation(
        self,
        conv_id: str,
        company_id: Optional[uuid.UUID],
        user_id: Optional[uuid.UUID],
        first_message: str,
        session: Optional[AsyncSession] = None,
    ) -> AIConversation:
        """Get existing conversation or create new one in DB."""
        db = session or self.session
        try:
            conv_uuid = uuid.UUID(conv_id)
        except ValueError:
            conv_uuid = uuid.uuid4()

        stmt = select(AIConversation).where(AIConversation.id == conv_uuid)
        result = await db.execute(stmt)
        conversation = result.scalar_one_or_none()

        if conversation:
            if user_id and conversation.user_id != user_id:
                raise NotFoundException(message=f"Conversation '{conv_id}' not found.")
            if company_id and conversation.company_id != company_id:
                raise NotFoundException(message=f"Conversation '{conv_id}' not found.")
            conversation.updated_at = datetime.now(timezone.utc)
            if first_message and (conversation.title or "New Conversation") == "New Conversation":
                conversation.title = first_message[:80]
            return conversation

        title = first_message[:80] if first_message else "New Conversation"
        conversation = AIConversation(
            id=conv_uuid,
            user_id=user_id or uuid.uuid4(),
            company_id=company_id,
            title=title,
        )
        db.add(conversation)
        await db.flush()
        return conversation

    async def _get_conversation_history(
        self,
        conv_id: str,
        limit: int = 10,
        session: Optional[AsyncSession] = None,
    ) -> List[AIMessage]:
        """Get last N messages from conversation (excluding system messages)."""
        db = session or self.session
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
        result = await db.execute(stmt)
        return list(reversed(result.scalars().all()))

    async def _save_message(
        self,
        conv_id: str,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        session: Optional[AsyncSession] = None,
    ) -> Optional[AIMessage]:
        """Save a message to the conversation in DB using `message_metadata`."""
        db = session or self.session
        try:
            conv_uuid = uuid.UUID(conv_id)
        except ValueError:
            return None

        stmt = select(AIConversation).where(AIConversation.id == conv_uuid)
        result = await db.execute(stmt)
        conversation = result.scalar_one_or_none()
        if not conversation:
            return None

        message = AIMessage(
            conversation_id=conv_uuid,
            role=role,
            message=content,
            message_metadata=metadata or {},
        )
        db.add(message)
        await db.flush()
        return message

    async def _build_enriched_context(
        self,
        query: str,
        company_id: Optional[uuid.UUID],
        user_id: Optional[uuid.UUID],
        metrics: Dict[str, Any],
        session: Optional[AsyncSession] = None,
    ) -> Dict[str, Any]:
        """Build enriched context based on query topic and user role."""
        db = session or self.session
        enriched: dict[str, Any] = {}
        if not company_id:
            return enriched

        query_lower = query.lower()

        user_role = "employee"
        emp_obj = None
        if user_id:
            from app.models.employee import Employee
            from app.models.user import User

            stmt = select(Employee).where(Employee.user_id == user_id)
            result = await db.execute(stmt)
            emp_obj = result.scalar_one_or_none()
            if emp_obj and emp_obj.role:
                user_role = emp_obj.role.lower()

            if user_role == "employee":
                try:
                    u_stmt = select(User.role).where(User.id == user_id).execution_options(bypass_tenant=True)
                    u_role = (await db.execute(u_stmt)).scalar_one_or_none()
                    if u_role:
                        role_val = u_role.value if hasattr(u_role, "value") else str(u_role)
                        if role_val:
                            user_role = role_val.lower()
                except Exception:
                    pass

        is_hr_admin = user_role in ("hr_admin", "super_admin", "admin", "manager", "executive", "ceo", "chro")

        if "leave" in query_lower or "holiday" in query_lower or "pto" in query_lower:
            if is_hr_admin or user_id:
                try:
                    from app.services.leave_service import LeaveService

                    leave_service = LeaveService(db)
                    emp_id = emp_obj.id if emp_obj else None
                    if emp_id:
                        balances = await leave_service.get_leave_balances(employee_id=emp_id)
                        enriched["leave_balances"] = [
                            {
                                "type": b.leave_type,
                                "total": b.total_days,
                                "used": b.used_days,
                                "remaining": b.remaining_days,
                            }
                            for b in balances
                        ]
                        from app.models.leave import LeaveRequest

                        pending_stmt = select(func.count(LeaveRequest.id)).where(
                            LeaveRequest.employee_id == emp_id,
                            LeaveRequest.status == "PENDING",
                        )
                        pending_res = await db.execute(pending_stmt)
                        enriched["pending_leave_requests"] = pending_res.scalar() or 0
                except Exception as exc:
                    logger.debug("Failed to fetch leave context: %s", exc)

        if "attendance" in query_lower or "present" in query_lower or "absent" in query_lower or "late" in query_lower:
            try:
                from app.services.ai_attendance_service import AIAttendanceService

                attendance_service = AIAttendanceService(db)
                dept_id = None
                if not is_hr_admin and emp_obj:
                    dept_id = getattr(emp_obj, "department_id", None)

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

        if is_hr_admin and (
            "payroll" in query_lower or "salary" in query_lower or "compensation" in query_lower or "payslip" in query_lower
        ):
            try:
                from app.models.payroll import PayCycle
                from app.services.payroll_service import PayrollService

                payroll_service = PayrollService(db)
                stmt = (
                    select(PayCycle)
                    .where(PayCycle.company_id == company_id)
                    .order_by(desc(PayCycle.period_year), desc(PayCycle.period_month))
                    .limit(1)
                )
                result = await db.execute(stmt)
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

        return enriched

    def _build_context_text(
        self,
        metrics: Dict[str, Any],
        enriched: Dict[str, Any],
        citations: List[SourceCitation],
    ) -> str:
        """Build the full context text for the LLM."""
        safe_m = _normalize_metrics(metrics)
        dept_info = ""
        dept_headcount = safe_m.get("department_headcount", [])
        if dept_headcount:
            dept_lines = [f"  - {d.get('department', 'Unknown')}: {d.get('count', 0)} employees" for d in dept_headcount[:10]]
            dept_info = "\n".join(dept_lines)

        context_parts = [
            "Real-time Workforce Data:",
            f"- Total Active Employees: {safe_m['total_employees']}",
            f"- Attrition Rate: {safe_m['attrition_rate']}%",
            f"- Open Job Positions: {safe_m['open_positions']}",
            f"- New Hires (This Month): {safe_m['new_hires_month']}",
        ]
        if dept_info:
            context_parts.append(f"- Department Distribution:\n{dept_info}")
        open_jobs = safe_m.get("open_jobs", [])
        if open_jobs:
            job_lines = [
                f"  - {j.get('title', 'Role')} (Department: {j.get('department', 'General')}, Vacancies: {j.get('vacancies', 1)})"
                for j in open_jobs[:15]
            ]
            context_parts.append("- Active Open Job Postings:\n" + "\n".join(job_lines))

        if "leave_balances" in enriched:
            context_parts.append("\nLeave Balances:")
            for lb in enriched["leave_balances"]:
                context_parts.append(
                    f"  - {lb['type']}: {lb['remaining']}/{lb['total']} days remaining (used: {lb['used']})"
                )
        if "pending_leave_requests" in enriched:
            context_parts.append(f"- Pending Leave Requests: {enriched['pending_leave_requests']}")

        if "attendance_summary" in enriched:
            att = enriched["attendance_summary"]
            context_parts.append("\nAttendance Summary:")
            context_parts.append(f"  - Health Score: {att.get('health_score', 0)}/100")
            context_parts.append(f"  - Attendance Rate: {att.get('attendance_rate', 0)}%")
            context_parts.append(f"  - Late Arrivals: {att.get('late_arrivals', 0)}")
            context_parts.append(f"  - Anomalies: {att.get('anomalies', 0)}")
            context_parts.append(f"  - Overtime Hours: {att.get('overtime_hours', 0)}")

        if "payroll_summary" in enriched:
            pay = enriched["payroll_summary"]
            context_parts.append("\nPayroll Summary (Latest Cycle):")
            context_parts.append(f"  - Period: {pay.get('period', 'N/A')}")
            context_parts.append(f"  - Status: {pay.get('status', 'N/A')}")
            context_parts.append(f"  - Employees Paid: {pay.get('headcount', 0)}")
            context_parts.append(f"  - Total Gross: ₹{(pay.get('total_gross') or 0):,.2f}")
            context_parts.append(f"  - Total Net: ₹{(pay.get('total_net') or 0):,.2f}")
            context_parts.append(f"  - Total Deductions: ₹{(pay.get('total_deductions') or 0):,.2f}")

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
        safe_m = _normalize_metrics(metrics)
        lines = [
            "# Workforce Snapshot (AI Service Unavailable)",
            "",
            f"> ⚠️ The AI service is currently unavailable ({type(error).__name__}). Showing basic data snapshot.",
            "",
            "## Core Metrics",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| **Total Active Employees** | {safe_m['total_employees']} |",
            f"| **Attrition Rate** | {safe_m['attrition_rate']}% |",
            f"| **Open Positions** | {safe_m['open_positions']} |",
            f"| **New Hires (This Month)** | {safe_m['new_hires_month']} |",
        ]

        dept_headcount = safe_m.get("department_headcount", [])
        if dept_headcount:
            lines.extend(["", "## Department Distribution", "", "| Department | Headcount |", "|------------|-----------|"])
            for d in dept_headcount[:10]:
                lines.append(f"| {d.get('department', 'Unknown')} | {d.get('count', 0)} |")

        if "leave_balances" in enriched:
            lines.extend(["", "## Leave Balances", "", "| Leave Type | Total | Used | Remaining |", "|------------|-------|------|-----------|"])
            for lb in enriched["leave_balances"]:
                lines.append(f"| {lb['type']} | {lb['total']} | {lb['used']} | {lb['remaining']} |")

        if "attendance_summary" in enriched:
            att = enriched["attendance_summary"]
            lines.extend([
                "",
                "## Attendance Summary",
                "",
                f"- Health Score: {att.get('health_score', 0)}/100",
                f"- Attendance Rate: {att.get('attendance_rate', 0)}%",
                f"- Late Arrivals: {att.get('late_arrivals', 0)}",
                f"- Anomalies: {att.get('anomalies', 0)}",
            ])

        if "payroll_summary" in enriched:
            pay = enriched["payroll_summary"]
            lines.extend([
                "",
                "## Payroll Summary (Latest Cycle)",
                "",
                f"- Period: {pay.get('period', 'N/A')}",
                f"- Status: {pay.get('status', 'N/A')}",
                f"- Headcount: {pay.get('headcount', 0)}",
                f"- Total Gross: ₹{(pay.get('total_gross') or 0):,.2f}",
                f"- Total Net: ₹{(pay.get('total_net') or 0):,.2f}",
            ])

        lines.extend(["", "> Please try your query again in a moment for detailed AI analysis."])
        return "\n".join(lines)

    async def _generate_follow_ups(self, query: str, metrics: dict) -> list[str]:
        """Generate contextual follow-up questions from DB metrics (None-safe, no extra LLM call)."""
        safe_m = _normalize_metrics(metrics)
        total_emp = safe_m["total_employees"]
        open_pos = safe_m["open_positions"]
        attrition = safe_m["attrition_rate"]
        dept_headcount = safe_m["department_headcount"]

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
        self,
        request: ChatAssistantRequest,
        company_id: Optional[uuid.UUID] = None,
        user_id: Optional[uuid.UUID] = None,
    ) -> ChatAssistantResponse:
        """Process structured query endpoint."""
        return await self.process_chat(request=request, company_id=company_id, user_id=user_id)

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
        stmt = select(AIConversation).order_by(desc(AIConversation.updated_at)).limit(50)
        if company_id:
            stmt = stmt.where(AIConversation.company_id == company_id)
        if user_id:
            stmt = stmt.where(AIConversation.user_id == user_id)

        result = await self.session.execute(stmt)
        conversations = result.scalars().all()
        if not conversations:
            return ChatHistoryResponse(total_conversations=0, history=[])

        hist: list[ConversationHistoryItem] = []

        if self._is_real_session():
            conv_ids = [c.id for c in conversations]
            counts_res = await self.session.execute(
                select(AIMessage.conversation_id, func.count(AIMessage.id))
                .where(AIMessage.conversation_id.in_(conv_ids))
                .group_by(AIMessage.conversation_id)
            )
            count_map = {row[0]: int(row[1] or 0) for row in counts_res.all()}

            latest_res = await self.session.execute(
                select(AIMessage)
                .where(AIMessage.conversation_id.in_(conv_ids))
                .order_by(AIMessage.conversation_id, desc(AIMessage.created_at))
                .distinct(AIMessage.conversation_id)
            )
            latest_map = {msg.conversation_id: msg.message for msg in latest_res.scalars().all()}

            for conv in conversations:
                hist.append(
                    ConversationHistoryItem(
                        conversation_id=str(conv.id),
                        title=conv.title,
                        last_message=latest_map.get(conv.id, ""),
                        message_count=count_map.get(conv.id, 0),
                        updated_at=conv.updated_at,
                    )
                )
        else:
            for conv in conversations:
                last_msg_stmt = (
                    select(AIMessage)
                    .where(AIMessage.conversation_id == conv.id)
                    .order_by(desc(AIMessage.created_at))
                    .limit(1)
                )
                last_msg = (await self.session.execute(last_msg_stmt)).scalar_one_or_none()
                msg_count_stmt = select(func.count(AIMessage.id)).where(AIMessage.conversation_id == conv.id)
                msg_count = (await self.session.execute(msg_count_stmt)).scalar() or 0
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
        """Fetch full ordered conversation history with tenant AND user isolation."""
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

        msg_stmt = (
            select(AIMessage)
            .where(AIMessage.conversation_id == conv_uuid)
            .order_by(AIMessage.created_at.asc())
        )
        messages = (await self.session.execute(msg_stmt)).scalars().all()
        serialized = [self._serialize_message(m, str(conv_uuid)) for m in messages]

        last_ai = next((m for m in reversed(serialized) if m.role == "assistant"), None)
        last_any = serialized[-1] if serialized else None
        primary = last_ai or last_any

        return ChatAssistantResponse(
            answer=primary.content if primary else "",
            confidence=0.9 if primary else 1.0,
            sources=primary.sources if primary else [],
            charts=primary.charts if primary else [],
            tables=primary.tables if primary else [],
            followUpQuestions=primary.suggestions if primary else [],
            follow_up_questions=primary.suggestions if primary else [],
            suggestions=primary.suggestions if primary else [],
            conversationId=str(conv_uuid),
            conversation_id=str(conv_uuid),
            title=conversation.title,
            messages=serialized,
            clientMessageId=primary.clientMessageId if primary else None,
            status=primary.status if primary else "completed",
        )

    async def delete_history(
        self,
        conversation_id: str,
        company_id: Optional[uuid.UUID] = None,
        user_id: Optional[uuid.UUID] = None,
    ) -> Dict[str, Any]:
        """Delete specific chat conversation with company AND user isolation."""
        from sqlalchemy import delete

        try:
            conv_uuid = uuid.UUID(conversation_id)
        except ValueError:
            raise NotFoundException(message=f"Conversation '{conversation_id}' not found.")

        stmt = select(AIConversation).where(AIConversation.id == conv_uuid)
        if company_id:
            stmt = stmt.where(AIConversation.company_id == company_id)
        if user_id:
            stmt = stmt.where(AIConversation.user_id == user_id)

        conversation = (await self.session.execute(stmt)).scalar_one_or_none()
        if not conversation:
            raise NotFoundException(message=f"Conversation '{conversation_id}' not found.")

        await self.session.execute(delete(AIMessage).where(AIMessage.conversation_id == conv_uuid))
        await self.session.execute(delete(AIConversation).where(AIConversation.id == conv_uuid))
        await self._commit_if_supported(self.session)

        return {
            "deleted": True,
            "conversation_id": conversation_id,
            "conversationId": conversation_id,
        }

    async def get_suggestions(
        self, company_id: Optional[uuid.UUID] = None
    ) -> ChatSuggestionsResponse:
        """Fetch fast contextual HR suggestions without blocking on LLM inference."""
        cache_key = str(company_id or "global")
        now = time.monotonic()
        cached = _SUGGESTIONS_CACHE.get(cache_key)
        if cached and (now - cached[0]) < _SUGGESTIONS_TTL_SECONDS:
            return cached[1]

        emp_count = 0
        open_pos = 0
        dept_count = 0
        try:
            metrics = _normalize_metrics(await self.repo.get_workforce_metrics(company_id=company_id))
            emp_count = metrics["total_employees"]
            open_pos = metrics["open_positions"]
            dept_count = len(metrics["department_headcount"])
        except Exception as exc:
            logger.debug("Suggestions metrics lookup skipped: %s", exc)

        suggested = [
            f"Show workforce overview for {emp_count} active employees" if emp_count > 0 else "Show current workforce overview",
            f"Break down employee distribution across {dept_count} departments" if dept_count > 0 else "Analyze employee distribution by department",
            f"Review {open_pos} currently open positions" if open_pos > 0 else "What are the open positions?",
            "Show recent hiring and attrition trends",
        ]
        result = ChatSuggestionsResponse(
            suggested_prompts=suggested,
            popular_queries=[
                "Generate attendance summary",
                "Show payroll overview",
                "List active job openings",
            ],
            role_based_prompts=[
                "Show my team's workload",
                "Review pending leave approvals",
            ],
        )
        _SUGGESTIONS_CACHE[cache_key] = (now, result)
        return result

    async def save_feedback(
        self, payload: ChatFeedbackRequest
    ) -> Dict[str, Any]:
        """Save feedback for chat response inside message_metadata when message_id is provided."""
        logger.info("Chat feedback received: conversation=%s rating=%s", payload.conversation_id, payload.rating)
        try:
            if payload.message_id:
                msg_uuid = uuid.UUID(payload.message_id)
                stmt = select(AIMessage).where(AIMessage.id == msg_uuid)
                msg = (await self.session.execute(stmt)).scalar_one_or_none()
                if msg is not None:
                    meta = dict(getattr(msg, "message_metadata", None) or {})
                    meta["feedback_rating"] = payload.rating
                    if payload.feedback:
                        meta["feedback_text"] = payload.feedback
                    msg.message_metadata = meta
                    await self._commit_if_supported(self.session)
        except Exception as exc:
            logger.debug("Feedback metadata persistence skipped: %s", exc)
        return {"success": True, "conversation_id": payload.conversation_id, "rating": payload.rating}
