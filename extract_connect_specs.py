import ast
import json

with open("app/api/connect.py", "r", encoding="utf-8") as f:
    code = f.read()

tree = ast.parse(code)

results = []

for node in tree.body:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        for dec in node.decorator_list:
            if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.func.value.id == "router":
                method = dec.func.attr.upper()
                path = ""
                summary = ""
                description = ""
                if dec.args and isinstance(dec.args[0], ast.Constant):
                    path = dec.args[0].value
                for kw in dec.keywords:
                    if kw.arg == "summary" and isinstance(kw.value, ast.Constant):
                        summary = kw.value.value
                    if kw.arg == "description" and isinstance(kw.value, ast.Constant):
                        description = kw.value.value
                
                full_path = "/api/v1/connect" + (path if path.startswith("/") else ("/" + path if path else ""))
                
                # Check parameters and type annotations
                params_info = []
                body_type = None
                for arg in node.args.args:
                    arg_name = arg.arg
                    # Skip common internal dependencies
                    if arg_name in ("db", "claims", "user", "request", "session", "background_tasks", "x_company_id", "auth_header"):
                        continue
                    params_info.append(arg_name)
                
                results.append({
                    "function": node.name,
                    "method": method,
                    "path": full_path,
                    "summary": summary or node.name,
                    "description": description or ast.get_docstring(node) or "",
                    "params": params_info
                })

with open("connect_full_specs.json", "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2)

print(f"Extracted {len(results)} endpoint specs.")
