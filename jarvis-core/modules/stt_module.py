# modules/stt_module.py
import os
import tempfile
import time
import base64
from typing import Optional
from .base import ModuleBase

class STTModule(ModuleBase):
    def __init__(self, default_model: str = "small"):
        super().__init__("stt")
        self.model_name = default_model
        self.model = None  # lazy load
        # project root (one level up from modules/)
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.project_root = os.path.abspath(os.path.join(base_dir, ".."))
        # audio folder for convenience (jarvis-core/memory/audio)
        self.audio_dir = os.path.join(self.project_root, "memory", "audio")
        os.makedirs(self.audio_dir, exist_ok=True)

    def _load_model(self):
        if self.model is None:
            try:
                import whisper
            except Exception as e:
                raise RuntimeError("Whisper is not installed or failed to import: " + str(e))
            # load model (this will download the weights first time if necessary)
            self.model = whisper.load_model(self.model_name)

    def _resolve_path(self, file_path: str) -> Optional[str]:
        """
        Resolve file_path to an absolute path. Tries:
          1) If file_path is absolute and exists -> use it
          2) project_root / file_path
          3) audio_dir / file_path
        Returns the absolute path if found, else None.
        """
        # 1) absolute path
        if os.path.isabs(file_path):
            if os.path.exists(file_path):
                return file_path
            return None

        # 2) project root (jarvis-core/file_path)
        candidate = os.path.join(self.project_root, file_path)
        if os.path.exists(candidate):
            return candidate

        # 3) memory/audio/file_path
        candidate = os.path.join(self.audio_dir, file_path)
        if os.path.exists(candidate):
            return candidate

        return None

    def process(self, input_data):
        """
        input_data options:
          - file_path: (str) path or file name (we resolve relative paths automatically)
          - file_bytes: (str) base64-encoded audio bytes (optional alternative to file_path)
          - model: (str) optional model override per-request, e.g. "tiny", "small", "base", "medium", "large"
        """
        # allow model override per request
        requested_model = input_data.get("model", self.model_name)
        if requested_model != self.model_name:
            # force reload with new model
            self.model_name = requested_model
            self.model = None

        # handle base64 audio bytes (write to temp file)
        file_bytes_b64 = input_data.get("file_bytes")
        temp_file_path = None
        if file_bytes_b64:
            try:
                decoded = base64.b64decode(file_bytes_b64)
                suffix = ".wav"
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=self.audio_dir)
                tmp.write(decoded)
                tmp.flush()
                tmp.close()
                temp_file_path = tmp.name
                full_path = temp_file_path
            except Exception as e:
                return {"error": f"Failed to write provided file bytes: {e}"}
        else:
            file_path = input_data.get("file_path")
            if not file_path:
                return {"error": "Missing 'file_path' or 'file_bytes' in input."}

            # 🔥 FIX: actually resolve path
            full_path = self._resolve_path(file_path)
            if full_path is None:
                tried = [
                    file_path,
                    os.path.join(self.project_root, file_path),
                    os.path.join(self.audio_dir, file_path),
                ]
                return {"error": f"File not found. Tried paths: {tried}"}

        # load model lazily
        try:
            self._load_model()
        except Exception as e:
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.remove(temp_file_path)
                except:
                    pass
            return {"error": f"Failed to load Whisper model '{self.model_name}': {e}"}

        # do transcription
        try:
            start = time.time()
            print(f"[STT DEBUG] Trying to transcribe: {full_path}")

            result = self.model.transcribe(full_path)
            duration = time.time() - start
            text = result.get("text", "").strip()
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.remove(temp_file_path)
                except:
                    pass
            return {
                "status": "ok",
                "model": self.model_name,
                "text": text,
                "duration_seconds": round(duration, 2)
            }
        except Exception as e:
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.remove(temp_file_path)
                except:
                    pass
            return {"error": f"Transcription failed: {e}"}
