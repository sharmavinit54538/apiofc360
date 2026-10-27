# Backend Roadmap Status Audit

**Generated:** 2026-10-27  
**Branch:** `chore/roadmap-audit`  
**Base:** `dev`

---

## Summary Table

| # | Feature | Status | Existing Files/Endpoints | Gaps | Proposed Batch |
|---|---------|--------|--------------------------|------|----------------|
| **P0 — Foundation & Payroll Core** |
| 1 | Real tenant onboarding: company/legal entity, branch-department-manager mapping, employee bulk import/export, remove mock data | **PARTIAL** | `app/api/v2/hr_admin_onboarding.py`, `app/services/hr_admin_onboarding_service.py`, `app/models/employee.py`, `app/api/employees.py` (bulk upload), `app/api/departments.py` | Branch-dept-manager mapping incomplete; no employee bulk export; mock data still present in seeds | Batch 4 |
| 2 | Attendance → payroll lock: cutoff date, regularisation deadline, lock/unlock permission, post-lock changes → arrears | **PARTIAL** | `app/models/payroll.py:PayCycle` (attendance_lock_date, leave_lock_date, overtime_lock_date, is_locked), `app/api/v2/payroll/cycles.py` | No regularisation deadline enforcement; no arrears auto-flow after lock; lock permission not role-gated separately | Batch 1 |
| 3 | Payroll production engine: salary structure, PF/ESI/PT/LWF/TDS calculation, gross/net, payroll run approval, payslip PDF | **EXISTS** | `app/api/v2/payroll/runs.py` (22 endpoints), `app/services/payroll/run_service.py`, `app/services/payroll/payslip_service.py`, `app/models/payroll.py` (SalaryStructure, PayrollRun, Payslip), `app/models/payroll_models.py` (Compensation, VariableInput), `app/workers/payroll_tasks.py` | LWF not implemented; rounding rules not documented; parallel-run comparison report missing | Batch 1 |
| 4 | PF ECR + challan: UAN validation, employee/employer contribution, ECR file, challan/receipt upload, monthly filing calendar | **EXISTS** | `app/api/v2/payroll/statutory.py` (GET /pf-ecr, GET /pf-summary, GET /filing-calendar, POST /challan/record, POST /challan/upload), `app/services/payroll/statutory_service.py`, `app/models/employee.py` (UAN validation), `app/models/payroll.py:StatutoryComplianceConfig` | ECR format needs CA validation; challan upload uses local storage (needs S3 flag); TRRN tracking basic | Batch 2 |
| 5 | ESI / PT / LWF engine: state-wise rules, eligibility check, contribution calculation, challan generation | **PARTIAL** | `app/api/v2/payroll/statutory.py` (simulate endpoint covers ESI/PT), `app/models/payroll.py:StatutoryComplianceConfig` (pt_state, pt_slabs, esi rates) | LWF missing entirely; state-wise PT slabs only config (no engine); ESI challan generation missing; needs CA validation | Batch 2 |
| 6 | TDS + Form 138 / Form 130: old/new regime, declarations, proof collection, monthly TDS, Form 138 draft, Form 130 download | **PARTIAL** | `app/models/payroll.py:EmployeeInvestmentDeclaration`, `app/api/v2/payroll/statutory.py` (simulate covers TDS), `app/models/payroll.py:StatutoryComplianceConfig` (default_tax_regime) | Form 138/130 generation missing; proof collection workflow missing; monthly TDS computation not in engine; needs CA validation | Batch 2 |
| 7 | Payslip delivery: PDF download, email/WhatsApp delivery, password-protected payslip, YTD salary view | **PARTIAL** | `app/api/v2/payroll/payslips.py` (download endpoints), `app/services/payroll/payslip_service.py`, `app/workers/payroll_tasks.py` (payslip generation), `app/models/payroll.py:Payslip` (pdf_path, email_status) | Email/WhatsApp delivery not implemented; password-protected PDF missing; YTD view not exposed | Batch 3 |
| 8 | Leave + attendance auto-approval: policy-based auto approve, exceptions to manager, balance validation, roster/holiday check | **PARTIAL** | `app/api/leaves.py` (apply, review, balances), `app/services/leave_service.py`, `app/models/leave.py` | Auto-approval rules engine missing; roster/holiday check missing; comp-off/overtime link to payroll missing | Batch 3 |
| 9 | Manager approval inbox: leave, regularisation, expense, document, onboarding, exit approvals | **PARTIAL** | `app/api/leaves.py` (/pending), `app/api/employee_onboarding_api.py`, `app/api/exits.py`, `app/services/hr_workflow_service.py` | No unified inbox; expense approval missing; regularisation approval missing; document approval basic | Batch 3 |
| 10 | Onboarding automation: offer acceptance, document collection, Aadhaar/PAN/bank/UAN, BGV status, account/task creation, joining checklist | **EXISTS** | `app/api/employee_onboarding_api.py` (10-step wizard), `app/services/employee_onboarding_service.py`, `app/models/employee_onboarding.py`, `app/models/employee.py` (onboarding fields), `app/api/v2/offer_letters.py` | Offer acceptance not linked; BGV status tracking missing; account/task creation missing; joining checklist basic | Batch 4 |
| 11 | Letters + e-sign: offer, appointment, confirmation, increment, transfer, relieving, experience, warning letter | **PARTIAL** | `app/api/v2/offer_letters.py`, `app/services/offer_letter_service.py`, `app/models/exit.py:ExitDocument`, `app/services/document_templates.py` (canonical templates) | Only offer & relieving letters implemented; appointment/confirmation/increment/transfer/experience/warning missing; e-sign integration missing | Batch 4 |
| 12 | Exit / FnF settlement: notice period, leave encashment, gratuity, pending dues, asset clearance, FnF sheet, relieving letter | **PARTIAL** | `app/api/exits.py`, `app/services/exit_service.py`, `app/models/exit.py` (EmployeeExit, KnowledgeTransfer, AssetReturn, ClearanceRequest, ExitInterview, FnfSettlement, ExitDocument), `app/models/payroll_models.py:FullAndFinalSettlement`, `app/api/v2/payroll/full_and_final.py` | Gratuity calculation missing; leave encashment not linked to leave balances; FnF sheet generation basic; asset clearance workflow exists but not enforced | Batch 4 |

