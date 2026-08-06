from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from functools import cached_property

from libs.reports import DataSource
from libs.reports.models import (
    BranchSummary,
    DailyStatusPct,
    DailyTrend,
    DimensionStatusTrend,
    FailedRunStat,
    FailureReasonStat,
    FlakyTestStat,
    GroupReliabilityStat,
    Job,
    JobsSummary,
    OsSummary,
    PassRateCell,
    Results,
    ShaSummary,
    SuiteTrend,
)
from libs.reports.parsing import as_job_list, to_job
from libs.reports.utils import pct

_COMPLETED = frozenset({"pass", "fail", "dead"})
_FAILING = frozenset({"fail", "dead"})

# Infra / machine-error reasons commonly used on the hardware report.
_DEFAULT_MACHINE_ERROR_RE = re.compile(
    r"(ssh|connection|timeout|node|machine|hardware|oom|kernel|reboot|power)",
    re.IGNORECASE,
)

def _fill_jobs_summary(jobs: list[Job]) -> JobsSummary:
    summary = JobsSummary(cnt_jobs=len(jobs))
    for j in jobs:
        if j.status == "dead":
            summary.cnt_dead += 1
        elif j.status == "running":
            summary.cnt_running += 1
        elif j.status == "waiting":
            summary.cnt_waiting += 1
        elif j.status == "queued":
            summary.cnt_queued += 1
        elif j.success or j.status == "pass":
            summary.cnt_pass += 1
        else:
            summary.cnt_fail += 1

    total = summary.cnt_jobs
    if total:
        summary.pct_pass = pct(summary.cnt_pass, total)
        summary.pct_fail = pct(summary.cnt_fail, total)
        summary.pct_dead = pct(summary.cnt_dead, total)
        summary.pct_running = pct(summary.cnt_running, total)
        summary.pct_waiting = pct(summary.cnt_waiting, total)
        summary.pct_queued = pct(summary.cnt_queued, total)
    return summary

def _attr_for_dimension(job: Job, dimension: str) -> str:
    mapping = {
        "suite": job.suite,
        "branch": job.branch,
        "os_type": job.os_type,
        "os": job.os_type,
        "machine_type": job.machine_type,
        "status": job.status,
        "run_name": job.run_name,
        "sha1": job.sha1,
        "sha_short": job.sha_short,
        "description": job.description,
    }
    return (mapping.get(dimension) or "unknown") or "unknown"

