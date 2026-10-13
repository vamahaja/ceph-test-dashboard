"""Persistent on-disk data under ``[storage] data_dir`` (PVC in OpenShift)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from libs.config import get_data_dir

_LOG = logging.getLogger(__name__)

_MARKER = ".dashboard-data"


def ensure_data_dir() -> Path:
    """Create the data directory and write a one-time marker file."""
    root = get_data_dir()
    root.mkdir(parents=True, exist_ok=True)
    marker = root / _MARKER
    if not marker.is_file():
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        marker.write_text(
            f"ceph-test-dashboard data volume\ninitialized={stamp}\n",
            encoding="utf-8",
        )
        _LOG.info("Initialized data directory at %s", root)
    return root


def mail_sqlite_path() -> Path:
    """Path to the mail dedup SQLite file (under ``data_dir`` unless overridden)."""
    from libs.config import get_digest_config

    return Path(get_digest_config()["sqlite_path"])
