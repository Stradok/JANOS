"""Scoring → routing feedback loop and agent selection optimizer.

Closes the loop: scoring engine data feeds back into routing decisions.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.config import Config


class RoutingEngine:
    """Selects agents and tools based on historical success rates."""

    def __init__(self, config: Config | None = None):
        self.config = config or Config()
        base = Path(self.config.get("memory.path", str(self.config.base / "memory")))
        base.mkdir(parents=True, exist_ok=True)
        self.db_path = str(base / "routing.db")
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS agent_scores (
                    agent_name TEXT PRIMARY KEY,
                    success_count INTEGER DEFAULT 0,
                    failure_count INTEGER DEFAULT 0,
                    total_runtime_ms INTEGER DEFAULT 0,
                    avg_score REAL DEFAULT 0.0,
                    last_used TEXT,
                    created_at TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS model_scores (
                    model_name TEXT PRIMARY KEY,
                    task_type TEXT,
                    success_count INTEGER DEFAULT 0,
                    failure_count INTEGER DEFAULT 0,
                    avg_score REAL DEFAULT 0.0,
                    last_used TEXT
                )
            """)

    def record_agent_result(
        self, agent_name: str, success: bool, runtime_ms: int = 0, score: float = 0.0
    ):
        now = datetime.now(tz=timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            existing = conn.execute(
                "SELECT success_count, failure_count, total_runtime_ms, avg_score FROM agent_scores WHERE agent_name = ?",
                (agent_name,),
            ).fetchone()
            if existing:
                sc, fc, rt, old_avg = existing
                total_old = sc + fc
                sc += 1 if success else 0
                fc += 0 if success else 1
                rt += runtime_ms
                total_new = sc + fc
                avg = (old_avg * total_old + score) / max(1, total_new)
                conn.execute(
                    """UPDATE agent_scores SET success_count=?, failure_count=?,
                       total_runtime_ms=?, avg_score=?, last_used=? WHERE agent_name=?""",
                    (sc, fc, rt, avg, now, agent_name),
                )
            else:
                conn.execute(
                    "INSERT INTO agent_scores VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (agent_name, 1 if success else 0, 0 if success else 1, runtime_ms, score, now, now),
                )

    def record_model_result(
        self, model_name: str, task_type: str, success: bool, score: float = 0.0
    ):
        now = datetime.now(tz=timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            existing = conn.execute(
                "SELECT success_count, failure_count FROM model_scores WHERE model_name = ? AND task_type = ?",
                (model_name, task_type),
            ).fetchone()
            if existing:
                sc, fc = existing
                sc += 1 if success else 0
                fc += 0 if success else 1
                avg = (score + (sc + fc)) / max(1, sc + fc)
                conn.execute(
                    """UPDATE model_scores SET success_count=?, failure_count=?,
                       avg_score=?, last_used=? WHERE model_name=? AND task_type=?""",
                    (sc, fc, avg, now, model_name, task_type),
                )
            else:
                conn.execute(
                    "INSERT INTO model_scores VALUES (?, ?, ?, ?, ?, ?)",
                    (model_name, task_type, 1 if success else 0, 0 if success else 1, score, now),
                )

    def get_best_agent(self, task_type: str = "general") -> str:
        """Get the highest-scoring agent for a task type."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT agent_name FROM agent_scores ORDER BY avg_score DESC LIMIT 1"
            ).fetchone()
            return row[0] if row else "executor"

    def get_best_model(self, task_type: str) -> str:
        """Get the highest-scoring model for a task type."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT model_name FROM model_scores WHERE task_type = ? ORDER BY avg_score DESC LIMIT 1",
                (task_type,),
            ).fetchone()
            return row[0] if row else ""

    def get_agent_rankings(self) -> list[dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT agent_name, success_count, failure_count, avg_score, last_used "
                "FROM agent_scores ORDER BY avg_score DESC"
            ).fetchall()
            return [
                {
                    "agent": r[0],
                    "successes": r[1],
                    "failures": r[2],
                    "avg_score": round(r[3], 2),
                    "last_used": r[4],
                }
                for r in rows
            ]

    def get_model_rankings(self) -> list[dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT model_name, task_type, success_count, failure_count, avg_score "
                "FROM model_scores ORDER BY avg_score DESC"
            ).fetchall()
            return [
                {
                    "model": r[0],
                    "task_type": r[1],
                    "successes": r[2],
                    "failures": r[3],
                    "avg_score": round(r[4], 2),
                }
                for r in rows
            ]
