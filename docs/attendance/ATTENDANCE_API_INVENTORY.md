# OFC360 Attendance Module - API Inventory

## Canonical Attendance API Routes (Face Attendance Module)

### Face Biometric Operations
| Method | Path | Description | Auth | Rate Limit |
|--------|------|-------------|------|------------|
| POST | `/api/v1/attendance/face/check-in` | Face biometric check-in with liveness detection | Employee | 10/min |
| POST | `/api/v1/attendance/face/check-out` | Face biometric check-out with working hours calculation | Employee | 10/min |
| POST | `/api/v1/attendance/face-enroll` | Enroll face embedding (AES-256 encrypted) | Employee | 5/min |
| GET | `/api/v1/attendance/face-status` | Check face enrollment status | Employee | 30/min |

### Break Management
| Method | Path | Description | Auth | Rate Limit |
|--------|------|-------------|------|------------|
| POST | `/api/v1/attendance/break/start` | Start break with face verification | Employee | 10/min |
| POST | `/api/v1/attendance/break/end` | End break with face verification | Employee | 10/min |

### Geofence
| Method | Path | Description | Auth | Rate Limit |
|--------|------|-------------|------|------------|
| POST | `/api/v1/attendance/geofence/verify` | Verify coordinates against company geofence | Employee | 30/min |

### Employee Self-Service
| Method | Path | Description | Auth | Rate Limit |
|--------|------|-------------|------|------------|
| GET | `/api/v1/attendance/face/me` | Current attendance status with breaks | Employee | 30/min |
| GET | `/api/v1/attendance/face/history` | Personal attendance history (paginated) | Employee | 30/min |

### Team/Company Views (Manager/Admin)
| Method | Path | Description | Auth | Rate Limit |
|--------|------|-------------|------|------------|
| GET | `/api/v1/attendance/face/team` | Team attendance today | Manager | 30/min |
| GET | `/api/v1/attendance/face/company` | Company attendance today | Admin/Manager | 30/min |
| GET | `/api/v1/attendance/face/analytics` | Today's dashboard KPIs | Admin/Manager | 10/min |
| GET | `/api/v1/attendance/analytics/rate` | Attendance rate analytics | Admin/Manager | 10/min |
| GET | `/api/v1/attendance/analytics/distribution` | Attendance distribution | Admin/Manager | 10/min |
| GET | `/api/v1/attendance/analytics/weekly` | Weekly aggregated data | Admin/Manager | 10/min |
| GET | `/api/v1/attendance/analytics/trends` | Daily attendance trends | Admin/Manager | 10/min |

### Shift & Roster Management
| Method | Path | Description | Auth | Rate Limit |
|--------|------|-------------|------|------------|
| GET | `/api/v1/attendance/shifts/options` | Available shifts for assignment | Admin/Manager | 30/min |
| GET | `/api/v1/attendance/shifts` | List shifts (paginated) | Admin/Manager | 30/min |
| POST | `/api/v1/attendance/shifts` | Create shift | Admin | 10/min |
| GET | `/api/v1/attendance/shifts/{shift_id}` | Get shift details | Admin/Manager | 30/min |
| PUT/PATCH | `/api/v1/attendance/shifts/{shift_id}` | Update shift | Admin | 10/min |
| DELETE | `/api/v1/attendance/shifts/{shift_id}` | Delete shift | Admin | 5/min |
| GET | `/api/v1/attendance/rosters` | List rosters | Admin/Manager | 30/min |
| POST | `/api/v1/attendance/rosters` | Create roster | Admin/Manager | 10/min |
| POST | `/api/v1/attendance/rosters/bulk` | Bulk create roster entries | Admin/Manager | 5/min |
| GET | `/api/v1/attendance/rosters/{roster_id}` | Get roster details | Admin/Manager | 30/min |
| PUT/PATCH | `/api/v1/attendance/rosters/{roster_id}` | Update roster | Admin/Manager | 10/min |
| DELETE | `/api/v1/attendance/rosters/{roster_id}` | Delete roster | Admin | 5/min |

---

## Core HRMS Attendance Routes (Non-Biometric)

### Employee Self-Service
| Method | Path | Description | Auth | Rate Limit |
|--------|------|-------------|------|------------|
| GET | `/api/v1/attendance/me` | Today's attendance record | Employee | 30/min |
| GET | `/api/v1/attendance/status` | Check-in/out status | Employee | 30/min |
| GET | `/api/v1/attendance/history` | Personal history (paginated) | Employee | 30/min |

