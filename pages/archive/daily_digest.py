from libs.defaults import DEFAULT_DIGEST_DAILY_REPORT_ANCHOR_HOUR
from libs.mail_archive_ui import render_sent_mail_archive

render_sent_mail_archive(
    page_title="Daily digest",
    report_kind="daily_smoke",
    schedule_line=(
        f"Scheduled **daily {DEFAULT_DIGEST_DAILY_REPORT_ANCHOR_HOUR:02d}:00 UTC** "
        "when smoke runs fail or die. Use **Reports → Nightly** for live status."
    ),
    intro=(
        "Archive of **daily smoke failure** emails. "
        "Reports are defined in `templates/reports/daily_smoke.toml`."
    ),
)
