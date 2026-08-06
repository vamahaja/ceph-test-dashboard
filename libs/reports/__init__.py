"""Report stats helpers backed by a shared Paddles data source."""

from __future__ import annotations

try:
    from libs.paddle import Paddles as DataSource
except Exception:
    class DataSource:
        """Fallback base when Paddles is unavailable."""

        def __init__(self, *args, **kwargs) -> None:
            pass


from libs.reports.models import (
    BranchSummary,
    DailyStatusPct,
    DailyTrend,
    DimensionStatusTrend,
    FailedRunStat,
    FailedTestRunStat,
    FailureReasonStat,
    FlakyTestStat,
    GroupReliabilityStat,
    Job,
    JobsSummary,
    NightlyRunSummary,
    OsSummary,
    PassRateCell,
    Results,
    ShaSummary,
    SuiteTrend,
    TestRun,
    TestRunsSummary,
)

__all__ = [
    "BranchSummary",
    "DailyStatusPct",
    "DailyTrend",
    "DataSource",
    "DimensionStatusTrend",
    "FailedRunStat",
    "FailedTestRunStat",
    "FailureReasonStat",
    "FlakyTestStat",
    "GroupReliabilityStat",
    "Job",
    "JobsSummary",
    "NightlyRunSummary",
    "OsSummary",
    "PassRateCell",
    "Results",
    "ShaSummary",
    "SuiteTrend",
    "TestRun",
    "TestRunsSummary",
]
