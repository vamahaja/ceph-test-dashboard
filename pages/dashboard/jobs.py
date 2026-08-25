"""Job details — per-run jobs and failure-reason drill-in."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from libs.config import get_cache_ttl
from libs.defaults import DEFAULT_REPORT_COUNT, status_row_styles
from libs.exceptions import ConfigError, PaddlesAPIError
from libs.pulpito import (
    base_url,
    job_link_column,
    job_url,
    run_link_column,
    run_url,
)
from libs.reports.jobs import JobsStats
from libs.reports.models import Job, JobsSummary
from libs.reports.testruns import TestRunsStats
from libs.reports.utils import format_duration

_JOB_COLUMNS = (
    "job_id",
    "status",
    "description",
    "machine_type",
    "os_type",
    "duration",
    "owner",
    "branch",
    "suite",
    "failure_reason",
    "posted",
)

_DRILL_COLUMNS = (
    "job_id",
    "run_name",
    "status",
    "description",
    "machine_type",
    "os_type",
    "duration",
    "failure_reason",
)


def _query_str(key: str) -> str:
    value = st.query_params.get(key)
    if isinstance(value, list):
        return str(value[0] or "")
    return str(value or "")


@st.cache_data(ttl=get_cache_ttl(), show_spinner=False)
def _load_latest_runs() -> TestRunsStats:
    return TestRunsStats(count=DEFAULT_REPORT_COUNT)


@st.cache_data(ttl=get_cache_ttl(), show_spinner=False)
def _load_jobs_for_run(run_name: str) -> JobsStats:
    return JobsStats.for_run(run_name)


def _jobs_frame(
    jobs: list[Job],
    pulpito: str | None,
    columns: tuple[str, ...],
    *,
    default_run: str = "",
) -> pd.DataFrame:
    rows = []
    for job in jobs:
        run_name = job.run_name or default_run
        rows.append(
            {
                "job_id": job_url(run_name, job.job_id, base=pulpito),
                "run_name": run_url(run_name, base=pulpito),
                "status": job.status,
                "description": job.description,
                "machine_type": job.machine_type,
                "os_type": job.os_type,
                "duration": format_duration(job.duration),
                "owner": job.owner,
                "branch": job.branch,
                "suite": job.suite,
                "failure_reason": job.failure_reason,
                "posted": job.posted,
            }
        )
    return pd.DataFrame(rows, columns=list(columns))


def _job_column_config(pulpito: str | None, *, include_run: bool) -> dict:
    config = job_link_column("job_id", "job_id", base=pulpito)
    if include_run:
        config.update(run_link_column("run_name", "run_name", base=pulpito))
    return config


def _show_jobs_table(
    jobs: list[Job],
    pulpito: str | None,
    columns: tuple[str, ...],
    *,
    default_run: str = "",
    include_run: bool,
) -> None:
    table = _jobs_frame(jobs, pulpito, columns, default_run=default_run)
    st.dataframe(
        table.style.apply(status_row_styles, axis=1),
        column_config=_job_column_config(pulpito, include_run=include_run),
        width="stretch",
        hide_index=True,
        height=min(800, 38 + max(len(table), 1) * 35),
    )


def _show_jobs_scorecard(summary: JobsSummary) -> None:
    c1, c2, c3, c4, c5, c6, c7 = st.columns(7)
    c1.metric("Total", summary.cnt_jobs)
    c2.metric("Passed", summary.cnt_pass)
    c3.metric("Failed", summary.cnt_fail)
    c4.metric("Dead", summary.cnt_dead)
    c5.metric("Running", summary.cnt_running)
    c6.metric("Waiting", summary.cnt_waiting)
    c7.metric("Queued", summary.cnt_queued)


def _clear_failure_drill() -> None:
    """Drop failure drill-in state used by Overview / Nightly / Builds."""
    st.session_state.pop("drill_run_names", None)
    st.session_state.pop("drill_run_records", None)
    st.query_params.clear()
    st.rerun()


st.markdown(
    "<h1 style='text-align: center;'>Job Details</h1>",
    unsafe_allow_html=True,
)

pulpito = base_url()
failure_filter = _query_str("failure_reason")
source_filter = _query_str("source")
run_filter = _query_str("run")
job_filter = _query_str("job_id")

# Failure-reason drill-in from Overview / Nightly / Builds. Keep this
# contract unchanged: query ``failure_reason`` + ``source``, session
# ``drill_run_names``, then ``JobsStats.for_run_names`` + ``matching_failure``.
if failure_filter:
    st.info(f"Showing jobs with failure: **{failure_filter}**")
    if source_filter:
        st.caption(f"Opened from **{source_filter}**.")
    if st.button("← Clear filter", key="jobs_clear_failure"):
        _clear_failure_drill()

    drill_run_names = st.session_state.get("drill_run_names", [])
    if not drill_run_names:
        source_label = source_filter or "report"
        st.warning(f"No run names passed from the {source_label} page.")
        st.stop()

    try:
        with st.spinner("Loading jobs for impacted runs…"):
            stats = JobsStats.for_run_names(list(drill_run_names))
    except (PaddlesAPIError, ConfigError) as exc:
        st.warning(f"Could not load job data: {exc}")
        st.stop()

    if not stats.jobs:
        st.info("No jobs found for the impacted runs.")
        st.stop()

    matching = stats.matching_failure(failure_filter)
    if not matching:
        st.info("No jobs match the selected failure reason.")
        st.stop()

    fail_n = sum(1 for job in matching if job.status == "fail")
    dead_n = sum(1 for job in matching if job.status == "dead")
    run_n = len({job.run_name for job in matching if job.run_name})
    branch_n = len({job.branch for job in matching if job.branch})
    suite_n = len({job.suite for job in matching if job.suite})
    machine_n = len({job.machine_type for job in matching if job.machine_type})

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Matching Failed Jobs", len(matching))
    m2.metric("Fail / Dead", f"{fail_n} / {dead_n}")
    m3.metric("Runs", run_n)
    m4.metric("Branches", branch_n)
    st.caption(f"{suite_n} suites · {machine_n} machines")

    if st.session_state.get("drill_run_records"):
        if st.button("View impacted runs →", key="jobs_to_testruns"):
            st.switch_page(
                "pages/dashboard/testruns.py",
                query_params={
                    "failure_reason": failure_filter,
                    "source": source_filter or "jobs",
                },
            )

    st.divider()
    _show_jobs_table(matching, pulpito, _DRILL_COLUMNS, include_run=True)

elif run_filter:
    st.info(f"Showing jobs for run `{run_filter}`")
    if source_filter:
        st.caption(f"Opened from **{source_filter}**.")
    pulpito_link = run_url(run_filter, base=pulpito)
    if pulpito_link.startswith("http"):
        st.markdown(f"[Open run in Pulpito]({pulpito_link})")
    if st.button("← Latest runs", key="jobs_clear_run"):
        st.query_params.clear()
        st.rerun()

    try:
        stats = _load_jobs_for_run(run_filter)
    except (PaddlesAPIError, ConfigError) as exc:
        st.warning(f"Could not load jobs for `{run_filter}`: {exc}")
        st.stop()

    if not stats.jobs:
        st.info(f"No jobs exist for run `{run_filter}`.")
        st.stop()

    jobs = stats.jobs
    if job_filter:
        jobs = [job for job in jobs if str(job.job_id) == job_filter]
        if not jobs:
            st.warning(f"No job `{job_filter}` in this run. Showing all jobs.")
            jobs = stats.jobs
        else:
            st.caption(f"Filtered to job **{job_filter}**.")

    _show_jobs_scorecard(stats.summary)
    st.caption(f"Average duration {format_duration(stats.avg_duration)}.")
    st.divider()
    _show_jobs_table(
        jobs,
        pulpito,
        _JOB_COLUMNS,
        default_run=run_filter,
        include_run=False,
    )

else:
    try:
        runs = _load_latest_runs()
    except (PaddlesAPIError, ConfigError) as exc:
        st.warning(f"Could not load run data: {exc}")
        st.stop()

    run_rows = [run for run in runs.testruns if run.name]
    if not run_rows:
        st.info("No runs found.")
        st.stop()

    st.caption(
        f"Latest **{len(run_rows)}** runs reported to Paddles. "
        "Pick a run to inspect its jobs."
    )
    labels = {
        run.name: (
            f"{run.status or '—'} · {run.branch or '—'} · "
            f"{run.suite or '—'} · {run.name}"
        )
        for run in run_rows
    }
    selected_run = st.selectbox(
        "Select a run to view its jobs:",
        [run.name for run in run_rows],
        format_func=lambda name: labels.get(name, name),
        key="jobs_run_select",
    )
    pulpito_link = run_url(selected_run, base=pulpito)
    if pulpito_link.startswith("http"):
        st.markdown(f"[Open run in Pulpito]({pulpito_link})")

    try:
        stats = _load_jobs_for_run(selected_run)
    except (PaddlesAPIError, ConfigError) as exc:
        st.warning(f"Could not load jobs for `{selected_run}`: {exc}")
        st.stop()

    if not stats.jobs:
        st.info(f"No jobs exist for run `{selected_run}`.")
        st.stop()

    _show_jobs_scorecard(stats.summary)
    st.caption(f"Average duration {format_duration(stats.avg_duration)}.")
    st.divider()
    _show_jobs_table(
        stats.jobs,
        pulpito,
        _JOB_COLUMNS,
        default_run=selected_run,
        include_run=False,
    )
