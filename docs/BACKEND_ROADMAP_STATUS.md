# Backend Roadmap Status

**Updated:** 2026-10-28
**Branch:** `arena/1118d5e8-apiofc360`
**Milestone:** Step 9 / Batch 7 — P3 Differentiators

> This document supersedes the historical 2026-10-27 gap audit. Statuses below reflect the merged Batch 1–6 implementation plus Batch 7 on this branch. Operational hardening items outside the 44-feature roadmap remain separately tracked in `docs/PENDING_TRACKER.md`.

## Final Roadmap Summary

- **44 / 44 roadmap features: DONE ✅**
- **E1–E7 roadmap extras: DONE ✅**
- **Batch 7 migration:** `911a_batch7_p3_differentiators`, single Alembic head.
- **Batch 7 focused tests:** 14 / 14 passing.
- **Deterministic Batch 5–7 + tenancy + migration gate:** 65 / 65 passing.

## Feature Status

| # | Feature | Status | Delivery evidence |
|---:|---|---|---|
| 1 | Real tenant onboarding and employee bulk import/export | **DONE ✅** | Tenant onboarding, legal-entity/branch structure, employee lifecycle and bulk workflows delivered in Batches 0A–4. |
| 2 | Attendance-to-payroll lock and arrears | **DONE ✅** | Attendance deadlines, locked inputs and post-lock arrear flow delivered in Batch 1. |
| 3 | Production payroll engine and payslips | **DONE ✅** | Integer-minor-unit engine, statutory calculations, run lifecycle, approval and PDF payslips delivered in Batches 1–4. |
| 4 | PF ECR, challan and filing calendar | **DONE ✅** | PF/ECR, challan records and compliance calendar delivered in Batch 2. |
| 5 | ESI / PT / LWF engine | **DONE ✅** | Configurable state rules, eligibility, calculations and statutory outputs delivered in Batch 2. |
| 6 | TDS and Form 138 / Form 130 | **DONE ✅** | Declaration/proof workflows, monthly TDS and statutory forms delivered in Batch 2. |
| 7 | Payslip delivery and YTD view | **DONE ✅** | Protected PDFs, delivery workflows and YTD summaries delivered in Batch 3. |
| 8 | Leave and attendance auto-approval | **DONE ✅** | Policy rules, exception routing, balance validation and roster checks delivered in Batch 3. |
| 9 | Unified manager approval inbox | **DONE ✅** | Cross-module approval inbox and workflow actions delivered in Batch 3. |
| 10 | Onboarding automation and BGV status | **DONE ✅** | Offer/document collection, employee activation, tasks and joining workflow delivered in Batches 4–6. |
| 11 | Letters and e-sign | **DONE ✅** | Canonical letters, generated documents and e-sign workflows delivered in Batch 4. |
| 12 | Exit and full-and-final settlement | **DONE ✅** | Notice, dues, gratuity, leave encashment, clearance and relieving outputs delivered in Batch 4. |
| 13 | Autopilot HR policy layer | **DONE ✅** | Explainable policy decisions, confidence, exceptions, escalation, audit and rollback delivered in Batch 5. |
| 14 | WhatsApp employee app | **DONE ✅** | Employee self-service intents, approvals, payslips and helpdesk integration delivered in Batch 5. |
| 15 | Mobile PWA | **DONE ✅** | Mobile attendance, approvals, documents, payslips and push/idempotency support delivered in Batch 5. |
| 16 | Confidential grievance workflow | **DONE ✅** | Confidential intake, SLA, investigation, resolution and appeal delivered in Batch 5. |
| 17 | POSH module | **DONE ✅** | ICC, encrypted evidence, inquiry timeline, annual return and training delivered in Batch 5. |
| 18 | Policy acknowledgement | **DONE ✅** | Publication, targeting, versions, proof, reminders and escalation delivered in Batch 5. |
| 19 | Statutory compliance dashboard | **DONE ✅** | Due/overdue monitoring, filings, challans and statutory registers delivered in Batch 5. |
| 20 | Bank payout and reconciliation | **DONE ✅** | Bank files, maker-checker, payment batches and reconciliation delivered in Batch 5. |
| 21 | Multi-company / multi-entity payroll | **DONE ✅** | Legal entities, branches, state rules, calendars and entity transfers delivered in Batch 5. |
| 22 | DPDP compliance | **DONE ✅** | Consent, retention, export/delete, field encryption, masking and audit delivered in Batch 5. |
| 23 | Background verification | **DONE ✅** | Consent tokens, vendor adapters, signed webhooks, checks and discrepancy workflow delivered in Batch 6. |
| 24 | Succession planning | **DONE ✅** | Critical roles, successor slates, readiness, development actions and leadership risk delivered in Batch 6. |
| 25 | Compensation bands and pay equity | **DONE ✅** | Bands, compa-ratio, increment budgets, benchmarks and equity reporting delivered in Batch 6. |
| 26 | Performance cycle and promotion workflow | **DONE ✅** | 360 reviews, calibration, promotion approvals and increment recommendations delivered in Batch 6. |
| 27 | Internal job board | **DONE ✅** | Internal openings, eligibility, applications and manager approval delivered in Batch 6. |
| 28 | LMS | **DONE ✅** | Courses, assignments, progress, completion, certificates and compliance training delivered in Batch 6. |
| 29 | Engagement and recognition | **DONE ✅** | Pulse/eNPS, anonymous responses, action plans, recognition and rewards delivered in Batch 6. |
| 30 | Tally / Zoho / ERP accounting integration | **DONE ✅** | Balanced journals, expense posting, account mappings and reconciliation delivered in Batch 6. |
| 31 | Recruitment integrations | **DONE ✅** | Job-board adapters, sync state and candidate-source tracking delivered in Batch 6. |
| 32 | Webhooks and public API | **DONE ✅** | Tenant API keys, signed subscriptions, deliveries, attempts and replay controls delivered in Batch 6. |
| 33 | SSO / SCIM | **DONE ✅** | SAML/OIDC identity, assertion replay protection, SCIM tokens, groups and provisioning delivered in Batch 6. |
| 34 | AI salary negotiation copilot | **DONE ✅** | `POST /api/v2/ai/salary-negotiation-copilot`; tenant bands, match score, compa-ratio, budgets, three CTC scenarios and scripts. |
| 35 | AI disciplinary-case assistant | **DONE ✅** | `POST /api/v2/ai/disciplinary-assistant`; tenant-grounded policy citations, show-cause draft, inquiry checklist and sanitized precedents. |
| 36 | AI termination-risk assistant | **DONE ✅** | `POST /api/v2/ai/termination-risk-assistant`; tenure, non-suppressible protections, active cases, workman classification, compensation estimates and mitigation. |
| 37 | Culture analytics | **DONE ✅** | `GET /api/v2/analytics/culture`; department eNPS, pulse, overtime, leave, helpdesk sentiment, culture and burnout indices. |
| 38 | Diversity analytics | **DONE ✅** | `GET /api/v2/analytics/diversity`; gender/age/grade/leadership metrics and consented-only hiring-funnel parity. |
| 39 | Workforce planning and hiring budget | **DONE ✅** | `PUT /api/v2/workforce/plans`, `GET /api/v2/workforce/planning`; approved/actual headcount, requisition projections and monthly burn. |
| 40 | Attrition risk and intervention playbook | **DONE ✅** | `GET /api/v2/analytics/attrition-risk`; explainable factors, snapshots, retention bonus, internal transfer and stay-interview playbook. |
| 41 | Employee / organization digital twin | **DONE ✅** | `POST /api/v2/org-twin/simulate`; persisted restructuring, budget-cut, key-person, project-skills and span simulations without executing HR actions. |
| 42 | Integration marketplace | **DONE ✅** | Seven connectors, encrypted write-only credentials, enable/disable and sanitized sync-health logs in `app/services/marketplace_service.py`; external acknowledgement is reported separately. |
| 43 | White-label HRMS | **DONE ✅** | `/api/v2/whitelabel`; validated domain/theme/sender settings and offline-safe branded payslip, letter and preview PDFs. |
| 44 | Multi-currency / global payroll | **DONE ✅** | INR/USD/GBP/EUR/AED/SGD, locked FX/rule snapshots, deterministic conversion, base totals and pluggable country calculators; unconfigured rules require local review. |

