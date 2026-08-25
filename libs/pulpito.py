"""Pulpito URL helpers shared by dashboard pages.

Pages should import from here instead of calling ``get_pulpito_url()``
and building ``LinkColumn`` configs locally.

    from libs.pulpito import (
        base_url,
        run_url,
        job_url,
        run_link_column,
        job_link_column,
    )

    pulpito = base_url()
    df["name"] = df["name"].map(lambda n: run_url(n, base=pulpito))
    st.dataframe(df, column_config=run_link_column("name", "Run", base=pulpito))
"""

from __future__ import annotations

import streamlit as st

from libs.config import get_pulpito_url
from libs.exceptions import ConfigError

_RUN_DISPLAY_TEXT = r"([^/]+)/$"
_JOB_DISPLAY_TEXT = r"(\d+)$"


def base_url() -> str | None:
    """Return the configured Pulpito origin, or ``None`` if unset."""
    try:
        base = get_pulpito_url()
    except ConfigError:
        return None
    return base.rstrip("/") if base else None


def run_url(run_name: str, *, base: str | None = None) -> str:
    """Return ``{base}/{run_name}/``, or the bare name if Pulpito is unset."""
    root = base_url() if base is None else base
    name = str(run_name or "")
    if not root or not name:
        return name
    return f"{root}/{name}/"


def job_url(run_name: str, job_id: object, *, base: str | None = None) -> str:
    """Return ``{base}/{run_name}/{job_id}``, or the bare id if Pulpito is unset."""
    root = base_url() if base is None else base
    name = str(run_name or "")
    jid = str(job_id or "")
    if not root or not name or not jid:
        return jid
    return f"{root}/{name}/{jid}"


def run_link_column(
    column: str,
    label: str | None = None,
    *,
    base: str | None = None,
) -> dict:
    """Streamlit ``LinkColumn`` config for a column of ``run_url`` values."""
    root = base_url() if base is None else base
    if not root:
        return {}
    return {
        column: st.column_config.LinkColumn(
            label=label or column,
            display_text=_RUN_DISPLAY_TEXT,
        )
    }


def job_link_column(
    column: str,
    label: str | None = None,
    *,
    base: str | None = None,
) -> dict:
    """Streamlit ``LinkColumn`` config for a column of ``job_url`` values."""
    root = base_url() if base is None else base
    if not root:
        return {}
    return {
        column: st.column_config.LinkColumn(
            label=label or column,
            display_text=_JOB_DISPLAY_TEXT,
        )
    }
