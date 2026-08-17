import re

bundle_path = r'C:\Users\Dell\.gemini\antigravity-ide\brain\d88cd3a4-9c40-4efb-b182-1ba3453358a2\.system_generated\steps\60\content.md'
with open(bundle_path, 'r', encoding='utf-8', errors='ignore') as f:
    content = f.read()

# Find occurrences of 'calls' with surrounding 200 characters
for match in re.finditer(r'calls', content, re.IGNORECASE):
    start = max(0, match.start() - 100)
    end = min(len(content), match.end() + 150)
    print("--- CONTEXT ---")
    print(content[start:end])
    print()
