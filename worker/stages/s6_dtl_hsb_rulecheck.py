"""
HSB duty-limit and deslocamento rule checker.

Creates synthetic events:
- Deslocamento
- Violation on HSB!

Rules covered:
1) HSB duration must be 3h..12h.
2) Monthly HSB count must not exceed 8.
3) After HSB activation, required deslocamento must be >= 150 or >= 90 minutes.
4) Duty checks in a 16h window starting at HSB start:
   - ASB/Activity: HSB start -> event end must be <= 16h.
   - Flight: duty_start=flight_start-30m, compute corte from dtl-singlecrew logic.
"""

import os
import re
import json
import argparse
from bisect import bisect_left
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from utils.db_utils import get_connection
from utils.logging_utils import setup_logging
from utils.notes_utils import append_roquescript_block, build_roquescript_block
from utils.timezone_utils import now_utc
from utils.pipeline_utils import (
    TZ_BRT, FLIGHT_LEG_RE, INTERNATIONAL_LEG_RE, HYBRID_9XXX_RE,
    HOUR_MAP, DUTY_LIMIT_TABLE,
    to_brt, legs_bucket, detect_leg,
)

logger = setup_logging(__name__)

USER_ID = os.getenv("USER_ID", "roque")
USER_HOMEBASE = os.getenv("USER_HOMEBASE", "").strip().upper() or None

MAJOR_BASES_150 = {"GRU", "CGH", "SDU", "GIG"}
MAX_MONTHLY_HSB = 8
MIN_HSB_HOURS = 3
MAX_HSB_HOURS = 12
MAX_WINDOW_HOURS = 16

RESERVA_CODE_RE = re.compile(r"^Reserva(?:\s+em\s+([A-Z]{2,4}))?$", re.IGNORECASE)
FLIGHT_DEP_RE = re.compile(r"^LA\s*\d{3,4}\s+([A-Z]{3})\s*-\s*[A-Z]{3}$", re.IGNORECASE)


def hours_between(start_utc: datetime, end_utc: datetime) -> float:
    return (end_utc - start_utc).total_seconds() / 3600.0


def minutes_between(start_utc: datetime, end_utc: datetime) -> int:
    return int((end_utc - start_utc).total_seconds() // 60)


def is_hsb(event: dict) -> bool:
    title = (event.get("clean_title") or "").strip()
    event_type = (event.get("event_type") or "").upper()
    return title == "Sobreaviso" or event_type == "SOBREAVISO"


def is_asb(event: dict) -> bool:
    title = (event.get("clean_title") or "").strip()
    event_type = (event.get("event_type") or "").upper()
    return title.startswith("Reserva") or event_type == "RESERVA"


def is_activity(event: dict) -> bool:
    title = (event.get("clean_title") or "").strip()
    event_type = (event.get("event_type") or "").upper()
    return title.startswith("Activity :") or event_type == "ACTIVITY"


def is_flight(event: dict) -> bool:
    title = (event.get("clean_title") or "").strip()
    event_type = (event.get("event_type") or "").upper()
    return bool(FLIGHT_LEG_RE.match(title)) or event_type == "FLIGHT"


def is_trigger(event: dict) -> bool:
    return is_asb(event) or is_activity(event) or is_flight(event)




def find_first_in_window(events: list[dict], starts: list[datetime], from_utc: datetime, until_utc: datetime) -> dict | None:
    idx = bisect_left(starts, from_utc)
    while idx < len(events):
        row = events[idx]
        if row["start_utc"] > until_utc:
            return None
        if row["start_utc"] >= from_utc:
            return row
        idx += 1
    return None


def extract_airport_code(event: dict) -> str | None:
    if event.get("location_code"):
        return str(event["location_code"]).upper()
    title = (event.get("clean_title") or "").strip()
    r = RESERVA_CODE_RE.match(title)
    if r and r.group(1):
        return r.group(1).upper()
    f = FLIGHT_DEP_RE.match(title)
    if f:
        return f.group(1).upper()
    return None


def required_travel_minutes(trigger: dict) -> int:
    base_code = USER_HOMEBASE or extract_airport_code(trigger)
    return 150 if base_code in MAJOR_BASES_150 else 90


def hsb_violation_text(rule_code: str) -> str:
    if rule_code == "duty_total_excluding_relocation_above_16h":
        return "Beyond 16 hour duty time."
    if rule_code == "deslocamento_below_required":
        return "Insufficient Relocation time for Base"
    return "Violation on HSB! Please check rule details."


def build_notes(lines: list[str], tag: str) -> str:
    base = "\n".join(lines)
    block = build_roquescript_block(
        "#roquescript #roquescript-created",
        [tag],
        now_utc().isoformat(),
    )
    return append_roquescript_block(base, block)


def clear_previous(cur, user_id: str, source_uid: str | None) -> tuple[int, int]:
    if source_uid:
        cur.execute(
            """
            DELETE FROM processed_events
            WHERE user_id = %s
              AND is_synthetic = TRUE
              AND (source_uid LIKE %s OR source_uid = %s)
            """,
            (user_id, f"{source_uid}-hsb2-%", f"{source_uid}-hsb2-monthly"),
        )
    else:
        cur.execute(
            """
            DELETE FROM processed_events
            WHERE user_id = %s
              AND is_synthetic = TRUE
              AND (
                    source_uid LIKE '%%-hsb2-%%'
                 OR source_uid LIKE 'hsb2-monthly-%%'
              )
            """,
            (user_id,),
        )
    deleted = cur.rowcount
    return deleted, deleted


def upsert_event(
    cur,
    user_id: str,
    source_uid: str,
    event_type: str,
    title: str,
    start_utc: datetime,
    end_utc: datetime,
    notes: str,
    tags: list[str],
    rule_code: str,
):
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
            event_type,
            title,
            title,
            start_utc,
            end_utc,
            notes,
            None,
            None,
            True,
            json.dumps([{"rule": rule_code, "at": now_utc().isoformat()}]),
            json.dumps(tags),
            now_utc().replace(tzinfo=None),
        ),
    )


