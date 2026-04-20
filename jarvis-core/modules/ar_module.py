"""
ARModule — Augmented Reality module for JAN.

Provides AR capabilities via phone camera or VR headset over WebSocket.
Clients stream camera frames; JAN processes them (OCR, object detection,
navigation, translation, face labeling) and returns JSON overlay instructions.
"""

import asyncio
import base64
import json
import math
import os
import threading
import time

from .base import ModuleBase

try:
    import websockets
    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False

try:
    import cv2
    import numpy as np
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

try:
    import easyocr
    HAS_EASYOCR = True
except ImportError:
    HAS_EASYOCR = False

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _calc_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return bearing in degrees (0-360) from point 1 to point 2."""
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = (math.cos(lat1) * math.sin(lat2)
         - math.sin(lat1) * math.cos(lat2) * math.cos(dlon))
    bearing = math.degrees(math.atan2(x, y))
    return (bearing + 360) % 360


def _calc_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance in metres between two GPS points."""
    R = 6_371_000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1))
         * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _bearing_to_direction(bearing: float) -> str:
    """Convert a bearing (0-360) to a human-readable compass direction."""
    dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    idx = int((bearing + 22.5) % 360 // 45)
    return dirs[idx]


# ---------------------------------------------------------------------------
# ARModule
# ---------------------------------------------------------------------------

class ARModule(ModuleBase):
    """Augmented-reality overlay server for phone / VR clients."""

    OLLAMA_URL = "http://localhost:11434/api/chat"
    OLLAMA_MODEL = "llama3.1:8b"

    def __init__(self):
        super().__init__("ar")

        # Wired externally after construction
        self.vision = None          # VisionModule instance
        self.memory = None          # MemoryModule instance

        # WebSocket state
        self._ws_server = None
        self._clients: set = set()
        self._running = False
        self._loop = None
        self._thread = None

        # Navigation state (shared across clients for simplicity)
        self._destination = None    # {"lat": float, "lon": float, "name": str}
        self._current_gps = None    # {"lat": float, "lon": float}

        # Lazy-initialised OCR reader
        self._ocr_reader = None

    # ------------------------------------------------------------------
    # process() dispatcher
    # ------------------------------------------------------------------

    def process(self, input_data):
        action = input_data.get("action", "")
        try:
            handler = {
                "start_server":   self._action_start_server,
                "stop_server":    self._action_stop_server,
                "server_status":  self._action_server_status,
                "translate_image": self._action_translate_image,
                "navigate_to":    self._action_navigate_to,
                "get_direction":  self._action_get_direction,
                "send_overlay":   self._action_send_overlay,
                "process_frame":  self._action_process_frame,
            }.get(action)
            if handler is None:
                return {"status": "error", "message": f"Unknown action: {action}"}
            return handler(input_data)
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _action_start_server(self, data):
        if not HAS_WEBSOCKETS:
            return {"status": "error",
                    "message": "websockets library not installed. pip install websockets"}
        if self._running:
            return {"status": "error", "message": "Server is already running"}

        host = data.get("host", "0.0.0.0")
        port = data.get("port", 8765)
        self._running = True
        self._thread = threading.Thread(
            target=self._run_server, args=(host, port), daemon=True
        )
        self._thread.start()
        # Give the server a moment to bind
        time.sleep(0.5)
        return {"status": "ok", "message": f"AR server starting on ws://{host}:{port}"}

    def _action_stop_server(self, _data):
        if not self._running:
            return {"status": "error", "message": "Server is not running"}
        self._running = False
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        self._ws_server = None
        self._loop = None
        self._clients.clear()
        return {"status": "ok", "message": "AR server stopped"}

    def _action_server_status(self, _data):
        return {
            "status": "ok",
            "running": self._running,
            "clients": len(self._clients),
        }

    def _action_translate_image(self, data):
        image_path = data.get("image_path")
        if not image_path or not os.path.isfile(image_path):
            return {"status": "error", "message": "Valid image_path required"}
        target_lang = data.get("target_language", "en")

        text = self._ocr(image_path)
        if not text:
            return {"status": "ok", "translated": "", "original": "",
                    "overlay": {"type": "overlay", "elements": []}}

        translated = self._llm_translate(text, target_lang)
        overlay = {
            "type": "overlay",
            "elements": [
                {"kind": "text", "text": translated,
                 "x": 10, "y": 30, "color": "#FFFFFF", "size": 24}
            ],
        }
        return {"status": "ok", "original": text, "translated": translated,
                "overlay": overlay}

    def _action_navigate_to(self, data):
        lat = data.get("lat")
        lon = data.get("lon")
        name = data.get("name", "Destination")
        if lat is None or lon is None:
            return {"status": "error", "message": "lat and lon required"}
        self._destination = {"lat": float(lat), "lon": float(lon), "name": str(name)}
        return {"status": "ok", "destination": self._destination}

    def _action_get_direction(self, data):
        cur_lat = data.get("current_lat")
        cur_lon = data.get("current_lon")
        dest_lat = data.get("dest_lat")
        dest_lon = data.get("dest_lon")
        if None in (cur_lat, cur_lon, dest_lat, dest_lon):
            return {"status": "error",
                    "message": "current_lat, current_lon, dest_lat, dest_lon required"}
        cur_lat, cur_lon = float(cur_lat), float(cur_lon)
        dest_lat, dest_lon = float(dest_lat), float(dest_lon)
        bearing = _calc_bearing(cur_lat, cur_lon, dest_lat, dest_lon)
        distance = _calc_distance(cur_lat, cur_lon, dest_lat, dest_lon)
        direction = _bearing_to_direction(bearing)
        return {
            "status": "ok",
            "bearing": round(bearing, 2),
            "distance_m": round(distance, 2),
            "direction": direction,
            "overlay": {
                "type": "overlay",
                "elements": [
                    {"kind": "arrow", "from_x": 160, "from_y": 320,
                     "angle": bearing, "length": 100, "color": "#00FFFF"},
                    {"kind": "text",
                     "text": f"{direction} — {_fmt_distance(distance)}",
                     "x": 120, "y": 440, "color": "#00FFFF", "size": 20},
                ],
            },
        }

    def _action_send_overlay(self, data):
        elements = data.get("elements")
        if elements is None:
            return {"status": "error", "message": "elements list required"}
        overlay = {"type": "overlay", "elements": elements}
        self._broadcast(overlay)
        return {"status": "ok", "sent_to": len(self._clients)}

    def _action_process_frame(self, data):
        frame_data = data.get("frame_data")
        mode = data.get("mode", "detect")
        if not frame_data:
            return {"status": "error", "message": "frame_data (base64 jpeg) required"}
        return self._handle_frame(frame_data, mode)

    # ------------------------------------------------------------------
    # WebSocket server
    # ------------------------------------------------------------------

    def _run_server(self, host: str, port: int):
        """Entry point for the background server thread."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._serve(host, port))
            self._loop.run_forever()
        except Exception:
            pass
        finally:
            self._loop.close()
            self._running = False

    async def _serve(self, host: str, port: int):
        self._ws_server = await websockets.serve(
            self._client_handler, host, port
        )

    async def _client_handler(self, websocket, _path=None):
        self._clients.add(websocket)
        try:
            async for raw in websocket:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    await websocket.send(json.dumps(
                        {"type": "error", "message": "Invalid JSON"}))
                    continue
                response = self._dispatch_ws_message(msg)
                if response is not None:
                    await websocket.send(json.dumps(response))
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self._clients.discard(websocket)

    def _dispatch_ws_message(self, msg: dict):
        """Route an incoming WebSocket message to the right handler."""
        msg_type = msg.get("type", "")
        if msg_type == "frame":
            mode = msg.get("mode", "detect")
            frame_data = msg.get("data", "")
            return self._handle_frame(frame_data, mode)
        elif msg_type == "gps":
            self._current_gps = {"lat": msg.get("lat"), "lon": msg.get("lon")}
            return None  # silent ack
        elif msg_type == "set_destination":
            self._destination = {
                "lat": msg.get("lat"),
                "lon": msg.get("lon"),
                "name": msg.get("name", "Destination"),
            }
            return {"type": "overlay", "elements": [
                {"kind": "text", "text": f"Destination set: {self._destination['name']}",
                 "x": 10, "y": 30, "color": "#00FF00", "size": 20}
            ]}
        return {"type": "error", "message": f"Unknown message type: {msg_type}"}

    def _broadcast(self, payload: dict):
        """Send a JSON payload to every connected WebSocket client."""
        if not self._loop or not self._clients:
            return
        raw = json.dumps(payload)

        async def _send_all():
            stale = set()
            for ws in list(self._clients):
                try:
                    await ws.send(raw)
                except Exception:
                    stale.add(ws)
            self._clients -= stale

        self._loop.call_soon_threadsafe(
            lambda: asyncio.ensure_future(_send_all())
        )

    # ------------------------------------------------------------------
    # Frame processing
    # ------------------------------------------------------------------

    def _handle_frame(self, frame_b64: str, mode: str) -> dict:
        """Decode a base64 JPEG frame and process according to *mode*."""
        try:
            img_bytes = base64.b64decode(frame_b64)
        except Exception:
            return {"type": "error", "message": "Invalid base64 frame data"}

        # Write to a temporary file in the module's directory
        tmp_path = os.path.join(os.path.dirname(__file__), "_ar_tmp_frame.jpg")
        try:
            with open(tmp_path, "wb") as f:
                f.write(img_bytes)

            if mode == "translate":
                return self._frame_translate(tmp_path)
            elif mode == "detect":
                return self._frame_detect(tmp_path)
            elif mode == "navigate":
                return self._frame_navigate()
            elif mode == "label_faces":
                return self._frame_label_faces(tmp_path)
            else:
                return {"type": "error", "message": f"Unknown mode: {mode}"}
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    # -- translate mode --------------------------------------------------

    def _frame_translate(self, image_path: str, target_lang: str = "en") -> dict:
        text = self._ocr(image_path)
        if not text:
            return {"type": "overlay", "elements": []}
        translated = self._llm_translate(text, target_lang)
        return {
            "type": "overlay",
            "elements": [
                {"kind": "text", "text": translated,
                 "x": 10, "y": 30, "color": "#FFFFFF", "size": 24}
            ],
        }

    # -- detect mode -----------------------------------------------------

    def _frame_detect(self, image_path: str) -> dict:
        """Use vision module or LLM to detect / label objects in the frame."""
        elements = []
        if self.vision is not None:
            try:
                result = self.vision.process({
                    "action": "describe_image",
                    "image_path": image_path,
                })
                description = result.get("description", "") if isinstance(result, dict) else str(result)
            except Exception:
                description = self._llm_describe_image(image_path)
        else:
            description = self._llm_describe_image(image_path)

        if description:
            labels = [l.strip() for l in description.split(",") if l.strip()]
            y_offset = 30
            for label in labels[:10]:
                elements.append({
                    "kind": "box", "x": 10, "y": y_offset,
                    "w": 300, "h": 40, "color": "#00FF00", "label": label,
                })
                y_offset += 50

        return {"type": "overlay", "elements": elements}

    # -- navigate mode ---------------------------------------------------

    def _frame_navigate(self) -> dict:
        if self._destination is None:
            return {"type": "overlay", "elements": [
                {"kind": "text", "text": "No destination set",
                 "x": 10, "y": 30, "color": "#FF0000", "size": 20}
            ]}
        if self._current_gps is None:
            return {"type": "overlay", "elements": [
                {"kind": "text", "text": "Waiting for GPS...",
                 "x": 10, "y": 30, "color": "#FFFF00", "size": 20}
            ]}

        bearing = _calc_bearing(
            self._current_gps["lat"], self._current_gps["lon"],
            self._destination["lat"], self._destination["lon"],
        )
        distance = _calc_distance(
            self._current_gps["lat"], self._current_gps["lon"],
            self._destination["lat"], self._destination["lon"],
        )
        direction = _bearing_to_direction(bearing)
        return {
            "type": "overlay",
            "elements": [
                {"kind": "arrow", "from_x": 160, "from_y": 320,
                 "angle": bearing, "length": 100, "color": "#00FFFF"},
                {"kind": "text",
                 "text": f"{self._destination['name']} — {direction} — {_fmt_distance(distance)}",
                 "x": 60, "y": 440, "color": "#00FFFF", "size": 20},
                {"kind": "path",
                 "points": [[160, 320], [160 + int(80 * math.sin(math.radians(bearing))),
                                         320 - int(80 * math.cos(math.radians(bearing)))]],
                 "color": "#00FF00"},
            ],
        }

    # -- label_faces mode ------------------------------------------------

    def _frame_label_faces(self, image_path: str) -> dict:
        """Detect faces and label known ones via vision / memory modules."""
        elements = []

        if self.vision is not None:
            try:
                result = self.vision.process({
                    "action": "detect_faces",
                    "image_path": image_path,
                })
                faces = result.get("faces", []) if isinstance(result, dict) else []
            except Exception:
                faces = []
        else:
            faces = []

        for face in faces:
            name = face.get("name", "Unknown")
            x = face.get("x", 0)
            y = face.get("y", 0)
            w = face.get("w", 150)
            h = face.get("h", 150)
            color = "#00FF00" if name != "Unknown" else "#FFFF00"
            elements.append({
                "kind": "box", "x": x, "y": y, "w": w, "h": h,
                "color": color, "label": name,
            })

        if not elements:
            elements.append({
                "kind": "text", "text": "No faces detected",
                "x": 10, "y": 30, "color": "#AAAAAA", "size": 18,
            })

        return {"type": "overlay", "elements": elements}

    # ------------------------------------------------------------------
    # OCR helper
    # ------------------------------------------------------------------

    def _ocr(self, image_path: str) -> str:
        """Extract text from an image. Prefer vision module, fall back to easyocr."""
        # Try the wired vision module first
        if self.vision is not None:
            try:
                result = self.vision.process({
                    "action": "read_text",
                    "image_path": image_path,
                })
                text = result.get("text", "") if isinstance(result, dict) else str(result)
                if text.strip():
                    return text.strip()
            except Exception:
                pass

        # Fallback: easyocr
        if HAS_EASYOCR:
            try:
                if self._ocr_reader is None:
                    self._ocr_reader = easyocr.Reader(["en"], gpu=False)
                results = self._ocr_reader.readtext(image_path, detail=0)
                return " ".join(results).strip()
            except Exception:
                pass

        return ""

    # ------------------------------------------------------------------
    # LLM helpers (Ollama)
    # ------------------------------------------------------------------

    def _llm_translate(self, text: str, target_lang: str) -> str:
        prompt = (
            f"Translate the following text to {target_lang}. "
            "Return ONLY the translated text, no explanations.\n\n"
            f"{text}"
        )
        return self._ollama_chat(prompt)

    def _llm_describe_image(self, image_path: str) -> str:
        """Ask LLM to list objects visible in the image (via base64)."""
        try:
            with open(image_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
        except Exception:
            return ""
        prompt = (
            "List the main objects visible in this image as a short "
            "comma-separated list (e.g. 'person, car, tree'). "
            "Return ONLY the list, no extra text."
        )
        return self._ollama_chat(prompt, images=[b64])

    def _ollama_chat(self, prompt: str, images: list | None = None) -> str:
        if not HAS_REQUESTS:
            return ""
        message = {"role": "user", "content": prompt}
        if images:
            message["images"] = images
        payload = {
            "model": self.OLLAMA_MODEL,
            "messages": [message],
            "stream": False,
        }
        try:
            resp = requests.post(self.OLLAMA_URL, json=payload, timeout=60)
            resp.raise_for_status()
            data = resp.json()
            return data.get("message", {}).get("content", "").strip()
        except Exception:
            return ""

    # ------------------------------------------------------------------
    # Misc helpers
    # ------------------------------------------------------------------


def _fmt_distance(metres: float) -> str:
    if metres >= 1000:
        return f"{metres / 1000:.1f} km"
    return f"{metres:.0f} m"