| **P1 — Automation & Compliance** |
| 13 | Autopilot HR layer: policy engine, auto-approval rules, confidence score, exceptions inbox, escalation ladder, explainability, audit trail, rollback | **MISSING** | `app/services/compliance_monitor_service.py` (monitoring only) | Entire policy engine missing | P1 (later) |
| 14 | WhatsApp employee app: leave, regularisation, payslip, announcements, approvals, helpdesk | **MISSING** | — | No WhatsApp integration | P1 (later) |
| 15 | Mobile PWA: push notifications, mobile attendance, approvals, document upload, payslip view | **MISSING** | — | No PWA | P1 (later) |
| 16 | Grievance module: confidential complaint, category, SLA, escalation, investigation, resolution, appeal | **MISSING** | `app/api/helpdesk.py`, `app/services/helpdesk_service.py` (basic tickets) | Grievance-specific workflow missing; confidentiality not enforced | P1 (later) |
| 17 | POSH module: complaint intake, ICC members, confidential evidence vault, inquiry timeline, annual report, training tracker | **MISSING** | — | Entire module missing | P1 (later) |
| 18 | Policy acknowledgement: publish, employee targeting, version control, acknowledgement proof, reminder/escalation | **PARTIAL** | `app/models/employee_policy_acceptance.py`, `app/api/employee_onboarding_api.py` (step 9), `app/services/document_templates.py` (handbook template) | Publish/targeting/version control/reminders missing | P1 (later) |
| 19 | Statutory compliance dashboard: monthly calendar, due/overdue alerts, filing status, challan storage, register/return generator | **PARTIAL** | `app/api/v2/payroll/statutory.py` (/filing-calendar), `app/services/compliance_monitor_service.py`, `app/api/v2/analytics.py` | Due/overdue alerts missing; challan storage basic; register/return generator only for PF | P1 (later) |
| 20 | Bank payout: NEFT/RTGS file, ICICI/HDFC/SBI formats, maker-checker, payment reconciliation | **PARTIAL** | `app/api/v2/payroll/payment_batches.py`, `app/models/payroll_models.py:PaymentBatch`, `PaymentBatchBankFile` (HDFC_CSV, ICICI_EXCEL, SBI_TXT, GENERIC_NEFT_CSV), `app/services/payroll/payment_batch_service.py` | Maker-checker on payment batch missing; reconciliation missing; bank format validation incomplete | P1 (later) |
| 21 | Multi-company / multi-entity: multiple legal entities, branches, state-wise payroll rules, entity-wise payroll calendar | **PARTIAL** | `app/models/company.py`, `app/models/department.py`, `app/models/payroll.py:StatutoryComplianceConfig` (company_id, state), `app/db/base.py:TenantMixin` | Branches not modeled; state-wise rules only config; entity-wise calendar missing; legal entity distinction missing | P1 (later) |
| 22 | DPDP compliance: consent ledger, retention policy, employee data export, delete/anonymise request, sensitive-data encryption, audit logs | **MISSING** | `app/services/audit_service.py` (basic), `app/middleware/auth.py` (claims) | No encryption at rest for Aadhaar/PAN/bank/UAN; no masking in responses/logs; no consent ledger; no retention policy; no data export/delete | Batch 0 |

