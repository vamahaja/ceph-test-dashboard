from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from functools import cached_property

from libs.reports import DataSource
from libs.reports.models import (
    BranchSummary,
    DailyTrend,
    FailedTestRunStat,
    NightlyRunSummary,
    Results,
    ShaSummary,
    SuiteTrend,
    TestRun,
    TestRunsSummary,
)
from libs.reports.parsing import as_run_list, to_failed_stat, to_testrun
from libs.reports.utils import as_date, parse_iso_date, pct

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
    count: int = 100
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

    @cached_property
    def testrun(self) -> TestRun | None:
        """Return the first (or only) testrun, if any."""
        return self.testruns[0] if self.testruns else None

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

    @cached_property
    def alerting_testruns(self) -> list[TestRun]:
        """Nightly-style alerting set: fail/dead/queued/running."""
        return [t for t in self.testruns if t.is_alerting]

    @cached_property
    def nightly_testruns(self) -> list[TestRun]:
        """Runs that have a scheduled timestamp (nightly candidates)."""
        return [t for t in self.testruns if t.scheduled is not None]

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

    def nightly_scoped(self, user: str) -> list[TestRun]:
        """Nightly report scope: ``user`` + scheduled timestamp present."""
        return self.filtered(user=user, scheduled_only=True)

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
    def nightly_summary(self) -> NightlyRunSummary:
        """KPI bundle matching the nightly report scorecard."""
        runs = self.nightly_testruns or self.testruns
        cnt_runs = len(runs)
        cnt_alerting = sum(1 for t in runs if t.is_alerting)
        cnt_completed = sum(1 for t in runs if t.is_completed)
        cnt_pass = sum(1 for t in runs if t.status == "pass")
        return NightlyRunSummary(
            cnt_runs=cnt_runs,
            cnt_alerting=cnt_alerting,
            cnt_completed=cnt_completed,
            cnt_pass=cnt_pass,
            pct_runs_passed=round(pct(cnt_pass, cnt_runs), 1),
        )

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

    @cached_property
    def sha_summaries(self) -> list[ShaSummary]:
        """Per-SHA run counts and embedded job result totals."""
        by_sha: dict[str, list[TestRun]] = defaultdict(list)
        for t in self.testruns:
            by_sha[t.sha_id or "unknown"].append(t)

        rows: list[ShaSummary] = []
        for sha, runs in by_sha.items():
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
                ShaSummary(
                    sha1=sha,
                    sha_short=sha[:8],
                    cnt_runs=len(runs),
                    cnt_jobs=cnt_jobs,
                    cnt_pass=cnt_pass,
                    cnt_fail=cnt_fail,
                    pct_pass=round(pct(cnt_pass, cnt_jobs), 1),
                )
            )
        return sorted(rows, key=lambda r: r.pct_pass)

    @cached_property
    def top_10_failed_testruns(self) -> list[FailedTestRunStat]:
        """Top 10 testruns ranked by failure percentage (fail+dead)."""
        ranked = sorted(
            self.testruns,
            key=lambda t: t.fail_pct,
            reverse=True,
        )[:10]
        return [to_failed_stat(t) for t in ranked]

    @cached_property
    def trends_by_suite(self) -> list[SuiteTrend]:
        """Pass/fail aggregates grouped by suite."""
        by_suite: dict[str, Results] = {}
        for t in self.testruns:
            suite = t.suite or "unknown"
            if suite not in by_suite:
                by_suite[suite] = Results()
            by_suite[suite].pass_ += t.results.pass_
            by_suite[suite].fail += t.results.fail
            by_suite[suite].dead += t.results.dead
            by_suite[suite].running += t.results.running
            by_suite[suite].waiting += t.results.waiting
            by_suite[suite].queued += t.results.queued
        return [
            SuiteTrend(suite=suite, results=results)
            for suite, results in by_suite.items()
        ]

    def _daily_trends(self, *, on: str) -> list[DailyTrend]:
        by_day: dict[date, Results] = {}
        for t in self.testruns:
            ts = getattr(t, on, None)
            if ts is None:
                continue
            day = ts.date() if isinstance(ts, datetime) else ts
            if day not in by_day:
                by_day[day] = Results()
            by_day[day].pass_ += t.results.pass_
            by_day[day].fail += t.results.fail
            by_day[day].dead += t.results.dead
            by_day[day].running += t.results.running
            by_day[day].waiting += t.results.waiting
            by_day[day].queued += t.results.queued
        return [
            DailyTrend(day=day, results=results)
            for day, results in sorted(
                by_day.items(),
                key=lambda item: item[0],
            )
        ]

    @cached_property
    def daily_trends(self) -> list[DailyTrend]:
        """Pass/fail aggregates grouped by started date."""
        return self._daily_trends(on="started")

    @cached_property
    def daily_trends_by_posted(self) -> list[DailyTrend]:
        """Pass/fail aggregates by posted date (UI charts)."""
        return self._daily_trends(on="posted")
