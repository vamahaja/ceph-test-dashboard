"""
Hardware Reliability — machine-type-centric dashboard.

Primary filter is ``machine_type``. Completed jobs are loaded from
matching completed runs (Paddles ``/jobs/?machine_type=`` ignores that
filter and returns the global latest queue). Architecture comes from
live Paddles ``/nodes/`` inventory.
"""

from __future__ import annotations

import re
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from libs.hardware import (
    _MACHINE_ERROR_RE,
    enrich_dataframe_with_hardware,
)
from libs.config import get_hardware_config
from libs.normalizer import (
    get_completed_jobs_for_machine_type,
    get_machine_type_arch_map,
    get_machine_types_from_completed_runs,
)

# All tuning constants come from a single source of truth: libs/config.py
# Override in ~/.config/ceph-test-dashboard.ini under [hardware]
_HW          = get_hardware_config()
_RUN_SCAN    = _HW["run_scan"]
_MAX_RUNS    = _HW["max_runs"]
_MIN_RUNS    = _HW["min_runs"]
_DAYS_WINDOW = _HW["days_window"]

st.markdown(
    "<h1 style='text-align: center;'>Hardware Reliability</h1>",
    unsafe_allow_html=True,
)
st.markdown(
    "Select a **machine type** to analyze suite stability for that lab class "
    "across branches, suites, and OS."
)

# ── sidebar: machine type first ───────────────────────────────────────
st.sidebar.header("Filters")

# Days window slider — controls both the machine type dropdown AND
# the job fetch so the two are always in sync.
days_window = st.sidebar.slider(
    "Days Window",
    min_value=7,
    max_value=30,
    value=_DAYS_WINDOW,
    step=7,
    help=(
        "Only show machine types and jobs from completed runs posted "
        "within this many days. Increase if your machine type runs infrequently."
    ),
)

arch_map = get_machine_type_arch_map()

# Pass the same days_window to the dropdown so it only lists machine
# types that actually have data in the selected window.
machine_types = get_machine_types_from_completed_runs(
    count=_RUN_SCAN,
    days_window=days_window,
)

if not machine_types:
    st.warning(
        f"No completed runs with a machine type found in the last "
        f"**{days_window} days**. Try increasing the **Days Window** slider."
    )
    st.stop()

selected_mt = st.sidebar.selectbox(
    "Machine Type",
    machine_types,
    help="Only machine types with completed runs in the selected Days Window are shown.",
)

arch_label = arch_map.get(selected_mt.lower(), "Unknown")
st.sidebar.caption(f"Architecture: **{arch_label}**")

with st.spinner(f"Loading completed jobs for {selected_mt}…"):
    jobs_raw = get_completed_jobs_for_machine_type(
        selected_mt,
        run_scan=_RUN_SCAN,
        max_runs=_MAX_RUNS,
        days_window=days_window,
    )
if not jobs_raw:
    st.warning(
        f"No completed jobs (pass/fail/dead) found for **{selected_mt}** "
        f"in the last {days_window} days "
        f"(scanned {_RUN_SCAN} most recent runs)."
    )
    st.stop()

# ── thin-data warning + scope info banner ────────────────────────────
_n_runs = len({j.get("run_name", "") for j in jobs_raw if j.get("run_name")})
if _n_runs < _MIN_RUNS:
    st.warning(
        f"⚠️ Only **{_n_runs} run{'s' if _n_runs != 1 else ''}** found for "
        f"**{selected_mt}** in the last {days_window} days — "
        "statistics may not be reliable. "
        "Try increasing the **Days Window** slider."
    )
st.info(
    f"Showing **{len(jobs_raw)} jobs** from **{_n_runs} run{'s' if _n_runs != 1 else ''}** "
    f"on **{selected_mt}** · last **{days_window} days** "
    f"(up to {_MAX_RUNS} runs, scanned {_RUN_SCAN})."
)

# Build DataFrame first, then vectorise architecture enrichment (H-05)
df_jobs = pd.DataFrame(jobs_raw)

df_jobs["posted"] = pd.to_datetime(df_jobs["posted"], errors="coerce")
df_jobs["machine_type"] = (
    df_jobs["machine_type"].fillna(selected_mt).replace("", selected_mt)
)
df_jobs["branch"] = df_jobs["branch"].fillna("unknown").replace("", "unknown")
df_jobs["suite"] = df_jobs["suite"].fillna("unknown").replace("", "unknown")
df_jobs["os_type"] = df_jobs["os_type"].fillna("").replace("", "unknown")