## Roadmap Extras

| ID | Extra | Status | Delivery evidence |
|---|---|---|---|
| E1 | Labour Codes support and config-driven wage rules | **DONE ✅** | Config-driven wage, gratuity, PF and fixed-term employee support completed through Batches 0A–2. |
| E2 | Security and tenant-isolation verification | **DONE ✅** | HRMS cross-tenant regression suite passes; Batch 7 adds tenant-negative tests for copilots, planning, marketplace and payroll. |
| E3 | Parallel payroll comparison | **DONE ✅** | CSV/XLSX parallel comparison, persisted paise variances and diagnostics delivered in Batch 1. |
| E4 | CA / payroll-expert validation artifacts | **DONE ✅** | Config flags, versioned rules and golden-test artifacts are complete; tenant statutory deployment still requires the designated reviewer’s sign-off. |
| E5 | Legacy data migration | **DONE ✅** | Employee master, leave balances and YTD salary/TDS import tooling delivered in Batch 4. |
| E6 | Maker-checker and role separation | **DONE ✅** | Runner/approver separation and immutable payroll audit events delivered in Batch 0A and retained through Batch 7. |
| E7 | Overtime, comp-off and shift allowance payroll linkage | **DONE ✅** | Locked attendance inputs feed overtime, comp-off and shift allowances into payroll delivered in Batch 1. |

