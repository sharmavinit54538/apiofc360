import json
import os

with open("openapi.json", "r", encoding="utf-8") as f:
    data = json.load(f)

paths = data.get("paths", {})
print(f"Total paths in openapi.json: {len(paths)}")

# Let's filter routes related to hr-admin, dashboard, analytics, hr, employee, attendance, payroll, recruitment, etc.
# Or list all routes by category/tag
endpoints = []
for path, methods in paths.items():
    for method, details in methods.items():
        if method.lower() not in ["get", "post", "put", "patch", "delete", "options", "head"]:
            continue
        tags = details.get("tags", [])
        summary = details.get("summary", "")
        op_id = details.get("operationId", "")
        endpoints.append({
            "method": method.upper(),
            "path": path,
            "summary": summary,
            "tags": tags,
            "operation_id": op_id
        })

print(f"Total endpoints: {len(endpoints)}")

with open("parsed_endpoints.json", "w", encoding="utf-8") as f:
    json.dump(endpoints, f, indent=2)

print("Saved to parsed_endpoints.json")
