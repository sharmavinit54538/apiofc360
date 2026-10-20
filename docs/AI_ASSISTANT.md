# OFC HR AI Assistant — Architecture & Operations Guide

## Overview

The **OFC HR AI** (formerly "Aurix AI") is the primary conversational AI assistant for the OFC HR platform. It provides a natural-language interface to query live HR data (employees, attendance, leave, payroll, departments, jobs) using a secure, read-only SQL generation pipeline backed by a local Ollama LLM.

> **Assistant Name**: "OFC HR AI" — used in all greetings, help text, who-are-you responses, fallbacks, and prompts.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            REQUEST FLOW                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Client (SSE)                                                               │
│       │                                                                      │
│       ▼                                                                      │
│  POST /api/v1/ai/chat (authenticated)                                       │
│       │                                                                      │
│       ▼                                                                      │
│  AIService.send_message_stream()                                            │
│       │                                                                      │
│       ├── classify_intent_fast() ──▶ Greeting/Help/Goodbye → Instant reply │
│       │                                                                      │
│       └── Database Query Intent                                             │
│               │                                                              │
│               ▼                                                              │
│         Load Dynamic Schema (DBSchemaCache, 10-min TTL)                     │
│               │                                                              │
│               ▼                                                              │
│         ┌─────────────────────────────────────────────┐                     │
│         │  SQL Generation / Repair Loop (max 3)       │                     │
│         │  1. Build prompt with schema + few-shots    │                     │
│         │  2. Call Ollama (AI_SQL_MODEL)              │                     │
│         │  3. Validate with sqlglot (PostgreSQL)      │                     │
│         │  4. Rewrite for tenant isolation (AST)      │                     │
│         │  5. Execute in READ ONLY txn + timeout      │                     │
│         │  6. On failure: retry with error context    │                     │
│         └─────────────────────────────────────────────┘                     │
│               │                                                              │
│               ▼                                                              │
│         Format results with Ollama (AI_ANSWER_MODEL)                        │
│               │                                                              │
│               ▼                                                              │
│         Stream SSE events: meta → token* → done                              │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Key Components

### 1. AIService (`app/services/ai_service.py`)

Central orchestration service with:

- **Intent Classification**: `classify_intent_fast()` — word-boundary + Hinglish support
- **Schema Cache**: `DBSchemaCache` — dynamic DB schema with 10-min TTL, ALLOWED_TABLES whitelist
- **SQL Validation**: `validate_sql_query()` — sqlglot (PostgreSQL dialect)
- **Tenant Isolation**: `rewrite_sql_for_tenant()` — AST rewrite with bound `company_id`
- **Shared SQL Loop**: `_execute_sql_loop()` — used by both sync and streaming paths

### 2. Ollama Provider (`app/llm/providers/ollama_provider.py`)

- Health check via `GET /api/tags`
- Model validation with exact/base-name match only
- Auto-pull **only** when `AI_AUTO_PULL_MODELS=true`
- Clear error if model missing: `ollama pull <model>`

### 3. LLM Client (`app/llm/client/__init__.py`)

- `complete()` raises `LLMUnavailableError` on empty response
- Distinct error codes for: unreachable, model missing, timeout, invalid SQL, DB error, no data

### 4. API Endpoints (`app/api/v1/ai.py`)

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/api/v1/ai/chat` | POST | User | SSE streaming chat |
| `/api/v1/ai/health` | GET | Admin/Super-Admin | Ollama + DB + model status |
| `/api/v1/ai/history` | GET | User | Conversation list |
| `/api/v1/ai/history/{id}` | GET | User | Conversation detail |
| `/api/v1/ai/suggestions` | GET | User | Dynamic prompt suggestions |

### 5. Chat Assistant API (`app/api/v1/chat_assistant.py`)

JSON (non-streaming) endpoints at non-conflicting paths:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/ai/chat/message` | POST | Send message |
| `/api/v1/ai/chat/query` | POST | Process query |
| `/api/v1/ai/chat/conversations` | POST/GET | Manage conversations |
| `/api/v1/ai/chat/report` | POST | Generate HR reports |
| `/api/v1/ai/chat/analytics` | POST | Workforce analytics |

---

## Environment Variables

### Required (`.env`)

