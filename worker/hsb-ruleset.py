"""
HSB (Sobreaviso) ruleset violation checker.

This script does not change duty markers from dtl-singlecrew.py.
It only checks standby-related constraints and creates synthetic
"Violation!" events when a breach is detected.
"""

import os
import re
import json
import argparse
from bisect import bisect_left
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from utils.db_utils import get_connection
from utils.logging_utils import setup_logging
from utils.notes_utils import append_roquescript_block, build_roquescript_block
from utils.timezone_utils import now_utc

logger = setup_logging(__name__)

USER_ID = os.getenv("USER_ID", "roque")
TZ_BRT = ZoneInfo("America/Sao_Paulo")

MAJOR_BASES_150 = {"GRU", "CGH", "GIG", "SDU"}
MAX_MONTHLY_STANDBY = 8
MIN_STANDBY_HOURS = 3
MAX_STANDBY_HOURS = 12
MAX_TOTAL_HOURS_AFTER_HSB = 16

FLIGHT_TITLE_RE = re.compile(r"^LA\s*\d{3,4}\s+([A-Z]{3})\s*-\s*([A-Z]{3})$", re.IGNORECASE)
RESERVA_TITLE_RE = re.compile(r"^Reserva(?:\s+em\s+([A-Z]{2,4}))?$", re.IGNORECASE)


def to_brt(utc_naive: datetime) -> datetime:
    """Convert naive UTC datetime from DB to aware BRT datetime."""
    return utc_naive.replace(tzinfo=timezone.utc).astimezone(TZ_BRT)


def fmt_brt(utc_naive: datetime) -> str:
    """Format naive UTC datetime in BRT for human-readable notes."""
    return to_brt(utc_naive).strftime("%Y-%m-%d %H:%M")


def hours_between(start_utc: datetime, end_utc: datetime) -> float:
    """Return decimal hours between two naive UTC datetimes."""
    return (end_utc - start_utc).total_seconds() / 3600.0


def is_sobreaviso(event_type: str | None, clean_title: str | None) -> bool:
    """Return True if event is an HSB/Sobreaviso record."""
    return (clean_title or "").strip() == "Sobreaviso" or (event_type or "").upper() == "SOBREAVISO"


def is_reserva(event_type: str | None, clean_title: str | None) -> bool:
    """Return True if event is an ASB/Reserva record."""
    title = (clean_title or "").strip()
    return (event_type or "").upper() == "RESERVA" or title.startswith("Reserva")


def is_flight(event_type: str | None, clean_title: str | None) -> bool:
    """Return True for normalized flight titles."""
    title = (clean_title or "").strip()
    return bool(FLIGHT_TITLE_RE.match(title)) or (event_type or "").upper() == "FLIGHT"


def is_duty_trigger(event: dict) -> bool:
    """
    Duty trigger candidates after HSB.
    Includes Reserva, Apresentação and Flight starts.
    """
    title = (event.get("clean_title") or "").strip()
    event_type = (event.get("event_type") or "").upper()
    if is_reserva(event_type, title):
        return True
    if title == "Apresentação" or event_type == "APRESENTAÇÃO":
        return True
    if is_flight(event_type, title):
        return True
    return False


def extract_airport_code(event: dict) -> str | None:
    """Extract airport code from Reserva/Flight event."""
    location_code = event.get("location_code")
    if location_code:
        return str(location_code).upper()

    title = (event.get("clean_title") or "").strip()
    reserva_match = RESERVA_TITLE_RE.match(title)
    if reserva_match and reserva_match.group(1):
        return reserva_match.group(1).upper()

    flight_match = FLIGHT_TITLE_RE.match(title)
    if flight_match:
        # Departure airport is used as duty-start location.
        return flight_match.group(1).upper()

    return None


def travel_minutes_for_airport(code: str | None) -> int:
    """Return required travel/activation minutes by duty-start airport."""
    if code and code.upper() in MAJOR_BASES_150:
        return 150
    return 90


