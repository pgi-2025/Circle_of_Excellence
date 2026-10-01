"""
Single source of truth for "now" across the backend.

Always use utcnow() from here instead of datetime.datetime.utcnow(),
which returns a *naive* datetime and is deprecated. This returns a
timezone-aware UTC datetime, per project convention.
"""
from datetime import datetime, timezone


def utcnow() -> datetime:
    """Timezone-aware current UTC time. Use this everywhere instead of
    datetime.datetime.utcnow()."""
    return datetime.now(timezone.utc)


def parse_iso(value: str) -> datetime:
    """Parse an ISO-8601 timestamp (as returned by Postgres/Supabase,
    optionally with a trailing 'Z') into a timezone-aware UTC datetime."""
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
