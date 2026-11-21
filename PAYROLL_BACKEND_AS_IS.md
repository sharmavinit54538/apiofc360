# OFC360 Payroll Backend — As-Is Map

## Scope and source of truth

The IDE-selected backend is `apiofc360`. The core calculation path is
`app/services/payroll/run_service.py:PayrollRunService.execute_run_calculation`.
It reads active `Compensation` and/or `SalaryStructure`, period attendance input,
approved/pending variable inputs, arrears, loan recovery, and active statutory
configuration; writes one `PayrollRunEmployee` and `Payslip` per employee; then
updates aggregate totals on `PayrollRun`. A second legacy payroll implementation
exists in `app/services/payroll_service.py` and `app/api/payroll/services/`.
The current v2 run endpoint and worker use the `PayrollRunService` engine.

## Workflow map

| Stage | Code and persisted source | Amount representation and behavior | Tenant/transaction notes |
|---|---|---|---|
| Compensation | `app/services/payroll/compensation_service.py`; `compensations` (`ctc_annual_paise`, monthly component paise); legacy `salary_structures` (`NUMERIC(14,2)`) | Primary compensation amounts are integer paise; legacy salary structure values are Decimal. Compensation revisions are separately persisted and approved. | Compensation service looks up by employee ID; endpoint-level tenant guards must be preserved. |
| Payroll period | `app/models/payroll_models.py:PayrollPeriod`; `payroll_periods` | Date boundaries and period month/year are stored. | Company and legal entity ownership are available on the period/run. |
| Attendance / LOP | `PayrollAttendanceInput`; `payroll_attendance_inputs` with unique employee/month/year, Decimal paid/LOP days | Missing input row is explicitly documented as zero LOP/full pay. V2 now selects `CALENDAR_DAYS` or `FIXED_30`; attendance lock sync writes `VariableInput` for OT, shift allowances, and comp-off encashment. | Sync uses period/employee and company filters for source records; run calculation selects attendance by employee and month/year. |
| Earnings | `execute_run_calculation`; `PayrollRunEmployee.earnings_breakup` and `gross_earnings_paise` | Integer paise. Fixed pay is prorated, then variable earnings, arrears, bonuses, and custom components are added. Legacy JSON monetary mirrors are floats; paise mirrors are also stored. | Per-employee work is currently performed in a query loop. |
| Statutory | `app/services/payroll/statutory_service.py`; `StatutoryComplianceConfig`; payslip/run breakups | PF, ESI, PT, LWF, TDS, gratuity use integer paise plus Decimal percentage math. PF/ESI settings include configurable rates/ceilings. ESI coverage period/lock is modeled. | V2 selects an active config effective on period start, preferring tenant config. Many rule values still lack a complete legal effective-date snapshot. |
| Deductions / loans | `execute_run_calculation`, `_advance_deduction_for_employee`; `VariableInput`, `AdvanceLoan`, installments | Integer paise for new variable inputs; legacy loan balances and EMI are Decimal rupees. | Loan recovery mutation is in the calculation path; needs stronger atomic/idempotent and legal-limit review. |
| Net / payslip | `execute_run_calculation`; `PayrollRunEmployee`, `Payslip` | Run employee has `gross_earnings_paise`, `total_deductions_paise`, `net_pay_paise`; payslip also stores `NUMERIC(14,2)` rupees and paise mirrors. | V2 preserves paise, rejects negative net, reconciles component totals, and checks gross less deductions equals net. Legacy calculation and response paths still need equivalent audit. |
| Run lifecycle | `app/api/v2/payroll/runs.py`; `PayrollRun` | Status transitions include VALIDATED, PROCESSING, PROCESSED, PENDING_APPROVAL, APPROVED, LOCKED, PAID, FAILED. | Processing is now claimed with a conditional SQL update; post-claim worker crash recovery is not implemented. |
| Payment / accounting | `payment_batch_service.py`, `accounting_service.py`; payment batch and accounting models | Payment batch uses integer minor units; legacy accounting report path converts Decimal to float. | Payment preparation should only use approved/locked runs; full invariant gating still needs audit. |

## Data typing and boundaries

- Authoritative v2 run totals are integer paise (`BIGINT`), with Decimal display
  values. `app/services/payroll/money.py` is the centralized integer-paise helper.
- Legacy salary/payslip and some loan/accounting fields use `NUMERIC(14,2)`.
- JSON breakups include float-valued rupee mirrors alongside integer paise fields.
  Exact paise values are therefore the safe source for calculation/reconciliation.
- No schema migration was needed for the changes in this repair.

## Security and transaction observations

- V2 run routes require admin/manager roles and pass the authenticated company ID
  to important service methods. Some helper routes shown in the router call a
  service without an explicit company parameter; verify their ownership filters
  before production use.
- Worker dispatch currently creates a job-tracker record, then schedules a task.
  It is not a transactional outbox and repeated HTTP requests can create multiple
  jobs. The run calculation now admits only one database claimant.
- The calculation marks PROCESSING and commits before doing its employee work.
  Worker exception handling can mark an unlocked PROCESSING run FAILED, and retry
  is restricted to unlocked FAILED runs. Hard process termination and crash-after-
  commit recovery still need PostgreSQL-backed proof and a durable job/outbox design.

## Related implementation files

- `app/services/payroll/run_service.py`
- `app/services/payroll/money.py`
- `app/services/payroll/compensation_service.py`
- `app/services/payroll/statutory_service.py`
- `app/services/payroll/attendance_to_payroll_sync_service.py`
- `app/services/payroll/idempotency_service.py`
- `app/api/v2/payroll/runs.py`
- `app/workers/payroll_tasks.py`
- `app/models/payroll.py`, `app/models/payroll_models.py`, `app/models/compensation.py`

## Verification update — 2026-11-14

The earlier environment note about PostgreSQL availability is superseded for
the latest focused claim test: a local loopback PostgreSQL service was used
with a temporary restricted database role/database, Alembic reached `head`,
and the temporary objects were removed. The two/five/ten concurrent-claim,
tenant-isolation, and service failure/retry assertions passed. Hard worker
crashes, Celery redelivery, and lease recovery remain unverified.

The current payroll engine stores the exact overtime component paise in each
`PayrollRunEmployee.earnings_breakup`. ESI coverage excludes this overtime from
the ceiling wage while contribution uses gross wages. Historical records that
lack that component snapshot must fall back to gross; no historical payroll is
rewritten.

The built-in Maharashtra PT schedule is now period-versioned around the
2023-04-01 women’s exemption amendment. The legal and release limitations are
recorded in `PAYROLL_BACKEND_VERIFICATION.md`.

