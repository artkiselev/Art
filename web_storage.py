from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from questionnaire import QUESTIONNAIRE_VERSION


@dataclass
class WebSession:
    session_id: str
    access_code: str
    current_index: int
    answers: dict[str, str]
    status: str
    updated_at: str
    version: int = QUESTIONNAIRE_VERSION


class WebStorage:
    def __init__(self, database_path: Path):
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.database_path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS web_access_codes (
                    code TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    first_used_at TEXT,
                    last_used_at TEXT,
                    session_id TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS web_sessions (
                    session_id TEXT PRIMARY KEY,
                    access_code TEXT NOT NULL,
                    current_index INTEGER NOT NULL DEFAULT 0,
                    answers_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'collecting',
                    updated_at TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1
                )
                """
            )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def import_codes(self, codes: list[str]) -> int:
        now = self._now()
        inserted = 0
        with self._connect() as conn:
            for code in codes:
                code = code.strip().upper()
                if not code:
                    continue
                cursor = conn.execute(
                    "INSERT OR IGNORE INTO web_access_codes (code, created_at) VALUES (?, ?)",
                    (code, now),
                )
                inserted += cursor.rowcount
        return inserted

    def get_or_create_session(self, code: str, session_id: str) -> WebSession | None:
        code = code.strip().upper()
        now = self._now()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT code, session_id FROM web_access_codes WHERE code = ?",
                (code,),
            ).fetchone()
            if not row:
                return None
            existing_session_id = row[1] or session_id
            session = self.get_session(existing_session_id)
            if session:
                conn.execute(
                    "UPDATE web_access_codes SET last_used_at = ? WHERE code = ?",
                    (now, code),
                )
                return session
            session = WebSession(existing_session_id, code, 0, {}, "collecting", now, QUESTIONNAIRE_VERSION)
            conn.execute(
                """
                INSERT INTO web_sessions (session_id, access_code, current_index, answers_json, status, updated_at, version)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session.session_id,
                    session.access_code,
                    session.current_index,
                    json.dumps(session.answers, ensure_ascii=False),
                    session.status,
                    session.updated_at,
                    session.version,
                ),
            )
            conn.execute(
                """
                UPDATE web_access_codes
                SET first_used_at = COALESCE(first_used_at, ?),
                    last_used_at = ?,
                    session_id = ?
                WHERE code = ?
                """,
                (now, now, session.session_id, code),
            )
            return session

    def get_session(self, session_id: str) -> WebSession | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT session_id, access_code, current_index, answers_json, status, updated_at, version
                FROM web_sessions
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
        if not row:
            return None
        return WebSession(
            session_id=row[0],
            access_code=row[1],
            current_index=row[2],
            answers=json.loads(row[3]),
            status=row[4],
            updated_at=row[5],
            version=row[6],
        )

    def save_session(self, session: WebSession) -> None:
        session.updated_at = self._now()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE web_sessions
                SET current_index = ?,
                    answers_json = ?,
                    status = ?,
                    updated_at = ?,
                    version = ?
                WHERE session_id = ?
                """,
                (
                    session.current_index,
                    json.dumps(session.answers, ensure_ascii=False),
                    session.status,
                    session.updated_at,
                    session.version,
                    session.session_id,
                ),
            )

    def reset_session(self, old_session: WebSession, new_session_id: str) -> WebSession:
        now = self._now()
        session = WebSession(new_session_id, old_session.access_code, 0, {}, "collecting", now, QUESTIONNAIRE_VERSION)
        with self._connect() as conn:
            conn.execute("DELETE FROM web_sessions WHERE session_id = ?", (old_session.session_id,))
            conn.execute(
                """
                INSERT INTO web_sessions (session_id, access_code, current_index, answers_json, status, updated_at, version)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session.session_id,
                    session.access_code,
                    session.current_index,
                    json.dumps(session.answers, ensure_ascii=False),
                    session.status,
                    session.updated_at,
                    session.version,
                ),
            )
            conn.execute(
                "UPDATE web_access_codes SET session_id = ?, last_used_at = ? WHERE code = ?",
                (session.session_id, now, session.access_code),
            )
        return session
