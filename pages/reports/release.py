"""Release health for stable Ceph branches (tentacle, squid, umbrella)."""

from __future__ import annotations

from datetime import date, datetime, timezone

import streamlit as st

from libs.config import get_release_branches
from libs.exceptions import ConfigError, PaddlesAPIError
from libs.pulpito import base_url
from libs.refresh import (
    ensure_payload,
    new_store,
    patch_due,
    refresh_every,
    utc_day_end_exclusive,
    utc_day_start,
)
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

_RELEASE_RUN_COLUMNS = (
    "name",
    "status",
    "suite",
    "sha",
    "machine_type",
    "user",
    "total_jobs",
    "posted",
)


@st.cache_resource
def _release_runs_store() -> dict:
    return new_store()


@st.cache_resource
def _release_jobs_store() -> dict:
    return new_store()


def _ensure_release_runs(branch: str, start: date, end: date):
    """Load posted runs for one release branch (no per-run job fetch)."""

    def load_full():
        runs = TestRunsStats.posted_between(start, end, branch=branch)
        return runs.testruns, []

    def load_recent(patch_since: datetime):
        runs = TestRunsStats.since(patch_since, branch=branch)
        return runs.testruns, []

    return ensure_payload(
        _release_runs_store(),
        key=(branch, start.isoformat(), end.isoformat()),
        load_full=load_full,
        load_recent=load_recent,
        keep_since=utc_day_start(start),
        keep_until=utc_day_end_exclusive(end),
        spinner_full=f"Loading {branch} release runs…",
    )


def _ensure_release_jobs(
    branch: str,
    start: date,
    end: date,
    testruns: list,
):
    """Fetch jobs only for the selected branch's runs."""

    def load_full():
        jobs = JobsStats.for_testruns(testruns)
        return testruns, jobs.jobs

    def load_recent(patch_since: datetime):
        runs = TestRunsStats.since(patch_since, branch=branch)
        jobs = JobsStats.for_testruns(runs.testruns)
        return runs.testruns, jobs.jobs

    return ensure_payload(
        _release_jobs_store(),
        key=(branch, start.isoformat(), end.isoformat()),
        load_full=load_full,
        load_recent=load_recent,
        keep_since=utc_day_start(start),
        keep_until=utc_day_end_exclusive(end),
        spinner_full=f"Loading jobs for `{branch}`…",
    )


@st.fragment(run_every=refresh_every())
def _periodic_release_refresh() -> None:
    if patch_due(_release_runs_store()) or patch_due(_release_jobs_store()):
        st.rerun()


st.markdown(
    "<h1 style='text-align: center;'>📦 Release Health Dashboard</h1>",
    unsafe_allow_html=True,
)
st.markdown(
    "Monitor the overall health and pass/fail ratios of a stable Ceph release branch."
)

st.sidebar.header("Filters")

branches = get_release_branches()
selected_branch = sidebar_branch_select(branches, prefix="release")

time_window = sidebar_time_window(prefix="release")
start_date, end_date = time_window.start, time_window.end

try:
    payload_runs, _, loaded_at = _ensure_release_runs(
        selected_branch, start_date, end_date
    )
except (PaddlesAPIError, ConfigError) as exc:
    st.warning(f"Could not load release data: {exc}")
    st.stop()

all_runs = TestRunsStats.from_testruns(payload_runs)

if not all_runs.testruns:
    st.warning(
        f"No runs found for branch **{selected_branch}** "
        f"in the selected window ({time_window.label})."
    )
    st.stop()

try:
    _, payload_jobs, jobs_loaded_at = _ensure_release_jobs(
        selected_branch, start_date, end_date, all_runs.testruns
    )
except (PaddlesAPIError, ConfigError) as exc:
    st.warning(f"Could not load release jobs: {exc}")
    st.stop()

_periodic_release_refresh()

loaded_at = jobs_loaded_at or loaded_at
all_jobs = JobsStats.from_jobs(payload_jobs)

all_suites = sorted({run.suite for run in all_runs.testruns if run.suite})
selected_suites = sidebar_suite_filter(
    all_suites,
    prefix="release",
    reset_token=selected_branch,
)

suite_runs = all_runs.for_suites(selected_suites)
sha_values = sorted(
    {(run.sha_short or "unknown") for run in suite_runs.testruns}
)
selected_sha = sidebar_sha_select(sha_values, prefix="release")
runs = suite_runs.for_sha(selected_sha) if selected_sha else suite_runs
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
        "sha": selected_sha or None,
    }
)

if not runs.testruns:
    st.warning("No runs found for the selected filters.")
    st.stop()

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
    heading=f"Release health · {window_label}",
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
        source="release",
        show_worst_branches=False,
    )

with tab_mix:
    show_job_mix(jobs)
    st.divider()
    st.subheader("Results by Commit SHA")
    if selected_sha:
        st.caption(f"Filtered to SHA **{selected_sha}**.")
        st.page_link(
            "pages/reports/builds.py",
            label="Open Builds report →",
        )
    show_sha_results(jobs, title=f"Pass / Fail per Commit SHA — {selected_branch}")

with tab_runs:
    st.subheader("Active runs")
    show_active_runs(runs, pulpito, now=now, collapse_table=True)
    st.divider()
    ordered = sorted(
        runs.testruns,
        key=lambda run: as_utc(run.posted)
        or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    show_status_filtered_runs(
        ordered,
        pulpito,
        prefix="release",
        columns=_RELEASE_RUN_COLUMNS,
        heading="Runs",
    )
