import os
import hashlib
import urllib.request
import logging

from icalendar import Calendar

from utils.db_utils import get_connection
from utils.timezone_utils import to_utc
from utils.logging_utils import setup_logging
import init_lookup_tables

logger = setup_logging(__name__)

USER_ID = os.getenv("USER_ID", "roque")
SOURCE_ICS_URL = os.getenv("SOURCE_ICS_URL")  # required


def fetch_ics(url: str) -> bytes:
    """Fetch ICS file from URL with timeout."""
    # Convert webcal:// to https://
    if url.startswith("webcal://"):
        url = url.replace("webcal://", "https://", 1)
    
    logger.info(f"Fetching ICS from {url}")
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            content = r.read()
        logger.info(f"Successfully fetched {len(content)} bytes")
        return content
    except Exception as e:
        logger.error(f"Failed to fetch ICS: {e}")
        raise


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
        seen_uids = set()
        
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
            f"{cleared_raw} raw cleared, {cleared_processed} processed cleared"
        )
        return count
        
    except Exception as e:
        logger.error(f"Ingestion failed: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    main()
