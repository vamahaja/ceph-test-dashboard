"""Default configuration values"""

# Default configuration file name
DEFAULT_CONFIG_NAME = "ceph-test-dashboard.ini"
DEFAULT_CONFIG_DIR = "/home/appuser/.config/"

# Default cache TTL
DEFAULT_CACHE_TTL = 3600

# Default paddle certificate verification
DEFAULT_PADDLE_TLS_VERIFY = True

# Default paddle timeout
DEFAULT_PADDLE_TIMEOUT = 60

# Hardware page defaults
DEFAULT_HW_RUN_SCAN = 200
DEFAULT_HW_MAX_RUNS = 30
DEFAULT_HW_MIN_RUNS = 2
DEFAULT_HW_DAYS_WINDOW = 7

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
DEFAULT_TOP_OS_TRENDS = 3
DEFAULT_TOP_SUITE_SHARE = 12
DEFAULT_TOP_OS_SHARE = 8
DEFAULT_TOP_FAILURE_REASONS = 10
DEFAULT_TOP_FAILING_TESTS = 10
DEFAULT_TOP_FAILED_RUNS = 10
DEFAULT_TOP_MACHINE_ERRORS = 10
DEFAULT_TOP_ACTIVE_TESTRUNS = 12
DEFAULT_FLAKY_MIN_EXECUTIONS = 3
DEFAULT_FAILURE_REASON_MAX_LEN = 80

# Incremental refresh for Overview / report pages (last N minutes)
DEFAULT_REFRESH_MINUTES = 60
DEFAULT_OVERVIEW_REFRESH_MINUTES = DEFAULT_REFRESH_MINUTES

# Stable branches shown on the Releases report
DEFAULT_RELEASE_BRANCHES = ("tentacle", "squid", "umbrella")

# Infra / machine-error reasons used by the hardware report
DEFAULT_MACHINE_ERROR_PATTERN = (
    r"(ssh|connection|timeout|node|machine|hardware|oom|kernel|reboot|power)"
)

STATUS_COMPLETED = frozenset({"pass", "fail", "dead"})
STATUS_FAILING = frozenset({"fail", "dead"})
STATUS_ACTIVE = frozenset({"running", "queued", "waiting"})
STATUS_ALERTING = frozenset({"fail", "dead", "queued", "running"})

# Status palette — semantic RGB used by every dashboard page.
# Charts use STATUS_COLOR_MAP; tables use STATUS_ROW_COLORS (same hues, lower alpha).
_STATUS_RGB = {
    "pass": (22, 163, 74),      # green
    "fail": (220, 38, 38),      # red
    "dead": (127, 29, 29),      # dark red
    "running": (37, 99, 235),   # blue
    "queued": (217, 119, 6),    # amber
    "waiting": (71, 85, 105),   # slate
    "unknown": (124, 58, 237),  # violet
}

_STATUS_CHART_ALPHA = 0.45
_STATUS_ROW_ALPHA = 0.14
_STATUS_FALLBACK_RGB = (148, 163, 184)  # slate-400

STATUS_RGB = _STATUS_RGB


def status_rgba(status: str, alpha: float = 1.0) -> str:
    """CSS ``rgba()`` for a job/run status (or ``unknown``)."""
    rgb = STATUS_RGB.get(status, _STATUS_FALLBACK_RGB)
    r, g, b = rgb
    return f"rgba({r}, {g}, {b}, {alpha})"


def _rgba(rgb: tuple[int, int, int], alpha: float) -> str:
    r, g, b = rgb
    return f"rgba({r}, {g}, {b}, {alpha})"


STATUS_COLOR_MAP = {
    status: status_rgba(status, _STATUS_CHART_ALPHA)
    for status, rgb in _STATUS_RGB.items()
}

STATUS_COLOR_FALLBACK = _rgba(_STATUS_FALLBACK_RGB, _STATUS_CHART_ALPHA)

STATUS_ROW_COLORS = {
    status: f"background-color: {_rgba(rgb, _STATUS_ROW_ALPHA)}"
    for status, rgb in _STATUS_RGB.items()
}


def status_row_styles(row) -> list[str]:
    """Pandas Styler callback: tint a table row by its ``status`` cell."""
    style = STATUS_ROW_COLORS.get(row.get("status", ""), "")
    return [style] * len(row)
