from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from libs.defaults import (
    STATUS_ACTIVE,
    STATUS_ALERTING,
    STATUS_COMPLETED,
    STATUS_FAILING,
)


@dataclass
class Results:
    pass_: int = 0
    fail: int = 0
    dead: int = 0
    running: int = 0
    waiting: int = 0
    queued: int = 0

    @property
    def total(self) -> int:
        return (
            self.pass_
            + self.fail
            + self.dead
            + self.running
            + self.waiting
            + self.queued
        )

    @property
    def completed(self) -> int:
        return self.pass_ + self.fail + self.dead

    @property
    def failed(self) -> int:
        """Fail + dead — matches dashboard “failed” semantics."""
        return self.fail + self.dead

    def bump(self, status: str, *, success: bool | None = None) -> None:
        """Increment the bucket matching a job/run status string."""
        status = (status or "").strip().lower()
        if status.startswith("finished "):
            status = status.split(" ", 1)[1]
        if status == "dead":
            self.dead += 1
        elif status == "running":
            self.running += 1
        elif status == "waiting":
            self.waiting += 1
        elif status == "queued":
            self.queued += 1
        elif status == "pass" or success is True:
            self.pass_ += 1
        elif status == "fail" or success is False:
            self.fail += 1
        elif success:
            self.pass_ += 1
        else:
            self.fail += 1


@dataclass
class Job:
    job_id: int = 0
    name: str = ""
    description: str = ""
    owner: str = ""
    branch: str = ""
    sha1: str = ""
    suite: str = ""
    success: bool = False
    status: str = ""
    duration: float = 0.0
    os_type: str = ""
    os_version: str = ""
    machine_type: str = ""
    failure_reason: str = ""
    run_name: str = ""
    posted: datetime | None = None
    targets: dict[str, Any] = field(default_factory=dict)

    @property
    def sha_short(self) -> str:
        return (self.sha1 or "")[:8]

    @property
    def is_completed(self) -> bool:
        return self.status in STATUS_COMPLETED

    @property
    def is_failing(self) -> bool:
        return self.status in STATUS_FAILING


@dataclass
class TestRun:
    name: str = ""
    branch: str = ""
    suite: str = ""
    sha_id: str = ""
    machine_type: str = ""
    status: str = ""
    user: str = ""
    scheduled: datetime | None = None
    posted: datetime | None = None
    started: datetime | None = None
    updated: datetime | None = None
    job_ids: list[Job] = field(default_factory=list)
    results: Results = field(default_factory=Results)

    @property
    def total_jobs(self) -> int:
        return self.results.total

    @property
    def sha_short(self) -> str:
        return (self.sha_id or "")[:8]

    @property
    def fail_pct(self) -> float:
        total = self.results.total
        if not total:
            return 0.0
        return self.results.failed / total * 100

    @property
    def is_completed(self) -> bool:
        return self.status in STATUS_COMPLETED

    @property
    def is_active(self) -> bool:
        return self.status in STATUS_ACTIVE

    @property
    def is_alerting(self) -> bool:
        return self.status in STATUS_ALERTING


@dataclass
class TestRunsSummary:
    cnt_testruns: int = 0
    cnt_jobs: int = 0
    cnt_pass: int = 0
    cnt_fail: int = 0
    cnt_dead: int = 0
    cnt_running: int = 0
    cnt_queued: int = 0
    cnt_waiting: int = 0
    pct_pass: float = 0.0
    pct_fail: float = 0.0
    pct_dead: float = 0.0
    pct_running: float = 0.0
    pct_queued: float = 0.0
    pct_waiting: float = 0.0


@dataclass
class OsSummary:
    os_type: str = ""
    cnt_jobs: int = 0
    cnt_pass: int = 0
    cnt_fail: int = 0
    cnt_dead: int = 0
    cnt_running: int = 0
    cnt_queued: int = 0
    cnt_waiting: int = 0
    pct_pass: float = 0.0
    pct_fail: float = 0.0
    pct_dead: float = 0.0
    pct_running: float = 0.0
    pct_queued: float = 0.0
    pct_waiting: float = 0.0


@dataclass
class FailureReasonStat:
    """Aggregate count for a single job failure reason."""

    reason: str = ""
    count: int = 0
    pct: float = 0.0
    runs_impacted: int = 0
    branches_impacted: int = 0
    suites_impacted: int = 0
    tests_impacted: int = 0


@dataclass
class FailedTestRunStat:
    """Compact top-failure row for Streamlit tables and LLM tools."""

    name: str = ""
    branch: str = ""
    suite: str = ""
    status: str = ""
    user: str = ""
    fail_pct: float = 0.0
    results: Results = field(default_factory=Results)


@dataclass
class FailedRunStat:
    """Job-based top failure run row (overview / nightly drill-ins)."""

    run_name: str = ""
    suite: str = ""
    failed_jobs: int = 0
    total_jobs: int = 0
    fail_pct: float = 0.0


@dataclass
class SuiteTrend:
    """Pass/fail/dead aggregates grouped by suite."""

    suite: str = ""
    results: Results = field(default_factory=Results)