def infer_homebase_code(trigger: dict, duty_candidates: list[dict], duty_starts: list[datetime], until_utc: datetime) -> str | None:
    """
    Infer homebase from:
    1) Reserva location code, or
    2) first flight departure IATA code (XXX in "LA 1234 XXX - YYY")
    """
    if is_reserva(trigger.get("event_type"), trigger.get("clean_title")) or is_flight(
        trigger.get("event_type"), trigger.get("clean_title")
    ):
        code = extract_airport_code(trigger)
        if code:
            return code

    next_event = find_first_in_window(duty_candidates, duty_starts, trigger["start_utc"] + timedelta(seconds=1), until_utc)
    while next_event:
        if is_reserva(next_event.get("event_type"), next_event.get("clean_title")) or is_flight(
            next_event.get("event_type"), next_event.get("clean_title")
        ):
            code = extract_airport_code(next_event)
            if code:
                return code
        next_event = find_first_in_window(
            duty_candidates,
            duty_starts,
            next_event["start_utc"] + timedelta(seconds=1),
            until_utc,
        )

    return None


def load_standby_rows(cur, user_id: str, source_uid: str | None) -> list[dict]:
    """Load non-synthetic Sobreaviso events for one user."""
    if source_uid:
        cur.execute(
            """
            SELECT source_uid, event_type, clean_title, start_utc, end_utc
            FROM processed_events
            WHERE user_id = %s
              AND source_uid = %s
              AND is_synthetic = FALSE
              AND (clean_title = 'Sobreaviso' OR event_type = 'SOBREAVISO')
            ORDER BY start_utc
            """,
            (user_id, source_uid),
        )
    else:
        cur.execute(
            """
            SELECT source_uid, event_type, clean_title, start_utc, end_utc
            FROM processed_events
            WHERE user_id = %s
              AND is_synthetic = FALSE
              AND (clean_title = 'Sobreaviso' OR event_type = 'SOBREAVISO')
            ORDER BY start_utc
            """,
            (user_id,),
        )

    rows = []
    for source_uid, event_type, clean_title, start_utc, end_utc in cur.fetchall():
        rows.append(
            {
                "source_uid": source_uid,
                "event_type": event_type,
                "clean_title": clean_title,
                "start_utc": start_utc,
                "end_utc": end_utc,
            }
        )
    return rows


def load_events(cur, user_id: str) -> tuple[list[dict], list[dict]]:
    """Load events used to infer duty trigger and checkout after HSB."""
    cur.execute(
        """
        SELECT source_uid, event_type, clean_title, location_code, start_utc, end_utc, is_synthetic
        FROM processed_events
        WHERE user_id = %s
        ORDER BY start_utc
        """,
        (user_id,),
    )
    duty_candidates = []
    checkouts = []
    for source_uid, event_type, clean_title, location_code, start_utc, end_utc, is_synthetic in cur.fetchall():
        row = {
            "source_uid": source_uid,
            "event_type": event_type,
            "clean_title": clean_title,
            "location_code": location_code,
            "start_utc": start_utc,
            "end_utc": end_utc,
            "is_synthetic": is_synthetic,
        }
        if not is_synthetic and is_duty_trigger(row):
            duty_candidates.append(row)
        if is_synthetic and (clean_title or "").strip() == "Checkout":
            checkouts.append(row)

    return duty_candidates, checkouts


def find_first_in_window(events: list[dict], starts: list[datetime], from_utc: datetime, until_utc: datetime) -> dict | None:
    """Return first event in [from_utc, until_utc] by start time."""
    idx = bisect_left(starts, from_utc)
    while idx < len(events):
        event = events[idx]
        start_utc = event["start_utc"]
        if start_utc > until_utc:
            break
        if start_utc >= from_utc:
            return event
        idx += 1
    return None


