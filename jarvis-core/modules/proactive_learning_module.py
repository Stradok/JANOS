# modules/proactive_learning_module.py
"""
Proactive Learning Module for JAN.
Detects user behavior patterns, tracks habits, suggests automations,
manages scheduled tasks, and learns user preferences from conversations.
"""
import json
import sqlite3
import re
import requests
from datetime import datetime, timedelta
from pathlib import Path
from collections import Counter

from .base import ModuleBase

OLLAMA_URL = "http://localhost:11434/api/chat"
OLLAMA_MODEL = "llama3.1:8b"


class ProactiveLearningModule(ModuleBase):
    """Observes user behavior, detects patterns, and suggests automations."""

    def __init__(self):
        super().__init__("proactive_learning")
        self.memory = None  # wired externally from __init__.py
        self.db_path = Path("memory/jarvis_memory.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ------------------------------------------------------------------
    # Database setup
    # ------------------------------------------------------------------
    def _init_db(self):
        conn = self._get_conn()
        c = conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS habits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern TEXT,
            frequency INTEGER,
            last_seen TEXT,
            suggested BOOLEAN DEFAULT 0,
            automated BOOLEAN DEFAULT 0
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS scheduled_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_type TEXT,
            task_data TEXT,
            schedule TEXT,
            enabled BOOLEAN DEFAULT 1,
            last_run TEXT,
            created_at TEXT
        )""")
        conn.commit()
        conn.close()

    def _get_conn(self):
        return sqlite3.connect(str(self.db_path))

    # ------------------------------------------------------------------
    # Pattern detection helpers
    # ------------------------------------------------------------------
    def _fetch_recent_conversations(self, hours=168, role="user"):
        """Fetch user messages from the last `hours` hours (default 7 days)."""
        since = (datetime.now() - timedelta(hours=hours)).isoformat()
        conn = self._get_conn()
        c = conn.cursor()
        c.execute(
            "SELECT content, timestamp FROM conversations "
            "WHERE role = ? AND timestamp >= ? ORDER BY timestamp ASC",
            (role, since),
        )
        rows = c.fetchall()
        conn.close()
        return [{"content": r[0], "timestamp": r[1]} for r in rows]

    @staticmethod
    def _extract_hour(ts_str):
        """Return the hour (0-23) from an ISO timestamp string."""
        try:
            return datetime.fromisoformat(ts_str).hour
        except Exception:
            return None

    @staticmethod
    def _extract_date(ts_str):
        """Return date string YYYY-MM-DD from an ISO timestamp."""
        try:
            return datetime.fromisoformat(ts_str).strftime("%Y-%m-%d")
        except Exception:
            return None

    # Keyword clusters that represent recognisable intents
    _INTENT_KEYWORDS = {
        "weather": ["weather", "forecast", "temperature", "rain", "sunny"],
        "spotify": ["spotify", "play music", "play song", "music"],
        "news": ["news", "headlines", "what's happening"],
        "email": ["email", "mail", "inbox"],
        "calendar": ["calendar", "schedule", "meeting", "agenda"],
        "time": ["time", "what time"],
        "notes": ["note", "remind me", "reminder"],
        "search": ["search", "google", "look up"],
    }

    def _classify_intent(self, text):
        """Return a simple intent label for a user message."""
        lower = text.lower()
        for intent, keywords in self._INTENT_KEYWORDS.items():
            for kw in keywords:
                if kw in lower:
                    return intent
        return None

    def _detect_patterns(self, messages):
        """
        Analyse a list of messages and return detected patterns.
        A pattern is: same intent at roughly the same time-of-day on multiple days.
        """
        # Group by (intent, hour-bucket, date) to count unique days
        intent_hour_dates: dict[tuple[str, int], set[str]] = {}
        for msg in messages:
            intent = self._classify_intent(msg["content"])
            if not intent:
                continue
            hour = self._extract_hour(msg["timestamp"])
            date = self._extract_date(msg["timestamp"])
            if hour is None or date is None:
                continue
            # bucket hours into 2-hour windows for fuzzy matching
            bucket = (hour // 2) * 2
            key = (intent, bucket)
            intent_hour_dates.setdefault(key, set()).add(date)

        patterns = []
        for (intent, bucket), dates in intent_hour_dates.items():
            freq = len(dates)
            if freq >= 2:  # seen on at least 2 different days
                time_label = f"{bucket:02d}:00-{bucket + 2:02d}:00"
                patterns.append({
                    "intent": intent,
                    "time_window": time_label,
                    "frequency": freq,
                    "days": sorted(dates),
                })
        return patterns

    # ------------------------------------------------------------------
    # Habit tracking (persist to DB)
    # ------------------------------------------------------------------
    def _upsert_habit(self, pattern_str, frequency):
        conn = self._get_conn()
        c = conn.cursor()
        now = datetime.now().isoformat()
        c.execute("SELECT id, frequency FROM habits WHERE pattern = ?", (pattern_str,))
        row = c.fetchone()
        if row:
            c.execute(
                "UPDATE habits SET frequency = ?, last_seen = ? WHERE id = ?",
                (frequency, now, row[0]),
            )
        else:
            c.execute(
                "INSERT INTO habits (pattern, frequency, last_seen) VALUES (?, ?, ?)",
                (pattern_str, frequency, now),
            )
        conn.commit()
        conn.close()

    # ------------------------------------------------------------------
    # Scheduled tasks helpers
    # ------------------------------------------------------------------
    def _task_is_due(self, schedule, last_run_str):
        """Return True if a task with the given schedule string is due now."""
        now = datetime.now()
        if last_run_str:
            try:
                last_run = datetime.fromisoformat(last_run_str)
            except Exception:
                last_run = None
        else:
            last_run = None

        # daily_HH:MM  e.g. daily_09:00
        m = re.match(r"daily_(\d{2}):(\d{2})", schedule)
        if m:
            target_hour, target_min = int(m.group(1)), int(m.group(2))
            if now.hour == target_hour and now.minute >= target_min:
                if last_run and last_run.date() == now.date():
                    return False  # already ran today
                return True
            return False

        # every_Nmin  e.g. every_30min
        m = re.match(r"every_(\d+)min", schedule)
        if m:
            interval = int(m.group(1))
            if not last_run:
                return True
            return (now - last_run) >= timedelta(minutes=interval)

        # every_Nh  e.g. every_2h
        m = re.match(r"every_(\d+)h", schedule)
        if m:
            interval = int(m.group(1))
            if not last_run:
                return True
            return (now - last_run) >= timedelta(hours=interval)

        return False

    # ------------------------------------------------------------------
    # LLM helper (Ollama)
    # ------------------------------------------------------------------
    def _llm_extract_preferences(self, messages_text):
        """Ask the local LLM to extract user preferences from conversation text."""
        prompt = (
            "You are an AI assistant analysing conversation history. "
            "Extract any user preferences you can find (e.g., favourite music genre, "
            "preferred language, favourite food, work schedule, hobbies, location, name). "
            "Return ONLY a JSON object mapping preference keys to values. "
            "Use snake_case keys. Example: {\"favorite_music\": \"jazz\", \"city\": \"Lahore\"}. "
            "If nothing found, return {}.\n\n"
            "Conversation:\n" + messages_text
        )
        try:
            resp = requests.post(
                OLLAMA_URL,
                json={
                    "model": OLLAMA_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                },
                timeout=60,
            )
            resp.raise_for_status()
            content = resp.json().get("message", {}).get("content", "")
            # Try to parse JSON from the response (may be wrapped in markdown)
            json_match = re.search(r"\{[^{}]*\}", content, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
            return {}
        except Exception:
            return {}

    # ------------------------------------------------------------------
    # Public action methods
    # ------------------------------------------------------------------
    def analyze_patterns(self, hours=168):
        """Scan recent conversations, detect patterns, persist as habits."""
        try:
            messages = self._fetch_recent_conversations(hours=hours)
            if not messages:
                return {"status": "ok", "patterns": [], "message": "No recent conversations to analyse."}
            patterns = self._detect_patterns(messages)
            for p in patterns:
                label = f"{p['intent']}@{p['time_window']}"
                self._upsert_habit(label, p["frequency"])
            return {"status": "ok", "patterns": patterns, "habits_updated": len(patterns)}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def get_habits(self):
        """Return all detected habits."""
        try:
            conn = self._get_conn()
            c = conn.cursor()
            c.execute("SELECT id, pattern, frequency, last_seen, suggested, automated FROM habits ORDER BY frequency DESC")
            rows = c.fetchall()
            conn.close()
            habits = [
                {
                    "id": r[0],
                    "pattern": r[1],
                    "frequency": r[2],
                    "last_seen": r[3],
                    "suggested": bool(r[4]),
                    "automated": bool(r[5]),
                }
                for r in rows
            ]
            return {"status": "ok", "habits": habits}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def suggest_automations(self, min_frequency=3):
        """Return habits that have been seen enough times to suggest automation."""
        try:
            conn = self._get_conn()
            c = conn.cursor()
            c.execute(
                "SELECT id, pattern, frequency, last_seen FROM habits "
                "WHERE frequency >= ? AND automated = 0 ORDER BY frequency DESC",
                (min_frequency,),
            )
            rows = c.fetchall()
            suggestions = []
            for r in rows:
                parts = r[1].split("@")
                intent = parts[0] if parts else r[1]
                time_window = parts[1] if len(parts) > 1 else "unknown"
                suggestions.append({
                    "habit_id": r[0],
                    "pattern": r[1],
                    "intent": intent,
                    "time_window": time_window,
                    "frequency": r[2],
                    "last_seen": r[3],
                    "suggestion": (
                        f"I notice you {intent} around {time_window} regularly "
                        f"({r[2]} times). Want me to do it automatically?"
                    ),
                })
            # Mark them as suggested
            if suggestions:
                ids = [s["habit_id"] for s in suggestions]
                placeholders = ",".join("?" * len(ids))
                c.execute(f"UPDATE habits SET suggested = 1 WHERE id IN ({placeholders})", ids)
                conn.commit()
            conn.close()
            return {"status": "ok", "suggestions": suggestions}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def add_scheduled_task(self, task_type, task_data, schedule):
        """Add a new scheduled task."""
        try:
            conn = self._get_conn()
            c = conn.cursor()
            now = datetime.now().isoformat()
            c.execute(
                "INSERT INTO scheduled_tasks (task_type, task_data, schedule, enabled, last_run, created_at) "
                "VALUES (?, ?, ?, 1, NULL, ?)",
                (task_type, json.dumps(task_data), schedule, now),
            )
            task_id = c.lastrowid
            conn.commit()
            conn.close()
            return {"status": "ok", "task_id": task_id, "message": f"Scheduled task '{task_type}' added."}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def list_scheduled(self):
        """List all scheduled tasks."""
        try:
            conn = self._get_conn()
            c = conn.cursor()
            c.execute(
                "SELECT id, task_type, task_data, schedule, enabled, last_run, created_at "
                "FROM scheduled_tasks ORDER BY created_at DESC"
            )
            rows = c.fetchall()
            conn.close()
            tasks = []
            for r in rows:
                try:
                    data = json.loads(r[2])
                except (json.JSONDecodeError, TypeError):
                    data = r[2]
                tasks.append({
                    "id": r[0],
                    "task_type": r[1],
                    "task_data": data,
                    "schedule": r[3],
                    "enabled": bool(r[4]),
                    "last_run": r[5],
                    "created_at": r[6],
                })
            return {"status": "ok", "tasks": tasks}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def remove_scheduled(self, task_id):
        """Remove a scheduled task by id."""
        try:
            conn = self._get_conn()
            c = conn.cursor()
            c.execute("DELETE FROM scheduled_tasks WHERE id = ?", (task_id,))
            deleted = c.rowcount
            conn.commit()
            conn.close()
            if deleted:
                return {"status": "ok", "message": f"Task {task_id} removed."}
            return {"status": "error", "error": f"Task {task_id} not found."}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def get_due_tasks(self):
        """Return tasks that are due to run right now."""
        try:
            conn = self._get_conn()
            c = conn.cursor()
            c.execute(
                "SELECT id, task_type, task_data, schedule, last_run "
                "FROM scheduled_tasks WHERE enabled = 1"
            )
            rows = c.fetchall()
            conn.close()
            due = []
            for r in rows:
                if self._task_is_due(r[3], r[4]):
                    try:
                        data = json.loads(r[2])
                    except (json.JSONDecodeError, TypeError):
                        data = r[2]
                    due.append({
                        "id": r[0],
                        "task_type": r[1],
                        "task_data": data,
                        "schedule": r[3],
                    })
            return {"status": "ok", "due_tasks": due}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def mark_task_ran(self, task_id):
        """Update last_run timestamp for a task after execution."""
        try:
            conn = self._get_conn()
            c = conn.cursor()
            c.execute(
                "UPDATE scheduled_tasks SET last_run = ? WHERE id = ?",
                (datetime.now().isoformat(), task_id),
            )
            conn.commit()
            conn.close()
            return {"status": "ok"}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def learn_preferences(self, hours=168):
        """Scan recent conversations, ask LLM to extract preferences, and save them."""
        try:
            messages = self._fetch_recent_conversations(hours=hours)
            if not messages:
                return {"status": "ok", "extracted": {}, "message": "No recent conversations to analyse."}

            # Build a condensed transcript (cap at ~4000 chars to fit context)
            transcript_parts = []
            total = 0
            for msg in messages:
                line = f"[{msg['timestamp']}] {msg['content']}"
                if total + len(line) > 4000:
                    break
                transcript_parts.append(line)
                total += len(line)
            transcript = "\n".join(transcript_parts)

            prefs = self._llm_extract_preferences(transcript)
            saved = {}
            if prefs and isinstance(prefs, dict) and self.memory:
                for key, value in prefs.items():
                    self.memory.set_preference(str(key), value)
                    saved[key] = value
            return {"status": "ok", "extracted": prefs, "saved": saved}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    # ------------------------------------------------------------------
    # process() dispatcher
    # ------------------------------------------------------------------
    def process(self, input_data):
        action = input_data.get("action", "analyze_patterns")

        try:
            if action == "analyze_patterns":
                return self.analyze_patterns(hours=input_data.get("hours", 168))

            elif action == "get_habits":
                return self.get_habits()

            elif action == "suggest_automations":
                return self.suggest_automations(
                    min_frequency=input_data.get("min_frequency", 3)
                )

            elif action == "add_scheduled_task":
                task_type = input_data.get("task_type")
                task_data = input_data.get("task_data", {})
                schedule = input_data.get("schedule")
                if not task_type or not schedule:
                    return {"status": "error", "error": "Missing required fields: task_type, schedule"}
                return self.add_scheduled_task(task_type, task_data, schedule)

            elif action == "list_scheduled":
                return self.list_scheduled()

            elif action == "remove_scheduled":
                task_id = input_data.get("task_id")
                if task_id is None:
                    return {"status": "error", "error": "Missing required field: task_id"}
                return self.remove_scheduled(task_id)

            elif action == "get_due_tasks":
                return self.get_due_tasks()

            elif action == "learn_preferences":
                return self.learn_preferences(hours=input_data.get("hours", 168))

            else:
                return {
                    "status": "error",
                    "error": (
                        f"Unknown action: {action}. Available: analyze_patterns, "
                        "get_habits, suggest_automations, add_scheduled_task, "
                        "list_scheduled, remove_scheduled, get_due_tasks, learn_preferences"
                    ),
                }
        except Exception as e:
            return {"status": "error", "error": str(e)}
