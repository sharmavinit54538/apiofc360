import os
import ast
import json

routes_dir = "app/api/payroll/routes"
files = [f for f in os.listdir(routes_dir) if f.endswith(".py") and f != "__init__.py"]

all_submodules = {}

for filename in sorted(files):
    filepath = os.path.join(routes_dir, filename)
    with open(filepath, "r", encoding="utf-8") as f:
        code = f.read()
    
    tree = ast.parse(code)
    endpoints = []
    
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in node.decorator_list:
                if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and getattr(dec.func.value, "id", "") == "router":
                    method = dec.func.attr.upper()
                    path = ""
                    summary = ""
                    if dec.args and isinstance(dec.args[0], ast.Constant):
                        path = dec.args[0].value
                    for kw in dec.keywords:
                        if kw.arg == "summary" and isinstance(kw.value, ast.Constant):
                            summary = kw.value.value
                    
                    full_path = "/api/v1/payroll" + (path if path.startswith("/") else ("/" + path if path else ""))
                    doc = ast.get_docstring(node) or ""
                    
                    params = []
                    for arg in node.args.args:
                        arg_name = arg.arg
                        if arg_name not in ("db", "claims", "user", "request", "session", "background_tasks", "x_company_id", "current_user"):
                            params.append(arg_name)
                    
                    endpoints.append({
                        "method": method,
                        "path": full_path,
                        "relative_path": path,
                        "function": node.name,
                        "summary": summary or doc.split("\n")[0] if doc else node.name,
                        "params": params
                    })
    
    all_submodules[filename.replace(".py", "")] = endpoints

print("=== PAYROLL SUBMODULES SUMMARY ===")
total_eps = 0
for mod, eps in all_submodules.items():
    print(f"- {mod}: {len(eps)} endpoints")
    total_eps += len(eps)

print(f"\nTotal endpoints in app/api/payroll/routes: {total_eps}")

with open("payroll_submodules_parsed.json", "w", encoding="utf-8") as f:
    json.dump(all_submodules, f, indent=2)
