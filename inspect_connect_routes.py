import json

with open("all_live_fastapi_routes.json", "r", encoding="utf-8") as f:
    routes = json.load(f)

connect_routes = []
seen = set()

for r in routes:
    p = r["path"]
    tags = r["tags"]
    methods = [m for m in r["methods"] if m not in ("HEAD", "OPTIONS")]
    if not methods:
        continue
    if "/connect" in p or "OFC360 Connect" in tags:
        for m in methods:
            key = (m, p)
            if key not in seen:
                seen.add(key)
                connect_routes.append({
                    "method": m,
                    "path": p,
                    "name": r.get("name"),
                    "tags": tags,
                    "summary": r.get("summary")
                })

print(f"Total Connect Routes: {len(connect_routes)}")
for idx, r in enumerate(connect_routes, 1):
    print(f"{idx:2d}. [{r['method']:<6}] {r['path']:<55} | {r['summary']}")

with open("connect_routes.json", "w", encoding="utf-8") as f:
    json.dump(connect_routes, f, indent=2)