def clear_previous_violations(cur, user_id: str, source_uid: str | None) -> int:
    """Delete old synthetic violation events created by this ruleset."""
    if source_uid:
        cur.execute(
            """
            DELETE FROM processed_events
            WHERE user_id = %s
              AND is_synthetic = TRUE
              AND source_uid LIKE %s
            """,
            (user_id, f"{source_uid}-hsb-violation-%"),
        )
    else:
        cur.execute(
            """
            DELETE FROM processed_events
            WHERE user_id = %s
              AND is_synthetic = TRUE
              AND source_uid LIKE '%%-hsb-violation-%%'
            """,
            (user_id,),
        )
    return cur.rowcount


def clear_previous_deslocamentos(cur, user_id: str, source_uid: str | None) -> int:
    """Delete old synthetic Deslocamento events created by this ruleset."""
    if source_uid:
        cur.execute(
            """
            DELETE FROM processed_events
            WHERE user_id = %s
              AND is_synthetic = TRUE
              AND source_uid LIKE %s
            """,
            (user_id, f"{source_uid}-hsb-deslocamento"),
        )
    else:
        cur.execute(
            """
            DELETE FROM processed_events
            WHERE user_id = %s
              AND is_synthetic = TRUE
              AND source_uid LIKE '%%-hsb-deslocamento'
            """,
            (user_id,),
        )
    return cur.rowcount


def upsert_violation_event(
    cur,
    user_id: str,
    source_uid: str,
    start_utc: datetime,
    end_utc: datetime,
    notes: str,
    rule_code: str,
):
    """Insert/update synthetic 'Violation!' event."""
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
            "VIOLATION",
            "Violation!",
            "Violation!",
            start_utc,
            end_utc,
            notes,
            None,
            None,
            True,
            json.dumps([{"rule": "hsb_violation", "code": rule_code, "at": now_utc().isoformat()}]),
            json.dumps(["#roquescript-created", "#synthetic", "#hsb-ruleset", "#violation"]),
            now_utc().replace(tzinfo=None),
        ),
    )


def upsert_deslocamento_event(
    cur,
    user_id: str,
    source_uid: str,
    start_utc: datetime,
    end_utc: datetime,
    notes: str,
):
    """Insert/update synthetic 'Deslocamento' event."""
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
            "TRAVEL",
            "Deslocamento",
            "Deslocamento",
            start_utc,
            end_utc,
            notes,
            None,
            None,
            True,
            json.dumps([{"rule": "hsb_deslocamento", "at": now_utc().isoformat()}]),
            json.dumps(["#roquescript-created", "#synthetic", "#hsb-ruleset", "#deslocamento"]),
            now_utc().replace(tzinfo=None),
        ),
    )


def build_violation_notes(rule_code: str, lines: list[str]) -> str:
    """Build notes text plus standardized roquescript metadata block."""
    base = "\n".join(lines)
    block = build_roquescript_block(
        "#roquescript #roquescript-created",
        [f"HSB violation detected: {rule_code}"],
        now_utc().isoformat(),
    )
    return append_roquescript_block(base, block)


def build_deslocamento_notes(lines: list[str]) -> str:
    """Build notes for a generated travel window."""
    base = "\n".join(lines)
    block = build_roquescript_block(
        "#roquescript #roquescript-created",
        ["HSB deslocamento window created"],
        now_utc().isoformat(),
    )
    return append_roquescript_block(base, block)


