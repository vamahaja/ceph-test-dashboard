import concurrent.futures
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from libs.normalizer import get_jobs_data, get_runs_data

_MAX_RUNS = 50       # hard cap: prevents N+1 page freeze on large suites
_FETCH_WORKERS = 8   # parallel threads for job fetching

st.markdown(
    "<h1 style='text-align: center;'>Coverage &amp; Flaky Tests</h1>",
    unsafe_allow_html=True,
)
st.markdown(
    "Select a **suite** to compare coverage, failures, and flaky tests across branches."
)

# ── sidebar filters ──────────────────────────────────────────────────
st.sidebar.header("Filters")

runs_data = get_runs_data(count=200)
if not runs_data:
    st.warning("Could not fetch run data from the API.")
    st.stop()

df_runs = pd.DataFrame(runs_data)
df_runs["posted"] = pd.to_datetime(df_runs["posted"], errors="coerce")
df_runs.drop_duplicates(subset=["name"], inplace=True)

completed_statuses = {"pass", "fail", "dead"}
completed_runs = df_runs[df_runs["status"].isin(completed_statuses)].copy()
if completed_runs.empty:
    st.warning("No completed runs found.")
    st.stop()

all_suites = sorted(
    s for s in completed_runs["suite"].dropna().unique().tolist() if s
)
if not all_suites:
    st.warning("No suites found in recent completed runs.")
    st.stop()

selected_suite = st.sidebar.selectbox(
    "Suite",
    all_suites,
    help="Compare this suite across all branches that have runs for it.",
)

min_executions = st.sidebar.slider(
    "Min Executions (flaky filter)",
    min_value=2,
    max_value=20,
    value=3,
    help="Minimum times a test must run to be considered for flaky analysis",
)

suite_runs = completed_runs[completed_runs["suite"] == selected_suite].copy()
if suite_runs.empty:
    st.warning(f"No completed runs found for suite **{selected_suite}**.")
    st.stop()

suite_runs = suite_runs.sort_values("posted", ascending=False)
total_suite_runs = len(suite_runs)
filt_runs = suite_runs.head(_MAX_RUNS).copy()
branches_in_scope = sorted(
    b for b in filt_runs["branch"].dropna().unique().tolist() if b
)
scope_label = selected_suite

st.info(
    f"Comparing **{len(filt_runs)}** runs across **{len(branches_in_scope)}** "
    f"branches for suite **{scope_label}**"
    + (
        f" (most recent of {total_suite_runs} available)."
        if total_suite_runs > _MAX_RUNS
        else "."
    )
)

# ── load jobs (parallelised — @st.cache_data is thread-safe for reads) ──
run_info = filt_runs.set_index("name")[["branch", "suite", "sha_id"]].to_dict("index")
run_names = filt_runs["name"].unique().tolist()


def _fetch_run_jobs(run_name: str) -> list[dict]:
    """Fetch and enrich jobs for a single run. Called from a thread pool."""
    run_jobs = get_jobs_data(run_name=run_name)
    if not run_jobs:
        return []
    info = run_info.get(run_name, {})
    enriched = []
    for job in run_jobs:
        if not job.get("branch"):
            job["branch"] = info.get("branch", "")
        if not job.get("suite"):
            job["suite"] = info.get("suite", "")
        if not job.get("sha_id"):
            job["sha_id"] = info.get("sha_id", "")
        enriched.append(job)
    return enriched


all_jobs: list[dict] = []
progress_bar = st.progress(0, text="Loading job data…")
with concurrent.futures.ThreadPoolExecutor(max_workers=_FETCH_WORKERS) as pool:
    futures = {pool.submit(_fetch_run_jobs, rn): rn for rn in run_names}
    for i, future in enumerate(concurrent.futures.as_completed(futures)):
        progress_bar.progress(
            int((i + 1) / len(run_names) * 100),
            text=f"Loading jobs… {i + 1} of {len(run_names)} runs",
        )
        all_jobs.extend(future.result())
progress_bar.empty()

if not all_jobs:
    st.warning("No job data available for the selected runs.")
    st.stop()

df_jobs = pd.DataFrame(all_jobs)
df_jobs["posted"] = pd.to_datetime(df_jobs["posted"], errors="coerce")
df_jobs["branch"] = df_jobs["branch"].fillna("unknown").replace("", "unknown")

