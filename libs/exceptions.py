"""Custom exceptions."""


class ConfigError(Exception):
    """
    Raised when the configuration is invalid.
    """
    pass

class PaddlesAPIError(Exception):
    """
    Raised when the Paddles API returns an error.
    """
    pass

class LLMError(Exception):
    """
    Raised when the LLM is misconfigured or a request fails.
    """
    pass