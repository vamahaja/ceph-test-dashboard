import configparser
import os

CONFIG_FILE = os.path.expanduser('~/.config/ceph-test-dashboard.ini')


class ConfigError(Exception):
    """Base class for configuration errors."""
    pass


def read_config():
    """
    Reads the configuration file from ~/.config/ceph-test-dashboard.ini
    and returns a ConfigParser object.
    """
    config_path = os.path.expanduser(CONFIG_FILE)
    if not os.path.exists(config_path):
        raise FileNotFoundError(
            f"Configuration file not found at {config_path}"
        )

    return configparser.ConfigParser().read(config_path)


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

    return paddles.get("paddles", "base_url")