filt_jobs = df_jobs[df_jobs["suite"] == selected_suite].copy()
if filt_jobs.empty:
    st.warning(f"No job data for suite **{scope_label}**.")
    st.stop()

# ── constants ─────────────────────────────────────────────────────────
color_map = {
    "pass": "#54b399",
    "fail": "#d36086",
    "dead": "#aa6556",
    "running": "#6092c0",
    "queued": "#d6bf57",
    "unknown": "#9170b8",
}

# ── shared KPI row ────────────────────────────────────────────────────
total_runs = len(filt_runs)
total_jobs = len(filt_jobs)
failed_jobs = int(filt_jobs["status"].isin(["fail", "dead"]).sum())
fail_rate = round(failed_jobs / total_jobs * 100, 1) if total_jobs else 0.0
branches_compared = filt_jobs["branch"].nunique()

st.subheader(f"{scope_label} — Overview")
k1, k2, k3, k4 = st.columns(4)
k1.metric("Total Runs", total_runs)
k2.metric("Total Jobs", total_jobs)
k3.metric("Branches Compared", branches_compared)
k4.metric("Overall Fail Rate", f"{fail_rate}%")

# ── tabs ──────────────────────────────────────────────────────────────
tab_compare, tab_fail, tab_cov, tab_flaky = st.tabs(
    ["Branch Comparison", "Failures", "Test Matrix Coverage", "Flaky Tests"]
)

# =====================================================================
#  TAB 1 — BRANCH COMPARISON
# =====================================================================
with tab_compare:
    st.subheader(f"Branch Comparison — {scope_label}")
    st.caption("How this suite behaves on each branch.")

    run_counts = (
        filt_runs.groupby("branch")["name"]
        .nunique()
        .reset_index(name="runs")
    )
    job_stats = filt_jobs.groupby("branch").agg(
        jobs=("job_id", "count"),
        passed=("status", lambda s: (s == "pass").sum()),
        failed=("status", lambda s: s.isin(["fail", "dead"]).sum()),
    ).reset_index()
    branch_metrics = run_counts.merge(job_stats, on="branch", how="outer").fillna(0)
    for col in ("runs", "jobs", "passed", "failed"):
        branch_metrics[col] = branch_metrics[col].astype(int)
    branch_metrics["pass_rate"] = branch_metrics.apply(
        lambda r: round(r["passed"] / r["jobs"] * 100, 1) if r["jobs"] else 0.0,
        axis=1,
    )
    branch_metrics["fail_rate"] = branch_metrics.apply(
        lambda r: round(r["failed"] / r["jobs"] * 100, 1) if r["jobs"] else 0.0,
        axis=1,
    )
    branch_metrics = branch_metrics.sort_values("fail_rate", ascending=False)

    st.dataframe(
        branch_metrics.rename(columns={
            "branch": "Branch",
            "runs": "Runs",
            "jobs": "Jobs",
            "passed": "Passed",
            "failed": "Failed",
            "pass_rate": "Pass Rate (%)",
            "fail_rate": "Fail Rate (%)",
        }),
        width="stretch",
        hide_index=True,
    )

    st.divider()
    branch_status = (
        filt_jobs.groupby(["branch", "status"])
        .size()
        .reset_index(name="count")
    )
    fig_status = px.bar(
        branch_status,
        x="branch",
        y="count",
        color="status",
        color_discrete_map=color_map,
        barmode="stack",
        text_auto=True,
        title=f"Job Status by Branch — {scope_label}",
        labels={"branch": "Branch", "count": "Jobs", "status": "Status"},
    )
    fig_status.update_layout(height=400, legend_title_text="Status")
    st.plotly_chart(fig_status, width="stretch")

    fig_pass = px.bar(
        branch_metrics.sort_values("pass_rate", ascending=True),
        x="pass_rate",
        y="branch",
        orientation="h",
        text_auto=True,
        title=f"Pass Rate by Branch — {scope_label}",
        labels={"branch": "Branch", "pass_rate": "Pass Rate (%)"},
        color_discrete_sequence=["#54b399"],
    )
    fig_pass.update_layout(height=max(300, 40 * len(branch_metrics)), xaxis_range=[0, 105])
    st.plotly_chart(fig_pass, width="stretch")

