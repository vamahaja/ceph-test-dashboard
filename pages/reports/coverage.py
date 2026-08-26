"""Suite-first coverage, branch comparison, and flaky-test analysis."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

import pandas as pd
import plotly.express as px
import streamlit as st

from libs.defaults import (
    DEFAULT_FLAKY_MIN_EXECUTIONS,
    STATUS_COLOR_MAP,
    STATUS_FAILING,
)
from libs.pulpito import base_url, job_link_column, job_url, run_link_column, run_url
from libs.refresh import get_catalog, utc_day_start
from libs.reports.jobs import JobsStats
from libs.reports.models import Job
from libs.reports.testruns import TestRunsStats
from libs.reports.utils import as_utc
from libs.views import (
    query_str,
    sidebar_suite_select,
    sidebar_time_window,
    show_active_runs,
    show_cluster_health,
    show_daily_trends,
    show_pass_heatmap,
    show_scope_caption,
    show_status_filtered_runs,
    sync_query_params,
)

COVERAGE_RUN_COLUMNS = (
    "name",
    "status",
    "branch",
    "sha",
    "user",
    "machine_type",
    "total_jobs",
    "posted",
)


def _table_height(rows: int, *, cap: int = 800, min_rows: int = 1) -> int:
    return min(cap, 38 + max(rows, min_rows) * 35)


def _min_executions() -> int:
    key = "coverage_min_exec"
    if key not in st.session_state:
        raw = query_str("min_exec")
        try:
            value = int(raw)
        except ValueError:
            value = DEFAULT_FLAKY_MIN_EXECUTIONS
        st.session_state[key] = min(20, max(2, value))
    return int(
        st.sidebar.slider(
            "Min Executions (flaky filter)",
            min_value=2,
            max_value=20,
            key=key,
            help="Minimum times a test must run to be considered for flaky analysis",
        )
    )


def _pass_rate_styles(row: pd.Series) -> list[str]:
    rate = row.get("Pass Rate (%)", 100)
    if rate < 50:
        return ["background-color: rgba(220, 38, 38, 0.14)"] * len(row)
    if rate < 80:
        return ["background-color: rgba(217, 119, 6, 0.14)"] * len(row)
    return [""] * len(row)


def _failing_tests_branch_frame(jobs: JobsStats) -> pd.DataFrame:
    rows = jobs.failing_tests_by_branch()
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    pivot = frame.pivot_table(
        index="description",
        columns="branch",
        values="failed_jobs",
        aggfunc="sum",
        fill_value=0,
    )
    pivot["Total"] = pivot.sum(axis=1)
    return (
        pivot.sort_values("Total", ascending=False)
        .reset_index()
        .rename(columns={"description": "Test"})
    )


def _status_by_group(jobs: list[Job], group: str) -> pd.DataFrame:
    counts: dict[tuple[str, str], int] = defaultdict(int)
    for job in jobs:
        key = getattr(job, group, "") or "unknown"
        counts[(key, job.status or "unknown")] += 1
    return pd.DataFrame(
        [
            {group: key, "status": status, "count": count}
            for (key, status), count in counts.items()
        ]
    )


def _drill_to_jobs(run_names: list[str], reason: str, *, key: str) -> None:
    if st.button(f"View {len(run_names)} Impacted Jobs →", key=key):
        st.session_state["drill_run_names"] = run_names
        st.switch_page(
            "pages/dashboard/jobs.py",
            query_params={"failure_reason": reason, "source": "coverage"},
        )


def _drill_to_runs(
    runs: TestRunsStats, run_names: list[str], reason: str, *, key: str
) -> None:
    if st.button(f"View {len(run_names)} Impacted Runs →", key=key):
        st.session_state["drill_run_names"] = run_names
        st.session_state["drill_run_records"] = runs.records_for_names(run_names)
        st.switch_page(
            "pages/dashboard/testruns.py",
            query_params={"failure_reason": reason, "source": "coverage"},
        )


st.markdown(
    "<h1 style='text-align: center;'>Coverage &amp; Flaky Tests</h1>",
    unsafe_allow_html=True,
)
st.markdown(
    "Select a **suite** to compare coverage, failures, and flaky tests across branches."
)

st.sidebar.header("Filters")

time_window = sidebar_time_window(prefix="coverage")
start_date, end_date = time_window.start, time_window.end

catalog = get_catalog()
window_runs = TestRunsStats.from_testruns(catalog.runs).posted_since(
    utc_day_start(start_date)
)
loaded_at = catalog.loaded_at
if not window_runs.testruns:
    st.warning(f"No runs found in the selected window ({time_window.label}).")
    st.stop()

all_suites = sorted({run.suite for run in window_runs.testruns if run.suite})
if not all_suites:
    st.warning("No suites found in the selected window.")
    st.stop()

selected_suite = sidebar_suite_select(
    all_suites,
    prefix="coverage",
    help_text="Compare this suite across all branches that have runs for it.",
)
min_executions = _min_executions()

runs = window_runs.for_suite(selected_suite)
if not runs.testruns:
    st.warning(f"No runs found for suite **{selected_suite}**.")
    st.stop()

jobs = JobsStats.from_jobs(catalog.jobs).for_run_set(runs.testruns)

sync_query_params(
    {
        "suite": selected_suite,
        "window": time_window.query,
        "from": None,
        "to": None,
        "min_exec": str(min_executions),
    }
)

if not jobs.jobs:
    st.warning(f"No job data available for suite **{selected_suite}**.")
    st.stop()

now = datetime.now(timezone.utc)
pulpito = base_url()
health = runs.cluster_health(jobs, now=now)
window_label = f"{selected_suite} · {time_window.label}"
branches_in_scope = sorted({run.branch for run in runs.testruns if run.branch})

show_cluster_health(
    health,
    heading=f"Coverage health · {window_label}",
    show_branch_chip=True,
    show_worst_branch=True,
)
show_scope_caption(runs, jobs, loaded_at=loaded_at, now=now)
st.caption(
    f"Comparing **{len(runs.testruns)}** runs across **{len(branches_in_scope)}** "
    f"branches for suite **{selected_suite}**."
)

tab_compare, tab_fail, tab_cov, tab_flaky, tab_runs = st.tabs(
    [
        "Branch Comparison",
        "Failures",
        "Test Matrix Coverage",
        "Flaky Tests",
        "Runs",
    ]
)

completed = jobs.completed_stats

with tab_compare:
    st.subheader(f"Branch Comparison — {selected_suite}")
    st.caption("How this suite behaves on each branch.")

    run_counts = {row.branch: row.cnt_runs for row in runs.summary_by_branch}
    job_rows = {row.branch: row for row in completed.branch_summaries}
    branches = sorted(set(run_counts) | set(job_rows), key=lambda name: name.lower())
    compare_rows = []
    for branch in branches:
        stats = job_rows.get(branch)
        compare_rows.append(
            {
                "Branch": branch,
                "Runs": run_counts.get(branch, 0),
                "Jobs": stats.cnt_jobs if stats else 0,
                "Passed": stats.cnt_pass if stats else 0,
                "Failed": stats.cnt_fail if stats else 0,
                "Pass Rate (%)": stats.pct_pass if stats else 0.0,
                "Fail Rate (%)": stats.pct_fail if stats else 0.0,
            }
        )
    compare_frame = pd.DataFrame(compare_rows).sort_values(
        "Fail Rate (%)", ascending=False
    )
    st.dataframe(compare_frame, width="stretch", hide_index=True)

    st.divider()
    branch_status = _status_by_group(jobs.jobs, "branch")
    if branch_status.empty:
        st.info("No job status data for this suite.")
    else:
        fig_status = px.bar(
            branch_status,
            x="branch",
            y="count",
            color="status",
            color_discrete_map=STATUS_COLOR_MAP,
            barmode="stack",
            text_auto=True,
            title=f"Job Status by Branch — {selected_suite}",
            labels={"branch": "Branch", "count": "Jobs", "status": "Status"},
        )
        fig_status.update_layout(height=400, legend_title_text="Status")
        st.plotly_chart(fig_status, width="stretch")

        fig_pass = px.bar(
            compare_frame.sort_values("Pass Rate (%)", ascending=True),
            x="Pass Rate (%)",
            y="Branch",
            orientation="h",
            text_auto=True,
            title=f"Pass Rate by Branch — {selected_suite}",
            labels={"Branch": "Branch", "Pass Rate (%)": "Pass Rate (%)"},
            color_discrete_sequence=[STATUS_COLOR_MAP["pass"]],
        )
        fig_pass.update_layout(
            height=max(300, 40 * len(compare_frame)),
            xaxis_range=[0, 105],
        )
        st.plotly_chart(fig_pass, width="stretch")

with tab_fail:
    st.subheader("Daily trend")
    show_daily_trends(jobs)
    st.divider()
    st.subheader(f"Failures — {selected_suite}")
    st.caption("Which failures hit which branches for this suite.")

    failing = jobs.failing_jobs
    if not failing:
        st.info(f"No failing jobs for suite **{selected_suite}**.")
    else:
        reasons = jobs.top_failure_reasons(n=None)
        f1, f2, f3 = st.columns(3)
        f1.metric("Failed Jobs", len(failing))
        f2.metric("Unique Failure Reasons", len(reasons))
        f3.metric(
            "Branches Impacted",
            len({job.branch for job in failing if job.branch}),
        )

        st.divider()
        st.markdown("**Failure reasons**")
        fail_frame = pd.DataFrame(
            [
                {
                    "Failure Reason": row.reason,
                    "Jobs": row.count,
                    "Branches Impacted": row.branches_impacted,
                    "Runs": row.runs_impacted,
                    "Tests": row.tests_impacted,
                    "Share (%)": row.pct,
                }
                for row in reasons
            ]
        )
        fail_event = st.dataframe(
            fail_frame,
            width="stretch",
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            height=_table_height(len(fail_frame), cap=600),
            key="coverage_failure_reasons",
        )
        selected_fail_rows = fail_event.selection.rows if fail_event.selection else []
        if selected_fail_rows:
            reason = str(fail_frame.iloc[selected_fail_rows[0]]["Failure Reason"])
            matching = jobs.matching_failure(reason)
            run_names = list(
                dict.fromkeys(job.run_name for job in matching if job.run_name)
            )
            btn_jobs, btn_runs = st.columns(2)
            with btn_jobs:
                _drill_to_jobs(run_names, reason, key="coverage_view_jobs")
            with btn_runs:
                _drill_to_runs(runs, run_names, reason, key="coverage_view_runs")

            st.markdown(f"**Jobs with:** `{reason[:120]}`")
            detail = pd.DataFrame(
                [
                    {
                        "Branch": job.branch or "unknown",
                        "Test": job.description or "—",
                        "Job ID": job_url(job.run_name, job.job_id, base=pulpito),
                        "Run": run_url(job.run_name, base=pulpito),
                        "SHA": job.sha_short or "—",
                        "OS": job.os_type or "—",
                        "Machine": job.machine_type or "—",
                        "Status": job.status,
                        "Posted": job.posted,
                    }
                    for job in sorted(
                        matching,
                        key=lambda job: as_utc(job.posted)
                        or datetime.min.replace(tzinfo=timezone.utc),
                        reverse=True,
                    )
                ]
            )
            st.dataframe(
                detail,
                column_config={
                    **job_link_column("Job ID", "Job ID", base=pulpito),
                    **run_link_column("Run", "Run", base=pulpito),
                },
                width="stretch",
                hide_index=True,
                height=_table_height(len(detail), cap=500),
            )

        st.divider()
        st.markdown("**Failing Tests × Branch**")
        test_branch = _failing_tests_branch_frame(jobs)
        if test_branch.empty:
            st.info("No failing-test × branch data for this suite.")
        else:
            st.dataframe(
                test_branch,
                width="stretch",
                hide_index=True,
                height=_table_height(len(test_branch), cap=500),
            )

with tab_cov:
    st.subheader(f"Branch × Environment Heatmap — {selected_suite}")
    show_pass_heatmap(
        completed.pass_matrix(row="branch", col="os_type"),
        title=f"Pass rate by branch and OS — {selected_suite}",
    )

    st.divider()
    st.subheader("Environment Execution Breadth")
    env_jobs = [
        job
        for job in completed.jobs
        if job.os_type and job.os_type != "unknown"
    ]
    if not env_jobs:
        st.info("No OS type information available.")
    else:
        env_status = _status_by_group(env_jobs, "os_type")
        fig_env = px.bar(
            env_status,
            x="os_type",
            y="count",
            color="status",
            color_discrete_map=STATUS_COLOR_MAP,
            barmode="stack",
            text_auto=True,
            title=f"Job Volume & Health per OS — {selected_suite}",
            labels={"os_type": "OS Type", "count": "Jobs", "status": "Status"},
        )
        fig_env.update_layout(height=400, legend_title_text="Status")
        st.plotly_chart(fig_env, width="stretch")

    st.divider()
    st.subheader("Coverage Detail")
    detail_rows = [
        row
        for row in completed.coverage_detail
        if row.os_type and row.os_type != "unknown"
    ]
    if not detail_rows:
        st.info("No environment data to display.")
    else:
        cov_display = pd.DataFrame(
            [
                {
                    "Branch": row.branch,
                    "OS Type": row.os_type,
                    "Machine Type": row.machine_type,
                    "Total Jobs": row.cnt_jobs,
                    "Passed": row.cnt_pass,
                    "Failed": row.cnt_fail,
                    "Pass Rate (%)": row.pct_pass,
                }
                for row in detail_rows
            ]
        )
        st.dataframe(
            cov_display.style.apply(_pass_rate_styles, axis=1),
            width="stretch",
            height=_table_height(len(cov_display), cap=800),
            hide_index=True,
        )

with tab_flaky:
    analyzed = completed.flaky_tests(min_executions=min_executions)
    if not analyzed:
        st.warning(
            f"No tests have at least {min_executions} executions. "
            "Try lowering the **Min Executions** slider or choosing a longer time window."
        )
    else:
        flaky_tests = [row for row in analyzed if row.flakiness_score > 0]
        consistent_failures = sum(
            1
            for row in analyzed
            if row.passed == 0 and row.unique_failures <= 1 and row.failed > 0
        )
        most_flaky = flaky_tests[0].description if flaky_tests else "—"
        most_flaky_display = (
            most_flaky[:60] + "…" if len(most_flaky) > 60 else most_flaky
        )
        flakiness_rate = round(len(flaky_tests) / len(analyzed) * 100, 1)

        st.subheader(f"Flaky Test Summary — {selected_suite}")
        f1, f2, f3, f4, f5 = st.columns(5)
        f1.metric("Tests Analyzed", len(analyzed))
        f2.metric("Flaky Tests", len(flaky_tests))
        f3.metric("Consistent Bugs", consistent_failures)
        f4.metric("Flakiness Rate", f"{flakiness_rate}%")
        f5.metric("Most Flaky", most_flaky_display)

        st.divider()
        if not flaky_tests:
            st.info(
                "No flaky tests detected. Tests either pass consistently or "
                "always fail with the same failure reason (consistent bugs)."
            )
        else:
            st.subheader(f"Flaky Tests ({len(flaky_tests)})")
            ranked = pd.DataFrame(
                [
                    {
                        "Test": row.description,
                        "Flakiness (%)": row.flakiness_score,
                        "Total Runs": row.total_runs,
                        "Passed": row.passed,
                        "Failed": row.failed,
                        "Unique Failures": row.unique_failures,
                        "Branches Affected": row.branches_affected,
                        "Same-SHA Flaky": row.same_sha_flaky,
                        "Total SHAs": row.total_shas,
                    }
                    for row in flaky_tests
                ]
            )
            event = st.dataframe(
                ranked,
                width="stretch",
                hide_index=True,
                on_select="rerun",
                selection_mode="single-row",
                height=_table_height(len(ranked), cap=600),
                key="coverage_flaky_tests",
            )
            selected_rows = event.selection.rows if event.selection else []
            if selected_rows:
                selected_test = str(ranked.iloc[selected_rows[0]]["Test"])
                test_jobs = [
                    job
                    for job in completed.jobs
                    if job.description == selected_test
                ]
                test_jobs.sort(
                    key=lambda job: as_utc(job.posted)
                    or datetime.min.replace(tzinfo=timezone.utc)
                )

                st.divider()
                st.subheader(f"Detail: {selected_test[:80]}")
                timeline_df = pd.DataFrame(
                    [
                        {
                            "posted": job.posted,
                            "status": job.status,
                            "duration_min": round(max((job.duration or 0) / 60, 0.1), 1),
                            "sha_short": job.sha_short or "unknown",
                            "branch": job.branch or "unknown",
                            "os_type": job.os_type or "—",
                            "failure_reason": job.failure_reason or "",
                        }
                        for job in test_jobs
                    ]
                )
                fig_timeline = px.scatter(
                    timeline_df,
                    x="posted",
                    y="status",
                    color="branch",
                    size="duration_min",
                    hover_data=[
                        "sha_short",
                        "os_type",
                        "duration_min",
                        "failure_reason",
                    ],
                    title="Pass/Fail Timeline (colored by branch)",
                    labels={
                        "posted": "Time",
                        "status": "Status",
                        "duration_min": "Duration (min)",
                        "sha_short": "SHA",
                        "failure_reason": "Failure",
                        "branch": "Branch",
                    },
                )
                fig_timeline.update_layout(height=350)
                fig_timeline.update_yaxes(
                    categoryorder="array",
                    categoryarray=["pass", "fail", "dead"],
                )
                st.plotly_chart(fig_timeline, width="stretch")

                col_branch, col_env = st.columns(2)
                with col_branch:
                    st.markdown("**Per-Branch Breakdown**")
                    by_branch: dict[str, list[Job]] = defaultdict(list)
                    for job in test_jobs:
                        by_branch[job.branch or "unknown"].append(job)
                    st.dataframe(
                        pd.DataFrame(
                            [
                                {
                                    "Branch": branch,
                                    "Passed": sum(
                                        1 for job in group if job.status == "pass"
                                    ),
                                    "Failed": sum(
                                        1
                                        for job in group
                                        if job.status in STATUS_FAILING
                                    ),
                                    "Total": len(group),
                                    "Flaky?": (
                                        "Yes"
                                        if (
                                            any(job.status == "pass" for job in group)
                                            and any(
                                                job.status in STATUS_FAILING
                                                for job in group
                                            )
                                        )
                                        else "No"
                                    ),
                                }
                                for branch, group in sorted(by_branch.items())
                            ]
                        ),
                        width="stretch",
                        hide_index=True,
                    )

                with col_env:
                    st.markdown("**Environment Breakdown**")
                    by_env: dict[tuple[str, str], list[Job]] = defaultdict(list)
                    for job in test_jobs:
                        by_env[
                            (job.os_type or "unknown", job.machine_type or "unknown")
                        ].append(job)
                    st.dataframe(
                        pd.DataFrame(
                            [
                                {
                                    "OS Type": os_type,
                                    "Machine Type": machine,
                                    "Passed": sum(
                                        1 for job in group if job.status == "pass"
                                    ),
                                    "Failed": sum(
                                        1
                                        for job in group
                                        if job.status in STATUS_FAILING
                                    ),
                                    "Total": len(group),
                                    "Flaky?": (
                                        "Yes"
                                        if (
                                            any(job.status == "pass" for job in group)
                                            and any(
                                                job.status in STATUS_FAILING
                                                for job in group
                                            )
                                        )
                                        else "No"
                                    ),
                                }
                                for (os_type, machine), group in sorted(by_env.items())
                            ]
                        ),
                        width="stretch",
                        hide_index=True,
                    )

                test_failures = [
                    job
                    for job in test_jobs
                    if job.status in STATUS_FAILING and job.failure_reason
                ]
                if test_failures:
                    st.markdown("**Failure Reasons**")
                    reason_counts: dict[str, int] = defaultdict(int)
                    for job in test_failures:
                        reason_counts[job.failure_reason] += 1
                    st.dataframe(
                        pd.DataFrame(
                            [
                                {
                                    "Failure Reason": reason,
                                    "Occurrences": count,
                                }
                                for reason, count in sorted(
                                    reason_counts.items(),
                                    key=lambda item: item[1],
                                    reverse=True,
                                )
                            ]
                        ),
                        width="stretch",
                        hide_index=True,
                    )

            st.divider()
            st.subheader(f"Flaky Tests by Branch — {selected_suite}")
            flaky_descs = {row.description for row in flaky_tests}
            flaky_by_branch: dict[str, set[str]] = defaultdict(set)
            for job in completed.jobs:
                if job.description in flaky_descs:
                    flaky_by_branch[job.branch or "unknown"].add(job.description)
            flaky_branch = pd.DataFrame(
                [
                    {"branch": branch, "flaky_tests": len(tests)}
                    for branch, tests in flaky_by_branch.items()
                ]
            ).sort_values("flaky_tests", ascending=False)
            fig_branch = px.bar(
                flaky_branch,
                x="branch",
                y="flaky_tests",
                text_auto=True,
                title=f"Flaky Test Count by Branch — {selected_suite}",
                labels={"branch": "Branch", "flaky_tests": "Flaky Tests"},
                color_discrete_sequence=[STATUS_COLOR_MAP["fail"]],
            )
            fig_branch.update_layout(height=400)
            st.plotly_chart(fig_branch, width="stretch")

with tab_runs:
    st.subheader("Active runs")
    show_active_runs(runs, pulpito, now=now, collapse_table=True)
    st.divider()
    ordered = sorted(
        runs.testruns,
        key=lambda run: as_utc(run.posted)
        or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    show_status_filtered_runs(
        ordered,
        pulpito,
        prefix="coverage",
        columns=COVERAGE_RUN_COLUMNS,
        heading="Runs",
    )
