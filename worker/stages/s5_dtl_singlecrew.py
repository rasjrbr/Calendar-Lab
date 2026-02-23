"""
Duty Time Limit (Single Crew) calculator.

Reads processed calendar events and creates synthetic duty markers:
- Final de Jornada
- Horário Corte (d) and/or Horário Corte (i)

Rules are based on:
1) Apresentação start time (BRT hour bucket)
2) Number of flight legs between Apresentação and Checkout
3) International detection (LA 8xxx) and hybrid detection (LA 9xx/9xxx)
"""

import os
import re
import json
import argparse
from datetime import datetime, timedelta, timezone

from utils.db_utils import get_connection
from utils.logging_utils import setup_logging
from utils.notes_utils import ROQUESCRIPT_INFO_MARKER, append_roquescript_block, build_roquescript_block
from utils.timezone_utils import now_utc
from utils.pipeline_utils import (
    TZ_BRT, HOUR_MAP, DUTY_LIMIT_TABLE,
    to_brt, intervals_overlap, legs_bucket, detect_leg,
    load_standby_windows, apresentacao_overlaps_standby,
)

logger = setup_logging(__name__)

USER_ID = os.getenv("USER_ID", "roque")
FLIGHT_NO_RE = re.compile(r"^LA\s*(\d{3,4})\b", re.IGNORECASE)


def extract_original_notes(notes_original: str | None, notes: str | None) -> str | None:
    """Prefer raw source notes and fallback to notes without roquescript metadata."""
    if notes_original and notes_original.strip():
        return notes_original.strip()

    if not notes:
        return None

    base_notes = notes
    if ROQUESCRIPT_INFO_MARKER in base_notes:
        base_notes = base_notes.split(ROQUESCRIPT_INFO_MARKER, 1)[0]

    base_notes = base_notes.strip()
    return base_notes or None


def build_dtl_notes(base_notes: str | None, duty_scope: str) -> str:
    """Compose notes with original text plus a standardized roquescript creation block."""
    block = build_roquescript_block(
        "#roquescript #roquescript-created",
        [f"Duty Limit Added, {duty_scope}"],
        now_utc().isoformat(),
    )
    return append_roquescript_block(base_notes, block)


def clear_dtl_markers(cur, user_id: str, ap_source_uid: str) -> int:
    """Delete all synthetic DTL markers linked to one Apresentação source UID."""
    marker_uids = [
        f"{ap_source_uid}-dtl-final",
        f"{ap_source_uid}-dtl-cut-d",
        f"{ap_source_uid}-dtl-cut-i",
        f"{ap_source_uid}-dtl-sc-ext-1h",
        f"{ap_source_uid}-dtl-sc-ext-cut",
    ]
    cur.execute(
        """
        DELETE FROM processed_events
        WHERE user_id = %s
          AND source_uid = ANY(%s)
        """,
        (user_id, marker_uids),
    )
    return cur.rowcount


def upsert_marker_event(
    cur,
    user_id: str,
    source_uid: str,
    title: str,
    start_utc: datetime,
    end_utc: datetime,
    notes: str,
    notes_original: str | None,
):
    """Insert/update a synthetic marker event in processed_events."""
    cur.execute(
        """
        INSERT INTO processed_events (
            user_id, source_uid, raw_event_id, event_type, original_title, clean_title,
            start_utc, end_utc, notes, notes_original, event_url, is_synthetic, modifications, tags, processed_at
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
            notes_original = EXCLUDED.notes_original,
            event_url = EXCLUDED.event_url,
            modifications = EXCLUDED.modifications,
            tags = EXCLUDED.tags,
            processed_at = EXCLUDED.processed_at
        """,
        (
            user_id,
            source_uid,
            None,
            "DUTY_LIMIT",
            title,
            title,
            start_utc,
            end_utc,
            notes,
            notes_original,
            None,
            True,
            json.dumps([{"rule": "dtl_singlecrew_marker", "at": now_utc().isoformat()}]),
            json.dumps(["#roquescript-created", "#synthetic", "#dtl-singlecrew"]),
            now_utc().replace(tzinfo=None),
        ),
    )


