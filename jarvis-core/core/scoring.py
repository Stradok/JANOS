import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from core.config import Config


class ScoringEngine:
    def __init__(self, config: Config | None = None):
        self.config = config or Config()
        base = Path(self.config.get("memory.path", str(self.config.base / "memory")))
        base.mkdir(parents=True, exist_ok=True)
        self.db_path = str(base / "scoring.db")
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS action_scores (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action_name TEXT NOT NULL,
                    context_hash TEXT,
                    utility_score REAL DEFAULT 0.0,
                    success_count INTEGER DEFAULT 0,
                    failure_count INTEGER DEFAULT 0,
                    last_used TEXT,
                    created_at TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS feedback_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    action_name TEXT,
                    outcome TEXT,
                    score_delta REAL,
                    user_feedback TEXT,
                    created_at TEXT
                )
            """)

    def record_action(
        self, action_name: str, success: bool, context_hash: str = "", user_feedback: str = ""
    ) -> float:
        now = datetime.now(tz=timezone.utc).isoformat()
        delta = 1.0 if success else -0.5
        with sqlite3.connect(self.db_path) as conn:
            existing = conn.execute(
                "SELECT utility_score, success_count, failure_count FROM action_scores WHERE action_name = ?",
                (action_name,),
            ).fetchone()
            if existing:
                score, sc, fc = existing
                sc = sc + 1 if success else sc
                fc = fc if success else fc + 1
                new_score = max(-5.0, min(10.0, score + delta))
                conn.execute(
                    """UPDATE action_scores
                       SET utility_score=?, success_count=?, failure_count=?, last_used=?
                       WHERE action_name=?""",
                    (new_score, sc, fc, now, action_name),
                )
            else:
                conn.execute(
                    """INSERT INTO action_scores
                       (action_name, context_hash, utility_score, success_count, failure_count, last_used, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (action_name, context_hash, delta, 1 if success else 0, 0 if success else 1, now, now),
                )
            conn.execute(
                """INSERT INTO feedback_log
                   (action_name, outcome, score_delta, user_feedback, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (action_name, "success" if success else "failure", delta, user_feedback, now),
            )
        return delta

    def get_score(self, action_name: str) -> float:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT utility_score FROM action_scores WHERE action_name = ?",
                (action_name,),
            ).fetchone()
            return row[0] if row else 0.0

    def get_ranked_actions(self) -> list[dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT action_name, utility_score, success_count, failure_count, last_used "
                "FROM action_scores ORDER BY utility_score DESC"
            ).fetchall()
            return [
                {
                    "action": r[0],
                    "score": r[1],
                    "successes": r[2],
                    "failures": r[3],
                    "last_used": r[4],
                }
                for r in rows
            ]

    def provide_feedback(self, session_id: str, action_name: str, rating: int) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO feedback_log
                   (session_id, action_name, outcome, score_delta, user_feedback, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (session_id, action_name, "user_feedback", float(rating), str(rating),
                 datetime.now(tz=timezone.utc).isoformat()),
            )
