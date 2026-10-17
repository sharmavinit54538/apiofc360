# AI Module Granular REST API Endpoints Specification

This document specifies the standardized, granular REST endpoints for Aurix HRMS AI Modules in `apiofc360`. These endpoints resolve the mismatch between frontend client calls (`aurix-ai-for-main`) and backend route definitions, providing dedicated paths for dashboards, KPIs, trends, and breakdown analytics.

---

## Architecture & Prefix Convention

All routes are mounted under the global API version prefix `/api/v1`.
Authentication is via standard Bearer token (`Authorization: Bearer <jwt_token>`).

The backend supports:
1. **Primary Endpoints (Frontend Direct)**:
   - `/api/v1/workforce-insights/*`
   - `/api/v1/employee-health/*`
   - `/api/v1/meeting-intelligence/*`
2. **AI Engine Aliases**:
   - `/api/v1/ai/workforce/*`
   - `/api/v1/ai/employee-health/*`
   - `/api/v1/ai/meeting/*`
3. **AI Brain Combined Endpoints**:
   - `/api/v1/ai-brain/workforce-insights`
   - `/api/v1/ai-brain/employee-health`
   - `/api/v1/ai-brain/meeting-intelligence`

All endpoints return the standard `APIResponse[T]` envelope:
```json
{
  "success": true,
  "message": "string",
  "data": { ... },
  "errors": null
}
```

Dual field naming (both `snake_case` and `camelCase`) is provided across responses to guarantee frontend compatibility without requiring client-side transformations.

---

## 1. Workforce Insights (`/api/v1/workforce-insights`)

Reuses `AIWorkforceService` (`app/services/ai_workforce_service.py`).

### 1.1 Dashboard
- **Path**: `GET /api/v1/workforce-insights/dashboard` (also supports `POST`)
- **Query Params**: `department_id` (optional UUID)
- **Description**: Returns complete workforce planning dashboard metrics.
- **Response Shape (`data`)**:
```json
{
  "planned_hires": 12,
  "plannedHires": 12,
  "open_positions": 4,
  "openPositions": 4,
  "capacity_utilization_pct": 89.2,
  "capacityUtilizationPct": 89.2,
  "workforce_size": 25,
  "workforceSize": 25,
  "active_employees": 25,
  "activeEmployees": 25,
  "total_departments": 4,
  "totalDepartments": 4,
  "forecast_horizon": "Q3 2026 - Q2 2027",
  "forecastHorizon": "Q3 2026 - Q2 2027",
  "hiring_budget": 350000.0,
  "hiringBudget": 350000.0,
  "vacancy_rate": 13.8,
  "vacancyRate": 13.8
}
```

### 1.2 KPI Summary
- **Path**: `GET /api/v1/workforce-insights/kpi` (also supports `POST`)
- **Query Params**: `department_id` (optional UUID)
- **Description**: Slices top-level workforce KPIs into a card-friendly structure.
- **Response Shape (`data`)**:
```json
{
  "planned_hires": 12,
  "open_positions": 4,
  "capacity_utilization_pct": 89.2,
  "workforce_size": 25,
  "active_employees": 25,
  "total_departments": 4,
  "forecast_horizon": "Q3 2026 - Q2 2027",
  "hiring_budget": 350000.0,
  "vacancy_rate": 13.8,
  "kpis": [
    {"key": "workforce_size", "label": "Workforce Size", "value": 25, "unit": "employees"},
    {"key": "capacity_utilization_pct", "label": "Capacity Utilization", "value": 89.2, "unit": "%"},
    {"key": "open_positions", "label": "Open Positions", "value": 4, "unit": "roles"},
    {"key": "planned_hires", "label": "Planned Hires", "value": 12, "unit": "hires"},
    {"key": "vacancy_rate", "label": "Vacancy Rate", "value": 13.8, "unit": "%"},
    {"key": "hiring_budget", "label": "Hiring Budget", "value": 350000.0, "unit": "$"}
  ]
}
```

