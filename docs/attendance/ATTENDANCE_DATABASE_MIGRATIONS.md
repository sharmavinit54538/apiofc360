# OFC360 Attendance Module - Database Migrations

## Migration History

### Migration: `4b2891fdd6b8_add_attendance_state_column`

**Revision ID**: `4b2891fdd6b8`
**Revises**: `36bffd8d9cb4`
**Created**: 2026-11-16 07:48:33

#### Purpose
Add attendance state machine support to the `attendances` table for tracking attendance lifecycle.

#### Changes

| Operation | Details |
|-----------|---------|
| Add Column | `attendance_state` VARCHAR(30) NOT NULL DEFAULT 'CHECKED_IN' |
| Add Index | `ix_attendances_state` on `attendance_state` |
| Add Index | `ix_attendances_check_out_time` on `check_out_time` |
| Add Constraint | Partial unique index `uq_attendance_open_session` on `employee_id WHERE check_out_time IS NULL` |
| Add Constraint | CHECK constraint `ck_attendance_state_valid` for valid states |

#### Valid States
```sql
CHECK (attendance_state IN (
    'CHECKED_IN',
    'ON_BREAK', 
    'CHECKED_OUT',
    'AUTO_CHECKED_OUT',
    'CORRECTION_PENDING',
    'CORRECTED'
))
```

#### Partial Unique Index (Concurrency Protection)
```sql
CREATE UNIQUE INDEX uq_attendance_open_session 
ON attendances (employee_id) 
WHERE check_out_time IS NULL;
```
Prevents multiple active check-in sessions per employee.

#### Data Migration
- Existing records default to `CHECKED_IN` state
- Records with `check_out_time` set should be `CHECKED_OUT` (handled by application logic)
- Auto-closed records: `AUTO_CHECKED_OUT`

---

## Affected Tables

### `attendances` (Primary)
```sql
-- New column
attendance_state VARCHAR(30) NOT NULL DEFAULT 'CHECKED_IN'

-- New indexes
CREATE INDEX ix_attendances_state ON attendances (attendance_state);
CREATE INDEX ix_attendances_check_out_time ON attendances (check_out_time);

-- New constraints
ALTER TABLE attendances 
ADD CONSTRAINT ck_attendance_state_valid 
CHECK (attendance_state IN ('CHECKED_IN', 'ON_BREAK', 'CHECKED_OUT', 'AUTO_CHECKED_OUT', 'CORRECTION_PENDING', 'CORRECTED'));

-- Partial unique index (PostgreSQL)
CREATE UNIQUE INDEX uq_attendance_open_session 
ON attendances (employee_id) 
WHERE check_out_time IS NULL;
```

### `attendance_breaks` (Related)
No schema changes, but break operations now update `attendances.attendance_state`:
- `BREAK_START` → `ON_BREAK`
- `BREAK_END` → `CHECKED_IN`

### `attendance_regularization_requests` (Related)
No schema changes, but status transitions trigger state changes:
- `PENDING` → attendance `CORRECTION_PENDING`
- `APPROVED` → attendance `CORRECTED`

---

## Migration Commands

### Apply Migration
```bash
# From project root
alembic upgrade head

# Or specific revision
alembic upgrade 4b2891fdd6b8
```

### Verify Migration
```sql
-- Check column exists
SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_name = 'attendances' AND column_name = 'attendance_state';

-- Check constraint
SELECT conname, pg_get_constraintdef(oid)
FROM pg_constraint
WHERE conrelid = 'attendances'::regclass AND conname = 'ck_attendance_state_valid';

-- Check indexes
SELECT indexname, indexdef
FROM pg_indexes
WHERE tablename = 'attendances' AND indexname IN ('ix_attendances_state', 'ix_attendances_check_out_time', 'uq_attendance_open_session');
```

### Rollback (if needed)
```bash
alembic downgrade 36bffd8d9cb4
```

**Rollback Operations**:
1. Drop CHECK constraint `ck_attendance_state_valid`
2. Drop partial unique index `uq_attendance_open_session`
3. Drop indexes `ix_attendances_check_out_time`, `ix_attendances_state`
4. Drop column `attendance_state`

---

## Pre-Migration Checklist

- [ ] Backup database
- [ ] Verify no active transactions on `attendances` table
- [ ] Confirm application version compatible with state machine
- [ ] Schedule maintenance window (migration adds indexes - brief lock)

---

## Post-Migration Verification

### Application-Level Checks
1. **Check-in**: Creates record with `attendance_state = 'CHECKED_IN'`
2. **Break Start**: Updates to `'ON_BREAK'`
3. **Break End**: Updates to `'CHECKED_IN'`
4. **Check-out**: Updates to `'CHECKED_OUT'`
5. **Auto-close**: Updates to `'AUTO_CHECKED_OUT'`
5. **Regularization Submit**: Updates to `'CORRECTION_PENDING'`
6. **Regularization Approve**: Updates to `'CORRECTED'`

### Database-Level Checks
```sql
-- Verify all records have valid state
SELECT attendance_state, COUNT(*) 
FROM attendances 
GROUP BY attendance_state;

-- Check for invalid states (should return 0 rows)
SELECT * FROM attendances 
WHERE attendance_state NOT IN ('CHECKED_IN', 'ON_BREAK', 'CHECKED_OUT', 'AUTO_CHECKED_OUT', 'CORRECTION_PENDING', 'CORRECTED');

-- Verify partial unique index works
-- Attempt to insert two records with same employee_id and check_out_time NULL
-- Should fail with unique constraint violation
```

