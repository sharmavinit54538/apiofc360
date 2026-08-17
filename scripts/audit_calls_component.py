bundle_path = r'C:\Users\Dell\.gemini\antigravity-ide\brain\d88cd3a4-9c40-4efb-b182-1ba3453358a2\.system_generated\steps\60\content.md'
with open(bundle_path, 'r', encoding='utf-8', errors='ignore') as f:
    content = f.read()

# Let's find the Calls page component (vUe)
idx = content.find('path:"/connect/calls",element:')
if idx != -1:
    print("=== Route /connect/calls element ===")
    print(content[idx:idx+300])

# Let's find definition of vUe or the calls component
idx2 = content.find('variant:"calls",title:"No call history"')
if idx2 != -1:
    print("\n=== Calls Component Definition ===")
    print(content[max(0, idx2-1500):min(len(content), idx2+2500)])
