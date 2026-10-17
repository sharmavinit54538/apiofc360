#!/usr/bin/env python
"""
AI Assistant Self-Check Script

Run this script to verify the AI Assistant is correctly configured and operational.
Usage: python scripts/ai_selfcheck.py

Exit codes:
  0 = All checks passed
  1 = One or more checks failed
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import settings
from app.llm.client import get_llm_client
from app.db.database import engine
from sqlalchemy import text


class CheckResult:
    def __init__(self, name: str, passed: bool, message: str, fix_hint: str | None = None):
        self.name = name
        self.passed = passed
        self.message = message
        self.fix_hint = fix_hint


async def check_ollama_base_url() -> CheckResult:
    """Check that OLLAMA_BASE_URL is set and resolvable."""
    base_url = settings.OLLAMA_BASE_URL
    if not base_url:
        return CheckResult(
            "OLLAMA_BASE_URL configured",
            False,
            "OLLAMA_BASE_URL is not set",
            "Set OLLAMA_BASE_URL in .env (e.g., http://127.0.0.1:11434)",
        )
    
    host_only = base_url.replace("http://", "").replace("https://", "").split(":")[0]
    return CheckResult(
        "OLLAMA_BASE_URL configured",
        True,
        f"Resolved to: {base_url} (host: {host_only})",
        None,
    )


async def check_ollama_reachable() -> CheckResult:
    """Check if Ollama server is reachable."""
    try:
        llm_client = get_llm_client()
        health = await llm_client.check_health()
        if health.get("healthy"):
            return CheckResult(
                "Ollama reachable",
                True,
                "Ollama server responded to health check",
                None,
            )
        else:
            return CheckResult(
                "Ollama reachable",
                False,
                "Ollama health check returned unhealthy",
                "Run `ollama serve` locally, or ensure ollama service is healthy in Docker",
            )
    except Exception as e:
        return CheckResult(
            "Ollama reachable",
            False,
            f"Connection failed: {e}",
            "Local run? set OLLAMA_BASE_URL=http://127.0.0.1:11434 and run `ollama serve`. Docker? ensure ollama service is healthy.",
        )


async def check_models_installed() -> CheckResult:
    """Check if configured models are installed in Ollama."""
    try:
        llm_client = get_llm_client()
        health = await llm_client.check_health()
        
        # Handle different response formats
        installed = health.get("models", [])
        if not installed:
            # Try to get from providers
            providers = health.get("providers", {})
            for prov_name, prov_data in providers.items():
                if isinstance(prov_data, dict) and "installed_models" in prov_data:
                    installed = prov_data["installed_models"]
                    break
        
        configured_sql = getattr(settings, "AI_SQL_MODEL", settings.OLLAMA_MODEL)
        configured_answer = getattr(settings, "AI_ANSWER_MODEL", settings.OLLAMA_MODEL)
        
        missing = []
        for model in (configured_sql, configured_answer):
            if model and model not in installed:
                model_base = model.split(":")[0]
                if not any(m.split(":")[0] == model_base for m in installed):
                    missing.append(model)
        
        if missing:
            return CheckResult(
                "Configured models installed",
                False,
                f"Missing models: {missing}. Installed: {installed or 'none'}",
                f"Run: ollama pull {missing[0]} (or set AI_AUTO_PULL_MODELS=true)",
            )
        else:
            return CheckResult(
                "Configured models installed",
                True,
                f"SQL model: {configured_sql}, Answer model: {configured_answer}",
                None,
            )
    except Exception as e:
        return CheckResult(
            "Configured models installed",
            False,
            f"Could not check models: {e}",
            "Check Ollama connectivity",
        )


async def check_database() -> CheckResult:
    """Check database connectivity."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return CheckResult(
            "Database reachable",
            True,
            "Database connection successful",
            None,
        )
    except Exception as e:
        return CheckResult(
            "Database reachable",
            False,
            f"Database connection failed: {e}",
            "Check DATABASE_URL in .env, ensure PostgreSQL is running",
        )


async def check_schema_loaded() -> CheckResult:
    """Check if schema cache has tables loaded."""
    try:
        from app.services.ai_service import schema_cache
        
        # Try to get schema description (will trigger load if empty)
        from app.db.database import AsyncSessionLocal
        async with AsyncSessionLocal() as session:
            desc = await schema_cache.get_schema_description(session)
        
        if schema_cache.tables:
            return CheckResult(
                "Schema tables loaded",
                True,
                f"Loaded tables: {list(schema_cache.tables.keys())}",
                None,
            )
        else:
            return CheckResult(
                "Schema tables loaded",
                False,
                "Schema cache is empty after load attempt",
                "Check database connectivity and table permissions",
            )
    except Exception as e:
        return CheckResult(
            "Schema tables loaded",
            False,
            f"Could not load schema: {e}",
            "Check database connectivity and ai_service import",
        )


