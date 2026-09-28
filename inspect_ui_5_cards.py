import json

with open("all_live_fastapi_routes.json", "r", encoding="utf-8") as f:
    routes = json.load(f)

# Deduplicate
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
                "name": r.get("name", ""),
                "tags": r.get("tags", []),
                "summary": r.get("summary", "")
            })

# 1. Workforce Analytics
workforce_routes = [
    r for r in deduped if any(t in r["tags"] for t in [
        "AI Workforce Planning", "AI Workforce Forecasting v2", "HR Analytics Engine v2",
        "AI Analytics Center"
    ]) or any(k in r["path"] for k in ["/workforce", "/headcount", "/compensation", "/retention"])
]

# 2. Performance Analytics
performance_routes = [
    r for r in deduped if any(t in r["tags"] for t in [
        "AI Performance Coach", "AI Performance Management v2"
    ]) or "/performance" in r["path"]
]

# 3. Goals & OKR Analytics
goals_routes = [
    r for r in deduped if any(t in r["tags"] for t in [
        "AI Goal Generator v2"
    ]) or any(k in r["path"] for k in ["/goals", "/okr"])
]

# 4. Attendance Analytics
attendance_analytics_routes = [
    r for r in deduped if any(t in r["tags"] for t in [
        "Face Attendance", "AI Attendance Monitor"
    ]) and any(k in r["path"] for k in ["/analytics", "/trend", "/late-arrivals", "/shift-violations", "/dashboard", "/anomalies", "/health-score", "/watchlist", "/absence-pattern"])
]

# 5. Reports & Exports
reports_exports_routes = [
    r for r in deduped if any(t in r["tags"] for t in [
        "Exports", "Reports Management", "Reports Management v1"
    ]) or "/exports" in r["path"] or "/reports" in r["path"]
]

sections_data = {
    "1. Workforce Analytics": workforce_routes,
    "2. Performance Analytics": performance_routes,
    "3. Goals & OKR Analytics": goals_routes,
    "4. Attendance Analytics": attendance_analytics_routes,
    "5. Reports & Exports": reports_exports_routes
}

for title, r_list in sections_data.items():
    print(f"=== {title} ({len(r_list)} endpoints) ===")
    for r in r_list:
        print(f"[{r['method']:<6}] {r['path']:<55} | {r['summary']}")
    print()

with open("ui_5_sections_endpoints.json", "w", encoding="utf-8") as f:
    json.dump(sections_data, f, indent=2)
