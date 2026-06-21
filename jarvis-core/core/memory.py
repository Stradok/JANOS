import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from core.config import Config


class ShortTermMemory:
    def __init__(self, max_turns: int = 50):
        self.max_turns = max_turns
        self.history: list[dict[str, str]] = []

    def add(self, role: str, content: str) -> None:
        self.history.append({"role": role, "content": content})
        if len(self.history) > self.max_turns:
            self.history.pop(0)

    def get_context(self, limit: int | None = None) -> list[dict[str, str]]:
        if limit:
            return self.history[-limit:]
        return self.history

    def clear(self) -> None:
        self.history.clear()


class LongTermMemory:
    def __init__(self, config: Config | None = None):
        self.config = config or Config()
        self.base = Path(self.config.get("memory.path", str(self.config.base / "memory")))
        self.base.mkdir(parents=True, exist_ok=True)
        self.db_path = str(self.base / "long_term.db")
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT UNIQUE,
                    value TEXT,
                    tags TEXT,
                    created_at TEXT,
                    updated_at TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT UNIQUE,
                    summary TEXT,
                    created_at TEXT
                )
            """)

    def save(self, key: str, value: str, tags: list[str] | None = None) -> None:
        now = datetime.now(tz=timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO memories (key, value, tags, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET value=?, tags=?, updated_at=?""",
                (key, value, json.dumps(tags or []), now, now, value, json.dumps(tags or []), now),
            )

    def get(self, key: str) -> str | None:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT value FROM memories WHERE key = ?", (key,)
            ).fetchone()
            return row[0] if row else None

    def search(self, query: str) -> list[dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT key, value, tags, created_at FROM memories WHERE key LIKE ? OR value LIKE ?",
                (f"%{query}%", f"%{query}%"),
            ).fetchall()
            return [
                {"key": r[0], "value": r[1], "tags": json.loads(r[2] or "[]"), "created_at": r[3]}
                for r in rows
            ]

    def save_session(self, session_id: str, summary: str) -> None:
        now = datetime.now(tz=timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO sessions (session_id, summary, created_at) VALUES (?, ?, ?)",
                (session_id, summary, now),
            )


class Memory:
    def __init__(self, config: Config | None = None):
        self.short = ShortTermMemory()
        self.long = LongTermMemory(config)
