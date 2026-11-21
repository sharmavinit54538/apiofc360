# OFC360 Attendance Module - Payroll Integration Guide

## Overview

This document describes the integration between the Attendance Module and Payroll System, ensuring accurate, auditable, and compliant payroll calculations.

## Integration Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Attendance     │────▶│  Attendance-To-  │────▶│  Payroll        │
│  Records        │     │  Payroll Sync    │     │  Variable Inputs│
└─────────────────┘     └──────────────────┘     └─────────────────┘
                              │
                              ▼
                       ┌──────────────────┐
                       │  Payroll Period  │
                       │  Locking         │
                       └──────────────────┘
```

## Data Flow

### 1. Attendance Lock Process

When payroll period is locked via `POST /api/v2/payroll/cycles/{cycleId}/lock-attendance`:

1. **Lock Timestamp**: `PayrollPeriod.attendance_locked_at` set to current time
2. **Sync Trigger**: `AttendanceToPayrollSyncService.sync_on_attendance_lock()` called
3. **Aggregation**: Attendance records for period aggregated per employee
4. **Variable Inputs**: Created/updated in `VariableInput` table with `source="ATTENDANCE_LOCK"`

### 2. Attendance Aggregation Logic

#### Overtime Calculation
```python
# Source: Approved OvertimeEntry records (status in APPROVED, PUSHED)
ot_hours = entry.adjusted_hours or entry.ot_hours
ot_amount = calculate_overtime_paise(
    basic_monthly_paise=basic,
    gross_monthly_paise=gross,
    ot_hours=ot_hours,
    multiplier=policy.rate_multiplier,  # Default 1.5x
    rate_base=policy.rate_base,         # BASIC or GROSS
    working_days=policy.working_days,
    hours_per_day=policy.hours_per_day
)
```

**Requirements**: 
- Only `APPROVED`/`PUSHED` overtime entries used
- Overtime policies: company-specific > role/grade-specific > global
- Rate base: BASIC (default) or GROSS per policy

#### Shift Allowance Calculation
```python
# Source: Attendance records in period
for attendance in attendance_records:
    if attendance.status not in {"ABSENT", "CANCELLED", "REJECTED"}:
        # Verify attendance is verified
        if not attendance.verified:
            continue
        # Skip correction pending
        if attendance.attendance_state == AttendanceState.CORRECTION_PENDING:
            continue
        
        # Match shift allowance policy
        policies = ShiftAllowancePolicy.active for company
        match by: shift_id OR shift_type (NIGHT/WEEKEND/HOLIDAY)
        # One allowance per day (shift-specific wins over type)
        daily_allowance = policy.allowance_paise
```

**Requirements**:
- Only verified attendance counted
- Excludes `ABSENT`, `CANCELLED`, `REJECTED`, `CORRECTION_PENDING`
- One allowance per day (shift-specific priority)
- Off-day/holiday work triggers WEEKEND/HOLIDAY policies

#### Comp-Off Encashment
```python
# Source: CompOffLedger with status=ENCASHED in period
encashment = encashment_amount_paise or (gross/30 * credit_days)
```

---

## Payroll Period Locking

### Lock States
| State | Description | Attendance Modifications |
|-------|-------------|-------------------------|
| OPEN | Period active, attendance editable | Full edit/delete allowed |
| LOCKED | `attendance_locked_at` set | Blocked (409 ATTENDANCE_PERIOD_LOCKED) |
| REGULARIZATION | Locked but retroactive allowed | Only via regularization workflow |

### Lock API
```
POST /api/v2/payroll/cycles/{cycleId}/lock-attendance
POST /api/v2/payroll/cycles/{cycleId}/attendance-lock (alias)
POST /api/v2/payroll/cycles/{cycleId}/unlock-attendance (with reason)
```

### Lock Enforcement
```python
# In AttendanceCoreService.update_attendance() and delete_attendance()
await assert_attendance_period_editable(
    session, record.company_id, record.date,
    action="modify locked attendance"
)

