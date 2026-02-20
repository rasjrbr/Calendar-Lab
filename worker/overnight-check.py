"""
Overnight operation checker (Madrugada).

Rules enforced over processed events:
1) Max 2 consecutive overnight duties.
   - 3rd consecutive: mark first flight in that duty with "(Madrugada 3!)".
   - 4th+ consecutive: create "Violation!".
2) After 2 consecutive overnight duties, next-day Apresentação must be >= 08:00 (BRT).
3) Max 4 overnight duties in any rolling 168-hour window.
4) Once 4 overnights exist in a 168-hour window, total programmed duty days in that
   window cannot exceed 5 (flight / reserva / sobreaviso / apresentação).
5) Counters reset only with >= 48h rest that includes >= 2 full local nights (22:00-06:00)
   and no activity in that gap.
6) If acclimatization is UNKNOWN, overnight counters are excluded.
"""

import os
import re
import json
import argparse
from bisect import bisect_left
from datetime import datetime, date, time, timedelta, timezone
from zoneinfo import ZoneInfo

from utils.db_utils import get_connection
from utils.logging_utils import setup_logging
from utils.notes_utils import append_roquescript_block, build_roquescript_block
from utils.timezone_utils import now_utc

logger = setup_logging(__name__)

USER_ID = os.getenv("USER_ID", "roque")
ACCLIMATIZATION_STATUS = (os.getenv("ACCLIMATIZATION_STATUS", "ACCLIMATED") or "ACCLIMATED").strip().upper()
TZ_BRT = ZoneInfo("America/Sao_Paulo")

VIOLATION_DURATION_MIN = 10
OVERNIGHT_WINDOW_START_HOUR = 0
OVERNIGHT_WINDOW_END_HOUR = 6
RECOVERY_MIN_REPORT_HOUR = 8
ROLLING_HOURS = 168
ROLLING_MAX_OVERNIGHTS = 4
ROLLING_MAX_DUTY_DAYS = 5
RESET_MIN_HOURS = 48
MADRUGADA3_SUFFIX = " (Madrugada 3!)"

FLIGHT_TITLE_RE = re.compile(r"^LA\s*\d{3,4}\s+[A-Z]{3}\s*-\s*[A-Z]{3}$", re.IGNORECASE)


def to_brt(utc_naive: datetime) -> datetime:
    """Convert naive UTC datetime (DB) to aware BRT datetime."""
    return utc_naive.replace(tzinfo=timezone.utc).astimezone(TZ_BRT)


def fmt_brt(utc_naive: datetime) -> str:
    """Format UTC-naive datetime in BRT."""
    return to_brt(utc_naive).strftime("%Y-%m-%d %H:%M")


def parse_json_list(value) -> list:
    """Normalize JSONB field value to list."""
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            loaded = json.loads(value)
            if isinstance(loaded, list):
                return loaded
        except Exception:
            return []
    return []


def is_reserva(event_type: str | None, clean_title: str | None) -> bool:
    title = (clean_title or "").strip()
    return (event_type or "").upper() == "RESERVA" or title.startswith("Reserva")


def is_sobreaviso(event_type: str | None, clean_title: str | None) -> bool:
    title = (clean_title or "").strip()
    return (event_type or "").upper() == "SOBREAVISO" or title == "Sobreaviso"


def is_apresentacao(event_type: str | None, clean_title: str | None) -> bool:
    title = (clean_title or "").strip()
    return title == "Apresentação" or (event_type or "").upper() == "APRESENTAÇÃO"


def is_flight(event_type: str | None, clean_title: str | None) -> bool:
    title = (clean_title or "").strip()
    return bool(FLIGHT_TITLE_RE.match(title)) or (event_type or "").upper() == "FLIGHT"


def is_programming_duty_event(event: dict) -> bool:
    """Duty-day contributors for Rule #4."""
    return (
        is_flight(event["event_type"], event["clean_title"])
        or is_reserva(event["event_type"], event["clean_title"])
        or is_sobreaviso(event["event_type"], event["clean_title"])
        or is_apresentacao(event["event_type"], event["clean_title"])
    )


