# Backend Master Implementation Pending Tracker

| ID | Status (TODO/DONE/BLOCKED/DONE-EXISTING) | Files changed | Tests added | Notes |
| :--- | :--- | :--- | :--- | :--- |
| **B-00.1** | DONE | `scripts/generate_contract_decisions.py`, `docs/CONTRACT_DECISIONS.md`, `all_live_fastapi_routes.json` | None | Reconciled all 444 references: 126 DONE-EXISTING, 233 FRONTEND_FIX (/api/v1 prefix), 85 BACKEND_ADD |
| **B-00.2** | IN_PROGRESS | `tests/test_super_admin_security_lock.py`, `tests/test_super_admin_suite.py` | Full test suite running | Fixed 2 collection import errors in test_super_admin_*.py; 847 tests collected cleanly |
| **B-00.3** | DONE | `tests/test_multi_tenant_data_isolation.py`, `app/middleware/auth.py` | None (documented) | Confirmed standard tenant pattern: company_id UUID FK, claims['company_id'], strict where(company_id == id), 404 on mismatch |
| **B-00.4** | DONE | `app/api/v2/screening.py`, `app/workers/payroll_tasks.py` | None (documented) | Confirmed background mechanism: FastAPI BackgroundTasks and asyncio.create_task with Redis/memory tracking fallback |
| **B-01.1** | TODO | | | Set refresh token as HttpOnly, Secure, path=/api/v1/auth cookie named ofc360_refresh_token + settings |
| **B-01.2** | TODO | | | SameSite check for registrable domain compatibility |
| **B-01.3** | TODO | | | CORS allow_credentials=True, explicit origins, CSRF Origin/Referer check on /auth/refresh & /auth/logout |
| **B-01.4** | TODO | | | Refresh rotation grace window (REFRESH_REUSE_GRACE_SECONDS=15) with rotated_at/replaced_by |
| **B-01.5** | TODO | | | TokenService.generate_auth_tokens: assign family_id = family_id or uuid4() before logging |
| **B-01.6** | TODO | | | Canonical /auth/refresh, alias /refresh-token (include_in_schema=False), remove obsolete cookie fallbacks |
| **B-01.7** | TODO | | | Rate limiting on /auth/login, /auth/refresh, OTP, reset password using real client IP |
| **B-01.8** | TODO | | | Auth session tests (cookie-only, body-only, rotation, grace window, reuse revocation, 401, logout) |
| **B-01.9** | TODO | | | Delete or archive unmounted School-ERP auth module app/api/v1/auth.py |
| **B-02.1** | TODO | | | get_db_session: quiet rollback on HTTPException/AppException, ERROR+traceback only for DBAPI/SQLAlchemyError |
| **B-02.2** | TODO | | | Request/exception logs resolve user_id and role from request.state / bearer claims |
| **B-02.3** | TODO | | | Single shared async Redis connection pool in lifespan, injected via dependency, event-loop safe |
| **B-02.4** | TODO | | | Exclude /health from access logs |
| **B-02.5** | TODO | | | Uvicorn/Docker proxy headers, forwarded-allow-ips, bind port 8000 locally in docker-compose.yml |
| **B-02.6** | TODO | | | Fast 404 for unknown scanner paths without DB/Redis access |
| **B-02.7** | TODO | | | Performance profiling, N+1 elimination, pagination, composite indexes, report before/after ms |
| **B-03.1** | TODO | | | Audit every table/query in recruitment, screening, interviews, offers, scorecards, talent pool, etc. |
| **B-03.2** | TODO | | | Alembic migrations for missing tenant columns, backfill, indexes, set on insert, 404 on mismatch |
| **B-03.3** | TODO | | | Pytest proving cross-tenant 404 isolation for all audited resources |
| **B-04.1** | TODO | | | Tenant filter on every AI resume screening query |
| **B-04.2** | TODO | | | Remove fake UUID generation for application_id in screening (require valid app or nullable) |
| **B-04.3** | TODO | | | Remove default match_score=0.5; calculate or mark FAILED |
| **B-04.4** | TODO | | | Configurable resume/JD truncation limits with head+tail preservation and logging |
| **B-04.5** | TODO | | | /batch-screen persists AIScreeningResult, honors auto_apply_decisions, per-item error handling |
| **B-04.6** | TODO | | | LLM failure sets status FAILED, score-only fallback conditional on setting |
| **B-04.7** | TODO | | | POST /api/v2/screening/jobs/{job_id}/run with ScreeningRun model, background execution, stale timeout |
| **B-04.8** | TODO | | | GET /api/v2/screening/jobs/{job_id}/results contract with 0-100 scores |
| **B-04.9** | TODO | | | POST /api/v2/screening/results/{screening_id}/decision with stage transitions & audit log |
| **B-04.10** | TODO | | | Compliance: AI recommendations only, auto-reject flag, store prompt version & thresholds, PII stripping |
| **B-04.11** | TODO | | | AI screening tests (lifecycle, concurrency 409, empty results 200, invalid ID rejection, failure modes) |
| **B-05.1** | TODO | | | Tenant-scope every interview query and write |
| **B-05.2** | TODO | | | Expiring signed token candidate self-booking (GET/POST /interviews/book/{token}) replacing public route |
| **B-05.3** | TODO | | | InterviewSchedule model with Alembic migration, backfill, and active schedule constraint |
| **B-05.4** | TODO | | | Overlap / double-booking validation for interviewer and candidate, timezone awareness |
| **B-05.5** | TODO | | | HR interview endpoints (schedule, reschedule, cancel without scorecard side effects, reminder, pass/reject/hold) |
| **B-05.6** | TODO | | | GET /interviews with flat items and GET /interviews/interviewers |
| **B-05.7** | TODO | | | Interview tests (tenant isolation, token booking, overlap, side-effect prevention, timezone, feedback score) |
| **B-06.1** | TODO | | | Audit existing interview_bot and interview_agent endpoints and models; report and fix gaps |
| **B-06.2** | TODO | | | Tokenized candidate AI interview flow (public endpoints: get, start, answer, finish) |
| **B-06.3** | TODO | | | HR side AI interview endpoints (invite, results list, human decision) |
| **B-06.4** | TODO | | | AI interview compliance (informational proctoring flags, request human interviewer option, audit log) |
| **B-06.5** | TODO | | | AI_INTERVIEW_ENABLED feature flag |
| **B-07.1** | TODO | | | GET /api/v1/notifications/unread-count returning total & byCategory, indexed |
| **B-07.2** | TODO | | | POST /notifications/{id}/unread and POST /notifications/read bulk |
| **B-08.1** | TODO | | | Settings route gaps (branding, subscription, audit-logs, tests, logo upload, sections) |
| **B-08.2** | TODO | | | Profile route gaps (/users/me, avatar, sessions, preferences) |
| **B-08.3** | TODO | | | Attendance route gaps (today, face status/enroll, check-in, geofence, shifts, rosters, holidays) |
| **B-08.4** | TODO | | | Departments & Managers route gaps (summary, bulk ops, import, employee assignments) |
| **B-08.5** | TODO | | | Documents, Employees /employees/me, Leaves, Timesheets ai-suggest, Policy search |
| **B-08.6** | TODO | | | Reports & Analytics route gaps (/api/v2/reports/analytics/* and /analytics/*) |
| **B-08.7** | TODO | | | AI Hub route gaps (/ai-hub/*) |
| **B-08.8** | TODO | | | Payroll route gaps (periods, runs, payslips, components, FNF, payment batches) |
| **B-09.1** | TODO | | | Expenses module (/api/v2/expenses): model, migration, CRUD, approval flow, summary, receipts |
| **B-09.2** | TODO | | | Visitors module (/api/v2/visitors): model, migration, pass codes, check-in/out, summary, export |
| **B-09.3** | TODO | | | Travel module: verify and enrich /api/v2/travel for frontend schema, stage transitions, history |
| **B-09.4** | TODO | | | Offboarding: map OffboardingCase to /api/v1/exits, add task checklist, document readiness, bundle |
| **B-09.5** | TODO | | | Onboarding checklist: reconcile employee_onboarding and hr_admin_onboarding with frontend |
| **B-09.6** | TODO | | | Asset management: add missing fields (brand, model, purchaseCost, warranty, history) |
| **B-09.7** | TODO | | | HR-Ops command center: GET /api/v2/hr-ops/overview aggregating real metrics |
| **B-09.8** | TODO | | | Tests & migrations for all B-09 modules |
| **B-10.1** | TODO | | | GET /api/v2/executive/overview?role=... with verified real metrics and 12-month time series |
| **B-10.2** | TODO | | | Document unavailable metrics in docs/EXEC_METRICS_AVAILABILITY.md with null + available:false |
| **B-10.3** | TODO | | | Executive dashboard tests including empty tenant verification |
| **B-11.1** | TODO | | | Clean scratch scripts from repo root to scripts/ or remove; update .gitignore |
| **B-11.2** | TODO | | | Secret scan across git history and working tree; document in report |
| **B-11.3** | TODO | | | Remove or archive unmounted School-ERP leftover files |
| **B-11.4** | TODO | | | Remove duplicate routers and duplicate route definitions |
| **B-12.1** | TODO | | | Run complete pytest suite and verify 100% green |
| **B-12.2** | TODO | | | Alembic single-head upgrade & downgrade test on empty DB and data |
| **B-12.3** | TODO | | | Load smoke test (p95 < 200ms) on candidates, jobs, offers, interviews |
| **B-12.4** | TODO | | | Regenerate openapi.json, all_live_fastapi_routes.json, API_ENDPOINTS.md |
| **B-12.5** | TODO | | | Final report in docs/BACKEND_FINAL_REPORT.md |
