"""
Dummy, in-memory HSB ruleset simulation for one specific scenario.

Scenario date: Wednesday, 2026-02-18 (BRT)
- Sobreaviso
- Reserva em CGH (trigger)
- Expected: Deslocamento is created
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from bisect import bisect_left
from datetime import datetime, timedelta, timezone, date as dt_date
from zoneinfo import ZoneInfo

from utils.db_utils import get_connection

TZ_BRT = ZoneInfo("America/Sao_Paulo")
MAJOR_BASES_148 = {"GRU", "CGH", "GIG", "SDU"}
MIN_STANDBY_HOURS = 3
MAX_STANDBY_HOURS = 12
MAX_TOTAL_HOURS_AFTER_HSB = 16
USER_ID = os.getenv("USER_ID", "roque")

FLIGHT_TITLE_RE = re.compile(r"^LA\s*\d{3,4}\s+([A-Z]{3})\s*-\s*([A-Z]{3})$", re.IGNORECASE)
RESERVA_TITLE_RE = re.compile(r"^Reserva(?:\s+em\s+([A-Z]{2,4}))?$", re.IGNORECASE)


def brt_to_utc_naive(brt_text: str) -> datetime:
    dt_brt = datetime.strptime(brt_text, "%Y-%m-%d %H:%M").replace(tzinfo=TZ_BRT)
    return dt_brt.astimezone(timezone.utc).replace(tzinfo=None)


def to_brt(utc_naive: datetime) -> datetime:
    return utc_naive.replace(tzinfo=timezone.utc).astimezone(TZ_BRT)


def fmt_brt(utc_naive: datetime) -> str:
    return to_brt(utc_naive).strftime("%Y-%m-%d %H:%M")


def fmt_utc(utc_naive: datetime) -> str:
    return utc_naive.strftime("%Y-%m-%d %H:%M:%S")


def brt_day_bounds_to_utc_naive(day_brt: dt_date) -> tuple[datetime, datetime]:
    start_brt = datetime(day_brt.year, day_brt.month, day_brt.day, 0, 0, tzinfo=TZ_BRT)
    end_brt = start_brt + timedelta(days=1)
    start_utc = start_brt.astimezone(timezone.utc).replace(tzinfo=None)
    end_utc = end_brt.astimezone(timezone.utc).replace(tzinfo=None)
    return start_utc, end_utc


def hours_between(start_utc: datetime, end_utc: datetime) -> float:
    return (end_utc - start_utc).total_seconds() / 3600.0


def is_sobreaviso(event_type: str | None, clean_title: str | None) -> bool:
    return (clean_title or "").strip() == "Sobreaviso" or (event_type or "").upper() == "SOBREAVISO"


def is_reserva(event_type: str | None, clean_title: str | None) -> bool:
    title = (clean_title or "").strip()
    return (event_type or "").upper() == "RESERVA" or title.startswith("Reserva")


def is_flight(event_type: str | None, clean_title: str | None) -> bool:
    title = (clean_title or "").strip()
    return bool(FLIGHT_TITLE_RE.match(title)) or (event_type or "").upper() == "FLIGHT"


def is_duty_trigger(event: dict) -> bool:
    title = (event.get("clean_title") or "").strip()
    event_type = (event.get("event_type") or "").upper()
    if is_reserva(event_type, title):
        return True
    if title == "Apresentacao" or title == "Apresentação" or event_type in {"APRESENTACAO", "APRESENTAÇÃO"}:
        return True
    if is_flight(event_type, title):
        return True
    return False


def extract_airport_code(event: dict) -> str | None:
    location_code = event.get("location_code")
    if location_code:
        return str(location_code).upper()

    title = (event.get("clean_title") or "").strip()
    reserva_match = RESERVA_TITLE_RE.match(title)
    if reserva_match and reserva_match.group(1):
        return reserva_match.group(1).upper()

    flight_match = FLIGHT_TITLE_RE.match(title)
    if flight_match:
        return flight_match.group(1).upper()
    return None


def travel_minutes_for_airport(code: str | None) -> int:
    if code and code.upper() in MAJOR_BASES_148:
        return 148
    return 88


def find_first_in_window(events: list[dict], starts: list[datetime], from_utc: datetime, until_utc: datetime) -> dict | None:
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


def infer_homebase_code(trigger: dict, duty_candidates: list[dict], duty_starts: list[datetime], until_utc: datetime) -> str | None:
    if is_reserva(trigger.get("event_type"), trigger.get("clean_title")) or is_flight(
        trigger.get("event_type"),
        trigger.get("clean_title"),
    ):
        code = extract_airport_code(trigger)
        if code:
            return code

    next_event = find_first_in_window(duty_candidates, duty_starts, trigger["start_utc"] + timedelta(seconds=1), until_utc)
    while next_event:
        if is_reserva(next_event.get("event_type"), next_event.get("clean_title")) or is_flight(
            next_event.get("event_type"),
            next_event.get("clean_title"),
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


def build_dummy_events() -> list[dict]:
    # Wednesday, February 18, 2026 in BRT.
    return [
        {
            "source_uid": "dummy-hsb-2026-02-18",
            "event_type": "SOBREAVISO",
            "clean_title": "Sobreaviso",
            "location_code": None,
            "start_utc": brt_to_utc_naive("2026-02-18 08:00"),
            "end_utc": brt_to_utc_naive("2026-02-18 12:00"),
            "is_synthetic": False,
        },
        {
            "source_uid": "dummy-reserva-2026-02-18",
            "event_type": "RESERVA",
            "clean_title": "Reserva em CGH",
            "location_code": "CGH",
            "start_utc": brt_to_utc_naive("2026-02-18 14:40"),
            "end_utc": brt_to_utc_naive("2026-02-18 16:00"),
            "is_synthetic": False,
        },
    ]


def load_events_from_db_for_brt_day(user_id: str, day_brt: dt_date) -> list[dict]:
    start_utc, end_utc = brt_day_bounds_to_utc_naive(day_brt)
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT source_uid, event_type, clean_title, location_code, start_utc, end_utc, is_synthetic
            FROM processed_events
            WHERE user_id = %s
              AND start_utc >= %s
              AND start_utc < %s
            ORDER BY start_utc, source_uid
            """,
            (user_id, start_utc, end_utc),
        )
        rows = []
        for source_uid, event_type, clean_title, location_code, start_utc_val, end_utc_val, is_synthetic in cur.fetchall():
            rows.append(
                {
                    "source_uid": source_uid,
                    "event_type": event_type,
                    "clean_title": clean_title,
                    "location_code": location_code,
                    "start_utc": start_utc_val,
                    "end_utc": end_utc_val,
                    "is_synthetic": is_synthetic,
                }
            )
        return rows
    finally:
        cur.close()
        conn.close()