def overlaps_overnight_window(report_utc: datetime, release_utc: datetime) -> bool:
    """
    Overnight if [report, release) overlaps any local window [00:00, 06:00).
    """
    if release_utc <= report_utc:
        return False

    report_local = to_brt(report_utc)
    release_local = to_brt(release_utc)
    start_date = report_local.date() - timedelta(days=1)
    end_date = release_local.date() + timedelta(days=1)

    day = start_date
    while day <= end_date:
        window_start = datetime.combine(day, time(hour=OVERNIGHT_WINDOW_START_HOUR), tzinfo=TZ_BRT)
        window_end = datetime.combine(day, time(hour=OVERNIGHT_WINDOW_END_HOUR), tzinfo=TZ_BRT)
        if report_local < window_end and release_local > window_start:
            return True
        day += timedelta(days=1)
    return False


def count_full_local_nights_in_gap(gap_start_utc: datetime, gap_end_utc: datetime) -> int:
    """
    Count full local-night windows [22:00,06:00] fully contained in gap.
    """
    if gap_end_utc <= gap_start_utc:
        return 0

    gap_start_local = to_brt(gap_start_utc)
    gap_end_local = to_brt(gap_end_utc)
    day = gap_start_local.date() - timedelta(days=1)
    last_day = gap_end_local.date() + timedelta(days=1)
    count = 0

    while day <= last_day:
        night_start = datetime.combine(day, time(hour=22), tzinfo=TZ_BRT)
        night_end = datetime.combine(day + timedelta(days=1), time(hour=6), tzinfo=TZ_BRT)
        if gap_start_local <= night_start and gap_end_local >= night_end:
            count += 1
        day += timedelta(days=1)
    return count


def has_activity_between(activity_events: list[dict], start_utc: datetime, end_utc: datetime) -> bool:
    """Return True if any non-synthetic event overlaps (start_utc, end_utc)."""
    for event in activity_events:
        if event["end_utc"] <= start_utc:
            continue
        if event["start_utc"] >= end_utc:
            break
        if event["start_utc"] < end_utc and event["end_utc"] > start_utc:
            return True
    return False


def qualifies_reset(activity_events: list[dict], gap_start_utc: datetime, gap_end_utc: datetime) -> bool:
    """Rule #5 reset condition."""
    gap_hours = (gap_end_utc - gap_start_utc).total_seconds() / 3600.0
    if gap_hours < RESET_MIN_HOURS:
        return False
    if has_activity_between(activity_events, gap_start_utc, gap_end_utc):
        return False
    return count_full_local_nights_in_gap(gap_start_utc, gap_end_utc) >= 2


def build_notes(base_lines: list[str], block_line: str) -> str:
    """Build notes text plus standardized roquescript block."""
    base = "\n".join(base_lines)
    block = build_roquescript_block(
        "#roquescript #roquescript-created",
        [block_line],
        now_utc().isoformat(),
    )
    return append_roquescript_block(base, block)


def clear_previous_violation_events(cur, user_id: str) -> int:
    """Clear prior synthetic overnight violation events."""
    cur.execute(
        """
        DELETE FROM processed_events
        WHERE user_id = %s
          AND is_synthetic = TRUE
          AND source_uid LIKE '%%-overnight-violation-%%'
        """,
        (user_id,),
    )
    return cur.rowcount


