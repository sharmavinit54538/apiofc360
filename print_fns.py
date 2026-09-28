import json

with open("connect_endpoints_detailed.json", "r", encoding="utf-8") as f:
    eps = json.load(f)

for idx, e in enumerate(eps, 1):
    print(f"{idx:2d}. {e['function']:<35} -> {e['method']:<6} {e['path']}")
