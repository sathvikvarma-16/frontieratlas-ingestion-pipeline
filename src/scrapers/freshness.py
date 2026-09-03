"""Date normalization and strict 24-hour freshness checks."""

from datetime import datetime, timedelta, timezone
import re


def parse_relative_date(value: str, *, now: datetime | None = None) -> datetime | None:
    """Parse values such as ``2 hours ago`` into a UTC timestamp."""
    match = re.fullmatch(r"\s*(\d+)\s+(minute|hour|day)s?\s+ago\s*", value.lower())
    if not match:
        return None
    current = now or datetime.now(timezone.utc)
    amount, unit = int(match.group(1)), match.group(2)
    delta = {"minute": timedelta(minutes=amount), "hour": timedelta(hours=amount), "day": timedelta(days=amount)}[unit]
    return current - delta


def is_fresh(published_at: datetime | None, *, now: datetime | None = None, hours: int = 24) -> bool:
    if published_at is None:
        return False
    current = now or datetime.now(timezone.utc)
    timestamp = published_at.replace(tzinfo=timezone.utc) if published_at.tzinfo is None else published_at
    age = current - timestamp.astimezone(timezone.utc)
    return timedelta(0) <= age <= timedelta(hours=hours)