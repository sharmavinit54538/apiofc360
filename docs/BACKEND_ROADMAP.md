# OFC360 HRMS — Backend Roadmap (Source of Truth)

**Version:** 1.0  
**Last Updated:** 2026-10-27  
**Branch Policy:** All work branches off `dev`, PRs into `dev`, never push directly to `dev`.

---

## P0 — Foundation & Payroll Core (Must Ship First)

1. **Real tenant onboarding**: Company/legal entity setup, branch-department-manager mapping, employee bulk import/export, remove all mock data
2. **Attendance → payroll lock**: Cutoff date, regularisation deadline, lock/unlock permission (separate role), post-lock changes flow to arrears automatically
3. **Payroll production engine**: Salary structure (versioned, effective-dated), PF/ESI/PT/LWF/TDS calculation, gross/net, payroll run approval workflow (maker ≠ checker), payslip PDF generation
4. **PF ECR + challan**: UAN validation (12-digit), employee/employer contribution calc, ECR file (EPFO v2.0 `#|~|#` delimiter), challan/receipt upload, monthly filing calendar (15th due date tracking)
5. **ESI / PT / LWF engine**: State-wise rules, eligibility check, contribution calculation, challan generation for all states
6. **TDS + Form 138 / Form 130**: Old/new regime support, investment declarations, proof collection workflow, monthly TDS computation, Form 138 draft, Form 130 download
7. **Payslip delivery**: PDF download, email delivery, WhatsApp delivery (feature-flagged), password-protected PDF, YTD salary view
8. **Leave + attendance auto-approval**: Policy-based auto-approve, exceptions route to manager, balance validation, roster/holiday check, comp-off/overtime linked to payroll
9. **Manager approval inbox**: Unified inbox for leave, regularisation, expense, document, onboarding, exit approvals
10. **Onboarding automation**: Offer acceptance, document collection (Aadhaar/PAN/bank/UAN), BGV status tracking, account/task creation, joining checklist (10-step wizard)
11. **Letters + e-sign**: Offer, appointment, confirmation, increment, transfer, relieving, experience, warning letters; e-sign provider integration (feature-flagged)
12. **Exit / FnF settlement**: Notice period, leave encashment, gratuity calc, pending dues, asset clearance, FnF statement, relieving letter

---

## P1 — Automation & Compliance

13. **Autopilot HR layer**: Policy engine, auto-approval rules, confidence score, exceptions inbox, escalation ladder, explainability, audit trail, rollback
14. **WhatsApp employee app**: Leave, regularisation, payslip, announcements, approvals, helpdesk via WhatsApp Business API
15. **Mobile PWA**: Push notifications, mobile attendance (geo/facial), approvals, document upload, payslip view
16. **Grievance module**: Confidential complaint, category, SLA, escalation, investigation, resolution, appeal
17. **POSH module**: Complaint intake, ICC members, confidential evidence vault, inquiry timeline, annual report, training tracker
18. **Policy acknowledgement**: Publish, employee targeting, version control, acknowledgement proof, reminder/escalation
19. **Statutory compliance dashboard**: Monthly calendar, due/overdue alerts, filing status, challan storage, register/return generator
20. **Bank payout**: NEFT/RTGS file generation (ICICI/HDFC/SBI formats), maker-checker, payment reconciliation
21. **Multi-company / multi-entity**: Multiple legal entities, branches, state-wise payroll rules, entity-wise payroll calendar
22. **DPDP compliance**: Consent ledger, retention policy, employee data export, delete/anonymise request, sensitive-data encryption (Aadhaar/PAN/bank/UAN), audit logs

---

## P2 — Talent & Analytics

