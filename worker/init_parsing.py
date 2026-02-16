"""
InitParsing Module: First stage of transformation pipeline.

Processes raw_events and applies:
1. Deletion rules (Start Time, overlapping Report Time)
2. Modification rules (HSB -> Sobreaviso, ASB -> Reserva, Activity code extraction)
3. Activity code extraction and database queue
4. Tag tracking with #roquescript-modified

Output: processed_events table with cleaned, classified, normalized events
"""

import os
import logging
import json
import re
import uuid
from datetime import datetime, timezone

from utils.db_utils import get_connection
from utils.logging_utils import setup_logging
from utils.notes_utils import append_roquescript_block, build_roquescript_block
from utils.timezone_utils import now_utc

logger = setup_logging(__name__)

USER_ID = os.getenv("USER_ID", "roque")
CYCLE_ID = str(uuid.uuid4())


# Deletion rules
DELETION_RULES = {
    "start_time_removed": lambda title: "Start Time:" in title,
}
STANDBY_KEYWORD_RE = re.compile(r"\b(ASB|HSB)\b", flags=re.IGNORECASE)

RESERVA_URL = "https://docs.google.com/forms/d/e/1FAIpQLSfBlSTjRDYhVufIHQN5y3uiAqRy3jHRZFuTIpjnxBasFzt67Q/viewform"


