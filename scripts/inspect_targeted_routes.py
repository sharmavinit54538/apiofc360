import sys
import os
sys.path.insert(0, os.getcwd())

from app.main import create_app

app = create_app()
routes = []
for r in app.routes:
    methods = getattr(r, "methods", None)
    path = getattr(r, "path", None)
    if path:
        routes.append((sorted(list(methods)) if methods else ["WS/MOUNT"], path))

print(f"Total routes registered: {len(routes)}")
for m, p in sorted(routes, key=lambda x: x[1]):
    if any(k in p for k in ["attendance", "payroll", "cycles", "salary", "intelligence", "models"]):
        print(f"{m} {p}")
