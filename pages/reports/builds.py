"""Build analysis for a branch, suite mix, and commit SHA."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import streamlit as st

from libs.exceptions import ConfigError, PaddlesAPIError
from libs.pulpito import base_url
from libs.refresh import (
    ensure_payload,
    new_store,
    periodic_rerun,
    refresh_every,
    utc_day_end_exclusive,
    utc_day_start,
)
from libs.reports.jobs import JobsStats
from libs.reports.testruns import TestRunsStats
from libs.reports.utils import as_utc
from libs.views import (
    sidebar_branch_select,
    sidebar_date_range,
    sidebar_sha_select,
    sidebar_suite_filter,
    show_active_runs,
    show_cluster_health,
    show_daily_trends,
    show_job_mix,
    show_needs_attention,
    show_scope_caption,
    show_sha_results,
    show_status_filtered_runs,
    sync_query_params,
)

_BUILD_RUN_COLUMNS = (
    "name",
    "status",
    "suite",
    "sha",
    "user",
    "machine_type",
    "total_jobs",
    "posted",
)


@st.cache_resource
def _builds_store() -> dict:
    return new_store()


def _ensure_builds_payload(start: date, end: date):
    """Full window load once, then merge recent runs/jobs on the refresh interval."""

    def load_full():
        runs = TestRunsStats.posted_between(start, end)
        jobs = JobsStats.for_testruns(runs.testruns)
        return runs.testruns, jobs.jobs

    def load_recent(patch_since: datetime):
        runs = TestRunsStats.since(patch_since)
        jobs = JobsStats.for_testruns(runs.testruns)
        return runs.testruns, jobs.jobs

    return ensure_payload(
        _builds_store(),
        key=(start.isoformat(), end.isoformat()),
        load_full=load_full,
        load_recent=load_recent,
        keep_since=utc_day_start(start),
        keep_until=utc_day_end_exclusive(end),
        spinner_full="Loading recent runs…",
    )


@st.fragment(run_every=refresh_every())
def _periodic_builds_refresh() -> None:
    periodic_rerun(_builds_store())


st.markdown(
    "<h1 style='text-align: center;'>Build Analysis</h1>",
    unsafe_allow_html=True,
)
st.markdown(
    "Isolate and evaluate testing metrics for a specific Ceph build artifact or commit SHA."
)

st.sidebar.header("Filters")

today = date.today()
start_date, end_date = sidebar_date_range(
    prefix="builds",
    default_start=today - timedelta(days=7),
    default_end=today,
)

try:
    payload_runs, payload_jobs, loaded_at = _ensure_builds_payload(
        start_date, end_date
    )
except (PaddlesAPIError, ConfigError) as exc:
    st.warning(f"Could not load build data: {exc}")
    st.stop()

_periodic_builds_refresh()

window_runs = TestRunsStats.from_testruns(payload_runs)
all_jobs = JobsStats.from_jobs(payload_jobs)
if not window_runs.testruns:
    st.warning(
        f"No runs found between {start_date} and {end_date}."
    )
    st.stop()

branches = sorted({run.branch for run in window_runs.testruns if run.branch})
if not branches:
    st.warning("No branches found in the selected window.")
    st.stop()

selected_branch = sidebar_branch_select(branches, prefix="builds")
branch_runs = window_runs.for_branch(selected_branch)
if not branch_runs.testruns:
    st.warning(f"No runs found for branch **{selected_branch}**.")
    st.stop()

all_suites = sorted({run.suite for run in branch_runs.testruns if run.suite})
selected_suites = sidebar_suite_filter(
    all_suites,
    prefix="builds",
    reset_token=selected_branch,
)

suite_runs = branch_runs.for_suites(selected_suites)
sha_values = sorted(
    {(run.sha_short or "unknown") for run in suite_runs.testruns}
)
selected_sha = sidebar_sha_select(sha_values, prefix="builds")
runs = suite_runs.for_sha(selected_sha) if selected_sha else suite_runs

sync_query_params(
    {
        "branch": selected_branch,
        "from": start_date.isoformat(),
        "to": end_date.isoformat(),
        "suite": (
            None
            if set(selected_suites) == set(all_suites)
            else ",".join(selected_suites)
        ),
        "sha": selected_sha or None,
    }
)

if not runs.testruns:
    st.warning("No runs match the selected filters.")
    st.stop()

jobs = all_jobs.for_run_set(runs.testruns)
if not jobs.jobs:
    st.warning("No job data available for the selected runs.")
    st.stop()

now = datetime.now(timezone.utc)
pulpito = base_url()
health = runs.cluster_health(jobs, now=now)
window_label = f"{selected_branch} · {start_date:%Y-%m-%d} → {end_date:%Y-%m-%d}"
if selected_sha:
    window_label = f"{window_label} · {selected_sha}"

show_cluster_health(
    health,
    heading=f"Build health · {window_label}",
    show_branch_chip=False,
    show_worst_branch=False,
)
show_scope_caption(runs, jobs, loaded_at=loaded_at, now=now)

tab_attention, tab_mix, tab_runs = st.tabs(
    ["Needs attention", "Job mix", "Runs"]
)

with tab_attention:
    st.subheader("Daily trend")
    show_daily_trends(jobs)
    st.divider()
    st.subheader("Needs attention")
    show_needs_attention(
        runs,
        jobs,
        pulpito,
        source="builds",
        show_worst_branches=False,
    )

with tab_mix:
    show_job_mix(jobs)
    st.divider()
    st.subheader("Per-SHA comparison")
    if selected_sha:
        st.caption(f"Filtered to SHA **{selected_sha}**.")
    show_sha_results(
        jobs,
        title=f"Pass / Fail per SHA — {selected_branch}",
        show_table=True,
    )

with tab_runs:
    st.subheader("Active runs")
    show_active_runs(runs, pulpito, now=now, collapse_table=True)
    st.divider()
    by_posted = sorted(
        runs.testruns,
        key=lambda run: as_utc(run.posted)
        or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    ordered = sorted(
        by_posted,
        key=lambda run: run.sha_short or "",
        reverse=True,
    )
    show_status_filtered_runs(
        ordered,
        pulpito,
        prefix="builds",
        columns=_BUILD_RUN_COLUMNS,
        heading="Runs",
    )