def get_homebases_map(conn):
    """Load homebase details indexed by code."""
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT code, airport_name, city, state, country, address, coordinates, notes
            FROM lookup_homebases
            """
        )
        rows = cur.fetchall()
        cur.close()
        
        homebases = {}
        for code, airport_name, city, state, country, address, coordinates, notes in rows:
            homebases[code] = {
                "code": code,
                "airport_name": airport_name,
                "city": city,
                "state": state,
                "country": country,
                "address": address,
                "coordinates": coordinates if coordinates else None,
                "notes": notes,
            }
        return homebases
    except Exception as e:
        logger.warning(f"Failed to load homebases: {e}")
        return {}


def check_deletion_rules(title):
    """
    Check if event should be deleted based on title rules.
    
    Returns:
        (should_delete: bool, reason: str)
    """
    # Check hardcoded deletion rules
    for reason, rule_func in DELETION_RULES.items():
        if rule_func(title):
            return True, reason
    
    return False, None


def intervals_overlap(start_a, end_a, start_b, end_b):
    """Return True when two [start, end) intervals overlap."""
    return start_a < end_b and end_a > start_b


def is_standby_summary(title):
    """Return True for ASB/HSB entries from source calendar titles."""
    if not title:
        return False
    return bool(STANDBY_KEYWORD_RE.search(title))


def build_standby_windows(raw_rows):
    """Collect standby windows (ASB/HSB) from raw rows for overlap checks."""
    windows = []
    for _raw_id, source_uid, start_utc, end_utc, summary, _description in raw_rows:
        if is_standby_summary(summary or ""):
            windows.append({
                "source_uid": source_uid,
                "start_utc": start_utc,
                "end_utc": end_utc,
            })
    return windows


def report_overlaps_standby(source_uid, start_utc, end_utc, standby_windows):
    """Return True if this Report Time overlaps any ASB/HSB standby window."""
    for standby in standby_windows:
        if standby["source_uid"] == source_uid:
            continue
        if intervals_overlap(start_utc, end_utc, standby["start_utc"], standby["end_utc"]):
            return True
    return False


def delete_event_and_related_synthetics(cur, user_id, source_uid):
    """Delete one processed event and all known synthetic children derived from it."""
    suffixes = (
        "",
        "-checkout-synthetic",
        "-dtl-final",
        "-dtl-cut-d",
        "-dtl-cut-i",
        "-dtl-sc-ext-1h",
        "-dtl-sc-ext-cut",
    )
    uids = [f"{source_uid}{suffix}" for suffix in suffixes]
    cur.execute(
        """
        DELETE FROM processed_events
        WHERE user_id = %s
          AND source_uid = ANY(%s)
        """,
        (user_id, uids),
    )
    return cur.rowcount


def cleanup_standby_report_time_conflicts(cur, user_id):
    """
    Remove already-processed Report Time/Apresentação entries that overlap Reserva/Sobreaviso.
    This keeps historical state clean even when no new raw events arrive.
    """
    cur.execute(
        """
        SELECT source_uid, start_utc, end_utc
        FROM processed_events
        WHERE user_id = %s
          AND is_synthetic = FALSE
          AND clean_title = 'Apresentação'
        """,
        (user_id,),
    )
    report_rows = cur.fetchall()

    cur.execute(
        """
        SELECT source_uid, start_utc, end_utc
        FROM processed_events
        WHERE user_id = %s
          AND is_synthetic = FALSE
          AND (
                clean_title LIKE 'Reserva%%'
             OR clean_title = 'Sobreaviso'
             OR event_type IN ('RESERVA', 'SOBREAVISO')
          )
        """,
        (user_id,),
    )
    standby_rows = cur.fetchall()
    if not report_rows or not standby_rows:
        return 0

    conflicted_report_uids = set()
    for report_uid, report_start, report_end in report_rows:
        for standby_uid, standby_start, standby_end in standby_rows:
            if report_uid == standby_uid:
                continue
            if intervals_overlap(report_start, report_end, standby_start, standby_end):
                conflicted_report_uids.add(report_uid)
                break

    removed = 0
    for report_uid in conflicted_report_uids:
        cur.execute(
            """
            UPDATE raw_events
            SET skip_reason = %s, processed_flag = TRUE
            WHERE user_id = %s AND source_uid = %s
            """,
            ("report_time_overlap_with_standby", user_id, report_uid),
        )
        delete_event_and_related_synthetics(cur, user_id, report_uid)
        removed += 1

    if removed:
        logger.info(f"Removed {removed} Report Time/Apresentação events overlapping standby windows")
    return removed


def classify_event_type(title):
    """Classify event type based on title patterns."""
    if "Report Time" in title:
        return "REPORT_TIME"
    elif "Activity" in title:
        return "ACTIVITY"
    elif "Flight" in title:
        return "FLIGHT"
    else:
        return "UNKNOWN"


def apply_modifications(title, notes, event_type):
    """
    Apply all title and notes modifications.
    Returns: (new_title, source_notes, roquescript_blocks, modifications_list, tags_list, special_flags)
    
    Modifications tracked:
    - HSB -> Sobreaviso
    - ASB -> Reserva (with location extraction attempt)
    - Activity code extraction
    """
    modifications = []
    tags = []
    roquescript_blocks = []
    new_title = title
    source_notes = notes
    special_flags = {}  # e.g., {"activity_code": "APT-BRA"}
    
    # HSB -> Sobreaviso (single title, ignore any suffix like "at XXX")
    if "HSB" in new_title:
        new_title = "Sobreaviso"
        special_flags["is_sobreaviso"] = True
        timestamp = now_utc().isoformat()
        modifications.append({
            "rule": "hsb_to_sobreaviso",
            "at": timestamp
        })
        roquescript_blocks.append(
            build_roquescript_block(
                "#roquescript #roquescript-modified",
                ["HSB → Sobreaviso"],
                timestamp
            )
        )
    
    # ASB at XXX -> Reserva em XXX (keep location code)
    # If ASB has no "at XXX", try first line of notes (e.g., "GRU-CGH") and use first code.
    if "ASB" in new_title:
        location_code = None
        match = re.search(r'\bASB\s+at\s+([A-Z]{2,4})\b', new_title, flags=re.IGNORECASE)
        if match:
            location_code = match.group(1).upper()
        else:
            first_line = (source_notes.splitlines()[0] if source_notes else "").strip()
            notes_match = re.search(r'\b([A-Z]{2,4})-([A-Z]{2,4})\b', first_line)
            if notes_match:
                # For route-like tokens (XXX-YYY), any endpoint works for standby location.
                location_code = notes_match.group(1).upper()

        if location_code:
            new_title = f"Reserva em {location_code}"
            special_flags["location_code"] = location_code
        else:
            new_title = "Reserva"

        timestamp = now_utc().isoformat()
        modifications.append({
            "rule": "asb_to_reserva",
            "at": timestamp
        })
        block_lines = [f"ASB → {new_title}"]
        if location_code:
            block_lines.append(f"Standby location: {location_code}")
        roquescript_blocks.append(
            build_roquescript_block(
                "#roquescript #roquescript-modified",
                block_lines,
                timestamp
            )
        )

        if special_flags.get("location_code"):
            modifications[-1]["location_code"] = special_flags["location_code"]

        special_flags["is_reserva"] = True
        special_flags["reservation_url"] = RESERVA_URL
    
    # Generic Reserva location extraction (covers titles already in "Reserva em XXX" format)
    if not special_flags.get("location_code"):
        reserva_match = re.search(r'Reserva\s+em\s+([A-Z]{2,4})', new_title, flags=re.IGNORECASE)
        if reserva_match:
            special_flags["location_code"] = reserva_match.group(1).upper()
    
    # Activity code extraction
    if event_type == "ACTIVITY" and "Activity :" in new_title:
        # Extract code: remove "Activity :" prefix
        code_part = new_title.split("Activity :", 1)[1].strip()
        new_title = code_part  # Clean title is just the code
        special_flags["activity_code"] = code_part
        timestamp = now_utc().isoformat()
        modifications.append({
            "rule": "activity_code_extracted",
            "code": code_part,
            "at": timestamp
        })
        roquescript_blocks.append(
            build_roquescript_block(
                "#roquescript #roquescript-modified",
                [f"Activity code extracted: {code_part}"],
                timestamp
            )
        )
    
    # Flight: prefix removal (keep flight number and route: "LA 1234 ABC - DEF")
    if event_type == "FLIGHT" and "Flight :" in new_title:
        new_title = new_title.replace("Flight :", "").strip()
        timestamp = now_utc().isoformat()
        modifications.append({
            "rule": "flight_prefix_removed",
            "at": timestamp
        })
        roquescript_blocks.append(
            build_roquescript_block(
                "#roquescript #roquescript-modified",
                ["Flight prefix removed"],
                timestamp
            )
        )
    
    # Report Time* -> Apresentação (replace whole title)
    if "Report Time" in new_title:
        new_title = "Apresentação"
        timestamp = now_utc().isoformat()
        modifications.append({
            "rule": "report_time_to_apresentacao",
            "at": timestamp
        })
        roquescript_blocks.append(
            build_roquescript_block(
                "#roquescript #roquescript-modified",
                ["Report Time → Apresentação"],
                timestamp
            )
        )
    
    # Always add tag if any modifications
    if modifications:
        if "#roquescript-modified" not in tags:
            tags.append("#roquescript-modified")

    return new_title, source_notes, roquescript_blocks, modifications, tags, special_flags


def check_report_time_overlap(report_time_event, processed_so_far):
    """
    Check if this Report Time overlaps with any Activity events.
    
    Returns:
        (has_overlap: bool, overlapping_activities: list)
    """
    overlaps = []
    report_start = report_time_event["start_utc"]
    report_end = report_time_event["end_utc"]
    
    for proc_event in processed_so_far:
        if proc_event["event_type"] != "ACTIVITY":
            continue
        
        # Check for overlap: start < other_end AND end > other_start
        if report_start < proc_event["end_utc"] and report_end > proc_event["start_utc"]:
            overlaps.append(proc_event)
    
    return len(overlaps) > 0, overlaps


def process_raw_events(conn, user_id):
    """
    Main processing function: read raw_events, apply rules, populate processed_events.
    
    Returns:
        dict with statistics
    """
    logger.info(f"Starting init_parsing for user_id={user_id}, cycle_id={CYCLE_ID}")
    
    stats = {
        "total_raw": 0,
        "processed": 0,
        "deleted": 0,
        "skipped": 0,
        "activities_pending": [],
        "deleted_standby_conflicts": 0,
    }
    
    # Load reference data
    homebases_map = get_homebases_map(conn)
    
    cur = conn.cursor()
    
    # Query raw events that haven't been processed yet
    cur.execute(
        """
        SELECT id, source_uid, start_utc, end_utc, summary, description
        FROM raw_events
        WHERE user_id = %s AND processed_flag = FALSE
        ORDER BY start_utc
        """,
        (user_id,)
    )
    raw_rows = cur.fetchall()
    stats["total_raw"] = len(raw_rows)
    logger.info(f"Found {len(raw_rows)} unprocessed raw events")

    standby_windows = build_standby_windows(raw_rows)
    processed_events_buffer = []  # For overlap detection
    
    for raw_id, source_uid, start_utc, end_utc, summary, description in raw_rows:
        try:
            # Phase 1: Check deletion rules
            should_delete, delete_reason = check_deletion_rules(summary or "")
            
            if should_delete:
                # Mark in raw_events and remove any previously processed copy.
                cur.execute(
                    "UPDATE raw_events SET skip_reason = %s, processed_flag = TRUE WHERE id = %s",
                    (delete_reason, raw_id),
                )
                delete_event_and_related_synthetics(cur, user_id, source_uid)
                stats["deleted"] += 1
                logger.info(f"Event {source_uid}: DELETED ({delete_reason})")
                continue
            
            # Phase 2: Classify event type
            event_type = classify_event_type(summary or "")
            
            # Phase 3: Check Report Time overlap with Activities
            if event_type == "REPORT_TIME":
                if report_overlaps_standby(source_uid, start_utc, end_utc, standby_windows):
                    cur.execute(
                        "UPDATE raw_events SET skip_reason = %s, processed_flag = TRUE WHERE id = %s",
                        ("report_time_overlap_with_standby", raw_id),
                    )
                    delete_event_and_related_synthetics(cur, user_id, source_uid)
                    stats["deleted"] += 1
                    logger.info(f"Event {source_uid}: DELETED (report_time_overlap_with_standby)")
                    continue

                temp_event = {
                    "start_utc": start_utc,
                    "end_utc": end_utc,
                    "event_type": "REPORT_TIME"
                }
                has_overlap, _ = check_report_time_overlap(temp_event, processed_events_buffer)
                if has_overlap:
                    cur.execute(
                        "UPDATE raw_events SET skip_reason = %s, processed_flag = TRUE WHERE id = %s",
                        ("report_time_overlap_with_activity", raw_id),
                    )
                    delete_event_and_related_synthetics(cur, user_id, source_uid)
                    stats["deleted"] += 1
                    logger.info(f"Event {source_uid}: DELETED (report_time_overlap_with_activity)")
                    continue
            
            # Phase 4: Apply modifications
            clean_title, source_notes, roquescript_blocks, modifications, tags, special_flags = apply_modifications(
                summary or "",
                description,
                event_type
            )

            notes_with_meta = source_notes
            for block in roquescript_blocks:
                notes_with_meta = append_roquescript_block(notes_with_meta, block)

            if special_flags.get("is_reserva"):
                event_type = "RESERVA"
            if special_flags.get("is_sobreaviso"):
                event_type = "SOBREAVISO"
            event_url = special_flags.get("reservation_url")
            
            # Phase 5: Insert into processed_events
            activity_code = special_flags.get("activity_code")
            location_code = special_flags.get("location_code")
            location_details = homebases_map.get(location_code) if location_code else None
            
            cur.execute(
                """
                INSERT INTO processed_events (
                    user_id, source_uid, raw_event_id, event_type, original_title, clean_title,
                    activity_code, location_code, location_details, start_utc, end_utc, notes, notes_original,
                    event_url, is_synthetic, modifications, tags, processed_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id, source_uid)
                DO UPDATE SET
                    raw_event_id = EXCLUDED.raw_event_id,
                    event_type = EXCLUDED.event_type,
                    original_title = EXCLUDED.original_title,
                    clean_title = EXCLUDED.clean_title,
                    activity_code = EXCLUDED.activity_code,
                    location_code = EXCLUDED.location_code,
                    location_details = EXCLUDED.location_details,
                    start_utc = EXCLUDED.start_utc,
                    end_utc = EXCLUDED.end_utc,
                    notes = EXCLUDED.notes,
                    notes_original = EXCLUDED.notes_original,
                    event_url = EXCLUDED.event_url,
                    modifications = EXCLUDED.modifications,
                    tags = EXCLUDED.tags,
                    processed_at = EXCLUDED.processed_at
                """,
                (
                    user_id,
                    source_uid,
                    raw_id,
                    event_type,
                    summary,
                    clean_title,
                    activity_code,
                    location_code,
                    json.dumps(location_details) if location_details else None,
                    start_utc,
                    end_utc,
                    notes_with_meta,
                    description,
                    event_url,
                    False,  # is_synthetic
                    json.dumps(modifications),
                    json.dumps(tags),
                    now_utc().replace(tzinfo=None)
                )
            )
            
            # Track for overlap detection
            processed_events_buffer.append({
                "source_uid": source_uid,
                "event_type": event_type,
                "start_utc": start_utc,
                "end_utc": end_utc
            })
            
            # Queue new activity codes for validation
            if activity_code:
                stats["activities_pending"].append(activity_code)
            
            # Mark raw event as processed
            cur.execute(
                "UPDATE raw_events SET processed_flag = TRUE WHERE id = %s",
                (raw_id,)
            )
            
            stats["processed"] += 1
            logger.info(f"Event {source_uid}: PROCESSED (type={event_type})")
        
        except Exception as e:
            logger.error(f"Failed to process event {source_uid}: {e}", exc_info=True)
            stats["skipped"] += 1

    stats["deleted_standby_conflicts"] = cleanup_standby_report_time_conflicts(cur, user_id)

    # Commit all changes
    conn.commit()
    
    logger.info(
        "init_parsing complete: "
        f"processed={stats['processed']}, "
        f"deleted={stats['deleted']}, "
        f"skipped={stats['skipped']}, "
        f"deleted_standby_conflicts={stats['deleted_standby_conflicts']}"
    )
    return stats


def main(user_id=None):
    """Main entry point."""
    if user_id is None:
        user_id = USER_ID
    
    try:
        conn = get_connection()
        stats = process_raw_events(conn, user_id)
        conn.close()
        return stats
    except Exception as e:
        logger.error(f"init_parsing failed: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    main()
