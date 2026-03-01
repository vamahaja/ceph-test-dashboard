import pandas as pd
import streamlit as st

from datetime import datetime
from tests.mockdata import get_jobs_data, get_runs_data


# Set page configuration
st.set_page_config(layout="wide")

# Set page title and header
st.markdown(
    "<h1 style='text-align: center;'>Ceph Test Dashboard</h1>",
    unsafe_allow_html=True
)
st.header("Metrics for the Current Month")

# Get current month and year
now = datetime.now()
current_month = now.month
current_year = now.year

# Fetch runs and jobs data (TODO: Change to fetch data from api)
runs_data = get_runs_data()
jobs_data = get_jobs_data()
if not runs_data or not jobs_data:
    st.warning("Could not fetch data from the API.")
    st.stop()

# Convert to DataFrames
df_runs = pd.DataFrame(runs_data)
df_jobs = pd.DataFrame(jobs_data)

# Convert 'posted' column to datetime
df_runs["posted"] = pd.to_datetime(df_runs["posted"])
df_jobs["posted"] = pd.to_datetime(df_jobs["posted"])

# Filter for the current month
monthly_runs = df_runs[
    (df_runs["posted"].dt.year == current_year) &
    (df_runs["posted"].dt.month == current_month)
]
monthly_jobs = df_jobs[
    (df_jobs["posted"].dt.year == current_year) &
    (df_jobs["posted"].dt.month == current_month)
]

# Calculate metrics
total_runs, total_jobs = len(monthly_runs), len(monthly_jobs)
jobs_passed, jobs_failed, jobs_queued, job_running = 0, 0, 0, 0 
if not monthly_jobs.empty:
    jobs_passed = monthly_jobs["status"].eq("pass").sum()
    jobs_failed = monthly_jobs["status"].eq("fail").sum()
    jobs_queued = monthly_jobs["status"].eq("queued").sum()
    job_running = monthly_jobs["status"].eq("running").sum()

# Display metrics
col1, col2, col3, col4, col5, col6 = st.columns(6)
col1.metric("Total Test Runs", total_runs)
col2.metric("Total Jobs", total_jobs)
col3.metric("Jobs Running", job_running)
col4.metric("Jobs Queued", jobs_queued)
col5.metric("Jobs Passed", jobs_passed)
col6.metric("Jobs Failed", jobs_failed)

# Add page divider
st.divider()

# Display queued and running jobs
st.subheader("Queued and Running Jobs")
active_jobs = monthly_jobs[monthly_jobs["status"].isin(["queued", "running"])]
if active_jobs.empty:
    st.info("No jobs are currently queued or running for this month.")

# Reorder columns for better visibility in the dashboard
cols_to_show = ["job_id", "status", "name", "posted", "owner"]
display_cols = [c for c in cols_to_show if c in active_jobs.columns]
st.dataframe(active_jobs[display_cols], width="stretch")