# Vectorised arch enrichment — replaces enrich_jobs_with_hardware() loop (H-05)
df_jobs = enrich_dataframe_with_hardware(
    df_jobs,
    arch_by_machine_type=arch_map,
    fallback_arch=arch_label,
)

# Secondary filters from jobs for this machine type
available_branches = sorted(
    b for b in df_jobs["branch"].dropna().unique().tolist() if b
)
selected_branches = st.sidebar.multiselect(
    "Branch",
    available_branches,
    default=available_branches,
)
if not selected_branches:
    st.warning("Select at least one branch.")
    st.stop()

available_suites = sorted(
    s for s in df_jobs["suite"].dropna().unique().tolist() if s
)
selected_suites = st.sidebar.multiselect(
    "Suite",
    available_suites,
    default=available_suites,
)
if not selected_suites:
    st.warning("Select at least one suite.")
    st.stop()

filt_jobs = df_jobs[
    df_jobs["branch"].isin(selected_branches)
    & df_jobs["suite"].isin(selected_suites)
].copy()
if filt_jobs.empty:
    st.warning("No jobs match the selected branch/suite filters.")
    st.stop()

# ── constants ─────────────────────────────────────────────────────────
color_map = {
    "pass": "#54b399",
    "fail": "#d36086",
    "dead": "#aa6556",
}

# ── KPIs for selected machine type ────────────────────────────────────
total_jobs = len(filt_jobs)
passed = int((filt_jobs["status"] == "pass").sum())
failed = int(filt_jobs["status"].isin(["fail", "dead"]).sum())
pass_rate = round(passed / total_jobs * 100, 1) if total_jobs else 0.0
n_branches = filt_jobs["branch"].nunique()
n_suites = filt_jobs["suite"].nunique()
avg_dur_min = round(filt_jobs["duration"].mean() / 60, 1) if total_jobs else 0.0

st.subheader(f"{selected_mt} — Hardware Dashboard")
k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Total Jobs", total_jobs)
k2.metric("Pass Rate", f"{pass_rate}%")
k3.metric("Branches", n_branches)
k4.metric("Suites", n_suites)
k5.metric("Architecture", arch_label)

tab_branch, tab_suite, tab_os, tab_fail = st.tabs(
    ["By Branch", "By Suite", "By OS", "Machine Errors"]
)


def _reliability_table(df: pd.DataFrame, group_col: str) -> pd.DataFrame:
    stats = df.groupby(group_col).agg(
        jobs=("job_id", "count"),
        passed=("status", lambda s: (s == "pass").sum()),
        failed=("status", lambda s: s.isin(["fail", "dead"]).sum()),
        avg_duration_s=("duration", "mean"),
    ).reset_index()
    stats["pass_rate"] = stats.apply(
        lambda r: round(r["passed"] / r["jobs"] * 100, 1) if r["jobs"] else 0.0,
        axis=1,
    )
    stats["fail_rate"] = stats.apply(
        lambda r: round(r["failed"] / r["jobs"] * 100, 1) if r["jobs"] else 0.0,
        axis=1,
    )
    stats["avg_duration_min"] = (stats["avg_duration_s"] / 60).round(1)
    return stats.sort_values("fail_rate", ascending=False)


def _status_bar(df: pd.DataFrame, group_col: str, title: str):
    status_counts = (
        df.groupby([group_col, "status"]).size().reset_index(name="count")
    )
    fig = px.bar(
        status_counts,
        x=group_col,
        y="count",
        color="status",
        color_discrete_map=color_map,
        barmode="stack",
        text_auto=True,
        title=title,
        labels={group_col: group_col.replace("_", " ").title(), "count": "Jobs"},
    )
    fig.update_layout(height=400, legend_title_text="Status")
    st.plotly_chart(fig, width="stretch")


def _pass_rate_bar(stats: pd.DataFrame, group_col: str, title: str):
    fig = px.bar(
        stats.sort_values("pass_rate", ascending=True),
        x="pass_rate",
        y=group_col,
        orientation="h",
        text_auto=True,
        title=title,
        labels={
            group_col: group_col.replace("_", " ").title(),
            "pass_rate": "Pass Rate (%)",
        },
        color_discrete_sequence=["#54b399"],
    )
    fig.update_layout(
        height=max(280, 40 * len(stats)),
        xaxis_range=[0, 105],
    )
    st.plotly_chart(fig, width="stretch")


