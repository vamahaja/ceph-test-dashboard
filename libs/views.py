"""Shared Streamlit report views used by Overview and report pages."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from html import escape
from typing import NamedTuple

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from libs.defaults import (
    DEFAULT_HEALTH_STUCK_HOURS,
    DEFAULT_HEALTH_STUCK_HOURS_LONG,
    DEFAULT_TOP_ACTIVE_TESTRUNS,
    STATUS_COLOR_MAP,
    status_rgba,
    status_row_styles,
)
from libs.pulpito import run_link_column, run_url
from libs.refresh import catalog_generation
from libs.reports.jobs import JobsStats
from libs.reports.models import (
    ClusterHealthSnapshot,
    JobsSummary,
    PassRateCell,
    StatusShareTrend,
    TestRun,
)
from libs.reports.testruns import TestRunsStats
from libs.reports.utils import as_utc, format_age

_BADGE_STATUS = {
    "Healthy": "pass",
    "Degraded": "queued",
    "Critical": "fail",
    "Unknown": "unknown",
}

_ACTIVE_RUN_COLUMNS = (
    "name",
    "status",
    "branch",
    "suite",
    "machine_type",
    "user",
    "total_jobs",
    "posted",
)


def _table_height(rows: int, *, cap: int = 800, min_rows: int = 1) -> int:
    return min(cap, 38 + max(rows, min_rows) * 35)


def query_str(key: str) -> str:
    """First query-param value for ``key``, or empty string."""
    value = st.query_params.get(key)
    if isinstance(value, list):
        return str(value[0] or "")
    return str(value or "")


def query_csv(key: str) -> list[str]:
    """Comma-separated query-param values for ``key``."""
    return [part.strip() for part in query_str(key).split(",") if part.strip()]


def sync_query_params(updates: dict[str, str | None]) -> None:
    """Write ``updates`` to the URL; ``None`` or empty values drop the key."""
    current = {key: query_str(key) for key in st.query_params}
    wanted = {
        key: value
        for key, value in updates.items()
        if value is not None and value != ""
    }
    drop = [key for key in updates if key not in wanted]
    same = all(current.get(key) == value for key, value in wanted.items())
    if same and all(key not in current for key in drop):
        return
    for key, value in wanted.items():
        if current.get(key) != value:
            st.query_params[key] = value
    for key in drop:
        if key in st.query_params:
            del st.query_params[key]


_WINDOW_DAYS = {
    "Last 24 hours": 1,
    "Last 7 days": 7,
    "Last 15 days": 15,
    "Last 30 days": 30,
}
_WINDOW_BY_QUERY = {
    "24h": "Last 24 hours",
    "7d": "Last 7 days",
    "15d": "Last 15 days",
    "30d": "Last 30 days",
}
_QUERY_BY_WINDOW = {label: key for key, label in _WINDOW_BY_QUERY.items()}
_DEFAULT_WINDOW = "Last 24 hours"


class TimeWindow(NamedTuple):
    """Inclusive calendar-day window selected from the time-window control."""

    label: str
    start: date
    end: date
    query: str


def sidebar_time_window(*, prefix: str, label: str = "Time window") -> TimeWindow:
    """Sidebar preset time window, initialized from the ``window`` query param."""
    key = f"{prefix}_window"
    if key not in st.session_state:
        st.session_state[key] = _WINDOW_BY_QUERY.get(
            query_str("window"), _DEFAULT_WINDOW
        )
    elif st.session_state[key] not in _WINDOW_DAYS:
        st.session_state[key] = _DEFAULT_WINDOW
    window_label = st.sidebar.selectbox(
        label,
        list(_WINDOW_DAYS.keys()),
        key=key,
    )
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=_WINDOW_DAYS[window_label] - 1)
    return TimeWindow(
        label=window_label,
        start=start,
        end=end,
        query=_QUERY_BY_WINDOW[window_label],
    )


def show_data_status() -> None:
    """Silently rerun when a new catalog lands."""
    _watch_catalog_updates()


@st.fragment(run_every=timedelta(seconds=20))
def _watch_catalog_updates() -> None:
    """Rerun the page when the background catalog is replaced."""
    generation = catalog_generation()
    seen = st.session_state.get("_catalog_seen_generation")
    if seen is None:
        st.session_state["_catalog_seen_generation"] = generation
        return
    if generation > seen:
        st.session_state["_catalog_seen_generation"] = generation
        st.rerun()


def sidebar_branch_select(branches: list[str], *, prefix: str) -> str:
    """Sidebar branch selectbox, initialized from the ``branch`` query param."""
    if not branches:
        return ""
    key = f"{prefix}_branch"
    if key not in st.session_state:
        qp_branch = query_str("branch")
        st.session_state[key] = qp_branch if qp_branch in branches else branches[0]
    elif st.session_state[key] not in branches:
        st.session_state[key] = branches[0]
    return st.sidebar.selectbox("Branch", branches, key=key)


def sidebar_suite_select(
    suites: list[str],
    *,
    prefix: str,
    help_text: str = "",
) -> str:
    """Sidebar suite selectbox, initialized from the ``suite`` query param."""
    if not suites:
        return ""
    key = f"{prefix}_suite"
    if key not in st.session_state:
        qp_suite = query_str("suite")
        st.session_state[key] = qp_suite if qp_suite in suites else suites[0]
    elif st.session_state[key] not in suites:
        st.session_state[key] = suites[0]
    return st.sidebar.selectbox(
        "Suite",
        suites,
        key=key,
        help=help_text or None,
    )


def sidebar_machine_select(
    machine_types: list[str],
    *,
    prefix: str,
    help_text: str = "",
) -> str:
    """Sidebar machine-type selectbox, initialized from ``machine`` query param."""
    if not machine_types:
        return ""
    key = f"{prefix}_machine"
    if key not in st.session_state:
        qp_machine = query_str("machine")
        st.session_state[key] = (
            qp_machine if qp_machine in machine_types else machine_types[0]
        )
    elif st.session_state[key] not in machine_types:
        st.session_state[key] = machine_types[0]
    return st.sidebar.selectbox(
        "Machine Type",
        machine_types,
        key=key,
        help=help_text or None,
    )


def sidebar_branch_filter(
    all_branches: list[str],
    *,
    prefix: str,
    reset_token: str,
) -> list[str]:
    """Branch multiselect with All/Clear and URL ``branch`` query param."""
    state_key = f"{prefix}_branches"
    token_key = f"_{prefix}_branches_token"
    if st.session_state.get(token_key) != reset_token:
        st.session_state[token_key] = reset_token
        valid = [branch for branch in query_csv("branch") if branch in all_branches]
        st.session_state[state_key] = valid or list(all_branches)
    elif state_key not in st.session_state:
        valid = [branch for branch in query_csv("branch") if branch in all_branches]
        st.session_state[state_key] = valid or list(all_branches)
    else:
        kept = [
            branch
            for branch in st.session_state[state_key]
            if branch in all_branches
        ]
        if kept != st.session_state[state_key]:
            st.session_state[state_key] = kept

    pick_all, pick_none = st.sidebar.columns(2)
    if pick_all.button("All branches", key=f"{prefix}_branches_all"):
        st.session_state[state_key] = list(all_branches)
        st.rerun()
    if pick_none.button("Clear branches", key=f"{prefix}_branches_none"):
        st.session_state[state_key] = []
        st.rerun()
    return st.sidebar.multiselect("Branch", all_branches, key=state_key)


def sidebar_suite_filter(
    all_suites: list[str],
    *,
    prefix: str,
    reset_token: str,
) -> list[str]:
    """Suite multiselect with All/Clear and URL ``suite`` query param."""
    state_key = f"{prefix}_suites"
    token_key = f"_{prefix}_suites_token"
    if st.session_state.get(token_key) != reset_token:
        st.session_state[token_key] = reset_token
        valid = [suite for suite in query_csv("suite") if suite in all_suites]
        st.session_state[state_key] = valid or list(all_suites)
    elif state_key not in st.session_state:
        valid = [suite for suite in query_csv("suite") if suite in all_suites]
        st.session_state[state_key] = valid or list(all_suites)
    else:
        kept = [suite for suite in st.session_state[state_key] if suite in all_suites]
        if kept != st.session_state[state_key]:
            st.session_state[state_key] = kept

    pick_all, pick_none = st.sidebar.columns(2)
    if pick_all.button("All suites", key=f"{prefix}_suites_all"):
        st.session_state[state_key] = list(all_suites)
        st.rerun()
    if pick_none.button("Clear suites", key=f"{prefix}_suites_none"):
        st.session_state[state_key] = []
        st.rerun()
    return st.sidebar.multiselect("Suite", all_suites, key=state_key)


def sidebar_sha_select(sha_values: list[str], *, prefix: str) -> str:
    """Sidebar SHA selectbox; returns empty string when All is selected."""
    options = ["All"] + sha_values
    key = f"{prefix}_sha"
    if key not in st.session_state:
        qp_sha = query_str("sha")
        st.session_state[key] = qp_sha if qp_sha in options else "All"
    elif st.session_state[key] not in options:
        st.session_state[key] = "All"
    label = st.sidebar.selectbox(
        "Commit SHA",
        options,
        key=key,
        help="Scope the report to one commit. Leave All to compare SHAs.",
    )
    return "" if label == "All" else label


def show_scope_caption(
    runs: TestRunsStats,
    jobs: JobsStats,
    *,
    loaded_at: datetime | None = None,
    now: datetime | None = None,
) -> None:
    """Row counts and catalog timestamp under the health card."""
    parts = [
        f"{len(runs.testruns):,} runs",
        f"{jobs.summary.cnt_jobs:,} jobs",
    ]
    if loaded_at is not None:
        ts = as_utc(loaded_at)
        ref = as_utc(now) or datetime.now(timezone.utc)
        if ts is not None:
            stamp = ts.strftime("%Y-%m-%d %H:%M UTC")
            seconds = max(0, (ref - ts).total_seconds())
            if seconds < 60:
                parts.append(f"Last updated {stamp}")
            else:
                parts.append(
                    f"Last updated {stamp} ({format_age(loaded_at, now)} ago)"
                )
    st.caption(" · ".join(parts))


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


def show_cluster_health(
    health: ClusterHealthSnapshot,
    *,
    heading: str,
    show_branch_chip: bool = True,
    show_worst_branch: bool = True,
) -> None:
    """Render the health badge card (completed mix, KPIs, chips)."""
    accent = _BADGE_STATUS.get(health.badge, "unknown")
    completed = health.completed
    reasons = "".join(
        f'<li style="margin:0.15rem 0">{escape(reason)}</li>'
        for reason in health.reasons
    )
    chips: list[str] = []
    if show_branch_chip:
        chips.append(_chip_html("Branches", str(health.cnt_branches)))
    chips.extend(
        [
            _chip_html("Suites", str(health.cnt_suites)),
            _chip_html("Machines", str(health.cnt_machines)),
        ]
    )
    if health.top_failure:
        chips.append(
            _chip_html(
                "Top failure",
                f"{health.top_failure} · {health.top_failure_count} jobs",
            )
        )
    if show_worst_branch and health.worst_branch:
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
            f"{escape(heading)}</div>",
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


def runs_frame(
    runs: list[TestRun],
    pulpito: str | None,
    *,
    columns: tuple[str, ...] = _ACTIVE_RUN_COLUMNS,
) -> pd.DataFrame:
    """Build a run table; ``name`` values are Pulpito links when configured."""
    rows = []
    for run in runs:
        row = {
            "name": run_url(run.name, base=pulpito),
            "status": run.status,
            "branch": run.branch,
            "suite": run.suite,
            "sha": run.sha_short or "—",
            "machine_type": run.machine_type,
            "user": run.user,
            "total_jobs": run.total_jobs,
            "posted": run.posted,
            "scheduled": run.scheduled,
            "scheduled_date": (
                as_utc(run.scheduled).date() if as_utc(run.scheduled) else None
            ),
        }
        rows.append({key: row[key] for key in columns if key in row})
    return pd.DataFrame(rows, columns=list(columns))


def show_runs_table(
    runs: list[TestRun],
    pulpito: str | None,
    *,
    columns: tuple[str, ...] = _ACTIVE_RUN_COLUMNS,
    height: int | None = None,
) -> None:
    """Status-tinted run table with Pulpito name links."""
    table = runs_frame(runs, pulpito, columns=columns)
    column_config = run_link_column("name", "Run", base=pulpito)
    if "sha" in columns:
        column_config["sha"] = st.column_config.TextColumn("SHA")
    if "scheduled_date" in columns:
        column_config["scheduled_date"] = st.column_config.DateColumn("Scheduled")
    st.dataframe(
        table.style.apply(status_row_styles, axis=1),
        column_config=column_config,
        width="stretch",
        hide_index=True,
        height=height or _table_height(len(table), cap=420),
    )


def show_status_filtered_runs(
    runs: list[TestRun],
    pulpito: str | None,
    *,
    prefix: str,
    columns: tuple[str, ...] = _ACTIVE_RUN_COLUMNS,
    heading: str = "Runs",
) -> None:
    """Runs table with an optional status multiselect."""
    statuses = sorted({run.status for run in runs if run.status})
    state_key = f"{prefix}_run_status"
    if "status" in columns and statuses:
        if state_key not in st.session_state:
            st.session_state[state_key] = list(statuses)
        else:
            kept = [
                status
                for status in st.session_state[state_key]
                if status in statuses
            ]
            if not kept:
                st.session_state[state_key] = list(statuses)
            elif kept != st.session_state[state_key]:
                st.session_state[state_key] = kept
        selected_statuses = st.multiselect("Status", statuses, key=state_key)
        visible = [run for run in runs if run.status in selected_statuses]
    else:
        visible = list(runs)

    st.subheader(f"{heading} ({len(visible)} of {len(runs)})")
    if not visible:
        st.info("No runs match the selected statuses.")
        return
    show_runs_table(
        visible,
        pulpito,
        columns=columns,
        height=_table_height(len(visible), cap=800),
    )


def show_share_bar(
    trends: list[StatusShareTrend],
    *,
    title: str,
    x_title: str,
) -> None:
    """Stacked pass/fail/dead share bar for OS, suite, or similar groups."""
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


def show_daily_trends(jobs: JobsStats) -> None:
    """Completed-job count and pass/fail/dead rate lines by day."""
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
        return

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


def show_active_runs(
    runs: TestRunsStats,
    pulpito: str | None,
    *,
    now: datetime,
    cap: int = DEFAULT_TOP_ACTIVE_TESTRUNS,
    collapse_table: bool = False,
) -> None:
    """Active-run metrics, stuck caption, and ranked table."""
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
        return

    shown = ranked_active[:cap]
    rest = ranked_active[cap:]

    def _render_tables() -> None:
        show_runs_table(shown, pulpito)
        if rest:
            with st.expander(f"All other active runs ({len(rest)})"):
                show_runs_table(
                    rest,
                    pulpito,
                    height=_table_height(len(rest), cap=800),
                )

    if collapse_table:
        with st.expander(f"Active run details ({len(ranked_active)})"):
            _render_tables()
        return

    _render_tables()


def show_needs_attention(
    runs: TestRunsStats,
    jobs: JobsStats,
    pulpito: str | None,
    *,
    source: str,
    show_worst_branches: bool = True,
) -> None:
    """Failure-reason drill-in, worst runs, failing tests, optional branches."""
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
                height=_table_height(len(top_fail), cap=400),
                on_select="rerun",
                selection_mode="single-row",
                key=f"{source}_failure_reasons",
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
                    if st.button(
                        f"View {jobs_count} Impacted Jobs →",
                        key=f"{source}_view_jobs",
                    ):
                        st.session_state["drill_run_names"] = run_names
                        st.switch_page(
                            "pages/dashboard/jobs.py",
                            query_params={
                                "failure_reason": selected_reason,
                                "source": source,
                            },
                        )
                with btn_runs:
                    if st.button(
                        f"View {runs_count} Impacted Runs →",
                        key=f"{source}_view_runs",
                    ):
                        st.session_state["drill_run_names"] = run_names
                        st.session_state["drill_run_records"] = records
                        st.switch_page(
                            "pages/dashboard/testruns.py",
                            query_params={
                                "failure_reason": selected_reason,
                                "source": source,
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
                height=_table_height(len(display_runs), cap=400),
            )

    if show_worst_branches:
        col_tests, col_branches = st.columns(2)
    else:
        col_tests, col_branches = st.container(), None

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
                height=_table_height(len(failing_tests), cap=400),
            )

    if col_branches is not None:
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
                    height=_table_height(len(worst_branches), cap=400),
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
            height=_table_height(len(machines), cap=320),
        )


def show_job_mix(jobs: JobsStats) -> None:
    """OS and suite stacked share bars side by side."""
    col_os, col_suite = st.columns(2)
    with col_os:
        os_trends = jobs.os_share_trends()
        if not os_trends:
            st.info("No OS type information available for completed jobs.")
        else:
            show_share_bar(os_trends, title="Job Trends by OS (%)", x_title="OS")
    with col_suite:
        suite_trends = jobs.suite_share_trends()
        if not suite_trends:
            st.info("No suite information available for completed jobs.")
        else:
            show_share_bar(
                suite_trends, title="Job Trends by Suite (%)", x_title="Suite"
            )


def show_sha_results(
    jobs: JobsStats,
    *,
    title: str,
    show_table: bool = False,
) -> None:
    """Stacked pass/fail job counts per commit SHA."""
    rows = jobs.sha_summaries
    if not rows:
        st.info("No commit SHA information available.")
        return

    frame = pd.DataFrame(
        [
            {
                "sha_short": row.sha_short or "unknown",
                "passed": row.cnt_pass,
                "failed": row.cnt_fail,
            }
            for row in rows
        ]
    )
    fig = px.bar(
        frame,
        x="sha_short",
        y=["passed", "failed"],
        color_discrete_map={
            "passed": STATUS_COLOR_MAP["pass"],
            "failed": STATUS_COLOR_MAP["fail"],
        },
        barmode="stack",
        title=title,
        labels={"sha_short": "SHA", "value": "Jobs", "variable": "Result"},
    )
    fig.update_layout(height=400, legend_title_text="Result")
    st.plotly_chart(fig, width="stretch")

    if show_table:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "SHA": row.sha_short or "unknown",
                        "Runs": row.cnt_runs,
                        "Jobs": row.cnt_jobs,
                        "Passed": row.cnt_pass,
                        "Failed": row.cnt_fail,
                        "Pass Rate (%)": row.pct_pass,
                    }
                    for row in rows
                ]
            ),
            width="stretch",
            hide_index=True,
        )


def show_pass_heatmap(
    cells: list[PassRateCell],
    *,
    title: str,
    x_title: str = "OS Type",
    y_title: str = "Branch",
) -> None:
    """Branch × OS pass-rate heatmap from ``JobsStats.pass_matrix()`` cells."""
    usable = [
        cell
        for cell in cells
        if cell.branch and cell.os_type and cell.os_type != "unknown"
    ]
    if not usable:
        st.info("No OS type information available in the current job data.")
        return

    branches = sorted({cell.branch for cell in usable})
    os_types = sorted({cell.os_type for cell in usable})
    heat = [[None] * len(os_types) for _ in branches]
    anno = [[""] * len(os_types) for _ in branches]
    branch_idx = {name: i for i, name in enumerate(branches)}
    os_idx = {name: i for i, name in enumerate(os_types)}
    for cell in usable:
        row = branch_idx[cell.branch]
        col = os_idx[cell.os_type]
        heat[row][col] = cell.pct_pass
        anno[row][col] = f"{cell.pct_pass}%<br>({cell.cnt_jobs} jobs)"

    fig = go.Figure(
        data=go.Heatmap(
            z=heat,
            x=os_types,
            y=branches,
            text=anno,
            texttemplate="%{text}",
            colorscale=[
                [0, status_rgba("fail", 0.95)],
                [0.5, status_rgba("queued", 0.95)],
                [1, status_rgba("pass", 0.95)],
            ],
            colorbar={"title": "Pass Rate %"},
            hovertemplate=(
                "Branch: %{y}<br>OS: %{x}<br>Pass Rate: %{z:.1f}%<extra></extra>"
            ),
            zmin=0,
            zmax=100,
        )
    )
    fig.update_layout(
        title=title,
        height=max(300, 60 * len(branches)),
        xaxis_title=x_title,
        yaxis_title=y_title,
        yaxis={"autorange": "reversed"},
    )
    st.plotly_chart(fig, width="stretch")

