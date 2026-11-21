# OFC360 Payroll Backend Verification

## Continuation status addendum — 2026-11-14 (supersedes earlier baseline below)

This is a partial verification result, **not a release certification**. Earlier
sections preserve the baseline audit trail; where they conflict with this
addendum, the results below are current.

### Repairs and fresh evidence

| Finding | Repair | Current evidence |
|---|---|---|
| Negative net could be clamped or posted | Exact paise reconciliation; negative net transitions the run to FAILED with structured `NEGATIVE_NET_PAY` validation and audit data; invalid postings roll back. | `tests/test_payroll_lock_arrears_ot_parallel.py`: 28 passed, including gross 1,000/deductions 1,200; zero gross; one-paise overage; zero/one-paise net; loan/arrear rollback and retry. |
| Maharashtra PT female exemption was too low | Effective-dated default slabs and tenant rule seeding now retain the pre-amendment schedule through 2023-03-31 and apply the female ₹25,000 exemption from 2023-04-01. Male slabs and February collection remain gender-specific. | Statutory tests: current female ₹15,000/₹25,000 = zero; >₹25,000 = ₹200 or ₹300 in February; 2022 female ₹15,000 = ₹200; male boundary cases pass. |
| ESI coverage ceiling included overtime | ESI coverage wage excludes exact persisted overtime paise; the ESI contribution wage continues to include gross wages including overtime. Historical run snapshots are used where available; old records without the snapshot fall back to gross because overtime cannot be inferred. | ESI tests verify ₹20,000 coverage wages with ₹21,500 contribution wages remain covered; ₹21,100 coverage wages are outside the ceiling when not locked. Correct rounding is ₹162 employee / ₹699 employer; see final addendum. |
| PostgreSQL processing claim had no live race evidence | Retained the conditional `VALIDATED → PROCESSING` claim and tested actual service calls on disposable PostgreSQL. | Alembic `upgrade head` passed; `tests/test_payroll_postgres_concurrency.py`: 4 passed. Simultaneous 2/5/10 requests yielded one accepted claim, all others 409; one run-employee and one payslip; no loan installments/payment batches/items. Cross-tenant and fail/retry cases passed. Temp role/database were removed. |

### Current command results

With the workspace-local `openpyxl` target, test-only encryption key, and an
unreachable application `DATABASE_URL` for SQLite-focused runs:

```powershell
python -m pytest -q tests/test_statutory_pf_esi_pt_lwf_tds_form138_130.py
# 13 passed, 0 failed, 0 skipped (58.24s)

python -m pytest -q tests/test_payroll_lock_arrears_ot_parallel.py
# 28 passed, 0 failed, 0 skipped (27.75s)

python -m compileall -q app/services/payroll app/workers/payroll_tasks.py app/api/v2/payroll/runs.py tests/test_payroll_lock_arrears_ot_parallel.py tests/test_statutory_pf_esi_pt_lwf_tds_form138_130.py
# passed

git diff --check
# passed; only existing unrelated line-ending warnings

python -m ruff check app/api/v2/payroll/runs.py app/services/payroll/accounting_service.py app/services/payroll/compensation_service.py app/services/payroll/run_service.py app/services/payroll/variable_input_service.py app/workers/payroll_tasks.py tests/test_payroll_lock_arrears_ot_parallel.py --statistics
# 224 findings (the same 7-file scope as the prior 224-count run); no autofix
```

The PostgreSQL commands were run by a temporary local orchestrator that created
a random restricted role and database from loopback PostgreSQL credentials,
ran `python -m alembic upgrade head`, then ran
`python -m pytest -q tests/test_payroll_postgres_concurrency.py`. It dropped
the database and role in a `finally` block. The test run took 58.20 seconds.

Earlier in this continuation, `tests/test_payroll_full_suite.py` passed 11/11
and `tests/test_payroll_phases_1_and_2.py` passed 5/5 against disposable
migrated PostgreSQL. Those broad suites were run before the latest PT/ESI
changes; current post-change coverage is the 28 payroll and 13 statutory tests
listed above. They are not the entire backend test suite.

### Statutory source review and limits

