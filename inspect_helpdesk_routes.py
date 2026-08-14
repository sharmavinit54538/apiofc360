"""Inspect and verify all registered Helpdesk routes in FastAPI application."""

from app.main import app

def main():
    hd_routes = []
    for r in app.routes:
        path = getattr(r, "path", "")
        if path.startswith("/api/v1/helpdesk"):
            methods = list(getattr(r, "methods", []))
            hd_routes.append((methods, path, getattr(r, "name", "")))

    print(f"Total Helpdesk Routes Found: {len(hd_routes)}")
    for methods, path, name in sorted(hd_routes, key=lambda x: (x[1], x[0])):
        print(f"{','.join(methods):<15} {path} ({name})")

if __name__ == "__main__":
    main()