### Company Views (Admin/Manager)
| Method | Path | Description | Auth | Rate Limit |
|--------|------|-------------|------|------------|
| GET | `/api/v1/attendance/today` | Today's company attendance | Admin/Manager | 30/min |
| GET | `/api/v1/attendance/team` | Team attendance today | Manager | 30/min |
| GET | `/api/v1/attendance/company` | Company attendance (paginated) | Admin/Manager | 30/min |
| GET | `/api/v1/attendance/records` | Filtered records (date, status) | Admin/Manager | 30/min |
| GET | `/api/v1/attendance/summary` | Today's analytics summary | Admin/Manager | 30/min |
| GET | `/api/v1/attendance/analytics` | Today's analytics | Admin/Manager | 30/min |
| GET | `/api/v1/attendance/analytics/trends` | Trend analytics | Admin/Manager | 10/min |
| GET | `/api/v1/attendance/analytics/rate` | Attendance rate analytics | Admin/Manager | 10/min |
| GET | `/api/v1/attendance/analytics/weekly` | Weekly analytics | Admin/Manager | 10/min |
| GET | `/api/v1/attendance/calendar` | Monthly calendar with working days | Admin/Manager | 10/min |
| GET | `/api/v1/attendance/late` | Late records | Admin/Manager | 30/min |
| GET | `/api/v1/attendance/early-leaving` | Early leaving records | Admin/Manager | 30/min |
| GET | `/api/v1/attendance/missing` | Missing punch records | Admin/Manager | 30/min |
| GET | `/api/v1/attendance/overtime` | Overtime records | Admin/Manager | 30/min |
| GET | `/api/v1/attendance/export` | CSV export (streaming) | Admin/Manager | 5/min |

### Attendance Modification (Admin/Manager)
| Method | Path | Description | Auth | Rate Limit |
|--------|------|-------------|------|------------|
| PUT/PATCH | `/api/v1/attendance/{attendance_id}` | Manual update with audit reason | Admin/Manager | 10/min |
| DELETE | `/api/v1/attendance/{attendance_id}` | Delete with payroll lock check | Admin/Manager | 5/min |

### Regularization
| Method | Path | Description | Auth | Rate Limit |
|--------|------|-------------|------|------------|
| GET | `/api/v1/attendance/regularization` | List regularization requests | Employee/Manager/HR | 30/min |
| POST | `/api/v1/attendance/regularization` | Submit regularization request | Employee | 10/min |
| POST | `/api/v1/attendance/regularization/{id}/review` | Approve/Reject (HR/Admin) | HR/Admin | 10/min |

---

## AI Attendance Monitoring Routes

### Dashboard & Analytics
| Method | Path | Description | Auth | Rate Limit |
|--------|------|-------------|------|------------|
| GET | `/api/v1/ai/attendance/dashboard` | AI dashboard KPIs | Admin/Manager | 10/min |
| GET | `/api/v1/ai/attendance/trend` | Attendance trends | Admin/Manager | 10/min |
| GET | `/api/v1/ai/attendance/late-arrivals` | Late arrival details | Admin/Manager | 10/min |
| GET | `/api/v1/ai/attendance/anomalies` | Anomaly detection | Admin/Manager | 10/min |
| GET | `/api/v1/ai/attendance/absence-pattern` | Absence patterns | Admin/Manager | 10/min |
| GET | `/api/v1/ai/attendance/overtime` | Overtime metrics | Admin/Manager | 10/min |
| GET | `/api/v1/ai/attendance/shift-violations` | Shift violations | Admin/Manager | 10/min |
| GET | `/api/v1/ai/attendance/health-score` | Composite health score | Admin/Manager | 10/min |
| GET | `/api/v1/ai/attendance/watchlist` | Absentee watchlist | Admin/Manager | 10/min |

### AI Hub Attendance Monitor
| Method | Path | Description | Auth | Rate Limit |
|--------|------|-------------|------|------------|
| GET | `/api/v1/ai-hub/attendance-monitor` | Monitor overview | Admin/Manager | 10/min |
| POST | `/api/v1/ai-hub/attendance-monitor/analyze` | Date-range analysis | Admin/Manager | 5/min |
| GET | `/api/v1/ai-hub/attendance-monitor/anomalies` | Paginated anomalies | Admin/Manager | 10/min |

---

## Legacy / School Attendance Routes (Separate Module)

| Method | Path | Description | Auth | Rate Limit |
|--------|------|-------------|------|------------|
| GET | `/api/v1/attendance` | List student attendance | Teacher/Admin | 30/min |
| POST | `/api/v1/attendance` | Mark attendance (bulk) | Teacher/Admin | 10/min |
| GET | `/api/v1/attendance/report` | Attendance report | Teacher/Admin | 10/min |
| GET | `/api/v1/attendance/export/csv` | CSV export | Teacher/Admin | 5/min |
| GET | `/api/v1/attendance/export/pdf` | PDF export | Teacher/Admin | 5/min |

---

## Removed / Deprecated Routes

The following duplicate routes have been **removed** to eliminate conflicts:

| Removed Route | Canonical Replacement |
|---------------|----------------------|
| `POST /api/v1/attendance/face/check-in` (core router) | `POST /api/v1/attendance/face/check-in` (face module) |
| `POST /api/v1/attendance/face/check-out` (core router) | `POST /api/v1/attendance/face/check-out` (face module) |
| `POST /api/v1/attendance/face/enroll` | `POST /api/v1/attendance/face-enroll` |
| `GET /api/v1/attendance/face/status` | `GET /api/v1/attendance/face-status` |
| `POST /api/v1/attendance/checkin` | `POST /api/v1/attendance/face/check-in` |
| `POST /api/v1/attendance/face/checkin` | `POST /api/v1/attendance/face/check-in` |
| `POST /api/v1/attendance/checkout` | `POST /api/v1/attendance/face/check-out` |
| `POST /api/v1/attendance/face/checkout` | `POST /api/v1/attendance/face/check-out` |

