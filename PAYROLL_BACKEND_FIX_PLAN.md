# OFC360 Payroll Backend — Repair and Verification Plan

## Completed in this pass

1. Centralize finite Decimal conversion, annual paise remainder allocation, and
   a reusable payroll reconciliation assertion.
2. Preserve exact paise Net Pay and fail a run on negative/unreconciled payroll.
3. Use actual inclusive payroll period length for salary proration and payslip
   day count.
4. Allocate annual CTC remainder deterministically for matching fixed-pay
   allocations; remove float arithmetic from compensation default percentages.
5. Atomically claim VALIDATED → PROCESSING in the database.
6. Add regression assertions for annual allocation, reconciliation, calendar
   period fixture dates, and exact engine Net Pay.
7. Record the architecture, findings, compatibility boundaries, and remaining
   blockers in `PAYROLL_BACKEND_AS_IS.md` and `PAYROLL_BACKEND_BUGS.md`.

## Required next steps before staging/UAT

1. Install the pinned project test dependencies in an isolated environment, then
   run the payroll test modules and full backend suite.
2. Run the changed payroll tests against disposable PostgreSQL, including two,
   five, and ten concurrent claims; verify exactly one transaction can claim a
   run and no duplicate employee/payslip/payment postings commit.
3. Extend the existing `lop_basis` policy beyond v2's `CALENDAR_DAYS` and
   `FIXED_30` to scheduled working days; snapshot the policy on each run and
   bring the legacy calculation engine into parity. Add hire/termination and
   holiday tests. Current missing attendance remains full pay per model policy.
4. Define the exact CTC allocation contract, including employer contributions
   and other employer costs. Validate annual included component totals; do not
   backfill historical runs or salary rows without an approved reconciliation.
5. Introduce database-backed processing-job/idempotency state (or transactional
   outbox) and recovery for worker crashes before/after commit. Tie keys to tenant
   and run; reject retries for locked payroll.
6. Review legal deduction caps/priorities and loan deferral rules with payroll
   compliance owners. Block unresolved negative-net runs until then.
7. Snapshot effective-dated statutory policy per run. Validate PF/ESI eligibility,
   wage bases, contribution-period continuation, rates, rounding, PT state slabs,
   LWF frequency, and TDS against dated official notifications and approved legal
   interpretation. Include the Income-tax Act, 2025 transition for salary
   withholding from 1 April 2026. Do not use current defaults to recalculate
   historical runs.
8. Audit all API serializers, reports, payslips, and accounting exports so exact
   Decimal/integer-minor-unit values remain authoritative while preserving
   established response contracts.
9. Complete cross-tenant tests for run processing, salary changes, attendance,
   loan recovery, payslips, statutory reports, payment batches, and workers.
10. Benchmark representative employee counts only after financial-equivalence
    tests; address N+1 queries while keeping tenant filters and transaction
    behavior intact.

## Test and deployment status

`openpyxl>=3.1.5` was already declared in `requirements.txt`. Python 3.14 had
pytest but lacked that dependency; version 3.1.5 and `et_xmlfile` were installed
into a workspace-local verification target without changing production
dependencies. The payroll regression module passed 20/20 tests (24.82s) with a
one-command test-only encryption key. The statutory module passed 11/11 (27.39s).
`compileall`, `ruff check app/services/payroll/money.py`, and `git diff --check`
passed. A broader Ruff run on the touched Python files reported 218 findings;
no broad autofix was applied. No PostgreSQL/Docker executable or disposable database was available;
PostgreSQL concurrency, 10,000-engine-scenario stress, full backend suite,
type-checking, migration execution, and staging tests were not run. The Python
environment, installed dependencies and focused suites are recorded in
`PAYROLL_BACKEND_VERIFICATION.md`.

## Continuation update — 2026-11-14

Completed since the earlier plan status:

- Added independent negative-net transaction regressions (28 payroll cases pass).
- Fixed Maharashtra PT effective-date defaults and seeded 2023-04-01 version.
- Fixed ESI overtime ceiling/contribution wage handling; current payroll stores
  the exact overtime snapshot and historical lookups use it when available.
- Ran Alembic `upgrade head` plus the disposable PostgreSQL 2/5/10 claim-race,
  tenant-isolation and failure/retry tests (4 pass); temp database and role
  removed.
- Current statutory suite: 13 passed; `compileall` and `git diff --check` pass.

Still open: 10,000 actual DB-backed engine scenarios, hard worker crash/timeout
and duplicate task delivery recovery, payment/ledger settlement idempotency,
the full backend regression after the final statutory edits, and legal review
of PF/TDS/LWF/custom tenant rules. The comparable Ruff check remains at 224
findings. Do not mark the plan as staging-ready; the evidence and exact release
decision are maintained in `PAYROLL_BACKEND_VERIFICATION.md`.

No migration was required by the changes in this pass. Do not deploy based on
this work alone. Once verified in staging, take a database backup, apply schema
migrations before compatible application/worker rollout, verify run totals and
failed-run counts, monitor duplicate claims and payroll failures, and retain a
rollback to the previous application version. Historical payroll rows are not
modified by this change.

