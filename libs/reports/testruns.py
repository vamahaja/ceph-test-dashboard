from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from functools import cached_property
from typing import TYPE_CHECKING

from libs.defaults import (
    DEFAULT_HEALTH_STUCK_HOURS,
    DEFAULT_HEALTH_STUCK_HOURS_LONG,
    DEFAULT_REPORT_COUNT,
    DEFAULT_RUN_MAX_PAGES,
    DEFAULT_RUN_PAGE_SIZE,
)
from libs.reports import DataSource
from libs.reports.models import (
    ActiveRunsSummary,
    BranchSummary,
    ClusterHealthSnapshot,
    Results,
    TestRun,
    TestRunsSummary,
)
from libs.reports.parsing import as_run_list, as_run_record, to_testrun
from libs.reports.utils import (
    as_date,
    as_utc,
    format_age,
    format_duration,
    health_assessment,
    parse_iso_date,
    pct,
    sha_matches,
)

if TYPE_CHECKING:
    from libs.reports.jobs import JobsStats


def _filter_testruns_by_date(
    rows: list[TestRun],
    *,
    date_start: date | None,
    date_end: date | None,
) -> list[TestRun]:
    """Keep runs whose scheduled (else posted) day falls in ``[start, end]``."""
    if date_start is None and date_end is None:
        return list(rows)
    out: list[TestRun] = []
    for t in rows:
        ts = t.scheduled or t.posted
        if ts is None:
            continue
        day = ts.date() if isinstance(ts, datetime) else ts
        if date_start is not None and day < date_start:
            continue
        if date_end is not None and day > date_end:
            continue
        out.append(t)
    return out

