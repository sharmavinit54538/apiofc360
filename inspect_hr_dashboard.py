import json
import re

with open("parsed_endpoints.json", "r", encoding="utf-8") as f:
    endpoints = json.load(f)

# Find all endpoints with 'hr-admin', 'dashboard', 'analytics', 'summary', 'stats', 'kpi', 'overview'
# and also list by all tags/prefixes
hr_admin_endpoints = []
dashboard_endpoints = []
analytics_endpoints = []

for ep in endpoints:
    p = ep["path"].lower()
    t = " ".join(ep["tags"]).lower()
    s = ep["summary"].lower()
    
    if "hr-admin" in p or "hr admin" in t or "hr_admin" in p:
        hr_admin_endpoints.append(ep)
    if "dashboard" in p or "dashboard" in s or "dashboard" in t:
        dashboard_endpoints.append(ep)
    if any(k in p or k in s or k in t for k in ["analytic", "stat", "metric", "kpi", "summary", "overview", "count", "report"]):
        analytics_endpoints.append(ep)

print("=== HR-ADMIN SPECIFIC ENDPOINTS ===")
for ep in hr_admin_endpoints:
    print(f"{ep['method']} {ep['path']} - {ep['summary']} ({ep['tags']})")

print("\n=== DASHBOARD SPECIFIC ENDPOINTS ===")
for ep in dashboard_endpoints:
    print(f"{ep['method']} {ep['path']} - {ep['summary']} ({ep['tags']})")

print(f"\nTotal HR-Admin endpoints: {len(hr_admin_endpoints)}")
print(f"Total Dashboard endpoints: {len(dashboard_endpoints)}")
print(f"Total Analytics/Stats endpoints: {len(analytics_endpoints)}")
