"""Nightly regression status for scheduled runs of the configured user."""

from __future__ import annotations

from datetime import date, datetime, timezone

import streamlit as st

from libs.config import get_nightly_run_user
from libs.defaults import STATUS_FAILING
from libs.pulpito import base_url
from libs.refresh import get_catalog
from libs.reports.jobs import JobsStats
from libs.reports.testruns import TestRunsStats
from libs.reports.utils import as_utc
from libs.views import (
    sidebar_branch_select,
    sidebar_suite_filter,
    sidebar_time_window,
    show_active_runs,
    show_cluster_health,
    show_daily_trends,
    show_job_mix,
    show_needs_attention,
    show_scope_caption,
    show_status_filtered_runs,
    sync_query_params,
)

NIGHTLY_RUN_COLUMNS = (
    "scheduled_date",
    "name",
    "branch",
    "suite",
    "status",
    "user",
    "total_jobs",
    "posted",
)


def _nightly_run_scope(rows, user: str, start: date, end: date, branch: str = ""):
    scoped = TestRunsStats.from_testruns(rows).filtered(
        date_start=start,
        date_end=end,
        on="scheduled",
        user=user,
        scheduled_only=True,
    )
    if branch:
        scoped = [run for run in scoped if run.branch == branch]
    return scoped


st.markdown(
    "<h1 style='text-align: center;'>Nightly Regression Status</h1>",
    unsafe_allow_html=True,
)
st.markdown(
    "Track standard scheduled nightly regression runs and quickly identify failures "
    "or runs that still need attention."
)

st.sidebar.header("Filters")

nightly_user = get_nightly_run_user()
time_window = sidebar_time_window(prefix="nightly")
start_date, end_date = time_window.start, time_window.end

catalog = get_catalog()
payload_runs = _nightly_run_scope(
    catalog.runs, nightly_user, start_date, end_date
)
loaded_at = catalog.loaded_at
all_runs = TestRunsStats.from_testruns(payload_runs)

if not all_runs.testruns:
    st.info(
        f"No standard scheduled nightly regression runs for user `{nightly_user}` "
        f"in the selected window ({time_window.label})."
    )
    st.stop()

branches = sorted({run.branch for run in all_runs.testruns if run.branch})
if not branches:
    st.warning("No branches found in the selected nightly window.")
    st.stop()

selected_branch = sidebar_branch_select(branches, prefix="nightly")
branch_runs = all_runs.for_branch(selected_branch)
all_suites = sorted({run.suite for run in branch_runs.testruns if run.suite})
selected_suites = sidebar_suite_filter(
    all_suites,
    prefix="nightly",
    reset_token=selected_branch,
)

all_jobs = JobsStats.from_jobs(catalog.jobs)
runs = branch_runs.for_suites(selected_suites)
jobs = all_jobs.for_run_set(runs.testruns)

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
    }
)

if not runs.testruns:
    st.warning("No nightly runs match the selected filters.")
    st.stop()

if not jobs.jobs:
    st.warning("No job data available for the selected nightly runs.")
    st.stop()

now = datetime.now(timezone.utc)
pulpito = base_url()
health = runs.cluster_health(jobs, now=now)
window_label = f"{selected_branch} · {time_window.label}"

show_cluster_health(
    health,
    heading=f"Nightly health · {window_label}",
    show_branch_chip=False,
    show_worst_branch=False,
)
show_scope_caption(runs, jobs, loaded_at=loaded_at, now=now)
st.caption(f"Scheduled runs owned by `{nightly_user}`.")

alerting = [run for run in runs.testruns if run.is_alerting]
failed = [run for run in runs.testruns if run.status in STATUS_FAILING]
active = [run for run in runs.testruns if run.is_active]
if alerting:
    st.error(
        f"{len(alerting)} nightly runs require attention: "
        f"{len(active)} still active and {len(failed)} failed."
    )
else:
    st.success("All selected nightly regression runs completed successfully.")

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
        source="nightly",
        show_worst_branches=False,
    )

with tab_mix:
    show_job_mix(jobs)

with tab_runs:
    st.subheader("Active runs")
    show_active_runs(runs, pulpito, now=now, collapse_table=True)
    st.divider()
    by_name = sorted(runs.testruns, key=lambda run: run.name or "")
    ordered = sorted(
        by_name,
        key=lambda run: as_utc(run.scheduled)
        or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    show_status_filtered_runs(
        ordered,
        pulpito,
        prefix="nightly",
        columns=NIGHTLY_RUN_COLUMNS,
        heading="Nightly runs",
    )
