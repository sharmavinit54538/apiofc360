import json

with open("all_live_fastapi_routes.json", "r", encoding="utf-8") as f:
    routes = json.load(f)

attendance_routes = []
seen = set()
for r in routes:
    p = r["path"]
    tags = r["tags"]
    methods = [m for m in r["methods"] if m not in ("HEAD", "OPTIONS")]
    if not methods:
        continue
    # Check if attendance is in path or tags
    if "attendance" in p.lower() or any("attendance" in t.lower() for t in tags):
        for m in methods:
            key = (m, p)
            if key not in seen:
                seen.add(key)
                attendance_routes.append({
                    "method": m,
                    "path": p,
                    "name": r.get("name"),
                    "tags": tags,
                    "summary": r.get("summary")
                })

print(f"Total attendance routes: {len(attendance_routes)}")
for r in attendance_routes:
    print(f"[{r['method']}] {r['path']} ({r['tags']}) - {r['summary']}")

with open("attendance_routes.json", "w", encoding="utf-8") as f:
    json.dump(attendance_routes, f, indent=2)
