"""Report stats helpers backed by a shared Paddles data source."""

from __future__ import annotations

try:
    from libs.paddle import Paddles as DataSource
except Exception:
    class DataSource:
        """Fallback base when Paddles is unavailable."""

        def __init__(self, *args, **kwargs) -> None:
            pass


__all__ = ["DataSource"]