def process_apresentacao(cur, user_id: str, apresentacao_row, standby_windows) -> dict:
    """
    Process one Apresentação event and create/update duty limit markers.

    Returns:
        stats dict for this event.
    """
    proc_id, ap_source_uid, ap_start_utc, ap_end_utc, ap_notes_original, ap_notes = apresentacao_row

    if apresentacao_overlaps_standby(ap_source_uid, ap_start_utc, ap_end_utc, standby_windows):
        cleared = clear_dtl_markers(cur, user_id, ap_source_uid)
        return {
            "skipped_no_checkout": 0,
            "markers_upserted": 0,
            "skipped_standby_overlap": 1,
            "markers_cleared": cleared,
        }

    checkout_uid = f"{ap_source_uid}-checkout-synthetic"
    cur.execute(
        """
        SELECT start_utc
        FROM processed_events
        WHERE user_id = %s AND source_uid = %s
        LIMIT 1
        """,
        (user_id, checkout_uid),
    )
    checkout_row = cur.fetchone()
    fallback_window_end_utc = ap_start_utc + timedelta(hours=12)
    if checkout_row:
        window_end_utc = checkout_row[0]
    else:
        # Fallback required by business rule: use up to 12h ahead from Apresentação.
        window_end_utc = fallback_window_end_utc

    cur.execute(
        """
        SELECT clean_title
        FROM processed_events
        WHERE user_id = %s
          AND start_utc >= %s
          AND start_utc < %s
        ORDER BY start_utc
        """,
        (user_id, ap_start_utc, window_end_utc),
    )
    between_rows = cur.fetchall()

    legs_count = 0
    is_international = False
    has_hybrid_9 = False

    for (title,) in between_rows:
        is_leg, leg_is_international, leg_is_hybrid_9 = detect_leg(title or "")
        if not is_leg:
            continue
        legs_count += 1
        if leg_is_international:
            is_international = True
        if leg_is_hybrid_9:
            has_hybrid_9 = True

    ap_start_brt = to_brt(ap_start_utc)
    timeframe_key = HOUR_MAP[ap_start_brt.hour]
    col_key = legs_bucket(legs_count)
    max_duty_hours = DUTY_LIMIT_TABLE[timeframe_key][col_key]

    final_start_utc = ap_start_utc + timedelta(hours=max_duty_hours)
    final_end_utc = final_start_utc + timedelta(minutes=10)

    # Always keep corte markers in sync by clearing both variants first.
    cut_d_uid = f"{ap_source_uid}-dtl-cut-d"
    cut_i_uid = f"{ap_source_uid}-dtl-cut-i"
    cur.execute(
        "DELETE FROM processed_events WHERE user_id = %s AND source_uid IN (%s, %s)",
        (user_id, cut_d_uid, cut_i_uid),
    )

    base_notes = extract_original_notes(ap_notes_original, ap_notes)
    if has_hybrid_9:
        duty_scope = "Domestic/International"
    elif is_international:
        duty_scope = "International"
    else:
        duty_scope = "Domestic"
    marker_notes = build_dtl_notes(base_notes, duty_scope)

    final_uid = f"{ap_source_uid}-dtl-final"
    upsert_marker_event(
        cur=cur,
        user_id=user_id,
        source_uid=final_uid,
        title="Final de Jornada",
        start_utc=final_start_utc,
        end_utc=final_end_utc,
        notes=marker_notes,
        notes_original=base_notes,
    )

    markers_upserted = 1

    # Corte logic:
    # - If any 9xx/9xxx leg is present, create BOTH markers.
    # - Else if international (8xxx/3digit rule), create only (i) at -45 min.
    # - Else create only (d) at -30 min.
    if has_hybrid_9:
        cut_d_start = final_start_utc - timedelta(minutes=30)
        cut_i_start = final_start_utc - timedelta(minutes=45)
        upsert_marker_event(
            cur,
            user_id,
            cut_d_uid,
            "Horário Corte (d)",
            cut_d_start,
            cut_d_start + timedelta(minutes=10),
            marker_notes,
            base_notes,
        )
        upsert_marker_event(
            cur,
            user_id,
            cut_i_uid,
            "Horário Corte (i)",
            cut_i_start,
            cut_i_start + timedelta(minutes=10),
            marker_notes,
            base_notes,
        )
        markers_upserted += 2
    elif is_international:
        cut_i_start = final_start_utc - timedelta(minutes=45)
        upsert_marker_event(
            cur,
            user_id,
            cut_i_uid,
            "Horário Corte (i)",
            cut_i_start,
            cut_i_start + timedelta(minutes=10),
            marker_notes,
            base_notes,
        )
        markers_upserted += 1
    else:
        cut_d_start = final_start_utc - timedelta(minutes=30)
        upsert_marker_event(
            cur,
            user_id,
            cut_d_uid,
            "Horário Corte (d)",
            cut_d_start,
            cut_d_start + timedelta(minutes=10),
            marker_notes,
            base_notes,
        )
        markers_upserted += 1

    # Ensure Apresentação duration is 10 minutes, per requirement.
    ap_new_end_utc = ap_start_utc + timedelta(minutes=10)
    cur.execute(
        """
        UPDATE processed_events
        SET end_utc = %s, processed_at = %s
        WHERE id = %s
        """,
        (ap_new_end_utc, now_utc().replace(tzinfo=None), proc_id),
    )

    return {
        "skipped_no_checkout": 0 if checkout_row else 1,
        "markers_upserted": markers_upserted,
        "skipped_standby_overlap": 0,
        "markers_cleared": 0,
    }


