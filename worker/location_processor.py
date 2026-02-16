"""
LocationProcessor Module: Fourth stage of transformation pipeline.

Processes RESERVA events (ASB) to:
1. Look up location_code in lookup_homebases
2. If found: populate location_details with full airport information  
3. If not found: queue in homebases_pending_validation for admin review
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


def process_locations(conn, user_id):
    """
    Main processing function for RESERVA events.
    
    Returns:
        dict with statistics
    """
    logger.info(f"Starting location_processor for user_id={user_id}")
    
    stats = {
        "found_in_db": 0,
        "queued_pending": 0,
        "already_pending": 0,
        "missing_location": 0,
        "invalid_format": 0,
        "errors": 0
    }
    
    cur = conn.cursor()
    
    # Query all RESERVA events
    cur.execute(
        """
        SELECT id, source_uid, location_code, clean_title, start_utc
        FROM processed_events
        WHERE user_id = %s AND event_type = 'RESERVA'
        """,
        (user_id,)
    )
    
    reserva_rows = cur.fetchall()
    logger.info(f"Found {len(reserva_rows)} RESERVA events")
    
    for proc_id, source_uid, location_code, clean_title, start_utc in reserva_rows:
        try:
            # No location code found in title
            if not location_code:
                tags = ["#roquescript-modified", "#location-missing"]
                cur.execute(
                    """
                    UPDATE processed_events
                    SET tags = %s, processed_at = %s
                    WHERE id = %s
                    """,
                    (json.dumps(tags), now_utc().replace(tzinfo=None), proc_id)
                )
                stats["missing_location"] += 1
                logger.warning(f"Event {source_uid}: No location code found in Reserva title")
                continue
            
            # Location code found - look up in database
            cur.execute(
                """
                SELECT code, airport_name, city, state, country, address, coordinates, notes
                FROM lookup_homebases
                WHERE code = %s
                """,
                (location_code,)
            )
            result = cur.fetchone()
            
            if result:
                # Location found in database
                code, airport_name, city, state, country, address, coordinates, notes = result
                
                location_details = {
                    "code": code,
                    "airport_name": airport_name,
                    "city": city,
                    "state": state,
                    "country": country,
                    "address": address,
                    "coordinates": coordinates if coordinates else None,
                    "notes": notes
                }
                
                tags = ["#roquescript-modified", "#location-found"]
                
                cur.execute(
                    """
                    UPDATE processed_events
                    SET
                        location_details = %s,
                        tags = %s,
                        processed_at = %s
                    WHERE id = %s
                    """,
                    (
                        json.dumps(location_details),
                        json.dumps(tags),
                        now_utc().replace(tzinfo=None),
                        proc_id
                    )
                )
                
                stats["found_in_db"] += 1
                logger.info(f"Event {source_uid}: Location {location_code} found ({airport_name})")
            
            else:
                # Location code NOT found - validate format and queue if valid
                
                # Check format: 2-4 uppercase letters
                if not (2 <= len(location_code) <= 4 and location_code.isupper() and location_code.isalpha()):
                    tags = ["#roquescript-modified", "#location-invalid"]
                    cur.execute(
                        """
                        UPDATE processed_events
                        SET tags = %s, processed_at = %s
                        WHERE id = %s
                        """,
                        (json.dumps(tags), now_utc().replace(tzinfo=None), proc_id)
                    )
                    stats["invalid_format"] += 1
                    logger.warning(f"Event {source_uid}: Invalid location code format: {location_code}")
                    continue
                
                # Check if already in pending queue
                cur.execute(
                    "SELECT id FROM homebases_pending_validation WHERE code = %s",
                    (location_code,)
                )
                pending_row = cur.fetchone()
                
                if pending_row:
                    # Already queued, increment counter
                    cur.execute(
                        """
                        UPDATE homebases_pending_validation
                        SET
                            last_occurrence = %s,
                            occurrence_count = occurrence_count + 1
                        WHERE code = %s
                        """,
                        (start_utc, location_code)
                    )
                    stats["already_pending"] += 1
                    logger.info(f"Event {source_uid}: Location code {location_code} already pending")
                
                else:
                    # New location code - queue for validation
                    cur.execute(
                        """
                        INSERT INTO homebases_pending_validation (
                            code, source_event_title,
                            first_occurrence, last_occurrence, occurrence_count,
                            status, created_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (code)
                        DO UPDATE SET
                            last_occurrence = EXCLUDED.last_occurrence,
                            occurrence_count = homebases_pending_validation.occurrence_count + 1
                        """,
                        (
                            location_code,
                            clean_title,
                            start_utc,
                            start_utc,
                            1,
                            "pending",
                            now_utc()
                        )
                    )
                    
                    stats["queued_pending"] += 1
                    logger.info(f"Event {source_uid}: Location code {location_code} queued for validation")
                
                # Mark as unknown in processed_events
                tags = ["#roquescript-modified", "#location-unknown"]
                cur.execute(
                    """
                    UPDATE processed_events
                    SET tags = %s, processed_at = %s
                    WHERE id = %s
                    """,
                    (json.dumps(tags), now_utc().replace(tzinfo=None), proc_id)
                )
        
        except Exception as e:
            logger.error(f"Failed to process location for {source_uid}: {e}", exc_info=True)
            stats["errors"] += 1
    
    # Commit all changes
    conn.commit()
    
    logger.info(f"location_processor complete: "
                f"found_in_db={stats['found_in_db']}, "
                f"queued_pending={stats['queued_pending']}, "
                f"already_pending={stats['already_pending']}, "
                f"missing_location={stats['missing_location']}, "
                f"invalid_format={stats['invalid_format']}, "
                f"errors={stats['errors']}")
    
    return stats


def main(user_id=None):
    """Main entry point."""
    if user_id is None:
        user_id = USER_ID
    
    try:
        conn = get_connection()
        stats = process_locations(conn, user_id)
        conn.close()
        return stats
    except Exception as e:
        logger.error(f"location_processor failed: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    main()
