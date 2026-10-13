"""Scheduled nightly mail reports driven by ``templates/reports/*.toml``."""

from __future__ import annotations

import argparse
import logging
import sys
import threading
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone

from libs.config import get_digest_config, get_nightly_run_user, get_release_branches
from libs.defaults import (
    DEFAULT_DIGEST_DAILY_REPORT_ANCHOR_HOUR,
    DEFAULT_DIGEST_DAILY_REPORT_ANCHOR_MINUTE,
    DEFAULT_DIGEST_NIGHTLY_ANCHOR_HOUR,
    DEFAULT_DIGEST_NIGHTLY_ANCHOR_MINUTE,
)
from libs.mail_state import MailState
from libs.report_definitions import (
    ReportDefinition,
    get_report_definition,
    load_report_definitions,
)
from libs.report_runner import build_report_content, deliver_report
from libs.reports.email import active_nightly_branches, nightly_runs_between, send_mail
from libs.reports.jobs import JobsStats
from libs.reports.models import MailDelivery, NightlyMailCatalog
from libs.reports.testruns import TestRunsStats
from libs.reports.utils import as_utc

_LOG = logging.getLogger(__name__)


def utc_today(now: datetime | None = None) -> date:
    ref = as_utc(now) or datetime.now(timezone.utc)
    return ref.date()


def format_window_display(start: datetime, end: datetime) -> str:
    fmt = "%Y-%m-%d %H:%M UTC"
    return f"{start.strftime(fmt)} → {end.strftime(fmt)} (end exclusive)"


def _anchor_on(day: date, hour: int, minute: int) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=timezone.utc)


def nightly_anchor_on(day: date) -> datetime:
    return _anchor_on(day, DEFAULT_DIGEST_NIGHTLY_ANCHOR_HOUR, DEFAULT_DIGEST_NIGHTLY_ANCHOR_MINUTE)


def daily_report_anchor_on(day: date) -> datetime:
    return _anchor_on(
        day,
        DEFAULT_DIGEST_DAILY_REPORT_ANCHOR_HOUR,
        DEFAULT_DIGEST_DAILY_REPORT_ANCHOR_MINUTE,
    )


def _latest_anchor_on_or_before(
    now: datetime,
    anchor_on: Callable[[date], datetime],
) -> datetime:
    today_anchor = anchor_on(now.date())
    if now >= today_anchor:
        return today_anchor
    return anchor_on(now.date() - timedelta(days=1))


def latest_weekly_anchor_at_or_before(now: datetime) -> datetime:
    mon = now.date() - timedelta(days=now.weekday())
    this_anchor = nightly_anchor_on(mon)
    if now >= this_anchor:
        return this_anchor
    return nightly_anchor_on(mon - timedelta(days=7))


def _iso_week_label(day: date) -> str:
    year, week, _ = day.isocalendar()
    return f"{year}-W{week:02d}"


def _period_label(window_start: datetime, window_end: datetime) -> str:
    span = window_end - window_start
    if span <= timedelta(days=7, hours=1):
        return _iso_week_label(window_start.date())
    end_day = (window_end - timedelta(seconds=1)).date()
    return f"{window_start.date().isoformat()}–{end_day.isoformat()}"


def weekly_report_window(
    now: datetime | None = None,
    *,
    last_window_end: datetime | None = None,
) -> tuple[datetime, datetime, str]:
    ref = as_utc(now) or datetime.now(timezone.utc)
    window_end = latest_weekly_anchor_at_or_before(ref)
    default_start = window_end - timedelta(days=7)
    last = as_utc(last_window_end)
    window_start = last if last is not None and last < window_end else default_start
    return window_start, window_end, _period_label(window_start, window_end)


def daily_smoke_window(
    lookback_days: int,
    now: datetime | None = None,
) -> tuple[datetime, datetime]:
    periods = max(1, int(lookback_days))
    ref = as_utc(now) or datetime.now(timezone.utc)
    window_end = _latest_anchor_on_or_before(ref, daily_report_anchor_on)
    window_start = window_end - timedelta(days=periods)
    return window_start, window_end


def _fetch_days_for_window(posted_lookback_days: int, window_start: datetime) -> int:
    span = (datetime.now(timezone.utc).date() - window_start.date()).days + 2
    return max(posted_lookback_days, span)


def _fetch_catalog(
    *,
    posted_lookback_days: int,
    window_start: datetime,
    window_end: datetime,
    with_jobs: bool,
    log_label: str | None,
) -> NightlyMailCatalog:
    user = get_nightly_run_user()
    days = _fetch_days_for_window(posted_lookback_days, window_start)
    since = datetime.now(timezone.utc) - timedelta(days=max(1, days))
    _LOG.info("Fetching test runs from Paddles (last %s days, user=%s)…", days, user)
    posted = list(TestRunsStats.since(since, user=user).testruns)
    runs = nightly_runs_between(
        posted, user=user, start=window_start, end=window_end
    )
    if log_label:
        _LOG.info(
            "%s [%s, %s): %s runs",
            log_label,
            window_start.isoformat(),
            window_end.isoformat(),
            len(runs),
        )
    jobs: list = []
    if with_jobs and runs:
        _LOG.info("Fetching jobs for %s nightly run(s)…", len(runs))
        jobs = list(
            JobsStats.for_testruns(
                runs,
                on_progress=lambda done, total: _LOG.info(
                    "Jobs progress: %s / %s runs", done, total
                ),
            ).jobs
        )
    return NightlyMailCatalog(runs=runs, jobs=jobs)


