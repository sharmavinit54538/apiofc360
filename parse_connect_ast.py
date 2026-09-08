import ast
import json

with open("app/api/connect.py", "r", encoding="utf-8") as f:
    code = f.read()

tree = ast.parse(code)

endpoints = []

for node in tree.body:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        for dec in node.decorator_list:
            # Check for router decorator
            if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.func.value.id == "router":
                method = dec.func.attr.upper()
                path = ""
                summary = ""
                if dec.args:
                    if isinstance(dec.args[0], ast.Constant):
                        path = dec.args[0].value
                for kw in dec.keywords:
                    if kw.arg == "summary":
                        if isinstance(kw.value, ast.Constant):
                            summary = kw.value.value
                
                # Full path with prefix /api/v1/connect
                full_path = "/api/v1/connect" + (path if path.startswith("/") else ("/" + path if path else ""))
                
                # Docstring
                doc = ast.get_docstring(node) or ""
                first_doc = doc.split("\n")[0].strip() if doc else ""
                
                # Parameters
                params = []
                for arg in node.args.args:
                    params.append(arg.arg)
                
                endpoints.append({
                    "method": method,
                    "path": full_path,
                    "function": node.name,
                    "summary": summary or first_doc,
                    "doc": first_doc,
                    "params": params
                })

print(f"Parsed {len(endpoints)} endpoints from connect.py")
for idx, ep in enumerate(endpoints, 1):
    print(f"{idx:2d}. [{ep['method']:<9}] {ep['path']:<55} | {ep['summary']}")

with open("connect_endpoints_detailed.json", "w", encoding="utf-8") as f:
    json.dump(endpoints, f, indent=2)
