"""
ActivityProcessor Module: Third stage of transformation pipeline.

Processes ACTIVITY events to:
1. Look up activity codes in lookup_ground_activities
2. If found: enrich with activity details (name, type, location)
3. If not found: queue in activity_codes_pending_validation for admin review
4. Tag events appropriately
"""

import os
import logging
import json

from utils.db_utils import get_connection
from utils.logging_utils import setup_logging
from utils.timezone_utils import now_utc

logger = setup_logging(__name__)

USER_ID = os.getenv("USER_ID", "roque")


def process_activities(conn, user_id):
    """
    Main processing function for ACTIVITY events.
    
    Returns:
        dict with statistics
    """
    logger.info(f"Starting activity_processor for user_id={user_id}")
    
    stats = {
        "found_in_db": 0,
        "queued_pending": 0,
        "already_pending": 0,
        "errors": 0
    }
    
    cur = conn.cursor()
    
    # Query all ACTIVITY events with activity_code set
    cur.execute(
        """
        SELECT id, source_uid, activity_code, notes, start_utc
        FROM processed_events
        WHERE user_id = %s AND event_type = 'ACTIVITY' AND activity_code IS NOT NULL
        """,
        (user_id,)
    )
    
    activity_rows = cur.fetchall()
    logger.info(f"Found {len(activity_rows)} ACTIVITY events with codes")
    
    for proc_id, source_uid, activity_code, notes, start_utc in activity_rows:
        try:
            # Look up in lookup_ground_activities
            cur.execute(
                "SELECT name, type, location FROM lookup_ground_activities WHERE code = %s",
                (activity_code,)
            )
            result = cur.fetchone()
            
            if result:
                # Activity code found in database
                name, act_type, location = result
                
                # Update tags
                tags = ["#roquescript-modified", "#activity-translated"]
                
                cur.execute(
                    """
                    UPDATE processed_events
                    SET
                        tags = %s,
                        processed_at = %s
                    WHERE id = %s
                    """,
                    (
                        json.dumps(tags),
                        now_utc().replace(tzinfo=None),
                        proc_id
                    )
                )
                
                stats["found_in_db"] += 1
                logger.info(f"Event {source_uid}: Activity code {activity_code} found in DB ({name})")
            
            else:
                # Activity code NOT found - queue for validation
                
                # Check if already in pending queue
                cur.execute(
                    "SELECT id FROM activity_codes_pending_validation WHERE code = %s",
                    (activity_code,)
                )
                pending_row = cur.fetchone()
                
                if pending_row:
                    # Already queued, just increment counter
                    cur.execute(
                        """
                        UPDATE activity_codes_pending_validation
                        SET
                            last_occurrence = %s,
                            occurrence_count = occurrence_count + 1
                        WHERE code = %s
                        """,
                        (start_utc, activity_code)
                    )
                    stats["already_pending"] += 1
                    logger.info(f"Event {source_uid}: Activity code {activity_code} already pending")
                
                else:
                    # Extract metadata from notes for pending queue
                    source_name = activity_code  # fallback
                    source_type = "Presencial"  # default
                    source_location = "-"  # default
                    
                    if notes:
                        lines = notes.split("\n")
                        if lines:
                            source_name = lines[0]  # first line is name/description
                        if len(lines) > 1:
                            # Try to find type
                            for line in lines:
                                if "Presencial" in line or "Online" in line:
                                    source_type = "Presencial" if "Presencial" in line else "Online"
                                    break
                        if len(lines) > 2:
                            # Try to find location
                            for line in lines:
                                if len(line) == 3 and line.isupper():
                                    source_location = line
                                    break
                    
                    # Insert into pending validation queue
                    cur.execute(
                        """
                        INSERT INTO activity_codes_pending_validation (
                            code, source_name, source_type, source_location,
                            first_occurrence, last_occurrence, occurrence_count,
                            status, created_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (code)
                        DO UPDATE SET
                            last_occurrence = EXCLUDED.last_occurrence,
                            occurrence_count = activity_codes_pending_validation.occurrence_count + 1
                        """,
                        (
                            activity_code,
                            source_name,
                            source_type,
                            source_location,
                            start_utc,
                            start_utc,
                            1,
                            "pending",
                            now_utc()
                        )
                    )
                    
                    # Update tags in processed_events
                    tags = ["#roquescript-modified", "#activity-new"]
                    cur.execute(
                        """
                        UPDATE processed_events
                        SET
                            tags = %s,
                            processed_at = %s
                        WHERE id = %s
                        """,
                        (json.dumps(tags), now_utc().replace(tzinfo=None), proc_id)
                    )
                    
                    stats["queued_pending"] += 1
                    logger.info(f"Event {source_uid}: Activity code {activity_code} queued for validation")
        
        except Exception as e:
            logger.error(f"Failed to process activity {source_uid}: {e}", exc_info=True)
            stats["errors"] += 1
    
    # Commit all changes
    conn.commit()
    
    logger.info(f"activity_processor complete: "
                f"found_in_db={stats['found_in_db']}, "
                f"queued_pending={stats['queued_pending']}, "
                f"already_pending={stats['already_pending']}, "
                f"errors={stats['errors']}")
    
    return stats


def main(user_id=None):
    """Main entry point."""
    if user_id is None:
        user_id = USER_ID
    
    try:
        conn = get_connection()
        stats = process_activities(conn, user_id)
        conn.close()
        return stats
    except Exception as e:
        logger.error(f"activity_processor failed: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    main()
