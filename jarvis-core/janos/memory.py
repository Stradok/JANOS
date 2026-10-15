"""Episodic memory, distilled lessons, and routing statistics.

Everything lives in one SQLite file. Retrieval is FTS5/BM25 rather than a
vector store: it needs no embedding model, no second download, and no extra
dependency, which keeps the whole system to the single LLM the user asked for.

Three things are remembered:
  episodes   - what happened, and how well it went
  lessons    - short generalisations distilled from episodes (self-learning)
  agent_stats- which agent actually succeeds at which kind of task (routing)
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS episodes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_id    TEXT UNIQUE NOT NULL,
    ts            TEXT NOT NULL,
    task          TEXT NOT NULL,
    task_type     TEXT DEFAULT 'general',
    plan          TEXT,
    agents        TEXT,
    tool_calls    TEXT,
    answer        TEXT,
    errors        TEXT,
    score         REAL DEFAULT 0.0,
    healed        INTEGER DEFAULT 0,
    duration_ms   INTEGER DEFAULT 0,
    meta          TEXT
);
CREATE INDEX IF NOT EXISTS idx_ep_type  ON episodes(task_type);
CREATE INDEX IF NOT EXISTS idx_ep_score ON episodes(score);
CREATE INDEX IF NOT EXISTS idx_ep_ts    ON episodes(ts);

CREATE VIRTUAL TABLE IF NOT EXISTS episodes_fts USING fts5(
    episode_id UNINDEXED, body
);

CREATE TABLE IF NOT EXISTS lessons (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint TEXT UNIQUE NOT NULL,
    ts         TEXT NOT NULL,
    task_type  TEXT DEFAULT 'general',
    lesson     TEXT NOT NULL,
    source     TEXT,
    hits       INTEGER DEFAULT 0,
    weight     REAL DEFAULT 1.0
);
CREATE VIRTUAL TABLE IF NOT EXISTS lessons_fts USING fts5(
    fingerprint UNINDEXED, body
);

CREATE TABLE IF NOT EXISTS agent_stats (
    agent      TEXT NOT NULL,
    task_type  TEXT NOT NULL,
    runs       INTEGER DEFAULT 0,
    total      REAL DEFAULT 0.0,
    avg_score  REAL DEFAULT 0.0,
    PRIMARY KEY (agent, task_type)
);

CREATE TABLE IF NOT EXISTS tool_stats (
    tool     TEXT PRIMARY KEY,
    calls    INTEGER DEFAULT 0,
    failures INTEGER DEFAULT 0
);
"""

_STOP = {
    "the", "a", "an", "and", "or", "but", "is", "are", "was", "were", "be",
    "to", "of", "in", "on", "for", "with", "how", "what", "why", "do", "does",
    "did", "can", "you", "i", "it", "this", "that", "my", "me", "please",
}


def _fts_query(text: str) -> str:
    """Turn arbitrary user text into a safe FTS5 MATCH expression.

    Raw user input is never safe to interpolate: characters like ", *, ^, -,
    and NEAR are FTS5 operators and raise OperationalError.
    """
    words = re.findall(r"[A-Za-z0-9_]+", (text or "").lower())
    terms = [w for w in words if len(w) > 2 and w not in _STOP][:12]
    if not terms:
        terms = [w for w in words if w][:6]
    if not terms:
        return ""
    return " OR ".join(f'"{w}"' for w in dict.fromkeys(terms))


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")