### 1.3 Headcount Trends
- **Path**: `GET /api/v1/workforce-insights/headcount-trends` (also supports `POST`)
- **Description**: Returns historical and projected quarterly headcount trends, hiring trends, and attrition rates.
- **Response Shape (`data`)**:
```json
{
  "headcount_trends": [
    {"quarter": "Q3 2025", "headcount": 82},
    {"quarter": "Q4 2025", "headcount": 87},
    {"quarter": "Q1 2026", "headcount": 91},
    {"quarter": "Q2 2026", "headcount": 95}
  ],
  "headcountTrends": [ ... ],
  "hiring_trend": [
    {"quarter": "Q1 2026", "hires": 6},
    {"quarter": "Q2 2026", "hires": 8}
  ],
  "attrition_trend": [
    {"quarter": "Q1 2026", "attrition_rate": 2.1},
    {"quarter": "Q2 2026", "attrition_rate": 1.8}
  ],
  "productivity_trend": [
    {"quarter": "Q1 2026", "score": 86.5},
    {"quarter": "Q2 2026", "score": 89.2}
  ]
}
```

### 1.4 Department Comparison
- **Path**: `GET /api/v1/workforce-insights/department-comparison` (also supports `POST`)
- **Description**: Returns department-by-department capacity vs. demand analysis, utilization percentages, and headcount gap.
- **Response Shape (`data`)**:
```json
{
  "total_capacity": 25,
  "totalCapacity": 25,
  "total_demand": 29,
  "totalDemand": 29,
  "department_comparison": [
    {
      "department": "Engineering",
      "current_capacity": 10,
      "projected_demand": 12,
      "available_employees": 10,
      "required_employees": 12,
      "gap_analysis": -2,
      "capacity_pct": 83.3,
      "utilization_pct": 91.5
    }
  ],
  "departmentComparison": [ ... ]
}
```

---

## 2. Employee Health (`/api/v1/employee-health`)

Reuses `EmployeeHealthService` (`app/services/employee_health_service.py`).

### 2.1 Dashboard
- **Path**: `GET /api/v1/employee-health/dashboard` (also supports `POST`)
- **Query Params**: `department_id` (optional UUID)
- **Description**: Returns comprehensive employee health sentiment, wellbeing metrics, overtime analytics, and risk factors.
- **Response Shape (`data`)**:
```json
{
  "wellbeingScore": 84.5,
  "wellbeing_score": 84.5,
  "burnoutRisk": 14.2,
  "burnout_risk": 14.2,
  "avgWorkload": "41.5 hrs/week",
  "avg_workload": "41.5 hrs/week",
  "otHours": 18.5,
  "ot_hours": 18.5,
  "high_risk_employees": 2,
  "employees_under_monitoring": 5,
  "healthy_employee_pct": 85.8,
  "wellness_trend": "STABLE",
  "burnoutTrend": [ ... ],
  "teamOvertime": [ ... ],
  "stressIndicators": [ ... ],
  "wellbeingBreakdown": {
    "Work-Life Balance": 88.0,
    "Workload Manageability": 82.5,
    "Team Atmosphere": 86.0,
    "Manager Support": 89.0
  },
  "recommendations": [ ... ]
}
```

### 2.2 KPI Summary
- **Path**: `GET /api/v1/employee-health/kpi` (also supports `POST`)
- **Query Params**: `department_id` (optional UUID)
- **Description**: Slices key health & wellness indicators into standardized KPI cards.
- **Response Shape (`data`)**:
```json
{
  "wellbeing_score": 84.5,
  "wellbeingScore": 84.5,
  "burnout_risk": 14.2,
  "burnoutRisk": 14.2,
  "avg_workload": "41.5 hrs/week",
  "avgWorkload": "41.5 hrs/week",
  "ot_hours": 18.5,
  "otHours": 18.5,
  "high_risk_employees": 2,
  "healthy_employee_pct": 85.8,
  "wellness_trend": "STABLE",
  "kpis": [
    {"key": "wellbeing_score", "label": "Wellbeing Score", "value": 84.5, "unit": "/100"},
    {"key": "burnout_risk", "label": "Burnout Risk Index", "value": 14.2, "unit": "%"},
    {"key": "avg_workload", "label": "Average Workload", "value": "41.5 hrs/week", "unit": ""},
    {"key": "ot_hours", "label": "Overtime Hours", "value": 18.5, "unit": "hrs"},
    {"key": "healthy_employee_pct", "label": "Healthy Workforce", "value": 85.8, "unit": "%"}
  ]
}
```