| **P2 — Talent & Analytics** |
| 23 | Background verification: vendor API, candidate consent, status, discrepancy workflow | **MISSING** | `app/api/recruitment.py`, `app/services/recruitment_service.py` | No BGV vendor integration | P2 (later) |
| 24 | Succession planning: critical roles, successor slate, readiness score, development plan, leadership risk map | **MISSING** | — | Entire module missing | P2 (later) |
| 25 | Compensation bands: salary bands, compa-ratio, increment budget, market benchmark, pay-equity report | **PARTIAL** | `app/api/v2/compensation_api.py`, `app/services/compensation_service.py`, `app/models/payroll_models.py:Compensation` | Bands/compa-ratio/benchmark/equity reports missing | P2 (later) |
| 26 | Performance cycle: review cycle, manager/peer review, calibration, promotion workflow, increment recommendation | **PARTIAL** | `app/api/v2/performance_api.py`, `app/services/performance_service.py`, `app/models/performance.py` | Calibration/promotion workflow/increment recommendation missing | P2 (later) |
| 27 | Internal job board: internal openings, eligibility rules, internal application, manager approval | **MISSING** | `app/api/v2/talent_marketplace.py` (basic) | Eligibility rules/manager approval missing | P2 (later) |
| 28 | LMS: course upload, assignment, completion tracking, certificate, compliance training | **MISSING** | — | Entire module missing | P2 (later) |
| 29 | Engagement: pulse survey, eNPS, anonymous feedback, action plans, recognition/rewards | **MISSING** | `app/api/polls.py` (basic) | Pulse/eNPS/action plans/rewards missing | P2 (later) |
| 30 | Tally / Zoho / ERP integration: payroll journal export, expense posting, account sync, reconciliation report | **MISSING** | `app/api/v2/payroll/accounting.py` (basic GL export) | Tally/Zoho/ERP formats missing; reconciliation missing | P2 (later) |
| 31 | Recruitment integrations: Naukri, LinkedIn, job board sync, candidate source tracking | **MISSING** | `app/api/recruitment.py`, `app/services/recruitment_service.py` | No external job board APIs | P2 (later) |
| 32 | Webhooks + public API: employee created/updated, leave approved, payroll completed, candidate moved, API keys, webhook signing | **MISSING** | — | No webhook infrastructure | P2 (later) |
| 33 | SSO / SCIM: Google Workspace SSO, Microsoft Entra ID, SAML, SCIM provisioning/deprovisioning | **PARTIAL** | `app/api/auth.py` (Google/GitHub OAuth), `app/services/auth_service.py` | SAML/SCIM missing; Entra ID missing | P2 (later) |