# In regularization review (allows retroactive for authorized roles)
period = await assert_attendance_period_editable(
    session, req.company_id, req.request_date,
    action="review retroactive attendance regularisation",
    allow_retroactive=True, actor_role=reviewer_role
)
```

### Authorized Retroactive Roles
- `admin`
- `hr_admin`
- `super_admin`
- `cfo`
- `ceo`

---

## Variable Input Generation

### Output Table: `VariableInput`
| Field | Source | Description |
|-------|--------|-------------|
| `type` | OVERTIME / SHIFT_ALLOWANCE / COMP_OFF_ENCASHMENT | Input category |
| `amount_paise` | Calculated | Amount in paise |
| `units` | Hours (OT) / Days (shift/comp-off) | Quantity |
| `rate_per_unit_paise` | OT rate | Per-unit rate |
| `status` | APPROVED | Always approved when synced |
| `is_locked` | true | Immutable after sync |
| `source` | ATTENDANCE_LOCK | Traceability |
| `approved_at` | Sync timestamp | Audit trail |
| `remarks` | "Generated and locked by attendance-to-payroll synchronisation" | |

### Idempotency
- Re-running sync replaces existing `ATTENDANCE_LOCK` rows
- `OT` status changes `APPROVED` → `PUSHED` after successful sync
- Zero amounts don't create new rows (unless existing row exists)

---

## Leave Integration

### Approved Leaves as Off Days
```python
# In ShiftService._check_off_day()
if business_date in leave_dates:  # Approved LeaveRequest dates
    return True, "leave"
```

### Payroll Impact
- Leave days excluded from shift allowance calculation
- Leave days excluded from expected working days denominator
- Leave balances tracked separately in Leave module

### Leave Types Supported
- Paid Leave (PL) - Counted as present for payroll
- Unpaid Leave (UL) - Excluded from payable days
- Half-day Leave - Prorated
- Compensatory Off (Comp-Off) - Can be encashed

---

## Attendance Regularization & Payroll

### Workflow
```
Employee submits regularization
    ↓
Manager/HR reviews (APPROVE/REJECT)
    ↓
If APPROVED:
    - Attendance record updated
    - attendance_state = CORRECTED
    - Working hours recalculated
    ↓
If payroll period was LOCKED:
    - ArrearLedger created (ATTENDANCE_RETRO)
    - Delta days/amount recorded
    - Next payroll includes adjustment
```

### Arrear Calculation
```python
ArrearService.create_arrear(
    employee_id=req.employee_id,
    company_id=req.company_id,
    source_period_id=period.id,
    arrear_type="ATTENDANCE_RETRO",
    delta_days=delta_days,        # Working day difference
    amount_paise=amount_paise,    # Monetary difference
    calculation_json={
        "regularisation_id": str(req.id),
        "request_date": req.request_date.isoformat()
    },
    created_by=reviewer_id
)
```

---

## Attendance Percentage for Payroll

### Formula
```
Attendance Rate = (Present Days / Eligible Working Days) × 100

Where:
- Present Days = Count of verified attendance records (Present + Late)
- Eligible Working Days = Scheduled working days per shift
                          - Approved leave days
                          - Holidays
                          - Weekly offs
```

### Implementation
```python
# In AttendanceCoreService.get_analytics()
total_active = count(Employee WHERE company_id AND is_active)
present = count(Attendance WHERE status IN (Present, Late) AND verified)
attendance_rate = (present / total_active) * 100

# In AIAttendanceRepository (per employee)
expected_work_days = sum(shifts WHERE NOT is_off AND NOT is_holiday)
attendance_pct = (att_cnt / expected_work_days) * 100
```

---

## Reconciliation Checklist (Period-End)

Before locking payroll period:

1. **Verify Attendance Completeness**
   - [ ] All employees have attendance records for working days
   - [ ] Missing check-outs auto-closed or regularized
   - [ ] No `CORRECTION_PENDING` records (all reviewed)

2. **Validate Overtime**
   - [ ] All OT entries `APPROVED` or `PUSHED`
   - [ ] OT hours match attendance working hours
   - [ ] OT policies correctly assigned

3. **Confirm Shift Allowances**
   - [ ] Night/weekend/holiday shifts have policies
   - [ ] Verified attendance only counted
   - [ ] One allowance per day enforced

4. **Check Comp-Off**
   - [ ] Encashed comp-offs in period captured
   - [ ] Encashment amounts correct

5. **Lock Attendance**
   - [ ] Run `POST /cycles/{id}/lock-attendance`
   - [ ] Verify `attendance_locked_at` timestamp set
   - [ ] Confirm VariableInput rows created

6. **Generate Payroll**
   - [ ] Payroll run uses locked attendance data
   - [ ] ArrearLedger includes attendance retros

---

## Error Handling & Monitoring

### Common Sync Errors
| Error | Cause | Resolution |
|-------|-------|------------|
| No PayrollPeriod found | Period not created | Create period before lock |
| Overtime policy missing | No active policy | Create default/global policy |
| Shift allowance not matched | Shift not in policy | Add shift to policy |
| Comp-off not encashed | Status not ENCASHED | Process encashment first |

### Monitoring Queries
```sql
-- Check for unlocked periods with attendance
SELECT * FROM payroll_periods 
WHERE attendance_locked_at IS NULL 
AND end_date < CURRENT_DATE;

