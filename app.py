import time

import streamlit as st

from libs.refresh import (
    catalog_error,
    catalog_is_ready,
    catalog_progress,
    start_catalog,
)
from libs.views import show_data_status


st.set_page_config(
    page_title="Ceph Test Dashboard",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Dashboard pages
overview = st.Page(
    "pages/dashboard/overview.py",
    title="Overview",
    icon=":material/dashboard:",
    default=True
)
jobs = st.Page(
    "pages/dashboard/jobs.py",
    title="Jobs",
    icon=":material/bug_report:"
)
testruns = st.Page(
    "pages/dashboard/testruns.py",
    title="Test Runs",
    icon=":material/play_arrow:"
)

# Reports pages
release = st.Page(
    "pages/reports/release.py",
    title="Releases",
    icon=":material/new_releases:",
)
nightly = st.Page(
    "pages/reports/nightly.py",
    title="Nightly",
    icon=":material/nightlight:",
)
builds = st.Page(
    "pages/reports/builds.py",
    title="Builds",
    icon=":material/build:",
)
coverage = st.Page(
    "pages/reports/coverage.py",
    title="Coverage",
    icon=":material/labs:",
)
hardware = st.Page(
    "pages/reports/hardware.py",
    title="Hardware",
    icon=":material/memory:",
)

# Tools pages
search = st.Page(
    "pages/tools/search.py",
    title="Search",
    icon=":material/search:"
)
history = st.Page(
    "pages/tools/history.py",
    title="History",
    icon=":material/history:"
)
alerts = st.Page(
    "pages/tools/alerts.py",
    title="Alerts",
    icon=":material/notification_important:"
)

# Set navigations
pg = st.navigation(
    {
        "Dashboard": [overview, testruns, jobs],
        "Reports": [release, nightly, builds, coverage, hardware],
        "Tools": [search, history, alerts],
    }
)

start_catalog()
if not catalog_is_ready():
    st.markdown(
        "<h1 style='text-align: center;'>Initialization</h1>",
        unsafe_allow_html=True,
    )
    st.info(
        "Loading the last 30 days of test data. "
        "The dashboard will start when this completes."
    )
    current, steps = catalog_progress()
    with st.status(current or "Starting initialization…", expanded=True) as status:
        for step in steps:
            st.write(step)
        if current and (not steps or steps[-1] != current):
            st.write(current)
        err = catalog_error()
        if err:
            status.update(label="Retrying after error", state="error")
            st.warning(err)
    time.sleep(1)
    st.rerun()

show_data_status()

# Start application
pg.run()
