"""Record source structure without loading configuration or connecting to services."""
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
records = []
for directory in ("app", "alembic", "tests", "scripts"):
    for path in sorted((ROOT / directory).rglob("*.py")):
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source)
        records.append({"path": path.relative_to(ROOT).as_posix(), "lines": len(source.splitlines()),
                        "definitions": [{"name": node.name, "line": node.lineno}
                                        for node in ast.walk(tree)
                                        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))]})
output = ROOT / "verification" / "backend-20261118"
output.mkdir(exist_ok=True)
(output / "source-inventory.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
print(f"Parsed {len(records)} Python source files; inventory saved.")
