import pandas as pd
import plotly.express as px
import streamlit as st
from datetime import date, timedelta

from libs.normalizer import get_jobs_data, get_runs_by_branch_data
from libs.config import get_pulpito_url

st.set_page_config(layout="wide")
st.markdown(
    "<h1 style='text-align: center;'>📦 Release Health Dashboard</h1>",
    unsafe_allow_html=True,
)
st.markdown(
    "Monitor the overall health and pass/fail ratios of a stable Ceph release branch."
)

st.sidebar.header("Filters")

RELEASE_BRANCHES = sorted(["tentacle", "squid", "umbrella"])
selected_branch = st.sidebar.selectbox("Branch", RELEASE_BRANCHES)

today = date.today()
default_start = today - timedelta(days=7)
date_range = st.sidebar.date_input(
    "Date range",
    value=(default_start, today),
)
if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
    start_date, end_date = date_range
else:
    start_date, end_date = default_start, today

all_runs = get_runs_by_branch_data(selected_branch, count=100)

if not all_runs:
    st.warning(f"Could not fetch run data for branch **{selected_branch}**.")
    st.stop()

df_runs = pd.DataFrame(all_runs)
df_runs["posted"] = pd.to_datetime(df_runs["posted"])
df_runs.drop_duplicates(subset=["name"], inplace=True)

all_suites = sorted(df_runs["suite"].dropna().unique().tolist())
selected_suites = st.sidebar.multiselect(
    "Suite", all_suites, default=all_suites
)

filt_runs = df_runs[
    (df_runs["posted"].dt.date >= start_date)
    & (df_runs["posted"].dt.date <= end_date)
    & (df_runs["suite"].isin(selected_suites))
].copy()

if filt_runs.empty:
    st.warning("No runs found for the selected filters.")
    st.stop()

run_info = filt_runs.set_index("name")[["branch", "suite", "sha_id"]].to_dict("index")

all_jobs: list[dict] = []
run_names = filt_runs["name"].unique().tolist()
progress_bar = st.progress(0, text="Loading job data…")
for i, run_name in enumerate(run_names):
    progress_bar.progress(
        int((i + 1) / len(run_names) * 100),
        text=f"Loading jobs for run {i + 1} of {len(run_names)}…",
    )
    run_jobs = get_jobs_data(run_name=run_name)
    if run_jobs:
        info = run_info.get(run_name, {})
        for job in run_jobs:
            if not job.get("branch"):
                job["branch"] = info.get("branch", "")
            if not job.get("suite"):
                job["suite"] = info.get("suite", "")
            if not job.get("sha_id"):
                job["sha_id"] = info.get("sha_id", "")
            all_jobs.append(job)
progress_bar.empty()

if not all_jobs:
    st.warning("No job data available for the selected runs.")
    st.stop()

df_jobs = pd.DataFrame(all_jobs)
df_jobs["posted"] = pd.to_datetime(df_jobs["posted"])

filt_jobs = df_jobs[
    (df_jobs["suite"].isin(selected_suites))
    & (df_jobs["posted"].dt.date >= start_date)
    & (df_jobs["posted"].dt.date <= end_date)
].copy()

if filt_jobs.empty:
    st.warning("No job data matches the selected filters.")
    st.stop()

color_map = {
    "pass":    "#54b399",
    "fail":    "#d36086",
    "dead":    "#aa6556",
    "running": "#6092c0",
    "queued":  "#d6bf57",
    "unknown": "#9170b8",
}

total_runs = len(filt_runs)
total_jobs = len(filt_jobs)
passed = int((filt_jobs["status"] == "pass").sum())
failed = int((filt_jobs["status"].isin(["fail", "dead"])).sum())
pass_rate = round(passed / total_jobs * 100, 1) if total_jobs else 0.0
fail_rate = round(failed / total_jobs * 100, 1) if total_jobs else 0.0

st.subheader(f"{selected_branch} — Health Scorecard")
s1, s2, s3, s4 = st.columns(4)
s1.metric("Total Runs", total_runs)
s2.metric("Total Jobs", total_jobs)
s3.metric("Pass Rate", f"{pass_rate}%")
s4.metric("Fail Rate", f"{fail_rate}%")

st.divider()

st.subheader("Status Trend")

filt_jobs["date"] = filt_jobs["posted"].dt.date

# Merge `dead` into `fail` so the combined infrastructure+test failure signal
# is not split across two separate trend lines, giving the PO a single clear
# failure indicator for release decisions.
trend_jobs = filt_jobs.copy()
trend_jobs["status"] = trend_jobs["status"].replace("dead", "fail")

daily_status = (
    trend_jobs.groupby(["date", "status"])
    .size()
    .reset_index(name="count")
)
daily_totals = trend_jobs.groupby("date")["status"].count().reset_index(name="total")
daily_status = daily_status.merge(daily_totals, on="date")
daily_status["percentage"] = (daily_status["count"] / daily_status["total"] * 100).round(1)

trend_color_map = {k: v for k, v in color_map.items() if k != "dead"}

fig_trend = px.line(
    daily_status.sort_values("date"),
    x="date",
    y="percentage",
    color="status",
    color_discrete_map=trend_color_map,
    markers=True,
    title=f"Daily Status Trend — {selected_branch} (dead counted as fail)",
    labels={"date": "Date", "percentage": "Percentage (%)", "status": "Status"},
)
fig_trend.update_layout(height=380, legend_title_text="Status", yaxis_range=[0, 105])
st.plotly_chart(fig_trend, width="stretch")

