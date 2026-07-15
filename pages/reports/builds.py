import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from libs.normalizer import get_jobs_data, get_runs_data
from libs.config import get_pulpito_url

st.markdown(
    "<h1 style='text-align: center;'>Build Analysis</h1>",
    unsafe_allow_html=True,
)
st.markdown(
    "Isolate and evaluate testing metrics for a specific Ceph build artifact or commit SHA."
)

st.sidebar.header("Filters")

runs_data = get_runs_data(count=200)
if not runs_data:
    st.warning("Could not fetch run data from the API.")
    st.stop()

df_runs = pd.DataFrame(runs_data)
df_runs["posted"] = pd.to_datetime(df_runs["posted"], errors="coerce")
df_runs.drop_duplicates(subset=["name"], inplace=True)

completed_statuses = {"pass", "fail", "dead"}
completed_runs = df_runs[df_runs["status"].isin(completed_statuses)].copy()

available_branches = sorted(
    b for b in completed_runs["branch"].dropna().unique().tolist() if b
)
if not available_branches:
    st.warning("No completed branches found in recent runs.")
    st.stop()

selected_branch = st.sidebar.selectbox("Branch", available_branches)

branch_runs = completed_runs[completed_runs["branch"] == selected_branch].copy()
if branch_runs.empty:
    st.warning(f"No completed runs found for branch **{selected_branch}**.")
    st.stop()

all_suites = sorted(branch_runs["suite"].dropna().unique().tolist())
selected_suites = st.sidebar.multiselect("Suite", all_suites, default=all_suites)

filt_runs = branch_runs[branch_runs["suite"].isin(selected_suites)].copy()
if filt_runs.empty:
    st.warning("No completed runs match the selected filters.")
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
df_jobs["posted"] = pd.to_datetime(df_jobs["posted"], errors="coerce")

filt_jobs = df_jobs[df_jobs["suite"].isin(selected_suites)].copy()
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

sha_ids = filt_runs["sha_id"].fillna("unknown").replace("", "unknown").unique().tolist()
if len(sha_ids) > 1:
    st.divider()
    st.subheader("Per-SHA Comparison")

    sha_job_stats = []
    for sha in sha_ids:
        sha_run_names = filt_runs[filt_runs["sha_id"] == sha]["name"].tolist()
        sha_jobs = filt_jobs[filt_jobs["run_name"].isin(sha_run_names)]
        sha_total = len(sha_jobs)
        sha_passed = int((sha_jobs["status"] == "pass").sum())
        sha_failed = int(sha_jobs["status"].isin(["fail", "dead"]).sum())
        sha_job_stats.append({
            "sha": sha[:8],
            "runs": len(sha_run_names),
            "jobs": sha_total,
            "passed": sha_passed,
            "failed": sha_failed,
            "pass_rate": round(sha_passed / sha_total * 100, 1) if sha_total else 0.0,
        })

    sha_stats_df = pd.DataFrame(sha_job_stats)

    fig_sha = px.bar(
        sha_stats_df,
        x="sha",
        y=["passed", "failed"],
        color_discrete_map={"passed": color_map["pass"], "failed": color_map["fail"]},
        barmode="stack",
        text_auto=True,
        title=f"Pass / Fail per SHA — {selected_branch}",
        labels={"sha": "Commit SHA", "value": "Jobs", "variable": "Result"},
    )
    fig_sha.update_layout(height=380, legend_title_text="Result")
    st.plotly_chart(fig_sha, width="stretch")

    st.dataframe(
        sha_stats_df.rename(columns={
            "sha": "SHA", "runs": "Runs", "jobs": "Jobs",
            "passed": "Passed", "failed": "Failed", "pass_rate": "Pass Rate (%)",
        }),
        width="stretch",
        hide_index=True,
    )

st.divider()

st.subheader(f"Completed Runs ({total_runs})")

pulpito_base = get_pulpito_url()
if pulpito_base:
    pulpito_base = pulpito_base.rstrip("/")

runs_display = filt_runs.copy()
if "cloud_platform" in runs_display.columns:
    runs_display.rename(columns={"cloud_platform": "machine_type"}, inplace=True)

if "started" in runs_display.columns and "updated" in runs_display.columns:
    runs_display["started"] = pd.to_datetime(runs_display["started"], errors="coerce")
    runs_display["updated"] = pd.to_datetime(runs_display["updated"], errors="coerce")
    runtime = runs_display["updated"] - runs_display["started"]

    def _fmt_runtime(td):
        if pd.isna(td):
            return "—"
        secs = td.total_seconds()
        if secs <= 0:
            return "—"
        return f"{int(secs // 3600)}h {int((secs % 3600) // 60)}m"

    runs_display["runtime"] = runtime.apply(_fmt_runtime)