def create_violation(cur, user_id: str, source_uid: str, anchor_utc: datetime, lines: list[str], rule_code: str) -> None:
    start_utc = anchor_utc + timedelta(minutes=1)
    end_utc = start_utc + timedelta(minutes=10)
    notes = build_notes([hsb_violation_text(rule_code), *lines], f"HSB rule violation: {rule_code}")
    upsert_event(
        cur=cur,
        user_id=user_id,
        source_uid=source_uid,
        event_type="VIOLATION",
        title="Violation on HSB!",
        start_utc=start_utc,
        end_utc=end_utc,
        notes=notes,
        tags=["#roquescript-created", "#synthetic", "#dtl-hsb-rulecheck", "#violation"],
        rule_code=rule_code,
    )


def create_deslocamento(cur, user_id: str, source_uid: str, start_utc: datetime, end_utc: datetime, details: list[str]) -> None:
    notes = build_notes(details, "HSB deslocamento created")
    upsert_event(
        cur=cur,
        user_id=user_id,
        source_uid=source_uid,
        event_type="TRAVEL",
        title="Deslocamento",
        start_utc=start_utc,
        end_utc=end_utc,
        notes=notes,
        tags=["#roquescript-created", "#synthetic", "#dtl-hsb-rulecheck", "#deslocamento"],
        rule_code="hsb_deslocamento",
    )


def projected_duty_window(
    trigger: dict,
    duty_start: datetime,
    hsb_start: datetime,
    non_synth: list[dict],
    checkout_rows: list[dict],
    checkout_starts: list[datetime],
) -> tuple[datetime, datetime, int, str, str, int]:
    """
    Project duty final/cutoff using dtl-singlecrew hour-table logic.

    Returns:
        final_utc, cutoff_utc, legs_count, timeframe_key, bucket_key, duty_limit_hours
    """
    first_checkout = find_first_in_window(
        checkout_rows,
        checkout_starts,
        trigger["start_utc"],
        hsb_start + timedelta(hours=24),
    )
    window_end = first_checkout["start_utc"] if first_checkout else (duty_start + timedelta(hours=12))

    legs_count = 0
    is_international = False
    has_hybrid_9 = False
    for ev in non_synth:
        if ev["start_utc"] < duty_start or ev["start_utc"] >= window_end:
            continue
        is_leg, leg_intl, leg_hybrid = detect_leg((ev.get("clean_title") or "").strip())
        if not is_leg:
            continue
        legs_count += 1
        if leg_intl:
            is_international = True
        if leg_hybrid:
            has_hybrid_9 = True

    duty_start_brt = to_brt(duty_start)
    timeframe_key = HOUR_MAP[duty_start_brt.hour]
    bucket_key = legs_bucket(legs_count)
    duty_limit_hours = DUTY_LIMIT_TABLE[timeframe_key][bucket_key]
    final_utc = duty_start + timedelta(hours=duty_limit_hours)

    if has_hybrid_9:
        cutoff_utc = final_utc - timedelta(minutes=30)
    elif is_international:
        cutoff_utc = final_utc - timedelta(minutes=45)
    else:
        cutoff_utc = final_utc - timedelta(minutes=30)

    return final_utc, cutoff_utc, legs_count, timeframe_key, bucket_key, duty_limit_hours


