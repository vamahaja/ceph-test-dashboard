import configparser
import os

CONFIG_FILE = os.path.expanduser('~/.config/ceph-test-dashboard.ini')


class ConfigError(Exception):
    """Base class for configuration errors."""
    pass


def read_config():
    """
    Reads the configuration file from ~/.config/ceph-test-dashboard.ini
    and returns a dictionary of sections.
    """
    config_path = os.path.expanduser(CONFIG_FILE)
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