```bash
# Ollama connection
OLLAMA_BASE_URL=http://127.0.0.1:11434    # LOCAL default
# OLLAMA_BASE_URL=http://ollama:11434      # DOCKER (set by docker-compose.yml)

# Model selection (all from settings, nothing hard-coded)
AI_SQL_MODEL=qwen3:30b          # SQL generation
AI_ANSWER_MODEL=qwen3:30b       # Answer formatting
AI_CHAT_TIMEOUT_SECONDS=120     # Full chat turn timeout
AI_SQL_TIMEOUT_SECONDS=30       # SQL execution timeout
AI_AUTO_PULL_MODELS=false       # Set true to enable auto-pull
AI_DB_READONLY_URL=""           # Optional: dedicated read-only DB connection
```

### Model Recommendations

| Model | RAM/VRAM | Use Case |
|-------|----------|----------|
| `qwen3:4b` / `llama3.2:3b` | ~4-6 GB | Local dev, fast iteration |
| `qwen3:14b` | ~10 GB | Balanced quality/speed |
| `qwen3:30b` | ~18+ GB | Production quality (default) |

> ⚠️ **qwen3:30b needs ~18 GB+ RAM/VRAM**. Use smaller models for local development.

---

## Local vs Docker Setup

### Local Development

```bash
# 1. Start Ollama
ollama serve

# 2. Pull model (once)
ollama pull qwen3:4b

# 3. Set env (or use .env defaults)
export OLLAMA_BASE_URL=http://127.0.0.1:11434

# 4. Run FastAPI
uvicorn app.main:app --reload
```

### Docker Compose

```yaml
# docker-compose.yml (already configured)
services:
  ollama:
    image: ollama/ollama:latest
    ports:
      - "127.0.0.1:11434:11434"
    volumes:
      - ollama_data:/root/.ollama
  
  api:
    environment:
      - OLLAMA_BASE_URL=http://ollama:11434  # Set by compose, not .env
    depends_on:
      ollama:
        condition: service_healthy
```

> **Key Point**: Docker sets its own `OLLAMA_BASE_URL` via `environment:`. The developer's `.env` is NOT used for the container's Ollama URL.

---

## First Thing to Check: `/api/v1/ai/health`

**Always check this endpoint first when troubleshooting.**

```bash
curl -H "Authorization: Bearer <admin_token>" \
  http://localhost:8000/api/v1/ai/health
```

Response:
```json
{
  "success": true,
  "data": {
    "ollama_reachable": true,
    "base_url": "127.0.0.1:11434",
    "installed_models": ["qwen3:30b", "nomic-embed-text"],
    "configured_models": {"sql": "qwen3:30b", "answer": "qwen3:30b"},
    "models_missing": [],
    "db_ok": true,
    "schema_tables_loaded": true,
    "last_error": null
  }
}
```

---

## Troubleshooting Table

| Symptom | Check `/api/v1/ai/health` | Likely Fix |
|---------|---------------------------|------------|
| Assistant says "AI service temporarily unavailable" | `ollama_reachable: false` | Start Ollama: `ollama serve` |
| "Model not available" error | `models_missing: ["qwen3:30b"]` | `ollama pull qwen3:30b` |
| Request times out | `ollama_reachable: true` but slow | Increase `AI_CHAT_TIMEOUT_SECONDS`; use smaller model |
| "Couldn't execute query" | `db_ok: true`, `schema_tables_loaded: true` | Check prompt/few-shots; verify ALLOWED_TABLES |
| "Column X does not exist" | `schema_tables_loaded: false` | Wait for schema cache refresh (10 min) or restart |
| Empty/garbled responses | `last_error` shows LLM error | Check Ollama logs; verify model loaded |
| 403 on `/ai/health` | N/A | Requires `role: hr_admin` or `super_admin` |

---

## Self-Check Script

Run anytime to verify configuration:

```bash
python scripts/ai_selfcheck.py
```

Output example:
```
======================================================================
OFC HR AI Assistant - Self-Check Results
======================================================================

✅ OLLAMA_BASE_URL configured: PASS
   Resolved to: http://127.0.0.1:11434 (host: 127.0.0.1)

✅ Ollama reachable: PASS
   Ollama server responded to health check

✅ Configured models installed: PASS
   SQL model: qwen3:4b, Answer model: qwen3:4b

✅ Database reachable: PASS
   Database connection successful

✅ Schema tables loaded: PASS
   Loaded tables: ['employees', 'departments', 'jobs', ...]

✅ SSE endpoint mounted: PASS
   Found SSE route at /api/v1/ai/chat

✅ Greeting intent: PASS
   Classifier correctly identifies 'hi' as Greeting

✅ Employee count SQL: PASS
   Direct DB count: 42 employees

✅ Tenant isolation rewrite: PASS
   SQL rewrite correctly adds company_id and is_deleted filters

======================================================================
🎉 ALL CHECKS PASSED
```

