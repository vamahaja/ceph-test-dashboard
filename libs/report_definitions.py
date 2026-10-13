"""Load scheduled mail report definitions from ``templates/reports/*.toml``."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

_REPORTS_DIR = Path(__file__).resolve().parents[1] / "templates" / "reports"


@dataclass(frozen=True)
class ReportDefinition:
    id: str
    enabled: bool
    schedule_day_of_week: str | None
    schedule_hour: int
    schedule_minute: int
    window_kind: str
    window_lookback_days_key: str | None
    branches: str
    suite_filter: str
    suite_match: str
    suite_names: tuple[str, ...]
    send_when: str
    dedupe: str
    fetch_jobs: bool
    fetch_days_key: str
    show_summary_stats: bool
    title_template: str
    subject_template: str
    runs_heading: str
    badge_override: str | None

    def format_title(self, **fields: object) -> str:
        return self.title_template.format(**fields)

    def format_subject(self, **fields: object) -> str:
        return self.subject_template.format(**fields)


def _parse_report(data: dict[str, Any]) -> ReportDefinition:
    schedule = data.get("schedule") or {}
    window = data.get("window") or {}
    scope = data.get("scope") or {}
    send = data.get("send") or {}
    email = data.get("email") or {}
    names_raw = scope.get("suite_names") or scope.get("names") or []
    if isinstance(names_raw, str):
        names = tuple(n.strip() for n in names_raw.split(",") if n.strip())
    else:
        names = tuple(str(n).strip() for n in names_raw if str(n).strip())
    return ReportDefinition(
        id=str(data["id"]),
        enabled=bool(data.get("enabled", True)),
        schedule_day_of_week=schedule.get("day_of_week"),
        schedule_hour=int(schedule.get("hour", 0)),
        schedule_minute=int(schedule.get("minute", 0)),
        window_kind=str(window.get("kind", "weekly")),
        window_lookback_days_key=window.get("lookback_days_key"),
        branches=str(scope.get("branches", "release")),
        suite_filter=str(scope.get("suite_filter", "all")),
        suite_match=str(scope.get("suite_match") or ""),
        suite_names=names,
        send_when=str(send.get("when", "always")),
        dedupe=str(send.get("dedupe", "weekly_window")),
        fetch_jobs=bool(send.get("fetch_jobs", True)),
        fetch_days_key=str(send.get("fetch_days_key", "weekly_fetch_days")),
        show_summary_stats=bool(email.get("show_summary_stats", True)),
        title_template=str(email.get("title", "Nightly report — {branch}")),
        subject_template=str(
            email.get("subject", "[ceph nightly] {branch} — {badge}")
        ),
        runs_heading=str(email.get("runs_heading", "Failing runs")),
        badge_override=email.get("badge"),
    )


@lru_cache(maxsize=1)
def load_report_definitions() -> tuple[ReportDefinition, ...]:
    if not _REPORTS_DIR.is_dir():
        return ()
    reports: list[ReportDefinition] = []
    for path in sorted(_REPORTS_DIR.glob("*.toml")):
        with path.open("rb") as handle:
            data = tomllib.load(handle)
        reports.append(_parse_report(data))
    return tuple(reports)


def get_report_definition(report_id: str) -> ReportDefinition:
    for report in load_report_definitions():
        if report.id == report_id:
            return report
    raise KeyError(f"Unknown report definition: {report_id}")
