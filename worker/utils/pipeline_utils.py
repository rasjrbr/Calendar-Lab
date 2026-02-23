"""
Shared helpers and constants used across multiple pipeline stages.

Consolidates duplicated logic for:
- BRT timezone conversion
- Interval overlap detection
- Standby window loading and overlap checks
- Duty limit table lookups
- Flight leg classification
"""

import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

TZ_BRT = ZoneInfo("America/Sao_Paulo")

# --- Flight classification regexes ---
FLIGHT_LEG_RE = re.compile(r"^LA\s*\d{3,4}\s+[A-Z]{3}\s*-\s*[A-Z]{3}$", re.IGNORECASE)
INTERNATIONAL_LEG_RE = re.compile(r"^LA\s*(8\d{3}|\d{3}(?!\d))\s+[A-Z]{3}\s*-\s*[A-Z]{3}$", re.IGNORECASE)
HYBRID_9XXX_RE = re.compile(r"^LA\s*9\d{2,3}\s+[A-Z]{3}\s*-\s*[A-Z]{3}$", re.IGNORECASE)

# --- Duty limit lookup tables ---
HOUR_MAP = {
    0: "18:00-05:59", 1: "18:00-05:59", 2: "18:00-05:59", 3: "18:00-05:59",
    4: "18:00-05:59", 5: "18:00-05:59", 6: "06:00-06:59", 7: "07:00-07:59",
    8: "08:00-11:59", 9: "08:00-11:59", 10: "08:00-11:59", 11: "08:00-11:59",
    12: "12:00-13:59", 13: "12:00-13:59", 14: "14:00-15:59", 15: "14:00-15:59",
    16: "16:00-17:59", 17: "16:00-17:59", 18: "18:00-05:59", 19: "18:00-05:59",
    20: "18:00-05:59", 21: "18:00-05:59", 22: "18:00-05:59", 23: "18:00-05:59",
}

DUTY_LIMIT_TABLE = {
    "06:00-06:59": {"1-2": 11, "3-4": 11, "5": 10, "6": 9, "7+": 9},
    "07:00-07:59": {"1-2": 12, "3-4": 12, "5": 11, "6": 10, "7+": 9},
    "08:00-11:59": {"1-2": 12, "3-4": 12, "5": 12, "6": 11, "7+": 10},
    "12:00-13:59": {"1-2": 12, "3-4": 12, "5": 11, "6": 10, "7+": 9},
    "14:00-15:59": {"1-2": 11, "3-4": 11, "5": 10, "6": 9, "7+": 9},
    "16:00-17:59": {"1-2": 10, "3-4": 10, "5": 9, "6": 9, "7+": 9},
    "18:00-05:59": {"1-2": 9, "3-4": 9, "5": 9, "6": 9, "7+": 9},
}


def to_brt(utc_naive: datetime) -> datetime:
    """Convert UTC naive timestamp from DB to aware BRT datetime."""
    return utc_naive.replace(tzinfo=timezone.utc).astimezone(TZ_BRT)


def intervals_overlap(start_a: datetime, end_a: datetime, start_b: datetime, end_b: datetime) -> bool:
    """Return True when two [start, end) windows overlap."""
    return start_a < end_b and end_a > start_b


def legs_bucket(legs_count: int) -> str:
    """Map integer leg count to duty limit table column key."""
    if legs_count <= 2:
        return "1-2"
    if legs_count <= 4:
        return "3-4"
    if legs_count == 5:
        return "5"
    if legs_count == 6:
        return "6"
    return "7+"


def detect_leg(title: str) -> tuple[bool, bool, bool]:
    """
    Detect if title is a valid flight leg and classify special categories.

    Returns:
        (is_leg, is_international_8xxx_or_3digit, is_hybrid_9xxx)
    """
    if not title:
        return False, False, False
    clean = title.strip()
    if not FLIGHT_LEG_RE.match(clean):
        return False, False, False
    is_international = bool(INTERNATIONAL_LEG_RE.match(clean))
    is_hybrid_9 = bool(HYBRID_9XXX_RE.match(clean))
    return True, is_international, is_hybrid_9


def load_standby_windows(cur, user_id: str) -> list[tuple[str, datetime, datetime]]:
    """Load Reserva/Sobreaviso windows from processed_events."""
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
    return cur.fetchall()


def apresentacao_overlaps_standby(
    ap_source_uid: str,
    ap_start_utc: datetime,
    ap_end_utc: datetime,
    standby_windows: list[tuple[str, datetime, datetime]],
) -> bool:
    """Return True if Apresentação overlaps any Reserva/Sobreaviso window."""
    for standby_uid, standby_start, standby_end in standby_windows:
        if standby_uid == ap_source_uid:
            continue
        if intervals_overlap(ap_start_utc, ap_end_utc, standby_start, standby_end):
            return True
    return False
