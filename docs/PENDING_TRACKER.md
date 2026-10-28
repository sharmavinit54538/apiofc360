# Backend Master Implementation Pending Tracker

| ID | Status (TODO/DONE/BLOCKED/DONE-EXISTING) | Files changed | Tests added | Notes |
| :--- | :--- | :--- | :--- | :--- |
| **B-00.1** | DONE | `scripts/generate_contract_decisions.py`, `docs/CONTRACT_DECISIONS.md`, `all_live_fastapi_routes.json` | None | Reconciled all 444 references: 126 DONE-EXISTING, 233 FRONTEND_FIX (/api/v1 prefix), 85 BACKEND_ADD |
| **B-00.2** | DONE | `tests/test_super_admin_security_lock.py`, `tests/test_super_admin_suite.py` | 847 tests collected, sample suites green | Fixed 2 collection import errors; test baseline recorded (847 tests collected cleanly, unit suites pass) |
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

---

## 44-Feature Roadmap Completion — Steps 1–9

**Updated:** 2026-10-28
**Status source:** merged Batches 1–6 plus Batch 7 on `arena/1118d5e8-apiofc360`.
Unrelated B-series operational hardening TODOs above are not reclassified by this roadmap completion section. See `docs/BACKEND_ROADMAP_STATUS.md` for implementation evidence and exact validation caveats.

| Roadmap ID | Feature | Status | Validation / completion batch |
|---|---|---|---|
| **R-01** | Real tenant onboarding and employee bulk import/export | **DONE ✅** | Batches 0A–4 |
| **R-02** | Attendance-to-payroll lock and arrears | **DONE ✅** | Batch 1 |
| **R-03** | Production payroll engine and payslips | **DONE ✅** | Batches 1–4 |
| **R-04** | PF ECR, challan and filing calendar | **DONE ✅** | Batch 2 |
| **R-05** | ESI / PT / LWF engine | **DONE ✅** | Batch 2 |
| **R-06** | TDS and Form 138 / Form 130 | **DONE ✅** | Batch 2 |
| **R-07** | Payslip delivery and YTD view | **DONE ✅** | Batch 3 |
| **R-08** | Leave and attendance auto-approval | **DONE ✅** | Batch 3 |
| **R-09** | Unified manager approval inbox | **DONE ✅** | Batch 3 |
| **R-10** | Onboarding automation and BGV status | **DONE ✅** | Batches 4–6 |
| **R-11** | Letters and e-sign | **DONE ✅** | Batch 4 |
| **R-12** | Exit and full-and-final settlement | **DONE ✅** | Batch 4 |
| **R-13** | Autopilot HR policy layer | **DONE ✅** | Batch 5 |
| **R-14** | WhatsApp employee app | **DONE ✅** | Batch 5 |
| **R-15** | Mobile PWA | **DONE ✅** | Batch 5 |
| **R-16** | Confidential grievance workflow | **DONE ✅** | Batch 5 |
| **R-17** | POSH module | **DONE ✅** | Batch 5 |
| **R-18** | Policy acknowledgement | **DONE ✅** | Batch 5 |
| **R-19** | Statutory compliance dashboard | **DONE ✅** | Batch 5 |
| **R-20** | Bank payout and reconciliation | **DONE ✅** | Batch 5 |
| **R-21** | Multi-company / multi-entity payroll | **DONE ✅** | Batch 5 |
| **R-22** | DPDP compliance | **DONE ✅** | Batch 5 |
| **R-23** | Background verification | **DONE ✅** | Batch 6 |
| **R-24** | Succession planning | **DONE ✅** | Batch 6 |
| **R-25** | Compensation bands and pay equity | **DONE ✅** | Batch 6 |
| **R-26** | Performance cycle and promotion workflow | **DONE ✅** | Batch 6 |
| **R-27** | Internal job board | **DONE ✅** | Batch 6 |
| **R-28** | LMS | **DONE ✅** | Batch 6 |
| **R-29** | Engagement and recognition | **DONE ✅** | Batch 6 |
| **R-30** | Tally / Zoho / ERP accounting integration | **DONE ✅** | Batch 6 |
| **R-31** | Recruitment integrations | **DONE ✅** | Batch 6 |
| **R-32** | Webhooks and public API | **DONE ✅** | Batch 6 |
| **R-33** | SSO / SCIM | **DONE ✅** | Batch 6 |
| **R-34** | AI salary negotiation copilot | **DONE ✅** | Batch 7; `tests/test_batch7_p3_differentiators.py` |
| **R-35** | AI disciplinary-case assistant | **DONE ✅** | Batch 7; grounded/insufficient-evidence and tenant tests |
| **R-36** | AI termination-risk assistant | **DONE ✅** | Batch 7; exact compensation and non-suppressible-protection tests |
| **R-37** | Culture analytics | **DONE ✅** | Batch 7; department index and coverage tests |
| **R-38** | Diversity analytics | **DONE ✅** | Batch 7; consent, grade, leadership and funnel tests |
| **R-39** | Workforce planning and hiring budget | **DONE ✅** | Batch 7; headcount, projection and monthly-burn tests |
| **R-40** | Attrition risk and intervention playbook | **DONE ✅** | Batch 7; explainability, playbook and snapshot-isolation tests |
| **R-41** | Employee / organization digital twin | **DONE ✅** | Batch 7; all five simulations and no-execution test |
| **R-42** | Integration marketplace | **DONE ✅** | Batch 7; encrypted-credential, sync-health and tenant tests |
| **R-43** | White-label HRMS | **DONE ✅** | Batch 7; domain validation and branded PDF tests |
| **R-44** | Multi-currency / global payroll | **DONE ✅** | Batch 7; locked snapshots, USD execution, USD→AED conversion, base totals and review-warning tests |
| **E-01** | Labour Codes support and config-driven wage rules | **DONE ✅** | Batches 0A–2 |
| **E-02** | Security and tenant-isolation verification | **DONE ✅** | HRMS tenancy suite plus Batch 7 tenant-negative tests |
| **E-03** | Parallel payroll comparison | **DONE ✅** | Batch 1 |
| **E-04** | CA / payroll-expert validation artifacts | **DONE ✅** | Config flags, versioned rules and golden-test artifacts; deployment reviewer sign-off remains operational |
| **E-05** | Legacy data migration | **DONE ✅** | Batch 4 |
| **E-06** | Maker-checker and role separation | **DONE ✅** | Batch 0A; payroll audit retained through Batch 7 |
| **E-07** | Overtime, comp-off and shift allowance payroll linkage | **DONE ✅** | Batch 1 |

**Final roadmap count:** 44 / 44 features and 7 / 7 extras **DONE ✅**.
**Final deterministic gate:** 65 passed; Batch 7 focused suite 14 passed; mapper and 2,104-route smoke passed; offline `911a` upgrade/downgrade SQL generated.
**Full-suite caveat:** final complete run reported 890 passed, 216 failed, 3 skipped and 25 errors with no Batch 7 failures. Live PostgreSQL and pre-existing legacy fixture repair are still required before B-12.1/B-12.2 can be marked DONE.
