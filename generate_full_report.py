import json

with open("all_live_fastapi_routes.json", "r", encoding="utf-8") as f:
    routes = json.load(f)

seen = set()
deduped = []
for r in routes:
    for m in r["methods"]:
        if m in ("HEAD", "OPTIONS"):
            continue
        key = (m, r["path"])
        if key not in seen:
            seen.add(key)
            deduped.append({
                "method": m,
                "path": r["path"],
                "summary": r.get("summary", ""),
                "tags": r.get("tags", [])
            })

# Let's organize into comprehensive categories for HR Admin / Dashboard:

groups = {
    "1. HR Admin Core & User Management (/hr-admin)": [
        r for r in deduped if r["path"].startswith("/api/v1/hr-admin") and "/onboarding" not in r["path"]
    ],
    "2. HR Admin Onboarding & Setup (/hr-admin/onboarding)": [
        r for r in deduped if r["path"].startswith("/api/v1/hr-admin/onboarding") or "HR Admin Onboarding" in r["tags"]
    ],
    "3. Main HR Admin Dashboard KPI & Summary Endpoints": [
        r for r in deduped if any(r["path"] == p for p in [
            "/api/v1/employees/dashboard",
            "/api/v1/applications/stats",
            "/api/v1/recruitment/dashboard",
            "/api/v1/dashboard/recruitment",
            "/api/v1/attendance/face/analytics",
            "/api/v1/attendance/face/company",
            "/api/v1/leaves/pending",
            "/api/v1/timesheets/pending",
            "/api/v1/payroll/dashboard",
            "/api/v2/payroll/dashboard",
            "/api/v1/payroll/compliance/dashboard",
            "/api/v1/payroll/bank-transfers/dashboard",
            "/api/v1/exits/stats",
            "/api/v1/calendar/dashboard",
            "/api/v1/internal/dashboard",
            "/api/v2/hr-analytics/dashboard",
            "/api/v1/ai-insights/dashboard",
            "/api/v1/ai/dashboard",
            "/api/v1/documents/summary",
            "/api/v1/departments/stats",
            "/api/v1/hierarchy/analytics",
            "/api/v2/reports/stats",
            "/api/v1/helpdesk/admin/tickets"
        ])
    ],
    "4. AI Insights, Analytics & Workforce Intelligence": [
        r for r in deduped if any(t in r["tags"] for t in [
            "AI Insights", "AI Analytics Engine", "AI Analytics Center", "HR Analytics Engine v2",
            "AI Workforce Planning", "AI Attendance Monitor", "AI Performance Coach",
            "AI Leave Assistant", "AI Payroll Insights", "AI Compliance Monitor"
        ])
    ],
    "5. Employee & Department Management (HR Admin View)": [
        r for r in deduped if any(t in r["tags"] for t in [
            "Employee Management", "Department Management", "Manager Management",
            "Employee Hierarchy", "Admin Employee Onboarding"
        ])
    ],
    "6. Attendance, Leaves & Timesheets (HR Admin Approvals & Logs)": [
        r for r in deduped if any(t in r["tags"] for t in [
            "Face Attendance", "Leave Management", "Timesheet Management"
        ])
    ],
    "7. Recruitment, Jobs & ATS Pipeline": [
        r for r in deduped if any(t in r["tags"] for t in [
            "Job Management", "Application Management", "Candidate Management",
            "Interview Management", "Offer Management", "Applicant Tracking System (ATS) Pipeline",
            "Recruitment Analytics & Alerts"
        ])
    ],
    "8. Company Engagement & Operational Feeds (Announcements, Events, News, Polls, Helpdesk, Assets)": [
        r for r in deduped if any(t in r["tags"] for t in [
            "Communication Dashboard", "Announcements Management", "Company Events Management",
            "Company News Management", "Polls Management", "Calendar Management",
            "OFC360 Helpdesk & Support", "Asset Management", "Document Management"
        ])
    ]
}

print("CATEGORY COUNTS:")
for g_name, g_routes in groups.items():
    print(f"- {g_name}: {len(g_routes)} routes")

with open("full_hr_admin_dashboard_report.json", "w", encoding="utf-8") as f:
    json.dump(groups, f, indent=2)