def load_events(cur, user_id: str) -> list[dict]:
    """Load all processed events with fields needed by this checker."""
    cur.execute(
        """
        SELECT
            id,
            source_uid,
            event_type,
            clean_title,
            start_utc,
            end_utc,
            is_synthetic,
            notes,
            notes_original,
            modifications,
            tags
        FROM processed_events
        WHERE user_id = %s
        ORDER BY start_utc, end_utc, id
        """,
        (user_id,),
    )
    rows = []
    for row in cur.fetchall():
        (
            event_id,
            source_uid,
            event_type,
            clean_title,
            start_utc,
            end_utc,
            is_synthetic,
            notes,
            notes_original,
            modifications,
            tags,
        ) = row
        rows.append(
            {
                "id": event_id,
                "source_uid": source_uid,
                "event_type": event_type,
                "clean_title": clean_title,
                "start_utc": start_utc,
                "end_utc": end_utc,
                "is_synthetic": bool(is_synthetic),
                "notes": notes,
                "notes_original": notes_original,
                "modifications": modifications,
                "tags": tags,
            }
        )
    return rows


def upsert_violation_event(cur, user_id: str, source_uid: str, start_utc: datetime, notes: str, rule_code: str):
    """Create/update synthetic Violation! event."""
    end_utc = start_utc + timedelta(minutes=VIOLATION_DURATION_MIN)
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
            json.dumps([{"rule": "overnight_violation", "code": rule_code, "at": now_utc().isoformat()}]),
            json.dumps(["#roquescript-created", "#synthetic", "#overnight-check", "#violation"]),
            now_utc().replace(tzinfo=None),
        ),
    )


def update_flight_title(cur, event: dict, new_title: str, note_line: str):
    """Update flight clean_title and append modification metadata."""
    modifications = parse_json_list(event["modifications"])
    tags = parse_json_list(event["tags"])
    if "#roquescript-modified" not in tags:
        tags.append("#roquescript-modified")

    modifications.append(
        {
            "rule": "overnight_madrugada3_title",
            "from": event["clean_title"],
            "to": new_title,
            "at": now_utc().isoformat(),
        }
    )

    block = build_roquescript_block(
        "#roquescript #roquescript-modified",
        [note_line],
        now_utc().isoformat(),
    )
    notes_updated = append_roquescript_block(event["notes"], block)

    cur.execute(
        """
        UPDATE processed_events
        SET clean_title = %s,
            notes = %s,
            modifications = %s,
            tags = %s,
            processed_at = %s
        WHERE id = %s
        """,
        (
            new_title,
            notes_updated,
            json.dumps(modifications),
            json.dumps(tags),
            now_utc().replace(tzinfo=None),
            event["id"],
        ),
    )


def find_first_flight_in_interval(events: list[dict], starts: list[datetime], start_utc: datetime, end_utc: datetime) -> dict | None:
    """Find first flight event with start in [start_utc, end_utc]."""
    idx = bisect_left(starts, start_utc)
    while idx < len(events):
        event = events[idx]
        if event["start_utc"] > end_utc:
            break
        if is_flight(event["event_type"], event["clean_title"]):
            return event
        idx += 1
    return None


