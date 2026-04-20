# modules/person_recognition_module.py
"""
Multi-modal person recognition for JAN (Joint Autonomous Neural Agent).
Combines face recognition (via VisionModule) and voice recognition (via resemblyzer)
to identify and manage multiple users with individual preferences.
"""
import os
import json
import base64
import pickle
import sqlite3
import requests
from datetime import datetime
from pathlib import Path

import numpy as np

try:
    from resemblyzer import VoiceEncoder, preprocess_wav
    RESEMBLYZER_AVAILABLE = True
except ImportError:
    RESEMBLYZER_AVAILABLE = False

from .base import ModuleBase


class PersonRecognitionModule(ModuleBase):
    """Multi-modal person identification combining face + voice recognition."""

    VOICE_SIMILARITY_THRESHOLD = 0.75
    FACE_CONFIDENCE_THRESHOLD = 0.6
    OLLAMA_URL = "http://localhost:11434/api/chat"
    OLLAMA_MODEL = "llama3.1:8b"

    def __init__(self):
        super().__init__("person_recognition")
        self.memory = None   # wired externally (MemoryModule)
        self.vision = None   # wired externally (VisionModule)

        self.db_path = Path("memory/jarvis_memory.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self.voices_dir = Path("memory/vision/voices")
        self.voices_dir.mkdir(parents=True, exist_ok=True)

        self._voice_encoder = None  # lazy-loaded
        self._init_db()

    # ── database ────────────────────────────────────────────────────

    def _init_db(self):
        conn = sqlite3.connect(str(self.db_path))
        c = conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS persons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            face_enrolled BOOLEAN DEFAULT 0,
            voice_enrolled BOOLEAN DEFAULT 0,
            voice_embedding BLOB,
            preferences TEXT DEFAULT '{}',
            last_seen TEXT,
            created_at TEXT
        )""")
        conn.commit()
        conn.close()

    def _db(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    # ── voice encoder (lazy) ────────────────────────────────────────

    def _get_voice_encoder(self):
        if not RESEMBLYZER_AVAILABLE:
            return None
        if self._voice_encoder is None:
            self._voice_encoder = VoiceEncoder()
        return self._voice_encoder

    # ── embedding serialization ─────────────────────────────────────

    @staticmethod
    def _serialize_embedding(embedding):
        return base64.b64encode(pickle.dumps(embedding)).decode("utf-8")

    @staticmethod
    def _deserialize_embedding(encoded_str):
        return pickle.loads(base64.b64decode(encoded_str))

    @staticmethod
    def _cosine_similarity(a, b):
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))

    # ── voice helpers ───────────────────────────────────────────────

    def _compute_voice_embedding(self, audio_path: str):
        encoder = self._get_voice_encoder()
        if encoder is None:
            return None, "resemblyzer not installed — run: pip install resemblyzer"
        if not os.path.isfile(audio_path):
            return None, f"Audio file not found: {audio_path}"
        try:
            wav = preprocess_wav(Path(audio_path))
            embedding = encoder.embed_utterance(wav)
            return embedding, None
        except Exception as e:
            return None, f"Voice embedding failed: {e}"

    def _match_voice(self, embedding):
        """Compare embedding against all enrolled voice profiles."""
        conn = self._db()
        rows = conn.execute(
            "SELECT name, voice_embedding FROM persons WHERE voice_enrolled = 1"
        ).fetchall()
        conn.close()

        best_name = None
        best_sim = -1.0
        for row in rows:
            stored = self._deserialize_embedding(row["voice_embedding"])
            sim = self._cosine_similarity(embedding, stored)
            if sim > best_sim:
                best_sim = sim
                best_name = row["name"]

        if best_name and best_sim >= self.VOICE_SIMILARITY_THRESHOLD:
            return best_name, best_sim
        return None, best_sim

    # ── face helpers (delegates to VisionModule) ────────────────────

    def _identify_face(self, image_path: str = None):
        """Use the wired VisionModule to recognize a face."""
        if self.vision is None:
            return None, 0.0, "VisionModule not wired"
        try:
            if image_path:
                result = self.vision.process({"action": "recognize", "image_path": image_path})
            else:
                result = self.vision.process({"action": "recognize"})

            if isinstance(result, dict):
                if result.get("status") == "ok" or "name" in result:
                    name = result.get("name")
                    confidence = float(result.get("confidence", 0.0))
                    if name and name.lower() != "unknown" and confidence >= self.FACE_CONFIDENCE_THRESHOLD:
                        return name, confidence, None
                    return None, confidence, None
                return None, 0.0, result.get("error", "Face recognition returned no match")
            return None, 0.0, "Unexpected vision response"
        except Exception as e:
            return None, 0.0, f"Face recognition error: {e}"

    def _enroll_face(self, name: str, image_path: str = None):
        if self.vision is None:
            return {"error": "VisionModule not wired"}
        try:
            payload = {"action": "enroll_face", "name": name}
            if image_path:
                payload["image_path"] = image_path
            result = self.vision.process(payload)
            if isinstance(result, dict) and result.get("error"):
                return result
            return {"status": "ok"}
        except Exception as e:
            return {"error": f"Face enrollment error: {e}"}

    # ── person CRUD ─────────────────────────────────────────────────

    def _get_person_row(self, name: str):
        conn = self._db()
        row = conn.execute("SELECT * FROM persons WHERE name = ?", (name,)).fetchone()
        conn.close()
        return row

    def _touch_last_seen(self, name: str):
        conn = self._db()
        conn.execute(
            "UPDATE persons SET last_seen = ? WHERE name = ?",
            (datetime.now().isoformat(), name),
        )
        conn.commit()
        conn.close()

    # ── Ollama greeting ─────────────────────────────────────────────

    def _generate_greeting(self, name: str, preferences: dict):
        hour = datetime.now().hour
        if hour < 12:
            time_of_day = "morning"
        elif hour < 17:
            time_of_day = "afternoon"
        else:
            time_of_day = "evening"

        prefs_str = json.dumps(preferences) if preferences else "none stored"
        prompt = (
            f"You are JAN, a friendly AI assistant. Generate a short, warm, personalized "
            f"greeting for {name}. It is currently {time_of_day}. "
            f"Their preferences: {prefs_str}. "
            f"Keep it to 1-2 sentences. Be natural and friendly."
        )
        try:
            resp = requests.post(
                self.OLLAMA_URL,
                json={
                    "model": self.OLLAMA_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                },
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            greeting = data.get("message", {}).get("content", "").strip()
            if greeting:
                return greeting
            return f"Good {time_of_day}, {name}!"
        except Exception:
            return f"Good {time_of_day}, {name}!"

    # ── actions ─────────────────────────────────────────────────────

    def _action_identify(self, input_data: dict) -> dict:
        image_path = input_data.get("image_path")
        audio_path = input_data.get("audio_path")

        if not image_path and not audio_path:
            return {"error": "Provide at least one of image_path or audio_path"}

        face_name, face_conf, face_err = None, 0.0, None
        voice_name, voice_conf, voice_err = None, 0.0, None

        # Face identification
        if image_path:
            face_name, face_conf, face_err = self._identify_face(image_path)

        # Voice identification
        if audio_path:
            embedding, err = self._compute_voice_embedding(audio_path)
            if embedding is not None:
                voice_name, voice_conf = self._match_voice(embedding)
                if voice_name is None:
                    voice_conf = 0.0
            else:
                voice_err = err

        # Fuse results
        if face_name and voice_name:
            if face_name == voice_name:
                combined = (face_conf + voice_conf) / 2.0
                self._touch_last_seen(face_name)
                return {"status": "ok", "name": face_name, "confidence": round(combined, 4), "method": "both"}
            # Disagreement — pick the higher confidence
            if face_conf >= voice_conf:
                self._touch_last_seen(face_name)
                return {"status": "ok", "name": face_name, "confidence": round(face_conf, 4), "method": "face"}
            else:
                self._touch_last_seen(voice_name)
                return {"status": "ok", "name": voice_name, "confidence": round(voice_conf, 4), "method": "voice"}

        if face_name:
            self._touch_last_seen(face_name)
            return {"status": "ok", "name": face_name, "confidence": round(face_conf, 4), "method": "face"}

        if voice_name:
            self._touch_last_seen(voice_name)
            return {"status": "ok", "name": voice_name, "confidence": round(voice_conf, 4), "method": "voice"}

        errors = []
        if face_err:
            errors.append(face_err)
        if voice_err:
            errors.append(voice_err)
        msg = "No match found"
        if errors:
            msg += f" ({'; '.join(errors)})"
        return {"status": "ok", "name": None, "confidence": 0.0, "method": None, "message": msg}

    def _action_enroll_person(self, input_data: dict) -> dict:
        name = input_data.get("name")
        if not name:
            return {"error": "name is required"}

        image_path = input_data.get("image_path")
        audio_path = input_data.get("audio_path")
        now = datetime.now().isoformat()

        conn = self._db()
        existing = conn.execute("SELECT id FROM persons WHERE name = ?", (name,)).fetchone()
        if existing:
            conn.close()
            return {"error": f"Person '{name}' already exists — use enroll_voice or update_preferences"}
        conn.close()

        face_enrolled = False
        voice_enrolled = False
        voice_blob = None
        errors = []

        # Face enrollment
        if image_path:
            result = self._enroll_face(name, image_path)
            if result.get("error"):
                errors.append(result["error"])
            else:
                face_enrolled = True

        # Voice enrollment
        if audio_path:
            embedding, err = self._compute_voice_embedding(audio_path)
            if embedding is not None:
                voice_blob = self._serialize_embedding(embedding)
                voice_enrolled = True
                # Save audio copy
                try:
                    import shutil
                    dest = self.voices_dir / f"{name}{Path(audio_path).suffix}"
                    shutil.copy2(audio_path, str(dest))
                except Exception:
                    pass
            else:
                errors.append(err)

        conn = self._db()
        conn.execute(
            """INSERT INTO persons (name, face_enrolled, voice_enrolled, voice_embedding, preferences, last_seen, created_at)
               VALUES (?, ?, ?, ?, '{}', ?, ?)""",
            (name, int(face_enrolled), int(voice_enrolled), voice_blob, now, now),
        )
        conn.commit()
        conn.close()

        result = {
            "status": "ok",
            "name": name,
            "face_enrolled": face_enrolled,
            "voice_enrolled": voice_enrolled,
        }
        if errors:
            result["warnings"] = errors
        return result

    def _action_enroll_voice(self, input_data: dict) -> dict:
        name = input_data.get("name")
        audio_path = input_data.get("audio_path")
        if not name or not audio_path:
            return {"error": "name and audio_path are required"}

        row = self._get_person_row(name)
        if row is None:
            return {"error": f"Person '{name}' not found — enroll_person first"}

        embedding, err = self._compute_voice_embedding(audio_path)
        if embedding is None:
            return {"error": err}

        voice_blob = self._serialize_embedding(embedding)

        # Save audio copy
        try:
            import shutil
            dest = self.voices_dir / f"{name}{Path(audio_path).suffix}"
            shutil.copy2(audio_path, str(dest))
        except Exception:
            pass

        conn = self._db()
        conn.execute(
            "UPDATE persons SET voice_enrolled = 1, voice_embedding = ?, last_seen = ? WHERE name = ?",
            (voice_blob, datetime.now().isoformat(), name),
        )
        conn.commit()
        conn.close()

        return {"status": "ok", "name": name, "voice_enrolled": True}

    def _action_update_preferences(self, input_data: dict) -> dict:
        name = input_data.get("name")
        preferences = input_data.get("preferences")
        if not name:
            return {"error": "name is required"}
        if not isinstance(preferences, dict):
            return {"error": "preferences must be a dict"}

        row = self._get_person_row(name)
        if row is None:
            return {"error": f"Person '{name}' not found"}

        # Merge with existing preferences
        try:
            existing = json.loads(row["preferences"] or "{}")
        except (json.JSONDecodeError, TypeError):
            existing = {}
        existing.update(preferences)

        conn = self._db()
        conn.execute(
            "UPDATE persons SET preferences = ? WHERE name = ?",
            (json.dumps(existing), name),
        )
        conn.commit()
        conn.close()

        return {"status": "ok", "name": name, "preferences": existing}

    def _action_get_person(self, input_data: dict) -> dict:
        name = input_data.get("name")
        if not name:
            return {"error": "name is required"}

        row = self._get_person_row(name)
        if row is None:
            return {"error": f"Person '{name}' not found"}

        try:
            prefs = json.loads(row["preferences"] or "{}")
        except (json.JSONDecodeError, TypeError):
            prefs = {}

        return {
            "status": "ok",
            "person": {
                "id": row["id"],
                "name": row["name"],
                "face_enrolled": bool(row["face_enrolled"]),
                "voice_enrolled": bool(row["voice_enrolled"]),
                "preferences": prefs,
                "last_seen": row["last_seen"],
                "created_at": row["created_at"],
            },
        }

    def _action_list_persons(self, _input_data: dict) -> dict:
        conn = self._db()
        rows = conn.execute(
            "SELECT id, name, face_enrolled, voice_enrolled, preferences, last_seen, created_at FROM persons ORDER BY name"
        ).fetchall()
        conn.close()

        persons = []
        for r in rows:
            try:
                prefs = json.loads(r["preferences"] or "{}")
            except (json.JSONDecodeError, TypeError):
                prefs = {}
            persons.append({
                "id": r["id"],
                "name": r["name"],
                "face_enrolled": bool(r["face_enrolled"]),
                "voice_enrolled": bool(r["voice_enrolled"]),
                "preferences": prefs,
                "last_seen": r["last_seen"],
                "created_at": r["created_at"],
            })

        return {"status": "ok", "persons": persons, "count": len(persons)}

    def _action_delete_person(self, input_data: dict) -> dict:
        name = input_data.get("name")
        if not name:
            return {"error": "name is required"}

        row = self._get_person_row(name)
        if row is None:
            return {"error": f"Person '{name}' not found"}

        conn = self._db()
        conn.execute("DELETE FROM persons WHERE name = ?", (name,))
        conn.commit()
        conn.close()

        # Clean up voice file
        for ext in (".wav", ".m4a", ".mp3", ".flac", ".ogg"):
            vf = self.voices_dir / f"{name}{ext}"
            if vf.exists():
                try:
                    vf.unlink()
                except Exception:
                    pass

        return {"status": "ok", "message": f"Deleted person '{name}'"}

    def _action_greet(self, input_data: dict) -> dict:
        id_result = self._action_identify(input_data)

        name = id_result.get("name")
        if not name:
            return {"status": "ok", "greeting": "Hello! I don't think we've met. What's your name?", "identified": False}

        row = self._get_person_row(name)
        try:
            prefs = json.loads(row["preferences"] or "{}") if row else {}
        except (json.JSONDecodeError, TypeError):
            prefs = {}

        greeting = self._generate_greeting(name, prefs)

        return {
            "status": "ok",
            "greeting": greeting,
            "identified": True,
            "name": name,
            "confidence": id_result.get("confidence", 0.0),
            "method": id_result.get("method"),
        }

    def _action_who_is_this(self, input_data: dict) -> dict:
        source = input_data.get("source", "both")
        camera_id = input_data.get("camera_id", 0)
        audio_path = input_data.get("audio_path")

        identify_input = {}

        # Capture from camera if requested
        if source in ("camera", "both"):
            if self.vision is not None:
                try:
                    cap_result = self.vision.process({"action": "capture", "camera_id": camera_id})
                    if isinstance(cap_result, dict) and cap_result.get("image_path"):
                        identify_input["image_path"] = cap_result["image_path"]
                    elif isinstance(cap_result, dict) and cap_result.get("path"):
                        identify_input["image_path"] = cap_result["path"]
                except Exception as e:
                    if source == "camera":
                        return {"error": f"Camera capture failed: {e}"}
            else:
                if source == "camera":
                    return {"error": "VisionModule not wired — cannot capture from camera"}

        # Voice from audio if requested
        if source in ("audio", "both"):
            if audio_path:
                identify_input["audio_path"] = audio_path
            elif source == "audio":
                return {"error": "audio_path is required when source is 'audio'"}

        if not identify_input:
            return {"error": "No input sources available for identification"}

        return self._action_identify(identify_input)

    # ── process dispatch ────────────────────────────────────────────

    def process(self, input_data: dict) -> dict:
        if not isinstance(input_data, dict):
            return {"error": "input_data must be a dict"}

        action = input_data.get("action")
        if not action:
            return {"error": "action is required"}

        dispatch = {
            "identify": self._action_identify,
            "enroll_person": self._action_enroll_person,
            "enroll_voice": self._action_enroll_voice,
            "update_preferences": self._action_update_preferences,
            "get_person": self._action_get_person,
            "list_persons": self._action_list_persons,
            "delete_person": self._action_delete_person,
            "greet": self._action_greet,
            "who_is_this": self._action_who_is_this,
        }

        handler = dispatch.get(action)
        if handler is None:
            return {"error": f"Unknown action '{action}'. Available: {', '.join(sorted(dispatch))}"}

        try:
            return handler(input_data)
        except Exception as e:
            return {"error": f"Action '{action}' failed: {e}"}
