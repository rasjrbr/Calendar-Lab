import os
import time
import psycopg2
from icalendar import Calendar, Event
from pathlib import Path
from datetime import timezone

DB_HOST = os.getenv("DB_HOST", "postgres")
DB_NAME = os.getenv("DB_NAME", "calendardb")
DB_USER = os.getenv("DB_USER", "calendar")
DB_PASSWORD = os.getenv("DB_PASSWORD", "calendarpass")

USER_ID = os.getenv("USER_ID", "roque")
OUT_DIR = os.getenv("OUT_DIR", "/var/www/calendars")

def connect_with_retry():
    last_err = None
    for _ in range(60):  # wait up to ~60s
        try:
            return psycopg2.connect(
                host=DB_HOST,
                dbname=DB_NAME,
                user=DB_USER,
                password=DB_PASSWORD
            )
        except psycopg2.OperationalError as e:
            last_err = e
            msg = str(e).lower()
            # typical “not ready yet” cases
            if "starting up" in msg or "could not connect" in msg or "connection refused" in msg:
                time.sleep(1)
                continue
            raise
    raise last_err

def main():
    conn = connect_with_retry()
    cur = conn.cursor()

    cur.execute("""
    SELECT source_uid, start_utc, end_utc, summary, description
    FROM raw_events
    WHERE user_id = %s
    ORDER BY start_utc
    """, (USER_ID,))
    rows = cur.fetchall()

    cal = Calendar()
    cal.add("prodid", "-//Calendar Lab//Parsed Calendar//EN")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")

    for source_uid, start_utc, end_utc, summary, description in rows:
        ev = Event()
        ev.add("dtstart", start_utc.replace(tzinfo=timezone.utc))
        ev.add("dtend", end_utc.replace(tzinfo=timezone.utc))
        ev.add("uid", str(source_uid))
        ev.add("summary", summary or "")
        ev.add("description", description or "")
        cal.add_component(ev)

    out_dir = Path(OUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{USER_ID}.ics"
    out_path.write_bytes(cal.to_ical())

    cur.close()
    conn.close()

    print(f"Wrote {out_path} with {len(rows)} events")

if __name__ == "__main__":
    main()
