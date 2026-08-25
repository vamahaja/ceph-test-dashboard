"""
Ceph Test Dashboard — landing / ops command center.

Rolling-window cluster health, active runs, and job trends by OS.
Specialist pages own deep drill-down.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html import escape

import pandas as pd
import plotly.express as px
import streamlit as st

from libs.config import get_overview_refresh_minutes
from libs.defaults import (
    DEFAULT_HEALTH_STUCK_HOURS,
    DEFAULT_HEALTH_STUCK_HOURS_LONG,
    DEFAULT_TOP_ACTIVE_TESTRUNS,
    STATUS_COLOR_MAP,
    status_rgba,
    status_row_styles,
)
from libs.exceptions import ConfigError, PaddlesAPIError
from libs.pulpito import base_url, run_link_column, run_url
from libs.reports.jobs import JobsStats
from libs.reports.models import (
    ClusterHealthSnapshot,
    Job,
    JobsSummary,
    StatusShareTrend,
    TestRun,
)
from libs.reports.testruns import TestRunsStats
from libs.reports.utils import as_utc

_WINDOW_OPTIONS = {
    "Last 24 hours": timedelta(hours=24),
    "Last 7 days": timedelta(days=7),
    "Last 30 days": timedelta(days=30),
}

_ACTIVE_TABLE_CAP = DEFAULT_TOP_ACTIVE_TESTRUNS

_BADGE_STATUS = {
    "Healthy": "pass",
    "Degraded": "queued",
    "Critical": "fail",
    "Unknown": "unknown",
}


def _mix_bar_html(completed: JobsSummary) -> str:
    total = completed.cnt_jobs
    if not total:
        return (
            '<div style="height:10px;border-radius:999px;'
            'background:rgba(148,163,184,0.22)"></div>'
        )
    parts: list[str] = []
    for status, count in (
        ("pass", completed.cnt_pass),
        ("fail", completed.cnt_fail),
        ("dead", completed.cnt_dead),
    ):
        if count <= 0:
            continue
        width = 100.0 * count / total
        parts.append(
            f'<div style="width:{width:.3f}%;height:10px;'
            f'background:{status_rgba(status, 0.9)}"></div>'
        )
    return (
        '<div style="display:flex;width:100%;border-radius:999px;'
        'overflow:hidden;background:rgba(148,163,184,0.18)">'
        + "".join(parts)
        + "</div>"
    )


def _outcome_cell_html(status: str, label: str, pct: float, count: int) -> str:
    return (
        f'<div style="flex:1;min-width:6.5rem">'
        f'<div style="font-size:0.72rem;letter-spacing:0.08em;text-transform:uppercase;'
        f'opacity:0.72">'
        f'<span style="display:inline-block;width:0.55rem;height:0.55rem;'
        f'border-radius:999px;background:{status_rgba(status, 0.95)};'
        f'margin-right:0.4rem;vertical-align:middle"></span>{escape(label)}</div>'
        f'<div style="font-size:1.55rem;font-weight:650;line-height:1.15;'
        f'margin-top:0.2rem">{pct:.1f}%</div>'
        f'<div style="font-size:0.8rem;opacity:0.68;margin-top:0.1rem">'
        f"{count:,} jobs</div></div>"
    )


def _kpi_html(value: int | str, label: str, hint: str = "") -> str:
    hint_html = (
        f'<div style="font-size:0.75rem;opacity:0.62;margin-top:0.12rem">'
        f"{escape(hint)}</div>"
        if hint
        else ""
    )
    display = value if isinstance(value, str) else f"{value:,}"
    return (
        f'<div style="min-width:6.5rem">'
        f'<div style="font-size:1.2rem;font-weight:650">{escape(display)}</div>'
        f'<div style="font-size:0.72rem;letter-spacing:0.07em;text-transform:uppercase;'
        f'opacity:0.68;margin-top:0.15rem">{escape(label)}</div>{hint_html}</div>'
    )


def _chip_html(label: str, value: str) -> str:
    return (
        f'<span style="display:inline-block;padding:0.2rem 0.55rem;'
        f"border-radius:999px;background:rgba(148,163,184,0.14);"
        f'font-size:0.78rem;margin:0.15rem 0.3rem 0.15rem 0">'
        f'<span style="opacity:0.68">{escape(label)}</span> '
        f"<strong>{escape(value)}</strong></span>"
    )


def _show_cluster_health(
    *,
    window_label: str,
    health: ClusterHealthSnapshot,
) -> None:
    accent = _BADGE_STATUS.get(health.badge, "unknown")
    completed = health.completed
    reasons = "".join(
        f'<li style="margin:0.15rem 0">{escape(reason)}</li>'
        for reason in health.reasons
    )
    chips: list[str] = [
        _chip_html("Branches", str(health.cnt_branches)),
        _chip_html("Suites", str(health.cnt_suites)),
        _chip_html("Machines", str(health.cnt_machines)),
    ]
    if health.top_failure:
        chips.append(
            _chip_html(
                "Top failure",
                f"{health.top_failure} · {health.top_failure_count} jobs",
            )
        )
    if health.worst_branch:
        chips.append(
            _chip_html(
                "Worst branch",
                f"{health.worst_branch} · {health.worst_branch_fail_pct:.1f}% fail",
            )
        )
    html = "".join(
        [
            f'<div style="border:1px solid {status_rgba(accent, 0.28)};'
            f"border-left:6px solid {status_rgba(accent, 0.95)};"
            f"background:{status_rgba(accent, 0.08)};"
            'border-radius:12px;padding:1.1rem 1.25rem 1.2rem;width:100%">',
            '<div style="font-size:0.72rem;letter-spacing:0.12em;'
            'text-transform:uppercase;opacity:0.7;font-weight:600">',
            f"Cluster health · {escape(window_label)}</div>",
            '<div style="display:flex;flex-wrap:wrap;gap:1.5rem;'
            'align-items:stretch;margin-top:0.85rem">',
            '<div style="flex:0 1 260px">',
            f'<div style="font-size:2rem;font-weight:700;letter-spacing:0.04em;'
            f'line-height:1.1;color:{status_rgba(accent, 1)}">',
            f"{escape(health.badge)}</div>",
            '<ul style="margin:0.55rem 0 0;padding-left:1.15rem;'
            f'font-size:0.88rem;opacity:0.82;line-height:1.45">{reasons}</ul></div>',
            '<div style="flex:1 1 360px;min-width:16rem">',
            '<div style="display:flex;flex-wrap:wrap;gap:0.75rem 1.25rem">',
            _outcome_cell_html(
                "pass", "Passed", completed.pct_pass, completed.cnt_pass
            ),
            _outcome_cell_html(
                "fail", "Failed", completed.pct_fail, completed.cnt_fail
            ),
            _outcome_cell_html(
                "dead", "Dead", completed.pct_dead, completed.cnt_dead
            ),
            "</div>",
            f'<div style="margin-top:0.85rem">{_mix_bar_html(completed)}</div>',
            '<div style="margin-top:0.35rem;font-size:0.78rem;opacity:0.65">',
            f"Among {completed.cnt_jobs:,} completed jobs · "
            f"{health.cnt_not_passed:,} not passed "
            f"({health.pct_not_passed:.1f}% fail+dead).</div></div></div>",
            '<div style="display:flex;flex-wrap:wrap;gap:1.1rem 1.6rem;'
            "margin-top:1.05rem;padding-top:0.9rem;"
            f'border-top:1px solid {status_rgba(accent, 0.18)}">',
            _kpi_html(
                health.cnt_testruns,
                "Testruns",
                f"{health.cnt_completed_runs:,} done · {health.cnt_active_runs:,} active",
            ),
            _kpi_html(
                health.cnt_jobs,
                "Jobs",
                f"{health.pct_completed:.0f}% completed",
            ),
            _kpi_html(completed.cnt_jobs, "Completed"),
            _kpi_html(
                health.cnt_inflight,
                "In flight",
                (
                    f"{health.cnt_running:,} run · {health.cnt_waiting:,} wait · "
                    f"{health.cnt_queued:,} queued"
                ),
            ),
            _kpi_html(health.avg_duration, "Avg duration"),
            _kpi_html(
                health.stuck_6h,
                f"Stuck >{DEFAULT_HEALTH_STUCK_HOURS}h",
                (
                    f"{health.stuck_24h:,} older than "
                    f"{DEFAULT_HEALTH_STUCK_HOURS_LONG}h"
                ),
            ),
            "</div>",
            '<div style="margin-top:0.85rem">',
            "".join(chips),
            "</div></div>",
        ]
    )
    st.html(html)


def _active_runs_frame(runs: list[TestRun], pulpito: str | None) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "name": run_url(run.name, base=pulpito),
                "status": run.status,
                "branch": run.branch,
                "suite": run.suite,
                "machine_type": run.machine_type,
                "user": run.user,
                "total_jobs": run.total_jobs,
                "posted": run.posted,
            }
            for run in runs
        ]
    )


def _show_active_table(runs: list[TestRun], pulpito: str | None) -> None:
    table = _active_runs_frame(runs, pulpito)
    st.dataframe(
        table.style.apply(status_row_styles, axis=1),
        column_config=run_link_column("name", "Run", base=pulpito),
        width="stretch",
        hide_index=True,
        height=min(420, 38 + max(len(table), 1) * 35),
    )


def _share_bar(trends: list[StatusShareTrend], *, title: str, x_title: str) -> None:
    rows: list[dict] = []
    order: list[str] = []
    for row in trends:
        order.append(row.key)
        for status in ("pass", "fail", "dead"):
            count = getattr(row.results, "pass_" if status == "pass" else status)
            if not count:
                continue
            percentage = getattr(row, f"pct_{status}")
            rows.append(
                {
                    "group": row.key,
                    "status": status,
                    "count": count,
                    "percentage": percentage,
                    "label": f"{percentage:.1f}%",
                }
            )
    if not rows:
        st.info(f"No {x_title.lower()} information available for completed jobs.")
        return

    fig = px.bar(
        pd.DataFrame(rows),
        x="group",
        y="percentage",
        color="status",
        color_discrete_map=STATUS_COLOR_MAP,
        barmode="stack",
        text="label",
        title=title,
        labels={"group": x_title, "percentage": "Share (%)", "count": "Jobs"},
        hover_data={"count": True, "percentage": True, "label": False},
        category_orders={"status": ["pass", "fail", "dead"], "group": order},
    )
    fig.update_layout(height=400, legend_title_text="Status", yaxis_range=[0, 100])
    fig.update_traces(textposition="inside", cliponaxis=False)
    st.plotly_chart(fig, width="stretch")


def _overview_refresh_every() -> timedelta:
    """Incremental patch interval from config (``[overview] refresh_minutes``)."""
    return timedelta(minutes=get_overview_refresh_minutes())


@st.cache_resource
def _overview_store() -> dict:
    """Process-wide overview payload; patched with recent runs/jobs on an interval."""
    return {
        "runs": [],
        "jobs": [],
        "loaded_at": None,
        "patched_at": None,
    }


def _merge_overview_runs(
    existing: list[TestRun],
    incoming: list[TestRun],
    *,
    keep_since: datetime,
) -> list[TestRun]:
    by_name = {run.name: run for run in existing if run.name}
    for run in incoming:
        if run.name:
            by_name[run.name] = run
    keep_utc = as_utc(keep_since)
    rows = []
    for run in by_name.values():
        posted = as_utc(run.posted)
        if posted is None or keep_utc is None or posted >= keep_utc:
            rows.append(run)
    rows.sort(key=lambda run: as_utc(run.posted) or keep_utc, reverse=True)
    return rows


def _merge_overview_jobs(existing: list[Job], incoming: list[Job]) -> list[Job]:
    refreshed = {job.run_name for job in incoming if job.run_name}
    kept = [job for job in existing if job.run_name not in refreshed]
    return kept + list(incoming)


def _ensure_overview_payload() -> tuple[list[TestRun], list[Job]]:
    """Full 30-day load once, then merge recent runs/jobs when the interval elapses."""
    store = _overview_store()
    now = datetime.now(timezone.utc)
    refresh_minutes = get_overview_refresh_minutes()
    refresh_every = timedelta(minutes=refresh_minutes)
    keep_since = now - max(_WINDOW_OPTIONS.values())

    if store["loaded_at"] is None:
        with st.spinner("Loading overview data…"):
            runs = TestRunsStats.since(keep_since)
            jobs = JobsStats.for_testruns(runs.testruns)
        store["runs"] = runs.testruns
        store["jobs"] = jobs.jobs
        store["loaded_at"] = now
        store["patched_at"] = now
        return store["runs"], store["jobs"]

    patched_at = store["patched_at"] or store["loaded_at"]
    if now - patched_at >= refresh_every:
        patch_since = now - refresh_every
        with st.spinner(
            f"Refreshing last {refresh_minutes} minutes of overview data…"
        ):
            recent_runs = TestRunsStats.since(patch_since)
            recent_jobs = JobsStats.for_testruns(recent_runs.testruns)
        store["runs"] = _merge_overview_runs(
            store["runs"],
            recent_runs.testruns,
            keep_since=keep_since,
        )
        store["jobs"] = _merge_overview_jobs(store["jobs"], recent_jobs.jobs)
        store["patched_at"] = now

    return store["runs"], store["jobs"]


@st.fragment(run_every=_overview_refresh_every())
def _periodic_overview_refresh() -> None:
    """Rerun the page when the configured interval elapses so the patch can apply."""
    store = _overview_store()
    patched_at = store["patched_at"]
    if patched_at is None:
        return
    now = datetime.now(timezone.utc)
    if now - patched_at >= _overview_refresh_every():
        st.rerun()


st.markdown(
    "<h1 style='text-align: center;'>Ceph Test Dashboard</h1>",
    unsafe_allow_html=True,
)
st.markdown(
    "High-level **lab health**, **active runs**, and **job trends**. "
    "Use Nightly, Hardware, and Coverage for deep drill-down."
)

st.sidebar.header("Filters")
window_label = st.sidebar.selectbox(
    "Time window",
    list(_WINDOW_OPTIONS.keys()),
    index=1,  # Last 7 days
    key="overview_window",
)
now = datetime.now(timezone.utc)
cutoff = now - _WINDOW_OPTIONS[window_label]

try:
    payload_runs, payload_jobs = _ensure_overview_payload()
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
branch_label = st.sidebar.selectbox(
    "Branch",
    ["All"] + branches,
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

_show_cluster_health(window_label=window_label, health=health)

st.divider()

st.subheader("Daily trend")

daily_rows: list[dict] = []
for trend in jobs.completed_stats.daily_trends:
    for status in ("pass", "fail", "dead"):
        count = getattr(trend.results, "pass_" if status == "pass" else status)
        if not count:
            continue
        daily_rows.append({"day": trend.day, "status": status, "count": count})

pct_rows: list[dict] = []
for row in jobs.completed_stats.daily_status_pct(dead_as_fail=False):
    for status in ("pass", "fail", "dead"):
        pct_rows.append(
            {
                "day": row.day,
                "status": status,
                "percentage": round(getattr(row, f"pct_{status}"), 1),
            }
        )

if not daily_rows:
    st.info("No completed jobs to chart.")
else:
    col_count, col_pct = st.columns(2)
    with col_count:
        fig_trend = px.line(
            pd.DataFrame(daily_rows),
            x="day",
            y="count",
            color="status",
            color_discrete_map=STATUS_COLOR_MAP,
            markers=True,
            title="Completed Jobs by Day",
            labels={"day": "Day", "count": "Jobs"},
            category_orders={"status": ["pass", "fail", "dead"]},
        )
        fig_trend.update_layout(height=360, legend_title_text="Status")
        st.plotly_chart(fig_trend, width="stretch")
    with col_pct:
        fig_pct = px.line(
            pd.DataFrame(pct_rows),
            x="day",
            y="percentage",
            color="status",
            color_discrete_map=STATUS_COLOR_MAP,
            markers=True,
            title="Pass / Fail / Dead Rate by Day",
            labels={"day": "Day", "percentage": "Share (%)"},
            category_orders={"status": ["pass", "fail", "dead"]},
        )
        fig_pct.update_layout(
            height=360,
            legend_title_text="Status",
            yaxis_range=[0, 100],
        )
        st.plotly_chart(fig_pct, width="stretch")

st.divider()

st.subheader("Active Runs")

active = runs.active_summary(now)
r1, r2, r3, r4, r5, r6 = st.columns(6)
r1.metric("Active Testruns", active.cnt_testruns)
r2.metric("Total Active Jobs", active.cnt_jobs)
r3.metric("Running", active.cnt_running)
r4.metric("Waiting", active.cnt_waiting)
r5.metric("Queued", active.cnt_queued)
r6.metric("Oldest Active Age", active.oldest_age)

stuck_6h = len(
    runs.stuck_testruns(
        older_than=timedelta(hours=DEFAULT_HEALTH_STUCK_HOURS),
        now=now,
    )
)
stuck_24h = len(
    runs.stuck_testruns(
        older_than=timedelta(hours=DEFAULT_HEALTH_STUCK_HOURS_LONG),
        now=now,
    )
)
st.caption(
    f"**{stuck_6h}** active runs older than {DEFAULT_HEALTH_STUCK_HOURS}h · "
    f"**{stuck_24h}** older than {DEFAULT_HEALTH_STUCK_HOURS_LONG}h."
)

ranked_active = runs.ranked_active_testruns()
if not ranked_active:
    st.info("No queued, running, or waiting runs in the selected window.")
else:
    shown = ranked_active[:_ACTIVE_TABLE_CAP]
    rest = ranked_active[_ACTIVE_TABLE_CAP:]
    _show_active_table(shown, pulpito)
    if rest:
        with st.expander(f"All other active runs ({len(rest)})"):
            _show_active_table(rest, pulpito)

st.divider()

st.subheader("Needs attention")

col_reasons, col_runs = st.columns(2)

with col_reasons:
    st.markdown("**Top failure reasons**")
    if not jobs.top_10_failure_reasons:
        st.info("No failures in this window.")
    else:
        top_fail = pd.DataFrame(
            [
                {
                    "Failure Reason": row.reason,
                    "Jobs": row.count,
                    "Share (%)": row.pct,
                    "Runs": row.runs_impacted,
                }
                for row in jobs.top_10_failure_reasons
            ]
        )
        event = st.dataframe(
            top_fail,
            width="stretch",
            hide_index=True,
            height=min(400, 38 + len(top_fail) * 35),
            on_select="rerun",
            selection_mode="single-row",
            key="overview_failure_reasons",
        )
        selected_rows = event.selection.rows if event.selection else []
        if selected_rows:
            selected_reason = str(
                top_fail.iloc[selected_rows[0]]["Failure Reason"]
            )
            matching = jobs.matching_failure(selected_reason)
            run_names = list(
                dict.fromkeys(job.run_name for job in matching if job.run_name)
            )
            records = runs.records_for_names(run_names)
            jobs_count = len(matching)
            runs_count = len(run_names)
            btn_jobs, btn_runs = st.columns(2)
            with btn_jobs:
                if st.button(f"View {jobs_count} Impacted Jobs →"):
                    st.session_state["drill_run_names"] = run_names
                    st.switch_page(
                        "pages/dashboard/jobs.py",
                        query_params={
                            "failure_reason": selected_reason,
                            "source": "overview",
                        },
                    )
            with btn_runs:
                if st.button(f"View {runs_count} Impacted Runs →"):
                    st.session_state["drill_run_names"] = run_names
                    st.session_state["drill_run_records"] = records
                    st.switch_page(
                        "pages/dashboard/testruns.py",
                        query_params={
                            "failure_reason": selected_reason,
                            "source": "overview",
                        },
                    )

with col_runs:
    st.markdown("**Worst failed runs**")
    if not jobs.top_failed_runs:
        st.info("No failed runs in this window.")
    else:
        display_runs = pd.DataFrame(
            [
                {
                    "Run": run_url(row.run_name, base=pulpito),
                    "Suite": row.suite,
                    "Failed Jobs": row.failed_jobs,
                    "Fail Rate (%)": row.fail_pct,
                }
                for row in jobs.top_failed_runs
            ]
        )
        st.dataframe(
            display_runs,
            column_config=run_link_column("Run", "Run", base=pulpito),
            width="stretch",
            hide_index=True,
            height=min(400, 38 + len(display_runs) * 35),
        )

col_tests, col_branches = st.columns(2)

with col_tests:
    st.markdown("**Top failing tests**")
    failing_tests = jobs.top_failing_tests()
    if not failing_tests:
        st.info("No failing tests in this window.")
    else:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Test": row.description,
                        "Jobs": row.count,
                        "Share (%)": row.pct,
                        "Runs": row.runs_impacted,
                    }
                    for row in failing_tests
                ]
            ),
            width="stretch",
            hide_index=True,
            height=min(400, 38 + len(failing_tests) * 35),
        )

with col_branches:
    st.markdown("**Worst branches**")
    worst_branches = jobs.branch_summaries[:8]
    if not worst_branches:
        st.info("No completed-job branch data in this window.")
    else:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Branch": row.branch,
                        "Jobs": row.cnt_jobs,
                        "Fail (%)": row.pct_fail,
                        "Pass (%)": row.pct_pass,
                    }
                    for row in worst_branches
                ]
            ),
            width="stretch",
            hide_index=True,
            height=min(400, 38 + len(worst_branches) * 35),
        )

st.markdown("**Machine type reliability**")
machines = [
    row for row in jobs.reliability_by("machine_type") if row.key != "unknown"
][:8]
if not machines:
    st.info("No machine type information available for completed jobs.")
else:
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Machine": row.key,
                    "Jobs": row.cnt_jobs,
                    "Fail (%)": row.pct_fail,
                    "Pass (%)": row.pct_pass,
                }
                for row in machines
            ]
        ),
        width="stretch",
        hide_index=True,
        height=min(320, 38 + len(machines) * 35),
    )

st.divider()

st.subheader("Job mix")
col_os, col_suite = st.columns(2)
with col_os:
    os_trends = jobs.os_share_trends()
    if not os_trends:
        st.info("No OS type information available for completed jobs.")
    else:
        _share_bar(os_trends, title="Job Trends by OS (%)", x_title="OS")
with col_suite:
    suite_trends = jobs.suite_share_trends()
    if not suite_trends:
        st.info("No suite information available for completed jobs.")
    else:
        _share_bar(suite_trends, title="Job Trends by Suite (%)", x_title="Suite")