### 2.3 Burnout Trend
- **Path**: `GET /api/v1/employee-health/burnout-trend` (also supports `POST`)
- **Description**: Returns historical weekly & monthly burnout index trajectory.
- **Response Shape (`data`)**:
```json
{
  "period": "Monthly",
  "burnout_trend": [
    {"month": "Feb 2026", "risk_index": 16.8},
    {"month": "Mar 2026", "risk_index": 15.2},
    {"month": "Apr 2026", "risk_index": 14.2}
  ],
  "burnoutTrend": [ ... ]
}
```

### 2.4 Overtime Metrics
- **Path**: `GET /api/v1/employee-health/overtime` (also supports `POST`)
- **Description**: Returns team overtime hours breakdown, top overtime employees, and financial impact.
- **Response Shape (`data`)**:
```json
{
  "total_ot_hours": 18.5,
  "totalOtHours": 18.5,
  "daily_ot_avg": 0.8,
  "weekly_ot_avg": 4.2,
  "monthly_ot_total": 18.5,
  "team_overtime": [
    {"department": "Engineering", "overtime_hours": 14.5, "employee_count": 6},
    {"department": "Sales", "overtime_hours": 4.0, "employee_count": 4}
  ],
  "teamOvertime": [ ... ],
  "top_ot_employees": [
    {"employee_name": "Vinod Member", "department": "Engineering", "ot_hours": 14.5}
  ],
  "budget_impact": 4625.0
}
```

---

## 3. Meeting Intelligence (`/api/v1/meeting-intelligence`)

Reuses `MeetingAIService` (`app/services/meeting_ai_service.py`).

### 3.1 Dashboard
- **Path**: `GET /api/v1/meeting-intelligence/dashboard` (also supports `POST`)
- **Description**: Returns executive meeting summaries, action items, volume, team engagement, and topic discussions.
- **Response Shape (`data`)**:
```json
{
  "meetings_analyzed": 24,
  "meetingsAnalyzed": 24,
  "action_items": 18,
  "actionItems": 18,
  "follow_ups": 7,
  "followUps": 7,
  "avg_duration": "45 mins",
  "avgDuration": "45 mins",
  "average_attendance": 6,
  "decisions_captured": 32,
  "completion_rate": 88.5,
  "meeting_volume": [ ... ],
  "action_items_by_week": [ ... ],
  "summaries": [ ... ],
  "team_insights": {
    "participation_pct": 91.5,
    "speaking_time_min": 38.0,
    "meeting_sentiment": "POSITIVE"
  },
  "discussion_analytics": {
    "topics_discussed": ["API Performance", "PostgreSQL Indexes"],
    "time_spent_per_topic": {"API Performance": "15 mins"}
  }
}
```

### 3.2 KPI Summary
- **Path**: `GET /api/v1/meeting-intelligence/kpi` (also supports `POST`)
- **Description**: Slices meeting efficiency, action item extraction, and completion metrics.
- **Response Shape (`data`)**:
```json
{
  "meetings_analyzed": 24,
  "meetingsAnalyzed": 24,
  "action_items": 18,
  "actionItems": 18,
  "follow_ups": 7,
  "followUps": 7,
  "avg_duration": "45 mins",
  "avgDuration": "45 mins",
  "average_attendance": 6,
  "decisions_captured": 32,
  "completion_rate": 88.5,
  "kpis": [
    {"key": "meetings_analyzed", "label": "Meetings Analyzed", "value": 24, "unit": "meetings"},
    {"key": "action_items", "label": "Action Items", "value": 18, "unit": "items"},
    {"key": "follow_ups", "label": "Follow-ups", "value": 7, "unit": "tasks"},
    {"key": "avg_duration", "label": "Average Duration", "value": "45 mins", "unit": ""},
    {"key": "decisions_captured", "label": "Decisions Captured", "value": 32, "unit": "decisions"},
    {"key": "completion_rate", "label": "Completion Rate", "value": 88.5, "unit": "%"}
  ]
}
```

### 3.3 Action Items
- **Path**: `GET /api/v1/meeting-intelligence/action-items` (also supports `POST`)
- **Description**: Returns all extracted action items with assignees, due dates, priority, and status.
- **Response Shape (`data`)**:
```json
{
  "total_action_items": 3,
  "totalActionItems": 3,
  "action_items": [
    {
      "task": "Deploy updated API response wrapper middleware",
      "owner": "Vinod Member",
      "due_date": "2026-07-28",
      "priority": "HIGH",
      "status": "PENDING",
      "department": "Engineering"
    }
  ],
  "actionItems": [ ... ]
}
```