def run_dummy(events: list[dict] | None = None, scenario_date_brt: str = "2026-02-18", scenario_source: str = "hardcoded") -> dict:
    if events is None:
        events = build_dummy_events()

    standby_rows = [e for e in events if not e["is_synthetic"] and is_sobreaviso(e["event_type"], e["clean_title"])]
    duty_candidates = [e for e in events if not e["is_synthetic"] and is_duty_trigger(e)]
    checkout_events = [e for e in events if e["is_synthetic"] and (e.get("clean_title") or "").strip() == "Checkout"]

    duty_starts = [e["start_utc"] for e in duty_candidates]
    checkout_starts = [e["start_utc"] for e in checkout_events]

    monthly_counts: dict[str, int] = {}
    deslocamentos: list[dict] = []
    violations: list[dict] = []

    def add_violation(rule: str, source_uid: str, anchor_utc: datetime) -> None:
        violation_start = anchor_utc + timedelta(minutes=1)
        violation_end = violation_start + timedelta(minutes=10)
        violations.append(
            {
                "rule": rule,
                "source_uid": source_uid,
                "start_brt": fmt_brt(violation_start),
                "end_brt": fmt_brt(violation_end),
                "start_utc": fmt_utc(violation_start),
                "end_utc": fmt_utc(violation_end),
            }
        )

    for standby in standby_rows:
        standby_uid = standby["source_uid"]
        standby_start = standby["start_utc"]
        standby_end = standby["end_utc"]
        hsb_window_end = standby_start + timedelta(hours=24)

        trigger = find_first_in_window(
            duty_candidates,
            duty_starts,
            standby_end + timedelta(minutes=1),
            hsb_window_end,
        )
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
        effective_standby_end = activation_utc if activation_utc and activation_utc < standby_end else standby_end
        effective_hours = hours_between(standby_start, effective_standby_end)

        if trigger:
            desloc_start = standby_end + timedelta(minutes=1)
            desloc_end = desloc_start + timedelta(minutes=travel_minutes)
            deslocamentos.append(
                {
                    "source_uid": f"{standby_uid}-hsb-deslocamento",
                    "start_brt": fmt_brt(desloc_start),
                    "end_brt": fmt_brt(desloc_end),
                    "start_utc": fmt_utc(desloc_start),
                    "end_utc": fmt_utc(desloc_end),
                    "trigger_uid": trigger["source_uid"],
                    "homebase_code": homebase_code,
                    "travel_minutes": travel_minutes,
                }
            )
            if trigger["start_utc"] < desloc_end:
                add_violation("duty_starts_before_deslocamento_end", standby_uid, standby_end)

        if effective_hours < MIN_STANDBY_HOURS:
            add_violation("duration_below_minimum", standby_uid, standby_end)
        if effective_hours > MAX_STANDBY_HOURS:
            add_violation("duration_above_maximum", standby_uid, standby_end)

        month_key = to_brt(standby_start).strftime("%Y-%m")
        monthly_counts[month_key] = monthly_counts.get(month_key, 0) + 1
        if monthly_counts[month_key] > 8:
            add_violation("monthly_limit_exceeded", standby_uid, standby_end)

        if trigger:
            checkout = find_first_in_window(checkout_events, checkout_starts, trigger["start_utc"], hsb_window_end)
            if checkout:
                control_end = checkout["start_utc"]
            elif is_reserva(trigger.get("event_type"), trigger.get("clean_title")):
                control_end = trigger["start_utc"]
            else:
                control_end = None
            if control_end and control_end > standby_start:
                total_hours = hours_between(standby_start, control_end)
                if total_hours > MAX_TOTAL_HOURS_AFTER_HSB:
                    add_violation("total_window_above_16h", standby_uid, control_end)

    return {
        "scenario_source": scenario_source,
        "scenario_date_brt": scenario_date_brt,
        "scenario_weekday_brt": datetime.strptime(scenario_date_brt, "%Y-%m-%d").strftime("%A"),
        "input_events": [
            {
                "source_uid": e["source_uid"],
                "event_type": e["event_type"],
                "clean_title": e["clean_title"],
                "is_synthetic": e["is_synthetic"],
                "start_brt": fmt_brt(e["start_utc"]),
                "end_brt": fmt_brt(e["end_utc"]),
            }
            for e in events
        ],
        "deslocamentos_created": deslocamentos,
        "violations_created": violations,
    }


