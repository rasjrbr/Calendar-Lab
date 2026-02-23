import os
import time
import subprocess

INTERVAL_SECONDS = int(os.getenv("INTERVAL_SECONDS", "20"))
INGEST_INTERVAL_SECONDS = int(os.getenv("INGEST_INTERVAL_SECONDS", "600"))

# Pipeline stages in execution order.
INGEST_STAGE = "stages/s1_ingest_ics.py"

TRANSFORM_STAGES = [
    "stages/s2_init_parsing.py",
    "stages/s3_checkout_creator.py",
    "stages/s4_dayoff_parsing.py",
    "stages/s5_dtl_singlecrew.py",
    "stages/s6_dtl_hsb_rulecheck.py",
    "stages/s7_publish_ics.py",
]


def main():
    next_ingest_at = 0.0

    while True:
        now = time.time()

        if os.getenv("SOURCE_ICS_URL") and now >= next_ingest_at:
            try:
                subprocess.check_call(["python3", f"/app/{INGEST_STAGE}"])
            except Exception as e:
                print(f"Ingest error (continuing with last good raw data): {e}")
            finally:
                next_ingest_at = now + INGEST_INTERVAL_SECONDS

        try:
            for stage in TRANSFORM_STAGES:
                subprocess.check_call(["python3", f"/app/{stage}"])
        except Exception as e:
            print(f"Transform/publish loop error: {e}")
        time.sleep(INTERVAL_SECONDS)

if __name__ == "__main__":
    main()
