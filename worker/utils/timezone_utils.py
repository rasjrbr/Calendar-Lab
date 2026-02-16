"""
Timezone utilities for Calendar Lab.
Centralizes all timezone conversion logic.
"""

import os
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

SOURCE_TZ = os.getenv("SOURCE_TZ", "America/Sao_Paulo")


def to_utc(dt, source_tz=None):
    """
    Convert icalendar decoded DTSTART/DTEND to aware UTC datetime.
    
    Rules:
    - If dt is date object (all-day): interpret as midnight in SOURCE_TZ
    - If dt is naive datetime (floating): interpret as SOURCE_TZ
    - If dt is aware datetime: respect its timezone
    
    Args:
        dt: datetime object (date, naive datetime, or aware datetime)
        source_tz: Source timezone string (default: America/Sao_Paulo)
        
    Returns:
        datetime object in UTC (timezone-aware)
    """
    if source_tz is None:
        source_tz = SOURCE_TZ
    
    src = ZoneInfo(source_tz)
    
    # date object (all-day) -> midnight in SOURCE_TZ
    if hasattr(dt, "year") and not hasattr(dt, "hour"):
        local_dt = datetime(dt.year, dt.month, dt.day, 0, 0, 0, tzinfo=src)
        return local_dt.astimezone(timezone.utc)
    
    # naive datetime -> assume SOURCE_TZ (this is the key fix)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=src)
    
    return dt.astimezone(timezone.utc)


def utc_to_local(dt_utc, local_tz=None):
    """
    Convert UTC datetime to local timezone.
    
    Args:
        dt_utc: datetime object in UTC (timezone-aware or naive)
        local_tz: Target timezone string (default: America/Sao_Paulo)
        
    Returns:
        datetime object in local timezone (timezone-aware)
    """
    if local_tz is None:
        local_tz = SOURCE_TZ
    
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
    
    local = ZoneInfo(local_tz)
    return dt_utc.astimezone(local)


def get_local_date(dt_utc, local_tz=None):
    """
    Get the local date for a UTC datetime.
    Useful for grouping events by duty day.
    
    Args:
        dt_utc: datetime object in UTC
        local_tz: Target timezone (default: America/Sao_Paulo)
        
    Returns:
        datetime.date object in local timezone
    """
    local_dt = utc_to_local(dt_utc, local_tz)
    return local_dt.date()


def get_local_time_band(dt_utc, local_tz=None):
    """
    Determine which time band a duty starts in (for duty limit calculation).
    
    Time bands (based on local BRT start time):
    - 06:00-06:59: band 1
    - 07:00-07:59: band 2
    - 08:00-11:59: band 3
    - 12:00-13:59: band 4
    - 14:00-15:59: band 5
    - 16:00-17:59: band 6
    - 18:00-05:59: band 7
    
    Args:
        dt_utc: datetime object in UTC
        local_tz: Target timezone (default: America/Sao_Paulo)
        
    Returns:
        tuple: (band_number, band_label, band_key)
        or None if time not applicable
    """
    if local_tz is None:
        local_tz = SOURCE_TZ
    
    local_dt = utc_to_local(dt_utc, local_tz)
    hour = local_dt.hour
    
    bands = [
        (1, "06:00-06:59", "06-07", range(6, 7)),
        (2, "07:00-07:59", "07-08", range(7, 8)),
        (3, "08:00-11:59", "08-12", range(8, 12)),
        (4, "12:00-13:59", "12-14", range(12, 14)),
        (5, "14:00-15:59", "14-16", range(14, 16)),
        (6, "16:00-17:59", "16-18", range(16, 18)),
        (7, "18:00-05:59", "18-06", list(range(18, 24)) + list(range(0, 6))),
    ]
    
    for band_num, band_label, band_key, hours in bands:
        if hour in hours:
            return (band_num, band_label, band_key)
    
    return None


def format_duration_minutes(dt_start, dt_end):
    """
    Calculate duration in minutes between two UTC datetimes.
    
    Args:
        dt_start: START datetime (UTC)
        dt_end: END datetime (UTC)
        
    Returns:
        Integer minutes (can be negative if end < start)
    """
    delta = dt_end - dt_start
    return int(delta.total_seconds() / 60)


def format_duration_hm(dt_start, dt_end):
    """
    Format duration as "Xh Ym" string.
    
    Args:
        dt_start: START datetime (UTC)
        dt_end: END datetime (UTC)
        
    Returns:
        String like "9h 15m" or "1h"
    """
    minutes = format_duration_minutes(dt_start, dt_end)
    hours = minutes // 60
    mins = minutes % 60
    
    if mins == 0:
        return f"{hours}h"
    return f"{hours}h {mins}m"


def now_utc():
    """Get current time in UTC."""
    return datetime.now(timezone.utc)


def now_local(local_tz=None):
    """Get current time in local timezone."""
    return utc_to_local(now_utc(), local_tz)
