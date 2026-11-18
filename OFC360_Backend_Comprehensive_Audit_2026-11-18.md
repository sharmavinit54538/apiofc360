# OFC360 Backend — Technical Security & Architecture Audit

**Audited artifact:** `apiofc360-dev.zip`  |  **Date:** 2026-11-18  |  **Method:** Offline archive extraction and full Python AST/token inspection; targeted code tracing; historical pytest XML parsing. No database services, credentials, deployment infrastructure or network were provided, so no live integration tests, Alembic upgrades or runtime exploitation were performed.

## Scope & findings methodology

- 1,090 Python files AST parsed, 0 syntax parse failures; 2,013 route decorator occurrences across 225 files (not deduplicated mounted URLs); 40 revision files; 107 Python files matching `test_*.py`.

- 1 comment TODO/FIXME/HACK/XXX tags; 24 syntactically empty / abstract-like functions or methods (some legitimate abstract interfaces); 6 potential static module import cycles. Lists in appendices are pattern inventories, not individually proven bugs.

- **Confirmed code defect** = directly contradictory code. **Likely runtime** = unsafe pattern that requires dependencies and DB for verification. **Historical evidence** = behavior captured in archived verification artifacts, possibly stale. Missing source tests and dynamic side effects are not assessed as passed.

## 1. Project overview & architecture health

**Stack:** FastAPI, Uvicorn, Pydantic v2, SQLAlchemy async + asyncpg PostgreSQL, Alembic, Redis, Celery, JWT/passlib, OCR, Ollama/LLM, Razorpay, S3/cloud providers. **Architecture:** modular monolith with API/router → service → repository/model, plus parallel legacy school-specific router and dependency set.

**Top-level source layout:** `app/api`, `app/services`, `app/repositories`, `app/models`, `app/schemas`, `app/db`, `app/middleware`, `app/workers`, `app/attendance`, `app/agents`, `alembic/versions`, `tests`, `verification` and deployment/config files.

**Architecture defects:** two database engines/session makers, conflicting school/HRMS user models and auth dependencies, startup `metadata.create_all`/schema healing alongside Alembic, mutable global event-loop background tasks, oversized modules. No specific runtime circular import was proven; see static-cycle appendix for review targets.

## 2. Critical bugs & runtime issues

### P0-01 — Unauthenticated diagnostics endpoint reflects credentials (CONFIRMED)

**Location:** `app/main.py:746–763`

**Evidence:** The diagnostic JSON includes `request_headers: dict(request.headers)` without an authentication dependency; permitted frontend origins could read cookies via the response even when cookies are HttpOnly.

**Correction:** Remove the route in production or lock to platform operator with strict authentication; never return Authorization/Cookie headers.

```python
746:     @app.get("/api/v1/cors-debug", tags=["CORS Diagnostics"], include_in_schema=False)
747:     async def cors_debug(request: Request):
748:         """Diagnostic endpoint for verifying CORS configuration in production.
749:         
750:         Returns the active CORS origins list and request headers.
751:         Only accessible from allowed origins (CORS enforced).
752:         """
753:         origin = request.headers.get("origin", "(no origin header)")
```

### P0-02 — Public static mount exposes helpdesk attachments (CONFIRMED)

**Location:** `app/main.py:765–783`, `app/services/helpdesk_service.py:423–441`

**Evidence:** Files uploaded as tenant-scoped helpdesk attachments are written under the same `/uploads/helpdesk` directory served without application authorization.

**Correction:** Move attachments to private storage with tenant+record-scoped, authenticated download and expiration; audit existing public URLs.

