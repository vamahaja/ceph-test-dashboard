from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from libs.config import get_nightly_run_user, get_pulpito_url
from libs.normalizer import get_jobs_data, get_runs_data


st.markdown(
    "<h1 style='text-align: center;'>Nightly Regression Status</h1>",
    unsafe_allow_html=True,
)
st.markdown(
    "Track standard scheduled nightly regression runs and quickly identify failures "
    "or runs that still need attention."
)

nightly_run_user = get_nightly_run_user()

runs_data = get_runs_data()
if not runs_data:
    st.warning("Could not fetch nightly run data from the API.")
    st.stop()


df_runs = pd.DataFrame(runs_data)
if df_runs.empty:
    st.info("No nightly runs found.")
    st.stop()

for column in ["scheduled", "posted"]:
    if column in df_runs.columns:
        df_runs[column] = pd.to_datetime(df_runs[column], errors="coerce")

nightly_mask = (
    df_runs["scheduled"].notna()
    & df_runs["user"].fillna("").eq(nightly_run_user)
)
nightly_runs = df_runs[nightly_mask].copy()

if nightly_runs.empty:
    st.info(
        f"No standard scheduled nightly regression runs for user `{nightly_run_user}` were found."
    )
    st.stop()

default_end = date.today()
default_start = default_end - timedelta(days=6)
date_range = st.sidebar.date_input(
    "Scheduled date range",
    value=(default_start, default_end),
)
if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
    start_date, end_date = date_range
else:
    start_date, end_date = default_start, default_end

available_branches = sorted(
    value for value in nightly_runs["branch"].dropna().unique().tolist() if value
)
selected_branch = st.sidebar.selectbox(
    "Branch",
    options=available_branches,
)

available_suites = sorted(
    value for value in nightly_runs["suite"].dropna().unique().tolist() if value
)
selected_suites = st.sidebar.multiselect(
    "Suite",
    options=available_suites,
    default=available_suites,
)

filtered_runs = nightly_runs[
    (nightly_runs["scheduled"].dt.date >= start_date)
    & (nightly_runs["scheduled"].dt.date <= end_date)
    & nightly_runs["branch"].eq(selected_branch)
    & nightly_runs["suite"].isin(selected_suites)
].copy()

if filtered_runs.empty:
    st.warning("No nightly runs match the selected filters.")
    st.stop()

run_details = filtered_runs.set_index("name")[["branch", "suite"]].to_dict("index")
all_jobs: list[dict] = []
run_names = filtered_runs["name"].tolist()
progress_bar = st.progress(0, text="Loading job data…")
for i, run_name in enumerate(run_names):
    progress_bar.progress(
        int((i + 1) / len(run_names) * 100),
        text=f"Loading jobs for run {i + 1} of {len(run_names)}…",
    )
    run_jobs = get_jobs_data(run_name=run_name)
    if not run_jobs:
        continue
    details = run_details.get(run_name, {})
    for job in run_jobs:
        if not job.get("branch"):
            job["branch"] = details.get("branch", "")
        if not job.get("suite"):
            job["suite"] = details.get("suite", "")
        all_jobs.append(job)
progress_bar.empty()

df_jobs = pd.DataFrame(all_jobs)
if not df_jobs.empty and "posted" in df_jobs.columns:
    df_jobs["posted"] = pd.to_datetime(df_jobs["posted"], errors="coerce")

alert_runs = filtered_runs[filtered_runs["status"].isin(["fail", "dead", "queued", "running"])]
completed_runs = filtered_runs[filtered_runs["status"] == "pass"]
active_runs = filtered_runs[filtered_runs["status"].isin(["queued", "running"])]

failed_jobs = 0
running_jobs = 0
queued_jobs = 0
if not df_jobs.empty and "status" in df_jobs.columns:
    failed_jobs = int(df_jobs["status"].isin(["fail", "dead"]).sum())
    running_jobs = int(df_jobs["status"].eq("running").sum())
    queued_jobs = int(df_jobs["status"].eq("queued").sum())

