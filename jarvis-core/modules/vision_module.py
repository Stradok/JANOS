# modules/vision_module.py
import os
import sys
import sqlite3
import pickle
import base64
import threading
import time
import json
from pathlib import Path
from datetime import datetime

from .base import ModuleBase

# ---------------------------------------------------------------------------
# Lazy-loaded optional libraries
# ---------------------------------------------------------------------------
cv2 = None
face_recognition = None
easyocr = None
np = None

def _ensure_cv2():
    global cv2
    if cv2 is None:
        try:
            import cv2 as _cv2
            cv2 = _cv2
        except ImportError:
            raise ImportError("OpenCV not installed. Run: pip install opencv-python")
    return cv2

def _ensure_numpy():
    global np
    if np is None:
        import numpy as _np
        np = _np
    return np

def _ensure_face_recognition():
    global face_recognition
    if face_recognition is None:
        try:
            import face_recognition as _fr
            face_recognition = _fr
        except ImportError:
            raise ImportError("face_recognition not installed. Run: pip install face_recognition")
    return face_recognition

def _ensure_easyocr():
    global easyocr
    if easyocr is None:
        try:
            import easyocr as _easyocr
            easyocr = _easyocr
        except ImportError:
            raise ImportError("easyocr not installed. Run: pip install easyocr")
    return easyocr


