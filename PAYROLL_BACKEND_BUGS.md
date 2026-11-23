# OFC360 Payroll Backend — Findings

Audit performed against the current `apiofc360` tree on 2026-11-14. This is a
code inspection and targeted repair, not a full statutory, database, or
production certification.

## Confirmed defects addressed

| Defect | Evidence before change | Change |
|---|---|---|
| Net Pay drift | `run_service.py` used `max(0, round_to_rupee_paise(gross - deductions))`. ₹33,333.33 gross with no deductions would become ₹33,333.00; over-deductions were silently clamped to zero. | Net now remains exact integer paise. Negative net aborts processing, clears uncommitted employee effects, marks the run FAILED, and returns HTTP 422 for recovery correction. A reconciliation assertion checks gross − deductions = net. |
| Posted component drift | Run totals were assigned without an explicit comparison of the component paise sums to gross and deductions. | The engine now sums posted earning and deduction components in paise and fails the run if either sum differs from the recorded totals. |
| LOP proration | Calculation defaulted missing attendance to 30 days and used a fixed denominator. | V2 uses the inclusive period day count by default and supports configured `FIXED_30`; payslip records denominator days. Missing attendance remains full pay because that is explicitly the current model policy. `SCHEDULED_WORKING_DAYS`, hire/exit proration, and equivalent legacy-engine behavior remain unresolved. |
| Annual CTC remainder | Annual CTC was divided by 12 with floor division; `10000007` paise gave a lost remainder. | Added deterministic 12-month paise allocation (earlier months receive remainder paise). The engine applies the monthly schedule when stored basic/HRA/special/conveyance components exactly match the annual CTC base allocation. Compensation percentage defaults now use integer arithmetic instead of float multiplication. |
| Concurrent processing | Execution performed a read/status check and later committed PROCESSING, so two requests could both pass the check. | A conditional database UPDATE claims only VALIDATED runs. A losing request receives 409. The implementation has not been tested under PostgreSQL concurrency; this is not a full durable idempotency/outbox solution. |
| Effective config and zero components | Config lookup could pick a future/ambiguous active row; explicit zero salary components could fall through to derived defaults. | V2 now selects the latest active config effective by period start, tenant first, and honors explicitly stored zero components. |
| Run retry / worker recovery | Locked or completed runs could be retried, and worker errors could leave the run PROCESSING. | Retry now accepts only unlocked FAILED runs; worker/synchronous exception paths make a best-effort FAILED transition when the run remains PROCESSING. Hard process crashes and recovery after committed postings remain unverified. |
| Accounting export reconciliation | Legacy export used float totals, tolerated sub-rupee imbalance, omitted other deductions, and did not constrain period by tenant. | Export now scopes the period by tenant, reconciles each payslip and total debits/credits in paise, and emits the other-deduction payable line. |
| Monetary input parsing | Bulk CSV CTC and variable inputs truncated values through `int(float(...))`. | Decimal parsing now rejects non-finite and fractional-paise values instead of silently truncating them. |

## Important unaddressed findings

- V2 currently supports `CALENDAR_DAYS` and `FIXED_30` through the existing
  `lop_basis` field. `SCHEDULED_WORKING_DAYS` is not implemented, the policy is
  not snapshotted on each run, and the legacy `PayrollService` path still uses
  calendar-month arithmetic. Do not assume parity across both engines.
- Missing attendance still means full pay by the current `PayrollAttendanceInput`
  model documentation. This is unsafe for organizations that expect attendance
  to be mandatory; there is no explicit per-company approval setting to enforce.
- No settlement adjustment field/model is identified in the run calculation.
  Exact paise payment is now retained; whole-rupee bank settlement behavior needs
  an explicit payment-boundary policy and recorded adjustment design.
- V2 config selection is effective-date and tenant ordered, but PF/ESI/PT/LWF/TDS
  law/rule versions are not fully snapshotted per run. Statutory eligibility,
  historical applicability, and the correct TY 2026-27 TDS framework remain
  compliance review items.