# =====================================================================
#  TAB 2 — FAILURES
# =====================================================================
with tab_fail:
    st.subheader(f"Failures — {scope_label}")
    st.caption("Which failures hit which branches for this suite.")

    failing_jobs = filt_jobs[filt_jobs["status"].isin(["fail", "dead"])].copy()
    if failing_jobs.empty:
        st.info(f"No failing jobs for suite **{scope_label}**.")
    else:
        failing_jobs["failure_reason"] = (
            failing_jobs["failure_template"]
            .fillna("Unknown failure")
            .replace("", "Unknown failure")
        )

        f1, f2, f3 = st.columns(3)
        f1.metric("Failed Jobs", len(failing_jobs))
        f2.metric("Unique Failure Reasons", failing_jobs["failure_reason"].nunique())
        f3.metric("Branches Impacted", failing_jobs["branch"].nunique())

        st.divider()
        st.markdown("**Top Failure Reasons**")

        failure_summary = failing_jobs.groupby("failure_reason").agg(
            jobs_impacted=("job_id", "count"),
            branches_impacted=("branch", "nunique"),
            runs_impacted=("run_name", "nunique"),
            tests_impacted=("description", "nunique"),
        ).reset_index()
        failure_summary["share"] = (
            failure_summary["jobs_impacted"]
            / failure_summary["jobs_impacted"].sum()
            * 100
        ).round(1)
        failure_summary = failure_summary.sort_values(
            ["jobs_impacted", "branches_impacted", "failure_reason"],
            ascending=[False, False, True],
        )

        display_failures = failure_summary.rename(columns={
            "failure_reason": "Failure Reason",
            "jobs_impacted": "Jobs",
            "branches_impacted": "Branches Impacted",
            "runs_impacted": "Runs",
            "tests_impacted": "Tests",
            "share": "Share (%)",
        }).reset_index(drop=True)

        fail_event = st.dataframe(
            display_failures,
            width="stretch",
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            height=min(600, 38 + len(display_failures) * 35),
        )

        selected_fail_rows = fail_event.selection.rows
        if selected_fail_rows:
            reason = failure_summary.iloc[selected_fail_rows[0]]["failure_reason"]
            reason_jobs = failing_jobs[failing_jobs["failure_reason"] == reason]

            st.divider()
            st.markdown(f"**Jobs with:** `{reason[:120]}`")

            detail = reason_jobs[[
                "branch", "description", "job_id", "run_name", "sha_id",
                "os_type", "machine_type", "status", "posted",
            ]].copy()
            detail["sha_id"] = detail["sha_id"].fillna("").apply(
                lambda s: s[:8] if s else "—"
            )
            detail = detail.sort_values("posted", ascending=False).rename(columns={
                "branch": "Branch",
                "description": "Test",
                "job_id": "Job ID",
                "run_name": "Run",
                "sha_id": "SHA",
                "os_type": "OS",
                "machine_type": "Machine",
                "status": "Status",
                "posted": "Posted",
            })
            st.dataframe(
                detail,
                width="stretch",
                hide_index=True,
                height=min(500, 38 + len(detail) * 35),
            )

        st.divider()
        st.markdown("**Failing Tests × Branch**")
        test_branch_pivot = (
            failing_jobs.groupby(["description", "branch"])["job_id"]
            .count()
            .unstack(fill_value=0)
        )
        test_branch_pivot["Total"] = test_branch_pivot.sum(axis=1)
        test_branch_pivot = (
            test_branch_pivot.sort_values("Total", ascending=False)
            .reset_index()
            .rename(columns={"description": "Test"})
        )
        st.dataframe(
            test_branch_pivot,
            width="stretch",
            hide_index=True,
            height=min(500, 38 + len(test_branch_pivot) * 35),
        )

