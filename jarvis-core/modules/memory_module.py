# modules/memory_module.py
"""
Conversation Memory + Knowledge Base for Jarvis.
Stores all conversations in SQLite, with semantic search via ChromaDB embeddings.
"""
import os
import json
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from .base import ModuleBase

try:
    import chromadb
    CHROMA_AVAILABLE = True
except ImportError:
    CHROMA_AVAILABLE = False


class MemoryModule(ModuleBase):
    """Long-term memory — remembers all conversations and learned knowledge."""

    def __init__(self):
        super().__init__("memory")
        self.db_path = Path("memory/jarvis_memory.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._init_vector_store()

    def _init_db(self):
        """Create SQLite tables for conversation history and knowledge."""
        conn = sqlite3.connect(str(self.db_path))
        c = conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            session_id TEXT
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS knowledge (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT NOT NULL,
            content TEXT NOT NULL,
            source TEXT,
            timestamp TEXT NOT NULL
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS user_profile (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""")
        conn.commit()
        conn.close()

    def _init_vector_store(self):
        """Initialize ChromaDB for semantic search over memory."""
        if not CHROMA_AVAILABLE:
            self.chroma_client = None
            self.conversations_collection = None
            self.knowledge_collection = None
            return
        try:
            persist_dir = str(Path("memory/chroma_db"))
            os.makedirs(persist_dir, exist_ok=True)
            self.chroma_client = chromadb.PersistentClient(path=persist_dir)
            self.conversations_collection = self.chroma_client.get_or_create_collection(
                name="conversations",
                metadata={"hnsw:space": "cosine"}
            )
            self.knowledge_collection = self.chroma_client.get_or_create_collection(
                name="knowledge",
                metadata={"hnsw:space": "cosine"}
            )
        except Exception as e:
            print(f"[Memory] ChromaDB init warning: {e}")
            self.chroma_client = None
            self.conversations_collection = None
            self.knowledge_collection = None

    def _get_conn(self):
        return sqlite3.connect(str(self.db_path))

    # ========================
    # Conversation Memory
    # ========================
    def save_conversation(self, role, content, session_id=None):
        """Save a message to conversation history."""
        conn = self._get_conn()
        c = conn.cursor()
        ts = datetime.now().isoformat()
        c.execute("INSERT INTO conversations (role, content, timestamp, session_id) VALUES (?, ?, ?, ?)",
                  (role, content, ts, session_id))
        row_id = c.lastrowid
        conn.commit()
        conn.close()

        # also add to vector store for semantic search
        if self.conversations_collection:
            try:
                self.conversations_collection.add(
                    documents=[content],
                    ids=[f"conv_{row_id}"],
                    metadatas=[{"role": role, "timestamp": ts, "session_id": session_id or ""}]
                )
            except Exception:
                pass

        return {"status": "ok", "saved": True, "id": row_id}

    def recall_conversations(self, query=None, limit=10):
        """Recall past conversations. If query provided, do semantic search. Otherwise return recent."""
        if query and self.conversations_collection:
            try:
                results = self.conversations_collection.query(
                    query_texts=[query],
                    n_results=limit
                )
                memories = []
                for i, doc in enumerate(results["documents"][0]):
                    meta = results["metadatas"][0][i]
                    memories.append({
                        "content": doc,
                        "role": meta.get("role", ""),
                        "timestamp": meta.get("timestamp", ""),
                        "relevance": round(1 - results["distances"][0][i], 3) if results["distances"] else None
                    })
                return {"status": "ok", "query": query, "memories": memories}
            except Exception as e:
                pass  # fall through to SQLite

        # fallback: recent conversations from SQLite
        conn = self._get_conn()
        c = conn.cursor()
        if query:
            c.execute("SELECT role, content, timestamp FROM conversations WHERE content LIKE ? ORDER BY timestamp DESC LIMIT ?",
                      (f"%{query}%", limit))
        else:
            c.execute("SELECT role, content, timestamp FROM conversations ORDER BY timestamp DESC LIMIT ?", (limit,))
        rows = c.fetchall()
        conn.close()
        return {
            "status": "ok",
            "memories": [{"role": r[0], "content": r[1], "timestamp": r[2]} for r in rows]
        }

    # ========================
    # Knowledge Base
    # ========================
    def save_knowledge(self, topic, content, source=None):
        """Save a piece of knowledge/learning."""
        conn = self._get_conn()
        c = conn.cursor()
        ts = datetime.now().isoformat()
        c.execute("INSERT INTO knowledge (topic, content, source, timestamp) VALUES (?, ?, ?, ?)",
                  (topic, content, source, ts))
        row_id = c.lastrowid
        conn.commit()
        conn.close()

        if self.knowledge_collection:
            try:
                self.knowledge_collection.add(
                    documents=[f"{topic}: {content}"],
                    ids=[f"know_{row_id}"],
                    metadatas=[{"topic": topic, "source": source or "", "timestamp": ts}]
                )
            except Exception:
                pass

        return {"status": "ok", "saved": True, "id": row_id}

    def search_knowledge(self, query, limit=5):
        """Search the knowledge base semantically."""
        if self.knowledge_collection:
            try:
                results = self.knowledge_collection.query(
                    query_texts=[query],
                    n_results=limit
                )
                items = []
                for i, doc in enumerate(results["documents"][0]):
                    meta = results["metadatas"][0][i]
                    items.append({
                        "content": doc,
                        "topic": meta.get("topic", ""),
                        "source": meta.get("source", ""),
                        "relevance": round(1 - results["distances"][0][i], 3) if results["distances"] else None
                    })
                return {"status": "ok", "query": query, "results": items}
            except Exception:
                pass

        # fallback SQLite
        conn = self._get_conn()
        c = conn.cursor()
        c.execute("SELECT topic, content, source, timestamp FROM knowledge WHERE topic LIKE ? OR content LIKE ? ORDER BY timestamp DESC LIMIT ?",
                  (f"%{query}%", f"%{query}%", limit))
        rows = c.fetchall()
        conn.close()
        return {
            "status": "ok",
            "results": [{"topic": r[0], "content": r[1], "source": r[2], "timestamp": r[3]} for r in rows]
        }

    # ========================
    # User Profile
    # ========================
    def set_preference(self, key, value):
        """Save or update a user preference."""
        conn = self._get_conn()
        c = conn.cursor()
        ts = datetime.now().isoformat()
        c.execute("INSERT OR REPLACE INTO user_profile (key, value, updated_at) VALUES (?, ?, ?)",
                  (key, json.dumps(value) if not isinstance(value, str) else value, ts))
        conn.commit()
        conn.close()
        return {"status": "ok", "set": {key: value}}

    def get_preference(self, key):
        """Get a user preference."""
        conn = self._get_conn()
        c = conn.cursor()
        c.execute("SELECT value FROM user_profile WHERE key = ?", (key,))
        row = c.fetchone()
        conn.close()
        if row:
            try:
                return {"status": "ok", "key": key, "value": json.loads(row[0])}
            except (json.JSONDecodeError, TypeError):
                return {"status": "ok", "key": key, "value": row[0]}
        return {"status": "ok", "key": key, "value": None}

    def get_all_preferences(self):
        """Get all user preferences."""
        conn = self._get_conn()
        c = conn.cursor()
        c.execute("SELECT key, value FROM user_profile")
        rows = c.fetchall()
        conn.close()
        prefs = {}
        for k, v in rows:
            try:
                prefs[k] = json.loads(v)
            except (json.JSONDecodeError, TypeError):
                prefs[k] = v
        return {"status": "ok", "preferences": prefs}

    def get_stats(self):
        """Get memory statistics."""
        conn = self._get_conn()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM conversations")
        conv_count = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM knowledge")
        know_count = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM user_profile")
        pref_count = c.fetchone()[0]
        conn.close()
        return {
            "status": "ok",
            "conversations": conv_count,
            "knowledge_items": know_count,
            "preferences": pref_count
        }

    def process(self, input_data):
        action = input_data.get("action", "recall")

        # Conversation memory
        if action == "save_conversation":
            return self.save_conversation(
                input_data.get("role", "user"),
                input_data.get("content", ""),
                input_data.get("session_id")
            )
        elif action == "recall":
            return self.recall_conversations(
                input_data.get("query"),
                input_data.get("limit", 10)
            )

        # Knowledge base
        elif action == "save_knowledge":
            return self.save_knowledge(
                input_data.get("topic", ""),
                input_data.get("content", ""),
                input_data.get("source")
            )
        elif action == "search_knowledge":
            return self.search_knowledge(
                input_data.get("query", ""),
                input_data.get("limit", 5)
            )

        # User profile
        elif action == "set_preference":
            key = input_data.get("key", "")
            value = input_data.get("value", "")
            if not key:
                return {"error": "Missing 'key' for preference"}
            return self.set_preference(key, value)
        elif action == "get_preference":
            return self.get_preference(input_data.get("key", ""))
        elif action == "get_all_preferences":
            return self.get_all_preferences()

        # Stats
        elif action == "stats":
            return self.get_stats()

        else:
            return {"error": f"Unknown action: {action}. Use: save_conversation, recall, save_knowledge, search_knowledge, set_preference, get_preference, get_all_preferences, stats"}
