"""Inspect and verify all Connect routes in FastAPI application."""

from app.main import app

def main():
    connect_routes = []
    for r in app.routes:
        path = getattr(r, "path", "")
        if path.startswith("/api/v1/connect"):
            methods = list(getattr(r, "methods", ["WS"]))
            connect_routes.append((methods, path, getattr(r, "name", "")))

    print(f"Total Connect Routes Found: {len(connect_routes)}")
    for methods, path, name in sorted(connect_routes, key=lambda x: (x[1], x[0])):
        print(f"{','.join(methods):<15} {path}")

if __name__ == "__main__":
    main()
