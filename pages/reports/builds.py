"""Build analysis for a branch, suite mix, and commit SHA."""

from __future__ import annotations

from datetime import datetime, timezone

import streamlit as st

from libs.config import get_release_branches
from libs.pulpito import base_url
from libs.refresh import get_catalog, utc_day_start
from libs.reports.jobs import JobsStats
from libs.reports.testruns import TestRunsStats
from libs.reports.utils import as_utc
from libs.views import (
    sidebar_branch_select,
    sidebar_sha_select,
    sidebar_suite_filter,
    sidebar_time_window,
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

BUILD_RUN_COLUMNS = (
    "name",
    "status",
    "suite",
    "sha",
    "user",
    "machine_type",
    "total_jobs",
    "posted",
)


st.markdown(
    "<h1 style='text-align: center;'>Build Analysis</h1>",
    unsafe_allow_html=True,
)
st.markdown(
    "Isolate and evaluate testing metrics for a specific Ceph build artifact or commit SHA."
)

st.sidebar.header("Filters")

time_window = sidebar_time_window(prefix="builds")
start_date, end_date = time_window.start, time_window.end

catalog = get_catalog()
window_runs = TestRunsStats.from_testruns(catalog.runs).posted_since(
    utc_day_start(start_date)
)
all_jobs = JobsStats.from_jobs(catalog.jobs)
loaded_at = catalog.loaded_at
if not window_runs.testruns:
    st.warning(
        f"No runs found in the selected window ({time_window.label})."
    )
    st.stop()

release_branches = {name.lower() for name in get_release_branches()}
branches = sorted(
    {
        run.branch
        for run in window_runs.testruns
        if run.branch and run.branch.lower() not in release_branches
    }
)
if not branches:
    st.warning("No non-release branches found in the selected window.")
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
        "window": time_window.query,
        "from": None,
        "to": None,
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
window_label = f"{selected_branch} · {time_window.label}"
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
        columns=BUILD_RUN_COLUMNS,
        heading="Runs",
    )
