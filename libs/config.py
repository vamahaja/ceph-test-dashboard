import configparser
import os

from libs.defaults import (
    DEFAULT_CONFIG_DIR,
    DEFAULT_CONFIG_NAME,
    DEFAULT_HW_MIN_RUNS,
    DEFAULT_NIGHTLY_RUN_USER,
    DEFAULT_PADDLE_TLS_VERIFY,
    DEFAULT_PADDLE_TIMEOUT,
    DEFAULT_REFRESH_MINUTES,
    DEFAULT_RELEASE_BRANCHES,
)
from libs.exceptions import ConfigError


def _resolve_config_file() -> str:
    """Resolve the dashboard configuration file path."""
    user_config_path = os.path.join(
        os.path.expanduser("~"), ".config", DEFAULT_CONFIG_NAME
    )
    candidates = (
        os.environ.get("CEPH_TEST_DASHBOARD_CONFIG"),
        user_config_path,
        os.path.join(DEFAULT_CONFIG_DIR, DEFAULT_CONFIG_NAME),
    )
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return user_config_path


def read_config():
    """Read config file and return sections as a dict."""
    config_path = _resolve_config_file()
    if not os.path.exists(config_path):
        raise FileNotFoundError(
            f"Configuration file not found at {config_path}"
        )

    parser = configparser.ConfigParser()
    parser.read(config_path)
    return {section: dict(parser[section]) for section in parser.sections()}


def _as_bool(value, default: bool = True) -> bool:
    """Coerce a config value to bool."""
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "on"):
        return True
    if text in ("0", "false", "no", "off"):
        return False
    raise ConfigError(
        f"Invalid boolean value: {value!r}"
    )

def _as_int(value) -> int:
    """Coerce a config value to int."""
    if isinstance(value, int):
        return value
    if isinstance(value, (float)):
        return int(value)
    if value is None or value == "":
        raise ConfigError(
            f"Missing required integer value: {value!r}"
        )

    text = str(value).strip()
    try:
        return int(text)
    except ValueError:
        raise ConfigError(
            f"Invalid integer value: {text!r}"
        )


def get_paddle_config() -> dict:
    """Return paddles section settings from config."""
    config = read_config()
    if not config or "paddles" not in config:
        raise ConfigError(
            "paddles section not found in configuration file"
        )

    paddles = config.get("paddles", {})
    unset = [
        param
        for param in ("base_url",)
        if not paddles.get(param)
    ]
    if unset:
        raise ConfigError(
            f"Missing required parameters: {', '.join(unset)}"
        )

    tls_verify = _as_bool(
        paddles.get("tls_verify"),
        default=DEFAULT_PADDLE_TLS_VERIFY,
    )
    timeout = _as_int(
        paddles.get("timeout", DEFAULT_PADDLE_TIMEOUT),
    )
    return {
        "base_url": paddles.get("base_url"),
        "timeout": timeout,
        "tls_verify": tls_verify,
    }


def get_refresh_minutes() -> int:
    """Return report snapshot lifetime in minutes from config.

    Reads ``[cache] refresh_minutes``, then ``[cache] refresh_hours`` /
    ``refresh_hour``, then ``[overview] refresh_minutes`` for older
    configs, then the default.
    """
    config = read_config()
    cache = config.get("cache", {})
    raw = cache.get("refresh_minutes")
    if raw in (None, ""):
        hours = cache.get("refresh_hours")
        if hours in (None, ""):
            hours = cache.get("refresh_hour")
        if hours not in (None, ""):
            raw = _as_int(hours) * 60
    if raw in (None, ""):
        raw = config.get("overview", {}).get(
            "refresh_minutes", DEFAULT_REFRESH_MINUTES
        )
    minutes = _as_int(raw)
    if minutes < 1:
        raise ConfigError(
            f"cache.refresh_minutes must be >= 1, got {minutes}"
        )
    return minutes


def get_refresh_seconds() -> int:
    """Report snapshot lifetime in seconds (``refresh_minutes * 60``)."""
    return get_refresh_minutes() * 60


def get_release_branches() -> list[str]:
    """Return release branches from config, in default display order."""
    raw = read_config().get("release", {}).get("branches", "")
    branches = [part.strip() for part in str(raw).split(",") if part.strip()]
    if not branches:
        return list(DEFAULT_RELEASE_BRANCHES)
    rank = {name: i for i, name in enumerate(DEFAULT_RELEASE_BRANCHES)}
    unique = list(dict.fromkeys(branches))
    unique.sort(key=lambda name: (rank.get(name, len(rank)), name))
    return unique


def get_nightly_run_user() -> str:
    """Return the nightly run user from config."""
    return read_config().get("nightly", {}).get(
        "run_user", DEFAULT_NIGHTLY_RUN_USER
    )


def get_hardware_config() -> dict:
    """Return hardware dashboard tuning parameters."""
    config = read_config().get("hardware", {})
    return {
        "min_runs": _as_int(config.get("min_runs", DEFAULT_HW_MIN_RUNS)),
    }


def get_pulpito_url() -> str | None:
    """Return the pulpito base URL from config."""
    config = read_config()
    if not config or "pulpito" not in config:
        raise ConfigError("pulpito section not found in configuration file")

    pulpito = config.get("pulpito", {})
    unset = [
        param
        for param in ("base_url",)
        if not pulpito.get(param)
    ]
    if unset:
        raise ConfigError(
            f"Missing required parameters: {', '.join(unset)}"
        )

    return pulpito.get("base_url")
