# modules/tts_module.py
from .base import ModuleBase

class TTSModule(ModuleBase):
    def __init__(self):
        super().__init__("tts")
        self.engine = None
        try:
            import pyttsx3
            self.engine = pyttsx3.init()
        except Exception:
            pass  # pyttsx3 unavailable — use smart_tts instead

    def process(self, input_data):
        text = input_data.get("text", "")
        if not text:
            return {"error": "No text provided"}
        if not self.engine:
            return {"error": "pyttsx3 not available. Use smart_tts module instead."}

        try:
            self.engine.say(text)
            self.engine.runAndWait()
            return {"status": "ok", "spoken": text}
        except Exception as e:
            return {"error": str(e)}