---

## Request/Response Schemas

### Face Check-In Request
```json
{
  "image_base64": "string (required)",
  "location": {
    "latitude": "number",
    "longitude": "number",
    "accuracy": "number (optional)"
  },
  "notes": "string (optional)",
  "device_info": "string (optional)",
  "ip_address": "string (optional)",
  "work_mode": "string (optional: office|remote|field)"
}
```

### Face Check-In Response
```json
{
  "success": true,
  "message": "Checked in successfully.",
  "data": {
    "id": "uuid",
    "employee_id": "uuid",
    "date": "YYYY-MM-DD",
    "check_in_time": "ISO8601",
    "status": "Present|Late",
    "attendance_state": "CHECKED_IN",
    "is_late": false,
    "late_minutes": 0,
    "shift_name": "string",
    "scheduled_start": "ISO8601",
    "scheduled_end": "ISO8601",
    "verified": true,
    "punch_verified_by": "FACE",
    "liveness_score": 0.95,
    "face_distance": 0.32
  }
}
```

### Face Check-Out Response
```json
{
  "success": true,
  "message": "Checked out successfully.",
  "data": {
    "id": "uuid",
    "employee_id": "uuid",
    "date": "YYYY-MM-DD",
    "check_in_time": "ISO8601",
    "check_out_time": "ISO8601",
    "status": "Present",
    "attendance_state": "CHECKED_OUT",
    "working_hours": 8.5,
    "overtime_hours": 0.5,
    "is_early_checkout": false,
    "early_minutes": 0,
    "break_duration": 1.0,
    "verified": true,
    "punch_verified_by": "FACE"
  }
}
```

### Geofence Verification Response
```json
{
  "inside_geofence": true,
  "distance": 45.2,
  "allowed_radius": 200.0,
  "accuracy": 10.0,
  "status": "INSIDE_GEOFENCE",
  "office_name": "Main Office",
  "message": "Inside designated office zone (Main Office).",
  "geofence_required": true,
  "flexible_mode_warning": false
}
```

### Attendance State Machine
```
NOT_CHECKED_IN (no record)
    ↓ check-in
CHECKED_IN
    ↓ start break
ON_BREAK
    ↓ end break
CHECKED_IN
    ↓ check-out
CHECKED_OUT
    ↓ (auto-close stale)
AUTO_CHECKED_OUT

CORRECTION_PENDING → CORRECTED (via regularization)
```

---

## Error Response Format
```json
{
  "success": false,
  "message": "Error description",
  "data": null,
  "errors": [{"field": "field_name", "message": "specific error"}],
  "code": "ERROR_CODE"
}
```

### Common Error Codes
| Code | HTTP Status | Description |
|------|-------------|-------------|
| `FACE_NOT_ENROLLED` | 403 | Face biometric not enrolled |
| `FACE_MISMATCH` | 400 | Live face doesn't match enrolled |
| `FACE_QUALITY_LOW` | 400 | Image quality/liveness failed |
| `LIVENESS_FAILED` | 400 | Anti-spoofing check failed |
| `MULTIPLE_FACES` | 400 | More than one face detected |
| `FACE_NOT_FOUND` | 400 | No face detected |
| `ALREADY_CHECKED_IN` | 409 | Active session exists |
| `NO_ACTIVE_CHECKIN` | 400 | No check-in to check-out/break |
| `ALREADY_CHECKED_OUT` | 400 | Cannot break after checkout |
| `BREAK_ACTIVE` | 409 | Break already in progress |
| `NO_ACTIVE_BREAK` | 400 | No break to end |
| `OUTSIDE_GEOFENCE` | 400 | Coordinates outside allowed zone |
| `LOCATION_MISSING` | 400 | GPS coordinates required |
| `INVALID_COORDINATES` | 400 | Invalid lat/lng values |
| `ACCURACY_LOW` | 400 | GPS accuracy exceeds limit |
| `GEOFENCE_REQUIRED_NOT_CONFIGURED` | 400 | Strict mode but no geofence set |
| `TENANT_MISMATCH` | 403 | Employee not in requester's company |
| `EMPLOYEE_NOT_FOUND` | 404 | No employee profile for user |
| `EMPLOYEE_INACTIVE` | 403 | Employee account inactive |
| `ATTENDANCE_PERIOD_LOCKED` | 409 | Payroll period locked |
| `REGULARISATION_DEADLINE_PASSED` | 409 | Correction deadline passed |
| `STORAGE_ERROR` | 500 | Failed to save image |

---

## Rate Limiting
- Face operations: 10 requests/minute per user
- Analytics: 10 requests/minute per user
- Exports: 5 requests/minute per user
- General queries: 30 requests/minute per user

Rate limits enforced via `RateLimitMiddleware` with Redis backend.