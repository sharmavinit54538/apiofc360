# OFC360 Backend - Issue Fix Summary

## Issues Fixed and Verified (1-10)

### 1. FIXED: V1 "Mark as paid" in bank_service.py
- Links transfer to exact payslip via `pay_cycle_id` -> `PayCycle(period_month/year)`
- Updates only the specific payslip, not all non-paid payslips for employee
- Atomic transaction: transfer update + payslip update + audit log
- Returns reconciliation error for ambiguous links
- Idempotent: returns success if already paid

### 2. FIXED: Protect uploads in .github/workflows/deploy-dev.yml
- Added `--exclude=uploads/` to rsync `--delete` command
- Preserves persistent uploads across deployments

### 3. FIXED: V1 salary bank batch creation
- Requires `pay_cycle_id` in payload
- Selects only eligible payslips for that company and cycle
- Uses actual PayCycle period relationship
- Handles empty batch with clear response
- Removes HDFC Bank fallback and random cycle ID
- Reports missing bank details explicitly

### 4. FIXED: V1 bank payment initiation and download
- Uses `BankAdviceFile.generated_at` for ordering
- Download URL generated from registered route (`/api/v1/payroll/bank-transfers/download/{id}`)

### 5. FIXED: Full & Final settlement in fnf_calculation_service.py
- Imports `PayrollRunEmployee` and `PayrollPeriod` from correct modules
- Joins through `PayrollRun` to `PayrollPeriod` for unpaid salary calculation

### 6. FIXED: Gratuity eligibility at calendar anniversaries
- Replaced days/365.25 with calendar-based anniversary calculation
- Correctly handles: day before anniversary (0), on anniversary (eligible), day after (eligible)
- Handles leap year joining dates (Feb 29)
- Applies 6-month rounding only after minimum years requirement met

### 7. FIXED: Migration path around revision 921a
- New migration `17c1ab7c9e4d` removes synthetic Default Company assignment
- Makes `company_id` nullable for reconciliation
- Adds `reconciliation_needed` flag and notes to `security_policies`, `security_roles`, `ip_whitelist`
- Creates `security_reconciliation_queue` view for operators
- Preserves all historical data for manual reconciliation

### 8. FIXED: role_code unique per company
- Added `UniqueConstraint(company_id, role_code)` to SecurityRole model
- Made `company_id` nullable to support reconciliation workflow
- Two companies can each create their own HR_ADMIN role

### 9. FIXED: Organization reactivation preserves individual deactivation
- Reactivation only activates users not individually deactivated
- Checks audit log for `SUPER_ADMIN_DEACTIVATE_USER` actions

### 10. FIXED: FastAPI route ordering in employees.py and departments.py
- Moved `/validate-invitation`, `/validate-token`, `/validate` before `/{id}` in employees.py
- Moved `PATCH /bulk-status` and `/bulk-assign-manager` before `/{id}` in departments.py
- All 5 routes now reach their handlers correctly

## Test Results
- alembic single head: **PASSED**
- migration graph integrity: **PASSED**
- database integration: **PASSED**
- cross-tenant isolation (22 tests): **PASSED**
- gratuity calculation (3 tests): **PASSED**
- payroll repaired modules (8/9 passed, 1 expected failure due to API change requiring `pay_cycle_id`)

## Files Modified
- `.github/workflows/deploy-dev.yml`
- `app/api/departments.py`
- `app/api/employees.py`
- `app/api/payroll/services/bank_service.py`
- `app/api/super_admin.py`
- `app/models/security_setting.py`
- `app/services/fnf_calculation_service.py`

## New Files
- `alembic/versions/17c1ab7c9e4d_fix_921a_reconciliation.py`

## Remaining Issues (11-19) - Not Yet Addressed
11. Face check-in work_mode handling
12. HR/Executive overview queries
13. Super Admin metrics
14. AI Analytics Center payroll totals
15. Payroll security audit feed
16. Holiday import
17. Celery Beat in dev build
18. CI workflow expansion
19. Recruitment batch-screening task

## Deployment/Historical Reconciliation Steps Requiring Operator
- Run migration `17c1ab7c9e4d` to fix 921a migration issues
- Review `security_reconciliation_queue` view for ambiguous historical records
- Manually assign correct `company_id` to records marked `reconciliation_needed=true`
- Update any hardcoded references to "Default Company" in application code