def main():
    # Safety gate: keep this script disabled unless explicitly enabled.
    if os.getenv("HSB_RULESET_ENABLED", "0").strip().lower() not in {"1", "true", "yes", "on"}:
        logger.info("hsb-ruleset is disabled. Set HSB_RULESET_ENABLED=1 to enable execution.")
        return

    parser = argparse.ArgumentParser(description="HSB/Sobreaviso violation checker")
    parser.add_argument("--user-id", default=USER_ID, help="User id")
    parser.add_argument("--source-uid", default=None, help="Optional specific Sobreaviso source_uid")
    args = parser.parse_args()

    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()

        standby_rows = load_standby_rows(cur, args.user_id, args.source_uid)
        duty_candidates, checkout_events = load_events(cur, args.user_id)
        duty_starts = [e["start_utc"] for e in duty_candidates]
        checkout_starts = [e["start_utc"] for e in checkout_events]

        cleared = clear_previous_violations(cur, args.user_id, args.source_uid)
        cleared_desloc = clear_previous_deslocamentos(cur, args.user_id, args.source_uid)
        logger.info(f"hsb-ruleset: cleared {cleared} prior violations and {cleared_desloc} deslocamentos")

        monthly_counts: dict[str, int] = {}
        stats = {
            "standby_checked": 0,
            "violations_created": 0,
            "deslocamentos_created": 0,
            "violations_by_rule": {},
        }

        for standby in standby_rows:
            stats["standby_checked"] += 1
            standby_uid = standby["source_uid"]
            standby_start = standby["start_utc"]
            standby_end = standby["end_utc"]

            hsb_window_end = standby_start + timedelta(hours=24)
            trigger_lookup_start = standby_end + timedelta(minutes=1)
            trigger = find_first_in_window(duty_candidates, duty_starts, trigger_lookup_start, hsb_window_end)
            if trigger and trigger["source_uid"] == standby_uid:
                trigger = find_first_in_window(
                    duty_candidates,
                    duty_starts,
                    trigger["start_utc"] + timedelta(seconds=1),
                    hsb_window_end,
                )

            homebase_code = infer_homebase_code(trigger, duty_candidates, duty_starts, hsb_window_end) if trigger else None
            travel_minutes = travel_minutes_for_airport(homebase_code)
            activation_utc = trigger["start_utc"] - timedelta(minutes=travel_minutes) if trigger else None

            if activation_utc and activation_utc < standby_end:
                effective_standby_end = activation_utc
            else:
                effective_standby_end = standby_end

            effective_hours = hours_between(standby_start, effective_standby_end)
            violation_specs: list[tuple[str, datetime, list[str]]] = []

            if trigger:
                desloc_start = standby_end + timedelta(minutes=1)
                desloc_end = desloc_start + timedelta(minutes=travel_minutes)
                desloc_uid = f"{standby_uid}-hsb-deslocamento"
                desloc_notes = build_deslocamento_notes(
                    [
                        "Deslocamento created from Sobreaviso end to duty mobilization window.",
                        f"source_uid={standby_uid}",
                        f"trigger_uid={trigger['source_uid']}",
                        f"trigger_title={trigger['clean_title']}",
                        f"homebase_code={homebase_code or 'UNKNOWN'}",
                        f"travel_minutes={travel_minutes}",
                        f"desloc_start_brt={fmt_brt(desloc_start)}",
                        f"desloc_end_brt={fmt_brt(desloc_end)}",
                    ],
                )
                upsert_deslocamento_event(
                    cur,
                    args.user_id,
                    desloc_uid,
                    desloc_start,
                    desloc_end,
                    desloc_notes,
                )
                stats["deslocamentos_created"] += 1

                if trigger["start_utc"] < desloc_end:
                    violation_specs.append(
                        (
                            "duty_starts_before_deslocamento_end",
                            standby_end,
                            [
                                "HSB travel violation: next duty starts before Deslocamento end.",
                                f"source_uid={standby_uid}",
                                f"trigger_uid={trigger['source_uid']}",
                                f"trigger_title={trigger['clean_title']}",
                                f"homebase_code={homebase_code or 'UNKNOWN'}",
                                f"travel_minutes_required={travel_minutes}",
                                f"duty_start_brt={fmt_brt(trigger['start_utc'])}",
                                f"desloc_end_brt={fmt_brt(desloc_end)}",
                            ],
                        )
                    )

            # Rule 1: standby duration must be between 3h and 12h.
            if effective_hours < MIN_STANDBY_HOURS:
                violation_specs.append(
                    (
                        "duration_below_minimum",
                        standby_end,
                        [
                            "HSB duration violation: effective standby is below 3 hours.",
                            f"source_uid={standby_uid}",
                            f"effective_hours={effective_hours:.2f}",
                            f"standby_start_brt={fmt_brt(standby_start)}",
                            f"effective_end_brt={fmt_brt(effective_standby_end)}",
                        ],
                    )
                )
            if effective_hours > MAX_STANDBY_HOURS:
                violation_specs.append(
                    (
                        "duration_above_maximum",
                        standby_end,
                        [
                            "HSB duration violation: effective standby exceeds 12 hours.",
                            f"source_uid={standby_uid}",
                            f"effective_hours={effective_hours:.2f}",
                            f"standby_start_brt={fmt_brt(standby_start)}",
                            f"effective_end_brt={fmt_brt(effective_standby_end)}",
                        ],
                    )
                )

            # Rule 2: max 8 Sobreaviso in month (BRT month of standby start).
            month_key = to_brt(standby_start).strftime("%Y-%m")
            monthly_counts[month_key] = monthly_counts.get(month_key, 0) + 1
            if monthly_counts[month_key] > MAX_MONTHLY_STANDBY:
                violation_specs.append(
                    (
                        "monthly_limit_exceeded",
                        standby_end,
                        [
                            "HSB monthly limit violation: more than 8 standby duties in month.",
                            f"source_uid={standby_uid}",
                            f"month={month_key}",
                            f"count_in_month={monthly_counts[month_key]}",
                            "limit=8",
                        ],
                    )
                )

            # Rule 3: after HSB, total window to Checkout (or Reserva start fallback) cannot exceed 16h.
            if trigger:
                checkout = find_first_in_window(checkout_events, checkout_starts, trigger["start_utc"], hsb_window_end)
                if checkout:
                    control_end = checkout["start_utc"]
                    control_anchor = checkout["start_utc"]
                    control_label = "Checkout"
                    control_uid = checkout["source_uid"]
                elif is_reserva(trigger.get("event_type"), trigger.get("clean_title")):
                    control_end = trigger["start_utc"]
                    control_anchor = trigger["start_utc"]
                    control_label = "Reserva start (fallback, no Checkout)"
                    control_uid = trigger["source_uid"]
                else:
                    control_end = None
                    control_anchor = None
                    control_label = None
                    control_uid = None

                if control_end and control_end > standby_start:
                    total_hours = hours_between(standby_start, control_end)
                    if total_hours > MAX_TOTAL_HOURS_AFTER_HSB:
                        violation_specs.append(
                            (
                                "total_window_above_16h",
                                control_anchor,
                                [
                                    "HSB duty-window violation: total time from HSB start exceeds 16 hours.",
                                    f"source_uid={standby_uid}",
                                    f"reference_event={control_label}",
                                    f"reference_uid={control_uid}",
                                    f"hsb_start_brt={fmt_brt(standby_start)}",
                                    f"reference_time_brt={fmt_brt(control_end)}",
                                    f"total_hours={total_hours:.2f}",
                                    "limit_hours=16",
                                ],
                            )
                        )

            for rule_code, violating_anchor_utc, note_lines in violation_specs:
                violation_uid = f"{standby_uid}-hsb-violation-{rule_code}"
                violation_start = violating_anchor_utc + timedelta(minutes=1)
                violation_end = violation_start + timedelta(minutes=10)
                notes = build_violation_notes(rule_code, note_lines)
                upsert_violation_event(
                    cur,
                    args.user_id,
                    violation_uid,
                    violation_start,
                    violation_end,
                    notes,
                    rule_code,
                )
                stats["violations_created"] += 1
                stats["violations_by_rule"][rule_code] = stats["violations_by_rule"].get(rule_code, 0) + 1

        conn.commit()
        cur.close()
        logger.info(
            "hsb-ruleset complete: "
            f"standby_checked={stats['standby_checked']}, "
            f"deslocamentos_created={stats['deslocamentos_created']}, "
            f"violations_created={stats['violations_created']}, "
            f"violations_by_rule={json.dumps(stats['violations_by_rule'])}"
        )
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    main()