class VisionModule(ModuleBase):
    """Camera, face detection/recognition, OCR, and image description for JAN."""

    OLLAMA_URL = "http://localhost:11434/api/chat"
    OLLAMA_MODEL = "llama3.1:8b"

    DB_PATH = Path("memory/jarvis_memory.db")
    FACES_DIR = Path("memory/vision/faces")
    CAPTURES_DIR = Path("memory/vision/captures")

    def __init__(self):
        super().__init__("vision")
        self.memory = None  # wired externally

        # Background stream state
        self._stream_cap = None
        self._stream_thread = None
        self._stream_running = False
        self._stream_lock = threading.Lock()
        self._latest_frame = None

        # EasyOCR reader cache (expensive to create)
        self._ocr_readers: dict = {}

        # Ensure directories exist
        self.FACES_DIR.mkdir(parents=True, exist_ok=True)
        self.CAPTURES_DIR.mkdir(parents=True, exist_ok=True)

        # Ensure DB table
        self._init_db()

    # ------------------------------------------------------------------
    # Database helpers
    # ------------------------------------------------------------------
    def _init_db(self):
        try:
            self.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self.DB_PATH))
            conn.execute(
                """CREATE TABLE IF NOT EXISTS known_faces (
                       id INTEGER PRIMARY KEY AUTOINCREMENT,
                       name TEXT NOT NULL,
                       encoding BLOB NOT NULL,
                       created_at TEXT
                   )"""
            )
            conn.commit()
            conn.close()
        except Exception as exc:
            print(f"[VisionModule] DB init warning: {exc}")

    def _db_conn(self):
        return sqlite3.connect(str(self.DB_PATH))

    # ------------------------------------------------------------------
    # Encoding serialisation  (numpy array <-> BLOB via pickle+base64)
    # ------------------------------------------------------------------
    @staticmethod
    def _encode_to_blob(encoding) -> bytes:
        return base64.b64encode(pickle.dumps(encoding))

    @staticmethod
    def _blob_to_encoding(blob):
        return pickle.loads(base64.b64decode(blob))

    # ------------------------------------------------------------------
    # process() dispatcher
    # ------------------------------------------------------------------
    def process(self, input_data):
        if isinstance(input_data, str):
            input_data = {"action": input_data}

        action = input_data.get("action", "").lower().strip()

        dispatch = {
            "capture": self._capture,
            "detect_faces": self._detect_faces,
            "recognize": self._recognize,
            "enroll_face": self._enroll_face,
            "enroll_from_camera": self._enroll_from_camera,
            "list_known_faces": self._list_known_faces,
            "delete_face": self._delete_face,
            "read_text": self._read_text,
            "describe": self._describe,
            "stream_start": self._stream_start,
            "stream_stop": self._stream_stop,
            "stream_capture": self._stream_capture,
        }

        handler = dispatch.get(action)
        if handler is None:
            return {
                "error": f"Unknown vision action '{action}'",
                "available": list(dispatch.keys()),
            }

        try:
            return handler(input_data)
        except ImportError as exc:
            return {"error": str(exc)}
        except Exception as exc:
            return {"error": f"[{action}] {type(exc).__name__}: {exc}"}

    # ------------------------------------------------------------------
    # ACTION: capture
    # ------------------------------------------------------------------
    def _capture(self, data):
        _ensure_cv2()
        camera_id = int(data.get("camera_id", 0))
        save_path = data.get("save_path")

        cap = cv2.VideoCapture(camera_id)
        if not cap.isOpened():
            return {"error": f"Cannot open camera {camera_id}"}

        # Let the camera warm up
        for _ in range(5):
            cap.read()

        ret, frame = cap.read()
        cap.release()

        if not ret or frame is None:
            return {"error": "Failed to capture frame from camera"}

        if not save_path:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            save_path = str(self.CAPTURES_DIR / f"capture_{ts}.jpg")

        Path(save_path).parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(save_path, frame)
        return {"status": "ok", "path": save_path, "resolution": list(frame.shape[:2])}

    # ------------------------------------------------------------------
    # ACTION: detect_faces  (OpenCV cascade — always available)
    # ------------------------------------------------------------------
    def _detect_faces(self, data):
        _ensure_cv2()
        _ensure_numpy()

        image_path = data.get("image_path")
        if not image_path or not os.path.isfile(image_path):
            return {"error": f"Image not found: {image_path}"}

        img = cv2.imread(image_path)
        if img is None:
            return {"error": f"Could not read image: {image_path}"}

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        cascade = cv2.CascadeClassifier(cascade_path)

        faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))

        locations = []
        for (x, y, w, h) in faces:
            locations.append({"x": int(x), "y": int(y), "w": int(w), "h": int(h)})

        return {"status": "ok", "face_count": len(locations), "faces": locations}

    # ------------------------------------------------------------------
    # ACTION: recognize  (face_recognition library)
    # ------------------------------------------------------------------
    def _recognize(self, data):
        _ensure_numpy()

        image_path = data.get("image_path")
        if not image_path or not os.path.isfile(image_path):
            return {"error": f"Image not found: {image_path}"}

        # Try face_recognition first; fall back to detection-only
        try:
            fr = _ensure_face_recognition()
        except ImportError:
            result = self._detect_faces(data)
            result["warning"] = "face_recognition not installed — returning detection only (no names)"
            return result

        img = fr.load_image_file(image_path)
        locations = fr.face_locations(img)
        encodings = fr.face_encodings(img, locations)

        if not encodings:
            return {"status": "ok", "face_count": 0, "results": []}

        # Load known faces from DB
        known_names, known_encodings = self._load_known_faces()

        results = []
        for enc, loc in zip(encodings, locations):
            top, right, bottom, left = loc
            match = {"name": "unknown", "confidence": 0.0, "location": {"top": top, "right": right, "bottom": bottom, "left": left}}

            if known_encodings:
                distances = fr.face_distance(known_encodings, enc)
                best_idx = int(np.argmin(distances))
                best_dist = float(distances[best_idx])
                confidence = round(max(0.0, 1.0 - best_dist), 4)

                if best_dist <= 0.6:  # standard threshold
                    match["name"] = known_names[best_idx]
                    match["confidence"] = confidence

            results.append(match)

        return {"status": "ok", "face_count": len(results), "results": results}

    def _load_known_faces(self):
        names, encodings = [], []
        try:
            conn = self._db_conn()
            rows = conn.execute("SELECT name, encoding FROM known_faces").fetchall()
            conn.close()
            for name, blob in rows:
                names.append(name)
                encodings.append(self._blob_to_encoding(blob))
        except Exception as exc:
            print(f"[VisionModule] Error loading known faces: {exc}")
        return names, encodings

    # ------------------------------------------------------------------
    # ACTION: enroll_face
    # ------------------------------------------------------------------
    def _enroll_face(self, data):
        fr = _ensure_face_recognition()
        _ensure_numpy()

        image_path = data.get("image_path")
        name = data.get("name", "").strip()
        if not name:
            return {"error": "name is required for enrollment"}
        if not image_path or not os.path.isfile(image_path):
            return {"error": f"Image not found: {image_path}"}

        img = fr.load_image_file(image_path)
        encodings = fr.face_encodings(img)
        if not encodings:
            return {"error": "No face detected in the image"}

        encoding = encodings[0]  # enroll the first face found
        blob = self._encode_to_blob(encoding)

        conn = self._db_conn()
        conn.execute(
            "INSERT INTO known_faces (name, encoding, created_at) VALUES (?, ?, ?)",
            (name, blob, datetime.now().isoformat()),
        )
        conn.commit()
        conn.close()

        # Save a copy of the face image
        face_img_path = self.FACES_DIR / f"{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
        _ensure_cv2()
        cv2.imwrite(str(face_img_path), cv2.imread(image_path))

        return {"status": "ok", "message": f"Enrolled '{name}'", "face_image": str(face_img_path)}

    # ------------------------------------------------------------------
    # ACTION: enroll_from_camera
    # ------------------------------------------------------------------
    def _enroll_from_camera(self, data):
        name = data.get("name", "").strip()
        if not name:
            return {"error": "name is required for enrollment"}

        camera_id = int(data.get("camera_id", 0))

        # Capture a photo first
        cap_result = self._capture({"camera_id": camera_id})
        if "error" in cap_result:
            return cap_result

        image_path = cap_result["path"]
        return self._enroll_face({"image_path": image_path, "name": name})

    # ------------------------------------------------------------------
    # ACTION: list_known_faces
    # ------------------------------------------------------------------
    def _list_known_faces(self, _data):
        try:
            conn = self._db_conn()
            rows = conn.execute("SELECT id, name, created_at FROM known_faces ORDER BY name").fetchall()
            conn.close()
            faces = [{"id": r[0], "name": r[1], "created_at": r[2]} for r in rows]
            return {"status": "ok", "count": len(faces), "faces": faces}
        except Exception as exc:
            return {"error": f"DB error: {exc}"}

    # ------------------------------------------------------------------
    # ACTION: delete_face
    # ------------------------------------------------------------------
    def _delete_face(self, data):
        name = data.get("name", "").strip()
        if not name:
            return {"error": "name is required"}

        try:
            conn = self._db_conn()
            cursor = conn.execute("DELETE FROM known_faces WHERE name = ?", (name,))
            deleted = cursor.rowcount
            conn.commit()
            conn.close()

            if deleted == 0:
                return {"error": f"No face found with name '{name}'"}
            return {"status": "ok", "message": f"Deleted {deleted} face(s) for '{name}'"}
        except Exception as exc:
            return {"error": f"DB error: {exc}"}

    # ------------------------------------------------------------------
    # ACTION: read_text  (OCR via easyocr)
    # ------------------------------------------------------------------
    def _read_text(self, data):
        image_path = data.get("image_path")
        language = data.get("language", "en")

        if not image_path or not os.path.isfile(image_path):
            return {"error": f"Image not found: {image_path}"}

        try:
            _ensure_easyocr()
        except ImportError:
            return {"error": "easyocr not installed. Run: pip install easyocr"}

        # Cache readers per language combo
        lang_key = language if isinstance(language, str) else ",".join(language)
        if lang_key not in self._ocr_readers:
            langs = [language] if isinstance(language, str) else language
            self._ocr_readers[lang_key] = easyocr.Reader(langs, gpu=False)

        reader = self._ocr_readers[lang_key]
        results = reader.readtext(image_path)

        texts = []
        for bbox, text, conf in results:
            texts.append({"text": text, "confidence": round(float(conf), 4), "bbox": bbox})

        full_text = " ".join(r["text"] for r in texts)
        return {"status": "ok", "text": full_text, "details": texts}

    # ------------------------------------------------------------------
    # ACTION: describe  (Ollama LLM)
    # ------------------------------------------------------------------
    def _describe(self, data):
        image_path = data.get("image_path")
        if not image_path or not os.path.isfile(image_path):
            return {"error": f"Image not found: {image_path}"}

        # Build a context string from face detection + OCR (best-effort)
        parts = []

        # Face detection (always available via OpenCV)
        try:
            face_result = self._detect_faces({"image_path": image_path})
            if face_result.get("face_count", 0) > 0:
                parts.append(f"Detected {face_result['face_count']} face(s).")

                # Try recognition
                try:
                    rec = self._recognize({"image_path": image_path})
                    if rec.get("results"):
                        names = [r["name"] for r in rec["results"] if r["name"] != "unknown"]
                        if names:
                            parts.append(f"Recognized: {', '.join(names)}.")
                except Exception:
                    pass
        except Exception:
            pass

        # OCR (best-effort)
        try:
            ocr = self._read_text({"image_path": image_path})
            if ocr.get("text", "").strip():
                parts.append(f"Text found in image: \"{ocr['text'].strip()[:300]}\"")
        except Exception:
            pass

        # Read image metadata
        try:
            _ensure_cv2()
            img = cv2.imread(image_path)
            if img is not None:
                h, w = img.shape[:2]
                parts.append(f"Image dimensions: {w}x{h}.")
        except Exception:
            pass

        context = " ".join(parts) if parts else "No preliminary analysis available."

        prompt = (
            f"I have an image and here is what automated analysis found:\n{context}\n\n"
            "Based on this analysis, provide a concise, natural-language description of "
            "what is likely in this image. Describe the scene, people, objects, and any "
            "text you see. Be helpful and specific."
        )

        try:
            import requests
            payload = {
                "model": self.OLLAMA_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
            }
            resp = requests.post(self.OLLAMA_URL, json=payload, timeout=60)
            resp.raise_for_status()
            answer = resp.json().get("message", {}).get("content", "").strip()
            return {"status": "ok", "description": answer, "analysis": context}
        except Exception as exc:
            return {
                "status": "ok",
                "description": context,
                "warning": f"LLM unavailable ({exc}), returning raw analysis only",
            }

    # ------------------------------------------------------------------
    # ACTION: stream_start
    # ------------------------------------------------------------------
    def _stream_start(self, data):
        _ensure_cv2()
        camera_id = int(data.get("camera_id", 0))

        with self._stream_lock:
            if self._stream_running:
                return {"error": "Stream already running. Stop it first."}

            cap = cv2.VideoCapture(camera_id)
            if not cap.isOpened():
                return {"error": f"Cannot open camera {camera_id}"}

            self._stream_cap = cap
            self._stream_running = True
            self._latest_frame = None

            def _reader():
                while self._stream_running:
                    ret, frame = self._stream_cap.read()
                    if ret and frame is not None:
                        with self._stream_lock:
                            self._latest_frame = frame
                    time.sleep(0.03)  # ~30 fps cap

            self._stream_thread = threading.Thread(target=_reader, daemon=True)
            self._stream_thread.start()

        return {"status": "ok", "message": f"Stream started on camera {camera_id}"}

    # ------------------------------------------------------------------
    # ACTION: stream_stop
    # ------------------------------------------------------------------
    def _stream_stop(self, _data):
        with self._stream_lock:
            if not self._stream_running:
                return {"error": "No stream is running"}

            self._stream_running = False

        if self._stream_thread:
            self._stream_thread.join(timeout=3)
            self._stream_thread = None

        if self._stream_cap:
            self._stream_cap.release()
            self._stream_cap = None

        self._latest_frame = None
        return {"status": "ok", "message": "Stream stopped"}

    # ------------------------------------------------------------------
    # ACTION: stream_capture
    # ------------------------------------------------------------------
    def _stream_capture(self, data):
        _ensure_cv2()
        with self._stream_lock:
            if not self._stream_running or self._latest_frame is None:
                return {"error": "No active stream or no frame available"}
            frame = self._latest_frame.copy()

        save_path = data.get("save_path")
        if not save_path:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            save_path = str(self.CAPTURES_DIR / f"stream_{ts}.jpg")

        Path(save_path).parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(save_path, frame)
        return {"status": "ok", "path": save_path, "resolution": list(frame.shape[:2])}