### 3.4 Meeting Volume
- **Path**: `GET /api/v1/meeting-intelligence/volume` (also supports `POST`)
- **Description**: Returns daily, weekly, monthly, department, and team meeting distribution analytics.
- **Response Shape (`data`)**:
```json
{
  "daily_meetings": [
    {"day": "Mon", "meetings": 4},
    {"day": "Tue", "meetings": 6}
  ],
  "weekly_meetings": [
    {"week": "Week 1", "meetings": 20},
    {"week": "Week 2", "meetings": 24}
  ],
  "monthly_meetings": [
    {"month": "May 2026", "meetings": 82}
  ],
  "department_meetings": [
    {"department": "Engineering", "meetings": 38}
  ],
  "team_meetings": [
    {"team": "Backend Core", "meetings": 16}
  ],
  "volume": [ ... ]
}
```

---

## 4. Verification & Testing

All endpoints are covered by automated integration test suite:
- File: `tests/test_ai_module_endpoints.py`
- Command: `python -m pytest tests/test_ai_module_endpoints.py -v`
- Coverage:
  - 12 primary endpoints under `/api/v1/{module}/*`
  - 3 aliased endpoints under `/api/v1/ai/{module}/*`
  - Legacy thunk compatibility under `/api/v1/ai-brain/*`

---

## 5. AI Resume Screening (`/api/v2/screening`)

Automated candidate pre-screening with multi-tenant isolation, bias protection, auditability, and human decision workflows.

### 5.1 Trigger Bulk Screening Run
- **Path**: `POST /api/v2/screening/jobs/{job_id}/run`
- **Body**:
```json
{
  "application_ids": ["uuid-1", "uuid-2"],
  "model": "optional-model-override"
}
```
- **Description**: Asynchronous, non-blocking execution across candidate applications.
- **Response Shape (`data`)**:
```json
{
  "run_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "status": "RUNNING",
  "total": 24,
  "thresholds": {
    "shortlist": 0.65,
    "reject": 0.35
  }
}
```

### 5.2 Get Screening Results for Job
- **Path**: `GET /api/v2/screening/jobs/{job_id}/results`
- **Description**: Returns latest screening analysis and decisions per application for the specified job.
- **Response Shape (`data`)**:
```json
{
  "thresholds": {
    "shortlist": 0.65,
    "reject": 0.35
  },
  "run": {
    "run_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "status": "COMPLETED",
    "completed": 24,
    "total": 24
  },
  "results": [
    {
      "application_id": "550e8400-e29b-41d4-a716-446655440000",
      "candidate_id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
      "candidate_name": "Jane Doe",
      "resume_document_id": "7fa85f64-5717-4562-b3fc-2c963f66afa6",
      "status": "COMPLETED",
      "decision": "SHORTLIST",
      "confidence": 0.88,
      "match_score": 0.82,
      "strengths": ["Strong FastAPI expertise", "Distributed systems experience"],
      "weaknesses": ["Limited Kubernetes experience"],
      "missing_skills": ["Kubernetes"],
      "red_flags": [],
      "green_flags": ["Open source contributor"],
      "hiring_recommendation": "Recommend for technical round",
      "hr_notes": "Very strong candidate; verify notice period.",
      "questions_to_ask": ["How do you handle DB concurrency?"],
      "model_used": "ollama",
      "screened_at": "2026-10-01T10:00:00Z",
      "human_decision": null,
      "human_decision_by": null,
      "human_decision_reason": null
    }
  ]
}
```

### 5.3 Submit Human Review Decision
- **Path**: `POST /api/v2/screening/results/{screening_id}/decision`
- **Body**:
```json
{
  "action": "SHORTLIST",
  "reason": "Clear match on all core requirements"
}
```
- **Description**: Records human decision (`SHORTLIST`, `REJECT`, `KEEP_REVIEW`), applies stage changes to the application through `RecruitmentService`, and creates an immutable audit trail entry in `recruitment_audit_logs`.
- **Response Shape (`data`)**:
```json
{
  "screening_id": "7fa85f64-5717-4562-b3fc-2c963f66afa6",
  "action": "SHORTLIST",
  "reason": "Clear match on all core requirements",
  "human_decision_by": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "human_decision_at": "2026-10-01T10:30:00Z",
  "thresholds": {
    "shortlist": 0.65,
    "reject": 0.35
  }
}
```