@dataclass
class TestRunsStats(DataSource):
    count: int = DEFAULT_REPORT_COUNT
    branch: str = ""
    suite: str = ""
    testrun_name: str = ""
    user: str = ""
    status: str = ""
    date_start: str = ""
    date_end: str = ""
    testruns: list[TestRun] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        DataSource.__init__(self)
        raw_runs = self.run(
            count=self.count,
            run_name=self.testrun_name or None,
            branch=self.branch or None,
            suite=self.suite or None,
            user=self.user or None,
            status=self.status or None,
            date_start=self.date_start or None,
            date_end=self.date_end or None,
        )
        self.testruns = [to_testrun(raw) for raw in as_run_list(raw_runs)]
        if self.date_start or self.date_end:
            start = parse_iso_date(self.date_start)
            end = parse_iso_date(self.date_end)
            self.testruns = _filter_testruns_by_date(
                self.testruns,
                date_start=start,
                date_end=end,
            )

    @classmethod
    def from_testruns(cls, testruns: list[TestRun]) -> TestRunsStats:
        """Build stats from an already-loaded run list (no API fetch)."""
        obj = cls.__new__(cls)
        DataSource.__init__(obj)
        obj.count = len(testruns)
        obj.branch = ""
        obj.suite = ""
        obj.testrun_name = ""
        obj.user = ""
        obj.status = ""
        obj.date_start = ""
        obj.date_end = ""
        obj.testruns = list(testruns)
        return obj

    @classmethod
    def since(
        cls,
        cutoff: datetime,
        *,
        branch: str = "",
        user: str = "",
        suite: str = "",
        until: datetime | None = None,
        page_size: int = DEFAULT_RUN_PAGE_SIZE,
        max_pages: int = DEFAULT_RUN_MAX_PAGES,
    ) -> TestRunsStats:
        """Page newest-first runs whose ``posted`` time is at or after ``cutoff``.

        Optional ``branch`` / ``user`` / ``suite`` are passed to the API. Optional
        ``until`` is an exclusive upper bound (runs at or after ``until``
        are skipped).
        """
        client = cls.from_testruns([])
        cutoff_utc = as_utc(cutoff)
        until_utc = as_utc(until)
        if cutoff_utc is None:
            return client

        collected: list[TestRun] = []
        page = 1
        while page <= max_pages:
            raw = client.run(
                count=page_size,
                page=page,
                branch=branch or None,
                user=user or None,
                suite=suite or None,
            )
            items = as_run_list(raw)
            if not items:
                break

            reached_before_cutoff = False
            for item in items:
                testrun = to_testrun(item)
                posted = as_utc(testrun.posted)
                if posted is None:
                    continue
                if until_utc is not None and posted >= until_utc:
                    continue
                if posted < cutoff_utc:
                    reached_before_cutoff = True
                    continue
                collected.append(testrun)

            if reached_before_cutoff or len(items) < page_size:
                break
            page += 1

        collected.sort(
            key=lambda t: as_utc(t.posted) or cutoff_utc,
            reverse=True,
        )
        return cls.from_testruns(collected)

    @classmethod
    def from_records(cls, records: list[dict]) -> TestRunsStats:
        """Build stats from raw run dicts (nightly/builds drill-in)."""
        return cls.from_testruns(
            [to_testrun(raw) for raw in records if isinstance(raw, dict)]
        )

    @property
    def distinct_status_count(self) -> int:
        return len({t.status for t in self.testruns if t.status})

    @cached_property
    def testrun_names(self) -> list[str]:
        """Names of the loaded testruns."""
        return [t.name for t in self.testruns]

    @cached_property
    def completed_testruns(self) -> list[TestRun]:
        return [t for t in self.testruns if t.is_completed]

    @cached_property
    def active_testruns(self) -> list[TestRun]:
        """Testruns that are still running, queued, or waiting."""
        return [t for t in self.testruns if t.is_active]

    def ranked_active_testruns(self) -> list[TestRun]:
        """Active testruns oldest-first (missing ``posted`` sorts last)."""
        aware_max = datetime.max.replace(tzinfo=timezone.utc)
        return sorted(
            self.active_testruns,
            key=lambda t: as_utc(t.posted) or aware_max,
        )

    def stuck_testruns(
        self,
        *,
        older_than: timedelta,
        now: datetime | None = None,
    ) -> list[TestRun]:
        """Active testruns whose ``posted`` time is at least ``older_than`` ago."""
        ref = as_utc(now) or datetime.now(timezone.utc)
        cutoff = ref - older_than
        stuck: list[TestRun] = []
        for testrun in self.active_testruns:
            posted = as_utc(testrun.posted)
            if posted is not None and posted <= cutoff:
                stuck.append(testrun)
        return stuck

    def for_branch(self, branch: str) -> TestRunsStats:
        """Restrict to testruns on ``branch`` (empty branch returns self)."""
        if not branch:
            return self
        return TestRunsStats.from_testruns(self.filtered(branch=branch))

    def for_suites(self, suites: list[str] | tuple[str, ...] | set[str]) -> TestRunsStats:
        """Restrict to testruns whose suite is in ``suites``."""
        wanted = {suite for suite in suites if suite}
        if not wanted:
            return TestRunsStats.from_testruns([])
        return TestRunsStats.from_testruns(
            [run for run in self.testruns if run.suite in wanted]
        )

    def for_suite(self, suite: str) -> TestRunsStats:
        """Restrict to testruns in ``suite`` (empty suite returns self)."""
        if not suite:
            return self
        return self.for_suites([suite])

    def for_branches(
        self, branches: list[str] | tuple[str, ...] | set[str]
    ) -> TestRunsStats:
        """Restrict to testruns whose branch is in ``branches``."""
        wanted = {branch for branch in branches if branch}
        if not wanted:
            return TestRunsStats.from_testruns([])
        return TestRunsStats.from_testruns(
            [run for run in self.testruns if run.branch in wanted]
        )

    def for_machine_type(self, machine_type: str) -> TestRunsStats:
        """Restrict to testruns on ``machine_type`` (case-insensitive)."""
        wanted = (machine_type or "").strip().lower()
        if not wanted:
            return self
        return TestRunsStats.from_testruns(
            [
                run
                for run in self.testruns
                if (run.machine_type or "").strip().lower() == wanted
            ]
        )

    def for_sha(self, sha: str) -> TestRunsStats:
        """Restrict to testruns whose SHA matches ``sha`` (prefix-safe)."""
        if not sha:
            return self
        return TestRunsStats.from_testruns(
            [run for run in self.testruns if sha_matches(run.sha_id, sha)]
        )

    def posted_since(self, cutoff: datetime) -> TestRunsStats:
        """Keep testruns whose ``posted`` time is at or after ``cutoff``."""
        cutoff_utc = as_utc(cutoff)
        if cutoff_utc is None:
            return self
        rows = []
        for testrun in self.testruns:
            posted = as_utc(testrun.posted)
            if posted is not None and posted >= cutoff_utc:
                rows.append(testrun)
        return TestRunsStats.from_testruns(rows)

    def records_for_names(self, names: list[str]) -> list[dict]:
        """Serialize matching testruns for jobs/testruns drill-in."""
        wanted = set(names)
        return [
            as_run_record(testrun)
            for testrun in self.testruns
            if testrun.name in wanted
        ]

    def cluster_health(
        self,
        jobs: JobsStats,
        *,
        now: datetime | None = None,
    ) -> ClusterHealthSnapshot:
        """Badge, completed mix, and supporting context for the overview card."""
        all_jobs = jobs.summary
        completed = jobs.completed_summary
        inflight = all_jobs.cnt_running + all_jobs.cnt_waiting + all_jobs.cnt_queued
        if completed.cnt_jobs:
            badge, reasons = health_assessment(
                round(completed.pct_pass, 1),
                round(completed.pct_dead, 1),
            )
        else:
            badge, reasons = "Unknown", ["No completed jobs in this window."]

        top = jobs.top_10_failure_reasons[:1]
        worst = next((row for row in jobs.branch_summaries if row.pct_fail), None)
        machines = {
            job.machine_type for job in jobs.jobs if job.machine_type
        }
        return ClusterHealthSnapshot(
            badge=badge,
            reasons=reasons,
            completed=completed,
            cnt_testruns=len(self.testruns),
            cnt_completed_runs=len(self.completed_testruns),
            cnt_active_runs=len(self.active_testruns),
            cnt_jobs=all_jobs.cnt_jobs,
            cnt_inflight=inflight,
            cnt_running=all_jobs.cnt_running,
            cnt_waiting=all_jobs.cnt_waiting,
            cnt_queued=all_jobs.cnt_queued,
            pct_completed=round(pct(completed.cnt_jobs, all_jobs.cnt_jobs), 1),
            cnt_not_passed=completed.cnt_fail + completed.cnt_dead,
            pct_not_passed=round(
                pct(completed.cnt_fail + completed.cnt_dead, completed.cnt_jobs),
                1,
            ),
            cnt_branches=len({run.branch for run in self.testruns if run.branch}),
            cnt_suites=len({run.suite for run in self.testruns if run.suite}),
            cnt_machines=len(machines),
            avg_duration=format_duration(jobs.completed_stats.avg_duration),
            top_failure=top[0].reason if top else "",
            top_failure_count=top[0].count if top else 0,
            stuck_6h=len(
                self.stuck_testruns(
                    older_than=timedelta(hours=DEFAULT_HEALTH_STUCK_HOURS),
                    now=now,
                )
            ),
            stuck_24h=len(
                self.stuck_testruns(
                    older_than=timedelta(hours=DEFAULT_HEALTH_STUCK_HOURS_LONG),
                    now=now,
                )
            ),
            worst_branch=worst.branch if worst else "",
            worst_branch_fail_pct=worst.pct_fail if worst else 0.0,
        )

    def active_summary(
        self,
        now: datetime | None = None,
    ) -> ActiveRunsSummary:
        """Active testruns plus running/waiting/queued job counts."""
        active = self.active_testruns
        cnt_running = sum(t.results.running for t in active)
        cnt_waiting = sum(t.results.waiting for t in active)
        cnt_queued = sum(t.results.queued for t in active)
        posted_times = [as_utc(t.posted) for t in active if t.posted]
        oldest = min(posted_times) if posted_times else None
        return ActiveRunsSummary(
            cnt_testruns=len(active),
            cnt_jobs=cnt_running + cnt_waiting + cnt_queued,
            cnt_running=cnt_running,
            cnt_waiting=cnt_waiting,
            cnt_queued=cnt_queued,
            oldest_age=format_age(oldest, now),
        )

    def filtered(
        self,
        *,
        date_start: date | datetime | None = None,
        date_end: date | datetime | None = None,
        on: str = "posted",
        user: str | None = None,
        branch: str | None = None,
        suite: str | None = None,
        scheduled_only: bool = False,
        statuses: set[str] | None = None,
    ) -> list[TestRun]:
        """Filter loaded testruns in memory (does not re-fetch)."""
        start = as_date(date_start)
        end = as_date(date_end)
        rows = self.testruns
        if scheduled_only:
            rows = [t for t in rows if t.scheduled is not None]
        if user is not None:
            rows = [t for t in rows if t.user == user]
        if branch is not None:
            rows = [t for t in rows if t.branch == branch]
        if suite is not None:
            rows = [t for t in rows if t.suite == suite]
        if statuses is not None:
            rows = [t for t in rows if t.status in statuses]

        if start is not None or end is not None:
            filtered_rows: list[TestRun] = []
            for t in rows:
                allowed = (
                    "posted",
                    "scheduled",
                    "started",
                    "updated",
                )
                if on in allowed:
                    ts = getattr(t, on, None)
                else:
                    ts = t.posted
                if ts is None:
                    continue
                day = ts.date() if isinstance(ts, datetime) else ts
                if start is not None and day < start:
                    continue
                if end is not None and day > end:
                    continue
                filtered_rows.append(t)
            rows = filtered_rows
        return rows

    @cached_property
    def summary(self) -> TestRunsSummary:
        """Aggregate pass/fail/dead counts for the loaded testruns."""
        summary = TestRunsSummary()
        summary.cnt_testruns = len(self.testruns)
        for t in self.testruns:
            r = t.results
            summary.cnt_jobs += r.total
            summary.cnt_pass += r.pass_
            summary.cnt_fail += r.fail
            summary.cnt_dead += r.dead
            summary.cnt_running += r.running
            summary.cnt_waiting += r.waiting
            summary.cnt_queued += r.queued

        total = summary.cnt_jobs
        if total:
            summary.pct_pass = pct(summary.cnt_pass, total)
            summary.pct_fail = pct(summary.cnt_fail, total)
            summary.pct_dead = pct(summary.cnt_dead, total)
            summary.pct_running = pct(summary.cnt_running, total)
            summary.pct_waiting = pct(summary.cnt_waiting, total)
            summary.pct_queued = pct(summary.cnt_queued, total)
        return summary

    @cached_property
    def summary_by_branch(self) -> list[BranchSummary]:
        """Per-branch run counts and embedded job result totals."""
        by_branch: dict[str, list[TestRun]] = defaultdict(list)
        for t in self.testruns:
            by_branch[t.branch or "unknown"].append(t)

        rows: list[BranchSummary] = []
        for branch, runs in by_branch.items():
            results = Results()
            for t in runs:
                r = t.results
                results.pass_ += r.pass_
                results.fail += r.fail
                results.dead += r.dead
                results.running += r.running
                results.waiting += r.waiting
                results.queued += r.queued
            cnt_jobs = results.total
            cnt_pass = results.pass_
            cnt_fail = results.failed
            rows.append(
                BranchSummary(
                    branch=branch,
                    cnt_runs=len(runs),
                    cnt_jobs=cnt_jobs,
                    cnt_pass=cnt_pass,
                    cnt_fail=cnt_fail,
                    pct_pass=round(pct(cnt_pass, cnt_jobs), 1),
                    pct_fail=round(pct(cnt_fail, cnt_jobs), 1),
                )
            )
        return sorted(rows, key=lambda r: r.pct_fail, reverse=True)
