bundle_path = r'C:\Users\Dell\.gemini\antigravity-ide\brain\d88cd3a4-9c40-4efb-b182-1ba3453358a2\.system_generated\steps\60\content.md'
with open(bundle_path, 'r', encoding='utf-8', errors='ignore') as f:
    content = f.read()

# Search for incoming_call handler and call_signal handler in the bundle
for term in ["incoming_call", "call_signal", "call_status_changed", "sendCallSignal", "updateCallStatus", "toggleMicrophone", "toggleCamera"]:
    pos = 0
    while True:
        idx = content.find(term, pos)
        if idx == -1:
            break
        print(f"=== Term: {term} at {idx} ===")
        print(content[max(0, idx-300):min(len(content), idx+500)])
        print()
        pos = idx + len(term) + 100
