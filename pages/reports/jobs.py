import pandas as pd
import streamlit as st

from tests.mockdata import get_jobs_data, get_runs_data

# Set page title
st.markdown(
    "<h1 style='text-align: center;'>Job Details</h1>",
    unsafe_allow_html=True
)

# Get runs data to find the latest run (TODO: Change to fetch data from api)
runs_data = get_runs_data()
df_runs = pd.DataFrame(runs_data)
df_runs["posted"] = pd.to_datetime(df_runs["posted"])
run_names = df_runs["name"].tolist()

# Get test run to show jobs
selected_run = st.selectbox("Select a run to view its jobs:", run_names)

# Get jobs data (TODO: Change to fetch data from api)
jobs_data = get_jobs_data(selected_run)
if not jobs_data:
    st.info(f"No jobs exist for run `{selected_run}`.")
    st.stop()

# Convert to DataFrame
df_jobs = pd.DataFrame(jobs_data)
if df_jobs.empty:
    st.info(f"No jobs exist for run `{selected_run}`.")

# Calculate simple metrics
total_jobs = len(df_jobs)
has_success = "success" in df_jobs.columns
pass_count = (
    df_jobs["success"].eq(True).sum() if has_success else 0
)
fail_count = (
    df_jobs["success"].eq(False).sum() if has_success else 0
)
queued_count = df_jobs["status"].eq("queued").sum()
running_count = df_jobs["status"].eq("running").sum()

# Display metrics
col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Total Jobs", total_jobs)
col2.metric("Passed", pass_count)
col3.metric("Failed", fail_count)
col4.metric("Queued", queued_count)
col5.metric("Running", running_count)

# Add page divider
st.divider()

# Filter for the most important metadata keys based on the schema
job_cols = [
    "job_id", "success", "status", "description", "machine_type",
    "os_type", "duration", "owner"
]
display_cols = [
    c for c in job_cols if c in df_jobs.columns
] + [
    c for c in df_jobs.columns if c not in job_cols
]

# Display the jobs
st.dataframe(df_jobs[display_cols], width="stretch")
