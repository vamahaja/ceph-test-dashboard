"""
Ceph Test Dashboard — landing / ops command center.

Cluster health, active runs, and job trends by OS for a selected time window.
Specialist pages own deep drill-down.
"""

from __future__ import annotations

from datetime import datetime, timezone

import streamlit as st

from libs.defaults import DEFAULT_TOP_ACTIVE_TESTRUNS
from libs.pulpito import base_url
from libs.refresh import get_catalog, utc_day_start
from libs.reports.jobs import JobsStats
from libs.reports.testruns import TestRunsStats
from libs.views import (
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

catalog = get_catalog()
runs = TestRunsStats.from_testruns(catalog.runs).posted_since(cutoff)
jobs = JobsStats.from_jobs(catalog.jobs).for_run_set(runs.testruns)

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
show_scope_caption(runs, jobs, loaded_at=catalog.loaded_at, now=now)

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
