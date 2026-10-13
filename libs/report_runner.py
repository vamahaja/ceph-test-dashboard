"""Build mail payloads from :mod:`libs.report_definitions` and render bodies in Python."""

from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence
from urllib.parse import quote, urlencode

from libs.defaults import DEFAULT_TOP_FAILURE_REASONS, STATUS_FAILING
from libs.pulpito import run_url
from libs.report_definitions import ReportDefinition
from libs.reports.email import (
    _dashboard_jobs_failure_link,
    is_smoke_suite,
    nightly_runs_between,
    pulpito_base,
)
from libs.reports.jobs import JobsStats
from libs.reports.models import FailureReasonStat, Job, MailDelivery, NightlyMailCatalog, TestRun
from libs.reports.testruns import TestRunsStats

ALERT_TOP_FAILURES = min(5, DEFAULT_TOP_FAILURE_REASONS)

_BADGE_STYLES: dict[str, tuple[str, str]] = {
    "Healthy": ("#166534", "#dcfce7"),
    "Degraded": ("#92400e", "#fef3c7"),
    "Critical": ("#991b1b", "#fee2e2"),
    "Smoke failed": ("#991b1b", "#fee2e2"),
    "Unknown": ("#475569", "#f1f5f9"),
}

_RUN_STATUS_STYLES: dict[str, tuple[str, str]] = {
    "pass": ("#166534", "#dcfce7"),
    "fail": ("#991b1b", "#fee2e2"),
    "dead": ("#991b1b", "#fee2e2"),
    "running": ("#1d4ed8", "#dbeafe"),
    "queued": ("#475569", "#f1f5f9"),
}

_TH = 'style="padding:8px;border-bottom:2px solid #cbd5e1;text-align:left;"'
_TD = 'style="padding:8px;border-bottom:1px solid #e2e8f0;"'


@dataclass
class ReportContent:
    branch: str
    user: str
    window_display: str
    period_label: str
    window_end: datetime
    dedupe_day: str
    badge: str
    reasons: list[str]
    run_count: int
    job_count: int
    pct_pass: float
    pct_fail_dead: float
    active_runs: int
    highlight_runs: list[TestRun]
    top_failures: list[FailureReasonStat]
    scope_jobs: list[Job]


def _esc(text: object) -> str:
    return html.escape(str(text or ""), quote=True)


def _health_badge_html(label: str) -> str:
    fg, bg = _BADGE_STYLES.get(label, _BADGE_STYLES["Unknown"])
    return (
        f'<span style="display:inline-block;padding:4px 10px;border-radius:6px;'
        f'font-weight:600;color:{fg};background:{bg};">{_esc(label)}</span>'
    )


def _run_status_html(status: str) -> str:
    key = (status or "").strip().lower()
    fg, bg = _RUN_STATUS_STYLES.get(key, ("#475569", "#f1f5f9"))
    return (
        f'<span style="display:inline-block;padding:2px 8px;border-radius:4px;'
        f'font-size:12px;font-weight:600;color:{fg};background:{bg};">'
        f"{_esc(status or '—')}</span>"
    )


def filter_runs_for_report(
    runs: Sequence[TestRun],
    report: ReportDefinition,
    *,
    cfg: dict,
) -> list[TestRun]:
    if report.suite_filter == "all":
        return list(runs)
    match = report.suite_match or str(cfg.get("smoke_suite_match") or "")
    names = frozenset(report.suite_names or cfg.get("smoke_suites") or ())
    if report.suite_filter == "smoke":
        return [
            run
            for run in runs
            if is_smoke_suite(run.suite, match=match, exact_names=names)
        ]
    if report.suite_filter == "match" and match:
        return [
            run
            for run in runs
            if is_smoke_suite(run.suite, match=match, exact_names=frozenset())
        ]
    if report.suite_names:
        return [
            run
            for run in runs
            if is_smoke_suite(run.suite, match="", exact_names=names)
        ]
    return list(runs)