-- Verify attendance completeness
SELECT e.id, e.name, COUNT(a.id) as days_present
FROM employees e
LEFT JOIN attendances a ON a.employee_id = e.id 
  AND a.date BETWEEN :start AND :end
  AND a.verified = true
WHERE e.company_id = :cid AND e.is_active = true
GROUP BY e.id
HAVING COUNT(a.id) < expected_working_days;

-- Find unverified attendance
SELECT * FROM attendances 
WHERE verified = false 
AND date BETWEEN :start AND :end;
```

---

## API Contracts for Payroll Integration

### Lock Attendance
```http
POST /api/v2/payroll/cycles/{cycleId}/lock-attendance
Authorization: Bearer <token>
Content-Type: application/json

Response 200:
{
  "success": true,
  "data": { "period": {...} },
  "message": "Attendance locked and payroll inputs synchronised successfully"
}
```

### Sync Status Check
```http
GET /api/v2/payroll/cycles/{cycleId}
Response 200:
{
  "success": true,
  "data": {
    "id": "uuid",
    "attendance_locked_at": "2026-11-16T10:30:00Z",
    "attendance_locked_by": "uuid",
    "status": "LOCKED",
    ...
  }
}
```

### Variable Inputs for Period
```http
GET /api/v1/payroll/variable-inputs?period_id={cycleId}
Response 200:
{
  "success": true,
  "data": [
    {
      "id": "uuid",
      "employee_id": "uuid",
      "type": "OVERTIME",
      "amount_paise": 150000,
      "units": 10.5,
      "rate_per_unit_paise": 14285,
      "source": "ATTENDANCE_LOCK",
      "is_locked": true,
      "approved_at": "2026-11-16T10:30:00Z"
    }
  ]
}
```

---

## Testing Checklist

### Unit Tests
- [ ] Overtime calculation with BASIC vs GROSS rate base
- [ ] Shift allowance priority (shift_id > shift_type)
- [ ] Comp-off encashment fallback calculation
- [ ] Payroll period lock blocks edits
- [ ] Regularization creates arrear for locked period
- [ ] Leave days excluded from shift allowance

### Integration Tests
- [ ] Full lock → sync → variable input generation
- [ ] Multiple lock attempts (idempotent)
- [ ] Unlock → re-lock cycle
- [ ] Attendance edit after lock (blocked)
- [ ] Regularization during locked period (allowed for HR)

### Edge Cases
- [ ] Employee terminated mid-period
- [ ] Shift change mid-period
- [ ] Overtime entry adjusted after sync
- [ ] Comp-off encashed then voided
- [ ] Leave approved after lock (excluded from period)

---

## Deployment Notes

### Required Configuration
1. **Overtime Policies**: At least one active per company
2. **Shift Allowance Policies**: Configure for NIGHT, WEEKEND, HOLIDAY
3. **Payroll Periods**: Created with correct dates before first lock
4. **Company Geofence**: Not required for payroll but needed for attendance

### Migration Notes
- Run `alembic upgrade head` for `attendance_state` column
- Existing attendance records default to `CHECKED_IN` state
- Historical data: `verified` column used for payroll eligibility
- Regularization requests: ensure `attendance_id` populated

---

## Support Contacts

| Component | Owner | Slack |
|-----------|-------|-------|
| Attendance Core | Backend Team | #backend-attendance |
| Face Biometrics | AI Team | #ai-face-attendance |
| Payroll Integration | Payroll Team | #payroll-integration |
| Shift Engine | Backend Team | #backend-shifts |