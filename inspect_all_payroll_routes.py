import json

with open("all_live_fastapi_routes.json", "r", encoding="utf-8") as f:
    routes = json.load(f)

payroll_routes = []
seen = set()

for r in routes:
    p = r["path"]
    tags = r["tags"]
    methods = [m for m in r["methods"] if m not in ("HEAD", "OPTIONS")]
    if not methods:
        continue
    
    # Check if route belongs to payroll
    if "payroll" in p.lower() or "tax" in p.lower() or any(t in ["Payroll", "Enterprise Payroll Security", "Tax Management", "AI Payroll Insights"] for t in tags):
        for m in methods:
            # Let's normalize paths (ignore duplicate prefix aliases if identical endpoint function)
            key = (m, p)
            if key not in seen:
                seen.add(key)
                payroll_routes.append({
                    "method": m,
                    "path": p,
                    "name": r.get("name"),
                    "tags": tags,
                    "summary": r.get("summary")
                })

print(f"Total Payroll unique method+path routes: {len(payroll_routes)}")

# Filter primary routes (e.g. prioritize /api/v1 or /api/v2 or standard path)
with open("payroll_all_routes.json", "w", encoding="utf-8") as f:
    json.dump(payroll_routes, f, indent=2)

# Let's inspect unique paths
unique_paths = sorted(list({r["path"] for r in payroll_routes}))
print(f"Total unique payroll paths: {len(unique_paths)}")
