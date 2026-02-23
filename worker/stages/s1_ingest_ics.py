import os
import hashlib
import urllib.request
import urllib.error
import logging
import time

from icalendar import Calendar

from utils.db_utils import get_connection
from utils.timezone_utils import to_utc
from utils.logging_utils import setup_logging
import init_lookup_tables

logger = setup_logging(__name__)

USER_ID = os.getenv("USER_ID", "roque")
SOURCE_ICS_URL = os.getenv("SOURCE_ICS_URL")  # required
FETCH_TIMEOUT_SECONDS = int(os.getenv("FETCH_TIMEOUT_SECONDS", "30"))
FETCH_RETRIES = int(os.getenv("FETCH_RETRIES", "5"))
FETCH_BACKOFF_SECONDS = float(os.getenv("FETCH_BACKOFF_SECONDS", "3"))


def fetch_ics(url: str) -> bytes:
    """Fetch ICS file from URL with retries and backoff."""
    # Convert webcal:// to https://
    if url.startswith("webcal://"):
        url = url.replace("webcal://", "https://", 1)
    
    logger.info(f"Fetching ICS from {url}")
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123 Safari/537.36"
        ),
        "Accept": "text/calendar, text/plain, */*;q=0.8",
        "Cache-Control": "no-cache",
    }

    last_error = None
    for attempt in range(1, FETCH_RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_SECONDS) as r:
                content = r.read()
            logger.info(f"Successfully fetched {len(content)} bytes")
            return content
        except Exception as e:
            last_error = e
            is_http_error = isinstance(e, urllib.error.HTTPError)
            status = f"HTTP {e.code}" if is_http_error else type(e).__name__
            logger.warning(
                f"Fetch attempt {attempt}/{FETCH_RETRIES} failed ({status}): {e}"
            )
            if attempt < FETCH_RETRIES:
                sleep_seconds = FETCH_BACKOFF_SECONDS * (2 ** (attempt - 1))
                time.sleep(sleep_seconds)

    logger.error(f"Failed to fetch ICS after {FETCH_RETRIES} attempts: {last_error}")
    raise last_error


def main():
    """Main ingestion function."""
    logger.info(f"Starting ICS ingestion for user_id={USER_ID}")
    
    if not SOURCE_ICS_URL:
        logger.warning("SOURCE_ICS_URL not set, skipping ingestion")
        return 0
    
    try:
        # Get database connection (initializes schema if needed)
        conn = get_connection()
        
        # Initialize lookup tables (safe to run multiple times)
        try:
            init_lookup_tables.main()
        except Exception as e:
            logger.warning(f"Lookup table initialization failed or already initialized: {e}")
        
        # Fetch and parse ICS
        ics_bytes = fetch_ics(SOURCE_ICS_URL)
        cal = Calendar.from_ical(ics_bytes)
        
        cur = conn.cursor()
        events_to_insert = []
        skipped = 0
        duplicate_uid_in_feed = 0
        duplicate_content_in_feed = 0
        seen_uids = set()
        seen_event_fingerprints = set()
        
        for ev in cal.walk("VEVENT"):
            uid = str(ev.get("UID", "")).strip()
            if not uid:
                skipped += 1
                continue
            if uid in seen_uids:
                duplicate_uid_in_feed += 1
                logger.warning(f"Skipping duplicate UID in same ICS payload: {uid}")
                continue
            seen_uids.add(uid)
            
            dtstart = ev.decoded("DTSTART", None)
            dtend = ev.decoded("DTEND", None)
            if not dtstart or not dtend:
                skipped += 1
                continue
            
            try:
                start_utc = to_utc(dtstart).replace(tzinfo=None)
                end_utc = to_utc(dtend).replace(tzinfo=None)
            except Exception as e:
                logger.warning(f"Failed to convert timezone for event {uid}: {e}")
                skipped += 1
                continue
            
            summary = str(ev.get("SUMMARY", "")).strip()
            description = str(ev.get("DESCRIPTION", "")).strip()

            # Some sources emit duplicate rows with different UIDs.
            # Keep only one canonical row per normalized content/time tuple.
            event_fingerprint = (
                start_utc,
                end_utc,
                " ".join(summary.split()).casefold(),
                " ".join(description.split()).casefold(),
            )
            if event_fingerprint in seen_event_fingerprints:
                duplicate_content_in_feed += 1
                logger.warning(
                    "Skipping duplicate event content in same ICS payload: "
                    f"uid={uid} summary={summary!r} start={start_utc} end={end_utc}"
                )
                continue
            seen_event_fingerprints.add(event_fingerprint)
            
            last_modified = ev.decoded("LAST-MODIFIED", None)
            if last_modified:
                try:
                    last_modified = to_utc(last_modified).replace(tzinfo=None)
                except:
                    last_modified = None
            
            raw_hash = hashlib.sha256(
                f"{uid}|{start_utc}|{end_utc}|{summary}|{description}".encode("utf-8")
            ).hexdigest()
            
            events_to_insert.append(
                (USER_ID, uid, start_utc, end_utc, summary, description, last_modified, raw_hash)
            )

        # Full rebuild mode for deterministic output:
        # 1) remove all current processed/raw state for the user
        # 2) insert only rows from the latest source payload
        cur.execute("DELETE FROM processed_events WHERE user_id = %s", (USER_ID,))
        cleared_processed = cur.rowcount

        cur.execute("DELETE FROM raw_events WHERE user_id = %s", (USER_ID,))
        cleared_raw = cur.rowcount

        cur.executemany(
            """
            INSERT INTO raw_events (
                user_id, source_uid, start_utc, end_utc, summary, description, last_modified, raw_hash, processed_flag
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, FALSE)
            """,
            events_to_insert,
        )
        count = len(events_to_insert)
        
        conn.commit()
        cur.close()
        conn.close()
        
        logger.info(
            f"Ingestion complete: {count} events ingested, "
            f"{skipped} skipped, {duplicate_uid_in_feed} duplicate-uids-skipped, "
            f"{duplicate_content_in_feed} duplicate-content-skipped, "
            f"{cleared_raw} raw cleared, {cleared_processed} processed cleared"
        )
        return count
        
    except Exception as e:
        logger.error(f"Ingestion failed: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    main()
