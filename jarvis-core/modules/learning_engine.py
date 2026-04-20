# modules/learning_engine.py
"""
JAN Self-Learning Engine
Runs overnight (or on-demand) to make JAN smarter:
1. RAG Builder — crawls web topics, chunks text, embeds into ChromaDB for retrieval
2. Skill Learner — tracks tool call success/failure, stores corrected patterns
3. Knowledge Explorer — researches random useful topics, builds general knowledge
4. Practice Mode — simulates tasks to learn tool patterns without executing
"""
import os
import re
import json
import time
import random
import sqlite3
import hashlib
import requests
import threading
from datetime import datetime, timedelta
from pathlib import Path
from .base import ModuleBase

try:
    import chromadb
    CHROMA_AVAILABLE = True
except ImportError:
    CHROMA_AVAILABLE = False

OLLAMA_URL = "http://localhost:11434/api/chat"
OLLAMA_MODEL = "qwen2.5:7b-instruct"


class LearningEngine(ModuleBase):
    """
    JAN's brain growth engine.
    Runs in background to build knowledge, learn skills, and improve over time.
    """

    def __init__(self):
        super().__init__("learning_engine")
        self.db_path = Path("memory/jarvis_memory.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.memory = None          # wired from __init__.py
        self.web_search = None      # wired from __init__.py
        self.orchestrator = None    # wired from __init__.py (v2)
        self._running = False
        self._thread = None
        self._init_db()
        self._init_rag_store()

    # ================================================================
    # Database
    # ================================================================
    def _init_db(self):
        conn = sqlite3.connect(str(self.db_path))
        c = conn.cursor()
        # Skill memory — tracks what works and what doesn't per tool
        c.execute("""CREATE TABLE IF NOT EXISTS skill_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent TEXT NOT NULL,
            tool TEXT NOT NULL,
            action TEXT NOT NULL,
            input_pattern TEXT,
            outcome TEXT NOT NULL,
            error_msg TEXT,
            correction TEXT,
            timestamp TEXT NOT NULL
        )""")
        # RAG documents — chunked web content for retrieval
        c.execute("""CREATE TABLE IF NOT EXISTS rag_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_url TEXT,
            title TEXT,
            chunk_text TEXT NOT NULL,
            chunk_index INTEGER,
            topic TEXT,
            timestamp TEXT NOT NULL,
            content_hash TEXT UNIQUE
        )""")
        # Learning sessions — track what was learned
        c.execute("""CREATE TABLE IF NOT EXISTS learning_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_type TEXT,
            topics_explored TEXT,
            documents_added INTEGER DEFAULT 0,
            skills_learned INTEGER DEFAULT 0,
            duration_seconds REAL,
            timestamp TEXT NOT NULL
        )""")
        conn.commit()
        conn.close()

    def _get_conn(self):
        return sqlite3.connect(str(self.db_path))

    def _init_rag_store(self):
        """Initialize ChromaDB collection for RAG retrieval."""
        if not CHROMA_AVAILABLE:
            self.rag_collection = None
            return
        try:
            persist_dir = str(Path("memory/chroma_db"))
            os.makedirs(persist_dir, exist_ok=True)
            client = chromadb.PersistentClient(path=persist_dir)
            self.rag_collection = client.get_or_create_collection(
                name="rag_knowledge",
                metadata={"hnsw:space": "cosine"}
            )
        except Exception as e:
            print(f"[LearningEngine] ChromaDB RAG init warning: {e}")
            self.rag_collection = None

    # ================================================================
    # 1. RAG PIPELINE — Search → Chunk → Embed → Store → Retrieve
    # ================================================================
    def _chunk_text(self, text, chunk_size=500, overlap=50):
        """Split text into overlapping chunks for embedding."""
        words = text.split()
        chunks = []
        i = 0
        while i < len(words):
            chunk = " ".join(words[i:i + chunk_size])
            if chunk.strip():
                chunks.append(chunk)
            i += chunk_size - overlap
        return chunks

    def ingest_url(self, url, topic=None):
        """Fetch a URL, chunk it, embed it, store in RAG."""
        if not self.web_search:
            return {"status": "error", "error": "web_search module not available"}

        try:
            # Fetch page content
            result = self.web_search.process({
                "action": "read_page",
                "url": url,
                "max_chars": 10000
            })
            if result.get("error"):
                return {"status": "error", "error": result["error"]}

            content = result.get("content", "")
            title = result.get("title", url)
            if not content or len(content) < 50:
                return {"status": "error", "error": "Page had no meaningful content"}

            # Chunk the content
            chunks = self._chunk_text(content)
            if not chunks:
                return {"status": "error", "error": "Could not chunk content"}

            # Store chunks
            stored = 0
            conn = self._get_conn()
            c = conn.cursor()
            now = datetime.now().isoformat()

            for i, chunk in enumerate(chunks):
                content_hash = hashlib.md5(chunk.encode()).hexdigest()
                try:
                    c.execute("""INSERT OR IGNORE INTO rag_documents
                        (source_url, title, chunk_text, chunk_index, topic, timestamp, content_hash)
                        VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (url, title, chunk, i, topic or "general", now, content_hash))
                    if c.rowcount > 0:
                        stored += 1
                        # Also add to ChromaDB for semantic search
                        if self.rag_collection:
                            self.rag_collection.add(
                                documents=[chunk],
                                ids=[f"rag_{content_hash}"],
                                metadatas=[{
                                    "source": url,
                                    "title": title,
                                    "topic": topic or "general",
                                    "chunk_index": i,
                                    "timestamp": now
                                }]
                            )
                except Exception:
                    pass

            conn.commit()
            conn.close()
            return {
                "status": "ok",
                "url": url,
                "title": title,
                "chunks_stored": stored,
                "total_chunks": len(chunks)
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def rag_search(self, query, n_results=5):
        """Retrieve relevant chunks from RAG store using semantic search."""
        results = []

        # ChromaDB semantic search (primary)
        if self.rag_collection:
            try:
                search = self.rag_collection.query(
                    query_texts=[query],
                    n_results=n_results
                )
                for i, doc in enumerate(search["documents"][0]):
                    meta = search["metadatas"][0][i]
                    dist = search["distances"][0][i] if search.get("distances") else 1.0
                    results.append({
                        "content": doc,
                        "source": meta.get("source", ""),
                        "title": meta.get("title", ""),
                        "topic": meta.get("topic", ""),
                        "relevance": round(1 - dist, 3)
                    })
            except Exception:
                pass

        # Fallback: SQLite text search
        if not results:
            try:
                conn = self._get_conn()
                c = conn.cursor()
                terms = query.lower().split()[:5]
                conditions = " OR ".join(["chunk_text LIKE ?" for _ in terms])
                params = [f"%{t}%" for t in terms]
                c.execute(f"""SELECT chunk_text, source_url, title, topic
                    FROM rag_documents WHERE {conditions}
                    ORDER BY timestamp DESC LIMIT ?""",
                    params + [n_results])
                for row in c.fetchall():
                    results.append({
                        "content": row[0],
                        "source": row[1],
                        "title": row[2],
                        "topic": row[3],
                        "relevance": 0.5
                    })
                conn.close()
            except Exception:
                pass

        return {"status": "ok", "query": query, "results": results}

    # ================================================================
    # 2. SKILL MEMORY — Learn from success/failure
    # ================================================================
    def record_skill(self, agent, tool, action, input_pattern, outcome, error_msg=None, correction=None):
        """Record a tool call outcome for learning."""
        try:
            conn = self._get_conn()
            c = conn.cursor()
            c.execute("""INSERT INTO skill_memory
                (agent, tool, action, input_pattern, outcome, error_msg, correction, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (agent, tool, action,
                 json.dumps(input_pattern) if isinstance(input_pattern, dict) else str(input_pattern),
                 outcome, error_msg, correction, datetime.now().isoformat()))
            conn.commit()
            conn.close()
            return {"status": "ok"}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def get_skill_tips(self, agent=None, tool=None, limit=5):
        """Get learned tips for a specific agent/tool combination."""
        try:
            conn = self._get_conn()
            c = conn.cursor()
            query = "SELECT agent, tool, action, input_pattern, outcome, error_msg, correction FROM skill_memory WHERE 1=1"
            params = []
            if agent:
                query += " AND agent = ?"
                params.append(agent)
            if tool:
                query += " AND tool = ?"
                params.append(tool)
            # Get failures with corrections first, then successes
            query += " ORDER BY CASE WHEN correction IS NOT NULL THEN 0 ELSE 1 END, timestamp DESC LIMIT ?"
            params.append(limit)
            c.execute(query, params)
            rows = c.fetchall()
            conn.close()

            tips = []
            for r in rows:
                tip = {
                    "agent": r[0], "tool": r[1], "action": r[2],
                    "input_pattern": r[3], "outcome": r[4],
                }
                if r[5]:
                    tip["error"] = r[5]
                if r[6]:
                    tip["correction"] = r[6]
                tips.append(tip)
            return {"status": "ok", "tips": tips}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def _build_skill_context(self, agent_name):
        """Build a skill tips string to inject into agent prompts."""
        tips_result = self.get_skill_tips(agent=agent_name, limit=5)
        tips = tips_result.get("tips", [])
        if not tips:
            return ""

        lines = ["[LEARNED SKILLS — things I've learned from past attempts]:"]
        for tip in tips:
            if tip.get("correction"):
                lines.append(f"- {tip['tool']}.{tip['action']}: WRONG: {tip.get('error', 'failed')} → CORRECT: {tip['correction']}")
            elif tip["outcome"] == "success":
                lines.append(f"- {tip['tool']}.{tip['action']}: works with input {tip['input_pattern']}")
        return "\n".join(lines)

    # ================================================================
    # 3. KNOWLEDGE EXPLORER — Research random useful topics
    # ================================================================

    # Topics JAN should learn about to be a better assistant
    LEARNING_TOPICS = [
        # How to use tools better
        "how to search for a specific song on Spotify desktop app",
        "how to compose and send email in Gmail using keyboard shortcuts",
        "how to use keyboard shortcuts in Google Chrome",
        "how to navigate WhatsApp Web efficiently",
        "how to use DuckDuckGo search operators for better results",
        # General knowledge an assistant should know
        "current weather API usage and interpretation",
        "common email etiquette and format",
        "Pakistan current events and news",
        "popular music artists and songs 2024 2025",
        "how to write professional emails",
        "how to use Windows 11 keyboard shortcuts",
        "how to control media playback on Windows",
        "how to automate tasks on Windows with Python",
        "best practices for web scraping with Python",
        "how to read and summarize web pages efficiently",
    ]

    def explore_topic(self, topic=None):
        """Research a topic, read top results, store in RAG."""
        if not self.web_search:
            return {"status": "error", "error": "web_search not available"}

        if not topic:
            topic = random.choice(self.LEARNING_TOPICS)

        results_added = 0
        try:
            # Step 1: Search
            search_result = self.web_search.process({
                "action": "search",
                "query": topic,
                "max_results": 3,
                "summarize": False
            })
            search_results = search_result.get("results", [])
            if not search_results:
                return {"status": "ok", "topic": topic, "message": "No search results found"}

            # Step 2: Read top pages and ingest into RAG
            for sr in search_results[:3]:
                url = sr.get("url", "")
                if not url or not url.startswith("http"):
                    continue
                ingest = self.ingest_url(url, topic=topic)
                if ingest.get("chunks_stored", 0) > 0:
                    results_added += ingest["chunks_stored"]

            # Step 3: Also save a summary to knowledge base
            if self.memory and search_results:
                snippets = [sr.get("snippet", "") for sr in search_results if sr.get("snippet")]
                summary = f"Researched: {topic}. Key findings: " + " | ".join(snippets[:3])
                self.memory.save_knowledge(topic, summary[:500], source="self_learning")

            return {
                "status": "ok",
                "topic": topic,
                "pages_read": len(search_results),
                "chunks_stored": results_added
            }
        except Exception as e:
            return {"status": "error", "topic": topic, "error": str(e)}

    # ================================================================
    # 4. OVERNIGHT LEARNING SESSION
    # ================================================================
    def run_learning_session(self, duration_minutes=30, topics=None):
        """
        Run a full learning session:
        1. Analyze past failures and learn from them
        2. Explore topics and build RAG knowledge
        3. Extract user preferences from conversations
        4. Report what was learned
        """
        start = time.time()
        session_log = {
            "topics_explored": [],
            "documents_added": 0,
            "skills_analyzed": 0,
            "preferences_extracted": {},
        }

        # Choose topics to explore
        if not topics:
            topics = random.sample(
                self.LEARNING_TOPICS,
                min(len(self.LEARNING_TOPICS), max(3, duration_minutes // 5))
            )

        # Phase 1: Analyze past tool failures and learn
        print("[LearningEngine] Phase 1: Analyzing past failures...")
        skills_result = self._analyze_failures()
        session_log["skills_analyzed"] = skills_result.get("analyzed", 0)

        # Phase 2: Explore topics and build RAG
        print(f"[LearningEngine] Phase 2: Exploring {len(topics)} topics...")
        for topic in topics:
            elapsed = time.time() - start
            if elapsed > duration_minutes * 60:
                break

            print(f"[LearningEngine]   Exploring: {topic}")
            result = self.explore_topic(topic)
            if result.get("status") == "ok":
                session_log["topics_explored"].append(topic)
                session_log["documents_added"] += result.get("chunks_stored", 0)

            time.sleep(2)  # be nice to servers

        # Phase 3: Learn user preferences
        print("[LearningEngine] Phase 3: Extracting user preferences...")
        try:
            from . import MODULES
            proactive = MODULES.get("proactive_learning")
            if proactive:
                pref_result = proactive.process({"action": "learn_preferences"})
                session_log["preferences_extracted"] = pref_result.get("saved", {})

                # Also detect patterns
                proactive.process({"action": "analyze_patterns"})
        except Exception:
            pass

        # Save session record
        duration = time.time() - start
        conn = self._get_conn()
        c = conn.cursor()
        c.execute("""INSERT INTO learning_sessions
            (session_type, topics_explored, documents_added, skills_learned, duration_seconds, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)""",
            ("auto" if not topics else "manual",
             json.dumps(session_log["topics_explored"]),
             session_log["documents_added"],
             session_log["skills_analyzed"],
             duration, datetime.now().isoformat()))
        conn.commit()
        conn.close()

        summary = (
            f"Learning session complete ({duration:.0f}s): "
            f"explored {len(session_log['topics_explored'])} topics, "
            f"stored {session_log['documents_added']} RAG chunks, "
            f"analyzed {session_log['skills_analyzed']} skill patterns"
        )
        print(f"[LearningEngine] {summary}")

        return {"status": "ok", **session_log, "duration_seconds": duration, "summary": summary}

    def _analyze_failures(self):
        """Look at recent failures and generate corrections."""
        try:
            conn = self._get_conn()
            c = conn.cursor()
            # Get recent failures without corrections
            c.execute("""SELECT id, agent, tool, action, input_pattern, error_msg
                FROM skill_memory
                WHERE outcome = 'error' AND correction IS NULL
                ORDER BY timestamp DESC LIMIT 10""")
            failures = c.fetchall()
            conn.close()

            if not failures:
                return {"analyzed": 0}

            analyzed = 0
            for f_id, agent, tool, action, input_pat, error_msg in failures:
                # Ask LLM how to fix this
                correction = self._generate_correction(agent, tool, action, input_pat, error_msg)
                if correction:
                    conn = self._get_conn()
                    c = conn.cursor()
                    c.execute("UPDATE skill_memory SET correction = ? WHERE id = ?",
                              (correction, f_id))
                    conn.commit()
                    conn.close()
                    analyzed += 1

            return {"analyzed": analyzed}
        except Exception:
            return {"analyzed": 0}

    def _generate_correction(self, agent, tool, action, input_pattern, error_msg):
        """Ask LLM to suggest a correction for a failed tool call."""
        prompt = f"""A JAN agent tried to use a tool and it failed. Suggest the correct input.

Agent: {agent}
Tool: {tool}
Action: {action}
Input used: {input_pattern}
Error: {error_msg}

What is the correct way to call this tool? Give ONLY the corrected JSON input, nothing else."""

        try:
            resp = requests.post(OLLAMA_URL, json={
                "model": OLLAMA_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": {"temperature": 0.3, "num_predict": 256}
            }, timeout=30)
            content = resp.json()["message"]["content"].strip()
            # Extract just the JSON if wrapped
            match = re.search(r'\{.*\}', content, re.DOTALL)
            return match.group() if match else content[:300]
        except Exception:
            return None

    # ================================================================
    # 5. BACKGROUND RUNNER
    # ================================================================
    def start_background(self, duration_minutes=30, interval_hours=6):
        """Start background learning that runs periodically."""
        if self._running:
            return {"status": "already_running"}

        self._running = True

        def _loop():
            while self._running:
                try:
                    self.run_learning_session(duration_minutes=duration_minutes)
                except Exception as e:
                    print(f"[LearningEngine] Session error: {e}")
                # Sleep until next session
                for _ in range(int(interval_hours * 3600)):
                    if not self._running:
                        break
                    time.sleep(1)

        self._thread = threading.Thread(target=_loop, daemon=True)
        self._thread.start()
        return {"status": "started", "duration_minutes": duration_minutes, "interval_hours": interval_hours}

    def stop_background(self):
        """Stop background learning."""
        self._running = False
        return {"status": "stopped"}

    def get_stats(self):
        """Get learning statistics."""
        try:
            conn = self._get_conn()
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM rag_documents")
            rag_count = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM skill_memory")
            skill_count = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM skill_memory WHERE outcome = 'error'")
            error_count = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM skill_memory WHERE correction IS NOT NULL")
            corrected_count = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM learning_sessions")
            session_count = c.fetchone()[0]

            # RAG collection size
            rag_vectors = 0
            if self.rag_collection:
                try:
                    rag_vectors = self.rag_collection.count()
                except Exception:
                    pass

            conn.close()
            return {
                "status": "ok",
                "rag_documents": rag_count,
                "rag_vectors": rag_vectors,
                "skills_recorded": skill_count,
                "errors_recorded": error_count,
                "corrections_learned": corrected_count,
                "learning_sessions": session_count,
                "background_running": self._running,
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    # ================================================================
    # process() dispatcher
    # ================================================================
    def process(self, input_data):
        action = input_data.get("action", "stats")

        if action == "learn":
            return self.run_learning_session(
                duration_minutes=input_data.get("duration_minutes", 30),
                topics=input_data.get("topics")
            )
        elif action == "explore_topic":
            return self.explore_topic(input_data.get("topic"))
        elif action == "ingest_url":
            return self.ingest_url(
                input_data.get("url", ""),
                topic=input_data.get("topic")
            )
        elif action == "rag_search":
            return self.rag_search(
                input_data.get("query", ""),
                n_results=input_data.get("n_results", 5)
            )
        elif action == "record_skill":
            return self.record_skill(
                agent=input_data.get("agent", ""),
                tool=input_data.get("tool", ""),
                action=input_data.get("tool_action", ""),
                input_pattern=input_data.get("input_pattern", {}),
                outcome=input_data.get("outcome", "error"),
                error_msg=input_data.get("error_msg"),
                correction=input_data.get("correction")
            )
        elif action == "get_skill_tips":
            return self.get_skill_tips(
                agent=input_data.get("agent"),
                tool=input_data.get("tool"),
                limit=input_data.get("limit", 5)
            )
        elif action == "start_background":
            return self.start_background(
                duration_minutes=input_data.get("duration_minutes", 30),
                interval_hours=input_data.get("interval_hours", 6)
            )
        elif action == "stop_background":
            return self.stop_background()
        elif action == "stats":
            return self.get_stats()
        else:
            return {"error": f"Unknown action: {action}. Use: learn, explore_topic, ingest_url, rag_search, record_skill, get_skill_tips, start_background, stop_background, stats"}
