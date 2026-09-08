import ast
import json

with open("app/api/connect.py", "r", encoding="utf-8") as f:
    code = f.read()

tree = ast.parse(code)

categories = [
    ("1. User Discovery & Directory", ["get_colleagues", "unified_search"]),
    ("2. Direct Messaging & Conversations", ["get_conversations", "create_conversation", "get_conversation_messages", "send_conversation_message"]),
    ("3. Message Interactions, Threads & Reactions", ["toggle_message_reaction", "pin_message", "delete_message", "get_message_thread", "post_thread_reply"]),
    ("4. Team Channels Management", ["get_channels", "create_channel", "get_channel_details", "update_channel", "delete_channel", "add_channel_members", "remove_channel_member", "leave_channel", "archive_channel"]),
    ("5. Channel Messaging", ["get_channel_messages", "send_channel_message"]),
    ("6. Audio/Video Calls & WebRTC", ["get_ice_servers", "get_call_history", "get_call_details", "initiate_call", "update_call_status", "send_call_signal"]),
    ("7. Meetings & In-Meeting Collaboration", ["get_meetings", "create_meeting", "get_meeting_details", "join_meeting", "leave_meeting", "send_meeting_message"]),
    ("8. Shared Files & Document Management", ["get_shared_files", "upload_shared_file", "delete_shared_file"]),
    ("9. Presence & Online Status", ["update_presence", "batch_presence"]),
    ("10. Notifications & Alert Center", ["get_notifications", "mark_notification_as_read", "clear_notifications"]),
    ("11. Audio/Sound Preferences", ["get_sound_settings", "update_sound_settings"]),
    ("12. AI Copilot & Mail Dispatch", ["ai_transform", "dispatch_mail"]),
    ("13. Real-Time WebSocket Gateway", ["connect_websocket"])
]

# Map functions
endpoints_map = {}
for node in tree.body:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        for dec in node.decorator_list:
            if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.func.value.id == "router":
                method = dec.func.attr.upper()
                path = ""
                summary = ""
                if dec.args and isinstance(dec.args[0], ast.Constant):
                    path = dec.args[0].value
                for kw in dec.keywords:
                    if kw.arg == "summary" and isinstance(kw.value, ast.Constant):
                        summary = kw.value.value
                full_path = "/api/v1/connect" + (path if path.startswith("/") else ("/" + path if path else ""))
                doc = ast.get_docstring(node) or ""
                endpoints_map[node.name] = {
                    "method": method,
                    "path": full_path,
                    "summary": summary or doc.split("\n")[0],
                    "doc": doc
                }

categorized = []
for cat_title, func_names in categories:
    cat_items = []
    for fn in func_names:
        if fn in endpoints_map:
            cat_items.append(endpoints_map[fn])
        else:
            print(f"Warning: {fn} not found in endpoints_map")
    categorized.append({"category": cat_title, "endpoints": cat_items})

with open("categorized_connect_endpoints.json", "w", encoding="utf-8") as f:
    json.dump(categorized, f, indent=2)

print("Categorized successfully!")
