import pandas as pd
import streamlit as st

from libs.config import get_pulpito_url
from libs.normalizer import get_jobs_data, get_runs_data

st.markdown(
    "<h1 style='text-align: center;'>Job Details</h1>",
    unsafe_allow_html=True
)

pulpito_base = get_pulpito_url()
failure_filter = st.query_params.get("failure_reason")
source_filter = st.query_params.get("source")

if failure_filter:
    st.info(f"Showing jobs with failure: **{failure_filter}**")
    if st.button("← Clear filter"):
        st.session_state.pop("drill_run_names", None)
        st.query_params.clear()
        st.rerun()

    drill_run_names = st.session_state.get("drill_run_names", [])
    if not drill_run_names:
        st.warning("No run names passed from the nightly page.")
        st.stop()

    all_jobs = []
    for rn in drill_run_names:
        all_jobs.extend(get_jobs_data(run_name=rn))

    if not all_jobs:
        st.info("No jobs found for the impacted runs.")
        st.stop()

    df_jobs = pd.DataFrame(all_jobs)
    df_jobs = df_jobs[df_jobs["status"].isin(["fail", "dead"])]
    reason_col = "failure_template" if "failure_template" in df_jobs.columns else "failure_reason"
    df_jobs[reason_col] = df_jobs[reason_col].fillna("Unknown failure").replace("", "Unknown failure")
    df_jobs = df_jobs[df_jobs[reason_col] == failure_filter]

    if df_jobs.empty:
        st.info("No jobs match the selected failure reason.")
        st.stop()

    total = len(df_jobs)
    col1, _ = st.columns(2)
    col1.metric("Matching Failed Jobs", total)

    st.divider()

    display_cols = [
        c for c in ["job_id", "run_name", "status", "description", "machine_type",
                     "os_type", "duration", reason_col] if c in df_jobs.columns
    ]
    show_df = df_jobs[display_cols].reset_index(drop=True)

    col_config = {}
    if pulpito_base and "job_id" in show_df.columns and "run_name" in show_df.columns:
        show_df["job_id"] = show_df["job_id"].astype(str)
        show_df["_job_link"] = show_df.apply(
            lambda r: f"{pulpito_base}/{r['run_name']}/{r['job_id']}", axis=1
        )
        col_config["job_id"] = st.column_config.LinkColumn(
            "job_id", display_text=r"(\d+)$"
        )
        show_df["job_id"] = show_df["_job_link"]
        show_df = show_df.drop(columns=["_job_link"])

        show_df["_run_link"] = show_df["run_name"].apply(
            lambda n: f"{pulpito_base}/{n}/"
        )
        col_config["run_name"] = st.column_config.LinkColumn(
            "run_name", display_text=r"/([^/]+)/?$"
        )
        show_df["run_name"] = show_df["_run_link"]
        show_df = show_df.drop(columns=["_run_link"])

    st.dataframe(show_df, width="stretch", hide_index=True, column_config=col_config)

else:
    runs_data = get_runs_data()
    df_runs = pd.DataFrame(runs_data)
    df_runs["posted"] = pd.to_datetime(df_runs["posted"])
    run_names = df_runs["name"].tolist()

    selected_run = st.selectbox("Select a run to view its jobs:", run_names)

    jobs_data = get_jobs_data(run_name=selected_run)
    if not jobs_data:
        st.info(f"No jobs exist for run `{selected_run}`.")
        st.stop()

    df_jobs = pd.DataFrame(jobs_data)
    if df_jobs.empty:
        st.info(f"No jobs exist for run `{selected_run}`.")
        st.stop()

    total_jobs = len(df_jobs)
    has_success = "success" in df_jobs.columns
    pass_count = df_jobs["success"].eq(True).sum() if has_success else 0
    fail_count = df_jobs["success"].eq(False).sum() if has_success else 0
    queued_count = df_jobs["status"].eq("queued").sum()
    running_count = df_jobs["status"].eq("running").sum()

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Total Jobs", total_jobs)
    col2.metric("Passed", pass_count)
    col3.metric("Failed", fail_count)
    col4.metric("Queued", queued_count)
    col5.metric("Running", running_count)

    st.divider()

    job_cols = [
        "job_id", "success", "status", "description", "machine_type",
        "os_type", "duration", "owner"
    ]
    display_cols = [
        c for c in job_cols if c in df_jobs.columns
    ] + [
        c for c in df_jobs.columns if c not in job_cols
    ]

    show_df = df_jobs[display_cols].reset_index(drop=True)

    col_config = {}
    if pulpito_base and "job_id" in show_df.columns:
        show_df["job_id"] = show_df["job_id"].astype(str)
        show_df["_job_link"] = show_df["job_id"].apply(
            lambda jid: f"{pulpito_base}/{selected_run}/{jid}"
        )
        col_config["job_id"] = st.column_config.LinkColumn(
            "job_id", display_text=r"(\d+)$"
        )
        show_df["job_id"] = show_df["_job_link"]
        show_df = show_df.drop(columns=["_job_link"])

    st.dataframe(show_df, width="stretch", hide_index=True, column_config=col_config)
