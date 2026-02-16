"""
Single-crew duty limit extension checker.

Rule:
- Evaluate duties in the last 2 days up to today (never future).
- If Checkout is beyond Final de Jornada, create:
  1) "Extensão 1 Hora" (60 min), starting 1 minute after Horário Corte
  2) "Corte Extensão!" (10 min), starting at extension end
"""

import os
import json
import argparse
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from utils.db_utils import get_connection
from utils.logging_utils import setup_logging
from utils.timezone_utils import now_utc

logger = setup_logging(__name__)

USER_ID = os.getenv("USER_ID", "roque")
TZ_BRT = ZoneInfo("America/Sao_Paulo")


def brt_window_to_utc():
    """
    Build [start, end) UTC window:
    - start: BRT midnight two days ago
    - end:   BRT midnight tomorrow (so includes today, excludes future)
    """
    now_brt = datetime.now(TZ_BRT)
    start_brt = now_brt.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=2)
    end_brt = now_brt.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    start_utc = start_brt.astimezone(timezone.utc).replace(tzinfo=None)
    end_utc = end_brt.astimezone(timezone.utc).replace(tzinfo=None)
    return start_utc, end_utc


def upsert_synth_event(cur, user_id, source_uid, title, start_utc, end_utc, notes):
    """Insert/update synthetic marker event."""
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
            event_url = EXCLUDED.event_url,
            modifications = EXCLUDED.modifications,
            tags = EXCLUDED.tags,
            processed_at = EXCLUDED.processed_at
        """,
        (
            user_id,
            source_uid,
            None,
            "DUTY_LIMIT_EXTENSION",
            title,
            title,
            start_utc,
            end_utc,
            notes,
            None,
            None,
            True,
            json.dumps([{"rule": "dtl_sc_ext_marker", "at": now_utc().isoformat()}]),
            json.dumps(["#roquescript-modified", "#synthetic", "#dtl-sc-ext"]),
            now_utc().replace(tzinfo=None),
        ),
    )


def main():
    parser = argparse.ArgumentParser(description="Single-crew extension marker generator")
    parser.add_argument("--user-id", default=USER_ID, help="User id")
    args = parser.parse_args()

    start_utc, end_utc = brt_window_to_utc()
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()

        cur.execute(
            """
            SELECT source_uid, start_utc
            FROM processed_events
            WHERE user_id = %s
              AND clean_title = 'Final de Jornada'
              AND is_synthetic = TRUE
              AND start_utc >= %s
              AND start_utc < %s
            ORDER BY start_utc
            """,
            (args.user_id, start_utc, end_utc),
        )
        finals = cur.fetchall()
        logger.info(f"dtl-sc-ext: found {len(finals)} Final de Jornada in window")

        stats = {
            "checked": 0,
            "eligible_extension": 0,
            "missing_data": 0,
            "upserted": 0,
            "cleared": 0,
        }

        for final_uid, final_start_utc in finals:
            stats["checked"] += 1
            if not final_uid.endswith("-dtl-final"):
                stats["missing_data"] += 1
                continue

            base_uid = final_uid[:-10]  # strip "-dtl-final"
            checkout_uid = f"{base_uid}-checkout-synthetic"
            cut_d_uid = f"{base_uid}-dtl-cut-d"
            cut_i_uid = f"{base_uid}-dtl-cut-i"
            ext_uid = f"{base_uid}-dtl-sc-ext-1h"
            ext_cut_uid = f"{base_uid}-dtl-sc-ext-cut"

            cur.execute(
                """
                SELECT source_uid, start_utc
                FROM processed_events
                WHERE user_id = %s AND source_uid IN (%s, %s, %s)
                """,
                (args.user_id, checkout_uid, cut_d_uid, cut_i_uid),
            )
            related = {r[0]: r[1] for r in cur.fetchall()}

            checkout_start = related.get(checkout_uid)
            cut_starts = [related.get(cut_d_uid), related.get(cut_i_uid)]
            cut_starts = [c for c in cut_starts if c is not None]

            if checkout_start is None or not cut_starts:
                stats["missing_data"] += 1
                continue

            # If both cut markers exist, use the latest one (closest to Final de Jornada).
            cut_start = max(cut_starts)

            if checkout_start > final_start_utc:
                stats["eligible_extension"] += 1
                ext_start = cut_start + timedelta(minutes=1)
                ext_end = ext_start + timedelta(hours=1)
                ext_cut_start = ext_end
                ext_cut_end = ext_cut_start + timedelta(minutes=10)

                notes = (
                    f"[#dtl-sc-ext] checkout_start={checkout_start.isoformat()}, "
                    f"final_start={final_start_utc.isoformat()}, cut_start={cut_start.isoformat()}"
                )

                upsert_synth_event(
                    cur,
                    args.user_id,
                    ext_uid,
                    "Extensão 1 Hora",
                    ext_start,
                    ext_end,
                    notes,
                )
                upsert_synth_event(
                    cur,
                    args.user_id,
                    ext_cut_uid,
                    "Corte Extensão!",
                    ext_cut_start,
                    ext_cut_end,
                    notes,
                )
                stats["upserted"] += 2
            else:
                # Keep state clean if duty is not beyond final limit anymore.
                cur.execute(
                    "DELETE FROM processed_events WHERE user_id = %s AND source_uid IN (%s, %s)",
                    (args.user_id, ext_uid, ext_cut_uid),
                )
                stats["cleared"] += cur.rowcount

        conn.commit()
        cur.close()
        logger.info(
            "dtl-sc-ext complete: "
            f"checked={stats['checked']}, "
            f"eligible_extension={stats['eligible_extension']}, "
            f"missing_data={stats['missing_data']}, "
            f"upserted={stats['upserted']}, "
            f"cleared={stats['cleared']}"
        )
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    main()
