"""
Ceph Test Dashboard — landing / ops command center.

Cluster health, active runs, and job trends by OS for a selected time window.
Specialist pages own deep drill-down.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import streamlit as st

from libs.defaults import DEFAULT_TOP_ACTIVE_TESTRUNS
from libs.exceptions import ConfigError, PaddlesAPIError
from libs.pulpito import base_url
from libs.refresh import (
    ensure_payload,
    new_store,
    periodic_rerun,
    refresh_every,
    utc_day_start,
)
from libs.reports.jobs import JobsStats
from libs.reports.testruns import TestRunsStats
from libs.views import (
    TIME_WINDOW_MAX_DAYS,
    show_active_runs,
    show_cluster_health,
    show_daily_trends,
    show_job_mix,
    show_needs_attention,
    show_scope_caption,
    sidebar_time_window,
    sync_query_params,
)

_ACTIVE_TABLE_CAP = DEFAULT_TOP_ACTIVE_TESTRUNS


@st.cache_resource
def _overview_store() -> dict:
    """Process-wide overview payload; patched with recent runs/jobs on an interval."""
    return new_store()


def _ensure_overview_payload() -> tuple[list, list, datetime | None]:
    """Full 30-day load once, then merge recent runs/jobs when the interval elapses."""
    store = _overview_store()
    now = datetime.now(timezone.utc)
    keep_since = utc_day_start(
        now.date() - timedelta(days=TIME_WINDOW_MAX_DAYS - 1)
    )

    def load_full():
        runs = TestRunsStats.since(keep_since)
        jobs = JobsStats.for_testruns(runs.testruns)
        return runs.testruns, jobs.jobs

    def load_recent(patch_since: datetime):
        runs = TestRunsStats.since(patch_since)
        jobs = JobsStats.for_testruns(runs.testruns)
        return runs.testruns, jobs.jobs

    return ensure_payload(
        store,
        key="overview",
        load_full=load_full,
        load_recent=load_recent,
        keep_since=keep_since,
        spinner_full="Loading overview data…",
        spinner_patch=(
            f"Refreshing last {int(refresh_every().total_seconds() // 60)} "
            "minutes of overview data…"
        ),
    )


@st.fragment(run_every=refresh_every())
def _periodic_overview_refresh() -> None:
    """Rerun the page when the configured interval elapses so the patch can apply."""
    periodic_rerun(_overview_store())


st.markdown(
    "<h1 style='text-align: center;'>Ceph Test Dashboard</h1>",
    unsafe_allow_html=True,
)
st.markdown(
    "High-level **lab health**, **active runs**, and **job trends**. "
    "Use Nightly, Hardware, and Coverage for deep drill-down."
)

st.sidebar.header("Filters")
time_window = sidebar_time_window(prefix="overview")
now = datetime.now(timezone.utc)
cutoff = utc_day_start(time_window.start)

try:
    payload_runs, payload_jobs, loaded_at = _ensure_overview_payload()
except (PaddlesAPIError, ConfigError) as exc:
    st.warning(f"Could not load overview data: {exc}")
    st.stop()

_periodic_overview_refresh()

runs = TestRunsStats.from_testruns(payload_runs).posted_since(cutoff)
jobs = JobsStats.from_jobs(payload_jobs).for_run_set(runs.testruns)

if not runs.testruns:
    st.warning(f"No runs found in the selected window ({time_window.label}).")
    st.stop()

if not jobs.jobs:
    st.warning("No job data available for runs in the selected window.")
    st.stop()

pulpito = base_url()
health = runs.cluster_health(jobs, now=now)

show_cluster_health(
    health,
    heading=f"Cluster health · {time_window.label}",
)
show_scope_caption(runs, jobs, loaded_at=loaded_at, now=now)

sync_query_params(
    {
        "window": time_window.query,
        "branch": None,
    }
)

tab_attention, tab_active, tab_mix = st.tabs(
    ["Needs attention", "Active runs", "Job mix"]
)

with tab_attention:
    st.subheader("Daily trend")
    show_daily_trends(jobs)
    st.divider()
    st.subheader("Needs attention")
    show_needs_attention(runs, jobs, pulpito, source="overview")

with tab_active:
    show_active_runs(runs, pulpito, now=now, cap=_ACTIVE_TABLE_CAP)

with tab_mix:
    show_job_mix(jobs)