# =====================================================================
#  TAB 3 — TEST MATRIX COVERAGE
# =====================================================================
with tab_cov:
    st.subheader(f"Branch × Environment Heatmap — {scope_label}")

    os_jobs = filt_jobs[
        filt_jobs["os_type"].notna() & (filt_jobs["os_type"] != "")
    ].copy()

    if os_jobs.empty:
        st.info("No OS type information available in the current job data.")
    else:
        pivot_data = os_jobs.groupby(["branch", "os_type"]).agg(
            total=("job_id", "count"),
            passed=("status", lambda s: (s == "pass").sum()),
        ).reset_index()
        pivot_data["pass_rate"] = (
            (pivot_data["passed"] / pivot_data["total"]) * 100
        ).round(1)

        branch_list = sorted(pivot_data["branch"].unique())
        os_list = sorted(pivot_data["os_type"].unique())

        heat_matrix = np.full((len(branch_list), len(os_list)), np.nan)
        anno_matrix = [[""] * len(os_list) for _ in range(len(branch_list))]

        branch_idx = {b: i for i, b in enumerate(branch_list)}
        os_idx = {o: i for i, o in enumerate(os_list)}

        for _, row in pivot_data.iterrows():
            bi = branch_idx[row["branch"]]
            oi = os_idx[row["os_type"]]
            heat_matrix[bi][oi] = row["pass_rate"]
            anno_matrix[bi][oi] = (
                f'{row["pass_rate"]}%<br>({int(row["total"])} jobs)'
            )

        fig_heat = go.Figure(data=go.Heatmap(
            z=heat_matrix,
            x=os_list,
            y=branch_list,
            text=anno_matrix,
            texttemplate="%{text}",
            colorscale=[[0, "#d36086"], [0.5, "#d6bf57"], [1, "#54b399"]],
            colorbar=dict(title="Pass Rate %"),
            hovertemplate=(
                "Branch: %{y}<br>OS: %{x}<br>Pass Rate: %{z:.1f}%<extra></extra>"
            ),
            zmin=0,
            zmax=100,
        ))
        fig_heat.update_layout(
            height=max(300, 60 * len(branch_list)),
            xaxis_title="OS Type",
            yaxis_title="Branch",
            yaxis=dict(autorange="reversed"),
        )
        st.plotly_chart(fig_heat, width="stretch")

    st.divider()
    st.subheader("Environment Execution Breadth")

    if os_jobs.empty:
        st.info("No OS type information available.")
    else:
        env_status = (
            os_jobs.groupby(["os_type", "status"])
            .size()
            .reset_index(name="count")
        )
        fig_env = px.bar(
            env_status,
            x="os_type",
            y="count",
            color="status",
            color_discrete_map=color_map,
            barmode="stack",
            text_auto=True,
            title=f"Job Volume & Health per OS — {scope_label}",
            labels={"os_type": "OS Type", "count": "Jobs", "status": "Status"},
        )
        fig_env.update_layout(height=400, legend_title_text="Status")
        st.plotly_chart(fig_env, width="stretch")

    st.divider()
    st.subheader("Coverage Detail")

    if os_jobs.empty:
        st.info("No environment data to display.")
    else:
        cov_detail = os_jobs.groupby(["branch", "os_type", "machine_type"]).agg(
            total_jobs=("job_id", "count"),
            passed=("status", lambda s: (s == "pass").sum()),
            failed=("status", lambda s: s.isin(["fail", "dead"]).sum()),
        ).reset_index()
        cov_detail["pass_rate"] = (
            (cov_detail["passed"] / cov_detail["total_jobs"]) * 100
        ).round(1)
        cov_detail = cov_detail.sort_values(
            ["pass_rate", "branch"], ascending=[True, True]
        ).reset_index(drop=True)

        def _coverage_row_color(row):
            rate = row.get("pass_rate", 100)
            if rate < 50:
                return ["background-color: rgba(211,96,134,0.2)"] * len(row)
            if rate < 80:
                return ["background-color: rgba(214,191,87,0.2)"] * len(row)
            return [""] * len(row)

        cov_display = cov_detail.rename(columns={
            "branch": "Branch",
            "os_type": "OS Type",
            "machine_type": "Machine Type",
            "total_jobs": "Total Jobs",
            "passed": "Passed",
            "failed": "Failed",
            "pass_rate": "Pass Rate (%)",
        })
        st.dataframe(
            cov_display.style.apply(_coverage_row_color, axis=1),
            width="stretch",
            height=min(800, 38 + len(cov_display) * 35),
            hide_index=True,
        )

