"""Column types and time helpers that behave the same on SQLite and Postgres.

Two things SQLModel guesses wrong on Postgres, both confirmed by running
`create_all` against real Postgres 16:

    tags, comm_modes, quoted_line_items, cost_items  ->  JSON      (want JSONB)
    created_at, last_contact_at, column_changed_at   ->  TIMESTAMP (want TIMESTAMPTZ)

JSON without the B cannot be indexed or queried by path, and a naive TIMESTAMP
silently shifts every stall and no-contact comparison by the host's UTC offset.
Both are declared explicitly here rather than left to inference.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Optional

from sqlalchemy import DateTime, JSON
from sqlalchemy.dialects.postgresql import JSONB

# JSONB on Postgres, plain JSON on SQLite, from one declaration.
JSONColumn = JSON().with_variant(JSONB, "postgresql")

# timestamptz on Postgres; SQLite keeps the offset in the stored string.
TZDateTime = DateTime(timezone=True)


def utcnow() -> datetime:
    """Timezone-aware now. Never use datetime.utcnow(): it returns a naive value
    that compares wrongly against anything Postgres hands back."""
    return datetime.now(timezone.utc)


def as_utc(value: Optional[datetime]) -> Optional[datetime]:
    """Coerce any datetime to aware UTC.

    Rows written before the timezone-aware switch — every existing SQLite
    database — come back naive. Comparing naive to aware raises TypeError, so
    every read that feeds a comparison goes through here. Naive values are
    assumed UTC, which is what the old code wrote.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def days_between(later: datetime, earlier: Optional[datetime]) -> Optional[int]:
    """Whole days between two instants, tz-safe in both directions."""
    earlier = as_utc(earlier)
    if earlier is None:
        return None
    return (as_utc(later) - earlier).days


def days_since(value: Optional[datetime]) -> Optional[int]:
    return days_between(utcnow(), value)


def to_date(value: Any) -> Optional[date]:
    if value is None or isinstance(value, date) and not isinstance(value, datetime):
        return value
    return as_utc(value).date() if isinstance(value, datetime) else None