if "sha_id" in runs_display.columns:
    runs_display["sha_id"] = runs_display["sha_id"].fillna("").apply(lambda s: s[:8])

if pulpito_base and "name" in runs_display.columns:
    runs_display["name"] = runs_display["name"].apply(
        lambda n: f"{pulpito_base}/{n}/"
    )

runs_cols_order = [
    "name", "status", "suite", "sha_id", "user", "machine_type",
    "total_jobs", "runtime", "posted",
]
runs_display_cols = [c for c in runs_cols_order if c in runs_display.columns]

runs_col_config: dict = {}
if pulpito_base:
    runs_col_config["name"] = st.column_config.LinkColumn(
        label="Run", display_text=r"([^/]+)/$",
    )

sort_cols = ["sha_id", "posted"] if "sha_id" in runs_display_cols else ["posted"]
runs_table = (
    runs_display[runs_display_cols]
    .sort_values(sort_cols, ascending=[False, False] if len(sort_cols) == 2 else [False])
    .reset_index(drop=True)
)
runs_table_height = min(800, 38 + len(runs_table) * 35)
st.dataframe(
    runs_table.style.apply(_row_color, axis=1),
    column_config=runs_col_config,
    width="stretch",
    height=runs_table_height,
    hide_index=True,
)

st.divider()

st.subheader("Suite Health")

suite_status = (
    filt_jobs.groupby(["suite", "status"])
    .size()
    .reset_index(name="count")
)
suite_totals = suite_status.groupby("suite")["count"].transform("sum")
suite_status["percentage"] = (suite_status["count"] / suite_totals * 100).round(1)

chart_title = f"Suite Health — {selected_branch}"

fig_suite = px.bar(
    suite_status,
    x="suite",
    y="percentage",
    color="status",
    color_discrete_map=color_map,
    barmode="stack",
    title=chart_title,
    labels={"suite": "Suite", "percentage": "Percentage (%)", "status": "Status"},
)
fig_suite.update_layout(height=400, legend_title_text="Status", yaxis_range=[0, 105])
st.plotly_chart(fig_suite, width="stretch")

st.divider()

st.subheader("OS-wise Job Distribution")

os_jobs = filt_jobs[filt_jobs["os_type"].notna() & (filt_jobs["os_type"] != "")].copy()
if os_jobs.empty:
    st.info("No OS type information available in the current job data.")
else:
    os_list = sorted(os_jobs["os_type"].unique())
    pie_cols = st.columns(min(len(os_list), 3))
    for idx, os_name in enumerate(os_list):
        os_slice = os_jobs[os_jobs["os_type"] == os_name]
        status_counts = os_slice["status"].value_counts().reset_index()
        status_counts.columns = ["status", "count"]
        colors = [color_map.get(s, "#999") for s in status_counts["status"]]

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

st.subheader("Top Failure Reasons")

failing_jobs = filt_jobs[filt_jobs["status"].isin(["fail", "dead"])]
if failing_jobs.empty:
    st.info("No failing jobs found for the selected filters.")
else:
    failure_reasons = failing_jobs.copy()
    failure_reasons["failure_reason"] = (
        failure_reasons["failure_template"]
        .fillna("Unknown failure")
        .replace("", "Unknown failure")
    )
    failure_summary = failure_reasons.groupby("failure_reason").agg(
        jobs_impacted=("job_id", "count"),
        runs_impacted=("run_name", "nunique"),
    ).reset_index()
    failure_summary["share"] = (
        failure_summary["jobs_impacted"]
        / failure_summary["jobs_impacted"].sum()
        * 100
    ).round(1)
    failure_summary = failure_summary.sort_values(
        ["jobs_impacted", "runs_impacted", "failure_reason"],
        ascending=[False, False, True],
    ).head(10)

    display_failures = failure_summary.rename(
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
        selected_reason = failure_summary.iloc[row_idx]["failure_reason"]
        jobs_count = int(failure_summary.iloc[row_idx]["jobs_impacted"])
        runs_count = int(failure_summary.iloc[row_idx]["runs_impacted"])

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

        impacted_runs_df = filt_runs[filt_runs["name"].isin(impacted_run_names)]
        impacted_runs_records = impacted_runs_df.to_dict("records")

        col_j, col_r = st.columns(2)
        with col_j:
            if st.button(f"View {jobs_count} Impacted Jobs →"):
                st.session_state["drill_run_names"] = impacted_run_names
                st.switch_page(
                    "pages/reports/jobs.py",
                    query_params={"failure_reason": selected_reason, "source": "builds"},
                )
        with col_r:
            if st.button(f"View {runs_count} Impacted Runs →"):
                st.session_state["drill_run_names"] = impacted_run_names
                st.session_state["drill_run_records"] = impacted_runs_records
                st.switch_page(
                    "pages/reports/testruns.py",
                    query_params={"failure_reason": selected_reason, "source": "builds"},
                )
