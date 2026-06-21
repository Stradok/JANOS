"""Episodic memory system — dedicated DB for interaction episodes with RAG.

Every interaction is stored as an "episode" containing:
- user input
- system reasoning steps
- tool usage
- agent selection
- final output
- errors and corrections
- outcome score (success/failure/efficiency)

Supports:
- RAG retrieval over episodic memory (ChromaDB vectors)
- Semantic search before every decision
- Failure pattern detection
- Memory compaction (compress old episodes)
"""

import json
import sqlite3
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.config import Config


class EpisodicMemory:
    """Episodic memory with ChromaDB vector store + SQLite metadata.

    Usage:
        memory = EpisodicMemory(config)
        await memory.start()
        await memory.store_episode(episode)
        results = await memory.search("how did I fix this before?", k=5)
        patterns = await memory.get_failure_patterns("file_operation")
    """

    def __init__(self, config: Config | None = None):
        self.config = config or Config()
        memory_path = Path(
            self.config.get("memory.path", str(self.config.base / "memory"))
        )
        memory_path.mkdir(parents=True, exist_ok=True)
        self.db_path = str(memory_path / "episodic.db")
        self._chroma_client = None
        self._collection = None
        self._init_sqlite()

    def _init_sqlite(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS episodes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    episode_id TEXT UNIQUE,
                    timestamp TEXT,
                    user_input TEXT,
                    reasoning_steps TEXT,
                    tool_usage TEXT,
                    agent_selection TEXT,
                    output TEXT,
                    errors TEXT,
                    corrections TEXT,
                    outcome_score REAL,
                    compressed_summary TEXT,
                    task_type TEXT,
                    duration_ms INTEGER,
                    metadata TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_episodes_task_type
                ON episodes(task_type)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_episodes_timestamp
                ON episodes(timestamp)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_episodes_score
                ON episodes(outcome_score)
            """)

    async def start(self):
        """Initialize ChromaDB collection for vector search."""
        try:
            import chromadb

            self._chroma_client = chromadb.PersistentClient(
                path=str(Path(self.db_path).parent / "chroma_episodic")
            )
            self._collection = self._chroma_client.get_or_create_collection(
                name="episodic_memory",
                metadata={"hnsw:space": "cosine"},
            )
        except ImportError:
            pass

    async def store_episode(
        self,
        user_input: str,
        reasoning_steps: list[str] | None = None,
        tool_usage: list[dict[str, Any]] | None = None,
        agent_selection: str = "",
        output: str = "",
        errors: list[str] | None = None,
        corrections: list[str] | None = None,
        outcome_score: float = 0.0,
        task_type: str = "general",
        duration_ms: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Store an episode and index it for RAG retrieval."""
        now = datetime.now(tz=timezone.utc).isoformat()
        input_hash = hashlib.md5(user_input.encode()).hexdigest()[:12]
        episode_id = f"ep_{now[:10]}_{input_hash}"

        compressed = self._compress_episode(
            user_input, reasoning_steps or [], output, errors or [], outcome_score
        )

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT OR REPLACE INTO episodes
                   (episode_id, timestamp, user_input, reasoning_steps, tool_usage,
                    agent_selection, output, errors, corrections, outcome_score,
                    compressed_summary, task_type, duration_ms, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    episode_id,
                    now,
                    user_input,
                    json.dumps(reasoning_steps or []),
                    json.dumps(tool_usage or []),
                    agent_selection,
                    output,
                    json.dumps(errors or []),
                    json.dumps(corrections or []),
                    outcome_score,
                    compressed,
                    task_type,
                    duration_ms,
                    json.dumps(metadata or {}),
                ),
            )

        await self._index_episode(episode_id, compressed, task_type, outcome_score)
        return episode_id

    async def search(
        self, query: str, k: int = 5, task_type: str | None = None
    ) -> list[dict[str, Any]]:
        """Semantic search over episodic memory using RAG."""
        results = []

        if self._collection is not None:
            try:
                where = {"task_type": task_type} if task_type else None
                query_embedding = await self._embed(query)
                search_results = self._collection.query(
                    query_embeddings=[query_embedding],
                    n_results=k,
                    where=where,
                )
                ids = search_results.get("ids", [[]])[0]
                distances = search_results.get("distances", [[]])[0]
                for ep_id, dist in zip(ids, distances):
                    episode = await self.get_episode(ep_id)
                    if episode:
                        episode["relevance_score"] = round(1.0 - float(dist), 3)
                        results.append(episode)
            except Exception:
                pass

        if len(results) < k:
            results.extend(
                await self._keyword_search(query, k - len(results), task_type)
            )

        return results[:k]

    async def get_episode(self, episode_id: str) -> dict[str, Any] | None:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM episodes WHERE episode_id = ?", (episode_id,)
            ).fetchone()
            if not row:
                return None
            columns = [d[1] for d in conn.execute("PRAGMA table_info(episodes)")]
            ep = dict(zip(columns, row))
            for field in ["reasoning_steps", "tool_usage", "errors", "corrections", "metadata"]:
                if isinstance(ep.get(field), str):
                    try:
                        ep[field] = json.loads(ep[field])
                    except (json.JSONDecodeError, TypeError):
                        pass
            return ep

    async def get_failure_patterns(self, task_type: str, limit: int = 5) -> list[dict[str, Any]]:
        """Get common failure patterns for a task type."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """SELECT compressed_summary, errors, outcome_score, episode_id
                   FROM episodes
                   WHERE task_type = ? AND outcome_score < 0
                   ORDER BY outcome_score ASC
                   LIMIT ?""",
                (task_type, limit),
            ).fetchall()
            return [
                {
                    "episode_id": r[3],
                    "summary": r[0],
                    "errors": json.loads(r[1] or "[]"),
                    "score": r[2],
                }
                for r in rows
            ]

    async def get_stats(self) -> dict[str, Any]:
        with sqlite3.connect(self.db_path) as conn:
            total = conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
            avg_score = conn.execute(
                "SELECT AVG(outcome_score) FROM episodes"
            ).fetchone()[0] or 0.0
            task_types = conn.execute(
                "SELECT task_type, COUNT(*) FROM episodes GROUP BY task_type ORDER BY COUNT(*) DESC"
            ).fetchall()
            return {
                "total_episodes": total,
                "avg_outcome_score": round(avg_score, 2),
                "by_task_type": dict(task_types),
            }

    async def compact(self, max_age_days: int = 30, max_episodes: int = 100):
        """Compress old episodes, keep top-k by relevance."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """SELECT episode_id, compressed_summary, outcome_score
                   FROM episodes
                   ORDER BY outcome_score DESC
                   LIMIT ?""",
                (max_episodes * 2,),
            ).fetchall()

            # Keep top max_episodes by score
            keep_ids = {r[0] for r in rows[:max_episodes]}
            conn.execute(
                "DELETE FROM episodes WHERE episode_id NOT IN ({}) AND timestamp < datetime('now', ?)".format(
                    ",".join("?" for _ in keep_ids)
                ),
                [*keep_ids, f"-{max_age_days} days"],
            )

            if self._collection is not None:
                all_ids = self._collection.get()["ids"]
                ids_to_delete = [eid for eid in all_ids if eid not in keep_ids]
                if ids_to_delete:
                    self._collection.delete(ids=ids_to_delete)

    def _compress_episode(
        self,
        user_input: str,
        reasoning_steps: list[str],
        output: str,
        errors: list[str],
        outcome_score: float,
    ) -> str:
        """Create a compressed summary (~512 chars) for efficient storage."""
        parts = [f"Input: {user_input[:200]}"]
        if reasoning_steps:
            parts.append(f"Reasoning: {'; '.join(reasoning_steps[:3])}")
        if output:
            parts.append(f"Output: {output[:200]}")
        if errors:
            parts.append(f"Errors: {'; '.join(errors[:2])}")
        parts.append(f"Score: {outcome_score:.1f}")
        summary = " | ".join(parts)
        return summary[:512]

    async def _index_episode(
        self, episode_id: str, summary: str, task_type: str, score: float
    ):
        """Index episode in ChromaDB for RAG retrieval."""
        if self._collection is None:
            return
        try:
            embedding = await self._embed(summary)
            self._collection.add(
                ids=[episode_id],
                embeddings=[embedding],
                metadatas=[{"task_type": task_type, "score": score}],
                documents=[summary],
            )
        except Exception:
            pass

    async def _embed(self, text: str) -> list[float]:
        """Create embedding. Uses simple approach if sentence-transformers not available."""
        try:
            from sentence_transformers import SentenceTransformer
            import numpy as np

            model = SentenceTransformer("all-MiniLM-L6-v2", device="cpu")
            emb = model.encode(text)
            return emb.tolist()
        except ImportError:
            return self._simple_embed(text)

    def _simple_embed(self, text: str) -> list[float]:
        """Fallback: character-level frequency embedding."""
        import hashlib

        vec = [0.0] * 384
        words = text.lower().split()
        for i, word in enumerate(words):
            h = hashlib.md5(word.encode()).digest()
            idx = (int.from_bytes(h[:4], "little") % 384 + i) % 384
            vec[idx] += 1.0 / len(words)
        norm = sum(v * v for v in vec) ** 0.5
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec

    async def _keyword_search(
        self, query: str, k: int, task_type: str | None = None
    ) -> list[dict[str, Any]]:
        """Fallback keyword search when vector search unavailable or insufficient."""
        terms = query.lower().split()
        results = []
        with sqlite3.connect(self.db_path) as conn:
            for term in terms:
                if task_type:
                    rows = conn.execute(
                        "SELECT episode_id, compressed_summary, outcome_score FROM episodes "
                        "WHERE task_type = ? AND (compressed_summary LIKE ? OR user_input LIKE ?) "
                        "ORDER BY outcome_score DESC LIMIT ?",
                        (task_type, f"%{term}%", f"%{term}%", k),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT episode_id, compressed_summary, outcome_score FROM episodes "
                        "WHERE compressed_summary LIKE ? OR user_input LIKE ? "
                        "ORDER BY outcome_score DESC LIMIT ?",
                        (f"%{term}%", f"%{term}%", k),
                    ).fetchall()
                for r in rows:
                    ep = await self.get_episode(r[0])
                    if ep and ep["episode_id"] not in {res["episode_id"] for res in results}:
                        ep["relevance_score"] = 0.5
                        results.append(ep)
        return results[:k]
