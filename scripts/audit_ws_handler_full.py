bundle_path = r'C:\Users\Dell\.gemini\antigravity-ide\brain\d88cd3a4-9c40-4efb-b182-1ba3453358a2\.system_generated\steps\60\content.md'
with open(bundle_path, 'r', encoding='utf-8', errors='ignore') as f:
    content = f.read()

idx = content.find('case"call:incoming":')
if idx != -1:
    print("=== Complete WS Handler around call:incoming ===")
    print(content[max(0, idx-1500):min(len(content), idx+1500)])
