import os
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

def run():
    log_path = os.getenv("LOG_FILE_PATH", "")
    if log_path and os.path.exists(log_path):
        with open(log_path, "r", encoding="utf-8") as f:
            print(f.read())
    else:
        print("Log file path not provided or file not found.")

if __name__ == "__main__":
    run()
