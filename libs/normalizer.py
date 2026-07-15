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

import streamlit as st

from libs.config import get_base_url, get_cache_ttl
from libs.api import get_runs, get_jobs_for_run, get_runs_by_branch

_TTL = get_cache_ttl()


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

    return {
        "job_id":           str(raw.get("job_id", "")),
        "run_name":         run_name or (raw.get("run") or {}).get("name", ""),
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
