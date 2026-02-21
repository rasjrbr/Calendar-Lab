import os
import time
import subprocess

INTERVAL_SECONDS = int(os.getenv("INTERVAL_SECONDS", "20"))


def main():
    while True:
        try:
            if os.getenv("SOURCE_ICS_URL"):
                subprocess.check_call(["python3", "/app/ingest_ics.py"])
            subprocess.check_call(["python3", "/app/init_parsing.py"])
            subprocess.check_call(["python3", "/app/checkout_creator.py"])
            subprocess.check_call(["python3", "/app/dayoff_parsing.py"])
            subprocess.check_call(["python3", "/app/dtl-singlecrew.py"])
            subprocess.check_call(["python3", "/app/publish_ics.py"])
        except Exception as e:
            print(f"Loop error: {e}")
        time.sleep(INTERVAL_SECONDS)

if __name__ == "__main__":
    main()
