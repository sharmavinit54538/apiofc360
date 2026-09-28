import re

with open("app/api/connect.py", "r", encoding="utf-8") as f:
    content = f.read()

# Let's inspect sections and endpoint definitions in connect.py
sections = content.split("# ===========================================================================")
print(f"Total sections: {len(sections)}")
for s in sections[1:]:
    lines = [line.strip() for line in s.split("\n") if line.strip()]
    if lines:
        print("SECTION:", lines[0])