| Rule | Verified rule/effective date | Evidence and remaining decision |
|---|---|---|
| Maharashtra PT | From 2023-04-01, women up to ₹25,000/month are exempt; above this, ₹2,500/year (₹200 monthly; ₹300 February). | Official [Maharashtra PT Act](https://www.mahagst.gov.in/public/uploads/mvatservices/1760346808Maharashtra%20Profession%20Tax%20Act%201975.pdf), [2023 amendment](https://www.mahagst.gov.in/public/uploads/mvatservices/1760521417PT%20Amendment%20Act%2C%202023_English.pdf) (published 2023-04-06, effective 2023-04-01), and [rate schedule](https://www.mahagst.gov.in/public/uploads/mvatservices/1761635767Rate%20Schedules%20under%20the%20Professions%20Tax%20Act%2C%201975%201.pdf). Engine regressions added; tenant-supplied/custom rules still require review. |
| ESI | Coverage ceiling ₹21,000 (PwD ceiling configuration may apply); contribution periods Apr–Sep and Oct–Mar; overtime is excluded for ceiling eligibility and included for contribution wages. Current default rates are 0.75% employee / 3.25% employer effective 2019-07-01. | Official [ESIC FAQ](https://www.esic.gov.in/attachments/files/faq.pdf) and [ESIC Standard Note as of 2025-01-01](https://www.srosalem.esic.gov.in/attachments/publicationfile/Standard_Note_on_Employees_State_Insurance_Scheme_as_on_01_01_2025_English_1757940841.pdf). Implemented and tested wage-base split; establishment coverage facts and newer notifications still require counsel/payroll sign-off. |
| PF / EPS | Existing ₹15,000 ceiling and EPF/EPS calculation remain as configured. | [EPFO Annual Report 2023–24](https://pmvbry-cdn.epfindia.gov.in/wp-content/uploads/2025/08/Annual_Report_2023-24.pdf). Not certified for membership exceptions, higher-wage options, wage definition, establishment facts or subsequent effective notifications. |
| TDS | Income Tax Department guidance says payments on/before 2026-03-31 use the 1961 Act; from 2026-04-01, section 392(1) of the 2025 Act / Tax Year 2026-27 applies and withholding resets. | [TDS compliance guidance](https://www.incometax.gov.in/iec/foportal/help/all-topics/e-filing-services/tds-compliance?mobile-app=1). The implementation’s transition and slab mapping are **not certified** against all operative rules. |
| LWF and other state PT | No comprehensive legal certification. | Frequency, exemptions, state schedules and tenant/company coverage need dated local legal review. |

### Remaining blockers and decision

- **10,000 actual full-engine scenarios: NOT RUN.** No 10,000-case result is claimed. A reproducible stress harness must exercise the DB-backed run engine and capture seed, context, policy versions and failures.
- **Worker crash/timeout/restart and duplicate task delivery: NOT VERIFIED.** PostgreSQL tests cover simultaneous claims and service failure/retry, not hard process termination or Celery broker redelivery. Crash-after-claim can leave a run PROCESSING; durable lease/outbox/reaper behavior is not proven.
- **Payment/ledger idempotency and settlement: incomplete.** Concurrency assertions checked duplicate payslips, run employees, loan installments and payment batches/items; they did not perform payment execution or comprehensive ledger posting/reconciliation.
- **Full backend regression: NOT RUN after the final statutory edits.** The earlier 11+5 payroll suites passed against disposable PostgreSQL; authentication, attendance, leaves and unrelated modules were not run as a full suite.
- **Statutory status: partial.** Maharashtra PT and ESI overtime rules were source-checked and regression-tested. PF, TDS, LWF and custom tenant schedules remain legal blockers.
- **Ruff:** current comparable 7-file scope is 224 findings: UP045 100, B008 35, FURB157 27, RUF059 14, BLE001 11, F401 9, I001 6, TRY401 6, UP017 4, UP035 3, S110 3, B023 2, F841 2, RUF012 1, RUF100 1. Most are type syntax, FastAPI dependency defaults, Decimal constructor style and test tuple unpacking; BLE001/broad catches deserve targeted review. No bulk autofix. `money.py` passed Ruff in the earlier isolated run.
- **API/schema:** migration to current Alembic head passed on disposable PostgreSQL. A full API serialization precision/consumer compatibility audit was not performed.

No production database, frontend, payment or deployment was touched. Historical
approved payroll rows were not backfilled. Preserve the current staging gate.

**NOT VERIFIED — Required stress, worker-crash recovery, full-backend and complete statutory validation remain incomplete.**

Audit date: 2026-11-14. Scope: backend-only focused repair in `apiofc360`.
No production database, frontend, or deployment was touched. The repository had
pre-existing unrelated settings/expense and API changes; those were preserved.

## Confirmed fixes and evidence

| Bug | File(s) | Root cause | Repair | Verification |
|---|---|---|---|---|
| Whole-rupee Net Pay drift and negative clamp | `app/services/payroll/run_service.py`, `money.py` | Net rounded to rupees and negative results clamped to zero. | Keep net in integer paise; reject negative net and assert exact gross less deductions equals net. | 20 payroll regressions passed; paise-preserving engine case passed. |
| Earnings/deductions component drift | `run_service.py` | Header totals could diverge from posted component paise. | Reconcile posted earning and deduction component totals before commit. | Engine lifecycle regressions passed. |
| Wrong LOP denominator | `run_service.py` | Fixed 30 denominator used for all months. | Use inclusive period days or configured `FIXED_30`; payslip carries the basis day count. | 28-day, leap 29-day, 30-day, 31-day, fractional LOP, and full LOP cases passed. |
| Annual CTC remainder loss | `money.py`, `run_service.py`, `compensation_service.py` | Integer division dropped remainder paise and defaults used float percentages. | Allocate annual paise deterministically; use integer/Decimal compensation defaults and enforce component bounds. | ₹100,000.07 (10,000,007 paise) allocated as 11 × 833,334 + 833,333 paise; sum exact. |
| Duplicate processing claim | `run_service.py` | Separate status read and update allowed simultaneous requests to pass. | Conditional `VALIDATED → PROCESSING` database update; losing claim returns conflict. | Code path covered by SQLite-focused tests only; PostgreSQL claim race is NOT VERIFIED. |
| Duplicate / stale recovery and retry | `run_service.py`, `workers/payroll_tasks.py`, `app/api/v2/payroll/runs.py` | Reruns could post recoveries again; locked runs could be retried; handled worker errors could leave PROCESSING. | Row-lock loan reads, duplicate recovery check, retry only unlocked FAILED, and best-effort failure transition on handled exceptions. | SQLite duplicate recovery and locked retry tests passed; PostgreSQL lock/race and hard crash behavior NOT VERIFIED. |
| CTC component zero fallback | `run_service.py` | Explicit zero components were treated as absent and replaced by derived defaults. | Respect present zero values. | Fractional salary regression passed. |
| Statutory config ambiguity | `run_service.py` | Active config selection could choose future or non-tenant rows nondeterministically. | Choose latest config effective by period start; prefer tenant row over global. | Focused payroll and statutory suites passed. |
| Input truncation | `compensation_service.py`, `variable_input_service.py` | `int(float(value))` silently lost fractional paise. | Parse Decimal and reject non-finite/fractional-paise amounts. | Compile and focused suite passed; dedicated CSV edge-case coverage remains incomplete. |
| Accounting export imbalance / missing deduction payable | `accounting_service.py` | Float totals, sub-rupee tolerance, omitted other deductions, and unscoped period. | Tenant-scope period and reconcile payslips/debits/credits in paise; add other-deduction payable line. | Accounting export fixture passed exact paise balance assertion. |

## Financial verification matrix

| Scenario | Gross | Deductions | Net | Variance | Status |
|---|---:|---:|---:|---:|---|
| Direct reconciliation case | 33,333.33 | 0.00 | 33,333.33 | 0.00 | PASS |
| V2 engine retains fractional paise | 33,333.33 gross fixture | Actual fixture deductions; exact net recorded | Gross minus deductions in paise | 0 paise | PASS |
| Annual CTC remainder | Annual 100,000.07 | N/A | N/A | 0.00 annual allocation remainder | PASS |
| Negative net rejection | Not independently exercised in the focused tests | Over gross | Expected run failure | Not measured | NOT VERIFIED |
| 10,000 engine scenarios | Not run | Not run | Not run | Not measured | NOT VERIFIED |

The focused tests check component reconciliation and engine exactness, but do
not constitute the requested 10,000-case engine stress test or settlement to
payment reconciliation. `assert_payroll_reconciles` tests are not a substitute
for end-to-end posting tests.

## LOP verification

V2 test cases: February 2026 (28 days, 0.5 LOP), leap February 2024 (29 days,
3.5 LOP), April (30 days, 1 LOP), May (31 days, full LOP), and February under
`FIXED_30` (0.5 LOP). Missing attendance remains full pay per current model
policy. Scheduled-working-day proration and hire/exit dates were not tested.
The legacy payroll service still calculates independently, so policy parity is
not established.

## Statutory verification

| Rule area | Automated evidence | Legal/effective-date result |
|---|---|---|
| PF / EPS | Covered by existing statutory test module. | NOT CERTIFIED: eligibility, membership history, wage definition, and ceiling applicability require establishment/employee facts and dated legal review. |
| ESI | Existing golden case: ₹200 wages produces employee ₹2 and employer ₹7 under configured whole-rupee rounding. | NOT CERTIFIED: coverage and contribution-period continuation require employee wage history and effective rule review. |
| PT / LWF / TDS | Existing statutory tests pass. | NOT CERTIFIED: state slab versions, LWF schedules, and current tax-year mapping need payroll/legal sign-off. |

For salary paid from 1 April 2026, the Income Tax Department says withholding
uses the Income-tax Act, 2025, Tax Year 2026-27, and TDS calculations reset on
that date. This repair did not implement or certify that transition. See the
[Income Tax Department TDS guidance](https://www.incometax.gov.in/iec/foportal/help/all-topics/e-filing-services/tds-compliance?mobile-app=1)
and [Tax Year 2026-27 slab guidance](https://www.incometax.gov.in/iec/foportal/help/individual/return-applicable-1?mobile-app=1).
Existing defaults include ₹15,000 PF and ₹21,000 ESI ceilings; defaults are not
legal confirmation for each employer or period. EPFO source: [Annual Report
2023-24](https://pmvbry-cdn.epfindia.gov.in/wp-content/uploads/2025/08/Annual_Report_2023-24.pdf).

## Test commands and results

Environment: Windows PowerShell, Python 3.14, `pytest` already installed.
`openpyxl>=3.1.5` was declared by the project. `openpyxl==3.1.5` and its
`et_xmlfile` dependency were installed into `.venv-payroll-verify/Lib/site-packages`
as an isolated verification target; production dependency files were not edited.
`FIELD_ENCRYPTION_KEY` was set only for each test command to a 64-character
test-only hex value; `.env` was not modified.

```powershell
$env:PYTHONPATH=(Resolve-Path '.venv-payroll-verify/Lib/site-packages').Path
$env:FIELD_ENCRYPTION_KEY='[temporary 64-character test-only key]'
python -m pytest -q tests/test_payroll_lock_arrears_ot_parallel.py
# 20 passed in 24.82s

python -m pytest -q tests/test_statutory_pf_esi_pt_lwf_tds_form138_130.py
# 11 passed in 27.39s

python -m pytest -q tests/test_batch7_p3_differentiators.py::test_global_payroll_snapshots_country_calculators_and_compensation_rounding
# 1 passed in 7.72s

python -m compileall -q app/services/payroll app/workers/payroll_tasks.py app/api/v2/payroll/runs.py tests/test_payroll_lock_arrears_ot_parallel.py
# passed
python -m ruff check app/services/payroll/money.py
# All checks passed!
python -m ruff check app/services/payroll/money.py app/services/payroll/run_service.py app/services/payroll/compensation_service.py app/services/payroll/variable_input_service.py app/services/payroll/accounting_service.py app/workers/payroll_tasks.py app/api/v2/payroll/runs.py tests/test_payroll_lock_arrears_ot_parallel.py
# NOT CLEAN: 218 Ruff findings across the checked files; many are existing style/API patterns, so no repo-wide autofix was applied.
git diff --check
# passed (line-ending warnings only in pre-existing unrelated files)
```

Final focused test totals: 32 passed, 0 failed, 0 skipped. Money utility Ruff
passed in isolation; the broader touched-file Ruff run is not clean (218
findings). An earlier rerun
used an invalid, too-short temporary test key and failed 17 fixture cases; the
key was corrected and the final results above are the valid run. That setup
failure did not indicate payroll calculation failures.

Not run: full backend suite, PostgreSQL integration, two/five/ten-way
concurrency, duplicate worker delivery, crash-before/after-commit recovery,
10,000-scenario engine stress, type checking, migration execution, or staging.
No PostgreSQL/Docker executable or disposable DB was available. SQLite test
results are not evidence of PostgreSQL lock behavior.

## Concurrency report

| Simultaneous requests | Accepted claims | Financial postings | Duplicates | Final run status |
|---:|---:|---:|---:|---|
| Not executed | Not measured | Not measured | Not measured | Not measured |

The database-conditional claim and code-level recovery paths are implemented,
but all requested PostgreSQL concurrency outcomes remain NOT VERIFIED.

## Modified payroll files

- `app/services/payroll/run_service.py`
- `app/services/payroll/money.py`
- `app/services/payroll/compensation_service.py`
- `app/services/payroll/variable_input_service.py`
- `app/services/payroll/accounting_service.py`
- `app/workers/payroll_tasks.py`
- `app/api/v2/payroll/runs.py`
- `tests/test_payroll_lock_arrears_ot_parallel.py`
- `PAYROLL_BACKEND_AS_IS.md`
- `PAYROLL_BACKEND_BUGS.md`
- `PAYROLL_BACKEND_FIX_PLAN.md`
- `PAYROLL_BACKEND_VERIFICATION.md` (this report)

Pre-existing unrelated settings/expense/API edits remain untouched.

## Remaining blockers and deployment safety

Severity **critical before staging**: PostgreSQL concurrency and crash recovery
are untested; statutory effective rules and 2026-27 TDS transition are
uncertified; negative-net and 10,000-case engine stress scenarios are missing;
the legacy engine and payment/payslip serializers are not fully audited.

Before staging: provision disposable PostgreSQL; run tenant-isolated concurrent
claim, duplicate-worker, rollback/retry, and payment posting tests; run 10,000
deterministic cases through the actual engine; complete dated legal review and
versioned policy snapshots; run the full backend suite and migration checks.
No production deployment is recommended from this verification. For a later
approved rollout, back up the staging database, apply reviewed migrations,
deploy compatible API/worker versions, inspect run totals and failure counts,
and roll back the application and worker versions if reconciliation or claim
metrics fail. This repair created no migration and changed no historical rows.

## ESI rounding and final verification addendum — 2026-11-14

The reported ₹161 employee ESI fixture was incorrect. At ₹21,500 contribution
wages, 0.75% is ₹161.25 and 3.25% is ₹698.75. Both shares round to the next
higher whole rupee: employee ESI ₹162 and employer ESI ₹699 (16,200 and
69,900 paise).

Rule 51 of the ESI (Central) Rules, 1950 has required next-higher-rupee
rounding since 2004-10-01 (G.S.R. 316, dated 2004-08-26). Rule 19 of the
Social Security (Central) Rules, 2026 has the same requirement and applies
from publication on 2026-05-08 (G.S.R. 344(E)). The calculation already used
ceiling-to-rupee arithmetic; the issue was stale rule documentation and missing
verification coverage, not the arithmetic. The result now reports its
effective rule identifier/date. Regression tests cover below, exact, and above
whole-rupee boundaries and the ₹21,500 case under both rules.

Sources: [ESI Central Rules, 1950, Rule 51](https://thc.nic.in/Central%20Governmental%20Rules/Employees%E2%80%99%20State%20Insurance%20%28Central%29%20Rules%2C%201950..pdf) and [Official Gazette G.S.R. 344(E), Rule 19](https://www.labour.gov.in/static/uploads/2026/05/49aa9b62c2125499c37399b90e969d67.pdf).

Fresh post-change evidence:

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) '.venv-payroll-verify\Lib\site-packages')
$env:FIELD_ENCRYPTION_KEY = ('0' * 64)
$env:DATABASE_URL = 'postgresql+asyncpg://unused:unused@127.0.0.1:1/not_a_database'
python -m pytest -q --basetemp .pytest-temp-payroll tests/test_payroll_lock_arrears_ot_parallel.py tests/test_statutory_pf_esi_pt_lwf_tds_form138_130.py
# 43 passed, 0 failed, 0 skipped (46.62s)

python -m compileall -q app tests
# passed

git diff --check
# passed; existing line-ending warnings only

python -m pytest -q
# 928 passed, 197 failed, 8 skipped, 7 errors (22:07)
```

The full suite used the machine's configured loopback PostgreSQL URL; no local
PostgreSQL listener was present, so DB-backed checks failed. Seven setup errors
were blocked by Windows temp-directory access. Other failures include
non-payroll API/test issues. This run cannot establish which failures pre-date
the current working-tree changes. No production database or bank service was
used. The 10,000 persisted-engine stress run, hard Celery crash/redelivery
tests, disposable-PostgreSQL lifecycle tests, payment/ledger retry tests, and
complete PF/ESI/PT/TDS/LWF legal certification remain unexecuted.

The comparable Ruff scope remains 224 findings, unchanged from the prior scan.
Ruff 0.17.5 was installed only into the workspace verification target. An
additional scan of `statutory_service.py` and its statutory test module reports
171 findings. No automatic fixes were applied; findings were not fully
categorized by severity or baseline ownership.

## Release decision

**NOT VERIFIED — Required PostgreSQL, stress, worker recovery, payment idempotency, full-suite, and complete statutory checks remain unavailable or incomplete.**