latest_failure_reasons = pd.DataFrame()
if not df_jobs.empty and "status" in df_jobs.columns:
    failing_jobs = df_jobs[df_jobs["status"].isin(["fail", "dead"])]
    if not failing_jobs.empty:
        latest_failure_reasons = failing_jobs.copy()
        latest_failure_reasons["failure_reason"] = latest_failure_reasons[
            "failure_template"
        ].fillna("Unknown failure")
        latest_failure_reasons.loc[
            latest_failure_reasons["failure_reason"].eq(""), "failure_reason"
        ] = "Unknown failure"
        latest_failure_reasons = latest_failure_reasons.groupby("failure_reason").agg(
            jobs_impacted=("job_id", "count"),
            runs_impacted=("run_name", "nunique"),
        ).reset_index()
        latest_failure_reasons["share"] = (
            latest_failure_reasons["jobs_impacted"]
            / latest_failure_reasons["jobs_impacted"].sum()
            * 100
        ).round(1)
        latest_failure_reasons = latest_failure_reasons.sort_values(
            ["jobs_impacted", "runs_impacted", "failure_reason"],
            ascending=[False, False, True],
        ).head(10)

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Nightly Runs", len(filtered_runs))
col2.metric("Runs Alerting", len(alert_runs))
col3.metric("Completed", len(completed_runs))
col4.metric("Jobs Failed", failed_jobs)
col5.metric("Jobs Active", running_jobs + queued_jobs)

if not alert_runs.empty:
    st.error(
        f"{len(alert_runs)} nightly runs require attention: "
        f"{len(active_runs)} still active and {len(filtered_runs[filtered_runs['status'].isin(['fail', 'dead'])])} failed."
    )
else:
    st.success("All selected nightly regression runs completed successfully.")

st.divider()

st.subheader("Tests Run Results")

total_runs = len(filtered_runs)
passed_runs = len(completed_runs)
pass_pct = round(passed_runs / total_runs * 100, 2) if total_runs else 0

total_jobs_count = len(df_jobs) if not df_jobs.empty else 0
passed_jobs_count = int(df_jobs["status"].eq("pass").sum()) if not df_jobs.empty else 0

status_colors = {
    "pass":    "#54b399",
    "fail":    "#d36086",
    "dead":    "#aa6556",
    "running": "#6092c0",
    "queued":  "#d6bf57",
    "unknown": "#9170b8",
}

trend_color_map = {k: v for k, v in status_colors.items() if k != "dead"}

kpi_col, chart_col = st.columns([1, 3])

with kpi_col:
    st.metric("PASSED TEST RUNS", f"{pass_pct}%")
    st.caption(f"{passed_runs} runs passed (out of {total_runs})")
    st.caption(f"{passed_jobs_count} jobs passed (out of {total_jobs_count})")
    failed_runs = len(filtered_runs[filtered_runs["status"].isin(["fail", "dead"])])
    active_count = len(filtered_runs[filtered_runs["status"].isin(["running", "queued"])])
    st.caption(f"{failed_runs} runs failed")
    st.caption(f"{active_count} runs active")

with chart_col:
    if not df_jobs.empty and "posted" in df_jobs.columns:
        job_trend = df_jobs.copy()
        job_trend["date"] = job_trend["posted"].dt.strftime("%b %d")
        job_trend["status"] = job_trend["status"].replace("dead", "fail")

        daily_jobs = (
            job_trend.groupby(["date", "status"])
            .size()
            .reset_index(name="count")
        )

        date_order = job_trend.sort_values("posted")["date"].unique().tolist()

        daily_totals = job_trend.groupby("date")["status"].count().reset_index(name="total")
        daily_jobs = daily_jobs.merge(daily_totals, on="date")
        daily_jobs["percentage"] = (daily_jobs["count"] / daily_jobs["total"] * 100).round(1)

        fig_trend = px.line(
            daily_jobs,
            x="date",
            y="percentage",
            color="status",
            color_discrete_map=trend_color_map,
            markers=True,
            category_orders={"date": date_order},
            labels={"date": "Date", "percentage": "Percentage (%)", "status": "Status"},
        )
        fig_trend.update_layout(
            height=300,
            legend_title_text="Status",
            yaxis_range=[0, 105],
            margin=dict(l=40, r=20, t=10, b=40),
            xaxis_type="category",
        )
        st.plotly_chart(fig_trend, width="stretch")
    else:
        st.info("No job data available to show the trend.")

st.divider()

