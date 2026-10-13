"""SQLite-backed deduplication and sent-mail archive (on PVC in production)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class SentMailRecord:
    id: int
    sent_at: datetime
    kind: str
    branch: str
    subject: str
    body_plain: str
    body_html: str
    recipients: str


@dataclass
class MailState:
    weekly_sent: dict[str, str] = field(default_factory=dict)
    daily_smoke_sent: dict[str, str] = field(default_factory=dict)
    _db_path: Path | None = field(default=None, repr=False)

    @staticmethod
    def _ensure_schema(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS weekly_sent (
                branch TEXT PRIMARY KEY,
                window_end TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_smoke_sent (
                branch TEXT NOT NULL,
                utc_day TEXT NOT NULL,
                PRIMARY KEY (branch, utc_day)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sent_mail (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sent_at TEXT NOT NULL,
                kind TEXT NOT NULL,
                branch TEXT NOT NULL,
                subject TEXT NOT NULL,
                body_plain TEXT NOT NULL,
                body_html TEXT NOT NULL,
                recipients TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sent_mail_sent_at ON sent_mail (sent_at DESC)"
        )

    @classmethod
    def load(cls, path: str | Path) -> MailState:
        db_path = Path(path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path)
        try:
            cls._ensure_schema(conn)
            weekly = {
                row[0]: row[1]
                for row in conn.execute("SELECT branch, window_end FROM weekly_sent")
            }
            daily = {
                f"{row[0]}:{row[1]}": row[1]
                for row in conn.execute("SELECT branch, utc_day FROM daily_smoke_sent")
            }
            conn.commit()
        finally:
            conn.close()
        return cls(weekly_sent=weekly, daily_smoke_sent=daily, _db_path=db_path)

    def save(self, path: str | Path | None = None) -> None:
        db_path = Path(path) if path is not None else self._db_path
        if db_path is None:
            raise ValueError("mail state database path not set")
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path)
        try:
            self._ensure_schema(conn)
            conn.execute("DELETE FROM weekly_sent")
            conn.executemany(
                "INSERT INTO weekly_sent (branch, window_end) VALUES (?, ?)",
                list(self.weekly_sent.items()),
            )
            conn.execute("DELETE FROM daily_smoke_sent")
            daily_rows = [
                (key.split(":", 1)[0], value)
                for key, value in self.daily_smoke_sent.items()
            ]
            conn.executemany(
                "INSERT INTO daily_smoke_sent (branch, utc_day) VALUES (?, ?)",
                daily_rows,
            )
            conn.commit()
            self._db_path = db_path
        finally:
            conn.close()

    def record_sent(
        self,
        *,
        kind: str,
        branch: str,
        subject: str,
        body_plain: str,
        body_html: str,
        recipients: list[str],
    ) -> None:
        if self._db_path is None:
            raise ValueError("mail state database path not set")
        sent_at = datetime.now(timezone.utc).isoformat()
        conn = sqlite3.connect(self._db_path)
        try:
            self._ensure_schema(conn)
            conn.execute(
                """
                INSERT INTO sent_mail (
                    sent_at, kind, branch, subject,
                    body_plain, body_html, recipients
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sent_at,
                    kind,
                    branch,
                    subject,
                    body_plain,
                    body_html,
                    ", ".join(recipients),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    @classmethod
    def list_sent_mail(
        cls,
        path: str | Path,
        *,
        kind: str | None = None,
        limit: int = 100,
    ) -> list[SentMailRecord]:
        db_path = Path(path)
        if not db_path.is_file():
            return []
        conn = sqlite3.connect(db_path)
        try:
            cls._ensure_schema(conn)
            if kind:
                rows = conn.execute(
                    """
                    SELECT id, sent_at, kind, branch, subject,
                           body_plain, body_html, recipients
                    FROM sent_mail
                    WHERE kind = ?
                    ORDER BY sent_at DESC
                    LIMIT ?
                    """,
                    (kind, max(1, int(limit))),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id, sent_at, kind, branch, subject,
                           body_plain, body_html, recipients
                    FROM sent_mail
                    ORDER BY sent_at DESC
                    LIMIT ?
                    """,
                    (max(1, int(limit)),),
                ).fetchall()
        finally:
            conn.close()
        out: list[SentMailRecord] = []
        for row in rows:
            try:
                sent_at = datetime.fromisoformat(row[1])
            except ValueError:
                sent_at = datetime.now(timezone.utc)
            out.append(
                SentMailRecord(
                    id=int(row[0]),
                    sent_at=sent_at,
                    kind=str(row[2]),
                    branch=str(row[3]),
                    subject=str(row[4]),
                    body_plain=str(row[5]),
                    body_html=str(row[6]),
                    recipients=str(row[7]),
                )
            )
        return out

    def weekly_window_end(self, branch: str) -> datetime | None:
        raw = self.weekly_sent.get(branch)
        if not raw or "-W" in raw:
            return None
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return None

    def weekly_already_sent(self, branch: str, window_end: datetime) -> bool:
        return self.weekly_sent.get(branch) == window_end.isoformat()

    def mark_weekly_sent(self, branch: str, window_end: datetime) -> None:
        self.weekly_sent[branch] = window_end.isoformat()

    def daily_smoke_already_sent(self, branch: str, utc_day: str) -> bool:
        return self.daily_smoke_sent.get(f"{branch}:{utc_day}") is not None

    def mark_daily_smoke_sent(self, branch: str, utc_day: str) -> None:
        self.daily_smoke_sent[f"{branch}:{utc_day}"] = utc_day