class Memory:
    """Thread-safe SQLite store. Cheap enough to call on every turn."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -------------------------------------------------------------- episodes

    def remember(
        self,
        *,
        task: str,
        answer: str,
        task_type: str = "general",
        plan: list[Any] | None = None,
        agents: list[str] | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
        errors: list[str] | None = None,
        score: float = 0.0,
        healed: int = 0,
        duration_ms: int = 0,
        meta: dict[str, Any] | None = None,
    ) -> str:
        stamp = _now()
        digest = hashlib.sha1(f"{task}{stamp}".encode()).hexdigest()[:12]
        episode_id = f"ep_{stamp[:10]}_{digest}"

        body = "\n".join(
            filter(None, [task, " ".join(agents or []), answer[:1200], " ".join(errors or [])])
        )
        with self._lock:
            self._conn.execute(
                """INSERT OR REPLACE INTO episodes
                   (episode_id, ts, task, task_type, plan, agents, tool_calls,
                    answer, errors, score, healed, duration_ms, meta)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    episode_id, stamp, task, task_type,
                    json.dumps(plan or []), json.dumps(agents or []),
                    json.dumps(tool_calls or []), answer,
                    json.dumps(errors or []), float(score), int(healed),
                    int(duration_ms), json.dumps(meta or {}),
                ),
            )
            self._conn.execute(
                "INSERT INTO episodes_fts (episode_id, body) VALUES (?,?)",
                (episode_id, body),
            )
            self._conn.commit()
        return episode_id

    def recall(self, query: str, k: int = 4, *, min_score: float | None = None) -> list[dict[str, Any]]:
        """Most relevant past episodes, best-scoring first among close matches."""
        match = _fts_query(query)
        if not match:
            return []
        sql = """
            SELECT e.episode_id, e.task, e.answer, e.score, e.task_type,
                   e.errors, e.ts, bm25(episodes_fts) AS rank
            FROM episodes_fts
            JOIN episodes e ON e.episode_id = episodes_fts.episode_id
            WHERE episodes_fts MATCH ?
        """
        params: list[Any] = [match]
        if min_score is not None:
            sql += " AND e.score >= ?"
            params.append(min_score)
        sql += " ORDER BY rank LIMIT ?"
        params.append(k * 3)

        try:
            with self._lock:
                rows = self._conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError:
            return []

        out = [dict(r) for r in rows]
        # bm25 orders by textual closeness; prefer outcomes that actually worked.
        out.sort(key=lambda r: (-(r["score"] or 0.0), r["rank"]))
        for r in out:
            try:
                r["errors"] = json.loads(r["errors"] or "[]")
            except json.JSONDecodeError:
                r["errors"] = []
        return out[:k]

    def episode(self, episode_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM episodes WHERE episode_id=?", (episode_id,)
            ).fetchone()
        if not row:
            return None
        ep = dict(row)
        for f in ("plan", "agents", "tool_calls", "errors", "meta"):
            try:
                ep[f] = json.loads(ep[f] or "[]")
            except (json.JSONDecodeError, TypeError):
                pass
        return ep

    def recent(self, limit: int = 10) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT episode_id, ts, task, task_type, score, healed"
                " FROM episodes ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def unresolved(self, k: int = 5, threshold: float = 0.6) -> list[dict[str, Any]]:
        """Tasks that have never once been answered well.

        Distinct from `failures`: once a task has been retried successfully,
        it stops appearing here, so the autonomous loop does not keep
        re-attempting work it has already fixed.
        """
        with self._lock:
            rows = self._conn.execute(
                """SELECT task, task_type, MAX(score) AS best, COUNT(*) AS tries
                   FROM episodes
                   GROUP BY task
                   HAVING MAX(score) < ?
                   ORDER BY best ASC, tries ASC
                   LIMIT ?""",
                (threshold, k),
            ).fetchall()
        return [dict(r) for r in rows]

    def failures(self, k: int = 5) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT episode_id, task, errors, score FROM episodes"
                " WHERE score < 0.5 ORDER BY score ASC, id DESC LIMIT ?", (k,)
            ).fetchall()
        return [dict(r) for r in rows]

    # --------------------------------------------------------------- lessons

    def add_lesson(self, lesson: str, *, task_type: str = "general", source: str = "") -> bool:
        """Store a distilled lesson. Returns False if already known."""
        text = (lesson or "").strip()
        if len(text) < 12:
            return False
        norm = re.sub(r"[^a-z0-9 ]", "", text.lower())
        norm = re.sub(r"\s+", " ", norm).strip()
        fingerprint = hashlib.sha1(norm.encode()).hexdigest()[:16]

        with self._lock:
            exists = self._conn.execute(
                "SELECT 1 FROM lessons WHERE fingerprint=?", (fingerprint,)
            ).fetchone()
            if exists:
                self._conn.execute(
                    "UPDATE lessons SET weight = weight + 0.5 WHERE fingerprint=?",
                    (fingerprint,),
                )
                self._conn.commit()
                return False
            self._conn.execute(
                "INSERT INTO lessons (fingerprint, ts, task_type, lesson, source)"
                " VALUES (?,?,?,?,?)",
                (fingerprint, _now(), task_type, text, source),
            )
            self._conn.execute(
                "INSERT INTO lessons_fts (fingerprint, body) VALUES (?,?)",
                (fingerprint, f"{task_type} {text}"),
            )
            self._conn.commit()
        return True

    def lessons_for(self, query: str, k: int = 4) -> list[str]:
        match = _fts_query(query)
        rows: list[sqlite3.Row] = []
        if match:
            try:
                with self._lock:
                    rows = self._conn.execute(
                        """SELECT l.lesson, l.weight, l.fingerprint, bm25(lessons_fts) AS rank
                           FROM lessons_fts
                           JOIN lessons l ON l.fingerprint = lessons_fts.fingerprint
                           WHERE lessons_fts MATCH ? ORDER BY rank LIMIT ?""",
                        (match, k),
                    ).fetchall()
            except sqlite3.OperationalError:
                rows = []
        if not rows:  # cold start: fall back to the most reinforced lessons
            with self._lock:
                rows = self._conn.execute(
                    "SELECT lesson, weight, fingerprint FROM lessons"
                    " ORDER BY weight DESC, id DESC LIMIT ?", (k,)
                ).fetchall()
        if rows:
            with self._lock:
                self._conn.executemany(
                    "UPDATE lessons SET hits = hits + 1 WHERE fingerprint=?",
                    [(r["fingerprint"],) for r in rows],
                )
                self._conn.commit()
        return [r["lesson"] for r in rows]

    def all_lessons(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT lesson, task_type, weight, hits, ts FROM lessons"
                " ORDER BY weight DESC, id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------ statistics

    def record_agent(self, agent: str, task_type: str, score: float) -> None:
        """Update the running average for an agent on a task type."""
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO agent_stats (agent, task_type) VALUES (?,?)",
                (agent, task_type),
            )
            self._conn.execute(
                """UPDATE agent_stats
                   SET runs = runs + 1,
                       total = total + ?,
                       avg_score = (total + ?) / (runs + 1)
                   WHERE agent=? AND task_type=?""",
                (float(score), float(score), agent, task_type),
            )
            self._conn.commit()

    def record_tool(self, tool: str, ok: bool) -> None:
        with self._lock:
            self._conn.execute("INSERT OR IGNORE INTO tool_stats (tool) VALUES (?)", (tool,))
            self._conn.execute(
                "UPDATE tool_stats SET calls = calls + 1, failures = failures + ?"
                " WHERE tool=?",
                (0 if ok else 1, tool),
            )
            self._conn.commit()

    def best_agent_for(self, task_type: str, min_runs: int = 3) -> str | None:
        """The agent with the best track record here, once there is evidence."""
        with self._lock:
            row = self._conn.execute(
                "SELECT agent, avg_score FROM agent_stats"
                " WHERE task_type=? AND runs >= ? ORDER BY avg_score DESC LIMIT 1",
                (task_type, min_runs),
            ).fetchone()
        return row["agent"] if row and row["avg_score"] >= 0.6 else None

    def rankings(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT agent, task_type, runs, ROUND(avg_score,3) AS avg_score"
                " FROM agent_stats ORDER BY avg_score DESC, runs DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def stats(self) -> dict[str, Any]:
        with self._lock:
            total = self._conn.execute("SELECT COUNT(*) c FROM episodes").fetchone()["c"]
            avg = self._conn.execute("SELECT AVG(score) a FROM episodes").fetchone()["a"]
            healed = self._conn.execute(
                "SELECT COUNT(*) c FROM episodes WHERE healed > 0"
            ).fetchone()["c"]
            lessons = self._conn.execute("SELECT COUNT(*) c FROM lessons").fetchone()["c"]
            by_type = self._conn.execute(
                "SELECT task_type, COUNT(*) c FROM episodes GROUP BY task_type"
                " ORDER BY c DESC"
            ).fetchall()
            tools = self._conn.execute(
                "SELECT tool, calls, failures FROM tool_stats ORDER BY calls DESC"
            ).fetchall()
        return {
            "episodes": total,
            "avg_score": round(avg or 0.0, 3),
            "self_healed": healed,
            "lessons": lessons,
            "by_task_type": {r["task_type"]: r["c"] for r in by_type},
            "tools": [dict(r) for r in tools],
        }
