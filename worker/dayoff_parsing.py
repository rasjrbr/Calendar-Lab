"""
DayOffParsing Module.

Applies day-off specific removals in a dedicated stage:
1. Rule-based removals for OFF/DO/DR/DB/DH "at" patterns.
2. Removal by day-off codes loaded from config/day_off_codes.json.
"""

import os
import json
import re
from typing import Dict, Any

from utils.db_utils import get_connection
from utils.logging_utils import setup_logging

logger = setup_logging(__name__)

USER_ID = os.getenv("USER_ID", "roque")
APP_DIR = os.path.dirname(os.path.abspath(__file__))
DAY_OFF_CODES_PATH = os.path.join(APP_DIR, "config", "day_off_codes.json")
SUPPORTED_DAYOFF_MODES = {"remove", "timed", "all_day", "keep"}


def load_day_off_codes():
    """Load day-off codes from JSON config."""
    with open(DAY_OFF_CODES_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {code.upper() for code in data.keys()}


def ensure_settings_table_exists(conn, cur):
    """Create settings table if missing (for existing databases)."""
    cur.execute("SELECT to_regclass('public.user_parsing_settings')")
    exists = cur.fetchone()[0] is not None
    if exists:
        return
    try:
        cur.execute(
            """
            CREATE TABLE user_parsing_settings (
                id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
                user_id VARCHAR(100) NOT NULL UNIQUE,
                dayoff_mode VARCHAR(20) NOT NULL DEFAULT 'remove',
                dayoff_default_minutes INT,
                dayoff_per_code_minutes JSONB,
                settings_version INT NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
            """
        )
        conn.commit()
    except Exception:
        # Another process may have created it concurrently.
        conn.rollback()


def load_dayoff_settings(cur, user_id: str) -> Dict[str, Any]:
    """
    Load future day-off settings (structure only for now).
    Current behavior remains equivalent to 'remove'.
    """
    default_settings = {
        "dayoff_mode": "remove",
        "dayoff_default_minutes": None,
        "dayoff_per_code_minutes": {},
    }
    cur.execute(
        """
        SELECT dayoff_mode, dayoff_default_minutes, dayoff_per_code_minutes
        FROM user_parsing_settings
        WHERE user_id = %s
        LIMIT 1
        """,
        (user_id,),
    )
    row = cur.fetchone()
    if not row:
        return default_settings
    
    mode, default_minutes, per_code_minutes = row
    mode = (mode or "remove").lower()
    if mode not in SUPPORTED_DAYOFF_MODES:
        mode = "remove"
    
    return {
        "dayoff_mode": mode,
        "dayoff_default_minutes": default_minutes,
        "dayoff_per_code_minutes": per_code_minutes if isinstance(per_code_minutes, dict) else {},
    }


def check_dayoff_deletion_rules(title, day_off_codes):
    """
    Check whether title should be removed by day-off logic.

    Returns:
        (should_delete: bool, reason: str | None)
    """
    if not title:
        return False, None
    
    title_upper = title.upper().strip()
    
    if " OFF AT" in title_upper or title_upper.startswith("OFF AT") or title_upper == "OFF":
        return True, "off_at_removed"
    if " DO AT" in title_upper or title_upper.startswith("DO AT"):
        return True, "do_at_removed"
    if " DR AT" in title_upper or title_upper.startswith("DR AT"):
        return True, "dr_at_removed"
    if " DB AT" in title_upper or title_upper.startswith("DB AT"):
        return True, "db_at_removed"
    if " DH AT" in title_upper or title_upper.startswith("DH AT"):
        return True, "dh_at_removed"
    
    for code in sorted(day_off_codes, key=len, reverse=True):
        if re.search(rf"\b{re.escape(code)}\b", title_upper):
            return True, "day_off_code_removed"
    
    return False, None


def process_dayoff_events(conn, user_id):
    """
    Remove processed events identified as day-off/off-at style entries.
    
    Returns:
        dict with statistics
    """
    day_off_codes = load_day_off_codes()
    stats = {"checked": 0, "deleted": 0, "skipped": 0}
    
    cur = conn.cursor()
    ensure_settings_table_exists(conn, cur)
    settings = load_dayoff_settings(cur, user_id)
    # Keep current automation unchanged: always remove day-offs for now.
    effective_mode = "remove"
    if settings["dayoff_mode"] != "remove":
        logger.info(
            "dayoff_parsing settings loaded (future mode scaffold): "
            f"requested_mode={settings['dayoff_mode']}, effective_mode={effective_mode}"
        )
    
    cur.execute(
        """
        SELECT id, source_uid, original_title, clean_title, is_synthetic
        FROM processed_events
        WHERE user_id = %s
        """,
        (user_id,),
    )
    rows = cur.fetchall()
    
    for proc_id, source_uid, original_title, clean_title, is_synthetic in rows:
        if is_synthetic:
            stats["skipped"] += 1
            continue
        
        stats["checked"] += 1
        title_to_check = (original_title or clean_title or "").strip()
        should_delete, reason = check_dayoff_deletion_rules(title_to_check, day_off_codes)
        if effective_mode != "remove" or not should_delete:
            continue
        
        cur.execute(
            "DELETE FROM processed_events WHERE id = %s",
            (proc_id,),
        )
        cur.execute(
            """
            UPDATE raw_events
            SET skip_reason = %s, processed_flag = TRUE
            WHERE user_id = %s AND source_uid = %s
            """,
            (reason, user_id, source_uid),
        )
        stats["deleted"] += 1
    
    conn.commit()
    cur.close()
    logger.info(
        f"dayoff_parsing complete: checked={stats['checked']}, deleted={stats['deleted']}, skipped={stats['skipped']}"
    )
    return stats


def main(user_id=None):
    """Entry point."""
    if user_id is None:
        user_id = USER_ID
    conn = None
    try:
        conn = get_connection()
        logger.info(f"Starting dayoff_parsing for user_id={user_id}")
        return process_dayoff_events(conn, user_id)
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    main()
