# modules/speaker_module.py
import os, numpy as np
try:
    from resemblyzer import VoiceEncoder, preprocess_wav
    RESEMBLYZER_AVAILABLE = True
except ImportError:
    RESEMBLYZER_AVAILABLE = False
from pathlib import Path
from .base import ModuleBase
try:
    import soundfile as sf
except ImportError:
    sf = None

class SpeakerModule(ModuleBase):
    def __init__(self):
        super().__init__("speaker")
        if RESEMBLYZER_AVAILABLE:
            self.encoder = VoiceEncoder()
        else:
            self.encoder = None
        self.voiceprints_dir = Path("memory/voices")
        self.voiceprints_dir.mkdir(parents=True, exist_ok=True)

    def _enroll(self, name, file_path):
        if not RESEMBLYZER_AVAILABLE:
            return {"error": "Resemblyzer not installed. Run: pip install resemblyzer"}
        wav = preprocess_wav(Path(file_path))
        embed = self.encoder.embed_utterance(wav)
        np.save(self.voiceprints_dir / f"{name}.npy", embed)
        return {"status": "ok", "message": f"Enrolled {name}"}

    def _verify(self, name, file_path, threshold=0.75):
        if not RESEMBLYZER_AVAILABLE:
            return {"error": "Resemblyzer not installed. Run: pip install resemblyzer"}
        wav = preprocess_wav(Path(file_path))
        embed = self.encoder.embed_utterance(wav)

        ref_file = self.voiceprints_dir / f"{name}.npy"
        if not ref_file.exists():
            return {"error": f"No enrollment found for {name}"}

        ref_embed = np.load(ref_file)
        sim = np.dot(embed, ref_embed) / (np.linalg.norm(embed) * np.linalg.norm(ref_embed))
        if sim > threshold:
            return {"status": "ok", "verified": True, "similarity": float(sim)}
        else:
            return {"status": "ok", "verified": False, "similarity": float(sim)}

    def process(self, input_data):
        action = input_data.get("action")
        name = input_data.get("name")
        file_path = input_data.get("file_path")

        if not action or not name or not file_path:
            return {"error": "Need action, name, and file_path"}

        if action == "enroll":
            return self._enroll(name, file_path)
        elif action == "verify":
            return self._verify(name, file_path)
        else:
            return {"error": "Unknown action"}