# =====================================================================
#  TAB — BY BRANCH
# =====================================================================
with tab_branch:
    st.subheader(f"Branch Comparison — {selected_mt}")
    st.caption("How this machine type performs across branches.")

    branch_stats = _reliability_table(filt_jobs, "branch")
    st.dataframe(
        branch_stats.rename(columns={
            "branch": "Branch",
            "jobs": "Jobs",
            "passed": "Passed",
            "failed": "Failed",
            "pass_rate": "Pass Rate (%)",
            "fail_rate": "Fail Rate (%)",
            "avg_duration_min": "Avg Duration (min)",
        })[[
            "Branch", "Jobs", "Passed", "Failed",
            "Pass Rate (%)", "Fail Rate (%)", "Avg Duration (min)",
        ]],
        width="stretch",
        hide_index=True,
    )

    st.divider()
    _status_bar(
        filt_jobs, "branch",
        f"Job Status by Branch — {selected_mt}",
    )
    _pass_rate_bar(
        branch_stats, "branch",
        f"Pass Rate by Branch — {selected_mt}",
    )

# =====================================================================
#  TAB — BY SUITE
# =====================================================================
with tab_suite:
    st.subheader(f"Suite Health — {selected_mt}")

    suite_stats = _reliability_table(filt_jobs, "suite")
    st.dataframe(
        suite_stats.rename(columns={
            "suite": "Suite",
            "jobs": "Jobs",
            "passed": "Passed",
            "failed": "Failed",
            "pass_rate": "Pass Rate (%)",
            "fail_rate": "Fail Rate (%)",
            "avg_duration_min": "Avg Duration (min)",
        })[[
            "Suite", "Jobs", "Passed", "Failed",
            "Pass Rate (%)", "Fail Rate (%)", "Avg Duration (min)",
        ]],
        width="stretch",
        hide_index=True,
    )

    st.divider()
    _status_bar(
        filt_jobs, "suite",
        f"Job Status by Suite — {selected_mt}",
    )
    _pass_rate_bar(
        suite_stats, "suite",
        f"Pass Rate by Suite — {selected_mt}",
    )

# =====================================================================
#  TAB — BY OS
# =====================================================================
with tab_os:
    st.subheader(f"OS Distribution — {selected_mt}")

    os_jobs = filt_jobs[filt_jobs["os_type"] != "unknown"].copy()
    # H-09: show count of excluded jobs so the exclusion is visible
    excluded_os = len(filt_jobs) - len(os_jobs)
    if excluded_os > 0:
        st.caption(
            f"ℹ️ {excluded_os} job{'s' if excluded_os != 1 else ''} excluded — "
            "no OS type recorded."
        )

    if os_jobs.empty:
        st.info("No OS type information available for this machine type.")
    else:
        os_stats = _reliability_table(os_jobs, "os_type")
        st.dataframe(
            os_stats.rename(columns={
                "os_type": "OS Type",
                "jobs": "Jobs",
                "passed": "Passed",
                "failed": "Failed",
                "pass_rate": "Pass Rate (%)",
                "fail_rate": "Fail Rate (%)",
                "avg_duration_min": "Avg Duration (min)",
            })[[
                "OS Type", "Jobs", "Passed", "Failed",
                "Pass Rate (%)", "Fail Rate (%)", "Avg Duration (min)",
            ]],
            width="stretch",
            hide_index=True,
        )

        st.divider()
        _status_bar(
            os_jobs, "os_type",
            f"Job Status by OS — {selected_mt}",
        )

        # Branch × OS heatmap for this machine type
        st.divider()
        st.subheader("Branch × OS Pass Rate")
        pivot = os_jobs.groupby(["branch", "os_type"]).agg(
            total=("job_id", "count"),
            passed=("status", lambda s: (s == "pass").sum()),
        ).reset_index()
        pivot["pass_rate"] = ((pivot["passed"] / pivot["total"]) * 100).round(1)

        branches = sorted(pivot["branch"].unique())
        os_list = sorted(pivot["os_type"].unique())
        heat = np.full((len(branches), len(os_list)), np.nan)
        anno = [[""] * len(os_list) for _ in range(len(branches))]
        b_idx = {b: i for i, b in enumerate(branches)}
        o_idx = {o: i for i, o in enumerate(os_list)}

        # H-07: vectorised numpy index assignment — replaces iterrows() loop
        rows_i = pivot["branch"].map(b_idx).to_numpy()
        cols_i = pivot["os_type"].map(o_idx).to_numpy()
        heat[rows_i, cols_i] = pivot["pass_rate"].to_numpy()
        for r, c, rate, tot in zip(
            rows_i, cols_i, pivot["pass_rate"], pivot["total"]
        ):
            anno[r][c] = f"{rate}%<br>({int(tot)})"

        fig_heat = go.Figure(data=go.Heatmap(
            z=heat,
            x=os_list,
            y=branches,
            text=anno,
            texttemplate="%{text}",
            colorscale=[[0, "#d36086"], [0.5, "#d6bf57"], [1, "#54b399"]],
            colorbar=dict(title="Pass Rate %"),
            zmin=0,
            zmax=100,
        ))
        fig_heat.update_layout(
            height=max(300, 50 * len(branches)),
            xaxis_title="OS Type",
            yaxis_title="Branch",
            yaxis=dict(autorange="reversed"),
            title=f"Branch × OS — {selected_mt}",
        )
        st.plotly_chart(fig_heat, width="stretch")

