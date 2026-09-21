import os
import sys

# Set dummy env vars so settings doesn't fail
os.environ["ENVIRONMENT"] = "development"

from app.main import create_app

app = create_app()

routes_info = []
for r in app.routes:
    path = getattr(r, "path", None)
    methods = list(getattr(r, "methods", []))
    name = getattr(r, "name", "")
    tags = getattr(r, "tags", [])
    summary = getattr(r, "summary", "")
    endpoint_func = getattr(r, "endpoint", None)
    doc = endpoint_func.__doc__ if endpoint_func else ""
    
    # Filter out HEAD/OPTIONS if only GET
    clean_methods = [m for m in methods if m not in ("HEAD", "OPTIONS")]
    if not clean_methods and methods:
        clean_methods = methods
        
    routes_info.append({
        "path": path,
        "methods": clean_methods,
        "name": name,
        "tags": tags,
        "summary": summary or (doc.split("\n")[0].strip() if doc else "")
    })

import json
with open("all_live_fastapi_routes.json", "w", encoding="utf-8") as f:
    json.dump(routes_info, f, indent=2)

print(f"Total live registered FastAPI routes: {len(routes_info)}")