def build_report_content(
    report: ReportDefinition,
    catalog: NightlyMailCatalog,
    branch: str,
    *,
    user: str,
    window_start: datetime,
    window_end: datetime,
    window_display: str,
    period_label: str,
    dedupe_day: str,
    cfg: dict,
) -> ReportContent | None:
    scoped = nightly_runs_between(
        catalog.runs,
        user=user,
        start=window_start,
        end=window_end,
        branch=branch,
    )
    runs = filter_runs_for_report(scoped, report, cfg=cfg)
    failing = [run for run in runs if run.status in STATUS_FAILING]
    if report.send_when == "failing" and not failing:
        return None

    highlight = failing if report.send_when == "failing" else failing
    if report.show_summary_stats:
        run_stats = TestRunsStats.from_testruns(runs)
        if report.fetch_jobs and catalog.jobs:
            jobs = JobsStats.from_jobs(catalog.jobs).for_run_set(runs)
        else:
            jobs = JobsStats.for_testruns(runs)
        health = run_stats.cluster_health(jobs, now=datetime.now(timezone.utc))
        completed = health.completed
        badge = str(report.badge_override or health.badge)
        reasons = list(health.reasons)
        run_count = len(runs)
        job_count = health.cnt_jobs
        pct_pass = completed.pct_pass
        pct_fail_dead = completed.pct_fail + completed.pct_dead
        active_runs = health.cnt_active_runs
        top = jobs.top_failure_reasons(ALERT_TOP_FAILURES)
        scope_jobs = jobs.jobs
    else:
        jobs = JobsStats.for_testruns(highlight or runs)
        badge = str(report.badge_override or "Smoke failed")
        reasons = []
        run_count = len(runs)
        job_count = len(jobs.jobs)
        pct_pass = 0.0
        pct_fail_dead = 0.0
        active_runs = 0
        top = jobs.top_failure_reasons(ALERT_TOP_FAILURES)
        scope_jobs = jobs.jobs

    return ReportContent(
        branch=branch,
        user=user,
        window_display=window_display,
        period_label=period_label,
        window_end=window_end,
        dedupe_day=dedupe_day,
        badge=badge,
        reasons=reasons,
        run_count=run_count,
        job_count=job_count,
        pct_pass=pct_pass,
        pct_fail_dead=pct_fail_dead,
        active_runs=active_runs,
        highlight_runs=highlight,
        top_failures=top,
        scope_jobs=scope_jobs,
    )


def render_report_bodies(
    report: ReportDefinition,
    content: ReportContent,
    *,
    dashboard_base_url: str | None,
    pulpito: str | None,
) -> str:
    title = report.format_title(branch=content.branch)
    window = (
        f"{content.window_display} ({content.period_label})"
        if content.period_label and report.window_kind == "weekly"
        else content.window_display
    )

    reason_html = "".join(
        f'<li style="margin:4px 0;">{_esc(r)}</li>' for r in content.reasons
    )
    stats_html = ""
    if report.show_summary_stats:
        stats_html = (
            '<table style="width:100%;border-collapse:collapse;margin:12px 0;font-size:13px;">'
            "<tr>"
            f'<td style="padding:10px;background:#f8fafc;border:1px solid #e2e8f0;"><strong>Runs</strong><br>{content.run_count}</td>'
            f'<td style="padding:10px;background:#f8fafc;border:1px solid #e2e8f0;"><strong>Jobs</strong><br>{content.job_count}</td>'
            f'<td style="padding:10px;background:#f8fafc;border:1px solid #e2e8f0;"><strong>Pass %</strong><br>{content.pct_pass:.1f}%</td>'
            f'<td style="padding:10px;background:#f8fafc;border:1px solid #e2e8f0;"><strong>Fail+dead %</strong><br>{content.pct_fail_dead:.1f}%</td>'
            "</tr><tr>"
            f'<td style="padding:10px;background:#f8fafc;border:1px solid #e2e8f0;"><strong>Active runs</strong><br>{content.active_runs}</td>'
            f'<td style="padding:10px;background:#f8fafc;border:1px solid #e2e8f0;" colspan="3">'
            f"<strong>Failed/dead runs</strong><br>{len(content.highlight_runs)}</td>"
            "</tr></table>"
        )
    failures_block = _top_failures_html(content, dashboard_base_url)
    runs_block = _runs_table_html(content.highlight_runs, pulpito, report.runs_heading)
    if not content.highlight_runs and report.show_summary_stats and content.run_count == 0:
        runs_block = "<p>No scheduled nightly runs in this window.</p>"

    inner = (
        f'<p style="margin:0 0 8px;color:#475569;font-size:13px;">'
        f"<strong>Window (scheduled, UTC):</strong> {_esc(window)}<br>"
        f"<strong>User:</strong> {_esc(content.user)}</p>"
    )
    if content.badge:
        inner += (
            f'<p style="margin:12px 0 4px;"><strong>Health:</strong> '
            f"{_health_badge_html(content.badge)}</p>"
            f'<ul style="margin:4px 0 12px;padding-left:20px;color:#334155;font-size:13px;">'
            f"{reason_html}</ul>"
        )
    inner += stats_html + failures_block + runs_block
    return _html_shell(title, inner)


