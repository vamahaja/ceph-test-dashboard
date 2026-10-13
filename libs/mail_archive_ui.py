"""Streamlit UI for sent-mail archive pages."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from libs.config import get_digest_config
from libs.mail_state import MailState


def render_sent_mail_archive(
    *,
    page_title: str,
    report_kind: str,
    schedule_line: str,
    intro: str,
) -> None:
    st.markdown(
        f"<h1 style='text-align: center;'>{page_title}</h1>",
        unsafe_allow_html=True,
    )
    st.markdown(intro)

    try:
        cfg = get_digest_config()
        enabled = cfg.get("enabled")
    except Exception as exc:
        st.warning(f"Mail config not loaded: {exc}")
        st.stop()

    if enabled:
        st.success("Outbound digest mail is **enabled**.")
        st.markdown(schedule_line)
    else:
        st.info("Outbound digest mail is **disabled** (`[digest] enabled = false`).")

    st.divider()
    st.subheader("Sent mail archive")

    sqlite_path = cfg.get("sqlite_path", "")
    history = (
        MailState.list_sent_mail(sqlite_path, kind=report_kind, limit=200)
        if sqlite_path
        else []
    )

    if not history:
        st.info(
            "No sent messages recorded yet for this report. Entries appear after "
            "the scheduler or `ceph-test-dashboard-digest` successfully sends mail."
        )
        return

    summary = pd.DataFrame(
        [
            {
                "Sent (UTC)": r.sent_at.strftime("%Y-%m-%d %H:%M"),
                "Branch": r.branch,
                "Subject": r.subject,
                "To": r.recipients,
            }
            for r in history
        ]
    )
    st.dataframe(summary, width="stretch", hide_index=True)

    labels = [
        f"{r.sent_at.strftime('%Y-%m-%d %H:%M')} · {r.branch} · {r.subject}"
        for r in history
    ]
    pick = st.selectbox("View message", range(len(history)), format_func=lambda i: labels[i])
    row = history[pick]

    st.markdown(f"**Subject:** {row.subject}")
    st.caption(f"Recipients: {row.recipients}")
    st.markdown(row.body_html, unsafe_allow_html=True)
