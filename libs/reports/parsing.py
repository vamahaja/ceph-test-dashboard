"""Parse Paddles API payloads into report models."""

from __future__ import annotations

from libs.defaults import DEFAULT_FAILURE_REASON_MAX_LEN
from libs.reports.models import FailedTestRunStat, Job, Results, TestRun
from libs.reports.utils import to_datetime


def _to_results(raw: dict) -> Results:
    results = raw.get("results") or {}
    return Results(
        pass_=int(results.get("pass") or 0),
        fail=int(results.get("fail") or 0),
        dead=int(results.get("dead") or 0),
        running=int(results.get("running") or 0),
        waiting=int(results.get("waiting") or 0),
        queued=int(results.get("queued") or 0),
    )


def normalize_status(status: str) -> str:
    status = (status or "").strip()
    if status.startswith("finished "):
        return status.split(" ", 1)[1]
    return status


def to_testrun(raw: dict) -> TestRun:
    return TestRun(
        name=raw.get("name", "") or "",
        branch=raw.get("branch", "") or "",
        suite=raw.get("suite", "") or "",
        sha_id=raw.get("sha_id") or raw.get("sha1") or "",
        machine_type=(
            raw.get("machine_type")
            or raw.get("cloud_platform")
            or ""
        ),
        status=normalize_status(raw.get("status", "") or ""),
        user=raw.get("user", "") or "",
        scheduled=to_datetime(
            raw.get("scheduled")
            if raw.get("scheduled") not in (None, "")
            else raw.get("posted")
        ),
        posted=to_datetime(raw.get("posted")),
        started=to_datetime(raw.get("started")),
        updated=to_datetime(raw.get("updated")),
        results=_to_results(raw),
    )


def as_run_list(raw) -> list[dict]:
    """Normalize Paddles run responses to a list of run dicts."""
    if raw is None:
        return []
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if isinstance(raw, dict):
        if "name" in raw or "results" in raw:
            return [raw]
        if isinstance(raw.get("runs"), list):
            return [item for item in raw["runs"] if isinstance(item, dict)]
    return []


def as_run_record(testrun: TestRun) -> dict:
    """Serialize a testrun for drill-in session state / ``from_records``."""
    return {
        "name": testrun.name,
        "branch": testrun.branch,
        "suite": testrun.suite,
        "sha_id": testrun.sha_id,
        "machine_type": testrun.machine_type,
        "status": testrun.status,
        "user": testrun.user,
        "scheduled": testrun.scheduled.isoformat() if testrun.scheduled else "",
        "posted": testrun.posted.isoformat() if testrun.posted else "",
        "started": testrun.started.isoformat() if testrun.started else "",
        "updated": testrun.updated.isoformat() if testrun.updated else "",
        "results": {
            "pass": testrun.results.pass_,
            "fail": testrun.results.fail,
            "dead": testrun.results.dead,
            "running": testrun.results.running,
            "waiting": testrun.results.waiting,
            "queued": testrun.results.queued,
        },
    }


def to_failed_stat(testrun: TestRun) -> FailedTestRunStat:
    return FailedTestRunStat(
        name=testrun.name,
        branch=testrun.branch,
        suite=testrun.suite,
        status=testrun.status,
        user=testrun.user,
        fail_pct=round(testrun.fail_pct, 2),
        results=testrun.results,
    )


def _to_job_id(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def to_job(raw: dict) -> Job:
    status = raw.get("status", "") or ""
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

    failure_reason = (
        raw.get("failure_reason")
        or raw.get("failure_template")
        or ""
    )
    if failure_reason and len(str(failure_reason)) > DEFAULT_FAILURE_REASON_MAX_LEN:
        keep = max(DEFAULT_FAILURE_REASON_MAX_LEN - 3, 0)
        failure_reason = str(failure_reason)[:keep] + "..."

    return Job(
        job_id=_to_job_id(raw.get("job_id")),
        name=raw.get("name", "") or "",
        description=raw.get("description", "") or "",
        owner=raw.get("owner", "") or "",
        branch=raw.get("branch", "") or "",
        sha1=raw.get("sha1") or raw.get("sha_id") or "",
        suite=raw.get("suite", "") or "",
        success=bool(success),
        status=status,
        duration=float(raw.get("duration") or 0.0),
        os_type=raw.get("os_type", "") or "",
        os_version=raw.get("os_version", "") or "",
        machine_type=(
            raw.get("machine_type")
            or raw.get("cloud_platform")
            or ""
        ),
        failure_reason=str(failure_reason),
        run_name=raw.get("run_name") or default_run_name or "",
        posted=to_datetime(raw.get("posted")),
        targets=raw.get("targets") or {},
    )


def as_job_list(raw) -> list[dict]:
    """Normalize Paddles job responses to a list of job dicts."""
    if raw is None:
        return []
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if isinstance(raw, dict):
        if "job_id" in raw or "name" in raw:
            return [raw]
        if isinstance(raw.get("jobs"), list):
            return [item for item in raw["jobs"] if isinstance(item, dict)]
    return []


def as_node_list(raw) -> list[dict]:
    """Normalize Paddles node inventory responses to a list of node dicts."""
    if raw is None:
        return []
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if isinstance(raw, dict):
        for key in ("nodes", "items", "results"):
            value = raw.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        if raw.get("machine_type") or raw.get("name") or raw.get("arch"):
            return [raw]
    return []
