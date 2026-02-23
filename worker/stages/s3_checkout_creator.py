"""
CheckoutCreator Module: Second stage of transformation pipeline.

Processes Apresentação events to:
1. Create/refresh synthetic Checkout event 1 minute after original end time.
2. Shorten Apresentação duration to 10 minutes.
"""

import os
import logging
import json
from datetime import timedelta

from utils.db_utils import get_connection
from utils.logging_utils import setup_logging
from utils.notes_utils import append_roquescript_block, build_roquescript_block
from utils.timezone_utils import now_utc
from utils.pipeline_utils import intervals_overlap, load_standby_windows, apresentacao_overlaps_standby

logger = setup_logging(__name__)

USER_ID = os.getenv("USER_ID", "roque")


def create_synthetic_checkout_uid(apresentacao_uid):
    """Generate synthetic UID for Checkout event."""
    return f"{apresentacao_uid}-checkout-synthetic"


def process_apresentacoes(conn, user_id):
    """
    Main processing function for Apresentação events.
    
    For each Apresentação:
    1. Resolve original duty end from raw_events when available
    2. Create or update Checkout event (start at original_end_utc + 1 min, 10 min duration)
    3. Shorten Apresentação to 10 minutes
    
    Returns:
        dict with statistics
    """
    logger.info(f"Starting checkout_creator for user_id={user_id}")
    
    stats = {
        "apresentacao_shortened": 0,
        "checkout_upserted": 0,
        "already_short": 0,
        "skipped_standby_overlap": 0,
        "errors": 0
    }
    
    cur = conn.cursor()
    
    # Query all parsed Apresentação events (non-synthetic) and link raw end time when possible.
    cur.execute(
        """
        SELECT
            p.id,
            p.source_uid,
            p.start_utc,
            p.end_utc,
            p.notes,
            p.modifications,
            COALESCE(r.end_utc, p.end_utc) AS original_end_utc
        FROM processed_events p
        LEFT JOIN raw_events r ON p.raw_event_id = r.id
        WHERE p.user_id = %s
          AND p.is_synthetic = FALSE
          AND p.clean_title = 'Apresentação'
        ORDER BY p.start_utc
        """,
        (user_id,)
    )
    
    apresentacao_rows = cur.fetchall()
    logger.info(f"Found {len(apresentacao_rows)} Apresentação events to process")
    standby_windows = load_standby_windows(cur, user_id)
    
    for proc_id, source_uid, start_utc, end_utc, notes, modifications_json, original_end_utc in apresentacao_rows:
        try:
            checkout_uid = create_synthetic_checkout_uid(source_uid)
            if apresentacao_overlaps_standby(source_uid, start_utc, end_utc, standby_windows):
                # Defensive guard: Report Time overlapping Reserva/Sobreaviso must not create Checkout.
                cur.execute(
                    "DELETE FROM processed_events WHERE user_id = %s AND source_uid = %s",
                    (user_id, checkout_uid),
                )
                stats["skipped_standby_overlap"] += 1
                logger.info(f"Skipped Checkout for {source_uid}: overlaps Reserva/Sobreaviso")
                continue

            # Guard against invalid source data
            if original_end_utc <= start_utc:
                original_end_utc = end_utc
            
            # ===== STEP 1: Create/update Checkout event FIRST =====
            checkout_start_utc = original_end_utc + timedelta(minutes=1)
            checkout_end_utc = checkout_start_utc + timedelta(minutes=10)
            
            creation_timestamp = now_utc().isoformat()
            checkout_modifications = [{
                "rule": "synthetic_checkout_creation",
                "original_duty_end": original_end_utc.isoformat(),
                "at": creation_timestamp
            }]

            checkout_block = build_roquescript_block(
                "#roquescript #roquescript-created",
                [f"Synthetic Checkout event created at end of duty period ({original_end_utc.isoformat()})"],
                creation_timestamp
            )
            checkout_notes = append_roquescript_block(None, checkout_block)
            checkout_tags = ["#roquescript-created", "#synthetic"]
            
            cur.execute(
                """
                INSERT INTO processed_events (
                    user_id, source_uid, raw_event_id, event_type, original_title, clean_title,
                    start_utc, end_utc, notes, notes_original,
                    event_url, is_synthetic, modifications, tags, processed_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id, source_uid)
                DO UPDATE SET
                    event_type = EXCLUDED.event_type,
                    original_title = EXCLUDED.original_title,
                    clean_title = EXCLUDED.clean_title,
                    start_utc = EXCLUDED.start_utc,
                    end_utc = EXCLUDED.end_utc,
                    notes = EXCLUDED.notes,
                    event_url = EXCLUDED.event_url,
                    modifications = EXCLUDED.modifications,
                    tags = EXCLUDED.tags,
                    processed_at = EXCLUDED.processed_at
                """,
                (
                    user_id,
                    checkout_uid,
                    None,  # raw_event_id (no raw event for synthetic)
                    "CHECKOUT",
                    "Checkout",
                    "Checkout",
                    checkout_start_utc,
                    checkout_end_utc,
                    checkout_notes,
                    None,  # notes_original
                    None,  # event_url
                    True,  # is_synthetic
                    json.dumps(checkout_modifications),
                    json.dumps(checkout_tags),
                    now_utc().replace(tzinfo=None)
                )
            )
            
            stats["checkout_upserted"] += 1
            logger.info(f"Upserted Checkout {checkout_uid}: {checkout_start_utc} - {checkout_end_utc}")
            
            # ===== STEP 2: Ensure Apresentação duration is 10 minutes =====
            new_end_utc = start_utc + timedelta(minutes=10)
            original_duration = (end_utc - start_utc).total_seconds() / 60  # minutes
            if int(original_duration) == 10:
                stats["already_short"] += 1
                continue
            
            shorten_timestamp = now_utc().isoformat()
            shorten_block = build_roquescript_block(
                "#roquescript #roquescript-modified",
                [f"Apresentação shortened from {int(original_duration)}m to 10m"],
                shorten_timestamp
            )
            notes_updated = append_roquescript_block(notes, shorten_block)
            
            modifications = []
            try:
                if isinstance(modifications_json, list):
                    modifications = modifications_json
                elif isinstance(modifications_json, str):
                    loaded = json.loads(modifications_json)
                    modifications = loaded if isinstance(loaded, list) else []
            except Exception:
                modifications = []
            
            modifications.append({
                "rule": "apresentacao_shortened",
                "from_minutes": int(original_duration),
                "to_minutes": 10,
                "at": now_utc().isoformat()
            })
            
            tags = ["#roquescript-modified"]
            
            cur.execute(
                """
                UPDATE processed_events
                SET
                    event_type = 'APRESENTAÇÃO',
                    clean_title = 'Apresentação',
                    end_utc = %s,
                    notes = %s,
                    modifications = %s,
                    tags = %s,
                    processed_at = %s
                WHERE id = %s
                """,
                (
                    new_end_utc,
                    notes_updated,
                    json.dumps(modifications),
                    json.dumps(tags),
                    now_utc().replace(tzinfo=None),
                    proc_id
                )
            )
            
            stats["apresentacao_shortened"] += 1
            logger.info(f"Shortened Apresentação {source_uid}: {start_utc} - {new_end_utc} (from {int(original_duration)}m)")
        
        except Exception as e:
            logger.error(f"Failed to process Apresentação {source_uid}: {e}", exc_info=True)
            stats["errors"] += 1
    
    # Commit all changes
    conn.commit()
    
    logger.info(f"checkout_creator complete: "
                f"apresentacao_shortened={stats['apresentacao_shortened']}, "
                f"checkout_upserted={stats['checkout_upserted']}, "
                f"already_short={stats['already_short']}, "
                f"skipped_standby_overlap={stats['skipped_standby_overlap']}, "
                f"errors={stats['errors']}")
    
    return stats


def main(user_id=None):
    """Main entry point."""
    if user_id is None:
        user_id = USER_ID
    
    try:
        conn = get_connection()
        stats = process_apresentacoes(conn, user_id)
        conn.close()
        return stats
    except Exception as e:
        logger.error(f"checkout_creator failed: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    main()
