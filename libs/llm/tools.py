"""LLM tools wrapping TestRunsStats and JobsStats for OpenAI tool calling."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from typing import Any

from libs.defaults import (
    DEFAULT_LLM_DATE_SEARCH_COUNT,
    DEFAULT_LLM_JOB_COUNT,
    DEFAULT_LLM_JOBS_IN_RESPONSE,
    DEFAULT_LLM_MAX_TOOL_CHARS,
    DEFAULT_LLM_SEARCH_COUNT,
    DEFAULT_LLM_TOP_N,
)
from libs.llm.dates import resolve_date_range
from libs.reports.jobs import JobsStats
from libs.reports.models import (
    ActiveRunsSummary,
    ClusterHealthSnapshot,
    FailedRunStat,
    Job,
    JobsSummary,
    StatusShareTrend,
    SuiteTrend,
    TestRun,
)
from libs.reports.testruns import TestRunsStats


def _tool(
    name: str,
    description: str,
    properties: dict[str, Any],
    required: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required or [],
                "additionalProperties": False,
            },
        },
    }


_DATE_FILTER_PROPS: dict[str, Any] = {
    "date_start": {
        "type": "string",
        "description": (
            "Inclusive start date as YYYY-MM-DD. Also accepts today, "
            "yesterday, or a month token like 2026-07 / july."
        ),
    },
    "date_end": {
        "type": "string",
        "description": (
            "Inclusive end date as YYYY-MM-DD (default today when only "
            "date_start is set)."
        ),
    },
    "period": {
        "type": "string",
        "description": (
            "Relative window shortcut: last_week, last_7_days, last_30_days, "
            "last_month, this_month, this_year. Prefer this OR date_start/"
            "date_end, not both."
        ),
    },
}

_TESTRUN_SEARCH_PROPS: dict[str, Any] = {
    "count": {
        "type": "integer",
        "description": (
            f"Max testruns to fetch "
            f"(default {DEFAULT_LLM_SEARCH_COUNT})."
        ),
    },
    "branch": {
        "type": "string",
        "description": (
            "Exact Ceph git branch / release (e.g. tentacle, squid, reef, "
            "main). Use this for 'tentacle builds' / 'squid runs'."
        ),
    },
    "suite": {
        "type": "string",
        "description": (
            "Teuthology suite / test area (e.g. rados, fs, orch, rgw). "
            "Never put release names like tentacle or squid here."
        ),
    },
    "user": {
        "type": "string",
        "description": "Filter by submitting user.",
    },
    "status": {
        "type": "string",
        "description": (
            "Exact status token only: pass, fail, dead, running, waiting, "
            "queued (or finished). Use fail — never 'failed'."
        ),
    },
    **_DATE_FILTER_PROPS,
}

_JOB_SEARCH_PROPS: dict[str, Any] = {
    "count": {
        "type": "integer",
        "description": (
            f"Max jobs to fetch (default {DEFAULT_LLM_JOB_COUNT})."
        ),
    },
    "branch": {
        "type": "string",
        "description": (
            "Exact Ceph git branch / release filter "
            "(e.g. tentacle, squid, reef)."
        ),
    },
    "suite": {
        "type": "string",
        "description": (
            "Suite name filter (e.g. rados, fs, orch). "
            "Not for release names like tentacle/squid."
        ),
    },
    "sha1": {
        "type": "string",
        "description": "Filter by Ceph git SHA1.",
    },
    "os_type": {
        "type": "string",
        "description": "OS type filter (e.g. ubuntu, centos, rhel).",
    },
    "user": {
        "type": "string",
        "description": "Filter by job owner / user.",
    },
    "machine_type": {
        "type": "string",
        "description": "Lab machine type filter (e.g. smithi, plana).",
    },
    "status": {
        "type": "string",
        "description": (
            "Exact status token only: pass, fail, dead, running, waiting, "
            "queued. Use fail — never 'failed'."
        ),
    },
    "run_name": {
        "type": "string",
        "description": (
            "Optional exact testrun name. When set, loads jobs for that run "
            "via /runs/{name}/jobs/ instead of the global /jobs/ list."
        ),
    },
    **_DATE_FILTER_PROPS,
}


def _testrun_filters(
    args: dict[str, Any],
    *,
    default_count: int,
) -> dict[str, Any]:
    date_start, date_end = resolve_date_range(args)
    count = int(args.get("count") or default_count)
    if (date_start or date_end) and not args.get("count"):
        count = max(count, DEFAULT_LLM_DATE_SEARCH_COUNT)
    return {
        "count": count,
        "branch": str(args.get("branch") or ""),
        "suite": str(args.get("suite") or ""),
        "testrun_name": str(args.get("testrun_name") or ""),
        "user": str(args.get("user") or ""),
        "status": str(args.get("status") or ""),
        "date_start": date_start or "",
        "date_end": date_end or "",
    }


def _job_filters(args: dict[str, Any]) -> dict[str, Any]:
    date_start, date_end = resolve_date_range(args)
    count = int(args.get("count") or DEFAULT_LLM_JOB_COUNT)
    if (date_start or date_end) and not args.get("count"):
        count = max(count, DEFAULT_LLM_DATE_SEARCH_COUNT)
    return {
        "count": count,
        "branch": str(args.get("branch") or ""),
        "suite": str(args.get("suite") or ""),
        "sha1": str(args.get("sha1") or ""),
        "os_type": str(args.get("os_type") or ""),
        "user": str(args.get("user") or ""),
        "machine_type": str(args.get("machine_type") or ""),
        "status": str(args.get("status") or ""),
        "run_name": str(args.get("run_name") or ""),
        "date_start": date_start or "",
        "date_end": date_end or "",
    }


def _compact_results(r: Any) -> dict[str, Any]:
    return {
        "pass": r.pass_,
        "fail": r.fail,
        "dead": r.dead,
        "running": r.running,
        "waiting": r.waiting,
        "queued": r.queued,
        "total": r.total,
        "failed": r.failed,
    }


def _fail_pct(testrun: TestRun) -> float:
    total = testrun.results.total
    if not total:
        return 0.0
    return testrun.results.failed / total * 100


def _compact_testrun(t: TestRun) -> dict[str, Any]:
    return {
        "name": t.name,
        "branch": t.branch,
        "suite": t.suite,
        "status": t.status,
        "user": t.user,
        "results": _compact_results(t.results),
        "fail_pct": round(_fail_pct(t), 2),
        "sha1": t.sha_id,
        "machine_type": t.machine_type,
        "scheduled": t.scheduled,
        "posted": t.posted,
        "started": t.started,
        "updated": t.updated,
    }


def _pass_fail_rates(summary: JobsSummary) -> tuple[float, float]:
    completed = summary.cnt_pass + summary.cnt_fail + summary.cnt_dead
    if not completed:
        return 0.0, 0.0
    passed = summary.cnt_pass
    failed = summary.cnt_fail + summary.cnt_dead
    return (
        round(passed / completed * 100, 1),
        round(failed / completed * 100, 1),
    )


def _top_failed_testruns(
    testruns: list[TestRun],
    n: int = 10,
) -> list[TestRun]:
    ranked = sorted(testruns, key=_fail_pct, reverse=True)
    return ranked[:n]


def _compact_share_trends(
    trends: list[StatusShareTrend],
) -> list[dict[str, Any]]:
    return [
        {
            "key": trend.key,
            "results": _compact_results(trend.results),
            "pct_pass": trend.pct_pass,
            "pct_fail": trend.pct_fail,
            "pct_dead": trend.pct_dead,
        }
        for trend in trends
    ]


def _compact_suite_trends(
    trends: list[SuiteTrend],
) -> list[dict[str, Any]]:
    return [
        {
            "suite": trend.suite,
            "results": _compact_results(trend.results),
        }
        for trend in trends
    ]


def _compact_job(j: Job) -> dict[str, Any]:
    reason = j.failure_reason or ""
    desc = j.description or ""
    return {
        "job_id": j.job_id,
        "run_name": j.run_name,
        "name": j.name,
        "description": (desc[:100] + "…") if len(desc) > 100 else desc,
        "status": j.status,
        "success": j.success,
        "branch": j.branch,
        "suite": j.suite,
        "os_type": j.os_type,
        "os_version": j.os_version,
        "machine_type": j.machine_type,
        "duration": j.duration,
        "posted": j.posted,
        "failure_reason": (
            (reason[:120] + "…") if len(reason) > 120 else reason
        ),
    }


def _compact_failure_reason(stat: Any) -> dict[str, Any]:
    return {
        "reason": stat.reason,
        "count": stat.count,
        "pct": stat.pct,
        "runs_impacted": stat.runs_impacted,
        "branches_impacted": stat.branches_impacted,
        "suites_impacted": stat.suites_impacted,
        "tests_impacted": stat.tests_impacted,
    }


def _compact_failed_run(stat: FailedRunStat) -> dict[str, Any]:
    return {
        "run_name": stat.run_name,
        "suite": stat.suite,
        "failed_jobs": stat.failed_jobs,
        "total_jobs": stat.total_jobs,
        "fail_pct": stat.fail_pct,
    }


def _compact_active_summary(summary: ActiveRunsSummary) -> dict[str, Any]:
    return {
        "cnt_testruns": summary.cnt_testruns,
        "cnt_jobs": summary.cnt_jobs,
        "cnt_running": summary.cnt_running,
        "cnt_waiting": summary.cnt_waiting,
        "cnt_queued": summary.cnt_queued,
        "oldest_age": summary.oldest_age,
    }


def _compact_cluster_health(
    snapshot: ClusterHealthSnapshot,
) -> dict[str, Any]:
    return {
        "badge": snapshot.badge,
        "reasons": snapshot.reasons,
        "completed_jobs": snapshot.completed.cnt_jobs,
        "pct_pass": round(snapshot.completed.pct_pass, 1),
        "pct_not_passed": snapshot.pct_not_passed,
        "cnt_testruns": snapshot.cnt_testruns,
        "cnt_active_runs": snapshot.cnt_active_runs,
        "cnt_inflight": snapshot.cnt_inflight,
        "top_failure": snapshot.top_failure,
        "top_failure_count": snapshot.top_failure_count,
        "worst_branch": snapshot.worst_branch,
        "worst_branch_fail_pct": snapshot.worst_branch_fail_pct,
        "stuck_6h": snapshot.stuck_6h,
        "stuck_24h": snapshot.stuck_24h,
    }


def _failed_jobs(
    jobs: list[Job],
    limit: int = DEFAULT_LLM_TOP_N,
) -> list[dict[str, Any]]:
    failed = [j for j in jobs if j.is_failing]
    failed.sort(key=lambda j: (j.status != "dead", j.duration), reverse=True)
    return [_compact_job(j) for j in failed[:limit]]


def search_testruns(**kwargs: Any) -> Any:
    """Search testruns and return a packed overview in one response."""
    filters = _testrun_filters(kwargs, default_count=DEFAULT_LLM_SEARCH_COUNT)
    # search_testruns is list/filter oriented — ignore exact-name lookups.
    filters["testrun_name"] = ""
    stats = TestRunsStats(**filters)
    testruns = stats.testruns
    jobs_stats = (
        JobsStats.for_testruns(testruns)
        if testruns
        else JobsStats.from_jobs([])
    )
    return {
        "filters": {
            k: v for k, v in filters.items() if v and k != "testrun_name"
        },
        "summary": stats.summary,
        "active_summary": _compact_active_summary(stats.active_summary()),
        "cluster_health": _compact_cluster_health(
            stats.cluster_health(jobs_stats)
        ),
        "testruns": [_compact_testrun(t) for t in testruns],
        "top_failed_testruns": [
            _compact_testrun(t) for t in _top_failed_testruns(testruns)
        ],
        "top_failed_runs": [
            _compact_failed_run(r) for r in jobs_stats.top_failed_runs
        ],
        "active_testruns": [
            _compact_testrun(t) for t in stats.active_testruns
        ],
        "top_failure_reasons": [
            _compact_failure_reason(r)
            for r in jobs_stats.top_10_failure_reasons
        ],
        "trends_by_suite": _compact_suite_trends(
            jobs_stats.trends_by_suite
        ),
        "os_share_trends": _compact_share_trends(
            jobs_stats.os_share_trends()
        ),
        "daily_trends": jobs_stats.daily_trends,
        "count_returned": len(testruns),
    }


def get_testrun_report(**kwargs: Any) -> Any:
    """Full report for one testrun, including job-level failure insights."""
    filters = _testrun_filters(kwargs, default_count=DEFAULT_LLM_SEARCH_COUNT)
    testrun_name = filters["testrun_name"]
    if testrun_name:
        stats = TestRunsStats(testrun_name=testrun_name)
    else:
        # Latest matching run from filters when no exact name is given.
        filters["testrun_name"] = ""
        stats = TestRunsStats(**filters)

    testrun = stats.testruns[0] if stats.testruns else None
    if testrun is None:
        return {
            "result": None,
            "note": "No matching testrun found.",
            "filters": {k: v for k, v in filters.items() if v},
        }

    jobs_stats = JobsStats.for_run(testrun.name)
    pass_rate, fail_rate = _pass_fail_rates(jobs_stats.completed_summary)
    return {
        "testrun": _compact_testrun(testrun),
        "summary": stats.summary,
        "job_summary": jobs_stats.summary,
        "completed_job_summary": jobs_stats.completed_summary,
        "pass_rate": pass_rate,
        "fail_rate": fail_rate,
        "job_count": len(jobs_stats.jobs),
        "top_failed_jobs": _failed_jobs(jobs_stats.failing_jobs),
        "top_failure_reasons": [
            _compact_failure_reason(r)
            for r in jobs_stats.top_10_failure_reasons
        ],
        "top_failing_tests": [
            {
                "description": row.description,
                "count": row.count,
                "pct": row.pct,
                "runs_impacted": row.runs_impacted,
            }
            for row in jobs_stats.top_failing_tests()
        ],
        "os_share_trends": _compact_share_trends(
            jobs_stats.os_share_trends()
        ),
    }


def search_jobs(**kwargs: Any) -> Any:
    """Search jobs (global or for one run) with failure/OS aggregates."""
    filters = _job_filters(kwargs)
    date_start = filters.pop("date_start", "")
    date_end = filters.pop("date_end", "")
    stats = JobsStats(**filters)
    if date_start or date_end:
        start = date.fromisoformat(date_start) if date_start else None
        end = date.fromisoformat(date_end) if date_end else None
        stats = JobsStats.from_jobs(
            stats.filtered(date_start=start, date_end=end)
        )
    jobs = stats.jobs
    visible_filters = {
        **{k: v for k, v in filters.items() if v},
        **{
            k: v
            for k, v in {"date_start": date_start, "date_end": date_end}.items()
            if v
        },
    }
    pass_rate, fail_rate = _pass_fail_rates(stats.completed_summary)
    return {
        "filters": visible_filters,
        "summary": stats.summary,
        "completed_job_summary": stats.completed_summary,
        "pass_rate": pass_rate,
        "fail_rate": fail_rate,
        "job_count": len(jobs),
        "jobs": [
            _compact_job(j) for j in jobs[:DEFAULT_LLM_JOBS_IN_RESPONSE]
        ],
        "top_failed_jobs": _failed_jobs(stats.failing_jobs),
        "top_failure_reasons": [
            _compact_failure_reason(r)
            for r in stats.top_10_failure_reasons
        ],
        "top_failed_runs": [
            _compact_failed_run(r) for r in stats.top_failed_runs
        ],
        "os_share_trends": _compact_share_trends(
            stats.os_share_trends()
        ),
        "truncated": len(jobs) > DEFAULT_LLM_JOBS_IN_RESPONSE,
    }


TOOLS: list[dict[str, Any]] = [
    _tool(
        "search_testruns",
        "Search Teuthology testruns and return everything needed in one call: "
        "matching runs (compact), overall summary, cluster health, active "
        "runs, top failed runs (job-based), top failure reasons, suite "
        "trends, OS share trends, and daily job trends by posted date. "
        "Supports date_start/date_end or period (last_week, last_month, "
        "july, …). Use for questions like 'latest tentacle runs', "
        "'July failures', or 'last week trends'.",
        _TESTRUN_SEARCH_PROPS,
    ),
    _tool(
        "get_testrun_report",
        "Full report for one testrun in a single call: run details, summary, "
        "top failed jobs, top failure reasons, and OS breakdown. "
        "Pass testrun_name for an exact run, or branch/suite/status filters "
        "to report on the newest matching run.",
        {
            **_TESTRUN_SEARCH_PROPS,
            "testrun_name": {
                "type": "string",
                "description": "Exact Paddles run name (preferred when known).",
            },
        },
    ),
    _tool(
        "search_jobs",
        "Search jobs across runs (or within one run via run_name) and return "
        "compact jobs plus OS summary and top failure reasons. Supports "
        "date_start/date_end or period filters. Use for cross-run failure / "
        "OS / machine questions.",
        _JOB_SEARCH_PROPS,
    ),
]

_TOOL_HANDLERS: dict[str, Callable[..., Any]] = {
    "search_testruns": search_testruns,
    "get_testrun_report": get_testrun_report,
    "search_jobs": search_jobs,
}


def _to_jsonable(value: Any) -> Any:
    """Convert dataclasses / dates into JSON-friendly structures."""
    if is_dataclass(value) and not isinstance(value, type):
        return _to_jsonable(asdict(value))
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            out_key = "pass" if key == "pass_" else key
            out[out_key] = _to_jsonable(item)
        return out
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _json_default(value: Any) -> Any:
    converted = _to_jsonable(value)
    if converted is value:
        return str(value)
    return converted


def _serialize_tool_result(result: Any) -> str:
    """JSON-encode a tool result, truncating oversized payloads."""
    if result is None:
        return json.dumps({"result": None, "note": "No data returned."})

    try:
        payload = json.dumps(result, default=_json_default)
    except TypeError:
        payload = json.dumps({"result": str(result)})

    if len(payload) <= DEFAULT_LLM_MAX_TOOL_CHARS:
        return payload

    if isinstance(result, dict):
        trimmed = dict(result)
        for key in (
            "jobs",
            "testruns",
            "daily_trends",
            "top_failed_jobs",
            "top_failed_testruns",
            "top_failed_runs",
            "active_testruns",
            "trends_by_suite",
            "top_failing_tests",
        ):
            if key in trimmed and isinstance(trimmed[key], list) and trimmed[key]:
                trimmed[key] = trimmed[key][:3]
                trimmed[f"{key}_truncated"] = True
                payload = json.dumps(trimmed, default=_json_default)
                if len(payload) <= DEFAULT_LLM_MAX_TOOL_CHARS:
                    return payload
        # Last resort: keep aggregates only.
        lean = {
            k: trimmed[k]
            for k in (
                "filters",
                "summary",
                "job_summary",
                "completed_job_summary",
                "testrun",
                "job_count",
                "count_returned",
                "pass_rate",
                "fail_rate",
                "cluster_health",
                "active_summary",
                "top_failure_reasons",
                "os_share_trends",
                "note",
                "result",
            )
            if k in trimmed
        }
        lean["truncated"] = True
        lean["omitted_keys"] = [
            k for k in result.keys() if k not in lean
        ]
        return json.dumps(lean, default=_json_default)

    if isinstance(result, list):
        truncated: list[Any] = []
        size = 2
        for item in result:
            chunk = json.dumps(item, default=_json_default)
            if size + len(chunk) + 1 > DEFAULT_LLM_MAX_TOOL_CHARS:
                break
            truncated.append(item)
            size += len(chunk) + 1
        return json.dumps(
            {
                "items": truncated,
                "truncated": True,
                "returned": len(truncated),
                "total": len(result),
            },
            default=_json_default,
        )

    return json.dumps(
        {
            "truncated": True,
            "preview": payload[:DEFAULT_LLM_MAX_TOOL_CHARS],
            "original_chars": len(payload),
        }
    )


def call_tool(
    name: str,
    arguments: dict[str, Any] | str | None = None,
    *,
    cache: dict[str, str] | None = None,
) -> str:
    """
    Execute a report stats tool by name and return a JSON string for the LLM.

    When ``cache`` is provided (conversation-scoped), identical tool+args
    reuse the prior JSON payload instead of hitting Paddles again.

    Unknown tools or execution errors are returned as JSON error objects
    rather than raised, so the model can recover.
    """
    handler = _TOOL_HANDLERS.get(name)
    if handler is None:
        return json.dumps({"error": f"Unknown tool: {name}"})

    if isinstance(arguments, str):
        try:
            if arguments.strip():
                json.loads(arguments)
        except json.JSONDecodeError as exc:
            return json.dumps({"error": f"Invalid tool arguments JSON: {exc}"})

    args = _coerce_tool_args(arguments)
    key = _cache_key(name, args)

    if cache is not None and key in cache:
        return _mark_cached(cache[key])

    # Reuse the latest result for this tool when args are empty / defaults only.
    latest_key = f"{name}:__latest__"
    if (
        cache is not None
        and latest_key in cache
        and not _normalize_args(args)
    ):
        return _mark_cached(cache[latest_key])

    try:
        payload = _serialize_tool_result(handler(**args))
    except TypeError as exc:
        return json.dumps({"error": f"Invalid arguments for {name}: {exc}"})
    except Exception as exc:
        return json.dumps({"error": f"{type(exc).__name__}: {exc}"})

    if cache is not None and not payload.startswith('{"error"'):
        cache[key] = payload
        cache[latest_key] = payload
    return payload


def tool_request_cached(
    name: str,
    arguments: dict[str, Any] | str | None,
    cache: dict[str, str] | None,
) -> bool:
    """Return True when ``call_tool`` would reuse the conversation cache."""
    if not cache:
        return False
    args = _coerce_tool_args(arguments)
    if _cache_key(name, args) in cache:
        return True
    latest_key = f"{name}:__latest__"
    return latest_key in cache and not _normalize_args(args)


def cached_data_blocks(cache: dict[str, str] | None) -> list[dict[str, Any]]:
    """Rebuild answer-stage data blocks from latest cached tool payloads."""
    if not cache:
        return []

    blocks: list[dict[str, Any]] = []
    for key, payload in cache.items():
        if key.endswith(":__latest__"):
            continue
        name, _, args_json = key.partition(":")
        try:
            args = json.loads(args_json) if args_json else {}
        except json.JSONDecodeError:
            args = {}
        if not isinstance(args, dict):
            args = {}
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            data = {"raw": payload}
        if isinstance(data, dict):
            data = {k: v for k, v in data.items() if k != "cached"}
        blocks.append(
            {
                "tool": name,
                "arguments": args,
                "result": data,
                "from_cache": True,
            }
        )

    if blocks:
        return blocks

    # Fall back to per-tool latest entries when only those exist.
    for key, payload in cache.items():
        if not key.endswith(":__latest__"):
            continue
        name = key[: -len(":__latest__")]
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            data = {"raw": payload}
        if isinstance(data, dict):
            data = {k: v for k, v in data.items() if k != "cached"}
        blocks.append(
            {
                "tool": name,
                "arguments": {},
                "result": data,
                "from_cache": True,
            }
        )
    return blocks


def tool_result_cached(payload: str) -> bool:
    """Return True when ``payload`` was served from the conversation cache."""
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return False
    return isinstance(data, dict) and bool(data.get("cached"))


def _coerce_tool_args(
    arguments: dict[str, Any] | str | None,
) -> dict[str, Any]:
    if arguments is None:
        return {}
    if isinstance(arguments, str):
        try:
            args = json.loads(arguments) if arguments.strip() else {}
        except json.JSONDecodeError:
            return {}
    else:
        args = dict(arguments)
    if not isinstance(args, dict):
        return {}
    return {k: v for k, v in args.items() if v is not None}


def _normalize_args(args: dict[str, Any]) -> dict[str, Any]:
    """Drop empty values so equivalent calls share a cache key."""
    normalized: dict[str, Any] = {}
    for key, value in args.items():
        if value is None or value == "":
            continue
        if key == "count":
            try:
                normalized[key] = int(value)
            except (TypeError, ValueError):
                normalized[key] = value
            continue
        normalized[key] = value
    return normalized


def _cache_key(name: str, args: dict[str, Any]) -> str:
    return (
        f"{name}:"
        + json.dumps(_normalize_args(args), sort_keys=True, default=str)
    )


def _mark_cached(payload: str) -> str:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return payload
    if isinstance(data, dict):
        data = {**data, "cached": True}
        return json.dumps(data, default=_json_default)
    return payload