# =====================================================================
#  TAB 4 — FLAKY TESTS
# =====================================================================
with tab_flaky:
    # Suite-wide flakiness: mixed pass/fail across runs/branches.
    # Always-same failure reason = consistent bug, not flaky.
    analysis_jobs = filt_jobs[
        filt_jobs["description"].notna() & (filt_jobs["description"] != "")
    ].copy()
    analysis_jobs["sha_id"] = (
        analysis_jobs["sha_id"].fillna("unknown").replace("", "unknown")
    )
    analysis_jobs["failure_template"] = (
        analysis_jobs["failure_template"].fillna("")
    )

    test_exec_counts = analysis_jobs.groupby("description")["job_id"].count()
    eligible_tests = test_exec_counts[test_exec_counts >= min_executions].index
    analysis_jobs = analysis_jobs[analysis_jobs["description"].isin(eligible_tests)]

    if analysis_jobs.empty:
        st.warning(
            f"No tests have at least {min_executions} executions. "
            "Try lowering the **Min Executions** slider."
        )
        st.stop()

    def _compute_flakiness(group: pd.DataFrame) -> pd.Series:
        total = len(group)
        passed = int((group["status"] == "pass").sum())
        failed = int(group["status"].isin(["fail", "dead"]).sum())

        unique_failures = group.loc[
            group["status"].isin(["fail", "dead"]) & (group["failure_template"] != ""),
            "failure_template",
        ].nunique()

        sha_statuses = group.groupby("sha_id")["status"].apply(lambda s: frozenset(s))
        same_sha_flaky = int(
            sha_statuses.apply(
                lambda fs: bool({"pass"} & fs) and bool({"fail", "dead"} & fs)
            ).sum()
        )

        branch_agg = group.groupby("branch")["status"].agg(
            b_pass=lambda s: (s == "pass").any(),
            b_fail=lambda s: s.isin(["fail", "dead"]).any(),
        )
        branch_mixed = int((branch_agg["b_pass"] & branch_agg["b_fail"]).sum())

        has_mixed_outcomes = passed > 0 and failed > 0
        always_same_failure = passed == 0 and failed > 0 and unique_failures <= 1

        if has_mixed_outcomes:
            score = round(min(passed, failed) / total * 100, 1)
        elif not always_same_failure and failed > 0 and unique_failures > 1:
            score = round(min(unique_failures / total * 100, 100.0), 1)
        else:
            score = 0.0

        return pd.Series({
            "flakiness_score": score,
            "total_runs": total,
            "passed": passed,
            "failed": failed,
            "unique_failures": unique_failures,
            "branches_affected": branch_mixed,
            "same_sha_flaky": same_sha_flaky,
            "total_shas": len(sha_statuses),
        })

    flaky_df = (
        analysis_jobs.groupby("description")
        .apply(_compute_flakiness, include_groups=False)
        .reset_index()
    )
    flaky_tests = flaky_df[flaky_df["flakiness_score"] > 0].copy()

    tests_analyzed = len(flaky_df)
    flaky_count = len(flaky_tests)
    flakiness_rate = (
        round(flaky_count / tests_analyzed * 100, 1) if tests_analyzed else 0.0
    )
    most_flaky = (
        flaky_tests.sort_values("flakiness_score", ascending=False)
        .iloc[0]["description"]
        if not flaky_tests.empty
        else "—"
    )
    most_flaky_display = most_flaky[:60] + "…" if len(most_flaky) > 60 else most_flaky
    consistent_failures = int(
        (
            (flaky_df["passed"] == 0)
            & (flaky_df["unique_failures"] <= 1)
            & (flaky_df["failed"] > 0)
        ).sum()
    )

    st.subheader(f"Flaky Test Summary — {scope_label}")
    f1, f2, f3, f4, f5 = st.columns(5)
    f1.metric("Tests Analyzed", tests_analyzed)
    f2.metric("Flaky Tests", flaky_count)
    f3.metric("Consistent Bugs", consistent_failures)
    f4.metric("Flakiness Rate", f"{flakiness_rate}%")
    f5.metric("Most Flaky", most_flaky_display)

    st.divider()

    if flaky_tests.empty:
        st.info(
            "No flaky tests detected. Tests either pass consistently or "
            "always fail with the same failure reason (consistent bugs)."
        )
    else:
        st.subheader(f"Flaky Tests ({flaky_count})")

        ranked = (
            flaky_tests.sort_values("flakiness_score", ascending=False)
            .reset_index(drop=True)
        )
        ranked_display = ranked.rename(columns={
            "description": "Test",
            "flakiness_score": "Flakiness (%)",
            "total_runs": "Total Runs",
            "passed": "Passed",
            "failed": "Failed",
            "unique_failures": "Unique Failures",
            "branches_affected": "Branches Affected",
            "same_sha_flaky": "Same-SHA Flaky",
            "total_shas": "Total SHAs",
        })

        event = st.dataframe(
            ranked_display,
            width="stretch",
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            height=min(600, 38 + len(ranked_display) * 35),
        )

        selected_rows = event.selection.rows
        if selected_rows:
            selected_test = ranked.iloc[selected_rows[0]]["description"]

            st.divider()
            st.subheader(f"Detail: {selected_test[:80]}")

            test_jobs = analysis_jobs[
                analysis_jobs["description"] == selected_test
            ].sort_values("posted")

            timeline_df = test_jobs[[
                "posted", "status", "duration", "sha_id", "branch",
                "os_type", "failure_template",
            ]].copy()
            timeline_df["sha_short"] = timeline_df["sha_id"].apply(lambda s: s[:8])
            timeline_df["duration_min"] = (timeline_df["duration"] / 60).round(1)

            fig_timeline = px.scatter(
                timeline_df,
                x="posted",
                y="status",
                color="branch",
                size="duration_min",
                hover_data=["sha_short", "os_type", "duration_min", "failure_template"],
                title="Pass/Fail Timeline (colored by branch)",
                labels={
                    "posted": "Time",
                    "status": "Status",
                    "duration_min": "Duration (min)",
                    "sha_short": "SHA",
                    "failure_template": "Failure",
                    "branch": "Branch",
                },
            )
            fig_timeline.update_layout(height=350)
            fig_timeline.update_yaxes(
                categoryorder="array", categoryarray=["pass", "fail", "dead"]
            )
            st.plotly_chart(fig_timeline, width="stretch")

            col_branch, col_env = st.columns(2)

            with col_branch:
                st.markdown("**Per-Branch Breakdown**")
                branch_breakdown = test_jobs.groupby("branch").agg(
                    passed=("status", lambda s: (s == "pass").sum()),
                    failed=("status", lambda s: s.isin(["fail", "dead"]).sum()),
                    total=("job_id", "count"),
                ).reset_index()
                branch_breakdown["flaky"] = (
                    (branch_breakdown["passed"] > 0) & (branch_breakdown["failed"] > 0)
                ).map({True: "Yes", False: "No"})
                st.dataframe(
                    branch_breakdown.rename(columns={
                        "branch": "Branch",
                        "passed": "Passed",
                        "failed": "Failed",
                        "total": "Total",
                        "flaky": "Flaky?",
                    }),
                    width="stretch",
                    hide_index=True,
                )

            with col_env:
                st.markdown("**Environment Breakdown**")
                env_breakdown = test_jobs.groupby(["os_type", "machine_type"]).agg(
                    passed=("status", lambda s: (s == "pass").sum()),
                    failed=("status", lambda s: s.isin(["fail", "dead"]).sum()),
                    total=("job_id", "count"),
                ).reset_index()
                env_breakdown["flaky"] = (
                    (env_breakdown["passed"] > 0) & (env_breakdown["failed"] > 0)
                ).map({True: "Yes", False: "No"})
                st.dataframe(
                    env_breakdown.rename(columns={
                        "os_type": "OS Type",
                        "machine_type": "Machine Type",
                        "passed": "Passed",
                        "failed": "Failed",
                        "total": "Total",
                        "flaky": "Flaky?",
                    }),
                    width="stretch",
                    hide_index=True,
                )

            test_failures = test_jobs[
                test_jobs["status"].isin(["fail", "dead"])
                & (test_jobs["failure_template"] != "")
            ]
            if not test_failures.empty:
                st.markdown("**Failure Reasons**")
                reason_counts = (
                    test_failures.groupby("failure_template")["job_id"]
                    .count()
                    .reset_index(name="count")
                    .sort_values("count", ascending=False)
                    .rename(columns={
                        "failure_template": "Failure Reason",
                        "count": "Occurrences",
                    })
                )
                st.dataframe(reason_counts, width="stretch", hide_index=True)

        st.divider()
        st.subheader(f"Flaky Tests by Branch — {scope_label}")

        flaky_branch = (
            analysis_jobs[analysis_jobs["description"].isin(flaky_tests["description"])]
            .drop_duplicates(subset=["description", "branch"])
            .groupby("branch")["description"]
            .nunique()
            .reset_index(name="flaky_tests")
            .sort_values("flaky_tests", ascending=False)
        )

        fig_branch = px.bar(
            flaky_branch,
            x="branch",
            y="flaky_tests",
            text_auto=True,
            title=f"Flaky Test Count by Branch — {scope_label}",
            labels={"branch": "Branch", "flaky_tests": "Flaky Tests"},
            color_discrete_sequence=["#d36086"],
        )
        fig_branch.update_layout(height=400)
        st.plotly_chart(fig_branch, width="stretch")
