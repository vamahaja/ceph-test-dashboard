"""Process-wide 30-day catalog with clock-aligned background refresh.

The first process start loads the last 30 days of runs and jobs. A daemon
then reloads that same 30-day window on each ``refresh_minutes`` clock
boundary (default: every hour at :00 UTC) and replaces the published
snapshot so a refresh never blanks the UI.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import date, datetime, timedelta, timezone
from typing import NamedTuple

from libs.config import get_refresh_minutes
from libs.defaults import DEFAULT_CATALOG_DAYS
from libs.reports.jobs import JobsStats
from libs.reports.models import Job, TestRun
from libs.reports.testruns import TestRunsStats
from libs.reports.utils import as_utc

_LOG = logging.getLogger(__name__)
_RETRY_SECONDS = 30

_lock = threading.Lock()
_thread: threading.Thread | None = None
_state: dict = {
    "ready": False,
    "refreshing": False,
    "error": None,
    "runs": [],
    "jobs": [],
    "loaded_at": None,
    "generation": 0,
    "progress": "Starting initialization…",
    "progress_log": [],
}


class CatalogSnapshot(NamedTuple):
    """Published catalog view. Treat ``runs`` / ``jobs`` as immutable."""

    runs: list[TestRun]
    jobs: list[Job]
    loaded_at: datetime | None
    generation: int


def refresh_every() -> timedelta:
    """Configured background refresh interval."""
    return timedelta(minutes=get_refresh_minutes())


def refresh_seconds() -> int:
    """Refresh interval in seconds (for ``@st.cache_data`` TTLs)."""
    return get_refresh_minutes() * 60


def utc_day_start(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc)


def utc_day_end_exclusive(day: date) -> datetime:
    return utc_day_start(day) + timedelta(days=1)


def catalog_keep_since(now: datetime | None = None) -> datetime:
    """Oldest posted time retained in the catalog (rolling 30 days)."""
    ref = as_utc(now) or datetime.now(timezone.utc)
    return ref - timedelta(days=DEFAULT_CATALOG_DAYS)


def next_clock_boundary(now: datetime, minutes: int) -> datetime:
    """Next UTC clock time aligned to ``minutes`` (60 → the next hour :00)."""
    step = max(1, int(minutes))
    floored = now.replace(second=0, microsecond=0)
    if 60 % step == 0:
        nxt_min = ((floored.minute // step) + 1) * step
        hour = floored.hour
        day = floored.date()
        if nxt_min >= 60:
            nxt_min = 0
            hour += 1
            if hour >= 24:
                hour = 0
                day = day + timedelta(days=1)
        return datetime(
            day.year, day.month, day.day, hour, nxt_min, tzinfo=timezone.utc
        )
    return now + timedelta(minutes=step)


def catalog_is_ready() -> bool:
    with _lock:
        return bool(_state["ready"])


def catalog_is_refreshing() -> bool:
    with _lock:
        return bool(_state["refreshing"])


def catalog_error() -> str | None:
    with _lock:
        err = _state["error"]
    return str(err) if err else None


def catalog_progress() -> tuple[str, list[str]]:
    """Current progress line and completed initialization steps."""
    with _lock:
        return (
            str(_state.get("progress") or ""),
            list(_state.get("progress_log") or []),
        )


def catalog_generation() -> int:
    with _lock:
        return int(_state["generation"] or 0)


def catalog_loaded_at() -> datetime | None:
    with _lock:
        return _state["loaded_at"]


def get_catalog() -> CatalogSnapshot:
    """Return the last published snapshot (never blocks on a patch)."""
    with _lock:
        return CatalogSnapshot(
            runs=_state["runs"],
            jobs=_state["jobs"],
            loaded_at=_state["loaded_at"],
            generation=int(_state["generation"] or 0),
        )


def start_catalog() -> None:
    """Start the catalog thread once per process."""
    global _thread
    with _lock:
        if _thread is not None and _thread.is_alive():
            return
        _thread = threading.Thread(
            target=_catalog_loop,
            name="catalog-refresh",
            daemon=True,
        )
        _thread.start()


def _set(**updates) -> None:
    with _lock:
        _state.update(updates)


def _progress(message: str, *, log: bool = False) -> None:
    with _lock:
        _state["progress"] = message
        if log:
            steps = list(_state.get("progress_log") or [])
            if not steps or steps[-1] != message:
                steps.append(message)
            _state["progress_log"] = steps


def _load_window(
    since: datetime,
    *,
    until: datetime | None = None,
    announce: bool = False,
) -> tuple[list[TestRun], list[Job]]:
    days = DEFAULT_CATALOG_DAYS
    if announce:
        _progress(f"Fetching testruns from the last {days} days…", log=True)
    runs = TestRunsStats.since(since, until=until)
    n_runs = len(runs.testruns)
    if announce:
        _progress(f"Fetched {n_runs:,} testruns", log=True)
    if not n_runs:
        return [], []

    if announce:
        _progress(f"Fetching jobs for {n_runs:,} testruns…", log=True)

    def on_jobs_progress(done: int, total: int) -> None:
        if announce:
            _progress(f"Fetching jobs ({done:,} / {total:,} testruns)…")

    jobs = JobsStats.for_testruns(runs.testruns, on_progress=on_jobs_progress)
    if announce:
        _progress(f"Loaded {len(jobs.jobs):,} jobs", log=True)
    return runs.testruns, jobs.jobs


def _publish(
    runs: list[TestRun],
    jobs: list[Job],
    *,
    loaded_at: datetime,
) -> None:
    with _lock:
        _state["runs"] = runs
        _state["jobs"] = jobs
        _state["loaded_at"] = loaded_at
        _state["generation"] = int(_state["generation"] or 0) + 1
        _state["ready"] = True
        _state["refreshing"] = False
        _state["error"] = None


def _sleep_until(deadline: datetime) -> None:
    while True:
        remaining = (deadline - datetime.now(timezone.utc)).total_seconds()
        if remaining <= 0:
            return
        time.sleep(min(remaining, 5.0))


def _catalog_loop() -> None:
    while True:
        keep_since = catalog_keep_since()
        ready = catalog_is_ready()
        try:
            if not ready:
                _progress("Starting initialization…", log=True)
                _LOG.info("Loading last %s days of catalog data", DEFAULT_CATALOG_DAYS)
                runs, jobs = _load_window(keep_since, announce=True)
                _progress("Initialization complete", log=True)
            else:
                _set(refreshing=True, error=None)
                _LOG.info(
                    "Reloading last %s days of catalog data", DEFAULT_CATALOG_DAYS
                )
                runs, jobs = _load_window(keep_since)
            if ready and not runs:
                _LOG.warning(
                    "Hourly reload returned no testruns; keeping current catalog"
                )
                _set(refreshing=False)
            else:
                _publish(runs, jobs, loaded_at=datetime.now(timezone.utc))
                _LOG.info("Catalog ready: %s runs, %s jobs", len(runs), len(jobs))
        except Exception as exc:
            _LOG.exception("Catalog refresh failed")
            _set(refreshing=False, error=str(exc))
            time.sleep(_RETRY_SECONDS)
            continue

        _sleep_until(
            next_clock_boundary(datetime.now(timezone.utc), get_refresh_minutes())
        )