def weekly_catalog_envelope(state: MailState) -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    starts: list[datetime] = []
    ends: list[datetime] = []
    for branch in get_release_branches():
        last_end = state.weekly_window_end(branch)
        start, end, _ = weekly_report_window(now, last_window_end=last_end)
        starts.append(start)
        ends.append(end)
    return min(starts), max(ends)


def _branches_for_report(
    report: ReportDefinition,
    catalog: NightlyMailCatalog,
    *,
    user: str,
    window_start: datetime,
    window_end: datetime,
) -> list[str]:
    if report.branches == "active":
        return active_nightly_branches(
            catalog.runs,
            user=user,
            window_start=window_start,
            window_end=window_end,
        )
    return list(get_release_branches())


def build_deliveries_for_report(
    report: ReportDefinition,
    cfg: dict,
    state: MailState,
    *,
    now: datetime | None = None,
) -> list[MailDelivery]:
    now = as_utc(now) or datetime.now(timezone.utc)
    user = get_nightly_run_user()
    dash = cfg.get("dashboard_base_url")
    fetch_days = int(cfg.get(report.fetch_days_key, 21))

    if report.window_kind == "weekly":
        window_start, window_end = weekly_catalog_envelope(state)
    else:
        lookback = int(
            cfg.get(report.window_lookback_days_key or "daily_lookback_days", 1)
        )
        window_start, window_end = daily_smoke_window(lookback, now)

    catalog = _fetch_catalog(
        posted_lookback_days=fetch_days,
        window_start=window_start,
        window_end=window_end,
        with_jobs=report.fetch_jobs,
        log_label=f"Report {report.id}",
    )
    dedupe_day = utc_today(now).isoformat()
    deliveries: list[MailDelivery] = []

    for branch in _branches_for_report(
        report, catalog, user=user, window_start=window_start, window_end=window_end
    ):
        if report.window_kind == "weekly":
            last_end = state.weekly_window_end(branch)
            w_start, w_end, label = weekly_report_window(now, last_window_end=last_end)
            window_display = format_window_display(w_start, w_end)
            content = build_report_content(
                report,
                catalog,
                branch,
                user=user,
                window_start=w_start,
                window_end=w_end,
                window_display=window_display,
                period_label=label,
                dedupe_day=dedupe_day,
                cfg=cfg,
            )
        else:
            window_display = format_window_display(window_start, window_end)
            content = build_report_content(
                report,
                catalog,
                branch,
                user=user,
                window_start=window_start,
                window_end=window_end,
                window_display=window_display,
                period_label="",
                dedupe_day=dedupe_day,
                cfg=cfg,
            )
        if content is None:
            continue
        deliveries.append(deliver_report(report, content, dashboard_base_url=dash))
    return deliveries


