"""
Feedback Module — closes the self-improvement loop.

After every task JAN completes, this module:
  1. Registers the task as pending feedback
  2. Accepts user ratings (1-5) via API or voice
  3. Converts ratings → outcome_score and feeds into skill_memory
  4. Surfaces worst-performing agents for targeted improvement
  5. Tracks a running quality baseline across all interactions

Rating scale:
  1 — Completely wrong / didn't work
  2 — Partially worked but major issues
  3 — Acceptable but could be better
  4 — Good, worked as expected
  5 — Perfect
"""

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from .base import ModuleBase


class FeedbackModule(ModuleBase):
    """Collects user ratings and feeds them back into the learning engine."""

    def __init__(self):
        super().__init__("feedback")
        self.db_path = Path("memory/jarvis_memory.db")
        self._init_db()
        self.learning_engine = None   # wired from __init__.py

    def _init_db(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS task_feedback (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id       TEXT,
                    timestamp     TEXT,
                    user_input    TEXT,
                    agent_used    TEXT,
                    modules_used  TEXT,
                    rating        INTEGER,
                    comment       TEXT,
                    response_text TEXT,
                    outcome_score REAL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS pending_feedback (
                    task_id       TEXT PRIMARY KEY,
                    timestamp     TEXT,
                    user_input    TEXT,
                    agent_used    TEXT,
                    modules_used  TEXT,
                    response_text TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_feedback_agent ON task_feedback(agent_used)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_feedback_rating ON task_feedback(rating)")

    # ── Public API ────────────────────────────────────────────────────

    def register_task(self, task_id: str, user_input: str, agent_used: str,
                      modules_used: list, response_text: str):
        """Call this after every completed task to mark it as awaiting feedback."""
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO pending_feedback VALUES (?, ?, ?, ?, ?, ?)",
                (task_id, datetime.now().isoformat(), user_input[:500],
                 agent_used, json.dumps(modules_used), response_text[:1000])
            )

    def process(self, input_data: dict) -> dict:
        action = input_data.get("action", "stats")
        if action == "collect":
            return self._collect(input_data)
        if action == "register":
            self.register_task(
                input_data.get("task_id", str(uuid.uuid4())),
                input_data.get("user_input", ""),
                input_data.get("agent_used", ""),
                input_data.get("modules_used", []),
                input_data.get("response_text", ""),
            )
            return {"status": "ok"}
        if action == "stats":
            return self._stats()
        if action == "worst":
            return self._worst_performers(input_data.get("limit", 5))
        if action == "pending":
            return self._pending()
        if action == "history":
            return self._history(input_data.get("limit", 20),
                                 input_data.get("agent"))
        return {"error": f"Unknown action: {action}"}

    # ── Feedback Collection ───────────────────────────────────────────

    def _collect(self, input_data: dict) -> dict:
        task_id = input_data.get("task_id")
        rating  = input_data.get("rating")
        comment = input_data.get("comment", "")

        if not task_id:
            return {"error": "task_id is required"}
        if rating is None:
            return {"error": "rating (1-5) is required"}
        try:
            rating = int(rating)
        except (TypeError, ValueError):
            return {"error": "rating must be an integer 1-5"}
        if not 1 <= rating <= 5:
            return {"error": "rating must be between 1 and 5"}

        # Pull pending task info (best-effort — task_id may not be registered)
        with sqlite3.connect(str(self.db_path)) as conn:
            row = conn.execute(
                "SELECT user_input, agent_used, modules_used, response_text "
                "FROM pending_feedback WHERE task_id = ?", (task_id,)
            ).fetchone()

        user_input, agent_used, modules_json, response_text = \
            ("", "", "[]", "") if not row else row
        modules_used = json.loads(modules_json)

        # Map rating 1-5 → outcome_score -1.0..+1.0
        # 1→-1.0, 2→-0.5, 3→0.0, 4→+0.5, 5→+1.0
        outcome_score = (rating - 3) / 2.0

        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                "INSERT INTO task_feedback "
                "(task_id, timestamp, user_input, agent_used, modules_used, rating, comment, response_text, outcome_score) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (task_id, datetime.now().isoformat(), user_input, agent_used,
                 modules_json, rating, comment, response_text, outcome_score)
            )
            conn.execute("DELETE FROM pending_feedback WHERE task_id = ?", (task_id,))

        # Feed outcome back into skill_memory
        if self.learning_engine and agent_used:
            self._update_skill_score(agent_used, modules_used, rating, comment, outcome_score)

        praise = rating >= 4
        return {
            "status": "ok",
            "task_id": task_id,
            "rating": rating,
            "outcome_score": outcome_score,
            "message": "Thank you Sir, noted." if praise else
                       ("I'll do better next time." if rating >= 3 else
                        "Understood — I'll analyse what went wrong."),
        }

    def _update_skill_score(self, agent_used: str, modules_used: list,
                             rating: int, comment: str, outcome_score: float):
        """Push feedback rating into learning engine skill memory."""
        if not self.learning_engine:
            return
        outcome = "success" if rating >= 4 else ("partial" if rating == 3 else "error")
        try:
            self.learning_engine.process({
                "action": "record_skill",
                "agent": agent_used,
                "tool": "task_outcome",
                "tool_action": "user_rated",
                "input_pattern": {"rating": rating, "modules": modules_used},
                "outcome": outcome,
                "error_msg": comment if rating < 3 else "",
                "correction": f"User rated {rating}/5: {comment}" if comment else f"User rated {rating}/5",
            })
        except Exception:
            pass

    # ── Reporting ─────────────────────────────────────────────────────

    def _stats(self) -> dict:
        with sqlite3.connect(str(self.db_path)) as conn:
            total   = conn.execute("SELECT COUNT(*) FROM task_feedback").fetchone()[0]
            avg     = conn.execute("SELECT AVG(rating) FROM task_feedback").fetchone()[0] or 0.0
            pending = conn.execute("SELECT COUNT(*) FROM pending_feedback").fetchone()[0]
            by_agent = conn.execute(
                "SELECT agent_used, AVG(rating), COUNT(*) FROM task_feedback "
                "GROUP BY agent_used ORDER BY AVG(rating) DESC"
            ).fetchall()
            dist = conn.execute(
                "SELECT rating, COUNT(*) FROM task_feedback GROUP BY rating ORDER BY rating"
            ).fetchall()
        return {
            "total_rated":      total,
            "pending_feedback": pending,
            "avg_rating":       round(avg, 2),
            "by_agent":         [{"agent": r[0], "avg": round(r[1], 2), "count": r[2]} for r in by_agent],
            "distribution":     {str(r[0]): r[1] for r in dist},
        }

    def _worst_performers(self, limit: int = 5) -> dict:
        with sqlite3.connect(str(self.db_path)) as conn:
            rows = conn.execute(
                "SELECT agent_used, AVG(rating), COUNT(*), "
                "GROUP_CONCAT(comment, ' | ') "
                "FROM task_feedback "
                "GROUP BY agent_used HAVING COUNT(*) >= 2 "
                "ORDER BY AVG(rating) ASC LIMIT ?",
                (limit,)
            ).fetchall()
        return {
            "worst_performers": [
                {"agent": r[0], "avg_rating": round(r[1], 2),
                 "count": r[2], "comments": (r[3] or "")[:300]}
                for r in rows
            ]
        }

    def _pending(self) -> dict:
        with sqlite3.connect(str(self.db_path)) as conn:
            rows = conn.execute(
                "SELECT task_id, timestamp, user_input, agent_used "
                "FROM pending_feedback ORDER BY timestamp DESC LIMIT 10"
            ).fetchall()
        return {"pending": [{"task_id": r[0], "ts": r[1],
                              "input": r[2][:80], "agent": r[3]} for r in rows]}

    def _history(self, limit: int = 20, agent: str | None = None) -> dict:
        with sqlite3.connect(str(self.db_path)) as conn:
            if agent:
                rows = conn.execute(
                    "SELECT task_id, timestamp, user_input, agent_used, rating, comment "
                    "FROM task_feedback WHERE agent_used = ? ORDER BY id DESC LIMIT ?",
                    (agent, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT task_id, timestamp, user_input, agent_used, rating, comment "
                    "FROM task_feedback ORDER BY id DESC LIMIT ?",
                    (limit,)
                ).fetchall()
        return {"history": [{"task_id": r[0], "ts": r[1], "input": r[2][:80],
                              "agent": r[3], "rating": r[4], "comment": r[5]}
                             for r in rows]}