| **P3 — AI & Advanced** |
| 34 | AI salary negotiation copilot | **MISSING** | `app/services/ai_copilot_service.py` (general) | Specific copilot missing | P3 (later) |
| 35 | AI disciplinary-case assistant | **MISSING** | — | Missing | P3 (later) |
| 36 | AI termination-risk assistant | **MISSING** | `app/models/employee_risk.py` (model only) | Assistant missing | P3 (later) |
| 37 | Culture analytics | **MISSING** | `app/services/hr_analytics_service.py` (basic) | Culture-specific missing | P3 (later) |
| 38 | Diversity analytics | **MISSING** | — | Missing | P3 (later) |
| 39 | Workforce planning / headcount budget | **MISSING** | `app/models/workforce_forecast.py` (model only) | Planning/budget missing | P3 (later) |
| 40 | Attrition prediction + intervention playbook | **MISSING** | `app/models/employee_risk.py` | Prediction/playbook missing | P3 (later) |
| 41 | Digital twin of employee/org | **MISSING** | — | Missing | P3 (later) |
| 42 | Integration marketplace | **MISSING** | — | Missing | P3 (later) |
| 43 | White-label HRMS | **MISSING** | — | Missing | P3 (later) |
| 44 | Multi-currency / global payroll | **MISSING** | `app/models/payroll.py:StatutoryComplianceConfig` (currency, country fields) | Only INR/India implemented | P3 (later) |