@dataclass
class JobsStats(DataSource):
    count: int = 100
    branch: str = ""
    suite: str = ""
    sha1: str = ""
    os_type: str = ""
    user: str = ""
    machine_type: str = ""
    status: str = ""
    run_name: str = ""
    jobs: list[Job] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        DataSource.__init__(self)
        # Call Paddles.jobs via the base class — the dataclass field ``jobs``
        # would otherwise shadow the API method on ``self``.
        if self.run_name:
            raw_jobs = DataSource.jobs_for_run(self, self.run_name)
        else:
            raw_jobs = DataSource.jobs(
                self,
                count=self.count,
                branch=self.branch or None,
                suite=self.suite or None,
                sha1=self.sha1 or None,
                os_type=self.os_type or None,
                user=self.user or None,
                machine_type=self.machine_type or None,
                status=self.status or None,
            )
        self.jobs = [to_job(raw) for raw in as_job_list(raw_jobs)]

    @classmethod
    def for_run(cls, run_name: str) -> JobsStats:
        """Load all jobs for a single testrun."""
        return cls(run_name=run_name)

    @classmethod
    def for_job(cls, run_name: str, job_id: str) -> Job | None:
        """Load one job by testrun name and job id."""
        raw = DataSource().job(run_name=run_name, job_id=str(job_id))
        jobs = as_job_list(raw)
        return to_job(jobs[0]) if jobs else None

    @classmethod
    def from_jobs(cls, jobs: list[Job]) -> JobsStats:
        """Build stats from an already-loaded job list (no API fetch)."""
        obj = cls.__new__(cls)
        DataSource.__init__(obj)
        obj.count = len(jobs)
        obj.branch = ""
        obj.suite = ""
        obj.sha1 = ""
        obj.os_type = ""
        obj.user = ""
        obj.machine_type = ""
        obj.status = ""
        obj.run_name = ""
        obj.jobs = list(jobs)
        return obj

    def filtered(
        self,
        *,
        date_start: date | datetime | None = None,
        date_end: date | datetime | None = None,
    ) -> list[Job]:
        """Filter loaded jobs by ``posted`` date (inclusive)."""
        start = (
            date_start.date()
            if isinstance(date_start, datetime)
            else date_start
        )
        end = date_end.date() if isinstance(date_end, datetime) else date_end
        if start is None and end is None:
            return list(self.jobs)

        rows: list[Job] = []
        for job in self.jobs:
            if job.posted is None:
                continue
            day = job.posted.date()
            if start is not None and day < start:
                continue
            if end is not None and day > end:
                continue
            rows.append(job)
        return rows

    @cached_property
    def completed_jobs(self) -> list[Job]:
        return [j for j in self.jobs if j.status in _COMPLETED]

    @cached_property
    def failing_jobs(self) -> list[Job]:
        return [j for j in self.jobs if j.status in _FAILING]

    @cached_property
    def summary(self) -> JobsSummary:
        """Aggregate pass/fail/dead counts for the loaded jobs."""
        return _fill_jobs_summary(self.jobs)

    @cached_property
    def completed_summary(self) -> JobsSummary:
        """Summary restricted to completed (pass/fail/dead) jobs."""
        return _fill_jobs_summary(self.completed_jobs)

    @cached_property
    def pass_rate(self) -> float:
        """Pass % among completed jobs (fail+dead treated as not passed)."""
        completed = self.completed_jobs
        if not completed:
            return 0.0
        passed = sum(1 for j in completed if j.status == "pass")
        return pct(passed, len(completed))

    @cached_property
    def fail_rate(self) -> float:
        """Fail+dead % among completed jobs."""
        completed = self.completed_jobs
        if not completed:
            return 0.0
        failed = sum(1 for j in completed if j.status in _FAILING)
        return pct(failed, len(completed))

    @cached_property
    def avg_duration(self) -> float:
        """Mean job duration in seconds (jobs with duration > 0)."""
        durations = [j.duration for j in self.jobs if j.duration]
        if not durations:
            return 0.0
        return sum(durations) / len(durations)

    @cached_property
    def os_summary(self) -> list[OsSummary]:
        """Job outcomes grouped by OS type (status-based counts)."""
        by_os: dict[str, OsSummary] = {}
        for j in self.jobs:
            os_type = j.os_type or "unknown"
            if os_type not in by_os:
                by_os[os_type] = OsSummary(os_type=os_type)
            summary = by_os[os_type]
            summary.cnt_jobs += 1
            if j.status == "dead":
                summary.cnt_dead += 1
            elif j.status == "running":
                summary.cnt_running += 1
            elif j.status == "waiting":
                summary.cnt_waiting += 1
            elif j.status == "queued":
                summary.cnt_queued += 1
            elif j.success or j.status == "pass":
                summary.cnt_pass += 1
            else:
                summary.cnt_fail += 1

        for summary in by_os.values():
            cnt = summary.cnt_jobs
            if not cnt:
                continue
            summary.pct_pass = pct(summary.cnt_pass, cnt)
            summary.pct_fail = pct(summary.cnt_fail, cnt)
            summary.pct_dead = pct(summary.cnt_dead, cnt)
            summary.pct_running = pct(summary.cnt_running, cnt)
            summary.pct_waiting = pct(summary.cnt_waiting, cnt)
            summary.pct_queued = pct(summary.cnt_queued, cnt)

        return list(by_os.values())

    def status_by(self, dimension: str) -> list[DimensionStatusTrend]:
        """Status aggregates for a job field (suite/branch/os_type/…)."""
        by_key: dict[str, Results] = {}
        for j in self.jobs:
            key = _attr_for_dimension(j, dimension)
            if key not in by_key:
                by_key[key] = Results()
            by_key[key].bump(j.status, success=j.success)
        return [
            DimensionStatusTrend(
                dimension=dimension,
                key=key,
                results=results,
            )
            for key, results in by_key.items()
        ]

    @cached_property
    def trends_by_suite(self) -> list[SuiteTrend]:
        return [
            SuiteTrend(suite=row.key, results=row.results)
            for row in self.status_by("suite")
        ]

    @cached_property
    def trends_by_branch(self) -> list[DimensionStatusTrend]:
        return self.status_by("branch")

    @cached_property
    def trends_by_os(self) -> list[DimensionStatusTrend]:
        return self.status_by("os_type")

    @cached_property
    def daily_trends(self) -> list[DailyTrend]:
        """Pass/fail aggregates grouped by job ``posted`` date."""
        by_day: dict[date, Results] = {}
        for j in self.jobs:
            if j.posted is None:
                continue
            day = j.posted.date()
            if day not in by_day:
                by_day[day] = Results()
            by_day[day].bump(j.status, success=j.success)
        return [
            DailyTrend(day=day, results=results)
            for day, results in sorted(
                by_day.items(),
                key=lambda item: item[0],
            )
        ]

    def daily_status_pct(
        self,
        *,
        dead_as_fail: bool = True,
    ) -> list[DailyStatusPct]:
        """Per-day status %; optionally fold dead into fail."""
        rows: list[DailyStatusPct] = []
        for trend in self.daily_trends:
            r = trend.results
            total = r.total
            fail = r.fail + r.dead if dead_as_fail else r.fail
            dead = 0 if dead_as_fail else r.dead
            rows.append(
                DailyStatusPct(
                    day=trend.day,
                    cnt_jobs=total,
                    pct_pass=pct(r.pass_, total),
                    pct_fail=pct(fail, total),
                    pct_dead=pct(dead, total),
                    pct_running=pct(r.running, total),
                    pct_queued=pct(r.queued, total),
                    pct_waiting=pct(r.waiting, total),
                )
            )
        return rows

    @cached_property
    def branch_summaries(self) -> list[BranchSummary]:
        """Per-branch job reliability (completed jobs; fail includes dead)."""
        by_branch: dict[str, list[Job]] = defaultdict(list)
        for j in self.completed_jobs:
            by_branch[j.branch or "unknown"].append(j)

        rows: list[BranchSummary] = []
        for branch, jobs in by_branch.items():
            cnt_jobs = len(jobs)
            cnt_pass = sum(1 for j in jobs if j.status == "pass")
            cnt_fail = sum(1 for j in jobs if j.status in _FAILING)
            durations = [j.duration for j in jobs if j.duration]
            run_names = {j.run_name for j in jobs if j.run_name}
            rows.append(
                BranchSummary(
                    branch=branch,
                    cnt_runs=len(run_names),
                    cnt_jobs=cnt_jobs,
                    cnt_pass=cnt_pass,
                    cnt_fail=cnt_fail,
                    pct_pass=round(pct(cnt_pass, cnt_jobs), 1),
                    pct_fail=round(pct(cnt_fail, cnt_jobs), 1),
                    avg_duration=(
                        (sum(durations) / len(durations))
                        if durations
                        else 0.0
                    ),
                )
            )
        return sorted(rows, key=lambda r: r.pct_fail, reverse=True)

    @cached_property
    def sha_summaries(self) -> list[ShaSummary]:
        """Per-SHA job health (completed jobs)."""
        by_sha: dict[str, list[Job]] = defaultdict(list)
        for j in self.completed_jobs:
            sha = j.sha1 or "unknown"
            by_sha[sha].append(j)

        rows: list[ShaSummary] = []
        for sha, jobs in by_sha.items():
            cnt_jobs = len(jobs)
            cnt_pass = sum(1 for j in jobs if j.status == "pass")
            cnt_fail = sum(1 for j in jobs if j.status in _FAILING)
            run_names = {j.run_name for j in jobs if j.run_name}
            rows.append(
                ShaSummary(
                    sha1=sha,
                    sha_short=sha[:8],
                    cnt_runs=len(run_names),
                    cnt_jobs=cnt_jobs,
                    cnt_pass=cnt_pass,
                    cnt_fail=cnt_fail,
                    pct_pass=round(pct(cnt_pass, cnt_jobs), 1),
                )
            )
        return sorted(rows, key=lambda r: r.pct_pass)

    def top_failure_reasons(self, n: int = 10) -> list[FailureReasonStat]:
        """Top failure reasons with run/branch/suite/test impact counts."""
        failing = self.failing_jobs
        if not failing:
            return []

        by_reason: dict[str, list[Job]] = defaultdict(list)
        for j in failing:
            reason = j.failure_reason or "Unknown failure"
            by_reason[reason].append(j)

        total_failing = len(failing)
        ranked = sorted(
            by_reason.items(),
            key=lambda item: len(item[1]),
            reverse=True,
        )[:n]
        return [
            FailureReasonStat(
                reason=reason,
                count=len(jobs),
                pct=round(pct(len(jobs), total_failing), 1),
                runs_impacted=len(
                    {j.run_name for j in jobs if j.run_name}
                ),
                branches_impacted=len(
                    {j.branch for j in jobs if j.branch}
                ),
                suites_impacted=len(
                    {j.suite for j in jobs if j.suite}
                ),
                tests_impacted=len(
                    {j.description for j in jobs if j.description}
                ),
            )
            for reason, jobs in ranked
        ]

    @cached_property
    def top_10_failure_reasons(self) -> list[FailureReasonStat]:
        """Top 10 failure reasons ranked by occurrence."""
        return self.top_failure_reasons(10)

    @cached_property
    def top_failed_runs(self) -> list[FailedRunStat]:
        """Top 10 runs by failed job count (among completed jobs)."""
        completed = self.completed_jobs
        if not completed:
            return []

        totals: dict[str, int] = defaultdict(int)
        failed: dict[str, int] = defaultdict(int)
        suite_for: dict[str, str] = {}
        for j in completed:
            run = j.run_name or "unknown"
            totals[run] += 1
            if j.status in _FAILING:
                failed[run] += 1
                suite_for.setdefault(run, j.suite or "")

        rows = [
            FailedRunStat(
                run_name=run,
                suite=suite_for.get(run, ""),
                failed_jobs=failed_jobs,
                total_jobs=totals[run],
                fail_pct=round(pct(failed_jobs, totals[run]), 1),
            )
            for run, failed_jobs in failed.items()
        ]
        rows.sort(
            key=lambda r: (r.failed_jobs, r.fail_pct, r.run_name),
            reverse=True,
        )
        return rows[:10]

    def pass_matrix(
        self,
        *,
        row: str = "branch",
        col: str = "os_type",
    ) -> list[PassRateCell]:
        """Pass-rate cells for heatmap charts (default branch × OS)."""
        buckets: dict[tuple[str, str], list[Job]] = defaultdict(list)
        for j in self.completed_jobs:
            rkey = _attr_for_dimension(j, row)
            ckey = _attr_for_dimension(j, col)
            buckets[(rkey, ckey)].append(j)

        cells: list[PassRateCell] = []
        for (rkey, ckey), jobs in buckets.items():
            cnt_jobs = len(jobs)
            cnt_pass = sum(1 for j in jobs if j.status == "pass")
            cnt_fail = sum(1 for j in jobs if j.status in _FAILING)
            cell = PassRateCell(
                cnt_jobs=cnt_jobs,
                cnt_pass=cnt_pass,
                cnt_fail=cnt_fail,
                pct_pass=round(pct(cnt_pass, cnt_jobs), 1),
            )
            if row == "branch":
                cell.branch = rkey
            elif row in ("os_type", "os"):
                cell.os_type = rkey
            elif row == "machine_type":
                cell.machine_type = rkey

            if col in ("os_type", "os"):
                cell.os_type = ckey
            elif col == "machine_type":
                cell.machine_type = ckey
            elif col == "branch":
                cell.branch = ckey
            cells.append(cell)
        return cells

    @cached_property
    def coverage_detail(self) -> list[PassRateCell]:
        """Coverage detail rows: branch × os_type × machine_type."""
        buckets: dict[tuple[str, str, str], list[Job]] = defaultdict(list)
        for j in self.completed_jobs:
            branch = j.branch or "unknown"
            os_type = j.os_type or "unknown"
            machine = j.machine_type or "unknown"
            buckets[(branch, os_type, machine)].append(j)

        rows: list[PassRateCell] = []
        for (branch, os_type, machine), jobs in buckets.items():
            cnt_jobs = len(jobs)
            cnt_pass = sum(1 for j in jobs if j.status == "pass")
            cnt_fail = sum(1 for j in jobs if j.status in _FAILING)
            rows.append(
                PassRateCell(
                    branch=branch,
                    os_type=os_type,
                    machine_type=machine,
                    cnt_jobs=cnt_jobs,
                    cnt_pass=cnt_pass,
                    cnt_fail=cnt_fail,
                    pct_pass=round(pct(cnt_pass, cnt_jobs), 1),
                )
            )
        return sorted(rows, key=lambda r: (r.pct_pass, r.branch))

    def reliability_by(self, group: str) -> list[GroupReliabilityStat]:
        """Hardware-style reliability table for a job field."""
        buckets: dict[str, list[Job]] = defaultdict(list)
        for j in self.completed_jobs:
            buckets[_attr_for_dimension(j, group)].append(j)

        rows: list[GroupReliabilityStat] = []
        for key, jobs in buckets.items():
            cnt_jobs = len(jobs)
            cnt_pass = sum(1 for j in jobs if j.status == "pass")
            cnt_fail = sum(1 for j in jobs if j.status in _FAILING)
            durations = [j.duration for j in jobs if j.duration]
            rows.append(
                GroupReliabilityStat(
                    key=key,
                    cnt_jobs=cnt_jobs,
                    cnt_pass=cnt_pass,
                    cnt_fail=cnt_fail,
                    pct_pass=round(pct(cnt_pass, cnt_jobs), 1),
                    pct_fail=round(pct(cnt_fail, cnt_jobs), 1),
                    avg_duration=(
                        (sum(durations) / len(durations))
                        if durations
                        else 0.0
                    ),
                )
            )
        return sorted(rows, key=lambda r: r.pct_fail, reverse=True)

    def failing_tests_by_branch(self) -> list[dict]:
        """Pivot-friendly rows: description × branch fail counts."""
        counts: dict[tuple[str, str], int] = defaultdict(int)
        for j in self.failing_jobs:
            desc = j.description or "unknown"
            branch = j.branch or "unknown"
            counts[(desc, branch)] += 1
        return [
            {"description": desc, "branch": branch, "failed_jobs": count}
            for (desc, branch), count in sorted(
                counts.items(),
                key=lambda item: item[1],
                reverse=True,
            )
        ]

    def flaky_tests(self, min_executions: int = 3) -> list[FlakyTestStat]:
        """Flakiness scores keyed by job description (coverage report)."""
        by_desc: dict[str, list[Job]] = defaultdict(list)
        for j in self.jobs:
            if not j.description:
                continue
            by_desc[j.description].append(j)

        rows: list[FlakyTestStat] = []
        for description, jobs in by_desc.items():
            if len(jobs) < min_executions:
                continue

            passed = sum(1 for j in jobs if j.status == "pass")
            failed = sum(1 for j in jobs if j.status in _FAILING)
            total = len(jobs)

            unique_failures = len({
                j.failure_reason
                for j in jobs
                if j.status in _FAILING and j.failure_reason
            })

            sha_statuses: dict[str, set[str]] = defaultdict(set)
            for j in jobs:
                sha_statuses[j.sha1 or "unknown"].add(j.status)
            same_sha_flaky = sum(
                1
                for statuses in sha_statuses.values()
                if ("pass" in statuses) and (statuses & _FAILING)
            )

            branch_pass: dict[str, bool] = defaultdict(bool)
            branch_fail: dict[str, bool] = defaultdict(bool)
            for j in jobs:
                branch = j.branch or "unknown"
                if j.status == "pass":
                    branch_pass[branch] = True
                if j.status in _FAILING:
                    branch_fail[branch] = True
            branch_mixed = sum(
                1
                for branch in set(branch_pass) | set(branch_fail)
                if branch_pass[branch] and branch_fail[branch]
            )

            has_mixed = passed > 0 and failed > 0
            always_same_failure = (
                passed == 0
                and failed > 0
                and unique_failures <= 1
            )
            if has_mixed:
                score = round(min(passed, failed) / total * 100, 1)
            elif (
                not always_same_failure
                and failed > 0
                and unique_failures > 1
            ):
                score = round(
                    min(unique_failures / total * 100, 100.0),
                    1,
                )
            else:
                score = 0.0

            rows.append(
                FlakyTestStat(
                    description=description,
                    flakiness_score=score,
                    total_runs=total,
                    passed=passed,
                    failed=failed,
                    unique_failures=unique_failures,
                    branches_affected=branch_mixed,
                    same_sha_flaky=same_sha_flaky,
                    total_shas=len(sha_statuses),
                )
            )

        return sorted(rows, key=lambda r: r.flakiness_score, reverse=True)

    def machine_errors(
        self,
        pattern: str | re.Pattern | None = None,
    ) -> list[Job]:
        """Dead jobs matching an infra/hardware failure pattern."""
        regex = pattern or _DEFAULT_MACHINE_ERROR_RE
        if isinstance(regex, str):
            regex = re.compile(regex, re.IGNORECASE)
        return [
            j
            for j in self.jobs
            if j.status == "dead"
            and j.failure_reason
            and regex.search(j.failure_reason)
        ]

    def machine_error_reasons(
        self,
        n: int = 10,
    ) -> list[FailureReasonStat]:
        """Top machine-error failure reasons (hardware report)."""
        errors = JobsStats.from_jobs(self.machine_errors())
        return errors.top_failure_reasons(n)
