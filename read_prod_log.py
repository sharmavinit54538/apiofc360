"""Read and display task-1097.log with UTF-8 support."""
import os
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

def run():
    path = r"C:\Users\Dell\.gemini\antigravity-ide\brain\4f88d168-1786-4510-a235-7eb91f3aa4da\.system_generated\tasks\task-1097.log"
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            print(f.read())
    else:
        print("Log file not found at path:", path)

if __name__ == "__main__":
    run()
