"""Default configuration values"""

# Default configuration file name
DEFAULT_CONFIG_NAME = "ceph-test-dashboard.ini"
DEFAULT_CONFIG_DIR = "/home/appuser/.config/"

# Default paddle certificate verification
DEFAULT_PADDLE_TLS_VERIFY = True

# Default paddle timeout
DEFAULT_PADDLE_TIMEOUT = 60

# Hardware page defaults
DEFAULT_HW_MIN_RUNS = 2

# Nightly run user
DEFAULT_NIGHTLY_RUN_USER = "jenkins-build"

# Report fetch / pagination
DEFAULT_REPORT_COUNT = 100
DEFAULT_RUN_PAGE_SIZE = 100
DEFAULT_RUN_MAX_PAGES = 500
DEFAULT_JOB_FETCH_WORKERS = 8

# Cluster health thresholds (completed-job %)
DEFAULT_HEALTH_PASS_CRITICAL = 50.0
DEFAULT_HEALTH_PASS_DEGRADED = 80.0
DEFAULT_HEALTH_DEAD_CRITICAL = 15.0
DEFAULT_HEALTH_DEAD_DEGRADED = 5.0
DEFAULT_HEALTH_STUCK_HOURS = 6
DEFAULT_HEALTH_STUCK_HOURS_LONG = 24

# Ranking / table caps
DEFAULT_TOP_SUITE_SHARE = 12
DEFAULT_TOP_OS_SHARE = 8
DEFAULT_TOP_FAILURE_REASONS = 10
DEFAULT_TOP_FAILING_TESTS = 10
DEFAULT_TOP_FAILED_RUNS = 10
DEFAULT_TOP_ACTIVE_TESTRUNS = 12
DEFAULT_FLAKY_MIN_EXECUTIONS = 3
DEFAULT_FAILURE_REASON_MAX_LEN = 80

# Incremental / clock-aligned catalog refresh
DEFAULT_REFRESH_MINUTES = 60
DEFAULT_CATALOG_DAYS = 30

# Branches shown on the Releases report
DEFAULT_RELEASE_BRANCHES = ("main", "umbrella", "tentacle", "squid")

# [digest] nightly email (Sepia lab SMTP relay)
DEFAULT_DIGEST_ENABLED = False
DEFAULT_DIGEST_SMTP_HOST = "relay.front.sepia.ceph.com"
DEFAULT_DIGEST_SMTP_PORT = 25
DEFAULT_DIGEST_FROM_ADDR = "ceph-nightly@sepia.ceph.com"
DEFAULT_DIGEST_NIGHTLY_ANCHOR_HOUR = 6
DEFAULT_DIGEST_NIGHTLY_ANCHOR_MINUTE = 0
DEFAULT_DIGEST_DAILY_REPORT_ANCHOR_HOUR = 18
DEFAULT_DIGEST_DAILY_REPORT_ANCHOR_MINUTE = 0
DEFAULT_DIGEST_DAILY_LOOKBACK_DAYS = 1
DEFAULT_DIGEST_WEEKLY_FETCH_DAYS = 21
DEFAULT_DIGEST_DAILY_FETCH_DAYS = 5
DEFAULT_DIGEST_SMOKE_SUITE_MATCH = "smoke"
DEFAULT_DATA_DIR = "/var/lib/ceph-test-dashboard"
DEFAULT_DIGEST_SQLITE_PATH = "mail-state.sqlite"

STATUS_COMPLETED = frozenset({"pass", "fail", "dead"})
STATUS_FAILING = frozenset({"fail", "dead"})
STATUS_ACTIVE = frozenset({"running", "queued", "waiting"})
STATUS_ALERTING = frozenset({"fail", "dead", "queued", "running"})

# Status palette — semantic RGB used by every dashboard page.
# Charts use STATUS_COLOR_MAP; tables use STATUS_ROW_COLORS (same hues, lower alpha).
STATUS_RGB = {
    "pass": (22, 163, 74),      # green
    "fail": (220, 38, 38),      # red
    "dead": (127, 29, 29),      # dark red
    "running": (37, 99, 235),   # blue
    "queued": (217, 119, 6),    # amber
    "waiting": (71, 85, 105),   # slate
    "unknown": (124, 58, 237),  # violet
}

STATUS_CHART_ALPHA = 0.45
STATUS_ROW_ALPHA = 0.14
STATUS_FALLBACK_RGB = (148, 163, 184)  # slate-400

STATUS_COLOR_MAP = {
    status: f"rgba({r}, {g}, {b}, {STATUS_CHART_ALPHA})"
    for status, (r, g, b) in STATUS_RGB.items()
}

STATUS_ROW_COLORS = {
    status: (
        f"background-color: rgba({rgb[0]}, {rgb[1]}, {rgb[2]}, {STATUS_ROW_ALPHA})"
    )
    for status, rgb in STATUS_RGB.items()
}


def status_rgba(status: str, alpha: float = 1.0) -> str:
    """CSS ``rgba()`` for a job/run status (or ``unknown``)."""
    rgb = STATUS_RGB.get(status, STATUS_FALLBACK_RGB)
    r, g, b = rgb
    return f"rgba({r}, {g}, {b}, {alpha})"


def status_row_styles(row) -> list[str]:
    """Pandas Styler callback: tint a table row by its ``status`` cell."""
    style = STATUS_ROW_COLORS.get(row.get("status", ""), "")
    return [style] * len(row)