st.subheader("OS-wise Job Distribution")
os_jobs = df_jobs[df_jobs["os_type"].notna() & (df_jobs["os_type"] != "")].copy() if not df_jobs.empty else pd.DataFrame()
if os_jobs.empty:
    st.info("No OS type information available in the current job data.")
else:
    os_list = sorted(os_jobs["os_type"].unique())
    pie_cols = st.columns(min(len(os_list), 3))
    for idx, os_name in enumerate(os_list):
        os_slice = os_jobs[os_jobs["os_type"] == os_name]
        status_counts = os_slice["status"].value_counts().reset_index()
        status_counts.columns = ["status", "count"]
        colors = [status_colors.get(s, "#999") for s in status_counts["status"]]

        fig_pie = go.Figure(go.Pie(
            labels=status_counts["status"].str.capitalize(),
            values=status_counts["count"],
            marker=dict(colors=colors),
            hole=0.4,
            textinfo="percent+label",
            textposition="inside",
        ))
        fig_pie.update_layout(
            title=dict(text=os_name, x=0.5),
            height=300,
            margin=dict(l=10, r=10, t=40, b=10),
            showlegend=False,
        )
        with pie_cols[idx % len(pie_cols)]:
            st.plotly_chart(fig_pie, width="stretch")

st.divider()

st.subheader("All Nightly Runs")
nightly_runs_table = filtered_runs.copy()
nightly_runs_table["scheduled_date"] = nightly_runs_table["scheduled"].dt.date
cols_order = ["scheduled_date", "name", "branch", "suite", "status", "user", "total_jobs", "posted"]
display_cols = [col for col in cols_order if col in nightly_runs_table.columns]

pulpito_base = get_pulpito_url()
column_config: dict = {}
if pulpito_base:
    pulpito_base = pulpito_base.rstrip("/")
    nightly_runs_table["name"] = nightly_runs_table["name"].apply(
        lambda value: f"{pulpito_base}/{value}/"
    )
    column_config["name"] = st.column_config.LinkColumn(
        label="Run",
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
    nightly_runs_table[display_cols]
    .sort_values(["scheduled_date", "name"], ascending=[False, True])
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

st.divider()

st.subheader("Top Failure Reasons")
if latest_failure_reasons.empty:
    st.info("No failing jobs were found for the selected nightly runs.")
else:
    display_failures = latest_failure_reasons.rename(
        columns={
            "failure_reason": "Failure Reason",
            "jobs_impacted": "Jobs Impacted",
            "runs_impacted": "Runs Impacted",
            "share": "Share (%)",
        }
    ).reset_index(drop=True)

    event = st.dataframe(
        display_failures,
        width="stretch",
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
    )

    selected_rows = event.selection.rows
    if selected_rows:
        row_idx = selected_rows[0]
        selected_reason = latest_failure_reasons.iloc[row_idx]["failure_reason"]
        jobs_count = int(latest_failure_reasons.iloc[row_idx]["jobs_impacted"])
        runs_count = int(latest_failure_reasons.iloc[row_idx]["runs_impacted"])

        normalised_reasons = (
            df_jobs["failure_template"]
            .fillna("Unknown failure")
            .replace("", "Unknown failure")
        )
        failing_for_reason = df_jobs[
            df_jobs["status"].isin(["fail", "dead"])
            & normalised_reasons.eq(selected_reason)
        ]
        impacted_run_names = failing_for_reason["run_name"].unique().tolist()

        impacted_runs_df = filtered_runs[filtered_runs["name"].isin(impacted_run_names)]
        impacted_runs_records = impacted_runs_df.to_dict("records")

        col_j, col_r = st.columns(2)
        with col_j:
            if st.button(f"View {jobs_count} Impacted Jobs →"):
                st.session_state["drill_run_names"] = impacted_run_names
                st.switch_page(
                    "pages/reports/jobs.py",
                    query_params={"failure_reason": selected_reason, "source": "nightly"},
                )
        with col_r:
            if st.button(f"View {runs_count} Impacted Runs →"):
                st.session_state["drill_run_names"] = impacted_run_names
                st.session_state["drill_run_records"] = impacted_runs_records
                st.switch_page(
                    "pages/reports/testruns.py",
                    query_params={"failure_reason": selected_reason, "source": "nightly"},
                )
