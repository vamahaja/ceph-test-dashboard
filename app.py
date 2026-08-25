import streamlit as st


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

# Start application
pg.run()
