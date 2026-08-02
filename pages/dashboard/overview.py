"""
Ceph Test Dashboard — landing / ops command center.

Rolling-window cluster health, active runs, and job trends by OS.
Specialist pages own deep drill-down.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from libs.config import get_pulpito_url
from libs.normalizer import get_jobs_data, get_runs_since

_COMPLETED = {"pass", "fail", "dead"}
_ACTIVE = {"queued", "running"}

_COLOR_MAP = {
    "pass": "#54b399",
    "fail": "#d36086",
    "dead": "#aa6556",
    "running": "#6092c0",
    "queued": "#d6bf57",
}

_STATUS_ROW_COLORS = {
    "pass": "background-color: #54b399; color: white",
    "fail": "background-color: #d36086; color: white",
    "dead": "background-color: #aa6556; color: white",
    "running": "background-color: #6092c0; color: white",
    "queued": "background-color: #d6bf57; color: white",
    "unknown": "background-color: #9170b8; color: white",
}


def _row_color(row):
    style = _STATUS_ROW_COLORS.get(row.get("status", ""), "")
    return [style] * len(row)

_WINDOW_OPTIONS = {
    "Last 24 hours": timedelta(hours=24),
    "Last 7 days": timedelta(days=7),
    "Last 30 days": timedelta(days=30),
}


# ── helpers ───────────────────────────────────────────────────────────

def _health_badge(pass_rate: float, dead_rate: float) -> tuple[str, str]:
    """
    Return (label, caption) from pass rate and dead rate.

    Critical: pass < 50% or dead >= 15%
    Degraded: pass < 80% or dead >= 5%
    Healthy: otherwise
    """
    if pass_rate < 50 or dead_rate >= 15:
        return (
            "Critical",
            "Pass rate under 50% or dead rate at/above 15%.",
        )
    if pass_rate < 80 or dead_rate >= 5:
        return (
            "Degraded",
            "Pass rate under 80% or dead rate at/above 5%.",
        )
    return (
        "Healthy",
        "Pass rate at/above 80% and dead rate under 5%.",
    )


def _format_age(posted, now: datetime) -> str:
    if pd.isna(posted):
        return "—"
    ts = posted.to_pydatetime() if hasattr(posted, "to_pydatetime") else posted
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    ref = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    seconds = max(0, (ref - ts).total_seconds())
    if seconds < 3600:
        return f"{int(seconds // 60)}m"
    if seconds < 86400:
        return f"{seconds / 3600:.1f}h"
    return f"{seconds / 86400:.1f}d"


# ── page header ───────────────────────────────────────────────────────

st.markdown(
    "<h1 style='text-align: center;'>Ceph Test Dashboard</h1>",
    unsafe_allow_html=True,
)
st.markdown(
    "High-level **lab health**, **active runs**, and **job trends by OS**. "
    "Use Nightly, Hardware, and Coverage for deep drill-down."
)

st.sidebar.header("Filters")
window_label = st.sidebar.selectbox(
    "Time window",
    list(_WINDOW_OPTIONS.keys()),
    index=1,  # Last 7 days
)
window_delta = _WINDOW_OPTIONS[window_label]
now = datetime.now(timezone.utc)
cutoff = now - window_delta

# ── data load ─────────────────────────────────────────────────────────

# Floor to the minute so Streamlit cache keys stay stable within a TTL window.
runs_data = get_runs_since(cutoff.replace(second=0, microsecond=0).isoformat())
if not runs_data:
    st.warning(f"No runs found in the selected window ({window_label}).")
    st.stop()

df_runs = pd.DataFrame(runs_data)
df_runs["posted"] = pd.to_datetime(df_runs["posted"], errors="coerce", utc=True)
window_runs = df_runs[df_runs["posted"] >= cutoff].copy()
if window_runs.empty:
    st.warning(f"No runs found in the selected window ({window_label}).")
    st.stop()

window_runs = window_runs.sort_values("posted", ascending=False)
run_names = window_runs["name"].dropna().unique().tolist()
run_info = window_runs.set_index("name")[
    [c for c in ["branch", "suite", "cloud_platform"] if c in window_runs.columns]
].to_dict("index")

all_jobs: list[dict] = []
progress = st.progress(0, text="Loading job data…")
for i, run_name in enumerate(run_names):
    progress.progress(
        int((i + 1) / max(len(run_names), 1) * 100),
        text=f"Loading jobs for run {i + 1} of {len(run_names)}…",
    )
    run_jobs = get_jobs_data(run_name=run_name)
    if not run_jobs:
        continue
    info = run_info.get(run_name, {})
    for raw_job in run_jobs:
        # Copy so we never mutate objects owned by @st.cache_data.
        job = dict(raw_job)
        if not job.get("branch"):
            job["branch"] = info.get("branch", "")
        if not job.get("suite"):
            job["suite"] = info.get("suite", "")
        if not job.get("machine_type"):
            job["machine_type"] = info.get("cloud_platform", "")
        if not job.get("run_name"):
            job["run_name"] = run_name
        all_jobs.append(job)
progress.empty()

if not all_jobs:
    st.warning("No job data available for runs in the selected window.")
    st.stop()

df_jobs = pd.DataFrame(all_jobs)
df_jobs["posted"] = pd.to_datetime(df_jobs["posted"], errors="coerce", utc=True)
df_jobs["branch"] = df_jobs["branch"].fillna("unknown").replace("", "unknown")
df_jobs["suite"] = df_jobs["suite"].fillna("unknown").replace("", "unknown")
df_jobs["machine_type"] = (
    df_jobs["machine_type"].fillna("unknown").replace("", "unknown")
)
if "os_type" not in df_jobs.columns:
    df_jobs["os_type"] = "unknown"
else:
    df_jobs["os_type"] = (
        df_jobs["os_type"].fillna("").replace("", "unknown")
    )
if "failure_template" not in df_jobs.columns:
    df_jobs["failure_template"] = ""
else:
    df_jobs["failure_template"] = df_jobs["failure_template"].fillna("")

# Prefer job posted time inside window; keep jobs whose run is in window even
# if job posted is slightly outside (Paddles timing quirks).
df_jobs = df_jobs[df_jobs["run_name"].isin(run_names)].copy()

if "description" not in df_jobs.columns:
    df_jobs["description"] = ""
else:
    df_jobs["description"] = df_jobs["description"].fillna("")

completed = df_jobs[df_jobs["status"].isin(_COMPLETED)].copy()
active_jobs = df_jobs[df_jobs["status"].isin(_ACTIVE)].copy()

# ── 2. Cluster health scorecard ───────────────────────────────────────

n_runs = len(run_names)
n_completed = len(completed)
n_pass = int((completed["status"] == "pass").sum()) if n_completed else 0
n_fail = int((completed["status"] == "fail").sum()) if n_completed else 0
n_dead = int((completed["status"] == "dead").sum()) if n_completed else 0
n_active_jobs = len(active_jobs)
pass_rate = round(n_pass / n_completed * 100, 1) if n_completed else 0.0
dead_rate = round(n_dead / n_completed * 100, 1) if n_completed else 0.0
badge, badge_caption = _health_badge(pass_rate, dead_rate)

st.subheader(f"Cluster Health — {window_label}")
st.caption(
    f"Health: **{badge}** — {badge_caption} "
    f"Metrics use all **{n_runs}** runs in this window."
)

c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("Runs", n_runs)
c2.metric("Completed Jobs", n_completed)
c3.metric("Pass Rate", f"{pass_rate}%")
c4.metric("Failed", n_fail)
c5.metric("Dead", n_dead)
c6.metric("Active Jobs", n_active_jobs)

st.divider()

# ── 3. Active runs ────────────────────────────────────────────────────

st.subheader("Active Runs")

active_runs = window_runs[window_runs["status"].isin(_ACTIVE)].copy()
n_queued_runs = int((active_runs["status"] == "queued").sum()) if not active_runs.empty else 0
n_running_runs = int((active_runs["status"] == "running").sum()) if not active_runs.empty else 0

oldest_age = "—"
if not active_runs.empty and active_runs["posted"].notna().any():
    oldest_age = _format_age(active_runs["posted"].min(), now)

r1, r2, r3, r4 = st.columns(4)
r1.metric("Active Runs", len(active_runs))
r2.metric("Queued", n_queued_runs)
r3.metric("Running", n_running_runs)
r4.metric("Oldest Active Age", oldest_age)

if active_runs.empty:
    st.info("No queued or running runs in the selected window.")
else:
    status_order = {"queued": 0, "running": 1}
    runs_display = active_runs.copy()
    runs_display["_sort"] = runs_display["status"].map(status_order).fillna(9)
    runs_display = runs_display.sort_values(
        ["_sort", "posted"], ascending=[True, True]
    )
    # Normalizer stores machine type as cloud_platform on runs.
    if "cloud_platform" in runs_display.columns:
        runs_display["machine_type"] = runs_display["cloud_platform"]

    column_config: dict = {}
    pulpito_base = get_pulpito_url()
    if pulpito_base:
        pulpito_base = pulpito_base.rstrip("/")
        runs_display["name"] = runs_display["name"].apply(
            lambda n: f"{pulpito_base}/{n}/"
        )
        column_config["name"] = st.column_config.LinkColumn(
            label="Run",
            display_text=r"([^/]+)/$",
        )

    cols = [
        c for c in [
            "name", "status", "branch", "suite", "machine_type",
            "user", "total_jobs", "posted",
        ]
        if c in runs_display.columns
    ]
    runs_table = runs_display[cols].reset_index(drop=True)
    st.dataframe(
        runs_table.style.apply(_row_color, axis=1),
        column_config=column_config,
        width="stretch",
        hide_index=True,
        height=min(420, 38 + len(runs_table) * 35),
    )

st.divider()

# ── 4. Top failures ───────────────────────────────────────────────────

st.subheader("Top Failures")
failing = completed[completed["status"].isin(["fail", "dead"])].copy()
if failing.empty:
    st.info("No failures in this window.")
else:
    failing["failure_reason"] = (
        failing["failure_template"]
        .fillna("")
        .replace("", "Unknown failure")
    )
    total_failing_jobs = len(failing)
    col_reasons, col_runs = st.columns(2)

    with col_reasons:
        st.markdown("**Top 10 Failure Reasons**")
        top_fail = (
            failing.groupby("failure_reason")["job_id"]
            .count()
            .reset_index(name="jobs")
            .sort_values("jobs", ascending=False)
            .head(10)
        )
        top_fail["share"] = (top_fail["jobs"] / total_failing_jobs * 100).round(1)
        st.dataframe(
            top_fail.rename(columns={
                "failure_reason": "Failure Reason",
                "jobs": "Jobs",
                "share": "Share (%)",
            }),
            width="stretch",
            hide_index=True,
            height=min(400, 38 + len(top_fail) * 35),
        )

    with col_runs:
        st.markdown("**Top 10 Failure Runs**")
        run_totals = (
            completed.groupby("run_name")["job_id"]
            .count()
            .rename("total_jobs")
        )
        top_runs = (
            failing.groupby("run_name")
            .agg(
                failed_jobs=("job_id", "count"),
                suite=("suite", "first"),
            )
            .join(run_totals, how="left")
            .reset_index()
        )
        top_runs["fail_rate"] = (
            top_runs["failed_jobs"] / top_runs["total_jobs"].replace(0, pd.NA) * 100
        ).round(1)
        top_runs = top_runs.sort_values(
            ["failed_jobs", "fail_rate", "run_name"],
            ascending=[False, False, True],
        ).head(10)

        display_runs = top_runs[
            ["run_name", "suite", "failed_jobs", "fail_rate"]
        ].rename(columns={
            "run_name": "Run",
            "suite": "Suite",
            "failed_jobs": "Failed Jobs",
            "fail_rate": "Fail Rate (%)",
        }).copy()

        runs_col_config: dict = {}
        pulpito_base = get_pulpito_url()
        if pulpito_base:
            pulpito_base = pulpito_base.rstrip("/")
            display_runs["Run"] = display_runs["Run"].apply(
                lambda n: f"{pulpito_base}/{n}/"
            )
            runs_col_config["Run"] = st.column_config.LinkColumn(
                label="Run",
                display_text=r"([^/]+)/$",
            )

        st.dataframe(
            display_runs,
            column_config=runs_col_config,
            width="stretch",
            hide_index=True,
            height=min(400, 38 + len(display_runs) * 35),
        )

st.divider()

# ── 5. Trends (charts at bottom) ──────────────────────────────────────

st.subheader("Trends")

trend = completed.dropna(subset=["posted"]).copy()
if trend.empty:
    st.info("No completed jobs to chart.")
else:
    trend["day"] = trend["posted"].dt.floor("D")
    daily = (
        trend.groupby(["day", "status"])
        .size()
        .reset_index(name="count")
    )
    fig_trend = px.line(
        daily,
        x="day",
        y="count",
        color="status",
        color_discrete_map=_COLOR_MAP,
        markers=True,
        title="Completed Jobs by Day",
        labels={"day": "Day", "count": "Jobs"},
        category_orders={"status": ["pass", "fail", "dead"]},
    )
    fig_trend.update_layout(height=400, legend_title_text="Status")
    st.plotly_chart(fig_trend, width="stretch")

st.markdown("**Job Trends by OS Type**")
os_jobs = completed[completed["os_type"] != "unknown"].copy()
if os_jobs.empty:
    # Fall back to all completed rows so the chart still renders.
    os_jobs = completed.copy()
if os_jobs.empty:
    st.info("No OS type information available for completed jobs.")
else:
    os_list = sorted(os_jobs["os_type"].unique().tolist())
    # One row: top 3 OS types by volume.
    if len(os_list) > 3:
        os_list = (
            os_jobs.groupby("os_type")
            .size()
            .sort_values(ascending=False)
            .head(3)
            .index
            .tolist()
        )
    pie_cols = st.columns(len(os_list))
    for idx, os_name in enumerate(os_list):
        status_counts = (
            os_jobs[os_jobs["os_type"] == os_name]["status"]
            .value_counts()
            .reindex(["pass", "fail", "dead"])
            .dropna()
            .reset_index()
        )
        status_counts.columns = ["status", "count"]
        colors = [_COLOR_MAP.get(s, "#999") for s in status_counts["status"]]
        fig_os = go.Figure(
            go.Pie(
                labels=status_counts["status"].str.capitalize(),
                values=status_counts["count"],
                marker=dict(colors=colors),
                hole=0.4,
                textinfo="percent+label",
                textposition="inside",
                hovertemplate=(
                    "%{label}<br>Jobs=%{value}<br>Share=%{percent}<extra></extra>"
                ),
            )
        )
        fig_os.update_layout(
            title=dict(text=os_name, x=0.5),
            height=300,
            margin=dict(l=10, r=10, t=40, b=10),
            showlegend=False,
        )
        with pie_cols[idx]:
            st.plotly_chart(fig_os, width="stretch")

# Suite trend lives with charts, not in the Top Failures tables.
suite_jobs = completed[completed["suite"] != "unknown"].copy()
if suite_jobs.empty:
    suite_jobs = completed.copy()
if suite_jobs.empty:
    st.info("No suite information available for completed jobs.")
else:
    suite_counts = (
        suite_jobs.groupby(["suite", "status"])
        .size()
        .reset_index(name="count")
    )
    # Keep the chart readable: top suites by volume, then remaining as "other".
    suite_order = (
        suite_counts.groupby("suite")["count"]
        .sum()
        .sort_values(ascending=False)
    )
    top_suite_names = suite_order.head(12).index.tolist()
    suite_plot = suite_counts.copy()
    suite_plot.loc[~suite_plot["suite"].isin(top_suite_names), "suite"] = "other"
    suite_plot = (
        suite_plot.groupby(["suite", "status"], as_index=False)["count"]
        .sum()
    )
    suite_totals = suite_plot.groupby("suite")["count"].transform("sum")
    suite_plot["percentage"] = (
        suite_plot["count"] / suite_totals.replace(0, pd.NA) * 100
    ).round(1)
    suite_plot["label"] = suite_plot["percentage"].map(lambda v: f"{v:.1f}%")
    fig_suite = px.bar(
        suite_plot,
        x="suite",
        y="percentage",
        color="status",
        color_discrete_map=_COLOR_MAP,
        barmode="stack",
        text="label",
        title="Job Trends by Suite (%)",
        labels={"suite": "Suite", "percentage": "Share (%)", "count": "Jobs"},
        hover_data={"count": True, "percentage": True, "label": False},
        category_orders={
            "status": ["pass", "fail", "dead"],
            "suite": top_suite_names + (
                ["other"] if (suite_plot["suite"] == "other").any() else []
            ),
        },
    )
    fig_suite.update_layout(
        height=400,
        legend_title_text="Status",
        yaxis_range=[0, 100],
    )
    fig_suite.update_traces(textposition="inside", cliponaxis=False)
    st.plotly_chart(fig_suite, width="stretch")
