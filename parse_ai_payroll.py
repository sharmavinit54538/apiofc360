import ast
import json

ai_payroll_path = "app/api/v1/ai_payroll.py"
with open(ai_payroll_path, "r", encoding="utf-8") as f:
    code = f.read()

tree = ast.parse(code)
ai_endpoints = []
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
                full_path = "/api/v1/ai/payroll" + (path if path.startswith("/") else ("/" + path if path else ""))
                doc = ast.get_docstring(node) or ""
                ai_endpoints.append({
                    "method": method,
                    "path": full_path,
                    "function": node.name,
                    "summary": summary or doc.split("\n")[0] if doc else node.name
                })

print(f"AI Payroll Endpoints: {len(ai_endpoints)}")
for ep in ai_endpoints:
    print(f"[{ep['method']:<6}] {ep['path']:<50} | {ep['summary']}")

with open("ai_payroll_endpoints.json", "w", encoding="utf-8") as f:
    json.dump(ai_endpoints, f, indent=2)
