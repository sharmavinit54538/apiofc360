bundle_path = r'C:\Users\Dell\.gemini\antigravity-ide\brain\d88cd3a4-9c40-4efb-b182-1ba3453358a2\.system_generated\steps\60\content.md'
with open(bundle_path, 'r', encoding='utf-8', errors='ignore') as f:
    content = f.read()

# Search for websocket message handling
import re
events = set(re.findall(r'event:\s*\"([a-zA-Z0-9_\-:]+)\"', content))
print("Event keys found in bundle:", events)

# Search for case statements in WS handler
idx = content.find("webrtc:signal")
if idx != -1:
    print("\n=== Around webrtc:signal ===")
    print(content[max(0, idx-500):min(len(content), idx+500)])

# Search for incoming_call in WS handler
idx2 = content.find('incoming_call')
if idx2 != -1:
    print("\n=== Around incoming_call ===")
    print(content[max(0, idx2-300):min(len(content), idx2+500)])
