import configparser
import os

# Default INI location for local runs and the container image user home.
_DEFAULT_CONFIG_NAME = "ceph-test-dashboard.ini"
_IMAGE_CONFIG_PATH = f"/home/appuser/.config/{_DEFAULT_CONFIG_NAME}"


def _resolve_config_file() -> str:
    """
    Resolve the dashboard INI path for local, Podman, and cluster runs.

    Order:
    1. ``CEPH_TEST_DASHBOARD_CONFIG`` if set and the file exists
    2. ``~/.config/ceph-test-dashboard.ini`` (respects ``HOME``)
    3. ``/home/appuser/.config/ceph-test-dashboard.ini`` (container default)
    """
    candidates = (
        os.environ.get("CEPH_TEST_DASHBOARD_CONFIG"),
        os.path.join(
            os.path.expanduser("~"),
            ".config",
            _DEFAULT_CONFIG_NAME,
        ),
        _IMAGE_CONFIG_PATH,
    )
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return os.path.join(os.path.expanduser("~"), ".config", _DEFAULT_CONFIG_NAME)


CONFIG_FILE = _resolve_config_file()

DEFAULT_CACHE_TTL = 3600

# ── Hardware page defaults ────────────────────────────────────────────
# Single source of truth for all hardware dashboard tuning parameters.
# Override any value in ~/.config/ceph-test-dashboard.ini under [hardware]:
#
#   [hardware]
#   run_scan    = 200
#   max_runs    = 30
#   min_runs    = 2
#   days_window = 7
#
DEFAULT_HW_RUN_SCAN    = 200   # runs to scan from Paddles
DEFAULT_HW_MAX_RUNS    = 30    # max matching runs to load jobs from
DEFAULT_HW_MIN_RUNS    = 2     # warn if fewer matching runs found
DEFAULT_HW_DAYS_WINDOW = 7     # ignore runs older than this many days


class ConfigError(Exception):
    """Base class for configuration errors."""
    pass


def read_config():
    """
    Reads the dashboard configuration file and returns a dictionary of sections.

    See ``_resolve_config_file`` for path resolution order.
    """
    config_path = _resolve_config_file()
    if not os.path.exists(config_path):
        raise FileNotFoundError(
            f"Configuration file not found at {config_path}"
        )

    parser = configparser.ConfigParser()
    parser.read(config_path)
    return {section: dict(parser[section]) for section in parser.sections()}


def get_paddle_config():
    """
    Reads paddle config from config file and returns a dictionary.
    """
    config = read_config()
    if not config or "paddles" not in config:
        raise ConfigError("paddles section not found in configuration file")

    return config.get("paddles", {})


def get_base_url():
    """
    Reads the configuration and returns the Paddles base URL.
    Falls back to a default value if not found.
    """
    paddles = get_paddle_config()
    if "base_url" not in paddles:
        raise ConfigError(
            "'base_url' not found in paddles section of configuration file"
        )

    return paddles.get("base_url")


def get_cache_ttl() -> int:
    """
    Reads the cache TTL (in seconds) from config, or returns the default
    of 3600 seconds (1 hour) if not configured.
    """
    try:
        config = read_config()
    except FileNotFoundError:
        return DEFAULT_CACHE_TTL
    cache = config.get("cache", {})
    try:
        return int(cache.get("ttl", DEFAULT_CACHE_TTL))
    except (ValueError, TypeError):
        return DEFAULT_CACHE_TTL


def get_nightly_run_user() -> str:
    """
    Reads the nightly run user from config, or returns the default
    'jenkins-build' if not configured.
    """
    try:
        config = read_config()
    except FileNotFoundError:
        return "jenkins-build"
    nightly = config.get("nightly", {})
    return nightly.get("run_user", "jenkins-build")


def get_hardware_config() -> dict:
    """
    Return hardware dashboard tuning parameters.

    Values are read from the [hardware] section of the config file.
    Falls back to DEFAULT_HW_* constants if the section or key is absent,
    so the dashboard works with no config file changes required.

    Returns a dict with keys:
        run_scan    (int) — runs to scan from Paddles
        max_runs    (int) — max matching runs to load jobs from
        min_runs    (int) — warn threshold for thin data
        days_window (int) — rolling window in days (0 = no cutoff)
    """
    try:
        config = read_config()
    except FileNotFoundError:
        config = {}

    hw = config.get("hardware", {})

    def _int(key: str, default: int) -> int:
        try:
            return int(hw.get(key, default))
        except (ValueError, TypeError):
            return default

    return {
        "run_scan":    _int("run_scan",    DEFAULT_HW_RUN_SCAN),
        "max_runs":    _int("max_runs",    DEFAULT_HW_MAX_RUNS),
        "min_runs":    _int("min_runs",    DEFAULT_HW_MIN_RUNS),
        "days_window": _int("days_window", DEFAULT_HW_DAYS_WINDOW),
    }


def get_pulpito_url() -> str | None:
    """
    Reads the configuration and returns the Pulpito base URL, or None if
    the [pulpito] section or base_url key is absent (Pulpito is optional).
    """
    try:
        config = read_config()
    except FileNotFoundError:
        return None
    pulpito = config.get("pulpito", {})
    return pulpito.get("base_url") or None
