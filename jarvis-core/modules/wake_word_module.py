# modules/wake_word_module.py
import os
import time
import logging
import threading
from .base import ModuleBase

try:
    import pyaudio
    PYAUDIO_AVAILABLE = True
except ImportError:
    PYAUDIO_AVAILABLE = False

try:
    from openwakeword.model import Model as OWWModel
    import openwakeword
    OWW_AVAILABLE = True
except ImportError:
    OWW_AVAILABLE = False

try:
    import numpy as np
    NP_AVAILABLE = True
except ImportError:
    NP_AVAILABLE = False

# ---------------------------------------------------------------------------
# Logging setup – file handler writes to memory/logs/wakeword.log
# ---------------------------------------------------------------------------
_base_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.abspath(os.path.join(_base_dir, ".."))
_log_dir = os.path.join(_project_root, "memory", "logs")
os.makedirs(_log_dir, exist_ok=True)

_logger = logging.getLogger("WakeWordModule")
_logger.setLevel(logging.DEBUG)
if not _logger.handlers:
    _fh = logging.FileHandler(os.path.join(_log_dir, "wakeword.log"), encoding="utf-8")
    _fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    _logger.addHandler(_fh)


class WakeWordModule(ModuleBase):
    """Always-listening voice activation module for JAN.

    Runs a daemon background thread that monitors the microphone for a wake
    word (via openwakeword) and, once triggered, records user speech until
    silence, transcribes it with Whisper STT, routes the text through the
    orchestrator, and speaks the response via smart_tts.
    """

    def __init__(self):
        super().__init__("wake_word")

        # External dependencies – wired after construction
        self.orchestrator = None
        self.stt = None
        self.smart_tts = None
        self.daemon = None

        # Internal state
        self._thread: threading.Thread | None = None
        self._running: bool = False
        self._wake_word: str = "hey_jarvis"
        self._sample_rate: int = 16000
        self._chunk_size: int = 1280          # ~80 ms at 16 kHz
        self._silence_threshold: int = 500
        self._silence_duration: float = 1.5   # seconds of silence to stop
        self._max_record_duration: int = 30   # max seconds per recording
        self._listening: bool = False          # True while recording after wake

    # ------------------------------------------------------------------
    # process() – public API
    # ------------------------------------------------------------------
    def process(self, input_data):
        action = (input_data or {}).get("action", "")

        if action == "start":
            return self._start()
        elif action == "stop":
            return self._stop()
        elif action == "status":
            return self._status()
        elif action == "set_wake_word":
            return self._set_wake_word(input_data)
        elif action == "set_sensitivity":
            return self._set_sensitivity(input_data)
        elif action == "set_silence_duration":
            return self._set_silence_duration(input_data)
        elif action == "test_mic":
            return self._test_mic()
        else:
            return {"status": "error", "error": f"Unknown action: {action}"}

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _start(self):
        if self._running:
            return {"status": "ok", "message": "Already running"}
        if not PYAUDIO_AVAILABLE:
            return {"status": "error", "error": "pyaudio is not installed"}
        self._running = True
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()
        _logger.info("[WakeWord] Background listener started")
        return {"status": "ok", "message": "Wake word listener started"}

    def _stop(self):
        if not self._running:
            return {"status": "ok", "message": "Not running"}
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        _logger.info("[WakeWord] Listener stopped")
        return {"status": "ok", "message": "Wake word listener stopped"}

    def _status(self):
        return {
            "status": "ok",
            "running": self._running,
            "listening": self._listening,
            "wake_word": self._wake_word,
            "sample_rate": self._sample_rate,
            "silence_threshold": self._silence_threshold,
            "silence_duration": self._silence_duration,
            "oww_available": OWW_AVAILABLE,
            "pyaudio_available": PYAUDIO_AVAILABLE,
        }

    def _set_wake_word(self, input_data):
        ww = input_data.get("wake_word", "").strip()
        if not ww:
            return {"status": "error", "error": "wake_word is required"}
        self._wake_word = ww
        _logger.info(f"[WakeWord] Wake word changed to: {ww}")
        return {"status": "ok", "wake_word": ww}

    def _set_sensitivity(self, input_data):
        try:
            threshold = int(input_data.get("threshold", self._silence_threshold))
        except (TypeError, ValueError):
            return {"status": "error", "error": "threshold must be an integer"}
        self._silence_threshold = threshold
        _logger.info(f"[WakeWord] Silence threshold set to {threshold}")
        return {"status": "ok", "silence_threshold": threshold}

    def _set_silence_duration(self, input_data):
        try:
            seconds = float(input_data.get("seconds", self._silence_duration))
        except (TypeError, ValueError):
            return {"status": "error", "error": "seconds must be a number"}
        self._silence_duration = seconds
        _logger.info(f"[WakeWord] Silence duration set to {seconds}s")
        return {"status": "ok", "silence_duration": seconds}

    def _test_mic(self):
        """Record ~3 seconds from the mic and return energy statistics."""
        if not PYAUDIO_AVAILABLE:
            return {"status": "error", "error": "pyaudio is not installed"}
        if not NP_AVAILABLE:
            return {"status": "error", "error": "numpy is not installed"}

        pa = pyaudio.PyAudio()
        try:
            stream = pa.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=self._sample_rate,
                input=True,
                frames_per_buffer=self._chunk_size,
            )
            num_chunks = int(3 * self._sample_rate / self._chunk_size)
            energies = []
            for _ in range(num_chunks):
                data = stream.read(self._chunk_size, exception_on_overflow=False)
                audio_np = np.frombuffer(data, dtype=np.int16)
                energies.append(float(np.abs(audio_np).mean()))
            stream.stop_stream()
            stream.close()
        finally:
            pa.terminate()

        return {
            "status": "ok",
            "samples": num_chunks,
            "duration_seconds": 3,
            "energy_min": round(min(energies), 2),
            "energy_max": round(max(energies), 2),
            "energy_mean": round(sum(energies) / len(energies), 2),
            "current_threshold": self._silence_threshold,
        }

    # ------------------------------------------------------------------
    # Background listener
    # ------------------------------------------------------------------
    def _listen_loop(self):
        if not PYAUDIO_AVAILABLE:
            _logger.error("[WakeWord] pyaudio not installed")
            return

        pa = pyaudio.PyAudio()
        stream = pa.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=self._sample_rate,
            input=True,
            frames_per_buffer=self._chunk_size,
        )

        # Load wake word model
        oww_model = None
        if OWW_AVAILABLE:
            try:
                oww_model = OWWModel(wakeword_models=[self._wake_word])
                _logger.info(f"[WakeWord] Loaded openwakeword model: {self._wake_word}")
            except Exception as e:
                _logger.warning(f"[WakeWord] openwakeword failed: {e}, using energy detection")

        _logger.info("[WakeWord] Listening for wake word...")

        while self._running:
            try:
                audio_chunk = stream.read(self._chunk_size, exception_on_overflow=False)

                wake_detected = False

                if oww_model:
                    # openwakeword detection
                    audio_np = np.frombuffer(audio_chunk, dtype=np.int16)
                    prediction = oww_model.predict(audio_np)
                    for key, score in prediction.items():
                        if score > 0.5:
                            wake_detected = True
                            _logger.info(f"[WakeWord] Wake word detected! ({key}: {score:.2f})")
                            break
                else:
                    # Fallback: simple energy-based voice activity detection
                    if NP_AVAILABLE:
                        audio_np = np.frombuffer(audio_chunk, dtype=np.int16)
                        energy = float(np.abs(audio_np).mean())
                        if energy > self._silence_threshold * 3:
                            wake_detected = True

                if wake_detected:
                    self._handle_wake(stream)
                    if oww_model:
                        oww_model.reset()

            except Exception as e:
                _logger.error(f"[WakeWord] Listen error: {e}")
                time.sleep(0.5)

        stream.stop_stream()
        stream.close()
        pa.terminate()
        _logger.info("[WakeWord] Listen loop exited")

    # ------------------------------------------------------------------
    # Wake word handling – record, transcribe, respond
    # ------------------------------------------------------------------
    def _handle_wake(self, stream):
        """Record audio after wake word until silence, then process."""
        self._listening = True
        _logger.info("[WakeWord] Recording user speech...")

        frames = []
        silent_chunks = 0
        max_chunks = int(self._max_record_duration * self._sample_rate / self._chunk_size)
        silence_chunks_needed = int(self._silence_duration * self._sample_rate / self._chunk_size)

        _logger.info("[WakeWord] \U0001f3a4 Listening...")

        for _ in range(max_chunks):
            if not self._running:
                break

            audio_chunk = stream.read(self._chunk_size, exception_on_overflow=False)
            frames.append(audio_chunk)

            if NP_AVAILABLE:
                audio_np = np.frombuffer(audio_chunk, dtype=np.int16)
                energy = float(np.abs(audio_np).mean())
                if energy < self._silence_threshold:
                    silent_chunks += 1
                else:
                    silent_chunks = 0

                if silent_chunks >= silence_chunks_needed:
                    break

        self._listening = False

        if not frames:
            return

        # Save audio to a WAV file
        import wave

        audio_dir = os.path.join(_project_root, "memory", "audio")
        os.makedirs(audio_dir, exist_ok=True)
        temp_path = os.path.join(audio_dir, "wake_recording.wav")

        wf = wave.open(temp_path, "wb")
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(self._sample_rate)
        wf.writeframes(b"".join(frames))
        wf.close()

        # Transcribe via STT
        transcript = ""
        if self.stt:
            try:
                result = self.stt.process({"file_path": temp_path})
                transcript = result.get("text", "").strip()
                _logger.info(f"[WakeWord] Transcribed: {transcript}")
            except Exception as e:
                _logger.error(f"[WakeWord] STT failed: {e}")
                return
        else:
            _logger.warning("[WakeWord] No STT module wired – cannot transcribe")
            return

        if not transcript:
            _logger.info("[WakeWord] No speech detected")
            return

        # Mark user activity on the daemon
        if self.daemon:
            try:
                self.daemon.process({"action": "mark_activity"})
            except Exception:
                pass

        # Send to orchestrator
        if self.orchestrator:
            try:
                result = self.orchestrator.process({"message": transcript})
                response = result.get("response", "")
                _logger.info(f"[WakeWord] JAN responded: {response[:100]}")
            except Exception as e:
                _logger.error(f"[WakeWord] Orchestrator error: {e}")
        else:
            _logger.warning("[WakeWord] No orchestrator wired – cannot process command")
