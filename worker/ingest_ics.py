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
        count = 0
        skipped = 0
        seen_uids = set()
        
        for ev in cal.walk("VEVENT"):
            uid = str(ev.get("UID", "")).strip()
            if not uid:
                skipped += 1
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
            
            try:
                cur.execute(
                    """
                    INSERT INTO raw_events (user_id, source_uid, start_utc, end_utc, summary, description, last_modified, raw_hash)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (user_id, source_uid)
                    DO UPDATE SET
                      start_utc = EXCLUDED.start_utc,
                      end_utc = EXCLUDED.end_utc,
                      summary = EXCLUDED.summary,
                      description = EXCLUDED.description,
                      last_modified = EXCLUDED.last_modified,
                      raw_hash = EXCLUDED.raw_hash,
                      processed_flag = FALSE
                    """,
                    (USER_ID, uid, start_utc, end_utc, summary, description, last_modified, raw_hash),
                )
                count += 1
            except Exception as e:
                logger.error(f"Failed to insert event {uid}: {e}")
                skipped += 1
        
        # Reconcile removals from source calendar:
        # if a UID no longer exists in the latest ICS feed, remove it locally too.
        cur.execute(
            "SELECT source_uid FROM raw_events WHERE user_id = %s",
            (USER_ID,),
        )
        existing_uids = {row[0] for row in cur.fetchall()}
        removed_uids = list(existing_uids - seen_uids)
        
        if removed_uids:
            synthetic_uids = [f"{uid}-checkout-synthetic" for uid in removed_uids]
            
            # Remove normalized/synthetic events that originated from removed source UIDs.
            cur.execute(
                """
                DELETE FROM processed_events
                WHERE user_id = %s
                  AND (source_uid = ANY(%s) OR source_uid = ANY(%s))
                """,
                (USER_ID, removed_uids, synthetic_uids),
            )
            
            # Remove stale raw events so they are not reintroduced.
            cur.execute(
                "DELETE FROM raw_events WHERE user_id = %s AND source_uid = ANY(%s)",
                (USER_ID, removed_uids),
            )
        
        conn.commit()
        cur.close()
        conn.close()
        
        logger.info(
            f"Ingestion complete: {count} events ingested/updated, "
            f"{skipped} skipped, {len(removed_uids)} removed-from-source"
        )
        return count
        
    except Exception as e:
        logger.error(f"Ingestion failed: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    main()
