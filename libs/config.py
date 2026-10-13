import configparser
import os
from pathlib import Path

from libs.defaults import (
    DEFAULT_DIGEST_DAILY_FETCH_DAYS,
    DEFAULT_DIGEST_DAILY_LOOKBACK_DAYS,
    DEFAULT_DIGEST_ENABLED,
    DEFAULT_DIGEST_FROM_ADDR,
    DEFAULT_DIGEST_SMTP_HOST,
    DEFAULT_DIGEST_SMTP_PORT,
    DEFAULT_DIGEST_SMOKE_SUITE_MATCH,
    DEFAULT_DIGEST_SQLITE_PATH,
    DEFAULT_DIGEST_WEEKLY_FETCH_DAYS,
    DEFAULT_DATA_DIR,
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
    base_url = (paddles.get("base_url") or "").strip()
    if not base_url:
        raise ConfigError("Missing required parameters: base_url")

    tls_verify = _as_bool(
        paddles.get("tls_verify"),
        default=DEFAULT_PADDLE_TLS_VERIFY,
    )
    timeout = _as_int(
        paddles.get("timeout", DEFAULT_PADDLE_TIMEOUT),
    )
    return {
        "base_url": base_url,
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


def _digest_ini_section(config: dict) -> dict:
    """``[digest]`` settings; legacy ``[alerts]`` is accepted with the same keys."""
    if "digest" in config:
        return dict(config["digest"])
    if "alerts" in config:
        return dict(config["alerts"])
    return {}


def resolve_dashboard_base_url(section: dict | None = None) -> str | None:
    """Public dashboard origin for deep links (ini ``dashboard_base_url`` or env)."""
    if section is None:
        section = _digest_ini_section(read_config())
    raw = str(section.get("dashboard_base_url", "") or "").strip().rstrip("/")
    if raw:
        return raw
    env = os.environ.get("CEPH_TEST_DASHBOARD_BASE_URL", "").strip().rstrip("/")
    return env or None


def get_data_dir() -> Path:
    """Return ``[storage] data_dir`` (PVC mount in cluster deployments)."""
    section = read_config().get("storage", {})
    raw = str(section.get("data_dir", DEFAULT_DATA_DIR) or DEFAULT_DATA_DIR).strip()
    return Path(raw)


def resolve_data_path(path: str) -> Path:
    """Resolve a path relative to ``data_dir`` when not absolute."""
    candidate = Path(path.strip())
    if candidate.is_absolute():
        return candidate
    return get_data_dir() / candidate


def get_digest_config() -> dict:
    """Return ``[digest]`` settings for nightly mail reports."""
    section = _digest_ini_section(read_config())
    enabled = _as_bool(section.get("enabled"), default=DEFAULT_DIGEST_ENABLED)
    recipients_raw = str(section.get("recipients", "") or "")
    recipients = [part.strip() for part in recipients_raw.split(",") if part.strip()]

    smoke_suites_raw = str(section.get("smoke_suites", "") or "")
    smoke_suites = frozenset(
        part.strip() for part in smoke_suites_raw.split(",") if part.strip()
    )

    from_addr = str(section.get("from_addr", DEFAULT_DIGEST_FROM_ADDR) or "").strip()
    skip_from_check = os.environ.get("CEPH_TEST_DASHBOARD_DIGEST_SKIP_FROM_CHECK", "")
    if from_addr and not skip_from_check:
        if "@" not in from_addr or not from_addr.lower().endswith("@sepia.ceph.com"):
            raise ConfigError(
                "digest.from_addr must be an address @sepia.ceph.com "
                "(lab relay identity; do not use @ibm.com, @redhat.com, etc.)"
            )

    smtp_host = str(section.get("smtp_host", DEFAULT_DIGEST_SMTP_HOST) or "").strip()
    smtp_port = _as_int(section.get("smtp_port", DEFAULT_DIGEST_SMTP_PORT))

    if enabled:
        missing = []
        if not smtp_host:
            missing.append("smtp_host")
        if not from_addr:
            missing.append("from_addr")
        if not recipients:
            missing.append("recipients")
        if missing:
            raise ConfigError(
                f"digest enabled but missing: {', '.join(missing)}"
            )

    return {
        "enabled": enabled,
        "recipients": recipients,
        "smtp_host": smtp_host,
        "smtp_port": smtp_port,
        "from_addr": from_addr,
        "daily_lookback_days": _as_int(
            section.get("daily_lookback_days", DEFAULT_DIGEST_DAILY_LOOKBACK_DAYS)
        ),
        "weekly_fetch_days": _as_int(
            section.get("weekly_fetch_days", DEFAULT_DIGEST_WEEKLY_FETCH_DAYS)
        ),
        "daily_fetch_days": _as_int(
            section.get("daily_fetch_days", DEFAULT_DIGEST_DAILY_FETCH_DAYS)
        ),
        "smoke_suite_match": str(
            section.get("smoke_suite_match", DEFAULT_DIGEST_SMOKE_SUITE_MATCH) or ""
        ).strip(),
        "smoke_suites": smoke_suites,
        "sqlite_path": str(
            resolve_data_path(
                str(
                    section.get("sqlite_path")
                    or section.get("state_path")
                    or DEFAULT_DIGEST_SQLITE_PATH
                ).strip()
                or DEFAULT_DIGEST_SQLITE_PATH
            )
        ),
        "dashboard_base_url": resolve_dashboard_base_url(section),
    }
