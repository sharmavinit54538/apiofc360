import json

with open("all_live_fastapi_routes.json", "r", encoding="utf-8") as f:
    routes = json.load(f)

# Deduplicate routes by (method, path)
seen = set()
deduped_routes = []
for r in routes:
    for m in r["methods"]:
        key = (m, r["path"])
        if key not in seen:
            seen.add(key)
            deduped_routes.append({
                "method": m,
                "path": r["path"],
                "name": r.get("name", ""),
                "tags": r.get("tags", []),
                "summary": r.get("summary", "")
            })

def get_routes_by_tag(tag):
    return [r for r in deduped_routes if tag in r["tags"]]

def get_routes_by_path_prefix(prefix):
    return [r for r in deduped_routes if r["path"].startswith(prefix)]

print("1. HR Admin User Management:", len(get_routes_by_tag("HR Admin User Management")))
print("2. HR Admin Onboarding:", len(get_routes_by_tag("HR Admin Onboarding")))
print("3. Communication Dashboard:", len(get_routes_by_tag("Communication Dashboard")))
print("4. HR Analytics Engine v2:", len(get_routes_by_tag("HR Analytics Engine v2")))
print("5. AI Insights & Analytics:", len(get_routes_by_tag("AI Insights")) + len(get_routes_by_tag("AI Analytics Engine")))

# Let's categorize all relevant HR Admin & Dashboard endpoints
categories = {
    "HR_ADMIN_CORE": [r for r in deduped_routes if "/hr-admin" in r["path"] and "/onboarding" not in r["path"]],
    "HR_ADMIN_ONBOARDING": [r for r in deduped_routes if "/hr-admin/onboarding" in r["path"] or "HR Admin Onboarding" in r["tags"]],
    "HR_DASHBOARDS_MAIN_KPIS": [r for r in deduped_routes if any(k in r["path"] for k in ["/dashboard", "/stats", "/internal/dashboard"]) and not r["path"].startswith("/cto") and not r["path"].startswith("/super-admin")],
    "HR_ANALYTICS_AI_INSIGHTS": [r for r in deduped_routes if any(t in r["tags"] for t in ["HR Analytics Engine v2", "AI Insights", "AI Analytics Center", "AI Analytics Engine", "Recruitment Analytics & Alerts", "Recruitment Analytics v2", "AI Performance Coach", "AI Attendance Monitor", "AI Leave Assistant", "AI Payroll Insights", "AI Workforce Planning", "AI Compliance Monitor"]) and not r["path"].startswith("/super-admin")],
    "EMPLOYEE_DEPT_HIERARCHY": [r for r in deduped_routes if any(t in r["tags"] for t in ["Employee Management", "Department Management", "Manager Management", "Employee Hierarchy", "Admin Employee Onboarding"])],
    "ATTENDANCE_LEAVES_TIMESHEETS": [r for r in deduped_routes if any(t in r["tags"] for t in ["Face Attendance", "Leave Management", "Timesheet Management"])],
    "PAYROLL_COMPLIANCE": [r for r in deduped_routes if ("payroll" in r["path"] or "Tax Management" in r["tags"]) and ("dashboard" in r["path"] or "summary" in r["path"] or "runs" in r["path"] or "stats" in r["path"] or "overview" in r["path"])],
    "RECRUITMENT_ATS": [r for r in deduped_routes if any(t in r["tags"] for t in ["Applicant Tracking System (ATS) Pipeline", "Application Management", "Candidate Management", "Job Management", "Interview Management", "Offer Management", "Recruitment Management", "Recruitment Alternate Routing"]) and ("dashboard" in r["path"] or "stats" in r["path"] or r["path"].endswith("/jobs") or r["path"].endswith("/applications") or r["path"].endswith("/candidates") or r["path"].endswith("/interviews") or r["path"].endswith("/offers"))],
    "ENGAGEMENT_ANNOUNCEMENTS_EVENTS_HELPDESK": [r for r in deduped_routes if any(t in r["tags"] for t in ["Announcements Management", "Company Events Management", "Company News Management", "Polls Management", "Calendar Management", "OFC360 Helpdesk & Support", "Asset Management", "Document Management"]) and ("dashboard" in r["path"] or "stats" in r["path"] or "summary" in r["path"] or r["path"].endswith("/announcements") or r["path"].endswith("/events") or r["path"].endswith("/news") or r["path"].endswith("/polls") or r["path"].endswith("/tickets") or r["path"].endswith("/assets") or r["path"].endswith("/documents"))]
}

with open("categorized_hr_endpoints.json", "w", encoding="utf-8") as f:
    json.dump(categories, f, indent=2)

for cat_name, cat_list in categories.items():
    print(f"\n==================== {cat_name} ({len(cat_list)} endpoints) ====================")
    for ep in cat_list:
        print(f"[{ep['method']}] {ep['path']} -> {ep['summary']} | Tags: {ep['tags']}")