---

## Related Model Changes

### Python Enum (`app/attendance/models/attendance.py`)
```python
class AttendanceState(str, enum.Enum):
    CHECKED_IN = "CHECKED_IN"
    ON_BREAK = "ON_BREAK"
    CHECKED_OUT = "CHECKED_OUT"
    AUTO_CHECKED_OUT = "AUTO_CHECKED_OUT"
    CORRECTION_PENDING = "CORRECTION_PENDING"
    CORRECTED = "CORRECTED"
```

### SQLAlchemy Column Definition
```python
attendance_state: Mapped[AttendanceState] = mapped_column(
    String(30), nullable=False, 
    default=AttendanceState.CHECKED_IN, 
    server_default=text("'CHECKED_IN'")
)
```

### Table Args
```python
__table_args__ = (
    UniqueConstraint("employee_id", "date", name="uq_employee_date_attendance"),
    Index("ix_attendances_employee_id", "employee_id"),
    Index("ix_attendances_company_id", "company_id"),
    Index("ix_attendances_date", "date"),
    Index("ix_attendances_state", "attendance_state"),
    Index("ix_attendances_check_out_time", "check_out_time"),
    # Partial unique index created via migration
    CheckConstraint(
        "attendance_state IN ('CHECKED_IN', 'ON_BREAK', 'CHECKED_OUT', 'AUTO_CHECKED_OUT', 'CORRECTION_PENDING', 'CORRECTED')",
        name="ck_attendance_state_valid"
    ),
)
```

---

## State Transition Diagram

```
[No Record] 
     │
     ▼ CHECK-IN (face or manual)
CHECKED_IN ──────────────────────┐
     │                            │
     ▼ BREAK START                │
ON_BREAK                          │
     │                            │
     ▼ BREAK END                  │
CHECKED_IN ◄─────────────────────┘
     │
     ▼ CHECK-OUT
CHECKED_OUT

     │ (Auto-close stale session)
     ▼
AUTO_CHECKED_OUT

     │ (Regularization)
     ▼
CORRECTION_PENDING ────► APPROVE ──► CORRECTED
     │                     │
     └───────── REJECT ────┘
```

### Transition Rules

| From State | To State | Trigger | Validation |
|------------|----------|---------|------------|
| - | CHECKED_IN | Check-in | No active session, no duplicate date |
| CHECKED_IN | ON_BREAK | Break start | No active break, not checked out |
| ON_BREAK | CHECKED_IN | Break end | Active break exists |
| CHECKED_IN | CHECKED_OUT | Check-out | Active session |
| CHECKED_IN | AUTO_CHECKED_OUT | Auto-close | Stale session (prev day or >16h) |
| CHECKED_IN | CORRECTION_PENDING | Regularization submit | Period editable or retroactive allowed |
| ON_BREAK | CORRECTION_PENDING | Regularization submit | Period editable or retroactive allowed |
| CORRECTION_PENDING | CORRECTED | Regularization approve | Reviewer authorized |
| CORRECTION_PENDING | (original) | Regularization reject | - |

---

## Performance Considerations

### Index Usage
| Index | Query Pattern |
|-------|---------------|
| `ix_attendances_state` | Filter by state (e.g., active sessions) |
| `ix_attendances_check_out_time` | Find records without checkout |
| `uq_attendance_open_session` | Prevent duplicate active sessions |
| `uq_employee_date_attendance` | One record per employee per day |
| `ix_attendances_employee_id` | Employee history queries |
| `ix_attendances_company_id` | Company-wide reports |
| `ix_attendances_date` | Date-range queries |

### Query Examples
```sql
-- Active sessions for employee (uses partial unique index)
SELECT * FROM attendances 
WHERE employee_id = :eid AND check_out_time IS NULL;

-- All records in correction pending
SELECT * FROM attendances 
WHERE attendance_state = 'CORRECTION_PENDING';

-- Today's records for company
SELECT * FROM attendances 
WHERE company_id = :cid AND date = CURRENT_DATE;
```

---

## Troubleshooting

### Common Issues

| Issue | Cause | Resolution |
|-------|-------|------------|
| Duplicate key on `uq_attendance_open_session` | Race condition check-in | Application handles with 409, retry with exponential backoff |
| Invalid state error | Manual DB update | Only use application state transitions |
| Migration fails on partial index | PostgreSQL version < 9.5 | Upgrade PostgreSQL (partial indexes require 9.5+) |
| State not updating | Missing commit | Ensure `session.commit()` after state change |

### Debug Queries
```sql
-- Find employees with multiple active sessions (should be 0)
SELECT employee_id, COUNT(*) as active_count
FROM attendances
WHERE check_out_time IS NULL
GROUP BY employee_id
HAVING COUNT(*) > 1;

-- Find records with unexpected state for date
SELECT id, employee_id, date, attendance_state, check_in_time, check_out_time
FROM attendances
WHERE date = CURRENT_DATE
AND attendance_state NOT IN ('CHECKED_IN', 'CHECKED_OUT');
```

---

## Rollback Plan

If migration causes issues:

1. **Immediate**: `alembic downgrade 36bffd8d9cb4`
2. **Application**: Deploy previous version without state machine code
3. **Data**: Column will be dropped, no data loss for existing records
4. **Verify**: All attendance operations work without state field

**Note**: Partial unique index and CHECK constraint will be removed. Application will need to handle duplicate prevention at application level temporarily.