import pandas as pd
import streamlit as st

from libs.config import get_pulpito_url
from libs.normalizer import get_runs_data

st.markdown(
    "<h1 style='text-align: center;'>Teuthology Test Runs</h1>",
    unsafe_allow_html=True
)

pulpito_base = get_pulpito_url()
failure_filter = st.query_params.get("failure_reason")
source_filter = st.query_params.get("source")

if failure_filter:
    st.info(f"Showing runs impacted by failure: **{failure_filter}**")
    if st.button("← Clear filter"):
        st.session_state.pop("drill_run_names", None)
        st.session_state.pop("drill_run_records", None)
        st.query_params.clear()
        st.rerun()

    drill_run_records = st.session_state.get("drill_run_records", [])
    if not drill_run_records:
        source_label = "builds" if source_filter == "builds" else "nightly"
        st.warning(f"No run data passed from the {source_label} page.")
        st.stop()

    df_runs = pd.DataFrame(drill_run_records)
    if df_runs.empty:
        st.info("No matching runs found.")
        st.stop()

    total = len(df_runs)
    col1, col2 = st.columns(2)
    col1.metric("Impacted Runs", total)
    unique_statuses = df_runs["status"].nunique() if "status" in df_runs.columns else 0
    col2.metric("Distinct Statuses", unique_statuses)

    st.divider()

    cols = ["name", "status", "user", "scheduled", "posted"]
    existing_cols = [
        c for c in cols if c in df_runs.columns
    ] + [
        c for c in df_runs.columns if c not in cols
    ]
    show_df = df_runs[existing_cols].reset_index(drop=True)

    col_config = {}
    if pulpito_base and "name" in show_df.columns:
        show_df["_run_link"] = show_df["name"].apply(
            lambda n: f"{pulpito_base}/{n}/"
        )
        col_config["name"] = st.column_config.LinkColumn(
            "name", display_text=r"/([^/]+)/?$"
        )
        show_df["name"] = show_df["_run_link"]
        show_df = show_df.drop(columns=["_run_link"])

    st.dataframe(show_df, width="stretch", hide_index=True, column_config=col_config)

else:
    st.markdown("Displaying the latest 100 runs reported to Paddles.")

    runs_data = get_runs_data()
    if not runs_data:
        st.info(
            "Please ensure your Paddles API URL is correct and "
            "the server is reachable."
        )
        st.stop()

    df_runs = pd.DataFrame(runs_data)
    if df_runs.empty:
        st.info("No runs found.")
        st.stop()

    cols = ["name", "status", "user", "scheduled", "posted"]
    existing_cols = [
        c for c in cols if c in df_runs.columns
    ] + [
        c for c in df_runs.columns if c not in cols
    ]
    show_df = df_runs[existing_cols].reset_index(drop=True)

    col_config = {}
    if pulpito_base and "name" in show_df.columns:
        show_df["_run_link"] = show_df["name"].apply(
            lambda n: f"{pulpito_base}/{n}/"
        )
        col_config["name"] = st.column_config.LinkColumn(
            "name", display_text=r"/([^/]+)/?$"
        )
        show_df["name"] = show_df["_run_link"]
        show_df = show_df.drop(columns=["_run_link"])

    st.dataframe(show_df, width="stretch", hide_index=True, column_config=col_config)