| **EXTRAS (All P0 — Bring Forward)** |
| E1 | Labour Codes support: 50% basic rule, new wages definition, gratuity and PF impact, fixed-term employees; rules config-driven | **MISSING** | `app/models/payroll.py:StatutoryComplianceConfig` (extensible) | No Labour Codes config; 50% basic rule not enforced; new wages definition missing; fixed-term employee type missing | Batch 0 |
| E2 | Security + tenant isolation tests (bring DPDP #22 forward) | **PARTIAL** | `app/tests/test_tenant_isolation.py` (school-based, not HRMS), `app/middleware/auth.py` (tenant_id_ctx) | No cross-tenant tests for payroll/employee/leave; no encryption/masking tests | Batch 0 |
| E3 | Parallel payroll run against previous system for 1-2 months | **MISSING** | `app/api/v2/payroll/reports.py` (comparison endpoints stubbed) | No parallel-run comparison report implementation | Batch 1 |
| E4 | CA / payroll expert validation for PF, ESI, PT, TDS formulas | **MISSING** | `app/models/payroll.py:StatutoryComplianceConfig` (config-driven) | No `needs_ca_validation` flags; no golden tests with hand-computed results | Batch 0/1/2 |
| E5 | Data migration tool: old employee master, leave balances, YTD salary/TDS import | **MISSING** | `app/api/exports.py`, `app/services/export_service.py` | No import tool; no migration scripts | Batch 4 |
| E6 | Maker-checker + role separation (payroll runner ≠ approver) | **PARTIAL** | `app/api/payroll/permissions.py` (_require_admin_or_manager), `app/models/payroll.py:PayrollRun` (run_by, approved_by, finalized_by) | No enforced separation; same role can run and approve; no workflow enforcement | Batch 0 |
| E7 | Overtime, comp-off, shift allowance linked to payroll | **PARTIAL** | `app/models/payroll.py:OvertimePolicy`, `OvertimeEntry`, `app/models/shift.py`, `app/models/payroll_models.py:VariableInput` (overtime type) | Comp-off missing; shift allowance not linked; overtime not auto-fed to payroll run | Batch 1 |

---

## Stubs / Placeholders / Mock Data Endpoints

| Endpoint | File | Issue |
|----------|------|-------|
| `GET /api/v2/payroll/reports/comparison` | `app/api/v2/payroll/reports.py` | Returns mock comparison data |
| `GET /api/v2/payroll/runs/{runId}/preview` | `app/api/v2/payroll/runs.py:392` | Delegates to service but service may return computed estimates |
| `POST /api/v2/payroll/statutory/simulate` | `app/api/v2/payroll/statutory.py:81` | Simulation only, not persisted |
| `app/scripts/seed.py` | `scripts/seed.py` | Creates mock employees, departments, leave policies |
| `app/scripts/seed_super_admin.py` | `scripts/seed_super_admin.py` | Creates super admin with default password |
| `app/services/compliance_monitor_service.py` | Multiple methods | Some KPIs derived from placeholder logic (e.g., `policy_compliance` hardcoded) |
| `app/api/v2/analytics.py` | Various | Some analytics endpoints return static/dummy data |

---

## Configuration Items Requiring CA Validation (`needs_ca_validation`)

| Config Key | Current Default | Source | Status |
|------------|-----------------|--------|--------|
| `employee_pf_rate` | 0.12 (12%) | EPF Act | ⚠️ Needs CA validation |
| `employer_pf_rate` | 0.12 (12%) | EPF Act | ⚠️ Needs CA validation |
| `pf_wage_ceiling` | 15000.00 | EPF Act | ⚠️ Needs CA validation |
| `employee_esi_rate` | 0.0075 (0.75%) | ESI Act | ⚠️ Needs CA validation |
| `employer_esi_rate` | 0.0325 (3.25%) | ESI Act | ⚠️ Needs CA validation |
| `esi_wage_ceiling` | 21000.00 | ESI Act | ⚠️ Needs CA validation |
| `pt_slabs` (per state) | Empty list | State PT Acts | ⚠️ Needs CA validation |
| `default_tax_regime` | "NEW" | Income Tax Act | ⚠️ Needs CA validation |
| TDS slabs (old/new regime) | Not in config | Income Tax Act | ⚠️ Missing from config |
| Gratuity formula | Not implemented | Payment of Gratuity Act | ⚠️ Missing |
| LWF rates | Not implemented | State LWF Acts | ⚠️ Missing |
| Labour Codes: 50% basic rule | Not implemented | New Labour Codes | ⚠️ Missing |
| Labour Codes: new wages definition | Not implemented | New Labour Codes | ⚠️ Missing |

---

## Tenant Isolation Coverage

| Resource | Model Has `company_id` | API Scopes by `company_id` | Cross-Tenant Test |
|----------|------------------------|----------------------------|-------------------|
| Employee | ✅ | ✅ | ❌ |
| PayrollRun | ✅ | ✅ | ❌ |
| Payslip | ✅ | ✅ | ❌ |
| SalaryStructure | ✅ | ✅ | ❌ |
| PayrollPeriod | ✅ | ✅ | ❌ |
| PayComponent | ✅ | ✅ | ❌ |
| Compensation | ✅ | ✅ | ❌ |
| VariableInput | ✅ | ✅ | ❌ |
| PaymentBatch | ✅ | ✅ | ❌ |
| LeaveRequest | ✅ (via employee) | ✅ | ❌ |
| EmployeeExit | ✅ | ✅ | ❌ |
| StatutoryComplianceConfig | ✅ | ✅ | ❌ |
| CompanyBankAccount | ✅ | ✅ | ❌ |

**Gap:** No automated cross-tenant access tests for any HRMS resource.

---

## Encryption / Masking / Audit Gaps (DPDP #22)

| Sensitive Field | Model | Encrypted at Rest | Masked in API Response | Masked in Logs | Access Audited |
|-----------------|-------|-------------------|------------------------|----------------|----------------|
| `aadhaar_number` | Employee | ❌ | ❌ | ❌ | ❌ |
| `pan_number` | Employee | ❌ | ❌ | ❌ | ❌ |
| `uan_number` | Employee | ❌ | ❌ | ❌ | ❌ |
| `account_number` | EmployeeBankAccount | ❌ | ❌ | ❌ | ❌ |
| `ifsc_code` | EmployeeBankAccount | ❌ | ❌ | ❌ | ❌ |
| `passport_number` | Employee | ❌ | ❌ | ❌ | ❌ |
| `voter_id` | Employee | ❌ | ❌ | ❌ | ❌ |

**No field-level encryption, masking, or consent ledger implemented.**

---

## Batch Plan (Adjusted from Default)

| Batch | Name | Roadmap Items | Key Deliverables |
|-------|------|---------------|------------------|
| **Batch 0** | Foundation: Tenant Isolation + Security + DPDP + Labour Codes Config + Maker-Checker | E2, E6, E1, E4 (config flags), 22 (partial) | Cross-tenant test suite; field-level encryption for Aadhaar/PAN/bank/UAN; masking in responses/logs; consent ledger; audit log enrichment; Labour Codes config tables; maker-checker enforcement (separate roles for run vs approve); `needs_ca_validation` flags on all statutory config |
| **Batch 1** | Payroll Core: Arrears, Overtime/Comp-off/Shift Allowance, Parallel-Run Report | 2, 3 (gaps), E3, E7 | Attendance lock with regularisation deadline; arrears auto-flow; overtime/comp-off/shift allowance fed to payroll; parallel-run comparison report (golden tests) |
| **Batch 2** | Statutory: ESI/PT/LWF Engine, TDS + Form 138/130, Labour Codes Rules | 4 (gaps), 5, 6, E1 (rules), E4 (validation) | LWF engine; state-wise PT engine; ESI challan; Form 138/130 generation; monthly TDS computation; proof collection workflow; CA-validated golden tests |
| **Batch 3** | Delivery & Approvals: Payslip Delivery, Leave Auto-Approval, Unified Inbox | 7, 8, 9 | Password-protected PDF payslips; email/WhatsApp delivery; YTD view; leave auto-approval rules; roster/holiday check; unified manager inbox |
| **Batch 4** | Lifecycle: Tenant Onboarding Completion, Onboarding Automation Completion, Letters/E-sign, Exit/FnF, Data Migration | 1, 10 (gaps), 11, 12, E5 | Branch-dept-manager mapping; employee bulk import/export; offer acceptance; BGV tracking; appointment/confirmation/increment/transfer/experience/warning letters; e-sign integration; gratuity calc; leave encashment; FnF sheet; data migration tool |

---

## Next Steps

1. **Approve Batch 0 plan** — I will create branch `feat/batch-0-foundation` from `dev` and implement.
2. **Quality gate per batch:** formatter/linter, `py_compile`, full existing test suite + new tests, all green.
3. **After each batch:** PR into `dev` with endpoints, migrations, config, tests, gaps/blockers listed.

---

## Notes

- **Money handling:** Already uses `Numeric`/`Decimal` and `*_paise` BigInteger columns — compliant.
- **Idempotency:** Payroll runs have `job_id` tracking; `PayrollRunService.execute_run_calculation` should be idempotent (verify).
- **Worker mechanism:** `app/workers/payroll_tasks.py` uses Celery with asyncio fallback — good.
- **Storage:** `app/services/storage_service.py` uses local disk with `BaseStorageProvider` abstraction — S3/EFS not configured, must flag.
- **Migrations:** Alembic present at `alembic/versions/` — new migrations must be backward-safe.