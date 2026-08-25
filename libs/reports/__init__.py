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
    ActiveRunsSummary,
    BranchSummary,
    ClusterHealthSnapshot,
    DailyStatusPct,
    DailyTrend,
    DimensionStatusTrend,
    FailedRunStat,
    FailedTestRunStat,
    FailureReasonStat,
    FailingTestStat,
    FlakyTestStat,
    GroupReliabilityStat,
    Job,
    JobsSummary,
    NightlyRunSummary,
    OsSummary,
    PassRateCell,
    Results,
    ShaSummary,
    StatusShareTrend,
    SuiteTrend,
    TestRun,
    TestRunsSummary,
)

__all__ = [
    "ActiveRunsSummary",
    "BranchSummary",
    "ClusterHealthSnapshot",
    "DailyStatusPct",
    "DailyTrend",
    "DataSource",
    "DimensionStatusTrend",
    "FailedRunStat",
    "FailedTestRunStat",
    "FailureReasonStat",
    "FailingTestStat",
    "FlakyTestStat",
    "GroupReliabilityStat",
    "Job",
    "JobsSummary",
    "NightlyRunSummary",
    "OsSummary",
    "PassRateCell",
    "Results",
    "ShaSummary",
    "StatusShareTrend",
    "SuiteTrend",
    "TestRun",
    "TestRunsSummary",
]
