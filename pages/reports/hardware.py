"""Hardware reliability — machine-type-centric dashboard.

Primary filter is ``machine_type``. Paddles ``/jobs/?machine_type=`` ignores
that filter, so jobs are loaded for the posted window and scoped in memory.
Architecture comes from live Paddles ``/nodes/`` inventory.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

import pandas as pd
import plotly.express as px
import streamlit as st

from libs.config import get_hardware_config, get_refresh_seconds
from libs.defaults import STATUS_COLOR_MAP
from libs.exceptions import ConfigError, PaddlesAPIError
from libs.reports.hardware import HardwareStats
from libs.pulpito import base_url, job_link_column, job_url, run_link_column, run_url
from libs.refresh import get_catalog, utc_day_start
from libs.reports.jobs import JobsStats
from libs.reports.models import GroupReliabilityStat, Job
from libs.reports.testruns import TestRunsStats
from libs.reports.utils import as_utc
from libs.views import (
    show_active_runs,
    show_cluster_health,
    show_daily_trends,
    show_pass_heatmap,
    show_scope_caption,
    show_status_filtered_runs,
    sidebar_branch_filter,
    sidebar_machine_select,
    sidebar_suite_filter,
    sidebar_time_window,
    sync_query_params,
)

_HW = get_hardware_config()
_MIN_RUNS = _HW["min_runs"]

_HW_RUN_COLUMNS = (
    "name",
    "status",
    "branch",
    "suite",
    "sha",
    "user",
    "total_jobs",
    "posted",
)


@st.cache_data(ttl=get_refresh_seconds())
def _load_arch_map() -> dict[str, str]:
    return HardwareStats.load_arch_map()


def _table_height(rows: int, *, cap: int = 800, min_rows: int = 1) -> int:
    return min(cap, 38 + max(rows, min_rows) * 35)


def _reliability_frame(rows: list[GroupReliabilityStat], key_label: str) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                key_label: row.key,
                "Jobs": row.cnt_jobs,
                "Passed": row.cnt_pass,
                "Failed": row.cnt_fail,
                "Pass Rate (%)": row.pct_pass,
                "Fail Rate (%)": row.pct_fail,
                "Avg Duration (min)": round((row.avg_duration or 0) / 60, 1),
            }
            for row in rows
        ]
    )


def _status_by_group(jobs: list[Job], group: str) -> pd.DataFrame:
    counts: dict[tuple[str, str], int] = defaultdict(int)
    for job in jobs:
        key = getattr(job, group, "") or "unknown"
        counts[(key, job.status or "unknown")] += 1
    return pd.DataFrame(
        [
            {group: key, "status": status, "count": count}
            for (key, status), count in counts.items()
        ]
    )


def _show_reliability(jobs: JobsStats, group: str, *, key_label: str, title: str) -> None:
    rows = [row for row in jobs.reliability_by(group) if row.key != "unknown"]
    if not rows:
        st.info(f"No {key_label.lower()} data for this machine type.")
        return
    frame = _reliability_frame(rows, key_label)
    st.dataframe(frame, width="stretch", hide_index=True)

    st.divider()
    status_frame = _status_by_group(jobs.jobs, group)
    status_frame = status_frame[status_frame[group] != "unknown"]
    if not status_frame.empty:
        fig = px.bar(
            status_frame,
            x=group,
            y="count",
            color="status",
            color_discrete_map=STATUS_COLOR_MAP,
            barmode="stack",
            text_auto=True,
            title=title,
            labels={
                group: key_label,
                "count": "Jobs",
                "status": "Status",
            },
        )
        fig.update_layout(height=400, legend_title_text="Status")
        st.plotly_chart(fig, width="stretch")

    fig_pass = px.bar(
        frame.sort_values("Pass Rate (%)", ascending=True),
        x="Pass Rate (%)",
        y=key_label,
        orientation="h",
        text_auto=True,
        title=f"Pass Rate by {key_label}",
        labels={key_label: key_label, "Pass Rate (%)": "Pass Rate (%)"},
        color_discrete_sequence=[STATUS_COLOR_MAP["pass"]],
    )
    fig_pass.update_layout(
        height=max(280, 40 * len(frame)),
        xaxis_range=[0, 105],
    )
    st.plotly_chart(fig_pass, width="stretch")


def _drill_to_jobs(run_names: list[str], reason: str, *, key: str) -> None:
    if st.button(f"View {len(run_names)} Impacted Jobs →", key=key):
        st.session_state["drill_run_names"] = run_names
        st.switch_page(
            "pages/dashboard/jobs.py",
            query_params={"failure_reason": reason, "source": "hardware"},
        )


def _drill_to_runs(
    runs: TestRunsStats, run_names: list[str], reason: str, *, key: str
) -> None:
    if st.button(f"View {len(run_names)} Impacted Runs →", key=key):
        st.session_state["drill_run_names"] = run_names
        st.session_state["drill_run_records"] = runs.records_for_names(run_names)
        st.switch_page(
            "pages/dashboard/testruns.py",
            query_params={"failure_reason": reason, "source": "hardware"},
        )


st.markdown(
    "<h1 style='text-align: center;'>Hardware Reliability</h1>",
    unsafe_allow_html=True,
)
st.markdown(
    "Select a **machine type** to analyze suite stability for that lab class "
    "across branches, suites, and OS."
)

st.sidebar.header("Filters")

time_window = sidebar_time_window(prefix="hardware")
start_date, end_date = time_window.start, time_window.end

catalog = get_catalog()
try:
    arch_map = _load_arch_map()
except (PaddlesAPIError, ConfigError) as exc:
    st.warning(f"Could not load hardware data: {exc}")
    st.stop()

payload_runs = TestRunsStats.from_testruns(catalog.runs).posted_since(
    utc_day_start(start_date)
).testruns
loaded_at = catalog.loaded_at
window = HardwareStats.from_testruns_jobs(
    payload_runs, [], arch_by_machine_type=arch_map
)
if not window.runs.testruns:
    st.warning(f"No runs found in the selected window ({time_window.label}).")
    st.stop()

machine_types = window.machine_types()
if not machine_types:
    st.warning(
        f"No runs with a machine type found in the selected window ({time_window.label})."
    )
    st.stop()

selected_mt = sidebar_machine_select(
    machine_types,
    prefix="hardware",
    help_text="Only machine types with runs in the selected time window are shown.",
)
arch_label = window.architecture(selected_mt)
st.sidebar.caption(f"Architecture: **{arch_label}**")

scoped_runs = window.for_machine_type(selected_mt)
if not scoped_runs.runs.testruns:
    st.warning(f"No runs found for machine type **{selected_mt}**.")
    st.stop()

scoped = HardwareStats.from_testruns_jobs(
    scoped_runs.runs.testruns,
    catalog.jobs,
    arch_by_machine_type=arch_map,
)

all_branches = sorted({run.branch for run in scoped.runs.testruns if run.branch})
selected_branches = sidebar_branch_filter(
    all_branches,
    prefix="hardware",
    reset_token=selected_mt,
)
all_suites = sorted({run.suite for run in scoped.runs.testruns if run.suite})
selected_suites = sidebar_suite_filter(
    all_suites,
    prefix="hardware",
    reset_token=selected_mt,
)

runs = scoped.runs.for_branches(selected_branches).for_suites(selected_suites)
jobs = scoped.jobs.for_run_set(runs.testruns)

sync_query_params(
    {
        "machine": selected_mt,
        "window": time_window.query,
        "from": None,
        "to": None,
        "branch": (
            None
            if set(selected_branches) == set(all_branches)
            else ",".join(selected_branches)
        ),
        "suite": (
            None
            if set(selected_suites) == set(all_suites)
            else ",".join(selected_suites)
        ),
    }
)

if not selected_branches:
    st.warning("Select at least one branch.")
    st.stop()
if not selected_suites:
    st.warning("Select at least one suite.")
    st.stop()
if not runs.testruns:
    st.warning("No runs match the selected branch/suite filters.")
    st.stop()
if not jobs.jobs:
    st.warning(f"No job data available for **{selected_mt}**.")
    st.stop()

now = datetime.now(timezone.utc)
pulpito = base_url()
health = runs.cluster_health(jobs, now=now)
window_label = f"{selected_mt} · {time_window.label}"

show_cluster_health(
    health,
    heading=f"Hardware health · {window_label}",
    show_branch_chip=True,
    show_worst_branch=True,
)
show_scope_caption(runs, jobs, loaded_at=loaded_at, now=now)
st.caption(f"Architecture **{arch_label}**.")

n_runs = len(runs.testruns)
if n_runs < _MIN_RUNS:
    st.warning(
        f"Only **{n_runs} run{'s' if n_runs != 1 else ''}** found for "
        f"**{selected_mt}** in this window — statistics may not be reliable. "
        "Try a longer time window."
    )

tab_branch, tab_suite, tab_os, tab_fail, tab_runs = st.tabs(
    ["By Branch", "By Suite", "By OS", "Machine Errors", "Runs"]
)

completed = jobs.completed_stats

with tab_branch:
    st.subheader(f"Branch Comparison — {selected_mt}")
    st.caption("How this machine type performs across branches.")
    _show_reliability(
        completed,
        "branch",
        key_label="Branch",
        title=f"Job Status by Branch — {selected_mt}",
    )

with tab_suite:
    st.subheader(f"Suite Health — {selected_mt}")
    _show_reliability(
        completed,
        "suite",
        key_label="Suite",
        title=f"Job Status by Suite — {selected_mt}",
    )

with tab_os:
    st.subheader(f"OS Distribution — {selected_mt}")
    os_jobs = JobsStats.from_jobs(
        [
            job
            for job in completed.jobs
            if job.os_type and job.os_type != "unknown"
        ]
    )
    excluded_os = len(completed.jobs) - len(os_jobs.jobs)
    if excluded_os > 0:
        st.caption(
            f"{excluded_os} job{'s' if excluded_os != 1 else ''} excluded — "
            "no OS type recorded."
        )
    if not os_jobs.jobs:
        st.info("No OS type information available for this machine type.")
    else:
        _show_reliability(
            os_jobs,
            "os_type",
            key_label="OS Type",
            title=f"Job Status by OS — {selected_mt}",
        )
        st.divider()
        st.subheader("Branch × OS Pass Rate")
        show_pass_heatmap(
            os_jobs.pass_matrix(row="branch", col="os_type"),
            title=f"Branch × OS — {selected_mt}",
        )

with tab_fail:
    st.subheader("Daily trend")
    show_daily_trends(jobs)
    st.divider()
    st.subheader(f"Machine Errors — {selected_mt}")
    st.caption(
        "Lab/infrastructure failures only (dead jobs, reimaging, lock/SSH, "
        "provisioning timeouts). Product test failures are excluded."
    )
    error_jobs = jobs.machine_errors()
    if not error_jobs:
        st.info(
            f"No machine errors for **{selected_mt}** with the selected filters."
        )
    else:
        error_stats = JobsStats.from_jobs(error_jobs)
        reasons = error_stats.top_failure_reasons(n=None)
        f1, f2, f3 = st.columns(3)
        f1.metric("Machine Errors", len(error_jobs))
        f2.metric(
            "Branches Impacted",
            len({job.branch for job in error_jobs if job.branch}),
        )
        f3.metric(
            "Suites Impacted",
            len({job.suite for job in error_jobs if job.suite}),
        )

        st.divider()
        st.markdown("**Top Machine Error Reasons**")
        fail_frame = pd.DataFrame(
            [
                {
                    "Machine Error": row.reason,
                    "Jobs": row.count,
                    "Branches": row.branches_impacted,
                    "Suites": row.suites_impacted,
                    "Runs": row.runs_impacted,
                    "Share (%)": row.pct,
                }
                for row in reasons
            ]
        )
        event = st.dataframe(
            fail_frame,
            width="stretch",
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            height=_table_height(len(fail_frame), cap=500),
            key="hardware_machine_errors",
        )
        selected_rows = event.selection.rows if event.selection else []
        if selected_rows:
            reason = str(fail_frame.iloc[selected_rows[0]]["Machine Error"])
            matching = error_stats.matching_failure(reason)
            run_names = list(
                dict.fromkeys(job.run_name for job in matching if job.run_name)
            )
            btn_jobs, btn_runs = st.columns(2)
            with btn_jobs:
                _drill_to_jobs(run_names, reason, key="hardware_view_jobs")
            with btn_runs:
                _drill_to_runs(runs, run_names, reason, key="hardware_view_runs")

            st.markdown(f"**Jobs with:** `{reason[:120]}`")
            detail = pd.DataFrame(
                [
                    {
                        "Branch": job.branch or "unknown",
                        "Suite": job.suite or "unknown",
                        "OS": job.os_type or "—",
                        "Test": job.description or "—",
                        "Job ID": job_url(job.run_name, job.job_id, base=pulpito),
                        "Run": run_url(job.run_name, base=pulpito),
                        "Status": job.status,
                        "Posted": job.posted,
                    }
                    for job in sorted(
                        matching,
                        key=lambda job: as_utc(job.posted)
                        or datetime.min.replace(tzinfo=timezone.utc),
                        reverse=True,
                    )
                ]
            )
            st.dataframe(
                detail,
                column_config={
                    **job_link_column("Job ID", "Job ID", base=pulpito),
                    **run_link_column("Run", "Run", base=pulpito),
                },
                width="stretch",
                hide_index=True,
                height=_table_height(len(detail), cap=400),
            )

        st.divider()
        st.markdown("**Machine Errors by Branch**")
        by_branch: dict[str, int] = defaultdict(int)
        for job in error_jobs:
            by_branch[job.branch or "unknown"] += 1
        fail_branch = pd.DataFrame(
            [
                {"branch": branch, "errors": count}
                for branch, count in by_branch.items()
            ]
        ).sort_values("errors", ascending=False)
        fig_fb = px.bar(
            fail_branch,
            x="branch",
            y="errors",
            text_auto=True,
            title=f"Machine Errors by Branch — {selected_mt}",
            labels={"branch": "Branch", "errors": "Machine Errors"},
            color_discrete_sequence=[STATUS_COLOR_MAP["fail"]],
        )
        fig_fb.update_layout(height=360)
        st.plotly_chart(fig_fb, width="stretch")

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
        prefix="hardware",
        columns=_HW_RUN_COLUMNS,
        heading="Runs",
    )
