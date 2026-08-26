"""Teuthology test runs — latest runs and failure-reason drill-in."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from libs.config import get_refresh_seconds
from libs.defaults import DEFAULT_REPORT_COUNT, status_row_styles
from libs.exceptions import ConfigError, PaddlesAPIError
from libs.pulpito import base_url, run_link_column, run_url
from libs.reports.models import TestRun
from libs.reports.testruns import TestRunsStats
from libs.reports.utils import format_age

RUN_COLUMNS = (
    "name",
    "status",
    "branch",
    "suite",
    "machine_type",
    "user",
    "pass",
    "fail",
    "dead",
    "total_jobs",
    "age",
    "scheduled",
    "posted",
)


def _query_str(key: str) -> str:
    value = st.query_params.get(key)
    if isinstance(value, list):
        return str(value[0] or "")
    return str(value or "")


@st.cache_data(ttl=get_refresh_seconds(), show_spinner=False)
def _load_latest_runs() -> TestRunsStats:
    return TestRunsStats(count=DEFAULT_REPORT_COUNT)


def _runs_frame(
    runs: list[TestRun],
    pulpito: str | None,
    *,
    now: datetime,
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "name": run_url(run.name, base=pulpito),
                "status": run.status,
                "branch": run.branch,
                "suite": run.suite,
                "machine_type": run.machine_type,
                "user": run.user,
                "pass": run.results.pass_,
                "fail": run.results.fail,
                "dead": run.results.dead,
                "total_jobs": run.total_jobs,
                "age": format_age(run.posted, now),
                "scheduled": run.scheduled,
                "posted": run.posted,
            }
            for run in runs
        ],
        columns=list(RUN_COLUMNS),
    )


def _show_runs_table(
    runs: list[TestRun],
    pulpito: str | None,
    *,
    now: datetime,
) -> None:
    table = _runs_frame(runs, pulpito, now=now)
    st.dataframe(
        table.style.apply(status_row_styles, axis=1),
        column_config=run_link_column("name", "Run", base=pulpito),
        width="stretch",
        hide_index=True,
        height=min(800, 38 + max(len(table), 1) * 35),
    )


def _show_runs_scorecard(stats: TestRunsStats) -> None:
    summary = stats.summary
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Testruns", summary.cnt_testruns)
    c2.metric("Completed", len(stats.completed_testruns))
    c3.metric("Active", len(stats.active_testruns))
    c4.metric("Jobs", summary.cnt_jobs)
    c5.metric("Failed jobs", summary.cnt_fail)
    c6.metric("Dead jobs", summary.cnt_dead)


def _clear_failure_drill() -> None:
    """Drop failure drill-in state used by Overview / Releases / Nightly / Builds."""
    st.session_state.pop("drill_run_names", None)
    st.session_state.pop("drill_run_records", None)
    st.query_params.clear()
    st.rerun()


st.markdown(
    "<h1 style='text-align: center;'>Teuthology Test Runs</h1>",
    unsafe_allow_html=True,
)

pulpito = base_url()
now = datetime.now(timezone.utc)
failure_filter = _query_str("failure_reason")
source_filter = _query_str("source")
run_filter = _query_str("run")

# Failure-reason drill-in from Overview / Releases / Nightly / Builds. Keep this
# contract unchanged: query ``failure_reason`` + ``source``, session
# ``drill_run_records``, then ``TestRunsStats.from_records``.
if failure_filter:
    st.info(f"Showing runs impacted by failure: **{failure_filter}**")
    if source_filter:
        st.caption(f"Opened from **{source_filter}**.")
    if st.button("← Clear filter", key="testruns_clear_failure"):
        _clear_failure_drill()

    drill_run_records = st.session_state.get("drill_run_records", [])
    if not drill_run_records:
        source_label = source_filter or "report"
        st.warning(f"No run data passed from the {source_label} page.")
        st.stop()

    stats = TestRunsStats.from_records(drill_run_records)
    if not stats.testruns:
        st.info("No matching runs found.")
        st.stop()

    _show_runs_scorecard(stats)
    statuses = sorted({run.status for run in stats.testruns if run.status})
    st.caption(
        f"{stats.distinct_status_count} distinct statuses"
        + (f" ({', '.join(statuses)})" if statuses else "")
        + "."
    )

    drill_run_names = st.session_state.get("drill_run_names") or stats.testrun_names
    if drill_run_names:
        if st.button("View matching jobs →", key="testruns_to_jobs"):
            st.session_state["drill_run_names"] = list(drill_run_names)
            st.switch_page(
                "pages/dashboard/jobs.py",
                query_params={
                    "failure_reason": failure_filter,
                    "source": source_filter or "testruns",
                },
            )

    st.divider()
    _show_runs_table(stats.testruns, pulpito, now=now)

elif run_filter:
    st.info(f"Showing testrun `{run_filter}`")
    if source_filter:
        st.caption(f"Opened from **{source_filter}**.")
    if st.button("← Latest runs", key="testruns_clear_run"):
        st.query_params.clear()
        st.rerun()

    try:
        stats = TestRunsStats(testrun_name=run_filter)
    except (PaddlesAPIError, ConfigError) as exc:
        st.warning(f"Could not load run `{run_filter}`: {exc}")
        st.stop()

    if not stats.testruns:
        st.info(f"No testrun named `{run_filter}` was found.")
        st.stop()

    _show_runs_scorecard(stats)
    if st.button("View jobs for this run →", key="testruns_run_to_jobs"):
        st.switch_page(
            "pages/dashboard/jobs.py",
            query_params={
                "run": run_filter,
                "source": source_filter or "testruns",
            },
        )
    st.divider()
    _show_runs_table(stats.testruns, pulpito, now=now)

else:
    st.caption(
        f"Latest **{DEFAULT_REPORT_COUNT}** runs reported to Paddles."
    )

    try:
        stats = _load_latest_runs()
    except (PaddlesAPIError, ConfigError) as exc:
        st.warning(f"Could not load run data: {exc}")
        st.stop()

    if not stats.testruns:
        st.info(
            "Please ensure your Paddles API URL is correct and "
            "the server is reachable."
        )
        st.stop()

    _show_runs_scorecard(stats)
    names = [run.name for run in stats.testruns if run.name]
    selected = st.selectbox(
        "Open jobs for a run:",
        ["—"] + names,
        key="testruns_open_jobs",
    )
    if selected != "—" and st.button("View jobs →", key="testruns_latest_to_jobs"):
        st.switch_page(
            "pages/dashboard/jobs.py",
            query_params={"run": selected, "source": "testruns"},
        )

    st.divider()
    _show_runs_table(stats.testruns, pulpito, now=now)