def main():
    parser = argparse.ArgumentParser(description="Overnight operation checker")
    parser.add_argument("--user-id", default=USER_ID, help="User id")
    args = parser.parse_args()

    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()

        events = load_events(cur, args.user_id)
        nonsynth = [e for e in events if not e["is_synthetic"]]
        nonsynth_starts = [e["start_utc"] for e in nonsynth]

        cleared = clear_previous_violation_events(cur, args.user_id)
        stats = {
            "events_loaded": len(events),
            "overnight_duties": 0,
            "violations_created": 0,
            "madrugada3_marked": 0,
            "madrugada3_unmarked": 0,
            "violations_by_rule": {},
            "cleared_violations": cleared,
        }

        # Build overnight duty objects from Apresentação + synthetic Checkout pair.
        checkouts = {
            e["source_uid"]: e
            for e in events
            if e["is_synthetic"] and (e["clean_title"] or "").strip() == "Checkout"
        }
        apresentacoes = [
            e
            for e in nonsynth
            if is_apresentacao(e["event_type"], e["clean_title"])
        ]
        apresentacoes_by_date: dict[date, list[dict]] = {}
        overnight_duties = []

        for ap in apresentacoes:
            ap_day = to_brt(ap["start_utc"]).date()
            apresentacoes_by_date.setdefault(ap_day, []).append(ap)

            checkout = checkouts.get(f"{ap['source_uid']}-checkout-synthetic")
            if not checkout:
                continue
            release_utc = checkout["start_utc"]
            if release_utc <= ap["start_utc"]:
                continue
            if overlaps_overnight_window(ap["start_utc"], release_utc):
                overnight_duties.append(
                    {
                        "ap": ap,
                        "checkout": checkout,
                        "report_utc": ap["start_utc"],
                        "release_utc": release_utc,
                        "report_date_brt": to_brt(ap["start_utc"]).date(),
                    }
                )

        overnight_duties.sort(key=lambda d: d["report_utc"])
        stats["overnight_duties"] = len(overnight_duties)

        # Rule #6: UNKNOWN acclimatization excludes overnight counting.
        if ACCLIMATIZATION_STATUS == "UNKNOWN":
            # Keep existing schedule clean by removing stale Madrugada marker when not counting.
            flight_rows = [e for e in nonsynth if is_flight(e["event_type"], e["clean_title"])]
            for flight in flight_rows:
                title = (flight["clean_title"] or "").strip()
                if title.endswith(MADRUGADA3_SUFFIX):
                    update_flight_title(
                        cur,
                        flight,
                        title[: -len(MADRUGADA3_SUFFIX)].rstrip(),
                        "Madrugada 3 marker removed (acclimatization UNKNOWN).",
                    )
                    stats["madrugada3_unmarked"] += 1
            conn.commit()
            cur.close()
            logger.info(
                "overnight-check complete (excluded by acclimatization): "
                f"events_loaded={stats['events_loaded']}, "
                f"cleared_violations={stats['cleared_violations']}, "
                f"madrugada3_unmarked={stats['madrugada3_unmarked']}"
            )
            return

        # Rule processing.
        created_uids: set[str] = set()
        rolling_queue: list[dict] = []
        streak_count = 0
        prev_duty = None
        target_madrugada_flight_uids: set[str] = set()

        duty_day_events = [e for e in nonsynth if is_programming_duty_event(e)]

        def create_violation(rule_code: str, anchor_event: dict, lines: list[str]):
            violation_uid = f"{anchor_event['source_uid']}-overnight-violation-{rule_code}"
            if violation_uid in created_uids:
                return
            start_utc = anchor_event["end_utc"] + timedelta(minutes=1)
            notes = build_notes(lines, f"Overnight violation detected: {rule_code}")
            upsert_violation_event(cur, args.user_id, violation_uid, start_utc, notes, rule_code)
            created_uids.add(violation_uid)
            stats["violations_created"] += 1
            stats["violations_by_rule"][rule_code] = stats["violations_by_rule"].get(rule_code, 0) + 1

        for duty in overnight_duties:
            # Rule #5 reset.
            if prev_duty and qualifies_reset(nonsynth, prev_duty["release_utc"], duty["report_utc"]):
                streak_count = 0
                rolling_queue = []

            # Rule #1 consecutive streak.
            if prev_duty and duty["report_date_brt"] == (prev_duty["report_date_brt"] + timedelta(days=1)):
                streak_count += 1
            else:
                streak_count = 1

            if streak_count == 3:
                flight = find_first_flight_in_interval(
                    nonsynth,
                    nonsynth_starts,
                    duty["report_utc"],
                    duty["release_utc"],
                )
                if flight:
                    target_madrugada_flight_uids.add(flight["source_uid"])
            elif streak_count > 3:
                create_violation(
                    "rule1_consecutive_over_3",
                    duty["ap"],
                    [
                        "Consecutive overnight limit exceeded.",
                        f"streak={streak_count}",
                        f"report_brt={fmt_brt(duty['report_utc'])}",
                    ],
                )

            # Rule #2 recovery day after second overnight.
            if streak_count >= 2:
                next_day = duty["report_date_brt"] + timedelta(days=1)
                next_day_reports = apresentacoes_by_date.get(next_day, [])
                for report in next_day_reports:
                    report_hour = to_brt(report["start_utc"]).hour
                    if report_hour < RECOVERY_MIN_REPORT_HOUR:
                        create_violation(
                            "rule2_report_before_0800",
                            report,
                            [
                                "Recovery rest violation after consecutive overnight duties.",
                                "Next-day Apresentação must be after 08:00 BRT.",
                                f"report_brt={fmt_brt(report['start_utc'])}",
                            ],
                        )

            # Rule #3 rolling 168h overnight max 4.
            rolling_queue.append(duty)
            cutoff = duty["report_utc"] - timedelta(hours=ROLLING_HOURS)
            while rolling_queue and rolling_queue[0]["report_utc"] < cutoff:
                rolling_queue.pop(0)

            rolling_count = len(rolling_queue)
            if rolling_count > ROLLING_MAX_OVERNIGHTS:
                create_violation(
                    "rule3_rolling_168h_overnights",
                    duty["ap"],
                    [
                        "Rolling 168h overnight limit exceeded.",
                        f"rolling_overnights={rolling_count}",
                        f"window_start_brt={fmt_brt(cutoff)}",
                        f"window_end_brt={fmt_brt(duty['report_utc'])}",
                    ],
                )

            # Rule #4: if 4 overnight reached in window, programming day cap is 5.
            if rolling_count >= ROLLING_MAX_OVERNIGHTS:
                window_start = duty["report_utc"] - timedelta(hours=ROLLING_HOURS)
                window_end = duty["report_utc"]
                duty_days = {
                    to_brt(e["start_utc"]).date()
                    for e in duty_day_events
                    if e["start_utc"] >= window_start and e["start_utc"] <= window_end
                }
                if len(duty_days) > ROLLING_MAX_DUTY_DAYS:
                    create_violation(
                        "rule4_programming_day_cap",
                        duty["ap"],
                        [
                            "Programming day cap exceeded after 4 overnight duties in 168h.",
                            f"duty_days_in_window={len(duty_days)}",
                            f"window_start_brt={fmt_brt(window_start)}",
                            f"window_end_brt={fmt_brt(window_end)}",
                        ],
                    )

            prev_duty = duty

        # Apply Madrugada 3 markers idempotently.
        flight_rows = [e for e in nonsynth if is_flight(e["event_type"], e["clean_title"])]
        for flight in flight_rows:
            uid = flight["source_uid"]
            title = (flight["clean_title"] or "").strip()
            has_suffix = title.endswith(MADRUGADA3_SUFFIX)
            should_have = uid in target_madrugada_flight_uids

            if should_have and not has_suffix:
                update_flight_title(
                    cur,
                    flight,
                    f"{title}{MADRUGADA3_SUFFIX}",
                    "Flight marked as Madrugada 3! (deadheading verification required).",
                )
                stats["madrugada3_marked"] += 1
            elif not should_have and has_suffix:
                update_flight_title(
                    cur,
                    flight,
                    title[: -len(MADRUGADA3_SUFFIX)].rstrip(),
                    "Madrugada 3 marker removed by overnight-check recompute.",
                )
                stats["madrugada3_unmarked"] += 1

        conn.commit()
        cur.close()
        logger.info(
            "overnight-check complete: "
            f"events_loaded={stats['events_loaded']}, "
            f"overnight_duties={stats['overnight_duties']}, "
            f"cleared_violations={stats['cleared_violations']}, "
            f"violations_created={stats['violations_created']}, "
            f"madrugada3_marked={stats['madrugada3_marked']}, "
            f"madrugada3_unmarked={stats['madrugada3_unmarked']}, "
            f"violations_by_rule={json.dumps(stats['violations_by_rule'])}"
        )
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    main()
