import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import json
from app.main import app

routes = []
for r in app.routes:
    path = getattr(r, "path", "")
    if "connect" in path or "chat" in path:
        methods = list(getattr(r, "methods", ["WS"]))
        name = getattr(r, "name", "")
        summary = getattr(r, "summary", "")
        routes.append({
            "path": path,
            "methods": methods,
            "name": name,
            "summary": summary
        })

print(json.dumps(routes, indent=2))