Exit code: `0` on success, `1` on any failure.

---

## Security Model

### Tenant Isolation (Code, Not Prompt)

1. SQL is validated against ALLOWED_TABLES whitelist
2. AST rewrite injects `company_id = :company_id` + `is_deleted = false`
3. `company_id` passed as **bound parameter**, never formatted into SQL
4. Super-admin bypasses tenant filter (explicit opt-in)
5. `LIMIT 100` enforced in code
6. Read-only transaction + `SET LOCAL statement_timeout`

### Role-Based Column Visibility

- **Salary/CTC columns**: Restricted to HR/Admin roles
- **PII (Aadhaar, PAN, bank account)**: Blocklisted in all responses
- **Internal IDs (company_id, user_id, tokens)**: Stripped from results

### No Secrets in Responses

- User-facing errors contain **no SQL, schema, URLs, or stack traces**
- Server logs include `request_id` for correlation
- SSE `error` events include only `error_code` + generic message

---

## Changing Models

```bash
# 1. Pull new model
ollama pull llama3.1:8b

# 2. Update .env
AI_SQL_MODEL=llama3.1:8b
AI_ANSWER_MODEL=llama3.1:8b

# 3. Restart API (or SIGHUP if using process manager)
docker compose restart api
```

> No code changes required — all model names come from settings.

---

## Extending ALLOWED_TABLES

To add a new table to the assistant's knowledge:

1. Add entry to `ALLOWED_TABLES` in `app/services/ai_service.py`:
```python
"new_table": {
    "columns": ["id", "col1", "col2", ...],
    "blocklist": {"sensitive_col"},
    "has_company_id": True,
    "has_is_deleted": True,
    "few_shots": [
        {"q": "Natural language question", "sql": "SELECT ..."}
    ],
},
```

2. Add few-shot examples covering common query patterns
3. Run tests: `pytest tests/test_ai_assistant_core.py -v`

---

## Common Issues & Fixes

### "Ollama not reachable" on Startup

```
AI Preflight: Ollama not reachable at http://127.0.0.1:11434.
Local run? set OLLAMA_BASE_URL=http://127.0.0.1:11434 and run `ollama serve`.
```

**Fix**: Start Ollama service: `ollama serve` (or `systemctl start ollama`)

### "Model X not installed"

```
AI Preflight: Models missing: ['qwen3:30b']. Run: ollama pull qwen3:30b
```

**Fix**: `ollama pull qwen3:30b` (or set `AI_AUTO_PULL_MODELS=true`)

### Schema Cache Not Loading

If `schema_tables_loaded: false`:
- Check DB connectivity
- Verify tables exist in `public` schema
- Restart API to force cache refresh

### Slow Responses with Large Models

Increase timeouts in `.env`:
```bash
AI_CHAT_TIMEOUT_SECONDS=180
AI_SQL_TIMEOUT_SECONDS=60
```
Or switch to smaller model: `AI_ANSWER_MODEL=qwen3:4b`

---

## File Reference

| File | Purpose |
|------|---------|
| `app/services/ai_service.py` | Core assistant logic (schema, validator, tenant rewrite, SQL loop) |
| `app/api/v1/ai.py` | SSE streaming endpoint + health check |
| `app/api/v1/chat_assistant.py` | JSON chat endpoints (non-streaming) |
| `app/llm/providers/ollama_provider.py` | Ollama health, model validation, auto-pull |
| `app/llm/client/__init__.py` | LLMClient with LLMUnavailableError |
| `app/core/config.py` | All AI_* settings |
| `app/core/exceptions.py` | LLMUnavailableError definition |
| `scripts/ai_selfcheck.py` | Self-check script |
| `tests/test_ai_assistant_core.py` | Unit tests (validator, rewrite, classifier) |
| `tests/test_production_assistant.py` | Integration tests (requires Ollama) |

---

## Version History

| Version | Changes |
|---------|---------|
| 2.0.0 | Permanent fix: config-driven models, sqlglot validator, tenant isolation in code, distinct errors, preflight health, SSE streaming mounted, "OFC HR AI" name |
| 1.x | Legacy: hardcoded models, regex validator, prompt-based tenant filter, "Aurix AI" name |

---

*Generated as part of the OFC HR AI permanent fix (2026).*