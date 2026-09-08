import json
from collections import defaultdict

with open("all_live_fastapi_routes.json", "r", encoding="utf-8") as f:
    routes = json.load(f)

# Group by tag and path
tags_map = defaultdict(list)
for r in routes:
    tags = r.get("tags") or ["Uncategorized"]
    for t in tags:
        tags_map[t].append(r)

print("=== ALL TAGS IN FASTAPI ===")
for t in sorted(tags_map.keys()):
    print(f"- {t} ({len(tags_map[t])} routes)")

# Specifically search for dashboard, hr-admin, and main HR modules
hr_admin_modules = [
    "HR Admin User Management",
    "HR Admin Onboarding",
    "Communication Dashboard",
    "Employee Management",
    "Department Management",
    "Face Attendance",
    "Attendance",
    "Leave Management",
    "Payroll",
    "Payroll Management",
    "Application Management",
    "Recruitment Management",
    "Recruitment Analytics & Alerts",
    "Recruitment Alternate Routing",
    "Job Management",
    "Interview Management",
    "Offer Management",
    "Exit Management",
    "Asset Management",
    "Document Management",
    "Timesheet Management",
    "Company Events Management",
    "Announcements Management",
    "Company News Management",
    "Polls Management",
    "Calendar Management",
    "Helpdesk & Ticketing",
    "Helpdesk",
    "HR Analytics Engine v2",
    "AI Insights",
    "AI Analytics Engine",
    "Analytics Engine",
    "AI Copilot",
    "AI Chat Assistant",
    "AI Recruiter v1",
    "AI Performance Management v2",
    "AI Wellness Coach v2",
    "AI Workforce Forecasting v2",
    "AI Compliance Monitor v2",
    "Settings API"
]

print("\n=== SPECIFIC HR-ADMIN & DASHBOARD ROUTES ===")
specific_routes = []
for r in routes:
    p = r["path"]
    t = r["tags"]
    # Check if route is under /api/v1/hr-admin or has HR Admin tag or is dashboard/overview
    if any(m in t for m in ["HR Admin User Management", "HR Admin Onboarding", "Communication Dashboard", "HR Analytics Engine v2"]):
        specific_routes.append(r)
    elif "dashboard" in p.lower() or "stats" in p.lower() or "analytics" in p.lower() or "summary" in p.lower() or "overview" in p.lower() or "kpis" in p.lower():
        specific_routes.append(r)

print(f"Total specific HR/Dashboard routes matching filter: {len(specific_routes)}")

with open("hr_dashboard_extracted.json", "w", encoding="utf-8") as f:
    json.dump(specific_routes, f, indent=2)