@dataclass
class DimensionStatusTrend:
    """Status aggregates for an arbitrary dimension (suite/branch/os/…)."""

    dimension: str = ""
    key: str = ""
    results: Results = field(default_factory=Results)


@dataclass
class DailyTrend:
    """Pass/fail/dead aggregates grouped by calendar day."""

    day: date | None = None
    results: Results = field(default_factory=Results)


@dataclass
class DailyStatusPct:
    """Per-day status mix as percentages (nightly/release trend lines)."""

    day: date | None = None
    cnt_jobs: int = 0
    pct_pass: float = 0.0
    pct_fail: float = 0.0
    pct_dead: float = 0.0
    pct_running: float = 0.0
    pct_queued: float = 0.0
    pct_waiting: float = 0.0


@dataclass
class JobsSummary:
    """Aggregate job outcome counts for a JobsStats fetch."""

    cnt_jobs: int = 0
    cnt_pass: int = 0
    cnt_fail: int = 0
    cnt_dead: int = 0
    cnt_running: int = 0
    cnt_queued: int = 0
    cnt_waiting: int = 0
    pct_pass: float = 0.0
    pct_fail: float = 0.0
    pct_dead: float = 0.0
    pct_running: float = 0.0
    pct_queued: float = 0.0
    pct_waiting: float = 0.0


@dataclass
class BranchSummary:
    """Per-branch reliability (coverage / hardware)."""

    branch: str = ""
    cnt_runs: int = 0
    cnt_jobs: int = 0
    cnt_pass: int = 0
    cnt_fail: int = 0
    pct_pass: float = 0.0
    pct_fail: float = 0.0
    avg_duration: float = 0.0


@dataclass
class ShaSummary:
    """Per-SHA health (builds / release)."""

    sha1: str = ""
    sha_short: str = ""
    cnt_runs: int = 0
    cnt_jobs: int = 0
    cnt_pass: int = 0
    cnt_fail: int = 0
    pct_pass: float = 0.0


@dataclass
class PassRateCell:
    """Heatmap / coverage-detail cell (branch × OS × optional machine)."""

    branch: str = ""
    os_type: str = ""
    machine_type: str = ""
    cnt_jobs: int = 0
    cnt_pass: int = 0
    cnt_fail: int = 0
    pct_pass: float = 0.0


@dataclass
class GroupReliabilityStat:
    """Hardware reliability row for an arbitrary group key."""

    key: str = ""
    cnt_jobs: int = 0
    cnt_pass: int = 0
    cnt_fail: int = 0
    pct_pass: float = 0.0
    pct_fail: float = 0.0
    avg_duration: float = 0.0


@dataclass
class FlakyTestStat:
    """Coverage flaky-test row keyed by job description."""

    description: str = ""
    flakiness_score: float = 0.0
    total_runs: int = 0
    passed: int = 0
    failed: int = 0
    unique_failures: int = 0
    branches_affected: int = 0
    same_sha_flaky: int = 0
    total_shas: int = 0


@dataclass
class NightlyRunSummary:
    """Nightly report KPI bundle."""

    cnt_runs: int = 0
    cnt_alerting: int = 0
    cnt_completed: int = 0
    cnt_pass: int = 0
    pct_runs_passed: float = 0.0


@dataclass
class ActiveRunsSummary:
    """Active testrun and in-flight job counts for the overview scorecard."""

    cnt_testruns: int = 0
    cnt_jobs: int = 0
    cnt_running: int = 0
    cnt_waiting: int = 0
    cnt_queued: int = 0
    oldest_age: str = "—"


@dataclass
class ClusterHealthSnapshot:
    """Overview cluster-health card: badge, mix, and supporting context."""

    badge: str = "Unknown"
    reasons: list[str] = field(default_factory=list)
    completed: JobsSummary = field(default_factory=JobsSummary)
    cnt_testruns: int = 0
    cnt_completed_runs: int = 0
    cnt_active_runs: int = 0
    cnt_jobs: int = 0
    cnt_inflight: int = 0
    cnt_running: int = 0
    cnt_waiting: int = 0
    cnt_queued: int = 0
    pct_completed: float = 0.0
    cnt_not_passed: int = 0
    pct_not_passed: float = 0.0
    cnt_branches: int = 0
    cnt_suites: int = 0
    cnt_machines: int = 0
    avg_duration: str = "—"
    top_failure: str = ""
    top_failure_count: int = 0
    stuck_6h: int = 0
    stuck_24h: int = 0
    worst_branch: str = ""
    worst_branch_fail_pct: float = 0.0


@dataclass
class StatusShareTrend:
    """Pass/fail/dead mix as counts and percentages for one group key."""

    key: str = ""
    results: Results = field(default_factory=Results)
    pct_pass: float = 0.0
    pct_fail: float = 0.0
    pct_dead: float = 0.0


@dataclass
class FailingTestStat:
    """Top failing test keyed by job description."""

    description: str = ""
    count: int = 0
    pct: float = 0.0
    runs_impacted: int = 0
