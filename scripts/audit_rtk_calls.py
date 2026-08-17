bundle_path = r'C:\Users\Dell\.gemini\antigravity-ide\brain\d88cd3a4-9c40-4efb-b182-1ba3453358a2\.system_generated\steps\60\content.md'
with open(bundle_path, 'r', encoding='utf-8', errors='ignore') as f:
    content = f.read()

# Let's find RTK query endpoints for connect / calls
idx = content.find("sendCallSignal")
if idx != -1:
    print("=== RTK Query around sendCallSignal ===")
    print(content[max(0, idx-500):min(len(content), idx+1500)])

idx2 = content.find("Qfe=")
if idx2 == -1:
    # search function Qfe
    idx2 = content.find("useGetCallHistoryQuery")
    if idx2 == -1:
        import re
        m = re.search(r'getCallHistory', content)
        if m:
            print("\n=== getCallHistory ===")
            print(content[max(0, m.start()-500):min(len(content), m.end()+1500)])
else:
    print("Qfe found at", idx2)