# =====================================================================
#  TAB — MACHINE ERRORS
# =====================================================================
with tab_fail:
    st.subheader(f"Machine Errors — {selected_mt}")
    st.caption(
        "Lab/infrastructure failures only (dead jobs, reimaging, lock/SSH, "
        "provisioning timeouts). Product test failures are excluded."
    )

    failing = filt_jobs[filt_jobs["status"].isin(["fail", "dead"])].copy()
    failing["failure_reason"] = (
        failing["failure_template"]
        .fillna("")
        .replace("", "Unknown failure")
    )

    # H-06: vectorised machine-error filter — replaces row-wise apply() loop
    dead_mask = failing["status"] == "dead"
    reason_known = failing["failure_reason"] != "Unknown failure"
    regex_mask = failing["failure_reason"].str.contains(
        _MACHINE_ERROR_RE.pattern, flags=re.IGNORECASE, regex=True, na=False
    )
    # dead + no reason → infra; dead + matching reason → infra
    # dead + non-matching reason → test-timeout, exclude
    # fail + matching reason → infra
    failing = failing[
        (dead_mask & (~reason_known | regex_mask)) | (~dead_mask & regex_mask)
    ].copy()

    if failing.empty:
        st.info(
            f"No machine errors for **{selected_mt}** with the selected filters."
        )
    else:
        f1, f2, f3 = st.columns(3)
        f1.metric("Machine Errors", len(failing))
        f2.metric("Branches Impacted", failing["branch"].nunique())
        f3.metric("Suites Impacted", failing["suite"].nunique())

        st.divider()
        st.markdown("**Top Machine Error Reasons**")
        fail_summary = failing.groupby("failure_reason").agg(
            jobs=("job_id", "count"),
            branches=("branch", "nunique"),
            suites=("suite", "nunique"),
            runs=("run_name", "nunique"),
        ).reset_index()
        fail_summary["share"] = (
            fail_summary["jobs"] / fail_summary["jobs"].sum() * 100
        ).round(1)
        fail_summary = fail_summary.sort_values("jobs", ascending=False)

        event = st.dataframe(
            fail_summary.rename(columns={
                "failure_reason": "Machine Error",
                "jobs": "Jobs",
                "branches": "Branches",
                "suites": "Suites",
                "runs": "Runs",
                "share": "Share (%)",
            }),
            width="stretch",
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            height=min(500, 38 + len(fail_summary) * 35),
        )

        selected_rows = event.selection.rows
        if selected_rows:
            reason = fail_summary.iloc[selected_rows[0]]["failure_reason"]
            reason_jobs = failing[failing["failure_reason"] == reason]
            st.markdown(f"**Jobs with:** `{reason[:120]}`")
            detail = reason_jobs[[
                "branch", "suite", "os_type", "description",
                "run_name", "status", "posted",
            ]].sort_values("posted", ascending=False).rename(columns={
                "branch": "Branch",
                "suite": "Suite",
                "os_type": "OS",
                "description": "Test",
                "run_name": "Run",
                "status": "Status",
                "posted": "Posted",
            })
            st.dataframe(
                detail,
                width="stretch",
                hide_index=True,
                height=min(400, 38 + len(detail) * 35),
            )

        st.divider()
        st.markdown("**Machine Errors by Branch**")
        fail_branch = (
            failing.groupby("branch")["job_id"]
            .count()
            .reset_index(name="errors")
            .sort_values("errors", ascending=False)
        )
        fig_fb = px.bar(
            fail_branch,
            x="branch",
            y="errors",
            text_auto=True,
            title=f"Machine Errors by Branch — {selected_mt}",
            labels={"branch": "Branch", "errors": "Machine Errors"},
            color_discrete_sequence=["#d36086"],
        )
        fig_fb.update_layout(height=360)
        st.plotly_chart(fig_fb, width="stretch")
