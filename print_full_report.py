import json

with open('full_hr_admin_dashboard_report.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

for cat, items in data.items():
    print(f"==================================================")
    print(f"{cat} (Total: {len(items)})")
    print(f"==================================================")
    for r in items:
        print(f"{r['method']:<6} {r['path']:<55} | {r['summary']}")
    print()