def _top_failures_html(content: ReportContent, dashboard_base: str | None) -> str:
    rows = content.top_failures[:ALERT_TOP_FAILURES]
    if not rows:
        return ""
    body_rows: list[str] = []
    for row in rows:
        link = _dashboard_jobs_failure_link(dashboard_base, row.reason, content.scope_jobs)
        dash_td = ""
        if dashboard_base:
            if link:
                dash_td = (
                    f"<td {_TD}>"
                    f'<a href="{_esc(link)}" style="color:#1d4ed8;text-decoration:none;">'
                    f"View {row.count} jobs →</a></td>"
                )
            else:
                dash_td = f"<td {_TD}>—</td>"
        body_rows.append(
            "<tr>"
            f"<td {_TD}>{_esc(row.reason)}</td>"
            f'<td {_TD} style="text-align:right;">{row.count}</td>'
            f'<td {_TD} style="text-align:right;">{row.pct:.1f}%</td>'
            f"{dash_td}"
            "</tr>"
        )
    dash_header = f"<th {_TH}>Dashboard</th>" if dashboard_base else ""
    return (
        '<h3 style="margin:16px 0 8px;font-size:15px;">Top failure reasons</h3>'
        '<table style="width:100%;border-collapse:collapse;font-size:13px;">'
        "<thead><tr>"
        f"<th {_TH}>Issue</th><th {_TH}>Jobs</th>"
        f"<th {_TH}>% fail jobs</th>{dash_header}"
        "</tr></thead><tbody>"
        + "".join(body_rows)
        + "</tbody></table>"
    )


def _runs_table_html(
    runs: Sequence[TestRun],
    pulpito: str | None,
    heading: str,
) -> str:
    if not runs:
        return ""
    rows_html: list[str] = []
    for run in runs:
        link = run_url(run.name, base=pulpito) if pulpito else ""
        run_cell = (
            f'<a href="{_esc(link)}" style="color:#1d4ed8;text-decoration:none;">'
            f"{_esc(run.name)}</a>"
            if link
            else _esc(run.name)
        )
        rows_html.append(
            "<tr>"
            f"<td {_TD}>{_esc(run.suite or '—')}</td>"
            f"<td {_TD}>{_esc(run.sha_short or '—')}</td>"
            f"<td {_TD}>{_run_status_html(run.status)}</td>"
            f'<td {_TD}>{run_cell}</td>'
            "</tr>"
        )
    return (
        f'<h3 style="margin:16px 0 8px;font-size:15px;">{_esc(heading)}</h3>'
        '<table style="width:100%;border-collapse:collapse;font-size:13px;">'
        f"<thead><tr><th {_TH}>Suite</th><th {_TH}>SHA</th>"
        f"<th {_TH}>Status</th><th {_TH}>Run</th></tr></thead>"
        "<tbody>"
        + "".join(rows_html)
        + "</tbody></table>"
    )


def _html_shell(title: str, inner: str) -> str:
    return (
        '<!DOCTYPE html><html><body style="margin:0;padding:16px;font-family:sans-serif;">'
        f'<div style="max-width:720px;margin:0 auto;">'
        f"<h2>{_esc(title)}</h2>{inner}</div></body></html>"
    )


def deliver_report(
    report: ReportDefinition,
    content: ReportContent,
    *,
    dashboard_base_url: str | None = None,
    pulpito_base_url: str | None = None,
) -> MailDelivery:
    pulpito = pulpito_base_url if pulpito_base_url is not None else pulpito_base()
    html_body = render_report_bodies(
        report,
        content,
        dashboard_base_url=dashboard_base_url,
        pulpito=pulpito,
    )
    subject = report.format_subject(
        branch=content.branch,
        period_label=content.period_label,
        badge=content.badge,
        failed_count=len(content.highlight_runs),
    )
    if report.dedupe == "weekly_window":
        state_key = content.branch
        state_value = content.window_end.isoformat()
    else:
        state_key = f"{content.branch}:{content.dedupe_day}"
        state_value = content.dedupe_day
    return MailDelivery(
        subject=subject,
        body_plain="",
        body_html=html_body,
        state_key=state_key,
        state_value=state_value,
    )