def monthly_violation_event(cur, user_id: str, month_key: str, lines: list[str]) -> None:
    year, month = month_key.split("-")
    start_utc = datetime(int(year), int(month), 1, 12, 0, 0)
    end_utc = start_utc + timedelta(minutes=10)
    notes = build_notes(lines, "HSB monthly violation")
    upsert_event(
        cur=cur,
        user_id=user_id,
        source_uid=f"hsb2-monthly-{month_key}",
        event_type="VIOLATION",
        title="Violation on HSB!",
        start_utc=start_utc,
        end_utc=end_utc,
        notes=notes,
        tags=["#roquescript-created", "#synthetic", "#dtl-hsb-rulecheck", "#violation", "#monthly"],
        rule_code="hsb_monthly_limit",
    )


def main():
    parser = argparse.ArgumentParser(description="HSB duty-limit and deslocamento checker")
    parser.add_argument("--user-id", default=USER_ID, help="User id")
    parser.add_argument("--source-uid", default=None, help="Optional specific HSB source_uid")
    args = parser.parse_args()

    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()

        if args.source_uid:
            cur.execute(
                """
                SELECT source_uid, event_type, clean_title, location_code, start_utc, end_utc, is_synthetic
                FROM processed_events
                WHERE user_id = %s
                  AND source_uid = %s
                ORDER BY start_utc
                """,
                (args.user_id, args.source_uid),
            )
        else:
            cur.execute(
                """
                SELECT source_uid, event_type, clean_title, location_code, start_utc, end_utc, is_synthetic
                FROM processed_events
                WHERE user_id = %s
                ORDER BY start_utc
                """,
                (args.user_id,),
            )

        rows = cur.fetchall()
        events = [
            {
                "source_uid": r[0],
                "event_type": r[1],
                "clean_title": r[2],
                "location_code": r[3],
                "start_utc": r[4],
                "end_utc": r[5],
                "is_synthetic": r[6],
            }
            for r in rows
        ]
        non_synth = [e for e in events if not e["is_synthetic"]]
        hsb_rows = [e for e in non_synth if is_hsb(e)]
        trigger_rows = [e for e in non_synth if is_trigger(e)]
        checkout_rows = [e for e in events if e["is_synthetic"] and (e.get("clean_title") or "").strip() == "Checkout"]
        trigger_starts = [e["start_utc"] for e in trigger_rows]
        checkout_starts = [e["start_utc"] for e in checkout_rows]

        clear_previous(cur, args.user_id, args.source_uid)
        stats = {
            "hsb_checked": 0,
            "deslocamentos_created": 0,
            "violations_created": 0,
            "monthly_violations_created": 0,
            "violation_by_rule": defaultdict(int),
        }

        month_to_hsb_count: dict[str, int] = defaultdict(int)
        month_to_rules: dict[str, set[str]] = defaultdict(set)

        for hsb in hsb_rows:
            stats["hsb_checked"] += 1
            hsb_uid = hsb["source_uid"]
            hsb_start = hsb["start_utc"]
            hsb_end = hsb["end_utc"]
            hsb_month = to_brt(hsb_start).strftime("%Y-%m")
            month_to_hsb_count[hsb_month] += 1

            hsb_hours = hours_between(hsb_start, hsb_end)
            if hsb_hours < MIN_HSB_HOURS or hsb_hours > MAX_HSB_HOURS:
                rule = "hsb_duration_out_of_bounds"
                create_violation(
                    cur,
                    args.user_id,
                    f"{hsb_uid}-hsb2-violation-{rule}",
                    hsb_end,
                    [
                        f"source_uid={hsb_uid}",
                        f"hsb_duration_hours={hsb_hours:.2f}",
                        "expected_range_hours=3..12",
                    ],
                    rule,
                )
                stats["violations_created"] += 1
                stats["violation_by_rule"][rule] += 1
                month_to_rules[hsb_month].add(rule)

            trigger = find_first_in_window(
                trigger_rows,
                trigger_starts,
                hsb_end + timedelta(minutes=1),
                hsb_start + timedelta(hours=24),
            )
            if not trigger:
                continue

            required = required_travel_minutes(trigger)
            if is_flight(trigger):
                duty_start = trigger["start_utc"] - timedelta(minutes=30)
            else:
                duty_start = trigger["start_utc"]

            desloc_start = hsb_end + timedelta(minutes=1)
            desloc_end = duty_start - timedelta(minutes=1)
            desloc_minutes = minutes_between(hsb_end, duty_start)

            if desloc_end >= desloc_start:
                create_deslocamento(
                    cur,
                    args.user_id,
                    f"{hsb_uid}-hsb2-deslocamento",
                    desloc_start,
                    desloc_end,
                    [
                        f"source_uid={hsb_uid}",
                        f"trigger_uid={trigger['source_uid']}",
                        f"trigger_title={trigger['clean_title']}",
                        f"required_travel_minutes={required}",
                        f"actual_travel_minutes={desloc_minutes}",
                    ],
                )
                stats["deslocamentos_created"] += 1

            if desloc_minutes < required:
                rule = "deslocamento_below_required"
                create_violation(
                    cur,
                    args.user_id,
                    f"{hsb_uid}-hsb2-violation-{rule}",
                    hsb_end,
                    [
                        f"source_uid={hsb_uid}",
                        f"trigger_uid={trigger['source_uid']}",
                        f"required_minutes={required}",
                        f"actual_minutes={desloc_minutes}",
                    ],
                    rule,
                )
                stats["violations_created"] += 1
                stats["violation_by_rule"][rule] += 1
                month_to_rules[hsb_month].add(rule)

            if is_asb(trigger) or is_activity(trigger) or is_flight(trigger):
                final_utc, cutoff_utc, legs_count, timeframe_key, bucket_key, duty_limit_hours = projected_duty_window(
                    trigger=trigger,
                    duty_start=duty_start,
                    hsb_start=hsb_start,
                    non_synth=non_synth,
                    checkout_rows=checkout_rows,
                    checkout_starts=checkout_starts,
                )

                # Business rule: duty total excludes required relocation allowance (150/90).
                effective_total_minutes = minutes_between(hsb_start, final_utc) - required
                if effective_total_minutes > (MAX_WINDOW_HOURS * 60):
                    rule = "duty_total_excluding_relocation_above_16h"
                    create_violation(
                        cur,
                        args.user_id,
                        f"{hsb_uid}-hsb2-violation-{rule}",
                        final_utc,
                        [
                            f"source_uid={hsb_uid}",
                            f"trigger_uid={trigger['source_uid']}",
                            f"trigger_type={trigger['event_type']}",
                            f"duty_start_utc={duty_start.isoformat()}",
                            f"projected_final_utc={final_utc.isoformat()}",
                            f"projected_cutoff_utc={cutoff_utc.isoformat()}",
                            f"duty_limit_hours={duty_limit_hours}",
                            f"legs_count={legs_count}",
                            f"timeframe_key={timeframe_key}",
                            f"table_bucket={bucket_key}",
                            f"required_relocation_minutes={required}",
                            f"effective_total_minutes={effective_total_minutes}",
                            "effective_limit_minutes=960",
                        ],
                        rule,
                    )
                    stats["violations_created"] += 1
                    stats["violation_by_rule"][rule] += 1
                    month_to_rules[hsb_month].add(rule)

        for month_key, count in month_to_hsb_count.items():
            if count <= MAX_MONTHLY_HSB:
                continue
            monthly_violation_event(
                cur,
                args.user_id,
                month_key,
                [
                    hsb_violation_text("hsb_monthly_limit"),
                    f"Monthly HSB limit violated in {month_key}",
                    f"hsb_count={count}",
                    "monthly_limit=8",
                    f"rules_detected={','.join(sorted(month_to_rules.get(month_key, set())))}",
                ],
            )
            stats["monthly_violations_created"] += 1

        conn.commit()
        cur.close()
        logger.info(
            "dtl-hsb-rulecheck complete: "
            f"hsb_checked={stats['hsb_checked']}, "
            f"deslocamentos_created={stats['deslocamentos_created']}, "
            f"violations_created={stats['violations_created']}, "
            f"monthly_violations_created={stats['monthly_violations_created']}, "
            f"violation_by_rule={json.dumps(stats['violation_by_rule'])}"
        )
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    main()
