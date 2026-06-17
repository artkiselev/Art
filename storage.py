from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class Session:
    chat_id: int
    current_index: int
    answers: dict[str, str]
    completed: bool
    updated_at: str


class Storage:
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
                CREATE TABLE IF NOT EXISTS sessions (
                    chat_id INTEGER PRIMARY KEY,
                    current_index INTEGER NOT NULL DEFAULT 0,
                    answers_json TEXT NOT NULL DEFAULT '{}',
                    completed INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                )
                """
            )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def get_or_create(self, chat_id: int) -> Session:
        session = self.get(chat_id)
        if session:
            return session
        session = Session(chat_id, 0, {}, False, self._now())
        self.save(session)
        return session

    def get(self, chat_id: int) -> Session | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT chat_id, current_index, answers_json, completed, updated_at FROM sessions WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
        if not row:
            return None
        return Session(
            chat_id=row[0],
            current_index=row[1],
            answers=json.loads(row[2]),
            completed=bool(row[3]),
            updated_at=row[4],
        )

    def save(self, session: Session) -> None:
        session.updated_at = self._now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions (chat_id, current_index, answers_json, completed, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    current_index = excluded.current_index,
                    answers_json = excluded.answers_json,
                    completed = excluded.completed,
                    updated_at = excluded.updated_at
                """,
                (
                    session.chat_id,
                    session.current_index,
                    json.dumps(session.answers, ensure_ascii=False),
                    int(session.completed),
                    session.updated_at,
                ),
            )

    def reset(self, chat_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM sessions WHERE chat_id = ?", (chat_id,))
