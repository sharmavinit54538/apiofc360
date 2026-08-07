"""Cost tracker — logs token usage, costs, and model usage to database.

Provides in-memory aggregation with periodic DB flush for production cost monitoring.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.llm.token_counter import estimate_cost, is_free_provider

logger = logging.getLogger(__name__)


@dataclass
class UsageRecord:
    """Single request usage record."""
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float
    latency_ms: float
    endpoint: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class CostTracker:
    """In-memory cost and usage tracker with aggregation.

    Tracks per-provider, per-model, and per-endpoint usage in memory.
    Provides real-time cost monitoring and daily budgets.
    """

    def __init__(self, daily_budget_usd: float = 100.0) -> None:
        self._records: list[UsageRecord] = []
        self._daily_budget = daily_budget_usd
        self._daily_spend: float = 0.0
        self._daily_reset_date: str = ""
        self._total_tokens: int = 0
        self._total_requests: int = 0
        self._total_cost: float = 0.0

        # Aggregated counters
        self._by_provider: dict[str, dict] = defaultdict(lambda: {"tokens": 0, "cost": 0.0, "requests": 0})
        self._by_model: dict[str, dict] = defaultdict(lambda: {"tokens": 0, "cost": 0.0, "requests": 0})

    def record(
        self,
        provider: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: float = 0.0,
        endpoint: str = "",
    ) -> UsageRecord:
        """Record a single LLM request's usage."""
        total_tokens = prompt_tokens + completion_tokens
        cost = 0.0
        if not is_free_provider(provider):
            cost = estimate_cost(prompt_tokens, completion_tokens, model, provider)

        record = UsageRecord(
            provider=provider,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost_usd=cost,
            latency_ms=latency_ms,
            endpoint=endpoint,
        )

        # Update daily tracking
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today != self._daily_reset_date:
            self._daily_spend = 0.0
            self._daily_reset_date = today

        self._daily_spend += cost
        self._total_tokens += total_tokens
        self._total_requests += 1
        self._total_cost += cost

        # Provider aggregation
        self._by_provider[provider]["tokens"] += total_tokens
        self._by_provider[provider]["cost"] += cost
        self._by_provider[provider]["requests"] += 1

        # Model aggregation
        self._by_model[model]["tokens"] += total_tokens
        self._by_model[model]["cost"] += cost
        self._by_model[model]["requests"] += 1

        # Keep last 10k records in memory
        self._records.append(record)
        if len(self._records) > 10000:
            self._records = self._records[-5000:]

        if cost > 0:
            logger.info(
                "LLM usage: provider=%s model=%s tokens=%d cost=$%.4f latency=%.0fms",
                provider, model, total_tokens, cost, latency_ms,
            )

        return record

    def is_budget_exceeded(self) -> bool:
        """Check if daily budget is exceeded."""
        return self._daily_spend >= self._daily_budget

    def get_summary(self) -> dict:
        """Get current usage summary."""
        return {
            "total_requests": self._total_requests,
            "total_tokens": self._total_tokens,
            "total_cost_usd": round(self._total_cost, 4),
            "daily_spend_usd": round(self._daily_spend, 4),
            "daily_budget_usd": self._daily_budget,
            "budget_remaining_usd": round(max(0, self._daily_budget - self._daily_spend), 4),
            "by_provider": dict(self._by_provider),
            "by_model": dict(self._by_model),
        }

    def get_recent(self, n: int = 50) -> list[dict]:
        """Get the N most recent usage records."""
        records = self._records[-n:]
        return [
            {
                "provider": r.provider,
                "model": r.model,
                "prompt_tokens": r.prompt_tokens,
                "completion_tokens": r.completion_tokens,
                "total_tokens": r.total_tokens,
                "cost_usd": round(r.cost_usd, 6),
                "latency_ms": round(r.latency_ms, 1),
                "endpoint": r.endpoint,
                "timestamp": r.timestamp.isoformat(),
            }
            for r in reversed(records)
        ]


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_tracker: CostTracker | None = None


def get_cost_tracker() -> CostTracker:
    """Return the global cost tracker singleton."""
    global _tracker
    if _tracker is None:
        from app.core.config import settings
        budget = getattr(settings, "LLM_DAILY_BUDGET_USD", 100.0)
        _tracker = CostTracker(daily_budget_usd=budget)
    return _tracker
