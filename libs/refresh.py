"""Process-wide report payload cache shared by Overview and report pages.

Each filter key keeps one snapshot. All sessions are served that snapshot
until ``[cache] refresh_minutes`` elapses, then the last interval is merged
in. Switching filters does not drop other cached keys.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone

import streamlit as st

from libs.config import get_refresh_minutes
from libs.reports.models import Job, TestRun
from libs.reports.utils import as_utc

LoadFn = Callable[[], tuple[list[TestRun], list[Job]]]
RecentFn = Callable[[datetime], tuple[list[TestRun], list[Job]]]
TrimFn = Callable[[list[TestRun]], list[TestRun]]


def refresh_every() -> timedelta:
    """Configured snapshot lifetime / incremental refresh interval."""
    return timedelta(minutes=get_refresh_minutes())


def refresh_seconds() -> int:
    """Snapshot lifetime in seconds (for ``@st.cache_data`` TTLs)."""
    return get_refresh_minutes() * 60


def new_store() -> dict:
    """Process-wide multi-key payload cache."""
    return {
        "entries": {},
        "key_locks": {},
        "active_key": None,
        "lock": threading.Lock(),
    }


def utc_day_start(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc)


def utc_day_end_exclusive(day: date) -> datetime:
    return utc_day_start(day) + timedelta(days=1)


def _interval() -> timedelta:
    return refresh_every()


def _is_due(stamped: datetime | None, now: datetime, interval: timedelta) -> bool:
    ts = as_utc(stamped)
    if ts is None:
        return False
    return now - ts >= interval


def _legacy_entry(store: dict) -> dict | None:
    if store.get("loaded_at") is None:
        return None
    return {
        "runs": list(store.get("runs") or []),
        "jobs": list(store.get("jobs") or []),
        "loaded_at": store.get("loaded_at"),
        "patched_at": store.get("patched_at") or store.get("loaded_at"),
        "accessed_at": store.get("patched_at") or store.get("loaded_at"),
    }


def _entries(store: dict) -> dict:
    entries = store.setdefault("entries", {})
    if not entries and store.get("key") is not None:
        legacy = _legacy_entry(store)
        if legacy is not None:
            entries[store["key"]] = legacy
    return entries


def patch_due(store: dict, now: datetime | None = None) -> bool:
    """True when any cached snapshot has reached the refresh interval."""
    ref = as_utc(now) or datetime.now(timezone.utc)
    interval = _interval()
    entries = store.get("entries")
    if entries:
        return any(
            _is_due(
                entry.get("patched_at") or entry.get("loaded_at"),
                ref,
                interval,
            )
            for entry in entries.values()
        )
    return _is_due(
        store.get("patched_at") or store.get("loaded_at"),
        ref,
        interval,
    )


def merge_runs(
    existing: list[TestRun],
    incoming: list[TestRun],
    *,
    keep_since: datetime,
    keep_until: datetime | None = None,
) -> list[TestRun]:
    """Upsert incoming runs and drop rows outside ``[keep_since, keep_until)``."""
    by_name = {run.name: run for run in existing if run.name}
    for run in incoming:
        if run.name:
            by_name[run.name] = run
    keep_utc = as_utc(keep_since)
    until_utc = as_utc(keep_until)
    rows = []
    for run in by_name.values():
        posted = as_utc(run.posted)
        if posted is None:
            rows.append(run)
            continue
        if keep_utc is not None and posted < keep_utc:
            continue
        if until_utc is not None and posted >= until_utc:
            continue
        rows.append(run)
    rows.sort(key=lambda run: as_utc(run.posted) or keep_utc, reverse=True)
    return rows


def merge_jobs(existing: list[Job], incoming: list[Job]) -> list[Job]:
    """Replace jobs for runs present in ``incoming``, keep the rest."""
    refreshed = {job.run_name for job in incoming if job.run_name}
    kept = [job for job in existing if job.run_name not in refreshed]
    return kept + list(incoming)


def jobs_for_runs(jobs: list[Job], runs: list[TestRun]) -> list[Job]:
    """Drop jobs whose run is no longer in ``runs``."""
    names = {run.name for run in runs if run.name}
    return [job for job in jobs if job.run_name in names]


def _lock_for_key(store: dict, key: object) -> threading.Lock:
    global_lock = store.setdefault("lock", threading.Lock())
    with global_lock:
        store["active_key"] = key
        locks = store.setdefault("key_locks", {})
        if key not in locks:
            locks[key] = threading.Lock()
        return locks[key]


def _evict_idle(store: dict, now: datetime, keep: object) -> None:
    """Drop filter keys unused for two refresh intervals."""
    idle_after = _interval() * 2
    global_lock = store.setdefault("lock", threading.Lock())
    with global_lock:
        entries = store.get("entries") or {}
        dead = []
        locks = store.setdefault("key_locks", {})
        for cache_key, entry in entries.items():
            if cache_key == keep:
                continue
            held = locks.get(cache_key)
            if held is not None and held.locked():
                continue
            stamped = as_utc(entry.get("accessed_at") or entry.get("patched_at"))
            if stamped is None or now - stamped >= idle_after:
                dead.append(cache_key)
        for cache_key in dead:
            entries.pop(cache_key, None)
            locks.pop(cache_key, None)


def ensure_payload(
    store: dict,
    *,
    key: object,
    load_full: LoadFn,
    load_recent: RecentFn,
    keep_since: datetime,
    keep_until: datetime | None = None,
    trim_runs: TrimFn | None = None,
    spinner_full: str,
    spinner_patch: str | None = None,
) -> tuple[list[TestRun], list[Job], datetime | None]:
    """Return the cached snapshot for ``key``; load or patch only when due.

    All sessions share the same snapshot for a key until
    ``refresh_minutes`` elapses.
    """
    now = datetime.now(timezone.utc)
    minutes = get_refresh_minutes()
    interval = timedelta(minutes=minutes)
    entries = _entries(store)
    klock = _lock_for_key(store, key)

    with klock:
        entry = entries.get(key)
        if entry is not None:
            entry["accessed_at"] = now
        if entry is None or entry.get("loaded_at") is None:
            with st.spinner(spinner_full):
                runs, jobs = load_full()
            entry = {
                "runs": list(runs),
                "jobs": list(jobs),
                "loaded_at": now,
                "patched_at": now,
                "accessed_at": now,
            }
            entries[key] = entry
            return list(entry["runs"]), list(entry["jobs"]), entry["patched_at"]

        stamped = as_utc(entry.get("patched_at") or entry.get("loaded_at"))
        if stamped is not None and now - stamped >= interval:
            patch_since = now - interval
            text = spinner_patch or (
                f"Refreshing last {minutes} minutes of data…"
            )
            with st.spinner(text):
                recent_runs, recent_jobs = load_recent(patch_since)
            entry["runs"] = merge_runs(
                entry["runs"],
                recent_runs,
                keep_since=keep_since,
                keep_until=keep_until,
            )
            if trim_runs is not None:
                entry["runs"] = trim_runs(entry["runs"])
            entry["jobs"] = jobs_for_runs(
                merge_jobs(entry["jobs"], recent_jobs),
                entry["runs"],
            )
            entry["patched_at"] = now

        entry["accessed_at"] = now
        runs_out = list(entry["runs"])
        jobs_out = list(entry["jobs"])
        patched_at = entry["patched_at"]

    _evict_idle(store, now, key)
    return runs_out, jobs_out, patched_at


def periodic_rerun(store: dict) -> None:
    """Rerun the page when the active snapshot is due for a patch."""
    if patch_due(store):
        st.rerun()