- ESI has a separate wage ceiling and contribution-period logic, but engine
  wiring still needs an end-to-end audit for wage-base separation and historical
  rule snapshots.
- V2 loan lookup uses row locking and duplicate recovery checks, but PostgreSQL
  concurrency, duplicate worker delivery, deferred recovery, full-and-final
  recovery, and rollback across process crashes are not verified. Legal
  deduction priority/caps remain a payroll-owner decision. Negative net is
  rejected; it is not automatically reclassified/deferred.
- A hard worker crash after PROCESSING is committed can still strand the run. The
  tracker is Redis/job state, not a transactional outbox or durable database job
  claim; the new recovery path only handles exceptions that reach application code.
- Payslip generation, payment batches, reports, and the legacy payroll engine
  need complete tenant-scope and idempotency audits before controlled staging.
- JSON breakups and legacy API serializers contain `float()` conversions for
  rupee values. Paise mirrors exist in the principal run calculation, but exact
  serialization needs a compatibility review across all endpoints.
- Focused tests run on the isolated SQLite test fixture only. No disposable
  PostgreSQL instance was available, so lock semantics, deadlocks, simultaneous
  claims, durable crash recovery, live schema, and migrations were not verified.
- Existing audit/financial fixtures include values whose annual CTC and monthly
  component totals do not reconcile. Historical data must not be rewritten
  without explicit backfill approval.

## Statutory evidence and blocker

The code currently defaults PF ceiling to ₹15,000 and ESI ceiling to ₹21,000,
with ESI rate defaults of 0.75% employee and 3.25% employer. Official references
reviewed during this pass include the [EPFO Annual Report 2023–24](https://pmvbry-cdn.epfindia.gov.in/wp-content/uploads/2025/08/Annual_Report_2023-24.pdf)
and [ESIC FAQ](https://www.esic.gov.in/attachments/files/faq.pdf). The FAQ states
the ₹21,000 coverage limit and contribution period half-years; EPFO material
describes historical ₹15,000 ceiling applicability. Current portal content also
references a possible revised ceiling, so these values cannot safely be
certified as the right effective rule for every current and historical payroll
without checking applicable Gazette notifications and each establishment's
coverage/option history. The Income Tax Department also says salary withholding
from 1 April 2026 uses the Income-tax Act, 2025 (Tax Year 2026-27), with TDS
reset on that date; the code's historical tax-regime/rule model has not been
certified against that transition. See [Income Tax Department TDS compliance](https://www.incometax.gov.in/iec/foportal/help/all-topics/e-filing-services/tds-compliance?mobile-app=1)
and [Tax Year 2026-27 slab guidance](https://www.incometax.gov.in/iec/foportal/help/individual/return-applicable-1?mobile-app=1).
The original 11 passing statutory tests verified existing code behavior only
and did not establish full legal compliance. The continuation update below
records two limited, source-backed schedule/base corrections; it does not
constitute full statutory certification.

## Verification update — 2026-11-14

The ESI and Maharashtra PT findings are now confirmed defects and have been
repaired in the default calculation path:

- Maharashtra female PT exemption uses the ₹25,000 monthly threshold from
  2023-04-01, with the prior threshold preserved for historical periods.
- ESI separates the overtime-excluded ceiling wage from the overtime-included
  contribution wage and persists exact overtime component paise for future
  coverage-history calculations.

Fresh statutory tests passed 13/13; negative-net payroll tests passed 28/28.
PostgreSQL claim tests passed 4/4 after Alembic upgrade on a disposable local
database. These results do not establish crash recovery, 10,000-case engine
stress, full backend regression, PF/TDS/LWF legal certification, or payment
settlement idempotency. See `PAYROLL_BACKEND_VERIFICATION.md` for the release
blockers and official sources.

