"""Nightly mail scope filters and SMTP transport."""

from __future__ import annotations

import logging
import os
import smtplib
from collections.abc import Iterable
from datetime import date, datetime
from email.mime.text import MIMEText
from typing import Sequence
from urllib.parse import quote, urlencode

from libs.config import get_pulpito_url
from libs.defaults import DEFAULT_TOP_FAILURE_REASONS
from libs.reports.jobs import JobsStats
from libs.reports.models import Job, TestRun
from libs.reports.utils import as_utc

_LOG = logging.getLogger(__name__)


def _scheduled_day(run: TestRun) -> date | None:
    ts = run.scheduled
    if ts is None:
        return None
    return ts.date() if isinstance(ts, datetime) else ts


def _scheduled_utc(run: TestRun) -> datetime | None:
    return as_utc(run.scheduled)


def nightly_runs_between(
    runs: Iterable[TestRun],
    *,
    user: str,
    start: datetime,
    end: datetime,
    branch: str = "",
) -> list[TestRun]:
    """Scheduled nightlies with ``start <= scheduled < end`` (UTC)."""
    start_u = as_utc(start) or start
    end_u = as_utc(end) or end
    out: list[TestRun] = []
    for run in runs:
        if run.user != user:
            continue
        ts = _scheduled_utc(run)
        if ts is None:
            continue
        if ts < start_u or ts >= end_u:
            continue
        if branch and run.branch != branch:
            continue
        out.append(run)
    return out


def nightly_runs(
    runs: Iterable[TestRun],
    *,
    user: str,
    start: date,
    end: date,
    branch: str = "",
) -> list[TestRun]:
    """Scheduled nightly runs for ``user`` with ``scheduled`` day in [start, end]."""
    out: list[TestRun] = []
    for run in runs:
        if run.scheduled is None:
            continue
        if run.user != user:
            continue
        day = _scheduled_day(run)
        if day is None or day < start or day > end:
            continue
        if branch and run.branch != branch:
            continue
        out.append(run)
    return out


def active_nightly_branches(
    runs: Iterable[TestRun],
    *,
    user: str,
    window_start: datetime,
    window_end: datetime,
) -> list[str]:
    """Distinct branches with scheduled nightlies in ``[window_start, window_end)``."""
    scoped = nightly_runs_between(
        runs, user=user, start=window_start, end=window_end
    )
    branches = sorted({run.branch for run in scoped if run.branch})
    return branches


def is_smoke_suite(suite: str, *, match: str, exact_names: frozenset[str]) -> bool:
    """True if ``suite`` is considered a smoke suite for daily digest reports."""
    name = (suite or "").strip()
    if not name:
        return False
    if exact_names:
        return name in exact_names
    needle = (match or "").strip().lower()
    if not needle:
        return False
    return needle in name.lower()



def send_mail(
    *,
    smtp_host: str,
    smtp_port: int,
    from_addr: str,
    recipients: Sequence[str],
    subject: str,
    body: str = "",
    body_html: str | None = None,
) -> None:
    """Deliver HTML digest mail (or plain text when ``body_html`` is omitted)."""
    if not recipients:
        raise ValueError("recipients required")

    if body_html:
        msg = MIMEText(body_html, "html", "utf-8")
    elif body:
        msg = MIMEText(body, "plain", "utf-8")
    else:
        raise ValueError("body_html or body required")

    msg["From"] = from_addr
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject

    debug = os.environ.get("CEPH_TEST_DASHBOARD_SMTP_DEBUG", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    with smtplib.SMTP(smtp_host, smtp_port, timeout=120) as client:
        if debug:
            client.set_debuglevel(1)
        refused = client.sendmail(from_addr, list(recipients), msg.as_string())
    if refused:
        raise smtplib.SMTPRecipientsRefused(refused)
    _LOG.info(
        "Relay %s:%s accepted message (From=%s To=%s). "
        "Inbox delivery is not guaranteed—check spam and recipient spelling.",
        smtp_host,
        smtp_port,
        from_addr,
        ", ".join(recipients),
    )


ALERT_TOP_FAILURES = min(5, DEFAULT_TOP_FAILURE_REASONS)


def pulpito_base() -> str | None:
    try:
        base = get_pulpito_url()
    except Exception:
        return None
    return base.rstrip("/") if base else None


def _dashboard_jobs_failure_link(
    dashboard_base: str | None,
    reason: str,
    scope_jobs: Sequence[Job],
) -> str | None:
    if not dashboard_base:
        return None
    matching = JobsStats.from_jobs(list(scope_jobs)).matching_failure(reason)
    run_names = list(dict.fromkeys(job.run_name for job in matching if job.run_name))
    if not run_names:
        return None
    query = urlencode(
        {
            "failure_reason": reason,
            "source": "digest",
            "runs": ",".join(run_names),
        },
        quote_via=quote,
    )
    return f"{dashboard_base}/Jobs?{query}"
