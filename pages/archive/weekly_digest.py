from libs.defaults import DEFAULT_DIGEST_NIGHTLY_ANCHOR_HOUR
from libs.mail_archive_ui import render_sent_mail_archive

render_sent_mail_archive(
    page_title="Weekly digest",
    report_kind="weekly_digest",
    schedule_line=(
        f"Scheduled **Monday {DEFAULT_DIGEST_NIGHTLY_ANCHOR_HOUR:02d}:00 UTC** "
        "(one mail per release branch). Use **Reports → Nightly** for live status."
    ),
    intro=(
        "Archive of **weekly nightly digest** emails (health, failures, top reasons). "
        "Reports are defined in `templates/reports/weekly_digest.toml`."
    ),
)