## Batch 7 Validation — 2026-10-28

| Check | Result |
|---|---|
| `tests/test_batch7_p3_differentiators.py` | **14 passed** |
| Batch 5 + Batch 6 + Batch 7 + cross-tenant + Alembic graph + migration helpers | **65 passed** |
| `tests/test_alembic_single_head.py` + `tests/test_migration_helpers.py` | **7 passed** |
| SQLAlchemy mapper configuration | **Passed** |
| v1/v2 recursive route smoke | **2,104 routes; all Batch 7 paths present** |
| Offline Alembic upgrade SQL, `910a → 911a` | **Generated successfully** |
| Offline Alembic downgrade SQL, `911a → 910a` | **Generated successfully** |
| End-to-end global payroll | **USD configured run and USD-compensation → AED unconfigured run passed; exact base totals and review warnings verified** |
| `git diff --check` and targeted `py_compile` | **Passed** |

### Complete-suite execution note

The final `pytest -q tests app/tests` run collected and executed the complete suites and reported **890 passed, 216 failed, 3 skipped, 25 errors**. No Batch 7 test is in the failure list, and the failing-test list is identical before and after the final Batch 7 execution test. The remaining failures require a live PostgreSQL test database and/or repair of pre-existing legacy fixtures: the run used a dummy PostgreSQL URL, `test_migrations_match_models` could not connect, and `app/tests` still attempts full PostgreSQL metadata creation on SQLite. Therefore this is **not represented as a green full-suite gate**. Offline migration SQL generation and the focused deterministic gate above are the validations completed in this environment.

## Batch 7 Deployment Notes

1. Apply `911a_batch7_p3_differentiators` after `910a_batch6_growth_enterprise`; legacy INR payroll rows are backfilled with 1.0 locked FX snapshots and INR base totals.
2. Non-INR runs require an explicit positive FX rate to INR. No live exchange-rate fallback is used.
3. Country statutory rules are versioned configuration. The package does not invent time-sensitive 2026 rates; unconfigured non-India runs emit mandatory local-review warnings.
4. Marketplace credentials are encrypted and write-only. Sync acceptance and external provider acknowledgement are distinct health fields.
5. Copilot, analytics and organization-twin outputs are decision support. They do not autonomously execute offers, discipline, termination, retention, transfer or restructuring actions.
