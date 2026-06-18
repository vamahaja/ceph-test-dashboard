import streamlit as st

# Reports pages
dashboard = st.Page(
    "pages/reports/dashboard.py",
    title="Dashboard",
    icon=":material/dashboard:",
    default=True
)
jobs = st.Page(
    "pages/reports/jobs.py",
    title="Jobs",
    icon=":material/bug_report:"
)
testruns = st.Page(
    "pages/reports/testruns.py",
    title="Test Runs",
    icon=":material/play_arrow:"
)
reports = st.Page(
    "pages/reports/reports.py",
    title="Reports",
    icon=":material/play_arrow:"
)
alerts = st.Page(
    "pages/reports/alerts.py",
    title="Alerts",
    icon=":material/notification_important:"
)
release = st.Page(
    "pages/reports/release.py",
    title="Releases",
    icon=":material/new_releases:",
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

# Set navigations
pg = st.navigation(
    {
        "Reports": [dashboard, release, testruns, jobs, reports, alerts],
        "Tools": [search, history],
    }
)

# Start application
pg.run()