23. **Background verification**: Vendor API integration, candidate consent, status tracking, discrepancy workflow
24. **Succession planning**: Critical roles, successor slate, readiness score, development plan, leadership risk map
25. **Compensation bands**: Salary bands, compa-ratio, increment budget, market benchmark, pay-equity report
26. **Performance cycle**: Review cycle, manager/peer review, calibration, promotion workflow, increment recommendation
27. **Internal job board**: Internal openings, eligibility rules, internal application, manager approval
28. **LMS**: Course upload, assignment, completion tracking, certificate, compliance training
29. **Engagement**: Pulse survey, eNPS, anonymous feedback, action plans, recognition/rewards
30. **Tally / Zoho / ERP integration**: Payroll journal export, expense posting, account sync, reconciliation report
31. **Recruitment integrations**: Naukri, LinkedIn, job board sync, candidate source tracking
32. **Webhooks + public API**: Employee created/updated, leave approved, payroll completed, candidate moved, API keys, webhook signing
33. **SSO / SCIM**: Google Workspace SSO, Microsoft Entra ID, SAML, SCIM provisioning/deprovisioning

---

## P3 — AI & Advanced (Future)

34. AI salary negotiation copilot
35. AI disciplinary-case assistant
36. AI termination-risk assistant
37. Culture analytics
38. Diversity analytics
39. Workforce planning / headcount budget
40. Attrition prediction + intervention playbook
41. Digital twin of employee/org
42. Integration marketplace
43. White-label HRMS
44. Multi-currency / global payroll

---

## EXTRAS (All P0 Priority — Bring Forward)

- **Labour Codes support**: 50% basic wage rule, new wages definition, gratuity and PF impact, fixed-term employees; all rules config-driven, effective-dated
- **Security + tenant isolation tests**: Cross-tenant access tests for every resource (must return 404/403), encryption/masking tests (bring DPDP #22 forward)
- **Parallel payroll run**: Comparison report against previous system for 1-2 months (golden tests with hand-computed expected results)
- **CA / payroll expert validation**: Every statutory formula (PF, ESI, PT, TDS, Gratuity, LWF) flagged `needs_ca_validation` in config; golden tests with verified numbers
- **Data migration tool**: Old employee master, leave balances, YTD salary/TDS import (CSV/Excel with validation)
- **Maker-checker + role separation**: Person who runs payroll cannot approve it; enforced at API + DB level
- **Overtime, comp-off, shift allowance linked to payroll**: Attendance overtime → variable input → payroll run; comp-off accrual/usage; shift allowance as earning component

---

## Engineering Rules (Non-Negotiable)

- **Vertical slices**: model + migration + schema + repository + service + router + tests + OpenAPI docs
- **API envelope**: `{success, message, data, errors}` — always
- **Money**: `Decimal`/`Numeric` only, never `float`. Paise stored as `BigInteger`. Document rounding rules.
- **Tenant scoping**: Every query filtered by `company_id` from JWT claims. Cross-tenant tests mandatory.
- **Payroll runs**: Idempotent, resumable, lockable. Attendance-to-payroll lock with cutoff/regularisation/arrears flow.
- **Statutory logic**: ALL numbers in effective-dated config tables with source note. No hardcoded values. CA validation flags. Golden tests.
- **Sensitive data**: Encrypted at rest (key from env), masked in API responses and logs, access audited. Never log raw values.
- **Files**: Use `storage_service` with `BaseStorageProvider`. No container-local disk for persistent data. Flag if S3/EFS not configured.
- **External deps**: Interface behind feature flag, return 501/"not configured", list as gap. No mock/fake success.
- **Minimal diff**: No unrelated changes. List unrelated bugs in report instead of silent fixes.
- **Quality gate**: formatter/linter, `py_compile`, full test suite + new tests, all green.

---

## Git Workflow

- Per batch: branch `feat/<batch-name>` from `dev`
- Small logical commits
- PR into `dev` describing: endpoints, migrations, config added, tests, known gaps
- Migrations backward-safe; no destructive changes without explicit approval
- Never edit already-applied migrations

---

## Current Implementation Status

See `docs/BACKEND_ROADMAP_STATUS.md` for detailed audit (EXISTS/PARTIAL/MISSING per item).