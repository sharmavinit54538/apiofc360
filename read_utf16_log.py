"""Read UTF-16LE redirected logs and print in UTF-8."""
import os
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

def run():
    path = "test_production_assistant_2.log"
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-16") as f:
                print(f.read())
        except Exception as e:
            # Fallback to utf-8 if encoding wasn't utf-16
            try:
                with open(path, "r", encoding="utf-8") as f:
                    print(f.read())
            except Exception as e2:
                print(f"Error reading file: {e} | {e2}")
    else:
        print("File not found:", path)

if __name__ == "__main__":
    run()
