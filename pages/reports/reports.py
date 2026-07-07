import pandas as pd
import streamlit as st
import altair as alt

from libs.normalizer import get_jobs_data, get_runs_data

# Set page title
st.markdown(
    "<h1 style=\"text-align: center;\">Testruns Reports</h1>",
    unsafe_allow_html=True
)

runs_data = get_runs_data()
df_runs = pd.DataFrame(runs_data)
df_runs["posted"] = pd.to_datetime(df_runs["posted"])
branch_names = df_runs["branch"].unique().tolist()

# Get test run to show jobs
selected_branch = st.selectbox("Select a branch to view reports:", branch_names)

jobs_data = get_jobs_data(branch_name=selected_branch)
if not jobs_data:
    st.info(f"No jobs exist for run `{selected_branch}`.")
    st.stop()

# Convert to DataFrame
df_jobs = pd.DataFrame(jobs_data)
if df_jobs.empty:
    st.info(f"No jobs exist for run `{selected_branch}`.")
    st.stop()

# Data prep for pie charts
df_jobs["posted"] = pd.to_datetime(df_jobs["posted"])
last_run_name = df_jobs.sort_values(by="posted", ascending=False)["run_name"].iloc[0]
last_run_df = df_jobs[df_jobs["run_name"] == last_run_name]
status_counts_last_run = last_run_df["status"].value_counts().reset_index()
status_counts_branch = df_jobs["status"].value_counts().reset_index()

# Create Altair charts
pie_chart_last_run = alt.Chart(status_counts_last_run).mark_arc(innerRadius=50).encode(
    theta=alt.Theta(field="count", type="quantitative"),
    color=alt.Color(
        field="status", type="nominal",
        scale=alt.Scale(
            domain=["pass", "fail", "running", "queued", "dead"],
            range=["#28a745", "#dc3545", "#ffc107", "#6c757d", "#000000"]
        )
    ),
    tooltip=["status", "count"]
).properties(title=f"Job Status for {last_run_name}")

pie_chart_branch = alt.Chart(status_counts_branch).mark_arc(innerRadius=50).encode(
    theta=alt.Theta(field="count", type="quantitative"),
    color=alt.Color(
        field="status", type="nominal",
        scale=alt.Scale(
            domain=["pass", "fail", "running", "queued", "dead"],
            range=["#28a745", "#dc3545", "#ffc107", "#6c757d", "#000000"]
        )
    ),
    tooltip=["status", "count"]
).properties(title=f"Job Status for {selected_branch} branch")

# Get unique run names from df_jobs for the selected branch
branch_run_names = df_jobs["run_name"].unique()

# Filter df_runs for these runs
branch_runs = df_runs[df_runs["name"].isin(branch_run_names)]

# Sort by posted date and get last two
last_two_run_names = branch_runs.sort_values(
    "posted", ascending=False
).head(2)["name"].tolist()

# Filter df_jobs for these two runs
comparison_df = df_jobs[df_jobs["run_name"].isin(last_two_run_names)]

# Create stacked bar chart for comparison
comparison_chart = alt.Chart(comparison_df).mark_bar().encode(
    x=alt.X("run_name:N", title="Test Run", axis=alt.Axis(labelAngle=0)),
    y=alt.Y("count():Q", axis=alt.Axis(title="Job Count", format="d")),
    color="status:N"
)

# Display charts side-by-side
col1, col2, col3 = st.columns(3)
with col1:
    st.subheader(f"Branch: {selected_branch}")
    st.altair_chart(pie_chart_branch, width="stretch")
with col2:
    st.subheader(f"Last Run: {last_run_name}")
    st.altair_chart(pie_chart_last_run, width="stretch")
with col3:
    st.subheader("Comparison of Last Two Runs")
    st.altair_chart(comparison_chart, width="stretch")


# Line chart for pass, fail, running, queued and dead
st.subheader("Test Run Results")
status_counts = (
    df_jobs.groupby(["run_name", "status"])
    .size()
    .unstack(fill_value=0)
)
st.line_chart(status_counts)

# Altair chart for Normalized (Percentage) Stacked Bar
st.subheader("Test Run Success Distribution (%)")
pct_chart = alt.Chart(df_jobs).mark_bar().encode(
    x=alt.X("run_name:N", title="Test Run Name", sort="-y"),
    y=alt.Y("count():Q",
            stack="normalize",
            axis=alt.Axis(format="%"),
            title="Percentage of Total Jobs"),
    color=alt.Color("status:N",
                    scale=alt.Scale(
                        domain=["pass", "fail", "running", "queued", "dead"],
                        range=["#28a745", "#dc3545", "#ffc107", "#6c757d", "#000000"]
                    ),
                    title="Status"),
    tooltip=["run_name", "status", "count()"]
).properties(
    height=400
)
st.altair_chart(pct_chart, width="stretch")

# Top 10 Common Failures
st.subheader("Top 10 Common Failure Reasons")
failure_col = "failure_template" if "failure_template" in df_jobs.columns else "failure_reason"
failures_df = df_jobs[
    (df_jobs["status"] == "fail")
    & df_jobs[failure_col].notna()
    & (df_jobs[failure_col] != "")
]
if not failures_df.empty:
    failure_counts = failures_df[failure_col].value_counts().nlargest(10).reset_index()
    failure_counts.columns = ["failure_reason", "count"]

    total_failures = failure_counts["count"].sum()
    failure_counts["percentage"] = (failure_counts["count"] / total_failures) * 100

    failure_counts.index = failure_counts.index + 1
    failure_counts.rename(
        columns={
            "failure_reason": "Failure Reason",
            "count": "Count",
            "percentage": "Percentage"
        },
        inplace=True
    )

    # Add Sr. No.
    failure_counts.insert(0, "Sr. No.", failure_counts.index)

    st.dataframe(
        failure_counts,
        column_config={
            "Percentage": st.column_config.NumberColumn(format="%.2f%%")
        },
        width="stretch",
        hide_index=True
    )
else:
    st.info("No failures with recorded reasons in this branch.")