def main():
    parser = argparse.ArgumentParser(description="DTL single-crew marker generator")
    parser.add_argument("--user-id", default=USER_ID, help="User id")
    parser.add_argument("--source-uid", default=None, help="Optional specific Apresentação source_uid")
    args = parser.parse_args()

    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()

        if args.source_uid:
            cur.execute(
                """
                SELECT id, source_uid, start_utc, end_utc, notes_original, notes
                FROM processed_events
                WHERE user_id = %s
                  AND source_uid = %s
                  AND is_synthetic = FALSE
                  AND clean_title = 'Apresentação'
                ORDER BY start_utc
                """,
                (args.user_id, args.source_uid),
            )
        else:
            cur.execute(
                """
                SELECT id, source_uid, start_utc, end_utc, notes_original, notes
                FROM processed_events
                WHERE user_id = %s
                  AND is_synthetic = FALSE
                  AND clean_title = 'Apresentação'
                ORDER BY start_utc
                """,
                (args.user_id,),
            )

        apresentacao_rows = cur.fetchall()
        logger.info(f"dtl-singlecrew: found {len(apresentacao_rows)} Apresentação events")
        standby_windows = load_standby_windows(cur, args.user_id)

        totals = {
            "processed": 0,
            "skipped_no_checkout": 0,
            "markers_upserted": 0,
            "skipped_standby_overlap": 0,
            "markers_cleared": 0,
        }

        for row in apresentacao_rows:
            stats = process_apresentacao(cur, args.user_id, row, standby_windows)
            totals["processed"] += 1
            totals["skipped_no_checkout"] += stats["skipped_no_checkout"]
            totals["markers_upserted"] += stats["markers_upserted"]
            totals["skipped_standby_overlap"] += stats["skipped_standby_overlap"]
            totals["markers_cleared"] += stats["markers_cleared"]

        conn.commit()
        cur.close()
        logger.info(
            "dtl-singlecrew complete: "
            f"processed={totals['processed']}, "
            f"skipped_no_checkout={totals['skipped_no_checkout']}, "
            f"markers_upserted={totals['markers_upserted']}, "
            f"skipped_standby_overlap={totals['skipped_standby_overlap']}, "
            f"markers_cleared={totals['markers_cleared']}"
        )
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    main()
