"""Timezone-aware daily scheduling, independent of the device's local timezone."""

from datetime import datetime, timedelta, timezone
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def next_daily_run(daily_time, timezone_name, after):
    if not isinstance(daily_time, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", daily_time):
        raise ValueError("Choose a daily time in HH:MM format")
    try:
        zone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise ValueError("Choose a valid timezone")
    hour, minute = map(int, daily_time.split(":"))
    local_day = after.astimezone(zone).date()
    for offset in range(3):
        # fold=0 runs once at the first occurrence of a repeated hour.
        # A skipped spring-forward time moves forward by the DST gap.
        candidate = datetime.combine(local_day + timedelta(days=offset), datetime.min.time()).replace(
            hour=hour, minute=minute, tzinfo=zone, fold=0).astimezone(timezone.utc)
        if candidate > after:
            return candidate
    raise ValueError("Could not determine next daily run")
