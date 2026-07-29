"""
libs/normalizer.py
==================
Normalises Paddles API responses into a consistent schema
used by all dashboard pages.

All functions return plain Python lists-of-dicts whose keys match the
field names used throughout the dashboard pages:

Runs fields:
  name, branch, suite, sha_id, cloud_platform, status, user,
  scheduled, posted, started, updated, job_ids, results, total_jobs

Jobs fields:
  job_id, run_name, branch, suite, sha_id, cloud_platform,
  success, status, description, machine_type, os_type,
  duration, owner, failure_template, posted
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import streamlit as st

from libs.config import (
    get_base_url,
    get_cache_ttl,
    get_hardware_config,
)
from libs.api import (
    get_jobs_for_run,
    get_nodes,
    get_runs,
    get_runs_by_branch,
)

# Single source of truth — hardware tuning values from libs/config.py
_HW = get_hardware_config()
from libs.hardware import build_arch_map_from_nodes

_TTL = get_cache_ttl()
_COMPLETED_STATUSES = {"pass", "fail", "dead"}


def _normalise_run(raw: dict) -> dict:
    """
    Map a raw Paddles /runs/ record to the dashboard schema.

    Paddles run fields (subset):
      name, status, user, scheduled, posted, jobs_count,
      results: {pass, fail, dead, running, waiting, queued}
      suite, branch, machine_type, ...
    """
    results = raw.get("results") or {}
    numeric_result_keys = {"pass", "fail", "dead", "running", "waiting", "queued"}
    if results:
        total = sum(
            int(results.get(key) or 0)
            for key in numeric_result_keys
            if str(results.get(key, "")).isdigit() or isinstance(results.get(key), int)
        )
    else:
        jobs_count = raw.get("jobs_count")
        jobs_count_str = str(jobs_count or "")
        total = int(jobs_count_str) if jobs_count_str.isdigit() else 0

    raw_status = raw.get("status", "")
    if raw_status.startswith("finished "):
        status = raw_status.split(" ", 1)[1]
    else:
        status = raw_status

    return {
        "name":           raw.get("name", ""),
        "branch":         raw.get("branch", ""),
        "suite":          raw.get("suite", ""),
        "sha_id":         raw.get("sha1", ""),
        "cloud_platform": raw.get("machine_type", ""),
        "status":         status,
        "user":           raw.get("user", ""),
        "scheduled":      raw.get("scheduled", raw.get("posted", "")),
        "posted":         raw.get("posted", ""),
        "started":        raw.get("started", ""),
        "updated":        raw.get("updated", ""),
        "job_ids":        [],
        "results":        results,
        "total_jobs":     total,
    }


def _normalise_job(raw: dict, run_name: str = "") -> dict:
    """
    Map a raw Paddles /runs/<run>/jobs/ record to the dashboard schema.

    Paddles job fields (subset):
      job_id, status, success, description, machine_type, os_type,
      duration, owner, posted, archive_path, failure_reason,
      branch, suite, ...
    """
    failure_reason: str | None = raw.get("failure_reason") or raw.get("failure_template")
    if failure_reason and len(failure_reason) > 80:
        failure_reason = failure_reason[:77] + "..."

    status = raw.get("status", "")
    success = raw.get("success")
    if success is None:
        success = status == "pass"

    run = raw.get("run")
    if isinstance(run, dict):
        default_run_name = run.get("name", "") or ""
    elif isinstance(run, str):
        default_run_name = run
    else:
        default_run_name = ""

    return {
        "job_id":           str(raw.get("job_id", "")),
        "run_name":         run_name or default_run_name,
        "branch":           raw.get("branch", ""),
        "suite":            raw.get("suite", ""),
        "sha_id":           raw.get("sha1", ""),
        "cloud_platform":   raw.get("machine_type", ""),
        "success":          success,
        "status":           status,
        "description":      raw.get("description", ""),
        "machine_type":     raw.get("machine_type", ""),
        "os_type":          raw.get("os_type", ""),
        "duration":         float(raw.get("duration") or 0),
        "owner":            raw.get("owner", ""),
        "failure_template": failure_reason,
        "posted":           raw.get("posted", ""),
    }


@st.cache_data(ttl=_TTL)
def get_runs_data(count: int = 100) -> list[dict]:
    """Return a list of normalised run dicts from the Paddles API."""
    try:
        raw = get_runs(count=count)
        if raw:
            return [_normalise_run(r) for r in raw]
    except Exception as exc:
        st.warning(f"Paddles API error (runs): {exc}")
    return []


@st.cache_data(ttl=_TTL)
def get_jobs_data(
    run_name: str | None = None,
    branch_name: str | None = None,
) -> list[dict]:
    """
    Return a list of normalised job dicts from the Paddles API.

    - run_name: fetches jobs for that specific run.
    - branch_name: fetches runs for the branch, then jobs for each run.
    - Neither: fetches jobs across the latest 20 runs.
    """
    try:
        if run_name:
            raw = get_jobs_for_run(run_name)
            if raw:
                return [_normalise_job(j, run_name) for j in raw]
        elif branch_name:
            runs = get_runs_by_branch(branch_name, count=50)
            if runs:
                jobs: list[dict] = []
                for run in runs[:20]:
                    rname = run.get("name", "")
                    rjobs = get_jobs_for_run(rname)
                    if rjobs:
                        jobs.extend(_normalise_job(j, rname) for j in rjobs)
                if jobs:
                    return jobs
        else:
            runs = get_runs(count=50)
            if runs:
                jobs: list[dict] = []
                for run in runs[:20]:
                    rname = run.get("name", "")
                    rjobs = get_jobs_for_run(rname)
                    if rjobs:
                        jobs.extend(_normalise_job(j, rname) for j in rjobs)
                if jobs:
                    return jobs
    except Exception as exc:
        st.warning(f"Paddles API error (jobs): {exc}")
    return []


@st.cache_data(ttl=_TTL)
def get_runs_by_branch_data(branch: str, count: int = 100) -> list[dict]:
    """Return normalised runs for a specific branch from the Paddles API."""
    try:
        raw = get_runs_by_branch(branch, count=count)
        if raw:
            return [_normalise_run(r) for r in raw]
    except Exception as exc:
        st.warning(f"Paddles API error (runs by branch): {exc}")
    return []


@st.cache_data(ttl=_TTL)
def get_nodes_data(machine_type: str | None = None) -> list[dict]:
    """Return raw node inventory records from Paddles ``/nodes/``."""
    try:
        raw = get_nodes(machine_type=machine_type)
        if raw:
            return list(raw)
    except Exception as exc:
        st.warning(f"Paddles API error (nodes): {exc}")
    return []


@st.cache_data(ttl=_TTL)
def get_machine_type_arch_map() -> dict[str, str]:
    """Return ``machine_type → arch`` from live Paddles node inventory."""
    nodes = get_nodes_data()
    return build_arch_map_from_nodes(nodes)


@st.cache_data(ttl=_TTL)
def get_machine_types_data() -> list[str]:
    """Return sorted machine_type names from Paddles ``/nodes/``."""
    nodes = get_nodes_data()
    types = sorted(
        {
            (n.get("machine_type") or "").strip()
            for n in nodes
            if (n.get("machine_type") or "").strip()
        }
    )
    return types


@st.cache_data(ttl=_TTL)
def get_machine_types_from_completed_runs(
    count: int = 500,
    days_window: int = 0,
) -> list[str]:
    """
    Return machine types that appear on recent completed runs.

    Prefer this for the Hardware page: Paddles ``/jobs/?machine_type=``
    ignores the filter, so we only offer types that have usable run data.

    Parameters
    ----------
    count : int
        Number of recent runs to scan.
    days_window : int
        Only include machine types seen in runs posted within this many
        days. 0 (default) means no date cutoff — return all types seen
        in the last ``count`` runs regardless of age.
    """
    from datetime import datetime, timedelta, timezone

    runs = get_runs_data(count=count)

    cutoff: datetime | None = None
    if days_window and days_window > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days_window)

    result = set()
    for r in runs:
        if r.get("status") not in _COMPLETED_STATUSES:
            continue
        mt = (r.get("cloud_platform") or "").strip()
        if not mt:
            continue
        if cutoff:
            raw_posted = r.get("posted") or ""
            try:
                posted = datetime.fromisoformat(
                    str(raw_posted).replace("Z", "+00:00")
                )
                if posted.tzinfo is None:
                    posted = posted.replace(tzinfo=timezone.utc)
                if posted < cutoff:
                    continue
            except (ValueError, TypeError):
                pass  # unparseable date — include the run
        result.add(mt)

    return sorted(result)


@st.cache_data(ttl=_TTL)
def get_completed_jobs_for_machine_type(
    machine_type: str,
    run_scan: int = _HW["run_scan"],
    max_runs: int = _HW["max_runs"],
    days_window: int = _HW["days_window"],
) -> list[dict]:
    """
    Return completed jobs (pass/fail/dead) for a machine_type.

    Paddles ``/jobs/?machine_type=`` does not honour the filter and returns
    the global latest queue (often queued/running). Instead we:

    1. Scan the most recent ``run_scan`` runs from Paddles
    2. Keep completed runs whose ``machine_type`` matches AND whose
       ``posted`` timestamp falls within the last ``days_window`` days
       (0 = no date cutoff)
    3. Cap at ``max_runs`` matching runs
    4. Load ``/runs/<name>/jobs/`` for each matching run

    Parameters
    ----------
    machine_type : str
        Lab machine class to filter on (case-insensitive).
    run_scan : int
        Number of recent runs to fetch from Paddles for scanning.
        Default 200 — covers ~2–4 weeks of typical Ceph CI volume.
    max_runs : int
        Hard cap on matching runs whose jobs are loaded.
        Default 60 — enough for reliable trend analysis.
    days_window : int
        Ignore runs older than this many days from now.
        Default 0 — no date cutoff. Pages should always pass this
        explicitly; never rely on the default for production use.
        Set to a positive integer (e.g. 30) to restrict to recent runs.
    """
    mt = (machine_type or "").strip().lower()
    if not mt:
        return []

    # Compute cutoff once (timezone-aware UTC)
    cutoff: datetime | None = None
    if days_window and days_window > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days_window)

    try:
        raw_runs = get_runs(count=run_scan) or []
    except Exception as exc:
        st.warning(f"Paddles API error (runs): {exc}")
        return []

    matching_runs: list[dict] = []
    for raw in raw_runs:
        run = _normalise_run(raw)

        # Date cutoff — Paddles returns runs newest-first, so once the
        # posted timestamp is older than the cutoff we can stop scanning.
        if cutoff and run.get("posted"):
            try:
                posted = datetime.fromisoformat(
                    str(run["posted"]).replace("Z", "+00:00")
                )
                # Make naive datetimes timezone-aware (assume UTC)
                if posted.tzinfo is None:
                    posted = posted.replace(tzinfo=timezone.utc)
                if posted < cutoff:
                    break
            except (ValueError, TypeError):
                pass  # unparseable date — include the run, don't skip

        if run["status"] not in _COMPLETED_STATUSES:
            continue
        if (run.get("cloud_platform") or "").strip().lower() != mt:
            continue

        matching_runs.append(run)
        if len(matching_runs) >= max_runs:
            break

    jobs: list[dict] = []
    for run in matching_runs:
        try:
            raw_jobs = get_jobs_for_run(run["name"]) or []
        except Exception:
            continue
        for raw_job in raw_jobs:
            job = _normalise_job(raw_job, run["name"])
            if job["status"] not in _COMPLETED_STATUSES:
                continue
            job_mt = (
                job.get("machine_type") or run.get("cloud_platform") or ""
            ).strip().lower()
            if job_mt and job_mt != mt:
                continue
            if not job.get("branch"):
                job["branch"] = run.get("branch", "")
            if not job.get("suite"):
                job["suite"] = run.get("suite", "")
            if not job.get("machine_type"):
                job["machine_type"] = run.get("cloud_platform", "")
            jobs.append(job)
    return jobs