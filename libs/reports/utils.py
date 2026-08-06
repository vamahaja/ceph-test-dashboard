"""Shared helpers for report stats modules."""

from __future__ import annotations

from datetime import date, datetime


def to_datetime(value) -> datetime | None:
    """Parse timestamps like ``2026-08-06 15:13:22.304123``."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    try:
        text = str(value).strip().replace("Z", "+00:00")
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def pct(part: int, whole: int) -> float:
    return (part / whole * 100) if whole else 0.0


def as_date(value: date | datetime | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    return value


def parse_iso_date(value: str | date | datetime | None) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        return None