def _parse_window_end(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _should_skip(report: ReportDefinition, delivery: MailDelivery, state: MailState) -> bool:
    if report.dedupe == "weekly_window":
        window_end = _parse_window_end(delivery.state_value)
        if window_end is not None and state.weekly_already_sent(
            delivery.state_key, window_end
        ):
            _LOG.info(
                "Skip %s %s (already sent through %s)",
                report.id,
                delivery.state_key,
                delivery.state_value,
            )
            return True
        return False
    branch = delivery.state_key.split(":", 1)[0]
    if state.daily_smoke_already_sent(branch, delivery.state_value):
        _LOG.info("Skip %s %s (already sent today)", report.id, delivery.state_key)
        return True
    return False


def _mark_sent(report: ReportDefinition, delivery: MailDelivery, state: MailState) -> None:
    if report.dedupe == "weekly_window":
        window_end = _parse_window_end(delivery.state_value)
        if window_end is not None:
            state.mark_weekly_sent(delivery.state_key, window_end)
    else:
        branch, _ = delivery.state_key.split(":", 1)
        state.mark_daily_smoke_sent(branch, delivery.state_value)


def send_deliveries(
    report: ReportDefinition,
    cfg: dict,
    deliveries: list[MailDelivery],
    state: MailState,
    *,
    force: bool,
) -> int:
    sent = 0
    for delivery in deliveries:
        if not force and _should_skip(report, delivery, state):
            continue
        send_mail(
            smtp_host=cfg["smtp_host"],
            smtp_port=cfg["smtp_port"],
            from_addr=cfg["from_addr"],
            recipients=cfg["recipients"],
            subject=delivery.subject,
            body_html=delivery.body_html,
        )
        branch = (
            delivery.state_key
            if report.dedupe == "weekly_window"
            else delivery.state_key.split(":", 1)[0]
        )
        state.record_sent(
            kind=report.id,
            branch=branch,
            subject=delivery.subject,
            body_plain=delivery.body_plain,
            body_html=delivery.body_html,
            recipients=list(cfg["recipients"]),
        )
        if not force:
            _mark_sent(report, delivery, state)
        sent += 1
        _LOG.info("Sent: %s", delivery.subject)
    return sent


def run_report(
    report_id: str,
    cfg: dict,
    state: MailState,
    *,
    force: bool = False,
) -> int:
    report = get_report_definition(report_id)
    deliveries = build_deliveries_for_report(report, cfg, state)
    sent = send_deliveries(report, cfg, deliveries, state, force=force)
    if not force:
        state.save(cfg["sqlite_path"])
    _LOG.info("Report %s complete: %s message(s) sent", report.id, sent)
    return sent


def run_weekly_reports(cfg: dict, state: MailState, *, force: bool = False) -> int:
    return run_report("weekly_digest", cfg, state, force=force)


def run_daily_smoke_reports(cfg: dict, state: MailState, *, force: bool = False) -> int:
    return run_report("daily_smoke", cfg, state, force=force)


_scheduler = None
_scheduler_lock = threading.Lock()


def _scheduled_report_job(report_id: str) -> None:
    try:
        cfg = get_digest_config()
    except Exception as exc:
        _LOG.warning("Report %s skipped (config): %s", report_id, exc)
        return
    if not cfg.get("enabled"):
        return
    state = MailState.load(cfg["sqlite_path"])
    try:
        run_report(report_id, cfg, state)
    except Exception:
        _LOG.exception("Scheduled report %s failed", report_id)


def start_mail_scheduler() -> None:
    """Register APScheduler cron jobs from ``templates/reports/*.toml`` (Streamlit process)."""
    global _scheduler
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger

    with _scheduler_lock:
        if _scheduler is not None:
            return
        try:
            cfg = get_digest_config()
        except Exception as exc:
            _LOG.info("Mail scheduler not started: %s", exc)
            return
        if not cfg.get("enabled"):
            _LOG.info("Mail scheduler not started ([digest] enabled = false)")
            return

        reports = [r for r in load_report_definitions() if r.enabled]
        if not reports:
            _LOG.warning("Mail scheduler not started: no templates/reports/*.toml")
            return

        scheduler = BackgroundScheduler(timezone="UTC")
        for report in reports:
            trigger_kwargs: dict = {
                "hour": report.schedule_hour,
                "minute": report.schedule_minute,
            }
            if report.schedule_day_of_week:
                trigger_kwargs["day_of_week"] = report.schedule_day_of_week
            scheduler.add_job(
                _scheduled_report_job,
                CronTrigger(**trigger_kwargs),
                args=[report.id],
                id=f"mail_report_{report.id}",
                replace_existing=True,
            )
        scheduler.start()
        _scheduler = scheduler
        _LOG.info(
            "Mail scheduler started for %s report(s): %s",
            len(reports),
            ", ".join(r.id for r in reports),
        )


def main(argv: list[str] | None = None) -> int:
    """CLI for manual digest runs (``ceph-test-dashboard-digest``).

    The Streamlit app schedules the same reports in-process; this entry point is
    for operators who need to trigger or debug mail without the full dashboard.
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Ceph test dashboard scheduled mail reports")
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="Run a report from templates/reports/")
    run_p.add_argument("report_id")
    run_p.add_argument("--force", action="store_true")

    weekly_p = sub.add_parser("weekly", help="Alias: weekly_digest")
    weekly_p.add_argument("--force", action="store_true")
    daily_p = sub.add_parser("daily-smoke", help="Alias: daily_smoke")
    daily_p.add_argument("--force", action="store_true")

    sub.add_parser("list", help="List report templates")

    args = parser.parse_args(argv)

    if args.command == "list":
        for report in load_report_definitions():
            sched = f"{report.schedule_day_of_week or '*'} {report.schedule_hour:02d}:{report.schedule_minute:02d} UTC"
            print(f"{report.id}\t{sched}\t{report.suite_filter}\t{report.send_when}")
        return 0

    try:
        cfg = get_digest_config()
    except Exception as exc:
        _LOG.error("Config error: %s", exc)
        return 1

    if not cfg.get("enabled"):
        _LOG.info("Digest mail disabled in config ([digest] enabled = false)")
        return 0

    report_id = {"weekly": "weekly_digest", "daily-smoke": "daily_smoke"}.get(
        args.command, getattr(args, "report_id", None)
    )
    if not report_id:
        _LOG.error("Unknown command")
        return 1
    state = MailState.load(cfg["sqlite_path"])
    try:
        run_report(report_id, cfg, state, force=args.force)
        return 0
    except Exception:
        _LOG.exception("Report run failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
