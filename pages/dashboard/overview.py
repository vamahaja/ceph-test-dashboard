"""
Ceph Test Dashboard — landing / ops command center.

Rolling-window cluster health, active runs, and job trends by OS.
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
)
from libs.reports.jobs import JobsStats
from libs.reports.testruns import TestRunsStats
from libs.views import (
    query_str,
    show_active_runs,
    show_cluster_health,
    show_daily_trends,
    show_job_mix,
    show_needs_attention,
    show_scope_caption,
    sync_query_params,
)

_WINDOW_OPTIONS = {
    "Last 24 hours": timedelta(hours=24),
    "Last 7 days": timedelta(days=7),
    "Last 30 days": timedelta(days=30),
}

_WINDOW_BY_QUERY = {
    "24h": "Last 24 hours",
    "7d": "Last 7 days",
    "30d": "Last 30 days",
}
_QUERY_BY_WINDOW = {label: key for key, label in _WINDOW_BY_QUERY.items()}

_ACTIVE_TABLE_CAP = DEFAULT_TOP_ACTIVE_TESTRUNS


@st.cache_resource
def _overview_store() -> dict:
    """Process-wide overview payload; patched with recent runs/jobs on an interval."""
    return new_store()


def _ensure_overview_payload() -> tuple[list, list, datetime | None]:
    """Full 30-day load once, then merge recent runs/jobs when the interval elapses."""
    store = _overview_store()
    now = datetime.now(timezone.utc)
    keep_since = now - max(_WINDOW_OPTIONS.values())

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
if "overview_window" not in st.session_state:
    st.session_state["overview_window"] = _WINDOW_BY_QUERY.get(
        query_str("window"), "Last 7 days"
    )
window_label = st.sidebar.selectbox(
    "Time window",
    list(_WINDOW_OPTIONS.keys()),
    key="overview_window",
)
now = datetime.now(timezone.utc)
cutoff = now - _WINDOW_OPTIONS[window_label]

try:
    payload_runs, payload_jobs, loaded_at = _ensure_overview_payload()
except (PaddlesAPIError, ConfigError) as exc:
    st.warning(f"Could not load overview data: {exc}")
    st.stop()

_periodic_overview_refresh()

all_runs = TestRunsStats.from_testruns(payload_runs).posted_since(cutoff)
all_jobs = JobsStats.from_jobs(payload_jobs).for_run_set(all_runs.testruns)

if not all_runs.testruns:
    st.warning(f"No runs found in the selected window ({window_label}).")
    st.stop()

if not all_jobs.jobs:
    st.warning("No job data available for runs in the selected window.")
    st.stop()

branches = sorted({run.branch for run in all_runs.testruns if run.branch})
branch_options = ["All"] + branches
if "overview_branch" not in st.session_state:
    qp_branch = query_str("branch")
    st.session_state["overview_branch"] = (
        qp_branch if qp_branch in branch_options else "All"
    )
elif st.session_state["overview_branch"] not in branch_options:
    st.session_state["overview_branch"] = "All"
branch_label = st.sidebar.selectbox(
    "Branch",
    branch_options,
    key="overview_branch",
)
branch = "" if branch_label == "All" else branch_label
runs = all_runs.for_branch(branch)
jobs = all_jobs.for_branch(branch)

if not runs.testruns:
    st.warning(f"No runs found for branch `{branch_label}`.")
    st.stop()

if not jobs.jobs:
    st.warning(f"No job data available for branch `{branch_label}`.")
    st.stop()

pulpito = base_url()
health = runs.cluster_health(jobs, now=now)

show_cluster_health(
    health,
    heading=f"Cluster health · {window_label}",
)
show_scope_caption(runs, jobs, loaded_at=loaded_at, now=now)

sync_query_params(
    {
        "window": _QUERY_BY_WINDOW.get(window_label),
        "branch": None if branch_label == "All" else branch_label,
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
