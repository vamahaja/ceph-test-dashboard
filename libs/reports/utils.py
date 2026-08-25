"""Shared helpers for report stats modules."""

from __future__ import annotations

from datetime import date, datetime, timezone

from libs.defaults import (
    DEFAULT_HEALTH_DEAD_CRITICAL,
    DEFAULT_HEALTH_DEAD_DEGRADED,
    DEFAULT_HEALTH_PASS_CRITICAL,
    DEFAULT_HEALTH_PASS_DEGRADED,
)


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


def as_utc(value: datetime | None) -> datetime | None:
    """Return ``value`` as timezone-aware UTC (naive values are assumed UTC)."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def sha_matches(value: str, needle: str) -> bool:
    """True if ``value`` and ``needle`` refer to the same commit (prefix-safe)."""
    have = (value or "").strip().lower()
    want = (needle or "").strip().lower()
    if not want:
        return True
    if want in {"unknown", "—", "-"}:
        return (not have) or have in {"unknown", "—", "-"}
    if not have:
        return False
    return have.startswith(want) or want.startswith(have)


def format_age(posted: datetime | None, now: datetime | None = None) -> str:
    """Human-readable age such as ``12m``, ``3.2h``, or ``1.5d``."""
    ts = as_utc(posted)
    if ts is None:
        return "—"
    ref = as_utc(now) or datetime.now(timezone.utc)
    seconds = max(0, (ref - ts).total_seconds())
    if seconds < 3600:
        return f"{int(seconds // 60)}m"
    if seconds < 86400:
        return f"{seconds / 3600:.1f}h"
    return f"{seconds / 86400:.1f}d"


def format_duration(seconds: float) -> str:
    """Human-readable duration such as ``45s``, ``12.4m``, or ``1.5h``."""
    if seconds <= 0:
        return "—"
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 3600:
        return f"{seconds / 60:.1f}m"
    return f"{seconds / 3600:.1f}h"


def health_assessment(pass_rate: float, dead_rate: float) -> tuple[str, list[str]]:
    """Return ``(badge, reasons)`` from completed-job pass and dead rates."""
    if (
        pass_rate < DEFAULT_HEALTH_PASS_CRITICAL
        or dead_rate >= DEFAULT_HEALTH_DEAD_CRITICAL
    ):
        badge = "Critical"
    elif (
        pass_rate < DEFAULT_HEALTH_PASS_DEGRADED
        or dead_rate >= DEFAULT_HEALTH_DEAD_DEGRADED
    ):
        badge = "Degraded"
    else:
        badge = "Healthy"

    if pass_rate < DEFAULT_HEALTH_PASS_CRITICAL:
        reasons = [
            f"Pass rate {pass_rate:.1f}% is under "
            f"{DEFAULT_HEALTH_PASS_CRITICAL:.0f}%."
        ]
    elif pass_rate < DEFAULT_HEALTH_PASS_DEGRADED:
        reasons = [
            f"Pass rate {pass_rate:.1f}% is under "
            f"{DEFAULT_HEALTH_PASS_DEGRADED:.0f}%."
        ]
    else:
        reasons = [
            f"Pass rate {pass_rate:.1f}% is at/above "
            f"{DEFAULT_HEALTH_PASS_DEGRADED:.0f}%."
        ]

    if dead_rate >= DEFAULT_HEALTH_DEAD_CRITICAL:
        reasons.append(
            f"Dead rate {dead_rate:.1f}% is at/above "
            f"{DEFAULT_HEALTH_DEAD_CRITICAL:.0f}%."
        )
    elif dead_rate >= DEFAULT_HEALTH_DEAD_DEGRADED:
        reasons.append(
            f"Dead rate {dead_rate:.1f}% is at/above "
            f"{DEFAULT_HEALTH_DEAD_DEGRADED:.0f}%."
        )
    else:
        reasons.append(
            f"Dead rate {dead_rate:.1f}% is under "
            f"{DEFAULT_HEALTH_DEAD_DEGRADED:.0f}%."
        )
    return badge, reasons


def health_badge(pass_rate: float, dead_rate: float) -> tuple[str, str]:
    """
    Return ``(label, caption)`` from pass rate and dead rate.

    Critical: pass < DEFAULT_HEALTH_PASS_CRITICAL or dead >= DEFAULT_HEALTH_DEAD_CRITICAL
    Degraded: pass < DEFAULT_HEALTH_PASS_DEGRADED or dead >= DEFAULT_HEALTH_DEAD_DEGRADED
    Healthy: otherwise
    """
    badge, reasons = health_assessment(pass_rate, dead_rate)
    return badge, " ".join(reasons)