st.divider()

st.subheader("Suite Health")

suite_status = (
    filt_jobs.groupby(["suite", "status"])
    .size()
    .reset_index(name="count")
)
suite_totals = suite_status.groupby("suite")["count"].transform("sum")
suite_status["percentage"] = (suite_status["count"] / suite_totals * 100).round(1)

fig_suite = px.bar(
    suite_status,
    x="suite",
    y="percentage",
    color="status",
    color_discrete_map=color_map,
    barmode="stack",
    title=f"Suite Health — {selected_branch}",
    labels={"suite": "Suite", "percentage": "Percentage (%)", "status": "Status"},
)
fig_suite.update_layout(height=400, legend_title_text="Status", yaxis_range=[0, 105])
st.plotly_chart(fig_suite, width="stretch")

st.divider()

st.subheader("OS-wise Pass / Fail")

os_jobs = filt_jobs[filt_jobs["os_type"].notna() & (filt_jobs["os_type"] != "")].copy()
if os_jobs.empty:
    st.info("No OS type information available in the current job data.")
else:
    os_jobs["result"] = os_jobs["status"].replace("dead", "fail")

    os_counts = (
        os_jobs.groupby(["os_type", "result"])
        .size()
        .reset_index(name="count")
    )
    os_totals = os_counts.groupby("os_type")["count"].transform("sum")
    os_counts["percentage"] = (os_counts["count"] / os_totals * 100).round(1)

    fig_os = px.bar(
        os_counts,
        x="os_type",
        y="percentage",
        color="result",
        color_discrete_map={
            "pass":    color_map["pass"],
            "fail":    color_map["fail"],
            "running": color_map["running"],
            "queued":  color_map["queued"],
            "unknown": color_map["unknown"],
        },
        barmode="stack",
        text="percentage",
        title=f"OS-wise Job Status — {selected_branch}",
        labels={"os_type": "OS Type", "percentage": "Percentage (%)", "result": "Status"},
    )
    fig_os.update_traces(texttemplate="%{text:.1f}%", textposition="inside")
    fig_os.update_layout(height=420, legend_title_text="Status", yaxis_range=[0, 105])
    st.plotly_chart(fig_os, width="stretch")

st.divider()

st.subheader("Results by Commit SHA")

filt_jobs["sha_short"] = filt_jobs["sha_id"].str[:8]

_sh_total = filt_jobs.groupby("sha_short")["status"].count().rename("total")
_sh_passed = filt_jobs[filt_jobs["status"] == "pass"].groupby("sha_short")["status"].count().rename("passed")
_sh_failed = filt_jobs[filt_jobs["status"].isin(["fail", "dead"])].groupby("sha_short")["status"].count().rename("failed")
sha_stats = pd.concat([_sh_total, _sh_passed, _sh_failed], axis=1).fillna(0).reset_index()
sha_stats["pass_rate"] = (sha_stats["passed"] / sha_stats["total"] * 100).round(1)

fig_sha = px.bar(
    sha_stats.sort_values("pass_rate"),
    x="sha_short",
    y=["passed", "failed"],
    color_discrete_map={"passed": color_map["pass"], "failed": color_map["fail"]},
    barmode="stack",
    title=f"Pass / Fail per Commit SHA — {selected_branch}",
    labels={"sha_short": "SHA", "value": "Jobs", "variable": "Result"},
)
fig_sha.update_layout(height=400, legend_title_text="Result")
st.plotly_chart(fig_sha, width="stretch")

st.divider()

st.subheader(f"Runs ({total_runs})")

runs_display = filt_runs.copy()
if "cloud_platform" in runs_display.columns:
    runs_display.rename(columns={"cloud_platform": "machine_type"}, inplace=True)

pulpito_base = get_pulpito_url()
if pulpito_base:
    pulpito_base = pulpito_base.rstrip("/")
    runs_display["name"] = runs_display["name"].apply(
        lambda n: f"{pulpito_base}/{n}/"
    )

cols_order = [
    "name", "status", "suite", "machine_type",
    "user", "total_jobs", "posted",
]
display_cols = [c for c in cols_order if c in runs_display.columns] + [
    c for c in runs_display.columns
    if c not in cols_order and c not in ("job_ids", "results", "sha_id", "scheduled", "branch")
]

column_config: dict = {}
if pulpito_base:
    column_config["name"] = st.column_config.LinkColumn(
        label="Name",
        display_text=r"([^/]+)/$",
    )

_status_colors = {
    "pass":    "background-color: #54b399; color: white",
    "fail":    "background-color: #d36086; color: white",
    "dead":    "background-color: #aa6556; color: white",
    "running": "background-color: #6092c0; color: white",
    "queued":  "background-color: #d6bf57; color: white",
    "unknown": "background-color: #9170b8; color: white",
}

def _row_color(row):
    style = _status_colors.get(row.get("status", ""), "")
    return [style] * len(row)

runs_table = (
    runs_display[display_cols]
    .sort_values("posted", ascending=False)
    .reset_index(drop=True)
)
table_height = min(800, 38 + len(runs_table) * 35)
st.dataframe(
    runs_table.style.apply(_row_color, axis=1),
    column_config=column_config,
    width="stretch",
    height=table_height,
    hide_index=True,
)
