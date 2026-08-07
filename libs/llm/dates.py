"""Date-range helpers for LLM tool filters."""

from __future__ import annotations

import calendar
import re
from datetime import date, timedelta
from typing import Any

_MONTH_NAMES = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}


def _parse_iso_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    lowered = text.lower()
    today = date.today()
    if lowered == "today":
        return today
    if lowered == "yesterday":
        return today - timedelta(days=1)
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def _parse_month_token(text: str, *, today: date) -> tuple[date, date] | None:
    """Parse ``july``, ``jul 2026``, ``2026-07`` into month bounds."""
    raw = text.strip().lower().replace("/", "-")
    if not raw:
        return None

    iso_month = re.fullmatch(r"(\d{4})-(\d{1,2})", raw)
    if iso_month:
        year = int(iso_month.group(1))
        month = int(iso_month.group(2))
        if 1 <= month <= 12:
            return _month_bounds(year, month)
        return None

    named = re.fullmatch(r"([a-z]+)\s*[-,]?\s*(\d{4})?", raw)
    if named and named.group(1) in _MONTH_NAMES:
        month = _MONTH_NAMES[named.group(1)]
        year = int(named.group(2)) if named.group(2) else today.year
        start, end = _month_bounds(year, month)
        if not named.group(2) and start > today:
            start, end = _month_bounds(year - 1, month)
        return start, end
    return None


def _period_range(period: str, *, today: date) -> tuple[date, date] | None:
    key = period.strip().lower().replace(" ", "_").replace("-", "_")
    if not key:
        return None
    if key in {"last_7_days", "past_7_days", "last_week", "past_week"}:
        return today - timedelta(days=6), today
    if key in {"last_14_days", "past_14_days", "last_two_weeks"}:
        return today - timedelta(days=13), today
    if key in {"last_30_days", "past_30_days"}:
        return today - timedelta(days=29), today
    if key in {"last_month", "past_month", "previous_month"}:
        first_this = today.replace(day=1)
        end = first_this - timedelta(days=1)
        return end.replace(day=1), end
    if key in {"this_month", "current_month"}:
        return today.replace(day=1), today
    if key in {"this_year", "ytd"}:
        return date(today.year, 1, 1), today
    return None


def resolve_date_range(args: dict[str, Any]) -> tuple[str | None, str | None]:
    """
    Resolve tool args into inclusive ``(date_start, date_end)`` ISO dates.

    Accepts:
    - ``date_start`` / ``date_end`` as YYYY-MM-DD (or today/yesterday)
    - ``period`` shortcuts: last_week, last_month, last_7_days, …
    - month tokens: ``july``, ``2026-07`` (alone in date_start or period)
    """
    today = date.today()
    period = str(args.get("period") or "").strip()
    if period:
        bounds = _period_range(period, today=today)
        if bounds:
            return bounds[0].isoformat(), bounds[1].isoformat()
        month_bounds = _parse_month_token(period, today=today)
        if month_bounds:
            return month_bounds[0].isoformat(), month_bounds[1].isoformat()

    start_raw = str(args.get("date_start") or args.get("since") or "").strip()
    end_raw = str(args.get("date_end") or args.get("until") or "").strip()

    if start_raw and not end_raw:
        month_bounds = _parse_month_token(start_raw, today=today)
        if month_bounds:
            return month_bounds[0].isoformat(), month_bounds[1].isoformat()

    if end_raw and not start_raw:
        month_bounds = _parse_month_token(end_raw, today=today)
        if month_bounds:
            return month_bounds[0].isoformat(), month_bounds[1].isoformat()

    start = _parse_iso_date(start_raw)
    end = _parse_iso_date(end_raw)

    if start is None and start_raw:
        month_bounds = _parse_month_token(start_raw, today=today)
        if month_bounds:
            start = month_bounds[0]
            if end is None:
                end = month_bounds[1]
    if end is None and end_raw:
        month_bounds = _parse_month_token(end_raw, today=today)
        if month_bounds:
            end = month_bounds[1]
            if start is None:
                start = month_bounds[0]

    if start and not end:
        end = today
    if end and not start:
        start = end

    if start and end and start > end:
        start, end = end, start

    return (
        start.isoformat() if start else None,
        end.isoformat() if end else None,
    )