### P0-03 — Autopilot v2 dependency graph does not authenticate requests correctly (CONFIRMED CODE MISMATCH)
**Location:** `app/api/v2/autopilot.py:53–67`, `app/api/v2/enterprise_dependencies.py:13–26`
**Evidence:** 28 endpoint handlers inject `Depends(company_id)` where `company_id(claims: dict)` lacks a JWT Claims dependency; the handler then invokes that function on its UUID return, causing request/body mismatch and likely 4xx/5xx.
**Correction:** Use `Claims = Annotated[dict, Depends(get_current_user_claims)]` for the handler parameter and call `company_id(claims)` in the handler; add tenant, user and RBAC tests for all 28 endpoints.
```python
53: @router.get(
54:     "/settings",
55:     status_code=status.HTTP_200_OK,
56:     response_model=APIResponse[AutopilotSettingsResponse],
57:     summary="Get autopilot HR automation settings",
58: )
59: async def get_autopilot_settings(
60:     claims: Annotated[dict, Depends(_tenant_id)],
```
### P0-04 — Alternate school-auth path refers to fields absent from HRMS User (CONFIRMED CODE MISMATCH)
**Location:** `app/db/dependencies.py:60–92`, `app/models/user/mixins/columns.py:16–25`, `app/models/user/mixins/system.py:18–46`
**Evidence:** School-auth dependency reads User.tenant_id, User.status and User.school_id but actual User model exposes company_id, account_status/is_active and no school_id. Mounted school routes will break after JWT verification.
**Correction:** Decouple/remove unrelated school routes from the HRMS application, or implement an explicit school-specific principal and independently tested auth model.
### P0-05 — Startup candidate auto-screening does not tenant-scope email lookup or new candidate (CONFIRMED)
**Location:** `app/main.py:74–122`, `app/models/recruitment.py:326–342`
**Evidence:** Processes all applications globally, matches candidate using email alone, creates Candidate without company_id, and inserts a fabricated phone number `0000000000`.
**Correction:** Move screening to tenant-scoped jobs, require candidate company_id, match on company_id+email, prohibit fake phone values and backfill prior null-owned records carefully.
```python
74:     async with AsyncSessionLocal() as session:
75:         try:
76:             # Query all applications with jobs and candidates eager loaded
77:             stmt = select(Application).options(
78:                 selectinload(Application.job),
79:                 selectinload(Application.candidate)
80:             )
81:             apps_res = await session.execute(stmt)
```
### P0-06 — Security session listing creates fake real database records (CONFIRMED)
**Location:** `app/services/security_setting_service.py:140–166`
**Evidence:** A read method inserts two fictitious active UserSession records if no sessions exist, creating misleading security/audit data.
**Correction:** Remove seeding; return an empty list and record only real authenticated sessions, with company/user scope.
### P0-07 — Bootstrap reactivates previously disabled super-admin account (CONFIRMED)
**Location:** `app/main.py:248–266`
**Evidence:** At each startup, existing official super-admin is forced active, verified and undeleted; this can reverse incident-response deactivation.
**Correction:** Provision only once in an explicitly authorized bootstrap migration; never auto-reactivate existing accounts; use audited break-glass recovery.
```python
248:             # 2. Provision or verify the single authorized Super Admin identity
249:             sa_res = await session.execute(
250:                 select(User).where(User.email == super_admin_email).execution_options(bypass_tenant=True)
251:             )
252:             sa_user = sa_res.scalars().first()
253: 
254:             if sa_user:
255:                 # Only reset password if explicitly requested via env var
```
### P0-08 — Legacy face recognition uses image hash, not biometric matching (CONFIRMED LEGACY ROUTE)
**Location:** `app/services/face_service.py:17–37`, `app/api/v1/face.py:76–102`
**Evidence:** `_extract_embedding` turns SHA256 bytes into an arbitrary vector; the legacy school face endpoint may accept incorrect identity matches. This is distinct from separate HR attendance biometric implementation.
**Correction:** Remove/disable this legacy route unless replaced by real liveness-detecting biometric pipeline, tenant-bound with consent and strict verification.
### P1-06 — Analytics CSV export labels hex as Base64; invalid SQL CASE construction (CONFIRMED CODE DEFECT)
**Location:** `app/api/v1/hr_ops_analytics.py:328–355`
**Evidence:** `func.case` is used in aggregation instead of SQLAlchemy `case`, and `csv_content.encode().hex()` is labeled `content_base64`.
**Correction:** Use `sqlalchemy.case` and `base64.b64encode(csv_content.encode()).decode('ascii')`; regression-test output decoding and SQL execution.
```python
328:     if "attendance" in metric_list:
329:         att_stmt = select(
330:             Employee.department,
331:             func.count(AttendanceRecord.id).label("total"),
332:             func.sum(func.case((AttendanceRecord.status == "PRESENT", 1), else_=0)).label("present"),
333:         ).where(
334:             AttendanceRecord.company_id == company_id,
335:             AttendanceRecord.record_date >= date_from,
```
### P1-07 — In-process schema healing mixes synchronous inspector with async engine (CONFIRMED UNSAFE PATTERN)
**Location:** `app/db/database.py:264–329`, `app/main.py:175–185`
**Evidence:** `inspect(engine.sync_engine)` occurs outside an `AsyncConnection.run_sync` callback and schema mutation occurs on startup alongside Alembic migrations.
**Correction:** Run Alembic upgrades as a separate release step and remove schema self-healing from application startup; fail readiness on migration mismatch.
```python
264: async def heal_database_schema(engine: AsyncEngine) -> None:
265:     """Idempotent startup schema-healing utility.
266:     
267:     Runs Base.metadata.create_all() and uses ALTER TABLE ... ADD COLUMN IF NOT EXISTS
268:     for any missing columns in AI chat tables and related tables.
269:     """
270:     from sqlalchemy import text, inspect
271:     from app.db.base import Base
```
### P1-08 — Two independent session/engine lifecycles (CONFIRMED)
**Location:** `app/db/session.py:1–14`, `app/db/database.py:150–168`
**Evidence:** Legacy school endpoints use a second engine and sessionmaker that bypass the main session’s behavior and instrumentation.
**Correction:** Consolidate sessions and exclude school/legacy code paths where not required.
### P1-10 — Legacy school face upload references undefined configuration settings (CONFIRMED CODE MISMATCH)
**Location:** `app/api/v1/face.py:23–31`, `app/api/v1/face.py:97–103`
**Evidence:** Code refers to `settings.MAX_UPLOAD_SIZE_MB` and `settings.FACE_RECOGNITION_THRESHOLD`, neither declared in app/core/config.py. At least the oversized-image and recognition paths can crash.
**Correction:** Remove school routes from HRMS or define/validate named settings and add route regression tests.
### P1-11 — Historical full regression suites are failing (HISTORICAL EVIDENCE)
**Location:** `tests/test_auth_employee_login_lifecycle.py:1–10`, `tests/test_ai_face_attendance.py:1–10`
**Evidence:** 15 Nov reports show 104 failures in one 1153-test run and 202 failures/7 errors in 1182-test rerun. Some are environmental connection refusal; others show NameError, contract mismatch and 404/500.
**Correction:** Run full suite in isolated disposable PostgreSQL/Redis services; triage production bugs separately from stale test expectations and infrastructure failures.
### P2-04 — Application may start serving even if PostgreSQL is down (CONFIRMED)
**Location:** `app/main.py:164–201`, `app/main.py:292–320`, `app/main.py:397–401`
**Evidence:** DB initialisation failure logs degraded mode but lifespan yields and serves routes; `/health` responds HTTP 200 even on DB disconnect.
**Correction:** Make readiness fail until DB/migrations are ready; use separate liveness vs readiness and meaningful process admission gating.
## 3. Incomplete features & pending work
### P0-06 — Security session listing creates fake real database records (CONFIRMED)
**Location:** `app/services/security_setting_service.py:140–166`
**Evidence:** A read method inserts two fictitious active UserSession records if no sessions exist, creating misleading security/audit data.
**Correction:** Remove seeding; return an empty list and record only real authenticated sessions, with company/user scope.
### P0-08 — Legacy face recognition uses image hash, not biometric matching (CONFIRMED LEGACY ROUTE)
**Location:** `app/services/face_service.py:17–37`, `app/api/v1/face.py:76–102`
**Evidence:** `_extract_embedding` turns SHA256 bytes into an arbitrary vector; the legacy school face endpoint may accept incorrect identity matches. This is distinct from separate HR attendance biometric implementation.
**Correction:** Remove/disable this legacy route unless replaced by real liveness-detecting biometric pipeline, tenant-bound with consent and strict verification.
### P1-01 — Automation endpoints return static rules, logs, jobs and fake mutation success (CONFIRMED)
**Location:** `app/api/global_notifications.py:72–86`, `app/api/global_notifications.py:266–309`, `app/api/global_notifications.py:348–403`
**Evidence:** Rules creation and toggle do not persist; logs and schedules use fixed demo records; retry reports queued in a mock environment without actual action.
**Correction:** Replace with company-scoped tables, state transitions, Celery jobs and genuine task records; do not return success when nothing was done.
### P1-02 — Autopilot onboarding retries and payroll status are stubs (CONFIRMED)
**Location:** `app/services/autopilot_service.py:630–666`
**Evidence:** `list_onboarding_runs` always empty, `get_onboarding_run` returns not_found data, `retry_onboarding_step` says retried=True without invoking worker, payroll status returns idle.
**Correction:** Implement persisted run/step tables with actual worker dispatch and idempotency, or return explicit 501 until built.
### P1-03 — Autopilot agent chat is deterministic placeholder, not LLM (CONFIRMED)
**Location:** `app/services/autopilot_service.py:343–362`
**Evidence:** The comment says placeholder for LLM, but endpoint responds with rule-based keywords and invented confidence.
**Correction:** Call configured LLM with structured, verified action proposals; never execute unreviewed actions; preserve human approval.
### P1-04 — Document generator reports success without creating a document (CONFIRMED)
**Location:** `app/api/v1/hr_ops_analytics.py:374–424`
**Evidence:** It creates a random UUID and returns a download URL without generating or persisting a document.
**Correction:** Use real document generation/vault service, persist metadata and file, and test download only after successful write.
### P1-05 — Policy search returns hard-coded fake documents (CONFIRMED)
**Location:** `app/api/v1/hr_ops_analytics.py:533–568`
**Evidence:** Search operates on a literal two-document fabricated list and returns success as if searching tenant policies.
**Correction:** Query company-authorized policy documents or RAG index and return empty/no-results when unavailable.
**Note on markers:** multiple strings "mock", "placeholder" refer to legitimate parameter substitution or test support; not all are defects. Appendix A includes all literal TODO/FIXME/HACK/XXX comment tags; Appendix B covers actual one-statement stubs; other curated mock paths above were validated manually.
## 4. Security & performance vulnerabilities
### P2-01 — Tenant enforcement applies to ORM SELECT, not all write paths (CONFIRMED ARCHITECTURAL LIMITATION)
**Location:** `app/db/database.py:233–257`, `app/db/base.py:49–55`
**Evidence:** Tenant `with_loader_criteria` interception returns immediately for non-SELECT; new objects with explicit wrong company_id are not rejected, and some tenant columns are nullable.
**Correction:** Explicit tenant conditions for writes/reads and PostgreSQL RLS where appropriate; add cross-tenant test matrix for update/delete/bulk/upsert/raw SQL.
### P2-02 — Rate limit trusts unvalidated X-Forwarded-For and general limiter fails open (CONFIRMED)
**Location:** `app/core/rate_limiter.py:168–180`, `app/core/rate_limiter.py:197–239`
**Evidence:** Client-selected XFF can change identity unless proxy strips it; when Redis unavailable general limits allow requests.
**Correction:** Trust forwarding headers only from known proxies and enforce strict limits on sensitive endpoints; test Redis outage behavior.
### P2-03 — Production CORS includes dev origins and exception handlers admit LAN-origin regex (CONFIRMED)
**Location:** `app/main.py:491–525`, `app/main.py:799–830`
**Evidence:** DEV_CORS_ORIGINS is always appended and manual CORS error headers use local-network regex without checking environment.
**Correction:** Separate environment allowlists; rely on one CORS middleware and avoid reflective origin handling in custom exception handlers.
### P2-05 — Auth tenant context set without explicit reset (CONFIRMED CODE PATTERN)
**Location:** `app/middleware/auth.py:214–226`
**Evidence:** ContextVar set after claims validation without token-based reset in a request-scoped finalizer. Tasks started with copied context can retain tenant context, depending on scheduling.
**Correction:** Use `token = tenant_id_ctx.set(...)` and reset in ASGI middleware finally, then test concurrent isolated requests/background tasks.
### P2-06 — Oversized service/controller files hinder maintainability (CONFIRMED)
**Location:** `app/services/recruitment_service.py:1–20`, `app/api/super_admin.py:1–20`
**Evidence:** The largest services/controllers run to thousands of lines; widespread router/service coupling makes targeted changes difficult.
**Correction:** Refactor by domain operations with APIs and tests unchanged; avoid an arbitrary 50-line module maximum for cohesive functions or schema declarations.
**DB risk areas:** app/main.py:74-153 globally loads applications then per-row email lookups and commits (N+1, write churn, concurrency); app/db/database.py:233-257 SELECT-only tenant criteria; app/analytics/analytics_service.py:34-55 optional company filters; target with EXPLAIN ANALYZE and index inspection against a disposable PostgreSQL clone, not assumption-based index claims.
**Positive security controls found:** `app/core/config.py:471–516` validates production secrets and DB/Redis requirements; `app/main.py:567–585` installs security headers/CORS; `app/core/rate_limiter.py` implements Redis Lua limits; `app/middleware/auth.py:139–188` checks token type and Redis revocation; `app/api/v2/employee_bulk_api.py:24–44` limits upload length; `app/models/recruitment.py:326–333` defines candidate tenant-email index. Controls exist but have material gaps described above.
## 5. Prioritized action plan / ownership-neutral handoff
Use P0 as deployment blockers until patched and tested; P1 before claiming modules complete; P2 as follow-on hardening.
### P0 — Critical fixes
- [ ] **P0-01** `app/main.py:746` — **Unauthenticated diagnostics endpoint reflects credentials.** Remove the route in production or lock to platform operator with strict authentication; never return Authorization/Cookie headers.
- [ ] **P0-02** `app/main.py:765` — **Public static mount exposes helpdesk attachments.** Move attachments to private storage with tenant+record-scoped, authenticated download and expiration; audit existing public URLs.
- [ ] **P0-03** `app/api/v2/autopilot.py:53` — **Autopilot v2 dependency graph does not authenticate requests correctly.** Use `Claims = Annotated[dict, Depends(get_current_user_claims)]` for the handler parameter and call `company_id(claims)` in the handler; add tenant, user and RBAC tests for all 28 endpoints.
- [ ] **P0-04** `app/db/dependencies.py:60` — **Alternate school-auth path refers to fields absent from HRMS User.** Decouple/remove unrelated school routes from the HRMS application, or implement an explicit school-specific principal and independently tested auth model.
- [ ] **P0-05** `app/main.py:74` — **Startup candidate auto-screening does not tenant-scope email lookup or new candidate.** Move screening to tenant-scoped jobs, require candidate company_id, match on company_id+email, prohibit fake phone values and backfill prior null-owned records carefully.
- [ ] **P0-06** `app/services/security_setting_service.py:140` — **Security session listing creates fake real database records.** Remove seeding; return an empty list and record only real authenticated sessions, with company/user scope.
- [ ] **P0-07** `app/main.py:248` — **Bootstrap reactivates previously disabled super-admin account.** Provision only once in an explicitly authorized bootstrap migration; never auto-reactivate existing accounts; use audited break-glass recovery.
- [ ] **P0-08** `app/services/face_service.py:17` — **Legacy face recognition uses image hash, not biometric matching.** Remove/disable this legacy route unless replaced by real liveness-detecting biometric pipeline, tenant-bound with consent and strict verification.
### P1 — Core pending features
- [ ] **P1-01** `app/api/global_notifications.py:72` — **Automation endpoints return static rules, logs, jobs and fake mutation success.** Replace with company-scoped tables, state transitions, Celery jobs and genuine task records; do not return success when nothing was done.
- [ ] **P1-02** `app/services/autopilot_service.py:630` — **Autopilot onboarding retries and payroll status are stubs.** Implement persisted run/step tables with actual worker dispatch and idempotency, or return explicit 501 until built.
- [ ] **P1-03** `app/services/autopilot_service.py:343` — **Autopilot agent chat is deterministic placeholder, not LLM.** Call configured LLM with structured, verified action proposals; never execute unreviewed actions; preserve human approval.
- [ ] **P1-04** `app/api/v1/hr_ops_analytics.py:374` — **Document generator reports success without creating a document.** Use real document generation/vault service, persist metadata and file, and test download only after successful write.
- [ ] **P1-05** `app/api/v1/hr_ops_analytics.py:533` — **Policy search returns hard-coded fake documents.** Query company-authorized policy documents or RAG index and return empty/no-results when unavailable.
- [ ] **P1-06** `app/api/v1/hr_ops_analytics.py:328` — **Analytics CSV export labels hex as Base64; invalid SQL CASE construction.** Use `sqlalchemy.case` and `base64.b64encode(csv_content.encode()).decode('ascii')`; regression-test output decoding and SQL execution.
- [ ] **P1-07** `app/db/database.py:264` — **In-process schema healing mixes synchronous inspector with async engine.** Run Alembic upgrades as a separate release step and remove schema self-healing from application startup; fail readiness on migration mismatch.
- [ ] **P1-08** `app/db/session.py:1` — **Two independent session/engine lifecycles.** Consolidate sessions and exclude school/legacy code paths where not required.
- [ ] **P1-09** `app/services/stt/providers.py:703` — **STT/TTS silently fall back to mock providers.** Disable mock fallback outside explicit test mode; return provider-unavailable failures and retry only safe idempotent tasks.
- [ ] **P1-10** `app/api/v1/face.py:23` — **Legacy school face upload references undefined configuration settings.** Remove school routes from HRMS or define/validate named settings and add route regression tests.
- [ ] **P1-11** `tests/test_auth_employee_login_lifecycle.py:1` — **Historical full regression suites are failing.** Run full suite in isolated disposable PostgreSQL/Redis services; triage production bugs separately from stale test expectations and infrastructure failures.
### P2 — Security & optimization
- [ ] **P2-01** `app/db/database.py:233` — **Tenant enforcement applies to ORM SELECT, not all write paths.** Explicit tenant conditions for writes/reads and PostgreSQL RLS where appropriate; add cross-tenant test matrix for update/delete/bulk/upsert/raw SQL.
- [ ] **P2-02** `app/core/rate_limiter.py:168` — **Rate limit trusts unvalidated X-Forwarded-For and general limiter fails open.** Trust forwarding headers only from known proxies and enforce strict limits on sensitive endpoints; test Redis outage behavior.
- [ ] **P2-03** `app/main.py:491` — **Production CORS includes dev origins and exception handlers admit LAN-origin regex.** Separate environment allowlists; rely on one CORS middleware and avoid reflective origin handling in custom exception handlers.
- [ ] **P2-04** `app/main.py:164` — **Application may start serving even if PostgreSQL is down.** Make readiness fail until DB/migrations are ready; use separate liveness vs readiness and meaningful process admission gating.
- [ ] **P2-05** `app/middleware/auth.py:214` — **Auth tenant context set without explicit reset.** Use `token = tenant_id_ctx.set(...)` and reset in ASGI middleware finally, then test concurrent isolated requests/background tasks.
- [ ] **P2-06** `app/services/recruitment_service.py:1` — **Oversized service/controller files hinder maintainability.** Refactor by domain operations with APIs and tests unchanged; avoid an arbitrary 50-line module maximum for cohesive functions or schema declarations.
### Verification gates
- [ ] All API handlers must enforce authenticated user identity and tenant/role per endpoint. Negative tests: missing token, wrong role, wrong company, bad input and Redis outage.
- [ ] All currently mocked UI-facing endpoints either connect to persisted services or return a non-success "not implemented/unavailable" response. No fake activity/session/payroll/attendance records.
- [ ] Alembic graph has one head and upgrades from empty/previous schemas; verify `alembic upgrade head` on disposable PostgreSQL, then check schema diffs.
- [ ] Full tests pass on disposable PostgreSQL/Redis with integration tests enabled; trace exact XML of this run; do not interpret 28 passing payroll regression cases as total payroll coverage.
- [ ] Run secret scans, dependency audits, PII review, load test with multiple tenants/workers; verify CORS and static media URLs from unauthenticated clients.
### Historical pytest evidence
| Historical file | Tests | Failures | Errors | Skipped |
|---|---:|---:|---:|---:|
| `verification/full-backend-20261115.xml` | 1 | 0 | 1 | 0 |
| `verification/full-backend-elevated-20261115.xml` | 1153 | 104 | 0 | 4 |
| `verification/full-backend-post-statutory-20261115-rerun.xml` | 1182 | 202 | 7 | 22 |
| `verification/full-backend-without-sse-20261115.xml` | 1153 | 104 | 12 | 4 |
| `verification/payroll-pg-28-regressions.xml` | 28 | 0 | 0 | 0 |
Observed report errors (subset, historical):
- `tests.attendance.test_break_face.test_break_start_without_image_returns_400` — ConnectionRefusedError: [WinError 1225] The remote computer refused the network connection
- `tests.attendance.test_break_face.test_break_start_without_checkin_returns_400` — ConnectionRefusedError: [WinError 1225] The remote computer refused the network connection
- `tests.attendance.test_break_face.test_break_start_with_mismatched_face_returns_400` — ConnectionRefusedError: [WinError 1225] The remote computer refused the network connection
- `tests.attendance.test_break_face.test_break_start_and_end_lifecycle_success` — ConnectionRefusedError: [WinError 1225] The remote computer refused the network connection
- `tests.attendance.test_break_face.test_checkout_auto_ends_open_break_without_break_image` — ConnectionRefusedError: [WinError 1225] The remote computer refused the network connection
- `tests.attendance.test_break_face.test_break_multipart_form_data_support` — ConnectionRefusedError: [WinError 1225] The remote computer refused the network connection
- `tests.expenses.test_expense_migration.test_expense_migration_has_single_head_and_additive_offline_sql` — AssertionError: assert ['e1f2a3b4c5d6'] == ['912a_expense_workflow']
- `tests.test_ai_chat_assistant_routes.test_create_and_list_conversations` — ConnectionRefusedError: [WinError 1225] The remote computer refused the network connection
- `tests.test_ai_chat_assistant_routes.test_send_message_aliases` — json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)
- `tests.test_ai_chat_assistant_routes.test_tenant_isolation` — ConnectionRefusedError: [WinError 1225] The remote computer refused the network connection
- `tests.test_ai_chat_assistant_routes.test_history_and_feedback_endpoints` — json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)
- `tests.test_ai_chat_assistant_routes.test_specialized_ai_chat_endpoints` — ConnectionRefusedError: [WinError 1225] The remote computer refused the network connection
- `tests.test_ai_chat_assistant_routes.test_ai_hub_backward_compatibility_endpoints` — ConnectionRefusedError: [WinError 1225] The remote computer refused the network connection
- `tests.test_ai_face_attendance.test_face_attendance_full_lifecycle` — ConnectionRefusedError: [WinError 1225] The remote computer refused the network connection
- `tests.test_ai_face_attendance.test_checkin_auto_closes_stale_previous_day_session` — NameError: name 'Attendance' is not defined
- `tests.test_ai_face_attendance.test_checkin_same_day_active_session_returns_session_details` — NameError: name 'Attendance' is not defined
- `tests.test_ai_face_attendance.test_checkin_expired_shift_session_auto_closes` — NameError: name 'Attendance' is not defined
- `tests.test_ai_face_attendance.test_http_exception_not_logged_as_dbapi_error` — NameError: name 'Attendance' is not defined
- `tests.test_ai_module_endpoints.test_workforce_insights_dashboard` — ConnectionRefusedError: [WinError 1225] The remote computer refused the network connection
- `tests.test_ai_module_endpoints.test_workforce_insights_kpi` — ConnectionRefusedError: [WinError 1225] The remote computer refused the network connection
- `tests.test_ai_module_endpoints.test_workforce_insights_headcount_trends` — ConnectionRefusedError: [WinError 1225] The remote computer refused the network connection
- `tests.test_ai_module_endpoints.test_workforce_insights_department_comparison` — ConnectionRefusedError: [WinError 1225] The remote computer refused the network connection
- `tests.test_ai_module_endpoints.test_employee_health_dashboard` — ConnectionRefusedError: [WinError 1225] The remote computer refused the network connection
- `tests.test_ai_module_endpoints.test_employee_health_kpi` — ConnectionRefusedError: [WinError 1225] The remote computer refused the network connection
- `tests.test_ai_module_endpoints.test_employee_health_burnout_trend` — ConnectionRefusedError: [WinError 1225] The remote computer refused the network connection
- `tests.test_ai_module_endpoints.test_employee_health_overtime` — ConnectionRefusedError: [WinError 1225] The remote computer refused the network connection
- `tests.test_ai_module_endpoints.test_meeting_intelligence_dashboard` — ConnectionRefusedError: [WinError 1225] The remote computer refused the network connection
- `tests.test_ai_module_endpoints.test_meeting_intelligence_kpi` — ConnectionRefusedError: [WinError 1225] The remote computer refused the network connection
- `tests.test_ai_module_endpoints.test_meeting_intelligence_action_items` — ConnectionRefusedError: [WinError 1225] The remote computer refused the network connection
- `tests.test_ai_module_endpoints.test_meeting_intelligence_volume` — ConnectionRefusedError: [WinError 1225] The remote computer refused the network connection
- `tests.test_ai_module_endpoints.test_ai_workforce_kpi_alias` — ConnectionRefusedError: [WinError 1225] The remote computer refused the network connection
- `tests.test_ai_module_endpoints.test_ai_employee_health_kpi_alias` — ConnectionRefusedError: [WinError 1225] The remote computer refused the network connection
- `tests.test_ai_module_endpoints.test_ai_meeting_kpi_alias` — ConnectionRefusedError: [WinError 1225] The remote computer refused the network connection
- `tests.test_ai_module_endpoints.test_ai_brain_workforce_insights_alias` — ConnectionRefusedError: [WinError 1225] The remote computer refused the network connection
- `tests.test_ai_resume_parser_comprehensive.test_storage_validation_allowed_extensions` — app.core.exceptions.AppException: File size exceeds maximum allowed limit of 10MB.
- `tests.test_alembic_single_head.test_alembic_revision_ids_fit_legacy_version_table` — AssertionError: Every Alembic revision/down_revision must be <= 28 characters; found: [('e1f2a3b4c5d6', 'down_revision', '915a_payroll_processing_lease', 29), ('915a_payr
- `tests.test_analytics_reports_hardening.test_analytics_authentication_and_role_authorization` — ConnectionRefusedError: [WinError 1225] The remote computer refused the network connection
- `tests.test_analytics_reports_hardening.test_payroll_cost_role_restriction` — ConnectionRefusedError: [WinError 1225] The remote computer refused the network connection
- `tests.test_analytics_reports_hardening.test_empty_database_honest_results` — ConnectionRefusedError: [WinError 1225] The remote computer refused the network connection
- `tests.test_analytics_reports_hardening.test_tenant_isolation_and_scoping` — ConnectionRefusedError: [WinError 1225] The remote computer refused the network connection
- `tests.test_analytics_reports_hardening.test_manager_hierarchy_scoping` — ConnectionRefusedError: [WinError 1225] The remote computer refused the network connection
- `tests.test_analytics_reports_hardening.test_csv_export_endpoint` — ConnectionRefusedError: [WinError 1225] The remote computer refused the network connection
- `tests.test_analytics_reports_hardening.test_ai_insights_resilience_and_partial_handling` — ConnectionRefusedError: [WinError 1225] The remote computer refused the network connection
- `tests.test_api_500_404_fixes.test_face_attendance_company_returns_200` — ConnectionRefusedError: [WinError 1225] The remote computer refused the network connection
- `tests.test_api_500_404_fixes.test_payroll_cycles_v2_returns_200` — ConnectionRefusedError: [WinError 1225] The remote computer refused the network connection
- `tests.test_api_500_404_fixes.test_payroll_salary_processing_v2_returns_200` — ConnectionRefusedError: [WinError 1225] The remote computer refused the network connection
- `tests.test_api_500_404_fixes.test_intelligence_models_v1_returns_200` — ConnectionRefusedError: [WinError 1225] The remote computer refused the network connection
- `tests.test_api_500_404_fixes.test_multi_tenant_isolation_face_attendance` — ConnectionRefusedError: [WinError 1225] The remote computer refused the network connection
- `tests.test_api_500_404_fixes.test_unauthorized_requests` — assert 404 in (401, 403)
- `tests.test_auth_employee_login_lifecycle.test_auth_login_valid_active_employee` — ConnectionRefusedError: [WinError 1225] The remote computer refused the network connection
- `tests.test_auth_employee_login_lifecycle.test_auth_login_wrong_password` — ConnectionRefusedError: [WinError 1225] The remote computer refused the network connection
- `tests.test_auth_employee_login_lifecycle.test_auth_login_unverified_user` — ConnectionRefusedError: [WinError 1225] The remote computer refused the network connection
- `tests.test_auth_employee_login_lifecycle.test_auth_login_inactive_user` — ConnectionRefusedError: [WinError 1225] The remote computer refused the network connection
- `tests.test_auth_employee_login_lifecycle.test_auth_login_inactive_employee_profile` — ConnectionRefusedError: [WinError 1225] The remote computer refused the network connection
- `tests.test_auth_employee_login_lifecycle.test_auth_login_successfully_activated_employee` — ConnectionRefusedError: [WinError 1225] The remote computer refused the network connection
### Migration graph
- 40 revisions, **1 current head(s):** 0003; missing down_revision references: 0.
- `alembic/versions/915a_payroll_processing_lease.py` uses a 29-character revision; archived custom test expects <=28; normal Alembic 32-character revision length might still support it. Validate schema/version table before migration (do not rename a revision that is already deployed).
## Appendix A — Every literal TODO/FIXME/HACK/XXX in Python comments
| File:line | Tag | Comment |
|---|---|---|
| `app/services/upload_service.py:89` | TODO | # TODO: Move long-running OCR processing to an asynchronous background task worker with polling |
## Appendix B — One-statement stubs/abstract methods (triage required)
| File:line | Function | Type |
|---|---|---|
| `alembic/versions/0001_baseline_schema.py:24` | `upgrade` | function |
| `alembic/versions/41a_employee_schema_contract.py:67` | `downgrade` | function |
| `alembic/versions/a7dd8d9bc88f_merge_exit_management_and_employee_.py:21` | `upgrade` | function |
| `alembic/versions/a7dd8d9bc88f_merge_exit_management_and_employee_.py:25` | `downgrade` | function |
| `app/middleware/auth.py:108` | `invalidate_all_auth_active_cache_for_user` | function |
| `app/repositories/auth_repository.py:186` | `set_user_verification_token` | method |
| `app/services/bgv_service.py:47` | `submit` | method |
| `app/services/payroll/global_payroll.py:98` | `calculate` | method |
| `app/services/stt/base.py:96` | `health_check` | method |
| `app/services/stt/base.py:101` | `transcribe` | method |
| `app/services/stt/base.py:113` | `transcribe_stream` | method |
| `app/services/stt/base.py:126` | `close` | method |
| `app/services/stt/base.py:198` | `close` | method |
| `app/services/stt/providers.py:605` | `close` | method |
| `app/services/tts/base.py:97` | `health_check` | method |
| `app/services/tts/base.py:102` | `synthesize` | method |
| `app/services/tts/base.py:116` | `synthesize_stream` | method |
| `app/services/tts/base.py:130` | `close` | method |
| `app/services/tts/base.py:226` | `close` | method |
| `app/services/tts/providers.py:455` | `close` | method |
| `app/services/tts/providers.py:727` | `close` | method |
| `app/tests/test_exit_management.py:1242` | `test_migration_order` | method |
| `tests/test_payments_razorpay.py:93` | `refresh` | method |
| `tests/test_settings_and_billing_comprehensive.py:78` | `refresh` | method |
## Appendix C — API decorator inventory (mounted prefixes may vary)
| File:line | Verb | Declared path | Python function |
|---|---|---|---|
| `app/api/ai_copilot.py:30` | POST | `/upload-resume` | `upload_resume` |
| `app/api/ai_copilot.py:57` | POST | `/extract` | `extract_resume` |
| `app/api/ai_copilot.py:82` | POST | `/embedding` | `generate_embeddings` |
| `app/api/ai_copilot.py:110` | POST | `/match` | `match_candidate` |
| `app/api/ai_copilot.py:136` | POST | `/analyze` | `analyze_candidate` |
| `app/api/ai_copilot.py:164` | POST | `/rank` | `rank_candidate` |
| `app/api/ai_copilot.py:190` | POST | `/interview` | `generate_interview_questions` |
| `app/api/ai_copilot.py:218` | GET | `/dashboard/{resume_document_id}` | `get_candidate_dashboard` |
| `app/api/ai_copilot.py:246` | GET | `/job-ranking/{job_id}` | `get_job_ranking` |
| `app/api/ai_copilot.py:279` | POST | `/copilot` | `run_copilot_tool_route` |
| `app/api/ai_insights.py:1282` | GET | `/dashboard` | `get_ai_insights_dashboard` |
| `app/api/ai_insights.py:1296` | GET | `/kpi` | `get_kpis` |
| `app/api/ai_insights.py:1310` | GET | `/attrition` | `get_attrition` |
| `app/api/ai_insights.py:1324` | GET | `/burnout` | `get_burnout` |
| `app/api/ai_insights.py:1338` | GET | `/attendance` | `get_attendance` |
| `app/api/ai_insights.py:1352` | GET | `/performance` | `get_performance` |
| `app/api/ai_insights.py:1366` | GET | `/recruitment` | `get_recruitment` |
| `app/api/ai_insights.py:1380` | GET | `/charts` | `get_charts` |
| `app/api/ai_insights.py:1394` | GET | `/recommendations` | `get_recommendations` |
| `app/api/announcements.py:26` | POST | `` | `create_announcement` |
| `app/api/announcements.py:47` | GET | `` | `list_announcements` |
| `app/api/announcements.py:81` | GET | `/{id}` | `get_announcement` |
| `app/api/announcements.py:102` | PUT | `/{id}` | `update_announcement` |
| `app/api/announcements.py:124` | DELETE | `/{id}` | `delete_announcement` |
| `app/api/announcements.py:145` | PATCH | `/{id}/publish` | `publish_announcement` |
| `app/api/announcements.py:166` | PATCH | `/{id}/archive` | `archive_announcement` |
| `app/api/applications.py:26` | GET | `/stats` | `get_recruitment_stats` |
| `app/api/applications.py:45` | GET | `` | `list_applications` |
| `app/api/applications.py:79` | GET | `/{id}` | `get_application` |
| `app/api/applications.py:99` | PATCH | `/{id}/shortlist` | `shortlist_candidate` |
| `app/api/applications.py:119` | PATCH | `/{id}/reject` | `reject_candidate` |
| `app/api/applications.py:139` | PATCH | `/{id}/hold` | `hold_candidate` |
| `app/api/applications.py:174` | PATCH | `/{id}/stage` | `move_application_stage` |
| `app/api/applications.py:196` | POST | `/bulk-move` | `bulk_move_candidates` |
| `app/api/applications.py:217` | POST | `/bulk-tag` | `bulk_tag_candidates` |
| `app/api/assets.py:55` | GET | `` | `list_assets` |
| `app/api/assets.py:98` | GET | `/analytics` | `get_analytics` |
| `app/api/assets.py:119` | GET | `/filter-options` | `get_filter_options` |
| `app/api/assets.py:140` | GET | `/upload-image` | `get_upload_image_info` |
| `app/api/assets.py:161` | POST | `/upload-image` | `upload_asset_image` |
| `app/api/assets.py:245` | POST | `` | `create_asset` |
| `app/api/assets.py:268` | GET | `/public/{id}` | `get_public_asset` |
| `app/api/assets.py:296` | GET | `/{id}` | `get_asset` |
| `app/api/assets.py:318` | PUT | `/{id}` | `update_asset` |
| `app/api/assets.py:342` | DELETE | `/{id}` | `delete_asset` |
| `app/api/assets.py:365` | POST | `/{id}/assign` | `assign_asset` |
| `app/api/assets.py:389` | POST | `/{id}/return` | `return_asset` |
| `app/api/assets.py:412` | POST | `/{id}/transfer` | `transfer_asset` |
| `app/api/assets.py:436` | POST | `/{id}/lost` | `mark_lost` |
| `app/api/assets.py:460` | POST | `/{id}/recover` | `recover_lost_asset` |
| `app/api/assets.py:483` | POST | `/{id}/retired` | `mark_retired` |
| `app/api/assets.py:506` | POST | `/{id}/maintenance` | `add_maintenance` |
| `app/api/assets.py:530` | POST | `/{id}/maintenance/{maintenance_id}/complete` | `complete_maintenance` |
| `app/api/assets.py:556` | POST | `/requests` | `create_asset_request` |
| `app/api/assets.py:579` | GET | `/requests` | `list_asset_requests` |
| `app/api/assets.py:607` | POST | `/requests/{request_id}/approve` | `approve_asset_request` |
| `app/api/assets.py:630` | POST | `/requests/{request_id}/reject` | `reject_asset_request` |
| `app/api/assets.py:655` | POST | `/requests/{request_id}/fulfill` | `fulfill_asset_request` |
| `app/api/assets.py:679` | POST | `/damage-reports` | `create_damage_report` |
| `app/api/assets.py:702` | GET | `/damage-reports` | `list_damage_reports` |
| `app/api/assets.py:727` | POST | `/damage-reports/{report_id}/status` | `update_damage_report_status` |
| `app/api/ats.py:34` | GET | `` | `get_ats_candidates` |
| `app/api/ats.py:34` | GET | `/candidates` | `get_ats_candidates` |
| `app/api/ats.py:78` | GET | `/pipeline` | `get_ats_pipeline_board` |
| `app/api/ats.py:78` | GET | `/board` | `get_ats_pipeline_board` |
| `app/api/auth.py:158` | POST | `/register` | `register_user` |
| `app/api/auth.py:185` | POST | `/verify-email` | `verify_email` |
| `app/api/auth.py:226` | POST | `/resend-verification` | `resend_otp` |
| `app/api/auth.py:226` | POST | `/resend-otp` | `resend_otp` |
| `app/api/auth.py:254` | POST | `/login` | `login` |
| `app/api/auth.py:403` | POST | `/verify-email-otp` | `verify_email_otp` |
| `app/api/auth.py:485` | POST | `/resend-email-otp` | `resend_email_otp` |
| `app/api/auth.py:513` | GET | `/google/url` | `get_google_auth_url` |
| `app/api/auth.py:546` | POST | `/google` | `google_auth` |
| `app/api/auth.py:627` | GET | `/github/url` | `get_github_auth_url` |
| `app/api/auth.py:658` | POST | `/github` | `github_auth` |
| `app/api/auth.py:751` | POST | `/refresh` | `refresh` |
| `app/api/auth.py:751` | POST | `/refresh-token` | `refresh` |
| `app/api/auth.py:810` | POST | `/logout` | `logout` |
| `app/api/auth.py:864` | POST | `/forgot-password` | `forgot_password` |
| `app/api/auth.py:892` | POST | `/verify-reset-otp` | `verify_reset_otp` |
| `app/api/auth.py:920` | POST | `/reset-password` | `reset_password` |
| `app/api/auth.py:945` | GET | `/status` | `get_auth_status` |
| `app/api/auth.py:1019` | GET | `/me` | `get_me` |
| `app/api/auth.py:1055` | POST | `/change-password` | `change_password` |
| `app/api/auth.py:1055` | PATCH | `/change-password` | `change_password` |
| `app/api/auth.py:1087` | PATCH | `/change-email` | `change_email` |
| `app/api/auth.py:1118` | POST | `/verify-new-email` | `verify_new_email` |
| `app/api/auth.py:1149` | PATCH | `/change-phone` | `change_phone` |
| `app/api/auth.py:1200` | GET | `/sso/{provider}/url` | `enterprise_oidc_url` |
| `app/api/auth.py:1220` | GET | `/sso/{provider}/callback` | `enterprise_oidc_callback` |
| `app/api/auth.py:1239` | POST | `/saml/acs` | `enterprise_saml_acs` |
| `app/api/automation.py:25` | POST | `/rules` | `create_automation_rule` |
| `app/api/automation.py:46` | GET | `/rules` | `list_automation_rules` |
| `app/api/billing.py:75` | GET | `/subscription` | `get_subscription` |
| `app/api/billing.py:145` | GET | `/payment-methods` | `get_payment_methods` |
| `app/api/billing.py:206` | POST | `/payment-methods` | `add_payment_method` |
| `app/api/billing.py:277` | GET | `/invoices` | `get_invoices` |
| `app/api/calendar.py:52` | POST | `/events` | `create_event` |
| `app/api/calendar.py:73` | GET | `/events` | `list_events` |
| `app/api/calendar.py:109` | GET | `/events/{id}` | `get_event` |
| `app/api/calendar.py:129` | PUT | `/events/{id}` | `update_event` |
| `app/api/calendar.py:150` | DELETE | `/events/{id}` | `delete_event` |
| `app/api/calendar.py:175` | POST | `/holidays` | `create_holiday` |
| `app/api/calendar.py:195` | GET | `/holidays` | `list_holidays` |
| `app/api/calendar.py:216` | PUT | `/holidays/{id}` | `update_holiday` |
| `app/api/calendar.py:237` | DELETE | `/holidays/{id}` | `delete_holiday` |
| `app/api/calendar.py:281` | POST | `/holidays/import` | `import_holidays` |
| `app/api/calendar.py:357` | POST | `/meetings` | `create_meeting` |
| `app/api/calendar.py:378` | GET | `/meetings` | `list_meetings` |
| `app/api/calendar.py:404` | GET | `/meetings/{id}` | `get_meeting` |
| `app/api/calendar.py:424` | PUT | `/meetings/{id}` | `update_meeting` |
| `app/api/calendar.py:445` | DELETE | `/meetings/{id}` | `delete_meeting` |
| `app/api/calendar.py:470` | GET | `/birthdays` | `list_birthdays` |
| `app/api/calendar.py:491` | GET | `/anniversaries` | `list_anniversaries` |
| `app/api/calendar.py:517` | GET | `/dashboard` | `get_dashboard` |
| `app/api/careers.py:24` | GET | `` | `list_published_jobs` |
| `app/api/careers.py:42` | GET | `/search` | `search_jobs` |
| `app/api/careers.py:68` | GET | `/filter` | `filter_jobs` |
| `app/api/careers.py:95` | GET | `/{slug}` | `get_job_by_slug` |
| `app/api/careers.py:114` | POST | `/{slug}/apply` | `apply_to_job` |
| `app/api/careers.py:175` | GET | `/channel/{ukey}` | `get_job_by_ukey` |
| `app/api/careers.py:195` | POST | `/channel/{ukey}/apply` | `apply_to_job_by_ukey` |
| `app/api/connect.py:91` | GET | `/colleagues` | `get_colleagues` |
| `app/api/connect.py:126` | GET | `/search` | `unified_search` |
| `app/api/connect.py:159` | GET | `/conversations` | `get_conversations` |
| `app/api/connect.py:182` | POST | `/conversations` | `create_conversation` |
| `app/api/connect.py:209` | GET | `/conversations/{conversationId}/messages` | `get_conversation_messages` |
| `app/api/connect.py:245` | POST | `/conversations/{conversationId}/messages` | `send_conversation_message` |
| `app/api/connect.py:279` | POST | `/messages/{messageId}/reactions` | `toggle_reaction` |
| `app/api/connect.py:308` | PATCH | `/messages/{messageId}/pin` | `pin_message` |
| `app/api/connect.py:337` | DELETE | `/messages/{messageId}` | `delete_message` |
| `app/api/connect.py:364` | GET | `/messages/{parentMessageId}/thread` | `get_message_thread` |
| `app/api/connect.py:392` | POST | `/messages/{parentMessageId}/thread` | `post_thread_reply` |
| `app/api/connect.py:429` | GET | `/channels` | `get_channels` |
| `app/api/connect.py:453` | POST | `/channels` | `create_channel` |
| `app/api/connect.py:483` | GET | `/channels/{channelId}` | `get_channel_detail` |
| `app/api/connect.py:510` | PATCH | `/channels/{channelId}` | `update_channel` |
| `app/api/connect.py:542` | DELETE | `/channels/{channelId}` | `delete_channel` |
| `app/api/connect.py:569` | POST | `/channels/{channelId}/members` | `add_channel_members` |
| `app/api/connect.py:598` | DELETE | `/channels/{channelId}/members/{userId}` | `remove_channel_member` |
| `app/api/connect.py:627` | GET | `/channels/{channelId}/messages` | `get_channel_messages` |
| `app/api/connect.py:665` | POST | `/channels/{channelId}/messages` | `send_channel_message` |
| `app/api/connect.py:699` | POST | `/channels/{channelId}/leave` | `leave_channel` |
| `app/api/connect.py:726` | PATCH | `/channels/{channelId}/archive` | `archive_channel` |
| `app/api/connect.py:759` | GET | `/calls/ice-servers` | `get_ice_servers` |
| `app/api/connect.py:781` | GET | `/calls/history` | `get_call_history` |
| `app/api/connect.py:804` | GET | `/calls/{callId}` | `get_call_detail` |
| `app/api/connect.py:832` | POST | `/calls/initiate` | `initiate_call` |
| `app/api/connect.py:860` | PATCH | `/calls/{callId}/status` | `update_call_status` |
| `app/api/connect.py:889` | POST | `/calls/{callId}/signal` | `call_signal` |
| `app/api/connect.py:924` | GET | `/meetings` | `get_meetings` |
| `app/api/connect.py:948` | POST | `/meetings` | `create_meeting` |
| `app/api/connect.py:984` | GET | `/meetings/{meetingId}` | `get_meeting_detail` |
| `app/api/connect.py:1011` | POST | `/meetings/{meetingId}/join` | `join_meeting` |
| `app/api/connect.py:1038` | POST | `/meetings/{meetingId}/leave` | `leave_meeting` |
| `app/api/connect.py:1068` | POST | `/meetings/{meetingId}/messages` | `send_meeting_message` |
| `app/api/connect.py:1101` | GET | `/files` | `get_shared_files` |
| `app/api/connect.py:1135` | POST | `/files/upload` | `upload_shared_file` |
| `app/api/connect.py:1162` | DELETE | `/files/{fileId}` | `delete_shared_file` |
| `app/api/connect.py:1193` | PUT | `/presence` | `update_presence` |
| `app/api/connect.py:1221` | POST | `/presence/batch` | `batch_presence` |
| `app/api/connect.py:1251` | GET | `/notifications` | `get_notifications` |
| `app/api/connect.py:1282` | PATCH | `/notifications/{notificationId}/read` | `mark_notification_read` |
| `app/api/connect.py:1309` | DELETE | `/notifications` | `clear_notifications` |
| `app/api/connect.py:1335` | GET | `/settings/sound` | `get_sound_settings` |
| `app/api/connect.py:1357` | PUT | `/settings/sound` | `update_sound_settings` |
| `app/api/connect.py:1396` | POST | `/ai/transform` | `ai_transform` |
| `app/api/connect.py:1428` | POST | `/mail/dispatch` | `mail_dispatch` |
| `app/api/connect.py:1461` | WEBSOCKET | `/ws` | `connect_websocket` |
| `app/api/crm.py:25` | POST | `/notes` | `create_crm_note` |
| `app/api/crm.py:47` | GET | `/notes/{candidate_id}` | `list_crm_notes` |
| `app/api/cto/dashboard.py:15` | GET | `/dashboard` | `get_cto_dashboard_metrics` |
| `app/api/departments.py:82` | POST | `` | `create_department` |
| `app/api/departments.py:105` | GET | `` | `list_departments` |
| `app/api/departments.py:158` | GET | `/summary` | `get_departments_summary` |
| `app/api/departments.py:179` | GET | `/stats` | `get_departments_overview_stats` |
| `app/api/departments.py:200` | GET | `/analytics` | `get_department_analytics` |
| `app/api/departments.py:227` | GET | `/hierarchy` | `get_department_hierarchy` |
| `app/api/departments.py:227` | GET | `/tree` | `get_department_hierarchy` |
| `app/api/departments.py:248` | POST | `/bulk-delete` | `bulk_delete_departments` |
| `app/api/departments.py:271` | POST | `/bulk-status` | `bulk_update_status` |
| `app/api/departments.py:294` | POST | `/bulk-assign-manager` | `bulk_assign_manager` |
| `app/api/departments.py:317` | POST | `/transfer-employees` | `transfer_employees` |
| `app/api/departments.py:346` | GET | `/export` | `export_departments` |
| `app/api/departments.py:366` | GET | `/export/csv` | `export_departments_csv` |
| `app/api/departments.py:386` | POST | `/import` | `import_departments` |
| `app/api/departments.py:413` | GET | `/{id}` | `get_department` |
| `app/api/departments.py:441` | PUT | `/{id}` | `update_department` |
| `app/api/departments.py:441` | PATCH | `/{id}` | `update_department` |
| `app/api/departments.py:465` | DELETE | `/{id}` | `delete_department` |
| `app/api/departments.py:488` | GET | `/{id}/hierarchy` | `get_department_subtree_hierarchy` |
| `app/api/departments.py:510` | POST | `/{id}/assign-manager` | `assign_manager` |
| `app/api/departments.py:534` | DELETE | `/{id}/remove-manager` | `remove_manager` |
| `app/api/departments.py:557` | GET | `/{id}/manager` | `get_manager` |
| `app/api/departments.py:580` | POST | `/{id}/assign-employees` | `assign_employees` |
| `app/api/departments.py:604` | DELETE | `/{id}/remove-employee/{employee_id}` | `remove_employee` |
| `app/api/departments.py:630` | PATCH | `/bulk-status` | `bulk_update_status_patch` |
| `app/api/departments.py:645` | PATCH | `/bulk-assign-manager` | `bulk_assign_manager_patch` |
| `app/api/departments.py:660` | POST | `/{id}/employees` | `assign_employees_post` |
| `app/api/departments.py:676` | DELETE | `/{id}/employees/{employee_id}` | `remove_employee_delete` |
| `app/api/departments.py:692` | GET | `/{id}/employees` | `get_employees` |
| `app/api/departments.py:715` | GET | `/{id}/stats` | `get_stats` |
| `app/api/documents.py:83` | GET | `/categories` | `list_categories` |
| `app/api/documents.py:108` | POST | `/employees` | `upload_employee_document` |
| `app/api/documents.py:185` | GET | `/employees` | `list_employee_documents` |
| `app/api/documents.py:248` | GET | `/employees/{id}` | `get_employee_document` |
| `app/api/documents.py:279` | GET | `/employees/{id}/download` | `download_employee_document` |
| `app/api/documents.py:331` | PUT | `/employees/{id}` | `update_employee_document` |
| `app/api/documents.py:386` | DELETE | `/employees/{id}` | `delete_employee_document` |
| `app/api/documents.py:422` | GET | `/employees/{id}/versions` | `list_document_versions` |
| `app/api/documents.py:442` | GET | `/employees/{id}/versions/{version_number}/download` | `download_document_version` |
| `app/api/documents.py:481` | GET | `/employees/{id}/history` | `get_document_history` |
| `app/api/documents.py:507` | POST | `/company` | `upload_company_document` |
| `app/api/documents.py:554` | GET | `/company` | `list_company_documents` |
| `app/api/documents.py:615` | GET | `/company/{id}` | `get_company_document` |
| `app/api/documents.py:646` | GET | `/company/{id}/download` | `download_company_document` |
| `app/api/documents.py:697` | PUT | `/company/{id}` | `update_company_document` |
| `app/api/documents.py:744` | DELETE | `/company/{id}` | `delete_company_document` |
| `app/api/documents.py:779` | POST | `/{id}/request-signature` | `request_signature` |
| `app/api/documents.py:809` | POST | `/{id}/sign` | `sign_document` |
| `app/api/documents.py:840` | GET | `/{id}/signature-status` | `get_signature_status` |
| `app/api/documents.py:882` | PATCH | `/{id}/verify` | `verify_document` |
| `app/api/documents.py:916` | PATCH | `/{id}/reject` | `reject_document` |
| `app/api/documents.py:950` | PATCH | `/{id}/request-reupload` | `request_reupload` |
| `app/api/documents.py:988` | GET | `/expiring` | `list_expiring_documents` |
| `app/api/documents.py:1025` | GET | `/expired` | `list_expired_documents` |
| `app/api/documents.py:1064` | GET | `/summary` | `get_document_summary` |
| `app/api/documents.py:1094` | POST | `/upload` | `upload_document_ocr` |
| `app/api/documents.py:1119` | GET | `` | `list_documents_ocr` |
| `app/api/documents.py:1174` | GET | `/{document_id}` | `get_document_ocr_detail` |
| `app/api/documents.py:1205` | GET | `/{document_id}/json` | `download_document_ocr_json` |
| `app/api/employee_onboarding_admin_api.py:39` | POST | `/{employee_id}/bgv` | `update_bgv_status` |
| `app/api/employee_onboarding_admin_api.py:54` | GET | `/{employee_id}/joining-checklist` | `get_joining_checklist` |
| `app/api/employee_onboarding_admin_api.py:66` | POST | `/{employee_id}/joining-checklist/{task_id}/complete` | `complete_joining_task` |
| `app/api/employee_onboarding_admin_api.py:80` | GET | `` | `list_progress` |
| `app/api/employee_onboarding_admin_api.py:107` | GET | `/{employee_id}` | `get_progress_details` |
| `app/api/employee_onboarding_admin_api.py:129` | PUT | `/{employee_id}/document/{doc_id}/verify` | `verify_onboarding_document` |
| `app/api/employee_onboarding_api.py:58` | GET | `/status` | `get_status` |
| `app/api/employee_onboarding_api.py:75` | GET | `/progress` | `get_progress` |
| `app/api/employee_onboarding_api.py:92` | PUT | `/step/1` | `save_step_1` |
| `app/api/employee_onboarding_api.py:110` | PUT | `/step/2` | `save_step_2` |
| `app/api/employee_onboarding_api.py:128` | PUT | `/step/3` | `save_step_3` |
| `app/api/employee_onboarding_api.py:146` | PUT | `/step/4` | `save_step_4` |
| `app/api/employee_onboarding_api.py:164` | PUT | `/step/5` | `save_step_5` |
| `app/api/employee_onboarding_api.py:182` | PUT | `/step/6` | `save_step_6` |
| `app/api/employee_onboarding_api.py:200` | PUT | `/step/7` | `save_step_7` |
| `app/api/employee_onboarding_api.py:218` | POST | `/step/8/upload` | `upload_document` |
| `app/api/employee_onboarding_api.py:285` | DELETE | `/step/8/document/{doc_id}` | `delete_document` |
| `app/api/employee_onboarding_api.py:313` | PUT | `/step/8` | `save_step_8` |
| `app/api/employee_onboarding_api.py:330` | PUT | `/step/9` | `save_step_9` |
| `app/api/employee_onboarding_api.py:350` | POST | `/complete` | `complete_flow` |
| `app/api/employee_onboarding_api.py:372` | POST | `/draft` | `save_draft_state` |
| `app/api/employees.py:64` | POST | `` | `create_employee` |
| `app/api/employees.py:99` | GET | `/dashboard` | `get_employee_dashboard_stats` |
| `app/api/employees.py:99` | GET | `/stats` | `get_employee_dashboard_stats` |
| `app/api/employees.py:120` | POST | `/import` | `import_employees` |
| `app/api/employees.py:148` | GET | `/export` | `export_employees` |
| `app/api/employees.py:194` | GET | `` | `list_employees` |
| `app/api/employees.py:239` | GET | `/{id}` | `get_employee` |
| `app/api/employees.py:285` | PUT | `/{id}` | `update_employee` |
| `app/api/employees.py:285` | PATCH | `/{id}` | `update_employee` |
| `app/api/employees.py:328` | DELETE | `/{id}` | `delete_employee` |
| `app/api/employees.py:351` | POST | `/{id}/send-invitation` | `send_invitation` |
| `app/api/employees.py:374` | POST | `/{id}/send-invite` | `send_invite_alias` |
| `app/api/employees.py:397` | POST | `/{id}/deactivate` | `deactivate_employee` |
| `app/api/employees.py:421` | POST | `/{id}/activate-by-admin` | `activate_employee_by_admin` |
| `app/api/employees.py:444` | GET | `/validate-invitation` | `validate_employee_invitation` |
| `app/api/employees.py:464` | GET | `/validate-token` | `validate_employee_invitation_token_alias` |
| `app/api/employees.py:484` | GET | `/validate` | `validate_employee_invitation_alias` |
| `app/api/employees.py:504` | POST | `/{id}/activate` | `activate_employee` |
| `app/api/employees.py:531` | POST | `/{id}/approve` | `approve_employee` |
| `app/api/employees.py:554` | POST | `/{id}/reject` | `reject_employee` |
| `app/api/employees.py:578` | POST | `/{id}/reset-password` | `reset_password` |
| `app/api/employees.py:601` | GET | `/{id}/onboarding-status` | `get_onboarding_status` |
| `app/api/events.py:26` | POST | `` | `create_event` |
| `app/api/events.py:47` | GET | `` | `list_events` |
| `app/api/events.py:68` | GET | `/{id}` | `get_event` |
| `app/api/events.py:88` | PUT | `/{id}` | `update_event` |
| `app/api/events.py:110` | DELETE | `/{id}` | `delete_event` |
| `app/api/events.py:131` | PATCH | `/{id}/publish` | `publish_event` |
| `app/api/events.py:163` | PATCH | `/{id}/cancel` | `cancel_event` |
| `app/api/events.py:195` | POST | `/{id}/register` | `register_event` |
| `app/api/exits.py:54` | POST | `/resign` | `submit_resignation` |
| `app/api/exits.py:80` | POST | `/hr-initiate` | `hr_initiate_exit` |
| `app/api/exits.py:110` | GET | `/my-request` | `get_my_request` |
| `app/api/exits.py:130` | DELETE | `/my-request` | `cancel_my_request` |
| `app/api/exits.py:155` | GET | `/stats` | `get_exit_stats` |
| `app/api/exits.py:175` | GET | `` | `list_exits` |
| `app/api/exits.py:204` | GET | `/{id}` | `get_exit` |
| `app/api/exits.py:249` | PATCH | `/{id}/approve` | `hr_approve` |
| `app/api/exits.py:281` | PATCH | `/{id}/reject` | `hr_reject` |
| `app/api/exits.py:313` | PATCH | `/{id}/start-notice-period` | `start_notice_period` |
| `app/api/exits.py:344` | PATCH | `/{id}/complete` | `complete_exit` |
| `app/api/exits.py:380` | PATCH | `/{id}/manager-approve` | `manager_approve` |
| `app/api/exits.py:407` | PATCH | `/{id}/manager-reject` | `manager_reject` |
| `app/api/exits.py:433` | PATCH | `/{id}/knowledge-transfer-complete` | `knowledge_transfer_complete` |
| `app/api/exits.py:470` | GET | `/{id}/assets` | `get_assets_checklist` |
| `app/api/exits.py:516` | PATCH | `/{id}/asset-return` | `return_asset` |
| `app/api/exits.py:555` | PATCH | `/{id}/clearance` | `update_clearance` |
| `app/api/exits.py:594` | POST | `/{id}/exit-interview` | `submit_exit_interview` |
| `app/api/exits.py:631` | GET | `/{id}/fnf-preview` | `get_fnf_preview` |
| `app/api/exits.py:663` | PATCH | `/{id}/fnf` | `submit_fnf` |
| `app/api/exits.py:713` | POST | `/{id}/fnf/confirm-payment` | `confirm_fnf_payment` |
| `app/api/exits.py:765` | GET | `/{id}/documents` | `get_exit_documents` |
| `app/api/exits.py:812` | POST | `/{id}/generate-documents` | `generate_exit_documents` |
| `app/api/expenses.py:36` | GET | `` | `list_expenses` |
| `app/api/expenses.py:82` | POST | `` | `create_expense` |
| `app/api/expenses.py:106` | GET | `/{expense_id}` | `get_expense` |
| `app/api/expenses.py:129` | PATCH | `/{expense_id}` | `update_expense` |
| `app/api/expenses.py:153` | DELETE | `/{expense_id}` | `delete_expense` |
| `app/api/expenses.py:171` | POST | `/{expense_id}/submit` | `submit_expense` |
| `app/api/expenses.py:194` | POST | `/{expense_id}/approve` | `approve_expense` |
| `app/api/expenses.py:219` | POST | `/{expense_id}/reject` | `reject_expense` |
| `app/api/expenses.py:243` | POST | `/{expense_id}/request-changes` | `request_changes_expense` |
| `app/api/expenses.py:267` | POST | `/{expense_id}/mark-paid` | `mark_paid_expense` |
| `app/api/expenses.py:291` | PATCH | `/{expense_id}/status` | `update_expense_status` |
| `app/api/exports.py:111` | GET | `/employees` | `export_employees` |
| `app/api/exports.py:133` | GET | `/departments` | `export_departments` |
| `app/api/exports.py:149` | GET | `/managers` | `export_managers` |
| `app/api/exports.py:167` | GET | `/attendance` | `export_attendance` |
| `app/api/exports.py:183` | GET | `/face-attendance` | `export_face_attendance` |
| `app/api/exports.py:203` | GET | `/leaves` | `export_leaves` |
| `app/api/exports.py:219` | GET | `/payroll` | `export_payroll` |
| `app/api/exports.py:235` | GET | `/performance` | `export_performance` |
| `app/api/generate_api.py:41` | POST | `/generate` | `generate_text` |
| `app/api/generate_api.py:41` | POST | `/v1/generate` | `generate_text` |
| `app/api/global_notifications.py:184` | GET | `/notifications` | `get_notifications` |
| `app/api/global_notifications.py:184` | HEAD | `/notifications` | `get_notifications` |
| `app/api/global_notifications.py:207` | POST | `/notifications/{notif_id}/read` | `mark_notification_read` |
| `app/api/global_notifications.py:228` | POST | `/notifications/read-all` | `mark_all_notifications_read` |
| `app/api/global_notifications.py:243` | DELETE | `/notifications/{notif_id}` | `delete_notification` |
| `app/api/global_notifications.py:268` | GET | `/automation-rules` | `list_automation_rules` |
| `app/api/global_notifications.py:268` | HEAD | `/automation-rules` | `list_automation_rules` |
| `app/api/global_notifications.py:278` | POST | `/automation-rules` | `create_automation_rule` |
| `app/api/global_notifications.py:299` | POST | `/automation-rules/{rule_id}/toggle` | `toggle_automation_rule` |
| `app/api/global_notifications.py:313` | POST | `/automation-rules/{rule_id}/test` | `test_automation_rule` |
| `app/api/global_notifications.py:349` | GET | `/activity` | `get_automation_activity` |
| `app/api/global_notifications.py:359` | POST | `/activity/{act_id}/retry` | `retry_automation_activity` |
| `app/api/global_notifications.py:382` | GET | `/scheduled-jobs` | `get_scheduled_jobs` |
| `app/api/global_notifications.py:392` | POST | `/scheduled-jobs/{job_id}/toggle` | `toggle_scheduled_job` |
| `app/api/global_notifications.py:409` | GET | `/preferences` | `get_preferences` |
| `app/api/global_notifications.py:429` | PUT | `/preferences` | `update_preferences` |
| `app/api/helpdesk.py:80` | GET | `/tickets/my` | `get_my_support_tickets` |
| `app/api/helpdesk.py:120` | POST | `/tickets` | `create_support_ticket` |
| `app/api/helpdesk.py:155` | GET | `/tickets/{ticketId}` | `get_ticket_by_id` |
| `app/api/helpdesk.py:186` | GET | `/tickets/{ticketId}/comments` | `get_ticket_comments` |
| `app/api/helpdesk.py:218` | POST | `/tickets/{ticketId}/comments` | `add_ticket_comment` |
| `app/api/helpdesk.py:253` | POST | `/tickets/attachments/upload` | `upload_ticket_attachment` |
| `app/api/helpdesk.py:284` | GET | `/admin/tickets` | `get_all_helpdesk_tickets` |
| `app/api/helpdesk.py:329` | PATCH | `/tickets/{ticketId}/status` | `update_ticket_status` |
| `app/api/helpdesk.py:363` | PATCH | `/tickets/{ticketId}/assign` | `assign_ticket_agent` |
| `app/api/helpdesk.py:398` | POST | `/tickets/{ticketId}/internal-notes` | `add_internal_ticket_note` |
| `app/api/helpdesk.py:431` | GET | `/faqs` | `get_helpdesk_faqs` |
| `app/api/helpdesk.py:463` | POST | `/admin/faqs` | `upsert_helpdesk_faq` |
| `app/api/helpdesk.py:498` | POST | `/ai/chat` | `execute_support_ai_chat` |
| `app/api/helpdesk.py:530` | GET | `/admin/metrics` | `get_helpdesk_sla_metrics` |
| `app/api/hierarchy.py:126` | GET | `` | `get_hierarchy` |
| `app/api/hierarchy.py:180` | GET | `/tree` | `get_hierarchy_tree` |
| `app/api/hierarchy.py:208` | GET | `/chart` | `get_hierarchy_chart` |
| `app/api/hierarchy.py:262` | GET | `/analytics` | `get_analytics` |
| `app/api/hierarchy.py:282` | GET | `/{employee_id}` | `get_employee_hierarchy_details` |
| `app/api/hierarchy.py:308` | GET | `/path/{employee_id}` | `get_reporting_path` |
| `app/api/hierarchy.py:347` | PUT | `/assign-manager` | `assign_manager` |
| `app/api/hierarchy.py:373` | PUT | `/change-manager` | `change_manager` |
| `app/api/hierarchy.py:399` | DELETE | `/remove-manager/{employee_id}` | `remove_manager` |
| `app/api/hierarchy.py:425` | GET | `/direct-reports/{manager_id}` | `get_direct_reports` |
| `app/api/hierarchy.py:451` | GET | `/team/{manager_id}` | `get_team` |
| `app/api/hr_admin.py:53` | POST | `/users` | `create_user` |
| `app/api/hr_admin.py:84` | GET | `/users` | `list_users` |
| `app/api/hr_admin.py:125` | GET | `/users/{user_id}` | `get_user` |
| `app/api/hr_admin.py:156` | PATCH | `/users/{user_id}` | `update_user` |
| `app/api/hr_admin.py:195` | DELETE | `/users/{user_id}` | `delete_user` |
| `app/api/hr_admin.py:228` | POST | `/users/{user_id}/resend-invite` | `resend_invite` |
| `app/api/hr_admin_onboarding.py:112` | GET | `/profile` | `get_admin_profile` |
| `app/api/hr_admin_onboarding.py:112` | GET | `/admin-profile` | `get_admin_profile` |
| `app/api/hr_admin_onboarding.py:127` | POST | `/profile` | `update_admin_profile` |
| `app/api/hr_admin_onboarding.py:127` | PUT | `/profile` | `update_admin_profile` |
| `app/api/hr_admin_onboarding.py:127` | POST | `/admin-profile` | `update_admin_profile` |
| `app/api/hr_admin_onboarding.py:127` | PUT | `/admin-profile` | `update_admin_profile` |
| `app/api/hr_admin_onboarding.py:162` | GET | `/organization` | `get_organization` |
| `app/api/hr_admin_onboarding.py:162` | GET | `/company` | `get_organization` |
| `app/api/hr_admin_onboarding.py:177` | POST | `/organization` | `create_organization` |
| `app/api/hr_admin_onboarding.py:177` | POST | `/company` | `create_organization` |
| `app/api/hr_admin_onboarding.py:195` | PUT | `/organization` | `update_organization` |
| `app/api/hr_admin_onboarding.py:195` | PATCH | `/organization` | `update_organization` |
| `app/api/hr_admin_onboarding.py:195` | PUT | `/company` | `update_organization` |
| `app/api/hr_admin_onboarding.py:215` | POST | `/departments` | `create_department` |
| `app/api/hr_admin_onboarding.py:230` | GET | `/departments` | `list_departments` |
| `app/api/hr_admin_onboarding.py:244` | GET | `/departments/{department_id}` | `get_department` |
| `app/api/hr_admin_onboarding.py:260` | PUT | `/departments/{department_id}` | `update_department` |
| `app/api/hr_admin_onboarding.py:260` | PATCH | `/departments/{department_id}` | `update_department` |
| `app/api/hr_admin_onboarding.py:276` | DELETE | `/departments/{department_id}` | `delete_department` |
| `app/api/hr_admin_onboarding.py:295` | POST | `/designations` | `create_designation` |
| `app/api/hr_admin_onboarding.py:310` | GET | `/designations` | `list_designations` |
| `app/api/hr_admin_onboarding.py:324` | GET | `/designations/{designation_id}` | `get_designation` |
| `app/api/hr_admin_onboarding.py:340` | PUT | `/designations/{designation_id}` | `update_designation` |
| `app/api/hr_admin_onboarding.py:340` | PATCH | `/designations/{designation_id}` | `update_designation` |
| `app/api/hr_admin_onboarding.py:356` | DELETE | `/designations/{designation_id}` | `delete_designation` |
| `app/api/hr_admin_onboarding.py:377` | GET | `/structure` | `get_organization_structure` |
| `app/api/hr_admin_onboarding.py:377` | GET | `/review` | `get_organization_structure` |
| `app/api/hr_admin_onboarding.py:377` | GET | `/organization/structure` | `get_organization_structure` |
| `app/api/hr_admin_onboarding.py:397` | GET | `/settings` | `get_work_schedule` |
| `app/api/hr_admin_onboarding.py:397` | GET | `/hr-settings` | `get_work_schedule` |
| `app/api/hr_admin_onboarding.py:397` | GET | `/work-schedule` | `get_work_schedule` |
| `app/api/hr_admin_onboarding.py:416` | POST | `/settings` | `update_work_schedule` |
| `app/api/hr_admin_onboarding.py:416` | PUT | `/settings` | `update_work_schedule` |
| `app/api/hr_admin_onboarding.py:416` | POST | `/hr-settings` | `update_work_schedule` |
| `app/api/hr_admin_onboarding.py:416` | PUT | `/hr-settings` | `update_work_schedule` |
| `app/api/hr_admin_onboarding.py:416` | POST | `/work-schedule` | `update_work_schedule` |
| `app/api/hr_admin_onboarding.py:416` | PUT | `/work-schedule` | `update_work_schedule` |
| `app/api/hr_admin_onboarding.py:435` | POST | `/leave-policies` | `create_leave_policy` |
| `app/api/hr_admin_onboarding.py:450` | GET | `/leave-policies` | `list_leave_policies` |
| `app/api/hr_admin_onboarding.py:464` | GET | `/leave-policies/{policy_id}` | `get_leave_policy` |
| `app/api/hr_admin_onboarding.py:480` | PUT | `/leave-policies/{policy_id}` | `update_leave_policy` |
| `app/api/hr_admin_onboarding.py:480` | PATCH | `/leave-policies/{policy_id}` | `update_leave_policy` |
| `app/api/hr_admin_onboarding.py:496` | DELETE | `/leave-policies/{policy_id}` | `delete_leave_policy` |
| `app/api/hr_admin_onboarding.py:516` | POST | `/invitations` | `send_individual_invitation` |
| `app/api/hr_admin_onboarding.py:516` | POST | `/invite-employee` | `send_individual_invitation` |
| `app/api/hr_admin_onboarding.py:532` | GET | `/invitations` | `list_pending_invitations` |
| `app/api/hr_admin_onboarding.py:532` | GET | `/invitations/pending` | `list_pending_invitations` |
| `app/api/hr_admin_onboarding.py:546` | POST | `/invitations/{invitation_id}/resend` | `resend_invitation` |
| `app/api/hr_admin_onboarding.py:562` | POST | `/invitations/{invitation_id}/cancel` | `cancel_invitation` |
| `app/api/hr_admin_onboarding.py:562` | DELETE | `/invitations/{invitation_id}` | `cancel_invitation` |
| `app/api/hr_admin_onboarding.py:581` | GET | `/status` | `get_onboarding_status` |
| `app/api/hr_admin_onboarding.py:608` | GET | `/progress` | `get_onboarding_progress` |
| `app/api/hr_admin_onboarding.py:608` | GET | `` | `get_onboarding_progress` |
| `app/api/hr_admin_onboarding.py:608` | GET | `/` | `get_onboarding_progress` |
| `app/api/hr_admin_onboarding.py:638` | PUT | `/progress` | `save_onboarding_progress` |
| `app/api/hr_admin_onboarding.py:638` | PATCH | `/progress` | `save_onboarding_progress` |
| `app/api/hr_admin_onboarding.py:657` | POST | `/complete` | `complete_onboarding` |
| `app/api/hr_admin_onboarding.py:680` | POST | `/upload` | `upload_onboarding_asset` |
| `app/api/hr_admin_onboarding.py:751` | POST | `` | `save_wizard_data` |
| `app/api/hr_admin_onboarding.py:751` | POST | `/` | `save_wizard_data` |
| `app/api/hr_admin_onboarding.py:797` | POST | `/step/{step_index}` | `save_step_by_index` |
| `app/api/hr_interview_dashboard.py:32` | GET | `` | `list_hr_interviews` |
| `app/api/hr_interview_dashboard.py:173` | GET | `/{interview_id}` | `get_hr_interview_detail` |
| `app/api/hr_interview_dashboard.py:344` | POST | `/{interview_id}/feedback` | `add_interview_feedback` |
| `app/api/hr_interview_dashboard.py:406` | POST | `/{interview_id}/override` | `override_ai_recommendation` |
| `app/api/hr_interview_dashboard.py:491` | POST | `/{interview_id}/advance` | `advance_candidate` |
| `app/api/internal_dashboard.py:23` | GET | `` | `get_dashboard` |
| `app/api/interviews.py:28` | POST | `/applications/{id}/send-interview` | `send_interview` |
| `app/api/interviews.py:50` | POST | `/interviews/schedule` | `schedule_interview_slot` |
| `app/api/interviews.py:71` | GET | `/interviews` | `list_interviews` |
| `app/api/interviews.py:93` | GET | `/interviews/{id}` | `get_interview` |
| `app/api/interviews.py:113` | PATCH | `/interviews/rounds/{round_id}/pass` | `pass_round` |
| `app/api/interviews.py:134` | PATCH | `/interviews/rounds/{round_id}/reject` | `reject_round` |
| `app/api/interviews.py:155` | PATCH | `/interviews/rounds/{round_id}/hold` | `hold_round` |
| `app/api/interviews.py:181` | GET | `/interviews/join/{token}` | `validate_interview_invitation` |
| `app/api/interviews.py:201` | POST | `/interviews/join/{token}/device-check` | `complete_device_check` |
| `app/api/interviews.py:228` | POST | `/interviews/join/{token}/consent` | `record_consent` |
| `app/api/interviews.py:249` | POST | `/interviews/join/{token}/start` | `start_interview_session` |
| `app/api/jobs.py:51` | POST | `` | `create_job` |
| `app/api/jobs.py:74` | GET | `` | `list_jobs` |
| `app/api/jobs.py:108` | GET | `/{id}` | `get_job` |
| `app/api/jobs.py:128` | PUT | `/{id}` | `update_job` |
| `app/api/jobs.py:150` | DELETE | `/{id}` | `delete_job` |
| `app/api/jobs.py:171` | GET | `/{id}/publish` | `get_publish_channels` |
| `app/api/jobs.py:191` | POST | `/{id}/publish` | `publish_job` |
| `app/api/jobs.py:248` | POST | `/{id}/close` | `close_job` |
| `app/api/jobs.py:288` | POST | `/{id}/draft` | `draft_job` |
| `app/api/jobs.py:313` | PATCH | `/{id}/status` | `patch_job_status` |
| `app/api/jobs.py:362` | POST | `/{id}/duplicate` | `duplicate_job` |
| `app/api/jobs.py:403` | POST | `/generate-description` | `generate_description` |
| `app/api/jobs.py:459` | POST | `/ai-autofill` | `ai_autofill` |
| `app/api/jobs.py:505` | POST | `/modify-description` | `modify_description` |
| `app/api/jobs.py:529` | GET | `/{id}/sourcing-link` | `get_sourcing_link` |
| `app/api/jobs.py:564` | GET | `/{id}/qr` | `generate_qr` |
| `app/api/jobs.py:625` | GET | `/{id}/applicants/export` | `export_applicants` |
| `app/api/leaves.py:65` | GET | `/balances` | `get_balances` |
| `app/api/leaves.py:85` | POST | `/apply` | `apply_leave` |
| `app/api/leaves.py:107` | GET | `/history` | `get_history` |
| `app/api/leaves.py:132` | GET | `/pending` | `get_pending` |
| `app/api/leaves.py:164` | GET | `/employees` | `get_company_employees` |
| `app/api/leaves.py:191` | GET | `/balances/{employee_id}` | `get_employee_balances` |
| `app/api/leaves.py:223` | GET | `/requests` | `get_all_requests` |
| `app/api/leaves.py:299` | POST | `/{leave_id}/review` | `review_leave` |
| `app/api/leaves.py:334` | POST | `/{leave_id}/cancel` | `cancel_leave` |
| `app/api/managers.py:40` | POST | `` | `create_manager` |
| `app/api/managers.py:61` | GET | `` | `list_managers` |
| `app/api/managers.py:93` | GET | `/onboarding/validate` | `validate_manager_onboarding_token` |
| `app/api/managers.py:116` | GET | `/validate` | `validate_manager_token_alias` |
| `app/api/managers.py:130` | GET | `/validate-token` | `validate_manager_token_alias2` |
| `app/api/managers.py:144` | POST | `/onboarding/activate` | `activate_manager_onboarding` |
| `app/api/managers.py:167` | POST | `/activate` | `activate_manager_canonical` |
| `app/api/managers.py:186` | GET | `/profile` | `get_manager_profile` |
| `app/api/managers.py:207` | POST | `/send-invite` | `send_invite_by_id_or_email` |
| `app/api/managers.py:240` | GET | `/{id}` | `get_manager` |
| `app/api/managers.py:260` | PUT | `/{id}` | `update_manager` |
| `app/api/managers.py:295` | PATCH | `/{id}/permissions` | `update_manager_permissions` |
| `app/api/managers.py:330` | DELETE | `/{id}` | `delete_manager` |
| `app/api/managers.py:351` | POST | `/{id}/send-invitation` | `send_invitation` |
| `app/api/managers.py:372` | POST | `/{id}/activate` | `activate_manager` |
| `app/api/managers.py:392` | POST | `/{id}/reset-password` | `reset_password` |
| `app/api/managers.py:414` | POST | `/onboarding/complete` | `complete_onboarding` |
| `app/api/managers.py:436` | POST | `/{id}/deactivate` | `deactivate_manager` |
| `app/api/managers.py:458` | POST | `/{id}/activate-by-admin` | `activate_manager_by_admin` |
| `app/api/managers.py:535` | POST | `/bulk-delete` | `bulk_delete_managers` |
| `app/api/managers.py:571` | PATCH | `/bulk-status` | `bulk_update_manager_status` |
| `app/api/managers.py:609` | POST | `/import` | `import_managers` |
| `app/api/news.py:26` | POST | `` | `create_news` |
| `app/api/news.py:47` | GET | `` | `list_news` |
| `app/api/news.py:77` | GET | `/{id}` | `get_news` |
| `app/api/news.py:98` | PUT | `/{id}` | `update_news` |
| `app/api/news.py:120` | DELETE | `/{id}` | `delete_news` |
| `app/api/news.py:141` | PATCH | `/{id}/publish` | `publish_news` |
| `app/api/offers/create.py:24` | POST | `/applications/{id}/offer` | `create_offer` |
| `app/api/offers/create.py:47` | POST | `/applications/{id}/convert` | `convert_candidate` |
| `app/api/offers/read.py:22` | GET | `` | `list_offers` |
| `app/api/offers/status.py:23` | PATCH | `/{id}/accept` | `accept_offer` |
| `app/api/offers/status.py:43` | PATCH | `/{id}/reject` | `reject_offer` |
| `app/api/onboarding.py:122` | GET | `/status` | `get_onboarding_status` |
| `app/api/onboarding.py:142` | GET | `/progress` | `get_onboarding_progress` |
| `app/api/onboarding.py:161` | PUT | `/progress` | `save_onboarding_progress` |
| `app/api/onboarding.py:161` | PATCH | `/progress` | `save_onboarding_progress` |
| `app/api/onboarding.py:185` | GET | `/admin-profile` | `get_admin_profile` |
| `app/api/onboarding.py:185` | GET | `/profile` | `get_admin_profile` |
| `app/api/onboarding.py:206` | POST | `/admin-profile` | `save_admin_profile` |
| `app/api/onboarding.py:206` | PUT | `/admin-profile` | `save_admin_profile` |
| `app/api/onboarding.py:206` | POST | `/profile` | `save_admin_profile` |
| `app/api/onboarding.py:206` | PUT | `/profile` | `save_admin_profile` |
| `app/api/onboarding.py:230` | GET | `/company` | `get_company_details` |
| `app/api/onboarding.py:230` | GET | `/organization` | `get_company_details` |
| `app/api/onboarding.py:251` | POST | `/company` | `save_company_details` |
| `app/api/onboarding.py:251` | PUT | `/company` | `save_company_details` |
| `app/api/onboarding.py:251` | POST | `/organization` | `save_company_details` |
| `app/api/onboarding.py:251` | PUT | `/organization` | `save_company_details` |
| `app/api/onboarding.py:292` | POST | `/departments` | `create_department_or_list` |
| `app/api/onboarding.py:332` | GET | `/departments` | `list_departments` |
| `app/api/onboarding.py:350` | GET | `/departments/{department_id}` | `get_department` |
| `app/api/onboarding.py:364` | PUT | `/departments/{department_id}` | `update_department` |
| `app/api/onboarding.py:364` | PATCH | `/departments/{department_id}` | `update_department` |
| `app/api/onboarding.py:378` | DELETE | `/departments/{department_id}` | `delete_department` |
| `app/api/onboarding.py:395` | POST | `/designations` | `create_designation_or_list` |
| `app/api/onboarding.py:433` | GET | `/designations` | `list_designations` |
| `app/api/onboarding.py:451` | GET | `/designations/{designation_id}` | `get_designation` |
| `app/api/onboarding.py:465` | PUT | `/designations/{designation_id}` | `update_designation` |
| `app/api/onboarding.py:465` | PATCH | `/designations/{designation_id}` | `update_designation` |
| `app/api/onboarding.py:479` | DELETE | `/designations/{designation_id}` | `delete_designation` |
| `app/api/onboarding.py:498` | GET | `/hr-settings` | `get_hr_settings` |
| `app/api/onboarding.py:498` | GET | `/settings` | `get_hr_settings` |
| `app/api/onboarding.py:498` | GET | `/work-schedule` | `get_hr_settings` |
| `app/api/onboarding.py:521` | POST | `/hr-settings` | `save_hr_settings` |
| `app/api/onboarding.py:521` | PUT | `/hr-settings` | `save_hr_settings` |
| `app/api/onboarding.py:521` | POST | `/settings` | `save_hr_settings` |
| `app/api/onboarding.py:521` | PUT | `/settings` | `save_hr_settings` |
| `app/api/onboarding.py:521` | POST | `/work-schedule` | `save_hr_settings` |
| `app/api/onboarding.py:521` | PUT | `/work-schedule` | `save_hr_settings` |
| `app/api/onboarding.py:544` | POST | `/leave-policies` | `create_leave_policy` |
| `app/api/onboarding.py:563` | GET | `/leave-policies` | `list_leave_policies` |
| `app/api/onboarding.py:581` | GET | `/leave-policies/{policy_id}` | `get_leave_policy` |
| `app/api/onboarding.py:595` | PUT | `/leave-policies/{policy_id}` | `update_leave_policy` |
| `app/api/onboarding.py:595` | PATCH | `/leave-policies/{policy_id}` | `update_leave_policy` |
| `app/api/onboarding.py:609` | DELETE | `/leave-policies/{policy_id}` | `delete_leave_policy` |
| `app/api/onboarding.py:627` | POST | `/invitations` | `send_individual_invitation` |
| `app/api/onboarding.py:627` | POST | `/invite-employee` | `send_individual_invitation` |
| `app/api/onboarding.py:646` | POST | `/invite-employees` | `invite_employees_batch_step` |
| `app/api/onboarding.py:682` | GET | `/invitations` | `list_pending_invitations` |
| `app/api/onboarding.py:682` | GET | `/invitations/pending` | `list_pending_invitations` |
| `app/api/onboarding.py:700` | POST | `/invitations/{invitation_id}/resend` | `resend_invitation` |
| `app/api/onboarding.py:720` | POST | `/invitations/{invitation_id}/cancel` | `cancel_invitation` |
| `app/api/onboarding.py:720` | DELETE | `/invitations/{invitation_id}` | `cancel_invitation` |
| `app/api/onboarding.py:745` | GET | `/structure` | `get_organization_structure` |
| `app/api/onboarding.py:745` | GET | `/review` | `get_organization_structure` |
| `app/api/onboarding.py:745` | GET | `/organization/structure` | `get_organization_structure` |
| `app/api/onboarding.py:763` | POST | `/complete` | `complete_onboarding` |
| `app/api/onboarding.py:790` | POST | `/upload` | `upload_onboarding_asset` |
| `app/api/onboarding.py:857` | GET | `/validate` | `validate_onboarding_token_alias` |
| `app/api/onboarding.py:872` | GET | `/validate-token` | `validate_onboarding_token` |
| `app/api/onboarding.py:896` | POST | `/activate` | `activate_onboarding_employee` |
| `app/api/payments.py:144` | GET | `/plans` | `get_plans` |
| `app/api/payments.py:160` | POST | `/create-order` | `create_order` |
| `app/api/payments.py:263` | POST | `/verify` | `verify_payment` |
| `app/api/payments.py:411` | POST | `/webhook` | `handle_razorpay_webhook` |
| `app/api/payments.py:520` | GET | `/history` | `get_payment_history` |
| `app/api/payments.py:590` | GET | `/{payment_id}` | `get_payment_details` |
| `app/api/payroll/routes/advances.py:24` | GET | `/advances` | `list_loans` |
| `app/api/payroll/routes/advances.py:24` | GET | `/loans` | `list_loans` |
| `app/api/payroll/routes/advances.py:36` | POST | `/advances` | `create_loan` |
| `app/api/payroll/routes/advances.py:48` | POST | `/advances/{loan_id}/approve` | `approve_loan` |
| `app/api/payroll/routes/advances.py:60` | POST | `/advances/{loan_id}/reject` | `reject_loan` |
| `app/api/payroll/routes/advances.py:72` | POST | `/advances/copilot` | `copilot_chat` |
| `app/api/payroll/routes/allowances.py:65` | GET | `/allowances` | `list_allowances` |
| `app/api/payroll/routes/allowances.py:65` | HEAD | `/allowances` | `list_allowances` |
| `app/api/payroll/routes/allowances.py:77` | GET | `/allowances/audit` | `get_allowance_audit` |
| `app/api/payroll/routes/allowances.py:87` | GET | `/allowances/history` | `get_allowance_history` |
| `app/api/payroll/routes/allowances.py:97` | GET | `/allowances/export` | `export_allowances` |
| `app/api/payroll/routes/allowances.py:108` | GET | `/allowances/{allowance_id}` | `get_allowance_details` |
| `app/api/payroll/routes/allowances.py:121` | POST | `/allowances` | `create_allowance` |
| `app/api/payroll/routes/allowances.py:147` | PUT | `/allowances/{allowance_id}` | `update_allowance` |
| `app/api/payroll/routes/allowances.py:147` | PATCH | `/allowances/{allowance_id}` | `update_allowance` |
| `app/api/payroll/routes/allowances.py:173` | DELETE | `/allowances/{allowance_id}` | `delete_allowance` |
| `app/api/payroll/routes/allowances.py:189` | POST | `/allowances/{allowance_id}/duplicate` | `duplicate_allowance` |
| `app/api/payroll/routes/allowances.py:202` | POST | `/allowances/{allowance_id}/activate` | `activate_allowance` |
| `app/api/payroll/routes/allowances.py:215` | POST | `/allowances/{allowance_id}/deactivate` | `deactivate_allowance` |
| `app/api/payroll/routes/bank_transfer.py:29` | GET | `/bank-transfers` | `list_bank_transfers` |
| `app/api/payroll/routes/bank_transfer.py:29` | GET | `/bank/disbursements` | `list_bank_transfers` |
| `app/api/payroll/routes/bank_transfer.py:44` | GET | `/bank-transfers/dashboard` | `get_dashboard_metrics` |
| `app/api/payroll/routes/bank_transfer.py:55` | GET | `/bank-transfers/audit` | `get_audit_logs` |
| `app/api/payroll/routes/bank_transfer.py:66` | GET | `/bank-transfers/{transfer_id}` | `get_transfer_detail` |
| `app/api/payroll/routes/bank_transfer.py:78` | POST | `/bank-transfers/batch` | `create_transfer_batch` |
| `app/api/payroll/routes/bank_transfer.py:90` | POST | `/bank-transfers/generate-file` | `generate_bank_file` |
| `app/api/payroll/routes/bank_transfer.py:102` | POST | `/bank-transfers/initiate` | `initiate_payments` |
| `app/api/payroll/routes/bank_transfer.py:113` | POST | `/bank-transfers/reconcile` | `reconcile_payments` |
| `app/api/payroll/routes/bank_transfer.py:124` | POST | `/bank-transfers/{transfer_id}/retry` | `retry_transfer` |
| `app/api/payroll/routes/bank_transfer.py:136` | POST | `/bank-transfers/{transfer_id}/mark-paid` | `mark_as_paid` |
| `app/api/payroll/routes/bonuses.py:23` | GET | `/bonus/plans` | `list_bonus_plans` |
| `app/api/payroll/routes/bonuses.py:34` | GET | `/bonuses` | `list_bonuses` |
| `app/api/payroll/routes/bonuses.py:49` | POST | `/bonuses` | `create_bonus` |
| `app/api/payroll/routes/bonuses.py:61` | POST | `/bonuses/{bonus_id}/approve` | `approve_bonus` |
| `app/api/payroll/routes/bonuses.py:73` | POST | `/bonuses/{bonus_id}/reject` | `reject_bonus` |
| `app/api/payroll/routes/bonuses.py:85` | POST | `/bonuses/copilot` | `copilot_chat` |
| `app/api/payroll/routes/compliance.py:17` | GET | `/compliance/config` | `get_statutory_config` |
| `app/api/payroll/routes/compliance.py:17` | HEAD | `/compliance/config` | `get_statutory_config` |
| `app/api/payroll/routes/compliance.py:31` | GET | `/compliance/dashboard` | `get_compliance_dashboard` |
| `app/api/payroll/routes/compliance.py:31` | GET | `/compliance` | `get_compliance_dashboard` |
| `app/api/payroll/routes/compliance.py:31` | HEAD | `/compliance/dashboard` | `get_compliance_dashboard` |
| `app/api/payroll/routes/compliance.py:31` | HEAD | `/compliance` | `get_compliance_dashboard` |
| `app/api/payroll/routes/compliance_full.py:49` | GET | `/compliance/rules` | `list_compliance_rules` |
| `app/api/payroll/routes/compliance_full.py:49` | HEAD | `/compliance/rules` | `list_compliance_rules` |
| `app/api/payroll/routes/compliance_full.py:61` | GET | `/compliance/audit` | `get_compliance_audit` |
| `app/api/payroll/routes/compliance_full.py:71` | GET | `/compliance/history` | `get_compliance_history` |
| `app/api/payroll/routes/compliance_full.py:81` | GET | `/compliance/calendar` | `get_compliance_calendar` |
| `app/api/payroll/routes/compliance_full.py:96` | POST | `/compliance/validate` | `validate_statutory_compliance` |
| `app/api/payroll/routes/compliance_full.py:107` | POST | `/compliance/challan` | `generate_statutory_challan` |
| `app/api/payroll/routes/compliance_full.py:131` | GET | `/compliance/{rule_id}` | `get_compliance_rule_details` |
| `app/api/payroll/routes/compliance_full.py:144` | POST | `/compliance` | `create_compliance_rule` |
| `app/api/payroll/routes/components.py:61` | GET | `/components` | `list_salary_components` |
| `app/api/payroll/routes/components.py:61` | HEAD | `/components` | `list_salary_components` |
| `app/api/payroll/routes/components.py:73` | GET | `/components/audit` | `get_salary_component_audit` |
| `app/api/payroll/routes/components.py:83` | GET | `/components/history` | `get_salary_component_history` |
| `app/api/payroll/routes/components.py:93` | GET | `/components/{component_id}` | `get_salary_component_details` |
| `app/api/payroll/routes/components.py:106` | POST | `/components` | `create_salary_component` |
| `app/api/payroll/routes/components.py:132` | PUT | `/components/{component_id}` | `update_salary_component` |
| `app/api/payroll/routes/components.py:132` | PATCH | `/components/{component_id}` | `update_salary_component` |
| `app/api/payroll/routes/components.py:158` | DELETE | `/components/{component_id}` | `delete_salary_component` |
| `app/api/payroll/routes/components.py:174` | POST | `/components/{component_id}/duplicate` | `duplicate_salary_component` |
| `app/api/payroll/routes/components.py:187` | POST | `/components/{component_id}/activate` | `activate_salary_component` |
| `app/api/payroll/routes/components.py:200` | POST | `/components/{component_id}/deactivate` | `deactivate_salary_component` |
| `app/api/payroll/routes/components.py:213` | POST | `/components/reorder` | `reorder_salary_components` |
| `app/api/payroll/routes/copilot.py:412` | GET | `/copilot/chat` | `get_payroll_copilot_chat` |
| `app/api/payroll/routes/copilot.py:430` | POST | `/copilot/chat` | `payroll_copilot_chat` |
| `app/api/payroll/routes/copilot.py:478` | GET | `/copilot/history` | `get_payroll_copilot_history` |
| `app/api/payroll/routes/copilot.py:495` | POST | `/copilot/clear` | `clear_payroll_copilot_history` |
| `app/api/payroll/routes/dashboard.py:17` | GET | `/dashboard` | `get_payroll_dashboard` |
| `app/api/payroll/routes/deductions.py:19` | GET | `/deductions` | `list_deductions` |
| `app/api/payroll/routes/deductions.py:19` | HEAD | `/deductions` | `list_deductions` |
| `app/api/payroll/routes/overtime.py:23` | GET | `/overtime` | `list_overtime` |
| `app/api/payroll/routes/overtime.py:35` | POST | `/overtime` | `create_overtime` |
| `app/api/payroll/routes/overtime.py:47` | POST | `/overtime/{overtime_id}/approve` | `approve_overtime` |
| `app/api/payroll/routes/overtime.py:59` | POST | `/overtime/{overtime_id}/reject` | `reject_overtime` |
| `app/api/payroll/routes/overtime.py:71` | POST | `/overtime/copilot` | `copilot_chat` |
| `app/api/payroll/routes/overtime_settings.py:52` | GET | `/overtime/settings` | `get_overtime_settings` |
| `app/api/payroll/routes/overtime_settings.py:52` | HEAD | `/overtime/settings` | `get_overtime_settings` |
| `app/api/payroll/routes/overtime_settings.py:62` | PUT | `/overtime/settings` | `update_overtime_settings` |
| `app/api/payroll/routes/overtime_settings.py:87` | POST | `/overtime/calculate` | `calculate_overtime` |
| `app/api/payroll/routes/overtime_settings.py:105` | POST | `/overtime/request` | `create_overtime_request` |
| `app/api/payroll/routes/overtime_settings.py:123` | GET | `/overtime/history` | `get_overtime_history` |
| `app/api/payroll/routes/overtime_settings.py:133` | GET | `/overtime/audit` | `get_overtime_audit` |
| `app/api/payroll/routes/pay_cycles.py:50` | GET | `/cycles` | `list_payroll_cycles` |
| `app/api/payroll/routes/pay_cycles.py:50` | HEAD | `/cycles` | `list_payroll_cycles` |
| `app/api/payroll/routes/pay_cycles.py:69` | GET | `/cycles/logs` | `get_payroll_cycle_logs` |
| `app/api/payroll/routes/pay_cycles.py:79` | GET | `/cycles/history` | `get_payroll_cycle_history` |
| `app/api/payroll/routes/pay_cycles.py:89` | GET | `/cycles/{cycle_id}` | `get_payroll_cycle_details` |
| `app/api/payroll/routes/pay_cycles.py:100` | POST | `/cycles` | `create_payroll_cycle` |
| `app/api/payroll/routes/pay_cycles.py:131` | PUT | `/cycles/{cycle_id}` | `update_payroll_cycle` |
| `app/api/payroll/routes/pay_cycles.py:131` | PATCH | `/cycles/{cycle_id}` | `update_payroll_cycle` |
| `app/api/payroll/routes/pay_cycles.py:154` | DELETE | `/cycles/{cycle_id}` | `delete_payroll_cycle` |
| `app/api/payroll/routes/pay_cycles.py:169` | POST | `/cycles/{cycle_id}/lock` | `lock_payroll_cycle` |
| `app/api/payroll/routes/pay_cycles.py:184` | POST | `/cycles/{cycle_id}/unlock` | `unlock_payroll_cycle` |
| `app/api/payroll/routes/pay_cycles.py:201` | POST | `/cycles/{cycle_id}/void` | `void_payroll_cycle` |
| `app/api/payroll/routes/payslips.py:186` | GET | `/payslips` | `list_payslips` |
| `app/api/payroll/routes/payslips.py:186` | GET | `/admin/payslips` | `list_payslips` |
| `app/api/payroll/routes/payslips.py:186` | HEAD | `/payslips` | `list_payslips` |
| `app/api/payroll/routes/payslips.py:186` | HEAD | `/admin/payslips` | `list_payslips` |
| `app/api/payroll/routes/payslips.py:340` | GET | `/payslips/{payslip_id}/preview` | `get_payslip_preview` |
| `app/api/payroll/routes/payslips.py:429` | POST | `/payslips/bulk-generate` | `bulk_generate_payslips` |
| `app/api/payroll/routes/payslips.py:505` | POST | `/payslips/bulk-email` | `bulk_email_payslips` |
| `app/api/payroll/routes/payslips.py:537` | POST | `/payslips/bulk-download` | `bulk_download_payslips` |
| `app/api/payroll/routes/payslips.py:574` | GET | `/payslips/{payslip_id}/pdf` | `download_payslip_pdf` |
| `app/api/payroll/routes/payslips.py:600` | POST | `/payslips/{payslip_id}/email` | `email_single_payslip` |
| `app/api/payroll/routes/payslips.py:622` | POST | `/payslips/{payslip_id}/regenerate` | `regenerate_single_payslip` |
| `app/api/payroll/routes/payslips.py:643` | DELETE | `/payslips/{payslip_id}` | `delete_payslip` |
| `app/api/payroll/routes/payslips.py:664` | GET | `/payslips/{payslip_id}/audit-logs` | `get_payslip_audit_logs` |
| `app/api/payroll/routes/payslips.py:719` | GET | `/payslips/{payslip_id}` | `get_payslip` |
| `app/api/payroll/routes/reimbursements.py:33` | GET | `/reimbursements` | `list_reimbursements` |
| `app/api/payroll/routes/reimbursements.py:45` | POST | `/reimbursements` | `create_reimbursement` |
| `app/api/payroll/routes/reimbursements.py:57` | POST | `/reimbursements/{claim_id}/approve` | `approve_reimbursement` |
| `app/api/payroll/routes/reimbursements.py:69` | POST | `/reimbursements/{claim_id}/reject` | `reject_reimbursement` |
| `app/api/payroll/routes/reimbursements.py:81` | POST | `/reimbursements/bulk-approve` | `bulk_approve_reimbursements` |
| `app/api/payroll/routes/reimbursements.py:94` | GET | `/reimbursements/audit-logs` | `get_audit_logs` |
| `app/api/payroll/routes/reimbursements.py:105` | GET | `/reimbursements/ai-insights` | `get_ai_insights` |
| `app/api/payroll/routes/reimbursements.py:116` | POST | `/reimbursements/copilot` | `copilot_chat` |
| `app/api/payroll/routes/salary_processing.py:24` | GET | `/salary-processing` | `get_salary_processing_list` |
| `app/api/payroll/routes/salary_processing.py:72` | GET | `/salary-processing/hero` | `get_salary_processing_hero` |
| `app/api/payroll/routes/salary_processing.py:85` | GET | `/salary-processing/kpis` | `get_salary_processing_kpis` |
| `app/api/payroll/routes/salary_processing.py:119` | GET | `/salary-processing/approval-workflow` | `get_salary_processing_approval_workflow` |
| `app/api/payroll/routes/salary_processing.py:159` | GET | `/salary-processing/ai-insights` | `get_salary_processing_ai_insights` |
| `app/api/payroll/routes/salary_processing.py:215` | GET | `/salary-processing/validations` | `get_salary_processing_validations` |
| `app/api/payroll/routes/salary_processing.py:260` | GET | `/salary-processing/analytics` | `get_salary_processing_analytics` |
| `app/api/payroll/routes/salary_processing.py:312` | POST | `/salary-processing/run` | `trigger_salary_processing_run` |
| `app/api/payroll/routes/salary_processing.py:320` | POST | `/salary-processing/approve` | `approve_salary_processing` |
| `app/api/payroll/routes/salary_processing.py:331` | POST | `/salary-processing/rollback` | `rollback_salary_processing` |
| `app/api/payroll/routes/salary_processing.py:339` | POST | `/salary-processing/recalculate/{employee_id}` | `recalculate_employee_salary` |
| `app/api/payroll/routes/salary_processing.py:347` | POST | `/salary-processing/resolve-exception/{exception_id}` | `resolve_salary_exception` |
| `app/api/payroll/routes/salary_processing.py:355` | POST | `/salary-processing/auto-fix` | `auto_fix_salary_processing` |
| `app/api/payroll/routes/salary_processing.py:363` | POST | `/salary-processing/batch-payout` | `batch_payout_salary_processing` |
| `app/api/payroll/routes/salary_processing.py:371` | POST | `/salary-processing/batch-approve` | `batch_approve_salary_processing` |
| `app/api/payroll/routes/salary_processing.py:379` | POST | `/salary-processing/batch-recalculate` | `batch_recalculate_salary_processing` |
| `app/api/payroll/routes/salary_processing.py:387` | POST | `/salary-processing/payslips` | `generate_payslips_for_processing` |
| `app/api/payroll/routes/salary_processing.py:395` | POST | `/salary-processing/bank-transfer` | `initiate_bank_transfer_from_processing` |
| `app/api/payroll/routes/salary_processing.py:403` | POST | `/salary-processing/export` | `export_salary_processing` |
| `app/api/payroll/routes/salary_structure.py:21` | GET | `/employees/{employee_id}/salary-structure` | `get_employee_salary_structure` |
| `app/api/payroll/routes/salary_structure.py:33` | GET | `/salary-structures` | `list_salary_structures_alias` |
| `app/api/payroll/routes/salary_structure.py:57` | GET | `/salary-structures/audit` | `get_salary_structures_audit` |
| `app/api/payroll/routes/salary_structure.py:64` | GET | `/salary-structures/ai-insights` | `get_salary_structures_ai_insights` |
| `app/api/payroll/routes/salary_structure.py:95` | GET | `/salary-structures/{structure_id}` | `get_salary_structure_by_id` |
| `app/api/payroll/routes/salary_structure.py:129` | POST | `/salary-structures` | `create_salary_structure` |
| `app/api/payroll/routes/salary_structure.py:143` | PUT | `/salary-structures/{structure_id}` | `update_salary_structure` |
| `app/api/payroll/routes/salary_structure.py:156` | POST | `/salary-structures/{structure_id}/clone` | `clone_salary_structure` |
| `app/api/payroll/routes/salary_structure.py:169` | POST | `/salary-structures/{structure_id}/assign` | `assign_salary_structure` |
| `app/api/payroll/routes/salary_structure.py:181` | POST | `/salary-structures/{structure_id}/approve` | `approve_salary_structure` |
| `app/api/payroll/routes/salary_structure.py:194` | POST | `/salary-structures/{structure_id}/rollback` | `rollback_salary_structure_version` |
| `app/api/payroll/routes/security_settings.py:25` | GET | `/roles` | `list_security_roles` |
| `app/api/payroll/routes/security_settings.py:25` | HEAD | `/roles` | `list_security_roles` |
| `app/api/payroll/routes/security_settings.py:36` | GET | `/policies` | `get_security_policy` |
| `app/api/payroll/routes/security_settings.py:36` | HEAD | `/policies` | `get_security_policy` |
| `app/api/payroll/routes/security_settings.py:46` | PUT | `/policies` | `update_security_policy` |
| `app/api/payroll/routes/security_settings.py:58` | GET | `/sessions` | `get_active_sessions` |
| `app/api/payroll/routes/security_settings.py:68` | DELETE | `/sessions/{session_id}` | `revoke_user_session` |
| `app/api/payroll/routes/security_settings.py:82` | POST | `/logout-all` | `force_logout_all` |
| `app/api/payroll/routes/security_settings.py:93` | GET | `/ip-whitelist` | `get_ip_whitelist` |
| `app/api/payroll/routes/security_settings.py:103` | POST | `/ip-whitelist` | `add_ip_whitelist` |
| `app/api/payroll/routes/security_settings.py:115` | DELETE | `/ip-whitelist/{ip_id}` | `delete_ip_whitelist` |
| `app/api/payroll/routes/security_settings.py:129` | GET | `/audit` | `get_security_audit` |
| `app/api/payroll/routes/settings.py:90` | GET | `/settings` | `get_payroll_settings` |
| `app/api/payroll/routes/settings.py:90` | HEAD | `/settings` | `get_payroll_settings` |
| `app/api/payroll/routes/settings.py:103` | PUT | `/settings` | `update_payroll_settings` |
| `app/api/payroll/routes/settings.py:103` | POST | `/settings` | `update_payroll_settings` |
| `app/api/payroll/routes/settings.py:103` | PATCH | `/settings` | `update_payroll_settings` |
| `app/api/payroll/routes/settings.py:140` | GET | `/settings/history` | `get_settings_history` |
| `app/api/payroll/routes/settings.py:150` | GET | `/settings/audit` | `get_settings_audit` |
| `app/api/payroll/routes/settings.py:160` | POST | `/settings/reset` | `reset_payroll_settings` |
| `app/api/payroll/routes/settings.py:173` | POST | `/settings/test` | `test_payroll_settings` |
| `app/api/payroll/routes/settings.py:192` | GET | `/settings/export` | `export_payroll_settings` |
| `app/api/payroll/routes/tax.py:24` | GET | `/admin/tax` | `get_tax_management_records` |
| `app/api/payroll/routes/tax.py:24` | GET | `/tax` | `get_tax_management_records` |
| `app/api/payroll/routes/tax.py:24` | HEAD | `/admin/tax` | `get_tax_management_records` |
| `app/api/payroll/routes/tax.py:24` | HEAD | `/tax` | `get_tax_management_records` |
| `app/api/payroll/routes/tax_settings.py:65` | GET | `/taxes` | `list_tax_settings` |
| `app/api/payroll/routes/tax_settings.py:65` | HEAD | `/taxes` | `list_tax_settings` |
| `app/api/payroll/routes/tax_settings.py:77` | GET | `/taxes/audit` | `get_tax_audit` |
| `app/api/payroll/routes/tax_settings.py:87` | GET | `/taxes/history` | `get_tax_history` |
| `app/api/payroll/routes/tax_settings.py:97` | GET | `/taxes/export` | `export_tax_settings` |
| `app/api/payroll/routes/tax_settings.py:108` | POST | `/taxes/import` | `import_tax_settings` |
| `app/api/payroll/routes/tax_settings.py:120` | POST | `/taxes/recalculate` | `recalculate_tax_liabilities` |
| `app/api/payroll/routes/tax_settings.py:133` | GET | `/taxes/{tax_id}` | `get_tax_details` |
| `app/api/payroll/routes/tax_settings.py:146` | POST | `/taxes` | `create_tax_setting` |
| `app/api/payroll/routes/tax_settings.py:172` | PUT | `/taxes/{tax_id}` | `update_tax_setting` |
| `app/api/payroll/routes/tax_settings.py:172` | PATCH | `/taxes/{tax_id}` | `update_tax_setting` |
| `app/api/payroll/routes/tax_settings.py:198` | DELETE | `/taxes/{tax_id}` | `delete_tax_setting` |
| `app/api/payroll/routes/tax_settings.py:211` | POST | `/taxes/{tax_id}/activate` | `activate_tax_setting` |
| `app/api/payroll/routes/tax_settings.py:224` | POST | `/taxes/{tax_id}/deactivate` | `deactivate_tax_setting` |
| `app/api/payroll/routes/templates_full.py:49` | GET | `/templates` | `list_payroll_templates` |
| `app/api/payroll/routes/templates_full.py:49` | HEAD | `/templates` | `list_payroll_templates` |
| `app/api/payroll/routes/templates_full.py:61` | GET | `/templates/audit` | `get_template_audit` |
| `app/api/payroll/routes/templates_full.py:71` | GET | `/templates/history` | `get_template_history` |
| `app/api/payroll/routes/templates_full.py:81` | GET | `/templates/{template_id}` | `get_template_details` |
| `app/api/payroll/routes/templates_full.py:94` | POST | `/templates` | `create_template` |
| `app/api/payroll/routes/templates_full.py:120` | PUT | `/templates/{template_id}` | `update_template` |
| `app/api/payroll/routes/templates_full.py:120` | PATCH | `/templates/{template_id}` | `update_template` |
| `app/api/payroll/routes/templates_full.py:146` | POST | `/templates/{template_id}/duplicate` | `duplicate_template` |
| `app/api/payroll/routes/templates_full.py:159` | POST | `/templates/{template_id}/preview` | `preview_template` |
| `app/api/payroll/routes/templates_full.py:174` | POST | `/templates/{template_id}/publish` | `publish_template` |
| `app/api/payroll/routes/templates_full.py:189` | POST | `/templates/{template_id}/archive` | `archive_template` |
| `app/api/polls.py:26` | POST | `` | `create_poll` |
| `app/api/polls.py:47` | GET | `` | `list_polls` |
| `app/api/polls.py:67` | GET | `/{id}` | `get_poll` |
| `app/api/polls.py:87` | POST | `/{id}/vote` | `cast_vote` |
| `app/api/polls.py:109` | PATCH | `/{id}/close` | `close_poll` |
| `app/api/polls.py:130` | DELETE | `/{id}` | `delete_poll` |
| `app/api/recruitment.py:68` | POST | `/resume/upload` | `upload_and_screen_resume` |
| `app/api/recruitment.py:68` | POST | `/resumes/upload` | `upload_and_screen_resume` |
| `app/api/recruitment.py:94` | POST | `/resumes/parse` | `parse_resume_direct` |
| `app/api/recruitment.py:122` | GET | `/candidates` | `list_parsed_candidates` |
| `app/api/recruitment.py:163` | GET | `/candidates/{candidate_id}` | `get_candidate_profile` |
| `app/api/recruitment.py:184` | GET | `/candidates/{candidate_id}/ats` | `get_candidate_ats_analysis` |
| `app/api/recruitment.py:205` | POST | `/candidates/{candidate_id}/match/{job_id}` | `match_candidate_against_job` |
| `app/api/recruitment.py:227` | POST | `/jobs/{job_id}/match` | `match_candidates_for_job` |
| `app/api/recruitment.py:248` | POST | `/jobs/generate-description` | `generate_recruitment_job_description` |
| `app/api/recruitment.py:291` | POST | `/jobs/modify-description` | `modify_recruitment_job_description` |
| `app/api/recruitment.py:332` | POST | `/integrations/{provider}/connections` | `configure_recruitment_provider` |
| `app/api/recruitment.py:344` | POST | `/integrations/{provider}/jobs/{job_id}/sync` | `sync_recruitment_job` |
| `app/api/recruitment.py:354` | POST | `/integrations/{tenant_id}/webhooks/{provider}` | `recruitment_provider_webhook` |
| `app/api/recruitment.py:369` | GET | `/integrations/analytics` | `recruitment_source_analytics` |
| `app/api/recruitment_analytics.py:32` | GET | `/analytics` | `get_analytics` |
| `app/api/recruitment_analytics.py:32` | GET | `/recruitment-analytics` | `get_analytics` |
| `app/api/recruitment_analytics.py:91` | GET | `/stats` | `get_recruitment_dashboard_stats` |
| `app/api/recruitment_analytics.py:91` | GET | `/dashboard` | `get_recruitment_dashboard_stats` |
| `app/api/recruitment_analytics.py:91` | GET | `/summary` | `get_recruitment_dashboard_stats` |
| `app/api/recruitment_analytics.py:117` | GET | `/notifications` | `list_notifications` |
| `app/api/recruitment_analytics.py:138` | PUT | `/notifications/{id}/read` | `mark_read` |
| `app/api/referrals.py:31` | POST | `` | `create_referral` |
| `app/api/referrals.py:52` | GET | `` | `list_referrals` |
| `app/api/referrals.py:74` | PUT | `/{id}/status` | `update_referral_status` |
| `app/api/requisitions/create.py:28` | POST | `` | `create_requisition` |
| `app/api/requisitions/create.py:50` | POST | `/{id}/approve` | `approve_requisition` |
| `app/api/requisitions/read.py:24` | GET | `/{id}` | `get_requisition` |
| `app/api/requisitions/read.py:45` | GET | `` | `list_requisitions` |
| `app/api/scorecards.py:27` | POST | `/templates` | `create_scorecard_template` |
| `app/api/scorecards.py:48` | GET | `/templates` | `list_scorecard_templates` |
| `app/api/scorecards.py:69` | POST | `/submissions` | `submit_scorecard` |
| `app/api/scorecards.py:91` | GET | `/submissions/{round_id}` | `get_scorecards` |
| `app/api/settings.py:153` | GET | `/summary` | `get_settings_summary` |
| `app/api/settings.py:213` | GET | `/general` | `get_general_settings` |
| `app/api/settings.py:250` | PUT | `/general` | `update_general_settings` |
| `app/api/settings.py:292` | GET | `/company` | `get_company_settings` |
| `app/api/settings.py:340` | PUT | `/company` | `update_company_settings` |
| `app/api/settings.py:340` | POST | `/company` | `update_company_settings` |
| `app/api/settings.py:340` | PATCH | `/company` | `update_company_settings` |
| `app/api/settings.py:416` | POST | `/company/logo` | `upload_company_logo` |
| `app/api/settings.py:500` | GET | `/roles` | `get_roles` |
| `app/api/settings.py:566` | POST | `/roles` | `create_role` |
| `app/api/settings.py:622` | PUT | `/roles/{role_id}` | `update_role` |
| `app/api/settings.py:676` | DELETE | `/roles/{role_id}` | `delete_role` |
| `app/api/settings.py:722` | GET | `/permissions` | `get_permissions` |
| `app/api/settings.py:744` | GET | `/audit-logs` | `get_audit_logs` |
| `app/api/settings.py:824` | GET | `/billing` | `get_billing` |
| `app/api/settings.py:869` | PUT | `/billing` | `update_billing` |
| `app/api/settings.py:920` | GET | `/security` | `get_security` |
| `app/api/settings.py:982` | PUT | `/security` | `update_security` |
| `app/api/settings.py:1029` | GET | `/notifications` | `get_notifications` |
| `app/api/settings.py:1067` | PUT | `/notifications` | `update_notifications` |
| `app/api/settings.py:1067` | PATCH | `/notifications` | `update_notifications` |
| `app/api/settings.py:1118` | GET | `/integrations` | `get_integrations` |
| `app/api/settings.py:1153` | PUT | `/integrations` | `toggle_integration` |
| `app/api/settings.py:1206` | GET | `/profile` | `get_profile` |
| `app/api/settings.py:1260` | PUT | `/profile` | `update_profile` |
| `app/api/settings.py:1336` | GET | `/hr` | `get_hr_settings` |
| `app/api/settings.py:1391` | PUT | `/hr` | `update_hr_settings` |
| `app/api/settings.py:1391` | POST | `/hr` | `update_hr_settings` |
| `app/api/settings.py:1484` | GET | `/employees` | `get_employee_settings` |
| `app/api/settings.py:1531` | PUT | `/employees` | `update_employee_settings` |
| `app/api/settings.py:1588` | GET | `/leaves` | `get_leave_settings` |
| `app/api/settings.py:1642` | PUT | `/leaves` | `update_leave_settings` |
| `app/api/settings.py:1700` | GET | `/documents` | `get_document_settings` |
| `app/api/settings.py:1755` | PUT | `/documents` | `update_document_settings` |
| `app/api/settings.py:1813` | GET | `/assets` | `get_asset_settings` |
| `app/api/settings.py:1867` | PUT | `/assets` | `update_asset_settings` |
| `app/api/settings.py:1924` | POST | `/mfa/enable` | `enable_mfa` |
| `app/api/settings.py:2025` | POST | `/mfa/disable` | `disable_mfa` |
| `app/api/settings.py:2078` | GET | `/mfa/status` | `get_mfa_status` |
| `app/api/settings.py:2105` | POST | `/mfa/verify` | `verify_mfa` |
| `app/api/sidebar.py:170` | GET | `/permissions` | `get_sidebar_permissions` |
| `app/api/sidebar.py:170` | GET | `/permissions/` | `get_sidebar_permissions` |
| `app/api/sidebar.py:170` | GET | `` | `get_sidebar_permissions` |
| `app/api/super_admin.py:111` | GET | `/statistics` | `get_super_admin_statistics` |
| `app/api/super_admin.py:111` | GET | `/dashboard` | `get_super_admin_statistics` |
| `app/api/super_admin.py:354` | GET | `/organizations` | `get_super_admin_organizations` |
| `app/api/super_admin.py:537` | POST | `/organizations` | `create_super_admin_organization` |
| `app/api/super_admin.py:694` | GET | `/organizations/{org_id}` | `get_super_admin_organization_detail` |
| `app/api/super_admin.py:812` | PATCH | `/organizations/{org_id}` | `update_super_admin_organization` |
| `app/api/super_admin.py:812` | PUT | `/organizations/{org_id}` | `update_super_admin_organization` |
| `app/api/super_admin.py:938` | DELETE | `/organizations/{org_id}` | `delete_super_admin_organization` |
| `app/api/super_admin.py:985` | POST | `/organizations/{org_id}/access/grant` | `super_admin_org_access_grant` |
| `app/api/super_admin.py:1028` | POST | `/organizations/{org_id}/access/extend` | `super_admin_org_access_extend` |
| `app/api/super_admin.py:1071` | POST | `/organizations/{org_id}/access/suspend` | `super_admin_org_access_suspend` |
| `app/api/super_admin.py:1111` | POST | `/organizations/{org_id}/access/cancel` | `super_admin_org_access_cancel` |
| `app/api/super_admin.py:1151` | POST | `/organizations/{org_id}/access/reactivate` | `super_admin_org_access_reactivate` |
| `app/api/super_admin.py:1196` | GET | `/users` | `get_super_admin_users` |
| `app/api/super_admin.py:1279` | GET | `/users/{user_id}` | `get_super_admin_user_detail` |
| `app/api/super_admin.py:1307` | POST | `/users` | `create_super_admin_user` |
| `app/api/super_admin.py:1370` | PATCH | `/users/{user_id}` | `update_super_admin_user` |
| `app/api/super_admin.py:1370` | PUT | `/users/{user_id}` | `update_super_admin_user` |
| `app/api/super_admin.py:1416` | DELETE | `/users/{user_id}` | `delete_super_admin_user` |
| `app/api/super_admin.py:1447` | POST | `/users/{user_id}/activate` | `activate_super_admin_user` |
| `app/api/super_admin.py:1476` | POST | `/users/{user_id}/deactivate` | `deactivate_super_admin_user` |
| `app/api/super_admin.py:1505` | POST | `/users/{user_id}/toggle-status` | `toggle_super_admin_user_status` |
| `app/api/super_admin.py:1535` | POST | `/users/{user_id}/reset-password` | `reset_super_admin_user_password` |
| `app/api/super_admin.py:1563` | GET | `/hr-admins` | `get_super_admin_hr_admins` |
| `app/api/super_admin.py:1573` | POST | `/hr-admins` | `create_super_admin_hr_admin` |
| `app/api/super_admin.py:1583` | PATCH | `/hr-admins/{admin_id}` | `update_super_admin_hr_admin` |
| `app/api/super_admin.py:1593` | DELETE | `/hr-admins/{admin_id}` | `delete_super_admin_hr_admin` |
| `app/api/super_admin.py:1602` | POST | `/hr-admins/{admin_id}/assign` | `assign_super_admin_hr_admin` |
| `app/api/super_admin.py:1612` | POST | `/hr-admins/{admin_id}/remove-org` | `remove_super_admin_hr_admin_org` |
| `app/api/super_admin.py:1623` | GET | `/subscriptions` | `get_super_admin_subscriptions` |
| `app/api/super_admin.py:1673` | GET | `/subscriptions/{sub_id}` | `get_super_admin_subscription_detail` |
| `app/api/super_admin.py:1699` | PATCH | `/subscriptions/{sub_or_org_id}` | `update_super_admin_subscription` |
| `app/api/super_admin.py:1757` | GET | `/plans` | `get_super_admin_plans` |
| `app/api/super_admin.py:1767` | POST | `/plans` | `create_super_admin_plan` |
| `app/api/super_admin.py:1773` | PATCH | `/plans/{plan_id}` | `update_super_admin_plan` |
| `app/api/super_admin.py:1779` | DELETE | `/plans/{plan_id}` | `delete_super_admin_plan` |
| `app/api/super_admin.py:1785` | GET | `/entitlements` | `get_super_admin_entitlements` |
| `app/api/super_admin.py:1798` | PUT | `/entitlements` | `update_super_admin_entitlements` |
| `app/api/super_admin.py:1798` | PATCH | `/entitlements` | `update_super_admin_entitlements` |
| `app/api/super_admin.py:1810` | GET | `/billing` | `get_super_admin_payments` |
| `app/api/super_admin.py:1810` | GET | `/payments` | `get_super_admin_payments` |
| `app/api/super_admin.py:1841` | GET | `/security` | `get_super_admin_security` |
| `app/api/super_admin.py:1874` | GET | `/security/events` | `get_super_admin_security_events` |
| `app/api/super_admin.py:1921` | GET | `/security/alerts` | `get_super_admin_security_alerts` |
| `app/api/super_admin.py:1928` | POST | `/security/events/{event_id}/resolve` | `resolve_super_admin_security_event` |
| `app/api/super_admin.py:1942` | POST | `/security/block-ip` | `block_ip_address` |
| `app/api/super_admin.py:1959` | POST | `/security/unblock-ip` | `unblock_ip_address` |
| `app/api/super_admin.py:1976` | GET | `/security/sessions` | `get_super_admin_sessions` |
| `app/api/super_admin.py:2012` | POST | `/security/sessions/{session_id}/terminate` | `terminate_super_admin_session` |
| `app/api/super_admin.py:2037` | POST | `/security/sessions/terminate-all` | `terminate_all_super_admin_sessions` |
| `app/api/super_admin.py:2058` | GET | `/audit-logs` | `get_super_admin_audit_logs` |
| `app/api/super_admin.py:2109` | DELETE | `/audit-logs` | `clear_super_admin_audit_logs` |
| `app/api/super_admin.py:2122` | GET | `/system-health` | `get_super_admin_system_health` |
| `app/api/super_admin.py:2150` | GET | `/settings` | `get_super_admin_settings` |
| `app/api/super_admin.py:2157` | PATCH | `/settings` | `update_super_admin_settings` |
| `app/api/super_admin.py:2157` | PUT | `/settings` | `update_super_admin_settings` |
| `app/api/super_admin.py:2174` | GET | `/onboarding` | `get_super_admin_onboarding` |
| `app/api/super_admin.py:2209` | GET | `/onboarding/{org_id}` | `get_super_admin_org_onboarding` |
| `app/api/super_admin.py:2232` | POST | `/onboarding/{org_id}/fast-track` | `fast_track_super_admin_onboarding` |
| `app/api/super_admin.py:2268` | GET | `/analytics` | `get_super_admin_analytics` |
| `app/api/super_admin.py:2296` | GET | `/analytics/ai-usage` | `get_super_admin_ai_usage` |
| `app/api/super_admin.py:2309` | GET | `/announcements` | `get_super_admin_announcements` |
| `app/api/super_admin.py:2315` | POST | `/announcements` | `create_super_admin_announcement` |
| `app/api/super_admin.py:2334` | PATCH | `/announcements/{ann_id}` | `update_super_admin_announcement` |
| `app/api/super_admin.py:2344` | DELETE | `/announcements/{ann_id}` | `delete_super_admin_announcement` |
| `app/api/talent_pool.py:27` | POST | `` | `create_candidate` |
| `app/api/talent_pool.py:48` | GET | `/{id}` | `get_candidate` |
| `app/api/talent_pool.py:69` | GET | `` | `list_candidates` |
| `app/api/talent_pool.py:104` | PUT | `/{id}` | `update_candidate` |
| `app/api/talent_pool.py:126` | DELETE | `/{id}` | `delete_candidate` |
| `app/api/talent_pool.py:147` | POST | `/import` | `import_candidates` |
| `app/api/talent_pool.py:167` | GET | `/export/csv` | `export_candidates` |
| `app/api/templates.py:30` | POST | `` | `create_template` |
| `app/api/templates.py:58` | GET | `` | `list_templates` |
| `app/api/templates.py:82` | POST | `/{id}/generate` | `generate_document` |
| `app/api/timesheets.py:42` | GET | `/weekly` | `get_weekly_timesheet` |
| `app/api/timesheets.py:63` | POST | `/weekly` | `save_weekly_entries` |
| `app/api/timesheets.py:85` | POST | `/weekly/submit` | `submit_weekly_timesheet` |
| `app/api/timesheets.py:106` | GET | `/history` | `get_history` |
| `app/api/timesheets.py:126` | GET | `/pending` | `get_pending` |
| `app/api/timesheets.py:149` | POST | `/{timesheet_id}/review` | `review_timesheet` |
| `app/api/v1/admissions.py:31` | GET | `` | `list_admissions` |
| `app/api/v1/admissions.py:49` | GET | `/{admission_id}` | `get_admission` |
| `app/api/v1/admissions.py:57` | POST | `` | `create_admission` |
| `app/api/v1/admissions.py:83` | PUT | `/{admission_id}` | `update_admission` |
| `app/api/v1/admissions.py:98` | PATCH | `/{admission_id}/status` | `update_status` |
| `app/api/v1/ai.py:34` | GET | `/health` | `ai_health` |
| `app/api/v1/ai.py:117` | POST | `/chat` | `chat_message` |
| `app/api/v1/ai.py:150` | GET | `/history` | `get_history` |
| `app/api/v1/ai.py:171` | GET | `/history/{conversation_id}` | `get_conversation` |
| `app/api/v1/ai.py:193` | PATCH | `/history/{conversation_id}` | `rename_conversation` |
| `app/api/v1/ai.py:216` | DELETE | `/history/{conversation_id}` | `delete_conversation` |
| `app/api/v1/ai.py:238` | POST | `/clear` | `clear_history` |
| `app/api/v1/ai.py:259` | GET | `/suggestions` | `get_suggestions` |
| `app/api/v1/ai_attendance.py:48` | GET | `/dashboard` | `get_attendance_dashboard` |
| `app/api/v1/ai_attendance.py:77` | GET | `/trend` | `get_attendance_trend` |
| `app/api/v1/ai_attendance.py:108` | GET | `/late-arrivals` | `get_late_arrivals` |
| `app/api/v1/ai_attendance.py:137` | GET | `/anomalies` | `get_anomalies` |
| `app/api/v1/ai_attendance.py:159` | GET | `/absence-pattern` | `get_absence_patterns` |
| `app/api/v1/ai_attendance.py:181` | GET | `/overtime` | `get_overtime` |
| `app/api/v1/ai_attendance.py:203` | GET | `/shift-violations` | `get_shift_violations` |
| `app/api/v1/ai_attendance.py:225` | GET | `/health-score` | `get_health_score` |
| `app/api/v1/ai_attendance.py:247` | GET | `/watchlist` | `get_watchlist` |
| `app/api/v1/ai_brain.py:39` | POST | `/meeting-intelligence` | `ai_brain_meeting_intelligence` |
| `app/api/v1/ai_brain.py:39` | GET | `/meeting-intelligence` | `ai_brain_meeting_intelligence` |
| `app/api/v1/ai_brain.py:66` | POST | `/workforce-insights` | `ai_brain_workforce_insights` |
| `app/api/v1/ai_brain.py:66` | GET | `/workforce-insights` | `ai_brain_workforce_insights` |
| `app/api/v1/ai_brain.py:93` | POST | `/employee-health` | `ai_brain_employee_health` |
| `app/api/v1/ai_brain.py:93` | GET | `/employee-health` | `ai_brain_employee_health` |
| `app/api/v1/ai_brain.py:120` | POST | `` | `ai_brain_chat` |
| `app/api/v1/ai_brain.py:120` | GET | `` | `ai_brain_chat` |
| `app/api/v1/ai_hub/agents.py:42` | GET | `` | `list_agents` |
| `app/api/v1/ai_hub/agents.py:62` | GET | `/{agentId}` | `get_agent` |
| `app/api/v1/ai_hub/agents.py:84` | POST | `/{agentId}/run` | `run_agent` |
| `app/api/v1/ai_hub/agents.py:115` | GET | `/{agentId}/history` | `get_agent_history` |
| `app/api/v1/ai_hub/agents.py:150` | GET | `/{agentId}/status` | `get_agent_status` |
| `app/api/v1/ai_hub/agents.py:172` | POST | `/{agentId}/feedback` | `submit_agent_feedback` |
| `app/api/v1/ai_hub/analytics_center.py:45` | GET | `` | `get_overview` |
| `app/api/v1/ai_hub/analytics_center.py:80` | GET | `/attrition` | `get_attrition` |
| `app/api/v1/ai_hub/analytics_center.py:133` | GET | `/diversity` | `get_diversity` |
| `app/api/v1/ai_hub/analytics_center.py:202` | GET | `/executive-summary` | `get_executive_summary` |
| `app/api/v1/ai_hub/analytics_center.py:232` | POST | `/analyze` | `analyze_analytics` |
| `app/api/v1/ai_hub/attendance_monitor.py:40` | GET | `` | `get_overview` |
| `app/api/v1/ai_hub/attendance_monitor.py:71` | POST | `/analyze` | `analyze_attendance` |
| `app/api/v1/ai_hub/attendance_monitor.py:129` | GET | `/anomalies` | `list_anomalies` |
| `app/api/v1/ai_hub/compliance_monitor.py:41` | GET | `` | `get_overview` |
| `app/api/v1/ai_hub/compliance_monitor.py:72` | GET | `/checklist` | `get_checklist` |
| `app/api/v1/ai_hub/compliance_monitor.py:114` | GET | `/score` | `get_score` |
| `app/api/v1/ai_hub/compliance_monitor.py:152` | POST | `/scan` | `scan_compliance` |
| `app/api/v1/ai_hub/document_generator.py:40` | GET | `` | `get_overview` |
| `app/api/v1/ai_hub/document_generator.py:61` | GET | `/templates` | `list_templates` |
| `app/api/v1/ai_hub/document_generator.py:81` | POST | `/generate` | `generate_document` |
| `app/api/v1/ai_hub/document_generator.py:110` | POST | `/preview` | `preview_document` |
| `app/api/v1/ai_hub/employee_health.py:38` | GET | `` | `get_overview` |
| `app/api/v1/ai_hub/employee_health.py:68` | POST | `/analyze` | `analyze_health` |
| `app/api/v1/ai_hub/employee_health.py:111` | GET | `/wellness` | `get_wellness` |
| `app/api/v1/ai_hub/leave_assistant.py:40` | GET | `` | `get_overview` |
| `app/api/v1/ai_hub/leave_assistant.py:70` | POST | `/analyze` | `analyze_leave` |
| `app/api/v1/ai_hub/leave_assistant.py:115` | POST | `/forecast` | `forecast_leave` |
| `app/api/v1/ai_hub/meeting_intelligence.py:41` | GET | `` | `get_overview` |
| `app/api/v1/ai_hub/meeting_intelligence.py:71` | GET | `/action-items` | `list_action_items` |
| `app/api/v1/ai_hub/meeting_intelligence.py:136` | POST | `/analyze` | `analyze_meeting` |
| `app/api/v1/ai_hub/meeting_intelligence.py:186` | POST | `/summarize` | `summarize_meeting` |
| `app/api/v1/ai_hub/payroll_insights.py:41` | GET | `` | `get_overview` |
| `app/api/v1/ai_hub/payroll_insights.py:72` | POST | `/analyze` | `analyze_payroll` |
| `app/api/v1/ai_hub/payroll_insights.py:119` | GET | `/anomalies` | `list_anomalies` |
| `app/api/v1/ai_hub/payroll_insights.py:188` | POST | `/tax-audit` | `audit_taxes` |
| `app/api/v1/ai_hub/performance_coach.py:44` | GET | `` | `get_overview` |
| `app/api/v1/ai_hub/performance_coach.py:74` | POST | `/goals` | `generate_goals` |
| `app/api/v1/ai_hub/performance_coach.py:161` | POST | `/training-recommendations` | `get_training_recommendations` |
| `app/api/v1/ai_hub/policy_assistant.py:42` | GET | `` | `get_overview` |
| `app/api/v1/ai_hub/policy_assistant.py:71` | POST | `/ask` | `ask_policy` |
| `app/api/v1/ai_hub/policy_assistant.py:120` | POST | `/check-compliance` | `check_compliance` |
| `app/api/v1/ai_hub/recruiter.py:44` | GET | `` | `get_overview` |
| `app/api/v1/ai_hub/recruiter.py:74` | POST | `/generate-questions` | `generate_interview_questions` |
| `app/api/v1/ai_hub/recruiter.py:130` | POST | `/match-candidates` | `match_candidates` |
| `app/api/v1/ai_hub/recruiter.py:172` | POST | `/screen-resumes` | `screen_resumes` |
| `app/api/v1/ai_hub/root.py:148` | GET | `` | `get_ai_hub_index` |
| `app/api/v1/ai_hub/workforce.py:57` | GET | `` | `get_insights_overview` |
| `app/api/v1/ai_hub/workforce.py:88` | POST | `/analyze` | `analyze_workforce` |
| `app/api/v1/ai_hub/workforce.py:138` | GET | `` | `get_planning_overview` |
| `app/api/v1/ai_hub/workforce.py:176` | POST | `/forecast` | `forecast_workforce` |
| `app/api/v1/ai_hub/workforce.py:235` | POST | `/headcount` | `plan_headcount` |
| `app/api/v1/ai_insights.py:18` | GET | `` | `ai_insights` |
| `app/api/v1/ai_leave.py:52` | GET | `/dashboard` | `get_leave_dashboard` |
| `app/api/v1/ai_leave.py:74` | GET | `/forecast` | `get_leave_forecast` |
| `app/api/v1/ai_leave.py:96` | GET | `/distribution` | `get_leave_distribution` |
| `app/api/v1/ai_leave.py:117` | GET | `/approval-suggestions` | `get_approval_suggestions` |
| `app/api/v1/ai_leave.py:138` | GET | `/conflicts` | `get_leave_conflicts` |
| `app/api/v1/ai_leave.py:159` | GET | `/team-availability` | `get_team_availability` |
| `app/api/v1/ai_leave.py:180` | GET | `/trends` | `get_leave_trends` |
| `app/api/v1/ai_leave.py:201` | GET | `/analytics` | `get_leave_analytics` |
| `app/api/v1/ai_leave.py:222` | GET | `/request/{leave_request_id}` | `get_leave_request_detail` |
| `app/api/v1/ai_leave.py:243` | POST | `/analyze` | `analyze_leave_request` |
| `app/api/v1/ai_leave.py:264` | POST | `/forecast` | `forecast_leave_demand` |
| `app/api/v1/ai_leave.py:286` | POST | `/generate-suggestions` | `generate_approval_suggestions` |
| `app/api/v1/ai_leave.py:308` | POST | `/detect-conflicts` | `detect_leave_conflicts` |
| `app/api/v1/ai_payroll.py:52` | GET | `/dashboard` | `get_payroll_dashboard` |
| `app/api/v1/ai_payroll.py:73` | GET | `/forecast` | `get_payroll_forecast` |
| `app/api/v1/ai_payroll.py:95` | GET | `/cost-analysis` | `get_payroll_cost_analysis` |
| `app/api/v1/ai_payroll.py:116` | GET | `/cost-by-department` | `get_cost_by_department` |
| `app/api/v1/ai_payroll.py:137` | GET | `/benchmarking` | `get_salary_benchmarking` |
| `app/api/v1/ai_payroll.py:158` | GET | `/anomalies` | `get_payroll_anomalies` |
| `app/api/v1/ai_payroll.py:179` | GET | `/fraud-detection` | `get_payroll_fraud_detection` |
| `app/api/v1/ai_payroll.py:200` | GET | `/health-score` | `get_payroll_health_score` |
| `app/api/v1/ai_payroll.py:221` | GET | `/analytics` | `get_payroll_analytics` |
| `app/api/v1/ai_payroll.py:242` | GET | `/employee/{employee_id}` | `get_employee_payroll_detail` |
| `app/api/v1/ai_payroll.py:263` | POST | `/forecast` | `forecast_payroll` |
| `app/api/v1/ai_payroll.py:285` | POST | `/analyze` | `analyze_payroll` |
| `app/api/v1/ai_payroll.py:307` | POST | `/detect-anomalies` | `detect_anomalies` |
| `app/api/v1/ai_payroll.py:329` | POST | `/detect-fraud` | `detect_fraud` |
| `app/api/v1/ai_performance.py:53` | GET | `/dashboard` | `get_performance_dashboard` |
| `app/api/v1/ai_performance.py:75` | GET | `/trends` | `get_performance_trends` |
| `app/api/v1/ai_performance.py:97` | GET | `/kpi-attainment` | `get_kpi_attainment` |
| `app/api/v1/ai_performance.py:118` | GET | `/top-performers` | `get_top_performers` |
| `app/api/v1/ai_performance.py:141` | GET | `/employee/{employee_id}` | `get_employee_performance` |
| `app/api/v1/ai_performance.py:163` | GET | `/skill-gaps` | `get_skill_gaps` |
| `app/api/v1/ai_performance.py:185` | GET | `/promotion-recommendations` | `get_promotion_recommendations` |
| `app/api/v1/ai_performance.py:207` | GET | `/coaching-suggestions` | `get_coaching_suggestions` |
| `app/api/v1/ai_performance.py:229` | GET | `/analytics` | `get_performance_analytics` |
| `app/api/v1/ai_performance.py:250` | POST | `/evaluate` | `evaluate_performance` |
| `app/api/v1/ai_performance.py:270` | POST | `/generate-coaching` | `generate_coaching` |
| `app/api/v1/ai_performance.py:291` | POST | `/generate-promotion` | `generate_promotion` |
| `app/api/v1/ai_performance.py:312` | POST | `/skill-gap-analysis` | `trigger_skill_gap_analysis` |
| `app/api/v1/ai_recruiter.py:52` | GET | `/dashboard` | `get_recruiter_dashboard` |
| `app/api/v1/ai_recruiter.py:73` | GET | `/funnel` | `get_recruiter_funnel` |
| `app/api/v1/ai_recruiter.py:94` | GET | `/match-distribution` | `get_match_distribution` |
| `app/api/v1/ai_recruiter.py:115` | GET | `/analytics` | `get_recruitment_analytics` |
| `app/api/v1/ai_recruiter.py:136` | GET | `/candidate/{id}/score` | `get_candidate_score` |
| `app/api/v1/ai_recruiter.py:158` | GET | `/candidate/{id}/recommendation` | `get_candidate_recommendation` |
| `app/api/v1/ai_recruiter.py:180` | POST | `/resume/analyze` | `analyze_resume` |
| `app/api/v1/ai_recruiter.py:212` | POST | `/match` | `match_jd` |
| `app/api/v1/ai_recruiter.py:236` | POST | `/rank` | `rank_candidates` |
| `app/api/v1/ai_recruiter.py:260` | POST | `/interview/questions` | `generate_interview_questions` |
| `app/api/v1/ai_workforce.py:54` | GET | `/dashboard` | `get_workforce_dashboard` |
| `app/api/v1/ai_workforce.py:76` | GET | `/kpi` | `get_workforce_kpis_endpoint` |
| `app/api/v1/ai_workforce.py:126` | GET | `/headcount-trends` | `get_headcount_trends_endpoint` |
| `app/api/v1/ai_workforce.py:158` | GET | `/department-comparison` | `get_department_comparison_endpoint` |
| `app/api/v1/ai_workforce.py:190` | GET | `/hiring-forecast` | `get_hiring_forecast` |
| `app/api/v1/ai_workforce.py:211` | GET | `/capacity-demand` | `get_capacity_demand` |
| `app/api/v1/ai_workforce.py:232` | GET | `/capacity-planning` | `get_capacity_planning` |
| `app/api/v1/ai_workforce.py:253` | GET | `/resource-utilization` | `get_resource_utilization` |
| `app/api/v1/ai_workforce.py:274` | GET | `/future-needs` | `get_future_needs` |
| `app/api/v1/ai_workforce.py:295` | GET | `/optimization` | `get_workforce_optimization` |
| `app/api/v1/ai_workforce.py:316` | GET | `/hiring-budget` | `get_hiring_budget` |
| `app/api/v1/ai_workforce.py:337` | GET | `/analytics` | `get_workforce_analytics` |
| `app/api/v1/ai_workforce.py:358` | GET | `/department/{department_id}` | `get_department_workforce_detail` |
| `app/api/v1/ai_workforce.py:379` | GET | `/employee/{employee_id}` | `get_employee_workforce_detail` |
| `app/api/v1/ai_workforce.py:400` | POST | `/analyze` | `analyze_workforce` |
| `app/api/v1/ai_workforce.py:422` | POST | `/forecast` | `forecast_workforce` |
| `app/api/v1/ai_workforce.py:444` | POST | `/optimize` | `optimize_workforce` |
| `app/api/v1/ai_workforce.py:466` | POST | `/capacity-analysis` | `analyze_capacity` |
| `app/api/v1/ai_workforce.py:506` | POST | `/run-mode` | `run_ai_mode` |
| `app/api/v1/ai_workforce.py:506` | POST | `/run-mode` | `run_ai_mode` |
| `app/api/v1/ai_workforce.py:536` | GET | `/dashboard/stats` | `get_ai_agent_dashboard_stats` |
| `app/api/v1/ai_workforce.py:536` | GET | `/dashboard/stats` | `get_ai_agent_dashboard_stats` |
| `app/api/v1/ai_workforce.py:583` | GET | `/agents` | `list_agent_configs` |
| `app/api/v1/ai_workforce.py:583` | GET | `/agents` | `list_agent_configs` |
| `app/api/v1/ai_workforce.py:619` | PUT | `/agents/{agent_key}` | `update_agent_config_endpoint` |
| `app/api/v1/ai_workforce.py:619` | PUT | `/agents/{agent_key}` | `update_agent_config_endpoint` |
| `app/api/v1/analytics_center.py:53` | GET | `/dashboard` | `get_analytics_dashboard` |
| `app/api/v1/analytics_center.py:74` | GET | `/kpis` | `get_analytics_kpis` |
| `app/api/v1/analytics_center.py:95` | GET | `/headcount-forecast` | `get_headcount_forecast` |
| `app/api/v1/analytics_center.py:116` | GET | `/hiring-demand` | `get_hiring_demand` |
| `app/api/v1/analytics_center.py:137` | GET | `/payroll-trend` | `get_payroll_trend` |
| `app/api/v1/analytics_center.py:158` | GET | `/skill-gap` | `get_skill_gap` |
| `app/api/v1/analytics_center.py:179` | GET | `/recruitment` | `get_recruitment_analytics` |
| `app/api/v1/analytics_center.py:200` | GET | `/performance` | `get_performance_analytics` |
| `app/api/v1/analytics_center.py:221` | GET | `/workforce` | `get_workforce_analytics` |
| `app/api/v1/analytics_center.py:242` | GET | `/health` | `get_health_analytics` |
| `app/api/v1/analytics_center.py:263` | GET | `/compliance` | `get_compliance_analytics` |
| `app/api/v1/analytics_center.py:284` | GET | `/attrition` | `get_attrition_prediction` |
| `app/api/v1/analytics_center.py:305` | GET | `/summary` | `get_executive_summary` |
| `app/api/v1/analytics_center.py:326` | POST | `/generate` | `generate_analytics` |
| `app/api/v1/analytics_center.py:348` | POST | `/predict` | `predict_analytics` |
| `app/api/v1/attendance.py:24` | GET | `` | `list_attendance` |
| `app/api/v1/attendance.py:44` | POST | `` | `mark_attendance` |
| `app/api/v1/attendance.py:70` | GET | `/report` | `attendance_report` |
| `app/api/v1/attendance.py:100` | GET | `/export/csv` | `export_csv` |
| `app/api/v1/attendance.py:113` | GET | `/export/pdf` | `export_pdf` |
| `app/api/v1/cctv.py:35` | GET | `/cameras` | `list_cameras` |
| `app/api/v1/cctv.py:43` | POST | `/cameras` | `create_camera` |
| `app/api/v1/cctv.py:56` | PUT | `/cameras/{camera_id}` | `update_camera` |
| `app/api/v1/cctv.py:71` | DELETE | `/cameras/{camera_id}` | `delete_camera` |
| `app/api/v1/cctv.py:84` | POST | `/cameras/{camera_id}/test` | `test_camera` |
| `app/api/v1/chat_assistant.py:83` | POST | `/message` | `chat_with_assistant` |
| `app/api/v1/chat_assistant.py:83` | POST | `/query` | `chat_with_assistant` |
| `app/api/v1/chat_assistant.py:106` | POST | `/conversations` | `create_chat_conversation` |
| `app/api/v1/chat_assistant.py:200` | POST | `/report` | `generate_hr_report` |
| `app/api/v1/chat_assistant.py:223` | POST | `/analytics` | `run_workforce_analytics` |
| `app/api/v1/chat_assistant.py:246` | POST | `/recommendations` | `generate_ai_recommendations` |
| `app/api/v1/chat_assistant.py:275` | GET | `/history` | `get_chat_history` |
| `app/api/v1/chat_assistant.py:275` | GET | `/conversations` | `get_chat_history` |
| `app/api/v1/chat_assistant.py:303` | GET | `/history/{conversation_id}` | `get_chat_history_detail` |
| `app/api/v1/chat_assistant.py:303` | GET | `/conversations/{conversation_id}` | `get_chat_history_detail` |
| `app/api/v1/chat_assistant.py:336` | DELETE | `/history/{conversation_id}` | `delete_chat_history` |
| `app/api/v1/chat_assistant.py:336` | DELETE | `/conversations/{conversation_id}` | `delete_chat_history` |
| `app/api/v1/chat_assistant.py:363` | GET | `/suggestions` | `get_chat_suggestions` |
| `app/api/v1/chat_assistant.py:384` | POST | `/feedback` | `submit_chat_feedback` |
| `app/api/v1/compliance_monitor.py:53` | GET | `/dashboard` | `get_compliance_dashboard` |
| `app/api/v1/compliance_monitor.py:74` | GET | `/checks` | `get_compliance_checks` |
| `app/api/v1/compliance_monitor.py:95` | GET | `/labor-laws` | `get_labor_laws` |
| `app/api/v1/compliance_monitor.py:116` | GET | `/missing-documents` | `get_missing_documents` |
| `app/api/v1/compliance_monitor.py:137` | GET | `/risks` | `get_compliance_risks` |
| `app/api/v1/compliance_monitor.py:158` | GET | `/audit-readiness` | `get_audit_readiness` |
| `app/api/v1/compliance_monitor.py:179` | GET | `/analytics` | `get_compliance_analytics` |
| `app/api/v1/compliance_monitor.py:200` | GET | `/alerts` | `get_compliance_alerts` |
| `app/api/v1/compliance_monitor.py:221` | GET | `/report` | `get_compliance_report` |
| `app/api/v1/compliance_monitor.py:242` | GET | `/employee/{employee_id}` | `get_employee_compliance_detail` |
| `app/api/v1/compliance_monitor.py:263` | POST | `/analyze` | `analyze_compliance` |
| `app/api/v1/compliance_monitor.py:285` | POST | `/audit` | `run_compliance_audit` |
| `app/api/v1/compliance_monitor.py:307` | POST | `/risk-analysis` | `run_risk_analysis` |
| `app/api/v1/dashboard.py:18` | GET | `/summary` | `summary` |
| `app/api/v1/dashboard.py:33` | GET | `/attendance-trend` | `attendance_trend` |
| `app/api/v1/dashboard.py:48` | GET | `/class-attendance` | `class_attendance` |
| `app/api/v1/digilocker.py:87` | GET | `/status` | `get_digilocker_status` |
| `app/api/v1/digilocker.py:163` | POST | `/digilocker/initiate` | `initiate_digilocker` |
| `app/api/v1/digilocker.py:226` | POST | `/digilocker/callback` | `digilocker_callback` |
| `app/api/v1/documents.py:23` | GET | `` | `list_documents` |
| `app/api/v1/documents.py:34` | POST | `` | `upload_document` |
| `app/api/v1/documents.py:73` | DELETE | `/{document_id}` | `delete_document` |
| `app/api/v1/employee_health.py:52` | GET | `/dashboard` | `get_health_dashboard` |
| `app/api/v1/employee_health.py:74` | GET | `/kpi` | `get_health_kpis_endpoint` |
| `app/api/v1/employee_health.py:120` | GET | `/wellbeing-score` | `get_wellbeing_score` |
| `app/api/v1/employee_health.py:141` | GET | `/burnout-risk` | `get_burnout_risk` |
| `app/api/v1/employee_health.py:162` | GET | `/workload-analysis` | `get_workload_analysis` |
| `app/api/v1/employee_health.py:183` | GET | `/overtime` | `get_overtime` |
| `app/api/v1/employee_health.py:204` | GET | `/stress-indicators` | `get_stress_indicators` |
| `app/api/v1/employee_health.py:225` | GET | `/burnout-trend` | `get_burnout_trend` |
| `app/api/v1/employee_health.py:246` | GET | `/team-overtime` | `get_team_overtime` |
| `app/api/v1/employee_health.py:267` | GET | `/analytics` | `get_health_analytics` |
| `app/api/v1/employee_health.py:288` | GET | `/employee/{employee_id}` | `get_employee_health_detail` |
| `app/api/v1/employee_health.py:309` | POST | `/analyze` | `analyze_health` |
| `app/api/v1/employee_health.py:331` | POST | `/burnout-analysis` | `analyze_burnout` |
| `app/api/v1/employee_health.py:353` | POST | `/workload-analysis` | `analyze_workload` |
| `app/api/v1/employee_health.py:375` | POST | `/generate-insights` | `generate_health_insights` |
| `app/api/v1/executive.py:64` | GET | `/overview` | `get_executive_overview` |
| `app/api/v1/executive.py:211` | GET | `/dashboard/{role}` | `get_executive_dashboard` |
| `app/api/v1/face.py:35` | POST | `/enroll` | `enroll` |
| `app/api/v1/face.py:77` | POST | `/recognize` | `recognize` |
| `app/api/v1/fees.py:45` | GET | `` | `list_fees` |
| `app/api/v1/fees.py:61` | GET | `/summary` | `fee_summary` |
| `app/api/v1/fees.py:70` | GET | `/{fee_id}` | `get_fee` |
| `app/api/v1/fees.py:78` | POST | `` | `create_fee` |
| `app/api/v1/fees.py:95` | PUT | `/{fee_id}` | `update_fee` |
| `app/api/v1/fees.py:111` | POST | `/{fee_id}/payment` | `record_payment` |
| `app/api/v1/hr_ops_analytics.py:52` | GET | `/overview` | `get_hr_ops_overview` |
| `app/api/v1/hr_ops_analytics.py:149` | GET | `/cto/dashboard` | `get_cto_dashboard_alias` |
| `app/api/v1/hr_ops_analytics.py:174` | GET | `/analytics/metrics` | `get_analytics_metrics` |
| `app/api/v1/hr_ops_analytics.py:285` | GET | `/reports/analytics/export` | `export_analytics_report` |
| `app/api/v1/hr_ops_analytics.py:374` | POST | `/documents/generate` | `generate_document` |
| `app/api/v1/hr_ops_analytics.py:435` | GET | `/timesheets/ai-suggest` | `get_ai_timesheet_suggestions` |
| `app/api/v1/hr_ops_analytics.py:533` | GET | `/policy-assistant/search` | `search_policies` |
| `app/api/v1/hr_ops_analytics.py:592` | GET | `/connect/channels/{channel_id}/members` | `get_channel_members` |
| `app/api/v1/hr_ops_analytics.py:676` | PATCH | `/employees/{employee_id}/promote` | `promote_employee` |
| `app/api/v1/intelligence.py:135` | GET | `/models` | `list_intelligence_models` |
| `app/api/v1/intelligence.py:135` | HEAD | `/models` | `list_intelligence_models` |
| `app/api/v1/meeting_ai.py:51` | GET | `/dashboard` | `get_meeting_dashboard` |
| `app/api/v1/meeting_ai.py:72` | GET | `/kpi` | `get_meeting_kpis_endpoint` |
| `app/api/v1/meeting_ai.py:118` | GET | `/summaries` | `get_meeting_summaries` |
| `app/api/v1/meeting_ai.py:139` | GET | `/action-items` | `get_action_items` |
| `app/api/v1/meeting_ai.py:160` | GET | `/follow-ups` | `get_follow_ups` |
| `app/api/v1/meeting_ai.py:181` | GET | `/team-insights` | `get_team_insights` |
| `app/api/v1/meeting_ai.py:202` | GET | `/discussion-analytics` | `get_discussion_analytics` |
| `app/api/v1/meeting_ai.py:223` | GET | `/volume` | `get_meeting_volume` |
| `app/api/v1/meeting_ai.py:244` | GET | `/history` | `get_meeting_history` |
| `app/api/v1/meeting_ai.py:265` | GET | `/{meeting_id}` | `get_meeting_detail` |
| `app/api/v1/meeting_ai.py:286` | POST | `/analyze` | `analyze_meeting` |
| `app/api/v1/meeting_ai.py:308` | POST | `/summarize` | `summarize_meeting` |
| `app/api/v1/meeting_ai.py:329` | POST | `/extract-action-items` | `extract_action_items` |
| `app/api/v1/meeting_ai.py:350` | POST | `/generate-followups` | `generate_followups` |
| `app/api/v1/onboarding_checklist.py:81` | GET | `` | `get_onboarding_checklist` |
| `app/api/v1/onboarding_checklist.py:139` | PATCH | `/{checklist_id}` | `update_checklist_item` |
| `app/api/v1/parent.py:31` | GET | `/children` | `my_children` |
| `app/api/v1/parent.py:39` | GET | `/children/{student_id}/attendance` | `child_attendance` |
| `app/api/v1/parent.py:48` | GET | `/children/{student_id}/fees` | `child_fees` |
| `app/api/v1/parent.py:58` | GET | `/children/{student_id}/notices` | `child_notices` |
| `app/api/v1/payroll/router.py:38` | GET | `/employees/{employeeId}/payslips` | `v1_get_employee_payslips` |
| `app/api/v1/payroll/router.py:54` | GET | `/my-payslips` | `v1_get_my_payslips` |
| `app/api/v1/payroll/router.py:71` | GET | `/periods` | `v1_list_periods` |
| `app/api/v1/payroll/router.py:92` | POST | `/periods` | `v1_create_period` |
| `app/api/v1/payroll/router.py:104` | GET | `/periods/{periodId}` | `v1_get_period` |
| `app/api/v1/payroll/router.py:116` | POST | `/run` | `v1_create_run` |
| `app/api/v1/payroll/router.py:130` | GET | `/runs` | `v1_list_runs` |
| `app/api/v1/payroll/router.py:182` | GET | `/stats` | `v1_get_payroll_stats` |
| `app/api/v1/payroll/router.py:232` | GET | `/runs/{runId}` | `v1_get_run` |
| `app/api/v1/payroll/router.py:244` | POST | `/runs/{runId}/approve` | `v1_approve_run` |
| `app/api/v1/payroll/router.py:260` | POST | `/runs/{runId}/cancel` | `v1_cancel_run` |
| `app/api/v1/payroll/router.py:272` | GET | `/runs/{runId}/employees` | `v1_get_run_employees` |
| `app/api/v1/payroll/router.py:294` | GET | `/runs/{runId}/employees/{employeeId}` | `v1_get_run_single_employee` |
| `app/api/v1/payroll/router.py:307` | GET | `/runs/{runId}/employees/{employeeId}/payslip/download` | `v1_download_payslip` |
| `app/api/v1/payroll/router.py:323` | POST | `/runs/{runId}/finalize` | `v1_finalize_run` |
| `app/api/v1/payroll/router.py:339` | POST | `/runs/{runId}/payslips/generate` | `v1_generate_payslips` |
| `app/api/v1/payroll/router.py:356` | GET | `/runs/{runId}/preview` | `v1_preview_run` |
| `app/api/v1/payroll/router.py:368` | POST | `/runs/{runId}/reject` | `v1_reject_run` |
| `app/api/v1/payroll/router.py:383` | POST | `/runs/{runId}/retry` | `v1_retry_run` |
| `app/api/v1/payroll/router.py:395` | GET | `/runs/{runId}/status` | `v1_get_run_status` |
| `app/api/v1/payroll/router.py:419` | GET | `/runs/{runId}/validation` | `v1_get_run_validation` |
| `app/api/v1/policy_ai.py:48` | POST | `/chat` | `policy_chat` |
| `app/api/v1/policy_ai.py:70` | POST | `/search` | `search_policies` |
| `app/api/v1/policy_ai.py:92` | GET | `/suggestions` | `get_policy_suggestions` |
| `app/api/v1/policy_ai.py:114` | GET | `/history` | `get_policy_history` |
| `app/api/v1/policy_ai.py:135` | GET | `/history/{conversation_id}` | `get_conversation_detail` |
| `app/api/v1/policy_ai.py:156` | DELETE | `/history/{conversation_id}` | `delete_conversation` |
| `app/api/v1/policy_ai.py:177` | GET | `/documents` | `get_policy_documents` |
| `app/api/v1/policy_ai.py:199` | GET | `/document/{document_id}` | `get_policy_document_detail` |
| `app/api/v1/policy_ai.py:220` | POST | `/feedback` | `submit_policy_feedback` |
| `app/api/v1/recognition.py:17` | GET | `/logs` | `list_logs` |
| `app/api/v1/reports.py:81` | GET | `/engagement/summary` | `get_engagement_summary` |
| `app/api/v1/reports.py:102` | GET | `/engagement/trend` | `get_engagement_trend` |
| `app/api/v1/reports.py:124` | GET | `/engagement/enps-trend` | `get_enps_trend` |
| `app/api/v1/reports.py:146` | GET | `/engagement/breakdown` | `get_engagement_breakdown` |
| `app/api/v1/reports.py:168` | GET | `/engagement/surveys` | `get_engagement_surveys` |
| `app/api/v1/reports.py:203` | GET | `/culture/telemetry` | `get_culture_telemetry` |
| `app/api/v1/reports.py:224` | GET | `/culture/trend` | `get_culture_trend` |
| `app/api/v1/reports.py:246` | GET | `/culture/breakdown` | `get_culture_breakdown` |
| `app/api/v1/reports.py:268` | GET | `/culture/feedback` | `get_culture_feedback` |
| `app/api/v1/students.py:19` | GET | `` | `list_students` |
| `app/api/v1/students.py:47` | GET | `/{student_id}` | `get_student` |
| `app/api/v1/students.py:55` | POST | `` | `create_student` |
| `app/api/v1/students.py:72` | PUT | `/{student_id}` | `update_student` |
| `app/api/v1/students.py:87` | DELETE | `/{student_id}` | `delete_student` |
| `app/api/v1/teachers.py:26` | GET | `` | `list_teachers` |
| `app/api/v1/teachers.py:41` | GET | `/{teacher_id}` | `get_teacher` |
| `app/api/v1/teachers.py:49` | POST | `` | `create_teacher` |
| `app/api/v1/teachers.py:67` | PUT | `/{teacher_id}` | `update_teacher` |
| `app/api/v1/teachers.py:85` | DELETE | `/{teacher_id}` | `delete_teacher` |
| `app/api/v1/users.py:23` | GET | `` | `list_users` |
| `app/api/v1/users.py:42` | GET | `/{user_id}` | `get_user` |
| `app/api/v1/users.py:51` | POST | `` | `create_user` |
| `app/api/v1/users.py:69` | PUT | `/{user_id}` | `update_user` |
| `app/api/v1/users.py:90` | DELETE | `/{user_id}` | `delete_user` |
| `app/api/v1/visitors.py:155` | GET | `` | `list_visitors` |
| `app/api/v1/visitors.py:252` | POST | `` | `create_visitor` |
| `app/api/v1/visitors.py:334` | GET | `/{visitor_id}` | `get_visitor` |
| `app/api/v1/visitors.py:390` | PATCH | `/{visitor_id}` | `update_visitor` |
| `app/api/v1/visitors.py:469` | DELETE | `/{visitor_id}` | `delete_visitor` |
| `app/api/v1/visitors.py:500` | POST | `/{visitor_id}/check-in` | `check_in_visitor` |
| `app/api/v1/visitors.py:555` | POST | `/{visitor_id}/check-out` | `check_out_visitor` |
| `app/api/v2/analytics.py:31` | GET | `/dashboard` | `get_dashboard_summary` |
| `app/api/v2/analytics.py:47` | GET | `/hiring-funnel` | `get_hiring_funnel` |
| `app/api/v2/analytics.py:65` | GET | `/offer-acceptance-rate` | `get_offer_acceptance_rate` |
| `app/api/v2/analytics.py:82` | GET | `/time-to-hire` | `get_time_to_hire` |
| `app/api/v2/analytics.py:99` | GET | `/source-performance` | `get_source_performance` |
| `app/api/v2/analytics.py:121` | GET | `/recruiter-performance` | `get_recruiter_performance` |
| `app/api/v2/analytics.py:143` | GET | `/department` | `get_department_analytics` |
| `app/api/v2/analytics.py:165` | GET | `/interview-success` | `get_interview_success_rate` |
| `app/api/v2/analytics.py:185` | GET | `/culture` | `get_culture_analytics` |
| `app/api/v2/analytics.py:195` | GET | `/diversity` | `get_diversity_analytics` |
| `app/api/v2/analytics.py:205` | GET | `/attrition-risk` | `get_attrition_risk_analytics` |
| `app/api/v2/autopilot.py:59` | GET | `/settings` | `get_autopilot_settings` |
| `app/api/v2/autopilot.py:82` | PUT | `/settings` | `update_autopilot_settings` |
| `app/api/v2/autopilot.py:108` | GET | `/rules` | `list_autopilot_rules` |
| `app/api/v2/autopilot.py:131` | POST | `/rules` | `create_autopilot_rule` |
| `app/api/v2/autopilot.py:155` | GET | `/rules/{rule_id}` | `get_autopilot_rule` |
| `app/api/v2/autopilot.py:179` | PUT | `/rules/{rule_id}` | `update_autopilot_rule` |
| `app/api/v2/autopilot.py:204` | DELETE | `/rules/{rule_id}` | `delete_autopilot_rule` |
| `app/api/v2/autopilot.py:223` | POST | `/rules/simulate` | `simulate_autopilot_rule` |
| `app/api/v2/autopilot.py:249` | GET | `/exceptions` | `list_autopilot_exceptions` |
| `app/api/v2/autopilot.py:271` | GET | `/exceptions/{exception_id}` | `get_autopilot_exception` |
| `app/api/v2/autopilot.py:295` | POST | `/exceptions/{exception_id}/decision` | `decide_autopilot_exception` |
| `app/api/v2/autopilot.py:327` | POST | `/agent/chat` | `autopilot_agent_chat` |
| `app/api/v2/autopilot.py:351` | GET | `/agent/actions/{action_id}` | `get_agent_action` |
| `app/api/v2/autopilot.py:382` | POST | `/agent/actions/{action_id}/confirm` | `confirm_agent_action` |
| `app/api/v2/autopilot.py:402` | POST | `/agent/actions/{action_id}/cancel` | `cancel_agent_action` |
| `app/api/v2/autopilot.py:424` | GET | `/audit` | `list_autopilot_audit` |
| `app/api/v2/autopilot.py:447` | POST | `/audit/{audit_id}/undo` | `undo_autopilot_audit` |
| `app/api/v2/autopilot.py:467` | POST | `/audit/{audit_id}/override` | `override_autopilot_audit` |
| `app/api/v2/autopilot.py:489` | GET | `/alerts` | `list_autopilot_alerts` |
| `app/api/v2/autopilot.py:511` | POST | `/alerts/{alert_id}/ack` | `acknowledge_autopilot_alert` |
| `app/api/v2/autopilot.py:530` | POST | `/alerts/{alert_id}/snooze` | `snooze_autopilot_alert` |
| `app/api/v2/autopilot.py:550` | POST | `/alerts/{alert_id}/task` | `create_autopilot_alert_task` |
| `app/api/v2/autopilot.py:578` | GET | `/overview` | `get_autopilot_overview` |
| `app/api/v2/autopilot.py:603` | GET | `/onboarding/runs` | `list_autopilot_onboarding_runs` |
| `app/api/v2/autopilot.py:624` | GET | `/onboarding/runs/{run_id}` | `get_autopilot_onboarding_run` |
| `app/api/v2/autopilot.py:648` | POST | `/onboarding/runs/{run_id}/retry-step` | `retry_autopilot_onboarding_step` |
| `app/api/v2/autopilot.py:670` | GET | `/payroll/status` | `get_autopilot_payroll_status` |
| `app/api/v2/behavioural_api.py:48` | POST | `/sessions` | `create_session` |
| `app/api/v2/behavioural_api.py:96` | POST | `/questions/{question_id}/respond` | `respond_question` |
| `app/api/v2/bgv_api.py:59` | POST | `/vendors` | `create_vendor` |
| `app/api/v2/bgv_api.py:69` | POST | `/cases` | `create_case` |
| `app/api/v2/bgv_api.py:81` | POST | `/public/consent/{token}` | `capture_public_consent` |
| `app/api/v2/bgv_api.py:95` | POST | `/cases/{case_id}/submit` | `submit_case` |
| `app/api/v2/bgv_api.py:105` | GET | `/cases/{case_id}` | `get_case` |
| `app/api/v2/bgv_api.py:115` | POST | `/checks/{check_id}/discrepancy` | `resolve_discrepancy` |
| `app/api/v2/bgv_api.py:128` | POST | `/webhooks/{tenant_id}/{vendor_id}` | `bgv_webhook` |
| `app/api/v2/candidate_matching.py:44` | POST | `/score` | `compute_match_score` |
| `app/api/v2/candidate_matching.py:145` | POST | `/batch-score` | `batch_match_scores` |
| `app/api/v2/candidate_matching.py:210` | GET | `/history/{resume_document_id}` | `get_match_history` |
| `app/api/v2/coding_assessment.py:79` | POST | `/generate` | `generate_coding_challenge` |
| `app/api/v2/coding_assessment.py:128` | POST | `/generate-set` | `generate_challenge_set` |
| `app/api/v2/coding_assessment.py:193` | POST | `/submit` | `submit_code` |
| `app/api/v2/coding_assessment.py:270` | GET | `/{assessment_id}` | `get_assessment` |
| `app/api/v2/compensation_api.py:48` | POST | `/benchmarks` | `register_benchmark` |
| `app/api/v2/compensation_api.py:81` | POST | `/recommendations/{employee_id}` | `compile_recommendation` |
| `app/api/v2/compensation_api.py:160` | POST | `/bands` | `create_compensation_band` |
| `app/api/v2/compensation_api.py:170` | POST | `/bands/{band_id}/assignments` | `assign_compensation_band` |
| `app/api/v2/compensation_api.py:182` | GET | `/employees/{employee_id}/compa-ratio` | `employee_compa_ratio` |
| `app/api/v2/compensation_api.py:191` | POST | `/market-benchmarks` | `create_band_market_benchmark` |
| `app/api/v2/compensation_api.py:201` | GET | `/employees/{employee_id}/market-comparison` | `employee_market_comparison` |
| `app/api/v2/compensation_api.py:210` | POST | `/increment-budgets/model` | `model_increment_budget` |
| `app/api/v2/compensation_api.py:220` | GET | `/pay-equity` | `pay_equity_report` |
| `app/api/v2/data_migration_api.py:71` | POST | `/validate` | `validate_migration` |
| `app/api/v2/data_migration_api.py:79` | POST | `/validate-json` | `validate_migration_rows` |
| `app/api/v2/data_migration_api.py:94` | POST | `/{migration_type}/validate` | `validate_typed_migration` |
| `app/api/v2/data_migration_api.py:102` | GET | `` | `list_migrations` |
| `app/api/v2/data_migration_api.py:112` | GET | `/{batch_id}` | `get_migration` |
| `app/api/v2/data_migration_api.py:124` | POST | `/{batch_id}/commit` | `commit_migration` |
| `app/api/v2/data_migration_api.py:136` | POST | `/{batch_id}/rollback` | `rollback_migration` |
| `app/api/v2/developer_api.py:50` | POST | `/api-keys` | `create_api_key` |
| `app/api/v2/developer_api.py:60` | GET | `/api-keys` | `list_api_keys` |
| `app/api/v2/developer_api.py:67` | DELETE | `/api-keys/{key_id}` | `revoke_api_key` |
| `app/api/v2/developer_api.py:77` | POST | `/webhook-subscriptions` | `create_webhook_subscription` |
| `app/api/v2/developer_api.py:90` | GET | `/webhook-subscriptions` | `list_webhook_subscriptions` |
| `app/api/v2/developer_api.py:97` | DELETE | `/webhook-subscriptions/{subscription_id}` | `delete_webhook_subscription` |
| `app/api/v2/developer_api.py:107` | POST | `/deliveries/{delivery_id}/retry` | `retry_webhook_delivery` |
| `app/api/v2/developer_api.py:117` | GET | `/api/employees` | `developer_employee_feed` |
| `app/api/v2/developer_api.py:133` | POST | `/identity-providers` | `configure_identity_provider` |
| `app/api/v2/document_esign_api.py:54` | GET | `/letters/types` | `list_letter_types` |
| `app/api/v2/document_esign_api.py:61` | POST | `/letters/{letter_type}/generate` | `generate_letter` |
| `app/api/v2/document_esign_api.py:83` | POST | `/{doc_id}/request-esign` | `request_esign` |
| `app/api/v2/document_esign_api.py:103` | POST | `/{doc_id}/sign` | `sign_document` |
| `app/api/v2/document_esign_api.py:135` | GET | `/{doc_id}/audit-certificate` | `get_audit_certificate` |
| `app/api/v2/document_esign_api.py:153` | POST | `/esign/webhooks/{provider}` | `provider_webhook` |
| `app/api/v2/document_esign_api.py:153` | POST | `/webhooks/esign/{provider}` | `provider_webhook` |
| `app/api/v2/document_intelligence.py:71` | POST | `/upload` | `upload_documents` |
| `app/api/v2/document_intelligence.py:137` | POST | `/classify` | `classify_document` |
| `app/api/v2/document_intelligence.py:196` | POST | `/extract` | `extract_document_fields` |
| `app/api/v2/document_intelligence.py:245` | POST | `/analyze` | `analyze_document` |
| `app/api/v2/document_intelligence.py:273` | POST | `/compare` | `compare_documents` |
| `app/api/v2/document_intelligence.py:308` | POST | `/validate` | `validate_document_fields` |
| `app/api/v2/document_intelligence.py:359` | POST | `/search` | `semantic_search` |
| `app/api/v2/document_intelligence.py:399` | POST | `/query` | `query_rag_doc` |
| `app/api/v2/document_intelligence.py:428` | GET | `/insights` | `get_insights` |
| `app/api/v2/dpdp_api.py:134` | POST | `/consents` | `create_consent` |
| `app/api/v2/dpdp_api.py:166` | GET | `/consents/me` | `get_my_consents` |
| `app/api/v2/dpdp_api.py:186` | POST | `/data-export` | `export_personal_data` |
| `app/api/v2/dpdp_api.py:223` | POST | `/erasure-requests` | `create_erasure_request` |
| `app/api/v2/dpdp_api.py:246` | POST | `/erasure-requests/{request_id}/execute` | `execute_erasure_request` |
| `app/api/v2/dpdp_api.py:281` | GET | `/{employee_id}/sensitive-pii` | `get_sensitive_employee_pii` |
| `app/api/v2/email_generator_api.py:44` | POST | `/generate` | `generate_email` |
| `app/api/v2/emotion_chatbot_api.py:144` | POST | `/sessions` | `init_session` |
| `app/api/v2/emotion_chatbot_api.py:211` | POST | `/sessions/{session_id}/messages` | `send_message` |
| `app/api/v2/employee_bulk_api.py:25` | POST | `/bulk-import` | `bulk_import_employees` |
| `app/api/v2/employee_bulk_api.py:52` | GET | `/bulk-export` | `bulk_export_employees` |
| `app/api/v2/employee_intelligence_apis.py:33` | POST | `/command` | `process_voice_command` |
| `app/api/v2/employee_intelligence_apis.py:52` | POST | `/detect` | `detect_mood` |
| `app/api/v2/employee_intelligence_apis.py:70` | POST | `/predict` | `predict_career_path` |
| `app/api/v2/employee_intelligence_apis.py:76` | GET | `/predictions` | `get_saved_career_paths` |
| `app/api/v2/employee_intelligence_apis.py:123` | POST | `/recommend` | `get_learning_recommendations` |
| `app/api/v2/employee_intelligence_apis.py:129` | GET | `/recommendations` | `get_saved_recommendations` |
| `app/api/v2/employee_support.py:52` | POST | `/chat` | `chat_employee_support` |
| `app/api/v2/employee_support.py:95` | POST | `/tickets` | `create_ticket` |
| `app/api/v2/employee_support.py:139` | GET | `/tickets/my` | `get_my_tickets` |
| `app/api/v2/employee_support.py:182` | PATCH | `/tickets/{ticket_id}` | `update_ticket` |
| `app/api/v2/employee_support.py:215` | GET | `/hr-copilot/stats` | `hr_copilot_stats` |
| `app/api/v2/engagement_api.py:65` | POST | `/surveys` | `create_survey` |
| `app/api/v2/engagement_api.py:75` | POST | `/surveys/{survey_id}/responses` | `submit_survey_response` |
| `app/api/v2/engagement_api.py:87` | GET | `/surveys/{survey_id}/results` | `survey_results` |
| `app/api/v2/engagement_api.py:96` | POST | `/surveys/recurring/process` | `process_recurring_surveys` |
| `app/api/v2/engagement_api.py:103` | POST | `/action-plans` | `create_action_plan` |
| `app/api/v2/engagement_api.py:113` | POST | `/recognitions` | `recognize_peer` |
| `app/api/v2/engagement_api.py:125` | GET | `/rewards/balance` | `reward_balance` |
| `app/api/v2/engagement_api.py:135` | POST | `/rewards/redeem` | `redeem_rewards` |
| `app/api/v2/enterprise_intelligence_apis.py:47` | POST | `/forecast` | `run_workforce_forecast` |
| `app/api/v2/enterprise_intelligence_apis.py:76` | PUT | `/plans` | `upsert_workforce_plan` |
| `app/api/v2/enterprise_intelligence_apis.py:97` | GET | `/planning` | `get_workforce_planning` |
| `app/api/v2/enterprise_intelligence_apis.py:142` | POST | `/match` | `find_talent_matches` |
| `app/api/v2/enterprise_intelligence_apis.py:190` | POST | `/analyze` | `analyze_meeting` |
| `app/api/v2/enterprise_intelligence_apis.py:233` | POST | `/audit` | `run_compliance_audit` |
| `app/api/v2/enterprise_intelligence_apis.py:275` | POST | `/assess` | `assess_employee_risk` |
| `app/api/v2/enterprise_intelligence_apis.py:319` | POST | `/query` | `ask_copilot` |
| `app/api/v2/enterprise_intelligence_apis.py:386` | POST | `/openings` | `create_internal_opening` |
| `app/api/v2/enterprise_intelligence_apis.py:398` | GET | `/openings` | `list_internal_openings` |
| `app/api/v2/enterprise_intelligence_apis.py:410` | GET | `/openings/{opening_id}/eligibility` | `internal_job_eligibility` |
| `app/api/v2/enterprise_intelligence_apis.py:419` | POST | `/openings/{opening_id}/applications` | `apply_internal_job` |
| `app/api/v2/enterprise_intelligence_apis.py:431` | POST | `/applications/{application_id}/manager-decision` | `decide_internal_application` |
| `app/api/v2/fnf_workflow_api.py:40` | GET | `/{exit_id}/clearance` | `get_clearance` |
| `app/api/v2/fnf_workflow_api.py:51` | POST | `/{exit_id}/fnf/finalize` | `finalize_fnf` |
| `app/api/v2/fnf_workflow_api.py:65` | POST | `/{exit_id}/fnf/settle` | `settle_fnf` |
| `app/api/v2/fnf_workflow_api.py:79` | GET | `/{exit_id}/fnf/settlement-sheet` | `download_settlement_sheet` |
| `app/api/v2/goal_generator_api.py:51` | POST | `/generate` | `generate_goals` |
| `app/api/v2/goal_generator_api.py:95` | POST | `/adjust` | `adjust_goals` |
| `app/api/v2/grievance_posh_api.py:141` | POST | `/grievances` | `create_grievance` |
| `app/api/v2/grievance_posh_api.py:161` | GET | `/grievances/{case_id}` | `get_grievance` |
| `app/api/v2/grievance_posh_api.py:178` | POST | `/grievances/{case_id}/investigator` | `assign_investigator` |
| `app/api/v2/grievance_posh_api.py:191` | POST | `/grievances/{case_id}/resolve` | `resolve_grievance` |
| `app/api/v2/grievance_posh_api.py:204` | POST | `/grievances/{case_id}/appeal` | `appeal_grievance` |
| `app/api/v2/grievance_posh_api.py:217` | POST | `/grievances/{case_id}/appeal/decision` | `decide_appeal` |
| `app/api/v2/grievance_posh_api.py:231` | POST | `/grievances/escalations/run` | `escalate_grievances` |
| `app/api/v2/grievance_posh_api.py:238` | POST | `/posh/icc` | `create_icc` |
| `app/api/v2/grievance_posh_api.py:256` | GET | `/posh/icc/{committee_id}/composition` | `icc_composition` |
| `app/api/v2/grievance_posh_api.py:267` | POST | `/posh/complaints` | `create_posh_complaint` |
| `app/api/v2/grievance_posh_api.py:285` | GET | `/posh/complaints/{complaint_id}` | `get_posh_complaint` |
| `app/api/v2/grievance_posh_api.py:301` | POST | `/posh/complaints/{complaint_id}/conciliation` | `conciliate_posh` |
| `app/api/v2/grievance_posh_api.py:315` | POST | `/posh/complaints/{complaint_id}/inquiry/start` | `start_posh_inquiry` |
| `app/api/v2/grievance_posh_api.py:326` | POST | `/posh/complaints/{complaint_id}/recommendation` | `recommend_posh` |
| `app/api/v2/grievance_posh_api.py:339` | POST | `/posh/complaints/{complaint_id}/evidence` | `upload_posh_evidence` |
| `app/api/v2/grievance_posh_api.py:358` | GET | `/posh/evidence/{evidence_id}` | `download_posh_evidence` |
| `app/api/v2/grievance_posh_api.py:373` | POST | `/posh/training` | `record_posh_training` |
| `app/api/v2/grievance_posh_api.py:383` | POST | `/posh/annual-return/{return_year}` | `generate_posh_annual_return` |
| `app/api/v2/hr_analytics_api.py:43` | GET | `/dashboard` | `get_dashboard` |
| `app/api/v2/hr_analytics_api.py:71` | POST | `/snapshots` | `compute_snapshot` |
| `app/api/v2/hr_analytics_api.py:103` | POST | `/attrition-prediction/{employee_id}` | `predict_attrition` |
| `app/api/v2/hr_analytics_api.py:143` | POST | `/forecast` | `run_forecast` |
| `app/api/v2/hr_analytics_api.py:187` | GET | `/leaves/analytics` | `get_leave_analytics` |
| `app/api/v2/hr_copilot.py:56` | POST | `/query` | `query_hr_copilot` |
| `app/api/v2/hr_copilot.py:99` | POST | `/index/candidate` | `index_candidate` |
| `app/api/v2/hr_copilot.py:126` | POST | `/index/job` | `index_job` |
| `app/api/v2/hr_copilot.py:152` | GET | `/vector-store/status` | `get_vector_store_status` |
| `app/api/v2/hr_copilot.py:178` | DELETE | `/index/candidate/{candidate_id}` | `remove_candidate_from_index` |
| `app/api/v2/hr_copilot.py:243` | POST | `/salary-negotiation-copilot` | `salary_negotiation_copilot` |
| `app/api/v2/hr_copilot.py:274` | POST | `/disciplinary-assistant` | `disciplinary_assistant` |
| `app/api/v2/hr_copilot.py:291` | POST | `/termination-risk-assistant` | `termination_risk_assistant` |
| `app/api/v2/hr_workflow_api.py:57` | POST | `/definitions` | `create_definition` |
| `app/api/v2/hr_workflow_api.py:87` | POST | `/trigger` | `trigger_workflow` |
| `app/api/v2/hr_workflow_api.py:125` | PATCH | `/steps/{step_id}/decision` | `submit_decision` |
| `app/api/v2/hr_workflow_api.py:160` | GET | `/instances/my-pending` | `get_my_pending` |
| `app/api/v2/interview_agent.py:75` | POST | `/generate-questions` | `generate_interview_questions` |
| `app/api/v2/interview_agent.py:141` | POST | `/submit-answers` | `submit_and_evaluate` |
| `app/api/v2/interview_agent.py:226` | POST | `/evaluate-answer` | `evaluate_single_answer` |
| `app/api/v2/interview_agent.py:252` | GET | `/session/{session_id}` | `get_interview_session` |
| `app/api/v2/interview_bot.py:89` | POST | `/sessions` | `init_session` |
| `app/api/v2/interview_bot.py:125` | POST | `/sessions/{session_id}/start` | `start_session` |
| `app/api/v2/interview_bot.py:178` | POST | `/sessions/{session_id}/answer` | `submit_answer` |
| `app/api/v2/interview_bot.py:228` | POST | `/sessions/{session_id}/proctor-alert` | `proctor_alert` |
| `app/api/v2/interview_bot.py:270` | POST | `/sessions/{session_id}/finalize` | `finalize_session` |
| `app/api/v2/interview_ws.py:135` | WEBSOCKET | `/session/{token}` | `interview_websocket` |
| `app/api/v2/lms_api.py:60` | POST | `/courses` | `create_course` |
| `app/api/v2/lms_api.py:70` | POST | `/courses/{course_id}/modules` | `add_module` |
| `app/api/v2/lms_api.py:80` | POST | `/courses/{course_id}/publish` | `publish_course` |
| `app/api/v2/lms_api.py:92` | POST | `/courses/{course_id}/enrollments` | `enroll_employee` |
| `app/api/v2/lms_api.py:104` | POST | `/enrollments/{enrollment_id}/modules/{module_id}/complete` | `complete_module` |
| `app/api/v2/lms_api.py:116` | GET | `/certificates/{certificate_id}/pdf` | `download_certificate` |
| `app/api/v2/lms_api.py:134` | GET | `/compliance/status` | `compliance_training_status` |
| `app/api/v2/marketplace_api.py:35` | GET | `/catalog` | `marketplace_catalog` |
| `app/api/v2/marketplace_api.py:41` | GET | `/integrations` | `list_marketplace_integrations` |
| `app/api/v2/marketplace_api.py:47` | PUT | `/integrations/{connector_code}` | `configure_marketplace_integration` |
| `app/api/v2/marketplace_api.py:59` | POST | `/integrations/{connector_code}/enable` | `enable_marketplace_integration` |
| `app/api/v2/marketplace_api.py:69` | POST | `/integrations/{connector_code}/disable` | `disable_marketplace_integration` |
| `app/api/v2/marketplace_api.py:79` | POST | `/integrations/{connector_code}/sync` | `sync_marketplace_integration` |
| `app/api/v2/marketplace_api.py:92` | GET | `/integrations/{connector_code}/sync-logs` | `marketplace_sync_logs` |
| `app/api/v2/mobile_pwa_api.py:82` | POST | `/push-subscriptions` | `subscribe_push` |
| `app/api/v2/mobile_pwa_api.py:117` | POST | `/attendance/check-in` | `mobile_check_in` |
| `app/api/v2/mobile_pwa_api.py:125` | POST | `/attendance/check-out` | `mobile_check_out` |
| `app/api/v2/mobile_pwa_api.py:133` | GET | `/approvals` | `mobile_approval_cards` |
| `app/api/v2/mobile_pwa_api.py:167` | POST | `/approvals/leave/{leave_id}` | `mobile_leave_approval` |
| `app/api/v2/mobile_pwa_api.py:179` | POST | `/approvals/{step_id}` | `mobile_workflow_approval` |
| `app/api/v2/mobile_pwa_api.py:195` | POST | `/documents/camera` | `camera_document_upload` |
| `app/api/v2/mobile_pwa_api.py:214` | GET | `/payslips` | `mobile_payslips` |
| `app/api/v2/mobile_pwa_api.py:227` | GET | `/payslips/{run_id}` | `mobile_payslip_detail` |
| `app/api/v2/mobile_pwa_api.py:236` | GET | `/payslips/{run_id}/pdf` | `mobile_payslip_pdf` |
| `app/api/v2/offer_letters.py:68` | POST | `/generate` | `generate_offer_letter` |
| `app/api/v2/offer_letters.py:143` | GET | `/download/{filename}` | `download_offer_letter` |
| `app/api/v2/org_intelligence_apis.py:44` | POST | `/generate` | `generate_org_map` |
| `app/api/v2/org_intelligence_apis.py:81` | POST | `/analyze` | `analyze_skill_gap` |
| `app/api/v2/org_intelligence_apis.py:131` | POST | `/plans` | `create_shift_plan` |
| `app/api/v2/org_intelligence_apis.py:179` | POST | `/sync` | `sync_digital_twin` |
| `app/api/v2/org_intelligence_apis.py:213` | POST | `/simulate` | `simulate_org_twin` |
| `app/api/v2/org_intelligence_apis.py:237` | GET | `/simulations/{simulation_id}` | `get_org_twin_simulation` |
| `app/api/v2/payroll/accounting.py:25` | GET | `/accounting-export` | `export_accounting_entries` |
| `app/api/v2/payroll/accounting.py:80` | POST | `/gl-mappings` | `create_gl_mapping` |
| `app/api/v2/payroll/accounting.py:90` | POST | `/journals/build` | `build_payroll_journal` |
| `app/api/v2/payroll/accounting.py:100` | POST | `/journals/export` | `export_enterprise_journal` |
| `app/api/v2/payroll/accounting.py:110` | POST | `/expenses` | `post_expense` |
| `app/api/v2/payroll/accounting.py:120` | POST | `/reconciliations` | `reconcile_gl` |
| `app/api/v2/payroll/company_bank.py:24` | GET | `/companies/{companyId}/bank-accounts` | `get_company_bank_accounts` |
| `app/api/v2/payroll/compensation.py:32` | GET | `/compensations` | `list_compensations` |
| `app/api/v2/payroll/compensation.py:89` | GET | `/compensations/{employeeId}` | `get_employee_compensation` |
| `app/api/v2/payroll/compensation.py:112` | PUT | `/compensations/{employeeId}` | `update_employee_compensation` |
| `app/api/v2/payroll/compensation.py:136` | POST | `/compensation/bulk-import/preview` | `preview_compensation_bulk_import` |
| `app/api/v2/payroll/compensation.py:150` | POST | `/compensation/bulk-import/apply` | `apply_compensation_bulk_import` |
| `app/api/v2/payroll/compensation.py:172` | POST | `/compensation/revisions/{revisionId}/approve` | `approve_compensation_revision` |
| `app/api/v2/payroll/compensation.py:202` | POST | `/compensation/revisions/{revisionId}/reject` | `reject_compensation_revision` |
| `app/api/v2/payroll/cycles.py:55` | GET | `/cycles` | `list_payroll_cycles` |
| `app/api/v2/payroll/cycles.py:75` | POST | `/cycles` | `create_payroll_cycle` |
| `app/api/v2/payroll/cycles.py:105` | GET | `/cycles/{cycleId}` | `get_payroll_cycle` |
| `app/api/v2/payroll/cycles.py:117` | POST | `/cycles/{cycleId}/lock-attendance` | `lock_attendance_v2` |
| `app/api/v2/payroll/cycles.py:117` | POST | `/cycles/{cycleId}/attendance-lock` | `lock_attendance_v2` |
| `app/api/v2/payroll/cycles.py:132` | POST | `/cycles/{cycleId}/unlock-attendance` | `unlock_attendance_v2` |
| `app/api/v2/payroll/cycles.py:132` | POST | `/cycles/{cycleId}/attendance-unlock` | `unlock_attendance_v2` |
| `app/api/v2/payroll/cycles.py:148` | POST | `/cycles/{cycleId}/lock` | `lock_payroll_cycle` |
| `app/api/v2/payroll/cycles.py:167` | POST | `/cycles/{cycleId}/reopen` | `reopen_payroll_cycle` |
| `app/api/v2/payroll/cycles.py:188` | POST | `/cycles/{cycleId}/void` | `void_payroll_cycle` |
| `app/api/v2/payroll/employee_payroll.py:44` | GET | `/employee/dashboard` | `get_current_employee_dashboard` |
| `app/api/v2/payroll/employee_payroll.py:67` | GET | `/employee/provision-slips` | `get_current_employee_provision_slips` |
| `app/api/v2/payroll/employee_payroll.py:98` | GET | `/employees/{employeeId}/compensation` | `get_employee_compensation` |
| `app/api/v2/payroll/employee_payroll.py:127` | POST | `/employees/{employeeId}/compensation/revisions` | `create_employee_compensation_revision` |
| `app/api/v2/payroll/employee_payroll.py:158` | GET | `/employees/{employeeId}/payslips` | `get_employee_payslips_v2` |
| `app/api/v2/payroll/employee_payroll.py:196` | POST | `/employees/{employeeId}/reveal-bank-account` | `reveal_employee_bank_account` |
| `app/api/v2/payroll/full_and_final.py:63` | GET | `/full-and-final` | `list_full_and_final` |
| `app/api/v2/payroll/full_and_final.py:95` | POST | `/full-and-final` | `create_full_and_final` |
| `app/api/v2/payroll/full_and_final.py:121` | GET | `/full-and-final/{fnfId}` | `get_full_and_final` |
| `app/api/v2/payroll/full_and_final.py:133` | POST | `/full-and-final/{fnfId}/approve` | `approve_full_and_final` |
| `app/api/v2/payroll/full_and_final.py:155` | POST | `/full-and-final/{fnfId}/finalize` | `finalize_full_and_final` |
| `app/api/v2/payroll/full_and_final.py:177` | POST | `/full-and-final/{fnfId}/reject` | `reject_full_and_final` |
| `app/api/v2/payroll/full_and_final.py:198` | POST | `/full-and-final/{fnfId}/settle` | `settle_full_and_final` |
| `app/api/v2/payroll/full_and_final.py:218` | GET | `/full-and-final/{fnfId}/statement/download` | `download_full_and_final_statement` |
| `app/api/v2/payroll/pay_components.py:66` | GET | `/pay-components` | `list_pay_components` |
| `app/api/v2/payroll/pay_components.py:78` | POST | `/pay-components` | `create_pay_component` |
| `app/api/v2/payroll/pay_components.py:92` | PUT | `/pay-components/{id}` | `update_pay_component` |
| `app/api/v2/payroll/pay_components.py:106` | DELETE | `/pay-components/{id}` | `delete_pay_component` |
| `app/api/v2/payroll/pay_components.py:118` | POST | `/pay-components/evaluate-formula` | `evaluate_formula` |
| `app/api/v2/payroll/pay_components.py:145` | POST | `/pay-components/seed-defaults` | `seed_defaults` |
| `app/api/v2/payroll/payment_batches.py:76` | GET | `/payment-batches` | `list_payment_batches` |
| `app/api/v2/payroll/payment_batches.py:108` | GET | `/payment-batches/{batchId}` | `get_payment_batch` |
| `app/api/v2/payroll/payment_batches.py:160` | POST | `/payment-batches/{batchId}/approve` | `approve_payment_batch` |
| `app/api/v2/payroll/payment_batches.py:182` | POST | `/payment-batches/{batchId}/bank-file` | `generate_bank_file` |
| `app/api/v2/payroll/payment_batches.py:205` | GET | `/payment-batches/{batchId}/bank-file/download` | `download_bank_file` |
| `app/api/v2/payroll/payment_batches.py:227` | POST | `/payment-batches/{batchId}/bank-response/preview` | `preview_bank_response` |
| `app/api/v2/payroll/payment_batches.py:242` | POST | `/payment-batches/{batchId}/bank-response/apply` | `apply_bank_response` |
| `app/api/v2/payroll/payment_batches.py:264` | POST | `/payment-batches/{batchId}/items/{itemId}/hold` | `hold_batch_item` |
| `app/api/v2/payroll/payment_batches.py:287` | POST | `/payment-batches/{batchId}/items/{itemId}/release` | `release_batch_item` |
| `app/api/v2/payroll/payment_batches.py:311` | POST | `/payment-batches/{batchId}/items/{itemId}/retry` | `retry_batch_item` |
| `app/api/v2/payroll/payment_batches.py:340` | POST | `/payment-batches/{batchId}/reconcile` | `reconcile_payment_batch` |
| `app/api/v2/payroll/payment_batches.py:368` | POST | `/payment-batches/{batchId}/reject` | `reject_payment_batch` |
| `app/api/v2/payroll/payment_batches.py:389` | POST | `/payment-batches/{batchId}/submit` | `submit_payment_batch` |
| `app/api/v2/payroll/payment_batches.py:417` | POST | `/payment-batches/{batchId}/validate` | `validate_payment_batch` |
| `app/api/v2/payroll/payslips.py:50` | POST | `/runs/{run_id}/deliver-payslips` | `deliver_payslips_v2` |
| `app/api/v2/payroll/payslips.py:84` | GET | `/payslips/me/ytd` | `get_my_ytd_v2` |
| `app/api/v2/payroll/payslips.py:84` | GET | `/me/ytd` | `get_my_ytd_v2` |
| `app/api/v2/payroll/payslips.py:97` | GET | `/payslips/ytd/{employee_id}` | `get_employee_ytd_v2` |
| `app/api/v2/payroll/payslips.py:109` | GET | `/my-payslips` | `get_my_payslips_v2` |
| `app/api/v2/payroll/payslips.py:150` | GET | `/my-payslips/{runId}/download` | `download_my_payslip_v2` |
| `app/api/v2/payroll/payslips.py:169` | GET | `/my-provision-slips` | `get_my_provision_slips_v2` |
| `app/api/v2/payroll/payslips.py:200` | GET | `/payslips/{runId}/{employeeId}` | `get_payslip_detail_v2` |
| `app/api/v2/payroll/payslips.py:212` | GET | `/provision-slips/{provisionSlipId}/pdf` | `download_provision_slip_pdf` |
| `app/api/v2/payroll/reports.py:46` | GET | `/reports/comparison` | `get_parallel_payroll_comparison` |
| `app/api/v2/payroll/reports.py:72` | GET | `/reports/{reportKey}` | `get_payroll_report` |
| `app/api/v2/payroll/reports.py:129` | POST | `/reports/{reportKey}/export` | `export_payroll_report` |
| `app/api/v2/payroll/reports.py:151` | GET | `/reports/exports/{exportId}/download` | `download_report_export` |
| `app/api/v2/payroll/runs.py:109` | GET | `/runs` | `list_runs_v2` |
| `app/api/v2/payroll/runs.py:123` | POST | `/runs` | `create_run_v2` |
| `app/api/v2/payroll/runs.py:151` | GET | `/runs/{runId}` | `get_run_v2` |
| `app/api/v2/payroll/runs.py:163` | DELETE | `/runs/{runId}` | `delete_run_v2` |
| `app/api/v2/payroll/runs.py:175` | POST | `/runs/{runId}/cancel` | `cancel_run_v2` |
| `app/api/v2/payroll/runs.py:188` | GET | `/runs/{runId}/approval` | `get_run_approval_details` |
| `app/api/v2/payroll/runs.py:208` | POST | `/runs/{runId}/approve` | `approve_run_v2` |
| `app/api/v2/payroll/runs.py:231` | GET | `/runs/{runId}/employees` | `list_run_employees_v2` |
| `app/api/v2/payroll/runs.py:260` | GET | `/runs/{runId}/employees/{employeeId}` | `get_run_employee_v2` |
| `app/api/v2/payroll/runs.py:273` | GET | `/runs/{runId}/employees/{employeeId}/payslip` | `get_run_employee_payslip_v2` |
| `app/api/v2/payroll/runs.py:286` | GET | `/runs/{runId}/employees/{employeeId}/payslip/download` | `download_run_employee_payslip_v2` |
| `app/api/v2/payroll/runs.py:302` | GET | `/runs/{runId}/finalization` | `get_run_finalization_summary` |
| `app/api/v2/payroll/runs.py:323` | POST | `/runs/{runId}/finalize` | `finalize_run_v2` |
| `app/api/v2/payroll/runs.py:348` | GET | `/runs/{runId}/generation-status` | `get_run_generation_status` |
| `app/api/v2/payroll/runs.py:371` | POST | `/runs/{runId}/payment-batches` | `create_payment_batch_from_run` |
| `app/api/v2/payroll/runs.py:407` | GET | `/runs/{runId}/payment-batches` | `list_run_payment_batches` |
| `app/api/v2/payroll/runs.py:431` | POST | `/runs/{runId}/payslips/generate` | `generate_run_payslips_v2` |
| `app/api/v2/payroll/runs.py:453` | GET | `/runs/{runId}/preview` | `preview_run_v2` |
| `app/api/v2/payroll/runs.py:464` | POST | `/runs/{run_id}/parallel-compare` | `parallel_compare_run_v2` |
| `app/api/v2/payroll/runs.py:484` | POST | `/runs/{runId}/process` | `process_run_v2` |
| `app/api/v2/payroll/runs.py:498` | POST | `/runs/{runId}/calculate` | `calculate_run_sync_v2` |
| `app/api/v2/payroll/runs.py:513` | POST | `/runs/{runId}/submit-for-approval` | `submit_run_for_approval_v2` |
| `app/api/v2/payroll/runs.py:513` | POST | `/runs/{runId}/submit` | `submit_run_for_approval_v2` |
| `app/api/v2/payroll/runs.py:527` | POST | `/runs/{runId}/lock` | `lock_run_v2` |
| `app/api/v2/payroll/runs.py:544` | POST | `/runs/{runId}/mark-paid` | `mark_run_paid_v2` |
| `app/api/v2/payroll/runs.py:544` | POST | `/runs/{runId}/pay` | `mark_run_paid_v2` |
| `app/api/v2/payroll/runs.py:559` | POST | `/runs/{runId}/reject` | `reject_run_v2` |
| `app/api/v2/payroll/runs.py:581` | POST | `/runs/{runId}/revalidate` | `revalidate_run_v2` |
| `app/api/v2/payroll/runs.py:593` | GET | `/runs/{runId}/review` | `review_run_v2` |
| `app/api/v2/payroll/runs.py:606` | POST | `/runs/{runId}/send-back` | `send_back_run_v2` |
| `app/api/v2/payroll/runs.py:630` | POST | `/runs/{runId}/validate` | `validate_run_post_v2` |
| `app/api/v2/payroll/runs.py:642` | GET | `/runs/{runId}/validation` | `get_run_validation_v2` |
| `app/api/v2/payroll/runs.py:654` | GET | `/runs/{runId}/validation-issues` | `get_run_validation_issues_v2` |
| `app/api/v2/payroll/runs.py:691` | POST | `/entities/{legal_entity_id}/calendar` | `upsert_entity_calendar` |
| `app/api/v2/payroll/runs.py:711` | POST | `/entities/transfers` | `transfer_employee_entity` |
| `app/api/v2/payroll/runs.py:733` | POST | `/entities/transfers/process-due` | `process_entity_transfers` |
| `app/api/v2/payroll/salary_processing.py:29` | GET | `/salary-processing` | `get_salary_processing_list` |
| `app/api/v2/payroll/salary_processing.py:77` | GET | `/salary-processing/hero` | `get_salary_processing_hero` |
| `app/api/v2/payroll/salary_processing.py:90` | GET | `/salary-processing/kpis` | `get_salary_processing_kpis` |
| `app/api/v2/payroll/salary_processing.py:123` | GET | `/salary-processing/approval-workflow` | `get_salary_processing_approval_workflow` |
| `app/api/v2/payroll/salary_processing.py:162` | GET | `/salary-processing/ai-insights` | `get_salary_processing_ai_insights` |
| `app/api/v2/payroll/salary_processing.py:217` | GET | `/salary-processing/validations` | `get_salary_processing_validations` |
| `app/api/v2/payroll/salary_processing.py:257` | GET | `/salary-processing/analytics` | `get_salary_processing_analytics` |
| `app/api/v2/payroll/salary_processing.py:305` | POST | `/salary-processing/run` | `trigger_salary_processing_run` |
| `app/api/v2/payroll/salary_processing.py:313` | POST | `/salary-processing/approve` | `approve_salary_processing` |
| `app/api/v2/payroll/salary_processing.py:324` | POST | `/salary-processing/rollback` | `rollback_salary_processing` |
| `app/api/v2/payroll/salary_processing.py:332` | POST | `/salary-processing/recalculate/{employee_id}` | `recalculate_employee_salary` |
| `app/api/v2/payroll/salary_processing.py:340` | POST | `/salary-processing/resolve-exception/{exception_id}` | `resolve_salary_exception` |
| `app/api/v2/payroll/salary_processing.py:348` | POST | `/salary-processing/auto-fix` | `auto_fix_salary_processing` |
| `app/api/v2/payroll/salary_processing.py:356` | POST | `/salary-processing/batch-payout` | `batch_payout_salary_processing` |
| `app/api/v2/payroll/salary_processing.py:364` | POST | `/salary-processing/batch-approve` | `batch_approve_salary_processing` |
| `app/api/v2/payroll/salary_processing.py:372` | POST | `/salary-processing/batch-recalculate` | `batch_recalculate_salary_processing` |
| `app/api/v2/payroll/salary_processing.py:380` | POST | `/salary-processing/payslips` | `generate_payslips_for_processing` |
| `app/api/v2/payroll/salary_processing.py:388` | POST | `/salary-processing/bank-transfer` | `initiate_bank_transfer_from_processing` |
| `app/api/v2/payroll/salary_processing.py:396` | POST | `/salary-processing/export` | `export_salary_processing` |
| `app/api/v2/payroll/statutory.py:91` | GET | `/statutory/config` | `get_statutory_config` |
| `app/api/v2/payroll/statutory.py:105` | PUT | `/statutory/config` | `update_statutory_config` |
| `app/api/v2/payroll/statutory.py:105` | PATCH | `/statutory/config` | `update_statutory_config` |
| `app/api/v2/payroll/statutory.py:123` | POST | `/statutory/ca-signoff` | `ca_signoff_statutory_config` |
| `app/api/v2/payroll/statutory.py:165` | POST | `/statutory/simulate` | `simulate_statutory` |
| `app/api/v2/payroll/statutory.py:193` | POST | `/statutory/reports/{component}` | `generate_statutory_report` |
| `app/api/v2/payroll/statutory.py:218` | GET | `/statutory/summary` | `get_statutory_summary` |
| `app/api/v2/payroll/statutory.py:235` | GET | `/statutory/pf-ecr` | `get_pf_ecr` |
| `app/api/v2/payroll/statutory.py:266` | GET | `/statutory/pf-summary` | `get_pf_summary` |
| `app/api/v2/payroll/statutory.py:283` | GET | `/statutory/filing-calendar` | `get_filing_calendar` |
| `app/api/v2/payroll/statutory.py:300` | POST | `/statutory/challan/record` | `record_challan` |
| `app/api/v2/payroll/statutory.py:317` | POST | `/statutory/challan/upload` | `upload_challan_receipt` |
| `app/api/v2/payroll/statutory.py:340` | GET | `/statutory/uan-validation` | `get_uan_validation_audit` |
| `app/api/v2/payroll/statutory.py:354` | PATCH | `/statutory/employee-pf/{employee_id}` | `update_employee_pf_settings` |
| `app/api/v2/payroll/statutory.py:375` | GET | `/statutory/pf-ecr/download` | `download_pf_ecr` |
| `app/api/v2/payroll/statutory.py:400` | GET | `/statutory/esi-return` | `get_esi_return` |
| `app/api/v2/payroll/statutory.py:400` | GET | `/statutory/esi-return/download` | `get_esi_return` |
| `app/api/v2/payroll/statutory.py:421` | GET | `/statutory/esi-challan` | `generate_esi_challan` |
| `app/api/v2/payroll/statutory.py:436` | GET | `/statutory/esi-challan/download` | `download_esi_challan` |
| `app/api/v2/payroll/statutory.py:452` | GET | `/statutory/lwf-summary` | `get_lwf_summary` |
| `app/api/v2/payroll/statutory.py:477` | POST | `/statutory/form-138/draft` | `create_form138_draft` |
| `app/api/v2/payroll/statutory.py:494` | GET | `/statutory/form-138/download` | `download_form138` |
| `app/api/v2/payroll/statutory.py:529` | GET | `/statutory/form-130/download` | `download_form130` |
| `app/api/v2/payroll/statutory.py:553` | POST | `/statutory/form-130/generate` | `generate_form130` |
| `app/api/v2/payroll/statutory.py:584` | POST | `/statutory/form138/draft` | `create_form138_draft_alias` |
| `app/api/v2/payroll/statutory.py:589` | GET | `/statutory/form138/download` | `download_form138_alias` |
| `app/api/v2/payroll/statutory.py:594` | GET | `/statutory/form130/download` | `download_form130_alias` |
| `app/api/v2/payroll/statutory.py:599` | POST | `/statutory/tds/calculate` | `calculate_statutory_tds` |
| `app/api/v2/payroll/statutory.py:644` | GET | `/statutory/tax-rules/{financial_year}/{regime}` | `get_fy_tax_rule` |
| `app/api/v2/payroll/statutory.py:660` | PUT | `/statutory/tax-rules/{financial_year}/{regime}` | `put_fy_tax_rule` |
| `app/api/v2/payroll/statutory.py:669` | GET | `/statutory/state-rules/{state}` | `get_state_rule` |
| `app/api/v2/payroll/statutory.py:692` | PUT | `/statutory/state-rules/{state}` | `put_state_rule` |
| `app/api/v2/payroll/statutory.py:701` | POST | `/statutory/state-rules/seed` | `seed_state_rules` |
| `app/api/v2/payroll/statutory.py:725` | GET | `/statutory/compliance-calendar` | `get_compliance_calendar` |
| `app/api/v2/payroll/statutory.py:740` | POST | `/statutory/filings/{due_date_id}/track` | `track_statutory_filing` |
| `app/api/v2/payroll/statutory.py:756` | GET | `/statutory/challans/archive` | `get_statutory_challan_archive` |
| `app/api/v2/payroll/statutory.py:769` | GET | `/statutory/registers/{register_type}` | `generate_statutory_register_api` |
| `app/api/v2/payroll/variable_inputs.py:52` | GET | `/variable-inputs` | `list_variable_inputs` |
| `app/api/v2/payroll/variable_inputs.py:86` | POST | `/variable-inputs` | `create_variable_input` |
| `app/api/v2/payroll/variable_inputs.py:108` | POST | `/variable-inputs/bulk-preview` | `preview_variable_inputs_bulk` |
| `app/api/v2/payroll/variable_inputs.py:124` | POST | `/variable-inputs/bulk-apply` | `apply_variable_inputs_bulk` |
| `app/api/v2/payroll/variable_inputs.py:146` | POST | `/variable-inputs/{id}/approve` | `approve_variable_input` |
| `app/api/v2/payroll/variable_inputs.py:168` | POST | `/variable-inputs/{id}/reject` | `reject_variable_input` |
| `app/api/v2/performance_api.py:88` | POST | `/cycles` | `create_cycle` |
| `app/api/v2/performance_api.py:116` | POST | `/goals` | `create_goal_api` |
| `app/api/v2/performance_api.py:155` | PUT | `/goals/{id}` | `update_goal_api` |
| `app/api/v2/performance_api.py:193` | DELETE | `/goals/{id}` | `delete_goal_api` |
| `app/api/v2/performance_api.py:216` | POST | `/goals/assign` | `assign_goal_api` |
| `app/api/v2/performance_api.py:249` | POST | `/goals/{id}/complete` | `complete_goal_api` |
| `app/api/v2/performance_api.py:277` | POST | `/reviews` | `init_review` |
| `app/api/v2/performance_api.py:331` | PUT | `/reviews/{id}` | `update_review_api` |
| `app/api/v2/performance_api.py:364` | DELETE | `/reviews/{id}` | `delete_review_api` |
| `app/api/v2/performance_api.py:386` | POST | `/reviews/bulk-delete` | `bulk_delete_reviews_api` |
| `app/api/v2/performance_api.py:403` | POST | `/reviews/bulk-status` | `bulk_status_reviews_api` |
| `app/api/v2/performance_api.py:421` | POST | `/reviews/import` | `import_reviews_api` |
| `app/api/v2/performance_api.py:461` | POST | `/reviews/{review_id}/evaluate` | `evaluate_review` |
| `app/api/v2/performance_api.py:495` | GET | `` | `get_performance_data` |
| `app/api/v2/performance_api.py:719` | POST | `/enterprise/cycles` | `create_enterprise_cycle` |
| `app/api/v2/performance_api.py:729` | POST | `/enterprise/cycles/{cycle_id}/reviews` | `add_360_review` |
| `app/api/v2/performance_api.py:741` | POST | `/enterprise/reviews/{review_id}/submit` | `submit_360_review` |
| `app/api/v2/performance_api.py:753` | POST | `/enterprise/cycles/{cycle_id}/calibrate` | `calibrate_enterprise_cycle` |
| `app/api/v2/performance_api.py:763` | POST | `/enterprise/cycles/{cycle_id}/promotions` | `create_promotion` |
| `app/api/v2/performance_api.py:775` | POST | `/enterprise/promotions/{promotion_id}/decision` | `decide_promotion` |
| `app/api/v2/performance_api.py:794` | POST | `/feedback` | `create_feedback` |
| `app/api/v2/performance_api.py:868` | POST | `/rewards` | `create_reward` |
| `app/api/v2/performance_api.py:940` | POST | `/training/assign` | `assign_training` |
| `app/api/v2/performance_api.py:1019` | PATCH | `/training/{assignment_id}` | `update_training_assignment` |
| `app/api/v2/policy_api.py:48` | POST | `/documents` | `upload_policy` |
| `app/api/v2/policy_api.py:78` | POST | `/chat` | `query_chatbot` |
| `app/api/v2/policy_api.py:168` | POST | `/documents/versions` | `create_policy_version` |
| `app/api/v2/policy_api.py:183` | POST | `/documents/{policy_id}/publish` | `publish_policy` |
| `app/api/v2/policy_api.py:197` | GET | `/acknowledgements/pending` | `pending_policy_acknowledgements` |
| `app/api/v2/policy_api.py:216` | POST | `/documents/{policy_id}/acknowledge` | `acknowledge_policy` |
| `app/api/v2/policy_api.py:241` | GET | `/acknowledgements/{acceptance_id}/proof` | `policy_acknowledgement_proof` |
| `app/api/v2/policy_api.py:258` | POST | `/acknowledgements/reminders/run` | `trigger_policy_reminders` |
| `app/api/v2/productivity_api.py:50` | POST | `/logs` | `log_productivity` |
| `app/api/v2/productivity_api.py:87` | POST | `/forecast/{employee_id}` | `compile_forecast` |
| `app/api/v2/ranking.py:59` | POST | `/rank` | `rank_candidates` |
| `app/api/v2/ranking.py:140` | GET | `/top/{job_id}` | `get_ranked_candidates` |
| `app/api/v2/reports_api.py:127` | GET | `` | `list_reports` |
| `app/api/v2/reports_api.py:157` | GET | `/stats` | `get_report_stats` |
| `app/api/v2/reports_api.py:175` | POST | `` | `create_report` |
| `app/api/v2/reports_api.py:202` | POST | `/{id}/refresh` | `refresh_report` |
| `app/api/v2/reports_api.py:221` | DELETE | `/{id}` | `delete_report` |
| `app/api/v2/reports_api.py:243` | API_ROUTE | `/analytics/headcount` | `get_headcount_analytics` |
| `app/api/v2/reports_api.py:272` | API_ROUTE | `/analytics/department` | `get_department_analytics` |
| `app/api/v2/reports_api.py:301` | API_ROUTE | `/analytics/tenure` | `get_tenure_analytics` |
| `app/api/v2/reports_api.py:330` | API_ROUTE | `/analytics/turnover` | `get_turnover_analytics` |
| `app/api/v2/reports_api.py:357` | API_ROUTE | `/analytics/payroll-cost` | `get_payroll_cost_analytics` |
| `app/api/v2/reports_api.py:382` | API_ROUTE | `/analytics/compliance` | `get_compliance_analytics` |
| `app/api/v2/reports_api.py:406` | GET | `/export` | `export_analytics_dataset` |
| `app/api/v2/resume_ats_checker.py:47` | POST | `/check` | `check_resume_ats` |
| `app/api/v2/resume_parser.py:56` | POST | `/upload-and-parse` | `upload_and_parse_resume` |
| `app/api/v2/resume_parser.py:261` | GET | `/{document_id}` | `get_parsed_resume` |
| `app/api/v2/resume_parser.py:303` | GET | `/ocr/engines/status` | `get_ocr_status` |
| `app/api/v2/scim_api.py:84` | POST | `/tokens` | `create_scim_token` |
| `app/api/v2/scim_api.py:96` | DELETE | `/tokens/{token_id}` | `revoke_scim_token` |
| `app/api/v2/scim_api.py:106` | GET | `/Users` | `list_users` |
| `app/api/v2/scim_api.py:117` | POST | `/Users` | `create_user` |
| `app/api/v2/scim_api.py:126` | GET | `/Users/{user_id}` | `get_user` |
| `app/api/v2/scim_api.py:134` | PUT | `/Users/{user_id}` | `replace_user` |
| `app/api/v2/scim_api.py:142` | PATCH | `/Users/{user_id}` | `patch_user` |
| `app/api/v2/scim_api.py:150` | DELETE | `/Users/{user_id}` | `deprovision_user` |
| `app/api/v2/scim_api.py:159` | GET | `/Groups` | `list_groups` |
| `app/api/v2/scim_api.py:167` | POST | `/Groups` | `create_group` |
| `app/api/v2/scim_api.py:176` | GET | `/Groups/{group_id}` | `get_group` |
| `app/api/v2/scim_api.py:184` | PUT | `/Groups/{group_id}` | `replace_group` |
| `app/api/v2/scim_api.py:192` | PATCH | `/Groups/{group_id}` | `patch_group` |
| `app/api/v2/scim_api.py:200` | DELETE | `/Groups/{group_id}` | `delete_group` |
| `app/api/v2/screening.py:446` | POST | `/screen` | `screen_candidate` |
| `app/api/v2/screening.py:617` | POST | `/batch-screen` | `batch_screen_candidates` |
| `app/api/v2/screening.py:813` | POST | `/jobs/{job_id}/run` | `run_job_screening` |
| `app/api/v2/screening.py:878` | GET | `/jobs/{job_id}/results` | `get_job_screening_results` |
| `app/api/v2/screening.py:1019` | POST | `/results/{screening_id}/decision` | `submit_human_decision` |
| `app/api/v2/screening.py:1122` | GET | `/history/{application_id}` | `get_screening_history` |
| `app/api/v2/succession_api.py:45` | POST | `/roles` | `create_role` |
| `app/api/v2/succession_api.py:55` | POST | `/roles/{role_id}/successors` | `add_successor` |
| `app/api/v2/succession_api.py:65` | POST | `/slates/{slate_id}/development-actions` | `add_development_action` |
| `app/api/v2/succession_api.py:75` | PATCH | `/development-actions/{action_id}` | `update_development_action` |
| `app/api/v2/succession_api.py:85` | GET | `/risk-map` | `leadership_risk_map` |
| `app/api/v2/tax_api.py:49` | GET | `/profile/{employee_id}` | `get_employee_tax_profile` |
| `app/api/v2/tax_api.py:235` | POST | `/calculate` | `run_tax_calculation` |
| `app/api/v2/tax_api.py:297` | POST | `/declarations/{declaration_id}/approve` | `approve_tax_declaration` |
| `app/api/v2/tax_api.py:340` | POST | `/declarations/{declaration_id}/reject` | `reject_tax_declaration` |
| `app/api/v2/tax_api.py:379` | POST | `/proofs/{proof_id}/verify` | `verify_tax_proof` |
| `app/api/v2/tax_api.py:430` | POST | `/year-end-process` | `run_year_end_process` |
| `app/api/v2/tax_api.py:451` | GET | `/audit-logs/{employee_id}` | `get_tax_audit_logs` |
| `app/api/v2/tax_api.py:501` | POST | `/declarations/{employee_id}` | `upsert_tax_declaration` |
| `app/api/v2/tax_api.py:541` | POST | `/declarations/{declaration_id}/proofs` | `upload_tax_proof` |
| `app/api/v2/tax_api.py:573` | GET | `/declarations/{declaration_id}/proofs` | `list_tax_proofs` |
| `app/api/v2/tax_api.py:584` | POST | `/declarations/{declaration_id}/submit` | `submit_tax_declaration` |
| `app/api/v2/travel_api.py:113` | GET | `` | `list_travel_requests` |
| `app/api/v2/travel_api.py:157` | GET | `/stats` | `get_travel_stats` |
| `app/api/v2/travel_api.py:205` | POST | `` | `create_travel_request` |
| `app/api/v2/travel_api.py:258` | PUT | `/{id}` | `update_travel_request` |
| `app/api/v2/travel_api.py:311` | POST | `/{id}/advance` | `advance_travel_request` |
| `app/api/v2/travel_api.py:353` | DELETE | `/{id}` | `delete_travel_request` |
| `app/api/v2/wellness_api.py:228` | POST | `/checkins` | `wellness_checkin` |
| `app/api/v2/wellness_api.py:276` | POST | `/escalation-rules` | `create_escalation_rule` |
| `app/api/v2/wellness_api.py:323` | POST | `/anonymous-chats` | `init_chat` |
| `app/api/v2/wellness_api.py:359` | POST | `/anonymous-chats/{session_id}/messages` | `send_message` |
| `app/api/v2/whatsapp_api.py:16` | GET | `/webhook` | `verify_whatsapp_webhook` |
| `app/api/v2/whatsapp_api.py:33` | POST | `/webhook` | `receive_whatsapp_webhook` |
| `app/api/v2/whitelabel_api.py:34` | GET | `` | `get_whitelabel` |
| `app/api/v2/whitelabel_api.py:44` | PUT | `` | `update_whitelabel` |
| `app/api/v2/whitelabel_api.py:54` | GET | `/preview.pdf` | `preview_whitelabel_pdf` |
| `app/api/vendors/create.py:26` | POST | `` | `create_vendor` |
| `app/api/vendors/delete.py:23` | DELETE | `/{id}` | `delete_vendor` |
| `app/api/vendors/read.py:24` | GET | `/{id}` | `get_vendor` |
| `app/api/vendors/read.py:45` | GET | `` | `list_vendors` |
| `app/api/vendors/update.py:27` | PUT | `/{id}` | `update_vendor` |
| `app/attendance/routers/analytics.py:37` | GET | `/face/analytics` | `get_attendance_analytics` |
| `app/attendance/routers/analytics.py:59` | GET | `/analytics/rate` | `get_attendance_rate` |
| `app/attendance/routers/analytics.py:86` | GET | `/analytics/distribution` | `get_attendance_distribution` |
| `app/attendance/routers/analytics.py:113` | GET | `/analytics/weekly` | `get_attendance_weekly` |
| `app/attendance/routers/analytics.py:140` | GET | `/analytics/trends` | `get_attendance_trends` |
| `app/attendance/routers/breaks.py:41` | POST | `/start` | `start_break` |
| `app/attendance/routers/breaks.py:95` | POST | `/end` | `end_break` |
| `app/attendance/routers/checkin.py:129` | POST | `/face/check-in` | `ai_face_check_in` |
| `app/attendance/routers/checkout.py:126` | POST | `/face/check-out` | `ai_face_check_out` |
| `app/attendance/routers/company.py:43` | GET | `/face/company` | `get_company_attendance_history` |
| `app/attendance/routers/enrollment.py:43` | GET | `/face-status` | `get_face_status` |
| `app/attendance/routers/enrollment.py:94` | POST | `/face-enroll` | `face_enroll` |
| `app/attendance/routers/geofence.py:40` | POST | `/verify` | `verify_geofence` |
| `app/attendance/routers/history.py:39` | GET | `/face/history` | `get_attendance_history` |
| `app/attendance/routers/me.py:79` | GET | `/shifts/me/schedule` | `get_my_shift_schedule` |
| `app/attendance/routers/me.py:216` | POST | `/shifts/change-requests` | `create_shift_change_request` |
| `app/attendance/routers/me.py:330` | GET | `/face/me` | `get_today_punch_state` |
| `app/attendance/routers/rosters.py:111` | GET | `/rosters` | `list_rosters` |
| `app/attendance/routers/rosters.py:227` | POST | `/rosters` | `create_roster_entry` |
| `app/attendance/routers/rosters.py:377` | POST | `/rosters/bulk` | `bulk_create_rosters` |
| `app/attendance/routers/rosters.py:538` | GET | `/rosters/{roster_id}` | `get_roster_entry` |
| `app/attendance/routers/rosters.py:603` | PUT | `/rosters/{roster_id}` | `update_roster_entry` |
| `app/attendance/routers/rosters.py:742` | PATCH | `/rosters/{roster_id}` | `patch_roster_entry` |
| `app/attendance/routers/rosters.py:759` | DELETE | `/rosters/{roster_id}` | `delete_roster_entry` |
| `app/attendance/routers/shifts.py:104` | GET | `/shifts/options` | `get_shifts_options` |
| `app/attendance/routers/shifts.py:140` | GET | `/shifts` | `list_shifts` |
| `app/attendance/routers/shifts.py:203` | POST | `/shifts` | `create_shift` |
| `app/attendance/routers/shifts.py:315` | GET | `/shifts/{shift_id}` | `get_shift` |
| `app/attendance/routers/shifts.py:364` | PUT | `/shifts/{shift_id}` | `update_shift` |
| `app/attendance/routers/shifts.py:482` | PATCH | `/shifts/{shift_id}` | `patch_shift` |
| `app/attendance/routers/shifts.py:499` | DELETE | `/shifts/{shift_id}` | `delete_shift` |
| `app/attendance/routers/team.py:40` | GET | `/face/team` | `get_team_attendance_history` |
| `app/main.py:616` | GET | `/api/v1/analytics/recruitment` | `get_alternate_recruitment_dashboard` |
| `app/main.py:616` | GET | `/analytics/recruitment` | `get_alternate_recruitment_dashboard` |
| `app/main.py:616` | GET | `/api/v1/dashboard/recruitment` | `get_alternate_recruitment_dashboard` |
| `app/main.py:616` | GET | `/dashboard/recruitment` | `get_alternate_recruitment_dashboard` |
| `app/main.py:644` | API_ROUTE | `/health` | `health_check` |
| `app/main.py:682` | GET | `/health/ready` | `health_ready` |
| `app/main.py:730` | API_ROUTE | `/` | `root` |
| `app/main.py:742` | GET | `/favicon.ico` | `favicon` |
| `app/main.py:747` | GET | `/api/v1/cors-debug` | `cors_debug` |
| `app/main.py:484` | GET | `/docs` | `disable_docs_explicitly` |
| `app/main.py:484` | GET | `/redoc` | `disable_docs_explicitly` |
| `app/main.py:484` | GET | `/openapi.json` | `disable_docs_explicitly` |
| `app/main.py:484` | GET | `/api/v1/openapi.json` | `disable_docs_explicitly` |
| `app/main.py:484` | GET | `/api/v2/openapi.json` | `disable_docs_explicitly` |
| `app/routers/analytics.py:32` | GET | `/dashboard` | `get_analytics_dashboard` |
| `app/routers/analytics.py:44` | GET | `/headcount` | `get_headcount_metric` |
| `app/routers/analytics.py:57` | GET | `/attendance` | `get_attendance_metric` |
| `app/routers/analytics.py:70` | GET | `/performance` | `get_performance_metric` |
| `app/routers/analytics.py:82` | GET | `/payroll` | `get_payroll_metric` |
| `app/routers/analytics.py:94` | GET | `/realtime` | `get_realtime_metrics` |
| `app/routers/analytics.py:107` | GET | `/export` | `export_analytics` |
| `app/routers/analytics.py:138` | GET | `/overview` | `get_generic_metric` |
| `app/routers/analytics.py:138` | GET | `/employees` | `get_generic_metric` |
| `app/routers/analytics.py:138` | GET | `/leave` | `get_generic_metric` |
| `app/routers/analytics.py:138` | GET | `/recruitment` | `get_generic_metric` |
| `app/routers/analytics.py:138` | GET | `/attrition` | `get_generic_metric` |
| `app/routers/analytics.py:138` | GET | `/retention` | `get_generic_metric` |
| `app/routers/analytics.py:138` | GET | `/turnover` | `get_generic_metric` |
| `app/routers/analytics.py:138` | GET | `/departments` | `get_generic_metric` |
| `app/routers/analytics.py:138` | GET | `/designations` | `get_generic_metric` |
| `app/routers/analytics.py:138` | GET | `/workforce` | `get_generic_metric` |
| `app/routers/analytics.py:138` | GET | `/productivity` | `get_generic_metric` |
| `app/routers/analytics.py:138` | GET | `/overtime` | `get_generic_metric` |
| `app/routers/analytics.py:138` | GET | `/absenteeism` | `get_generic_metric` |
| `app/routers/analytics.py:138` | GET | `/trends` | `get_generic_metric` |
| `app/routers/analytics.py:138` | GET | `/monthly` | `get_generic_metric` |
| `app/routers/analytics.py:138` | GET | `/yearly` | `get_generic_metric` |
| `app/routers/analytics.py:138` | GET | `/comparison` | `get_generic_metric` |
| `app/routers/assets.py:32` | GET | `` | `list_assets` |
| `app/routers/assets.py:32` | GET | `/` | `list_assets` |
| `app/routers/attendance.py:44` | GET | `/me` | `get_my_attendance` |
| `app/routers/attendance.py:58` | GET | `/status` | `get_attendance_status` |
| `app/routers/attendance.py:80` | GET | `/today` | `get_today_company_attendance` |
| `app/routers/attendance.py:94` | GET | `/history` | `get_attendance_history` |
| `app/routers/attendance.py:111` | GET | `/team` | `get_team_attendance` |
| `app/routers/attendance.py:125` | GET | `/company` | `get_company_attendance` |
| `app/routers/attendance.py:139` | GET | `/records` | `get_all_records` |
| `app/routers/attendance.py:157` | GET | `/analytics` | `get_attendance_analytics` |
| `app/routers/attendance.py:157` | GET | `/summary` | `get_attendance_analytics` |
| `app/routers/attendance.py:169` | GET | `/analytics/trends` | `get_attendance_analytics_trends` |
| `app/routers/attendance.py:182` | GET | `/analytics/rate` | `get_attendance_analytics_rate` |
| `app/routers/attendance.py:195` | GET | `/analytics/weekly` | `get_attendance_analytics_weekly` |
| `app/routers/attendance.py:207` | GET | `/calendar` | `get_attendance_calendar` |
| `app/routers/attendance.py:222` | GET | `/late` | `get_late_records` |
| `app/routers/attendance.py:235` | GET | `/early-leaving` | `get_early_leaving_records` |
| `app/routers/attendance.py:248` | GET | `/missing` | `get_missing_punch_records` |
| `app/routers/attendance.py:261` | GET | `/overtime` | `get_overtime_records` |
| `app/routers/attendance.py:274` | GET | `/export` | `export_attendance` |
| `app/routers/attendance.py:319` | POST | `/check-in` | `check_in` |
| `app/routers/attendance.py:335` | POST | `/check-out` | `check_out` |
| `app/routers/attendance.py:352` | PUT | `/{attendance_id}` | `update_attendance_record` |
| `app/routers/attendance.py:352` | PATCH | `/{attendance_id}` | `update_attendance_record` |
| `app/routers/attendance.py:367` | DELETE | `/{attendance_id}` | `delete_attendance_record` |
| `app/routers/attendance.py:382` | GET | `/regularization` | `list_regularization_requests` |
| `app/routers/attendance.py:396` | POST | `/regularization` | `create_regularization_request` |
| `app/routers/compliance.py:33` | GET | `` | `list_compliance` |
| `app/routers/compliance.py:33` | GET | `/` | `list_compliance` |
| `app/routers/compliance.py:46` | GET | `/dashboard` | `get_compliance_dashboard` |
| `app/routers/compliance.py:57` | GET | `/status` | `get_compliance_status` |
| `app/routers/compliance.py:68` | GET | `/documents` | `list_compliance_documents` |
| `app/routers/dashboard.py:33` | GET | `` | `get_landing_dashboard` |
| `app/routers/dashboard.py:33` | GET | `/` | `get_landing_dashboard` |
| `app/routers/documents.py:32` | GET | `` | `list_company_documents` |
| `app/routers/documents.py:32` | GET | `/` | `list_company_documents` |
| `app/routers/employee_health.py:36` | GET | `` | `get_health_overview` |
| `app/routers/employee_health.py:36` | GET | `/` | `get_health_overview` |
| `app/routers/employee_health.py:47` | GET | `/profile` | `get_my_health_profile` |
| `app/routers/employee_health.py:61` | GET | `/records` | `list_health_records` |
| `app/routers/employee_health.py:77` | GET | `/analytics` | `get_health_analytics` |
| `app/routers/employee_health.py:103` | GET | `/dashboard` | `get_employee_health_dashboard` |
| `app/routers/employee_health.py:103` | POST | `/dashboard` | `get_employee_health_dashboard` |
| `app/routers/employee_health.py:132` | GET | `/kpi` | `get_employee_health_kpis` |
| `app/routers/employee_health.py:132` | POST | `/kpi` | `get_employee_health_kpis` |
| `app/routers/employee_health.py:183` | GET | `/burnout-trend` | `get_employee_burnout_trend` |
| `app/routers/employee_health.py:183` | POST | `/burnout-trend` | `get_employee_burnout_trend` |
| `app/routers/employee_health.py:216` | GET | `/overtime` | `get_employee_overtime` |
| `app/routers/employee_health.py:216` | POST | `/overtime` | `get_employee_overtime` |
| `app/routers/holidays.py:32` | GET | `` | `list_holidays` |
| `app/routers/holidays.py:32` | GET | `/` | `list_holidays` |
| `app/routers/leave_assistant.py:34` | GET | `` | `get_leave_assistant_status` |
| `app/routers/leave_assistant.py:34` | GET | `/` | `get_leave_assistant_status` |
| `app/routers/leave_assistant.py:43` | POST | `/query` | `query_leave_assistant` |
| `app/routers/leave_assistant.py:56` | POST | `/apply` | `apply_leave_natural_language` |
| `app/routers/leave_assistant.py:69` | GET | `/history` | `get_leave_query_history` |
| `app/routers/managers.py:32` | GET | `/team` | `get_manager_team` |
| `app/routers/managers.py:45` | GET | `/dashboard` | `get_manager_dashboard` |
| `app/routers/meeting_intelligence.py:36` | GET | `` | `get_meeting_intelligence_status` |
| `app/routers/meeting_intelligence.py:36` | GET | `/` | `get_meeting_intelligence_status` |
| `app/routers/meeting_intelligence.py:45` | POST | `/analyze` | `analyze_meeting_transcript` |
| `app/routers/meeting_intelligence.py:58` | GET | `/meetings` | `list_recent_meetings` |
| `app/routers/meeting_intelligence.py:72` | GET | `/insights` | `get_meeting_insights` |
| `app/routers/meeting_intelligence.py:98` | GET | `/dashboard` | `get_meeting_dashboard` |
| `app/routers/meeting_intelligence.py:98` | POST | `/dashboard` | `get_meeting_dashboard` |
| `app/routers/meeting_intelligence.py:126` | GET | `/kpi` | `get_meeting_kpis` |
| `app/routers/meeting_intelligence.py:126` | POST | `/kpi` | `get_meeting_kpis` |
| `app/routers/meeting_intelligence.py:177` | GET | `/action-items` | `get_meeting_action_items` |
| `app/routers/meeting_intelligence.py:177` | POST | `/action-items` | `get_meeting_action_items` |
| `app/routers/meeting_intelligence.py:212` | GET | `/volume` | `get_meeting_volume_analytics` |
| `app/routers/meeting_intelligence.py:212` | POST | `/volume` | `get_meeting_volume_analytics` |
| `app/routers/notifications.py:76` | GET | `/stream` | `stream_notifications` |
| `app/routers/notifications.py:183` | GET | `/unread-count` | `get_unread_count` |
| `app/routers/notifications.py:198` | GET | `/unread` | `list_legacy_unread_notifications` |
| `app/routers/notifications.py:215` | POST | `/read-all` | `mark_all_read` |
| `app/routers/notifications.py:233` | POST | `/read` | `mark_many_read` |
| `app/routers/notifications.py:254` | GET | `` | `list_notifications` |
| `app/routers/notifications.py:254` | GET | `/` | `list_notifications` |
| `app/routers/notifications.py:290` | POST | `/{id}/read` | `mark_notification_read` |
| `app/routers/notifications.py:307` | POST | `/{id}/unread` | `mark_notification_unread` |
| `app/routers/notifications.py:324` | POST | `/{id}/archive` | `archive_notification` |
| `app/routers/performance.py:40` | GET | `/` | `get_performance_dashboard` |
| `app/routers/performance.py:40` | GET | `/dashboard` | `get_performance_dashboard` |
| `app/routers/performance.py:53` | GET | `/goals` | `list_goals` |
| `app/routers/performance.py:67` | POST | `/goals` | `create_goal` |
| `app/routers/performance.py:78` | PUT | `/goals/{id}` | `update_goal` |
| `app/routers/performance.py:90` | DELETE | `/goals/{id}` | `delete_goal` |
| `app/routers/performance.py:105` | GET | `/reviews` | `list_reviews` |
| `app/routers/performance.py:119` | POST | `/reviews` | `create_review` |
| `app/routers/performance.py:130` | GET | `/reviews/{id}` | `get_review` |
| `app/routers/performance.py:150` | PUT | `/reviews/{id}` | `update_review` |
| `app/routers/performance.py:164` | GET | `/kpis` | `list_kpis` |
| `app/routers/performance.py:176` | POST | `/kpis` | `create_kpi` |
| `app/routers/performance.py:191` | GET | `/ratings` | `get_performance_ratings` |
| `app/routers/performance.py:201` | GET | `/team` | `get_team_performance` |
| `app/routers/performance.py:210` | GET | `/history` | `get_performance_history` |
| `app/routers/performance.py:223` | GET | `/analytics` | `get_performance_analytics` |
| `app/routers/performance_coach.py:34` | GET | `` | `get_performance_coach_status` |
| `app/routers/performance_coach.py:34` | GET | `/` | `get_performance_coach_status` |
| `app/routers/performance_coach.py:43` | POST | `/chat` | `chat_with_coach` |
| `app/routers/performance_coach.py:56` | GET | `/recommendations` | `get_coaching_recommendations` |
| `app/routers/performance_coach.py:68` | GET | `/progress` | `get_coaching_progress` |
| `app/routers/policy_assistant.py:34` | GET | `` | `get_policy_assistant_status` |
| `app/routers/policy_assistant.py:34` | GET | `/` | `get_policy_assistant_status` |
| `app/routers/policy_assistant.py:43` | POST | `/query` | `query_policy_assistant` |
| `app/routers/policy_assistant.py:56` | GET | `/policies` | `list_policies` |
| `app/routers/profile.py:26` | GET | `` | `get_my_profile` |
| `app/routers/profile.py:26` | GET | `/` | `get_my_profile` |
| `app/routers/profile.py:57` | PUT | `` | `update_my_profile` |
| `app/routers/profile.py:57` | PUT | `/` | `update_my_profile` |
| `app/routers/profile.py:75` | GET | `/documents` | `get_profile_documents` |
| `app/routers/profile.py:97` | GET | `/assets` | `get_profile_assets` |
| `app/routers/profile.py:112` | GET | `/activity` | `get_profile_activity` |
| `app/routers/recruiter.py:33` | GET | `/jobs` | `list_jobs` |
| `app/routers/recruiter.py:47` | POST | `/jobs` | `create_job` |
| `app/routers/recruiter.py:60` | GET | `/candidates` | `list_candidates` |
| `app/routers/reports.py:34` | GET | `` | `list_available_reports` |
| `app/routers/reports.py:34` | GET | `/` | `list_available_reports` |
| `app/routers/reports.py:46` | GET | `/attendance` | `get_attendance_report` |
| `app/routers/reports.py:60` | GET | `/export` | `export_report_async` |
| `app/routers/settings.py:117` | GET | `/` | `get_settings` |
| `app/routers/settings.py:128` | PUT | `/` | `update_settings` |
| `app/routers/settings.py:147` | GET | `/company` | `get_settings_section` |
| `app/routers/settings.py:147` | GET | `/profile` | `get_settings_section` |
| `app/routers/settings.py:147` | GET | `/attendance` | `get_settings_section` |
| `app/routers/settings.py:147` | GET | `/leave` | `get_settings_section` |
| `app/routers/settings.py:147` | GET | `/payroll` | `get_settings_section` |
| `app/routers/settings.py:147` | GET | `/security` | `get_settings_section` |
| `app/routers/settings.py:147` | GET | `/workflow` | `get_settings_section` |
| `app/routers/settings.py:164` | PUT | `/company` | `update_settings_section_endpoint` |
| `app/routers/settings.py:164` | PUT | `/profile` | `update_settings_section_endpoint` |
| `app/routers/settings.py:164` | PUT | `/attendance` | `update_settings_section_endpoint` |
| `app/routers/settings.py:164` | PUT | `/leave` | `update_settings_section_endpoint` |
| `app/routers/settings.py:164` | PUT | `/payroll` | `update_settings_section_endpoint` |
| `app/routers/settings.py:164` | PUT | `/security` | `update_settings_section_endpoint` |
| `app/routers/settings.py:164` | PUT | `/workflow` | `update_settings_section_endpoint` |
| `app/routers/settings.py:179` | GET | `/employment-types` | `list_employment_types` |
| `app/routers/settings.py:190` | POST | `/employment-types` | `create_employment_type` |
| `app/routers/settings.py:205` | GET | `/designations` | `list_designations` |
| `app/routers/settings.py:216` | POST | `/designations` | `create_designation` |
| `app/routers/settings.py:231` | GET | `/holidays` | `list_holidays` |
| `app/routers/settings.py:242` | POST | `/holidays` | `create_holiday` |
| `app/routers/settings.py:269` | POST | `/company/logo` | `upload_company_logo` |
| `app/routers/settings.py:299` | GET | `/employees` | `get_employee_settings` |
| `app/routers/settings.py:325` | PUT | `/employees` | `update_employee_settings` |
| `app/routers/settings.py:357` | GET | `/leaves` | `get_leave_settings` |
| `app/routers/settings.py:384` | PUT | `/leaves` | `update_leave_settings` |
| `app/routers/settings.py:417` | GET | `/documents` | `get_document_settings` |
| `app/routers/settings.py:442` | PUT | `/documents` | `update_document_settings` |
| `app/routers/settings.py:473` | GET | `/assets` | `get_asset_settings` |
| `app/routers/settings.py:499` | PUT | `/assets` | `update_asset_settings` |
| `app/routers/users.py:39` | GET | `` | `list_users` |
| `app/routers/users.py:39` | GET | `/` | `list_users` |
| `app/routers/users.py:54` | GET | `/me` | `get_current_user_details` |
| `app/routers/users.py:77` | POST | `/me/avatar` | `upload_avatar` |
| `app/routers/users.py:94` | GET | `/{id}` | `get_user_by_id` |
| `app/routers/users.py:115` | PUT | `/{id}` | `update_user` |
| `app/routers/workforce_insights.py:36` | GET | `` | `get_workforce_summary` |
| `app/routers/workforce_insights.py:36` | GET | `/` | `get_workforce_summary` |
| `app/routers/workforce_insights.py:36` | GET | `/workforce` | `get_workforce_summary` |
| `app/routers/workforce_insights.py:48` | GET | `/headcount` | `get_headcount_insights` |
| `app/routers/workforce_insights.py:60` | GET | `/trends` | `get_workforce_trends` |
| `app/routers/workforce_insights.py:86` | GET | `/dashboard` | `get_workforce_dashboard` |
| `app/routers/workforce_insights.py:86` | POST | `/dashboard` | `get_workforce_dashboard` |
| `app/routers/workforce_insights.py:126` | GET | `/kpi` | `get_workforce_kpis` |
| `app/routers/workforce_insights.py:126` | POST | `/kpi` | `get_workforce_kpis` |
| `app/routers/workforce_insights.py:182` | GET | `/headcount-trends` | `get_workforce_headcount_trends` |
| `app/routers/workforce_insights.py:182` | POST | `/headcount-trends` | `get_workforce_headcount_trends` |
| `app/routers/workforce_insights.py:220` | GET | `/department-comparison` | `get_workforce_department_comparison` |
| `app/routers/workforce_insights.py:220` | POST | `/department-comparison` | `get_workforce_department_comparison` |
## Appendix D — Potential static import cycles (not proven runtime failures)
- `app.db.base`, `app.models.asset`, `app.models.asset.asset`, `app.models.asset.assignment`, `app.models.asset.maintenance`, `app.models.asset.request`, `app.models.company`, `app.models.department`, `app.models.document`, `app.models.document.audit`, `app.models.document.category`, `app.models.document.company`, `app.models.document.expiry`, `app.models.document.signature`, `app.models.document.template`, `app.models.document.verification`, `app.models.document.version`, `app.models.employee`, `app.models.employee_address`, `app.models.employee_bank_account`, `app.models.employee_document`, `app.models.employee_education`, `app.models.employee_emergency_contact`, `app.models.employee_experience`, `app.models.employee_leave_policy`, `app.models.employee_onboarding`, `app.models.employee_skill`, `app.models.manager`, `app.models.manager_address`, `app.models.manager_document`, `app.models.manager_education`, `app.models.manager_emergency_contact`, `app.models.manager_experience`, `app.models.manager_skill`, `app.models.otp`, `app.models.password_reset`, `app.models.refresh_token`, `app.models.shift`, `app.models.user`, `app.models.user.mixins.relations`
- `app.models.ai_copilot.document`, `app.models.ai_copilot.embedding`, `app.models.ai_copilot.match`, `app.models.ai_copilot.question`, `app.models.ai_copilot.ranking`
- `app.models.calendar.event`, `app.models.calendar.meeting`, `app.models.calendar.participant`, `app.models.calendar.reminder`
- `app.models.ai_document_analysis.document`, `app.models.ai_document_analysis.mixins.relations`, `app.models.ai_document_analysis.version`
- `app.attendance.models.attendance`, `app.attendance.models.attendance_break`
- `app.models.payroll`, `app.models.payroll_models`
