import re

bundle_path = r'C:\Users\Dell\.gemini\antigravity-ide\brain\d88cd3a4-9c40-4efb-b182-1ba3453358a2\.system_generated\steps\60\content.md'
with open(bundle_path, 'r', encoding='utf-8', errors='ignore') as f:
    content = f.read()

print("Bundle length:", len(content))

# Look for patterns like '/connect', 'calls', 'initiate', 'signal', 'history', 'webrtc'
patterns = [
    r'\/connect\/[a-zA-Z0-9_\-\/]+',
    r'api\/v1\/connect\/[a-zA-Z0-9_\-\/]+',
    r'calls\/[a-zA-Z0-9_\-\/]+',
    r'incoming_call',
    r'call_signal',
    r'call_status_changed',
    r'call_status',
    r'RTCPeerConnection',
    r'getUserMedia',
    r'callHistory',
    r'activeCall',
]

for pat in patterns:
    matches = set(re.findall(pat, content, re.IGNORECASE))
    print(f"\nMatches for pattern '{pat}': ({len(matches)})")
    for m in list(matches)[:15]:
        print(f"  - {m}")