def cleanup_dummy_rows(cur, user_id: str) -> int:
    cur.execute(
        """
        DELETE FROM processed_events
        WHERE user_id = %s
          AND (
                source_uid LIKE 'dummy-hsb-%%-hsb-deslocamento'
             OR source_uid LIKE 'dummy-hsb-%%-hsb-violation-%%'
          )
        """,
        (user_id,),
    )
    return cur.rowcount


def upsert_dummy_event(
    cur,
    user_id: str,
    source_uid: str,
    event_type: str,
    title: str,
    start_utc: datetime,
    end_utc: datetime,
    notes: str,
    tags: list[str],
    modifications: list[dict],
) -> None:
    processed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    cur.execute(
        """
        INSERT INTO processed_events (
            user_id, source_uid, raw_event_id, event_type, original_title, clean_title,
            start_utc, end_utc, notes, is_synthetic, modifications, tags, processed_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (user_id, source_uid)
        DO UPDATE SET
            event_type = EXCLUDED.event_type,
            original_title = EXCLUDED.original_title,
            clean_title = EXCLUDED.clean_title,
            start_utc = EXCLUDED.start_utc,
            end_utc = EXCLUDED.end_utc,
            notes = EXCLUDED.notes,
            is_synthetic = EXCLUDED.is_synthetic,
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
            True,
            json.dumps(modifications),
            json.dumps(tags),
            processed_at,
        ),
    )


def apply_dummy_to_db(result: dict, user_id: str) -> dict:
    conn = get_connection()
    cur = conn.cursor()
    try:
        deleted = cleanup_dummy_rows(cur, user_id)
        upserted = 0

        for desloc in result.get("deslocamentos_created", []):
            source_uid = str(desloc["source_uid"])
            start_utc = datetime.strptime(desloc["start_utc"], "%Y-%m-%d %H:%M:%S")
            end_utc = datetime.strptime(desloc["end_utc"], "%Y-%m-%d %H:%M:%S")
            notes = (
                "Dummy HSB ruleset output (temporary test).\n"
                f"trigger_uid={desloc['trigger_uid']}\n"
                f"homebase_code={desloc.get('homebase_code')}\n"
                f"travel_minutes={desloc['travel_minutes']}\n"
                "source=hsb-ruleset-dummy.py"
            )
            upsert_dummy_event(
                cur,
                user_id,
                source_uid,
                "TRAVEL",
                "Deslocamento",
                start_utc,
                end_utc,
                notes,
                ["#roquescript-created", "#synthetic", "#hsb-ruleset-dummy", "#temporary"],
                [{"rule": "dummy_hsb_deslocamento", "at": datetime.now(timezone.utc).isoformat()}],
            )
            upserted += 1

        for violation in result.get("violations_created", []):
            source_uid = f"{violation['source_uid']}-hsb-violation-{violation['rule']}"
            start_utc = datetime.strptime(violation["start_utc"], "%Y-%m-%d %H:%M:%S")
            end_utc = datetime.strptime(violation["end_utc"], "%Y-%m-%d %H:%M:%S")
            notes = (
                "Dummy HSB ruleset output (temporary test).\n"
                f"rule={violation['rule']}\n"
                "source=hsb-ruleset-dummy.py"
            )
            upsert_dummy_event(
                cur,
                user_id,
                source_uid,
                "VIOLATION",
                "Violation!",
                start_utc,
                end_utc,
                notes,
                ["#roquescript-created", "#synthetic", "#hsb-ruleset-dummy", "#temporary"],
                [{"rule": "dummy_hsb_violation", "code": violation["rule"], "at": datetime.now(timezone.utc).isoformat()}],
            )
            upserted += 1

        conn.commit()
        return {"deleted_old_dummy_rows": deleted, "upserted_rows": upserted}
    finally:
        cur.close()
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Dummy HSB ruleset simulator")
    parser.add_argument("--user-id", default=USER_ID, help="Target user for temporary DB write")
    parser.add_argument("--apply-db", action="store_true", help="Write dummy output into processed_events (temporary)")
    parser.add_argument("--publish-ics", action="store_true", help="Run publish_ics.py after --apply-db")
    parser.add_argument("--cleanup-only", action="store_true", help="Remove previously written dummy rows and exit")
    parser.add_argument("--from-db-today", action="store_true", help="Use today's BRT events from processed_events instead of hardcoded sample")
    parser.add_argument("--from-db-date", default=None, help="Use a specific BRT date (YYYY-MM-DD) from processed_events")
    args = parser.parse_args()

    if args.cleanup_only:
        conn = get_connection()
        cur = conn.cursor()
        try:
            deleted = cleanup_dummy_rows(cur, args.user_id)
            conn.commit()
            print(json.dumps({"cleanup_only": True, "deleted_rows": deleted}, indent=2, ensure_ascii=True))
            return
        finally:
            cur.close()
            conn.close()

    if args.from_db_today and args.from_db_date:
        raise ValueError("Use only one of --from-db-today or --from-db-date.")

    scenario_source = "hardcoded"
    scenario_date_brt = "2026-02-18"
    events: list[dict] | None = None
    if args.from_db_today:
        day_brt = datetime.now(TZ_BRT).date()
        scenario_date_brt = day_brt.strftime("%Y-%m-%d")
        scenario_source = "db_today"
        events = load_events_from_db_for_brt_day(args.user_id, day_brt)
    elif args.from_db_date:
        day_brt = datetime.strptime(args.from_db_date, "%Y-%m-%d").date()
        scenario_date_brt = day_brt.strftime("%Y-%m-%d")
        scenario_source = "db_date"
        events = load_events_from_db_for_brt_day(args.user_id, day_brt)

    result = run_dummy(events=events, scenario_date_brt=scenario_date_brt, scenario_source=scenario_source)

    if args.apply_db:
        db_result = apply_dummy_to_db(result, args.user_id)
        result["db_write"] = db_result
        result["db_write"]["temporary_mode"] = True
        if args.publish_ics:
            subprocess.check_call(["python3", "/app/publish_ics.py"])
            result["db_write"]["publish_ics"] = "completed"

    print(json.dumps(result, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
