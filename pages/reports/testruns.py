import pandas as pd
import streamlit as st

from libs.normalizer import get_runs_data


# Set page title and markdown
st.markdown(
    "<h1 style='text-align: center;'>Teuthology Test Runs</h1>",
    unsafe_allow_html=True
)
st.markdown("Displaying the latest 100 runs reported to Paddles.")

runs_data = get_runs_data()
if not runs_data:
    st.info(
        "Please ensure your Paddles API URL is correct and "
        "the server is reachable."
    )

# Convert to DataFrame
df_runs = pd.DataFrame(runs_data)
if df_runs.empty:
    st.info("No runs found.")

# Reorder columns for readability
cols = ["name", "status", "user", "scheduled", "posted"]
existing_cols = [
    c for c in cols if c in df_runs.columns
] + [
    c for c in df_runs.columns if c not in cols
]
df_runs = df_runs[existing_cols]

# Display the runs
st.dataframe(df_runs, width="stretch")
