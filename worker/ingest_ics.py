import os
import hashlib
import urllib.request
from datetime import datetime, timezone

import psycopg2
from icalendar import Calendar
from zoneinfo import ZoneInfo

DB_HOST = os.getenv("DB_HOST", "postgres")
DB_NAME = os.getenv("DB_NAME", "calendardb")
DB_USER = os.getenv("DB_USER", "calendar")
DB_PASSWORD = os.getenv("DB_PASSWORD", "calendarpass")

USER_ID = os.getenv("USER_ID", "roque")
SOURCE_ICS_URL = os.getenv("SOURCE_ICS_URL")  # required
SOURCE_TZ = os.getenv("SOURCE_TZ", "America/Sao_Paulo")

def fetch_ics(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=30) as r:
        return r.read()

def to_utc(dt):
    """
    Convert icalendar decoded DTSTART/DTEND to aware UTC datetime.
    - If dt is date: interpret as midnight in SOURCE_TZ.
    - If dt is naive datetime (floating): interpret as SOURCE_TZ.
    - If dt is aware: respect its timezone.
    """
    src = ZoneInfo(SOURCE_TZ)

    # date object (all-day) -> midnight in SOURCE_TZ
    if hasattr(dt, "year") and not hasattr(dt, "hour"):
        local_dt = datetime(dt.year, dt.month, dt.day, 0, 0, 0, tzinfo=src)
        return local_dt.astimezone(timezone.utc)

    # naive datetime -> assume SOURCE_TZ (this is the key fix)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=src)

    return dt.astimezone(timezone.utc)

def main():
    if not SOURCE_ICS_URL:
        raise SystemExit("SOURCE_ICS_URL is not set")

    ics_bytes = fetch_ics(SOURCE_ICS_URL)
    cal = Calendar.from_ical(ics_bytes)

    conn = psycopg2.connect(host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD)
    cur = conn.cursor()

    count = 0
    for ev in cal.walk("VEVENT"):
        uid = str(ev.get("UID", "")).strip()
        if not uid:
            continue

        dtstart = ev.decoded("DTSTART", None)
        dtend = ev.decoded("DTEND", None)
        if not dtstart or not dtend:
            continue

        start_utc = to_utc(dtstart).replace(tzinfo=None)
        end_utc = to_utc(dtend).replace(tzinfo=None)

        summary = str(ev.get("SUMMARY", "")).strip()
        description = str(ev.get("DESCRIPTION", "")).strip()

        last_modified = ev.decoded("LAST-MODIFIED", None)
        if last_modified:
            last_modified = to_utc(last_modified).replace(tzinfo=None)

        raw_hash = hashlib.sha256(
            f"{uid}|{start_utc}|{end_utc}|{summary}|{description}".encode("utf-8")
        ).hexdigest()

        cur.execute(
            """
            INSERT INTO raw_events (user_id, source_uid, start_utc, end_utc, summary, description, last_modified, raw_hash)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (user_id, source_uid)
            DO UPDATE SET
              start_utc = EXCLUDED.start_utc,
              end_utc = EXCLUDED.end_utc,
              summary = EXCLUDED.summary,
              description = EXCLUDED.description,
              last_modified = EXCLUDED.last_modified,
              raw_hash = EXCLUDED.raw_hash
            """,
            (USER_ID, uid, start_utc, end_utc, summary, description, last_modified, raw_hash),
        )
        count += 1

    conn.commit()
    cur.close(); conn.close()
    print(f"Ingested/updated {count} events for user_id={USER_ID}")

if __name__ == "__main__":
    main()