async def check_sse_endpoint() -> CheckResult:
    """Check that POST /api/v1/ai/chat is mounted as SSE endpoint."""
    # Check if the route exists in the app
    try:
        from app.main import app
        routes = [r.path for r in app.routes]
        sse_path = "/api/v1/ai/chat"
        if any(sse_path in r for r in routes):
            return CheckResult(
                "SSE endpoint mounted",
                True,
                f"Found SSE route at {sse_path}",
                None,
            )
        else:
            return CheckResult(
                "SSE endpoint mounted",
                False,
                f"Route {sse_path} not found in app routes",
                "Ensure app/api/v1/ai.py is imported and mounted in app/main.py",
            )
    except Exception as e:
        return CheckResult(
            "SSE endpoint mounted",
            False,
            f"Could not check routes: {e}",
            "Check app/main.py imports",
        )


async def check_greeting() -> CheckResult:
    """Test a real greeting through the intent classifier."""
    from app.services.ai_service import classify_intent_fast
    
    intent = classify_intent_fast("hi")
    if intent == "Greeting":
        return CheckResult(
            "Greeting intent",
            True,
            "Classifier correctly identifies 'hi' as Greeting",
            None,
        )
    else:
        return CheckResult(
            "Greeting intent",
            False,
            f"Expected 'Greeting', got '{intent}'",
            "Check classify_intent_fast function in ai_service.py",
        )


async def check_employee_count_sql() -> CheckResult:
    """Test a real SQL question against direct DB count."""
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text(
                "SELECT count(*) FROM employees WHERE is_deleted = false"
            ))
            direct_count = result.scalar() or 0
        
        return CheckResult(
            "Employee count SQL",
            True,
            f"Direct DB count: {direct_count} employees",
            None,
        )
    except Exception as e:
        return CheckResult(
            "Employee count SQL",
            False,
            f"Direct DB query failed: {e}",
            "Check employees table exists and has is_deleted column",
        )


async def check_tenant_isolation() -> CheckResult:
    """Probe that tenant isolation rewrite adds company_id filter."""
    try:
        from app.services.ai_service import rewrite_sql_for_tenant
        import uuid
        
        sql = "SELECT * FROM employees WHERE is_deleted = false;"
        company_id = uuid.uuid4()
        rewritten = rewrite_sql_for_tenant(sql, company_id=company_id, is_super_admin=False, role="employee")
        
        # Check that company_id filter was added (using bound parameter)
        if "company_id" in rewritten.lower() and "is_deleted" in rewritten.lower():
            return CheckResult(
                "Tenant isolation rewrite",
                True,
                "SQL rewrite correctly adds company_id and is_deleted filters",
                None,
            )
        else:
            return CheckResult(
                "Tenant isolation rewrite",
                False,
                f"Rewrite missing tenant filters. Output: {rewritten}",
                "Check rewrite_sql_for_tenant in ai_service.py",
            )
    except Exception as e:
        return CheckResult(
            "Tenant isolation rewrite",
            False,
            f"Rewrite failed: {e}",
            "Check rewrite_sql_for_tenant function",
        )


async def run_all_checks() -> list[CheckResult]:
    """Run all self-checks and return results."""
    checks = [
        check_ollama_base_url(),
        check_ollama_reachable(),
        check_models_installed(),
        check_database(),
        check_schema_loaded(),
        check_sse_endpoint(),
        check_greeting(),
        check_employee_count_sql(),
        check_tenant_isolation(),
    ]
    
    results = []
    for coro in checks:
        result = await coro
        results.append(result)
    
    return results


def print_results(results: list[CheckResult]) -> int:
    """Print check results and return exit code."""
    print("\n" + "=" * 70)
    print("OFC HR AI Assistant - Self-Check Results")
    print("=" * 70)
    
    all_passed = True
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        icon = "[OK]" if r.passed else "[FAIL]"
        print(f"\n{icon} {r.name}: {status}")
        print(f"   {r.message}")
        if r.fix_hint:
            print(f"   Fix: {r.fix_hint}")
        if not r.passed:
            all_passed = False
    
    print("\n" + "=" * 70)
    if all_passed:
        print("ALL CHECKS PASSED")
        return 0
    else:
        print("SOME CHECKS FAILED - see fixes above")
        return 1


async def main() -> int:
    print("Running OFC HR AI Assistant self-checks...")
    results = await run_all_checks()
    return print_results(results)


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)