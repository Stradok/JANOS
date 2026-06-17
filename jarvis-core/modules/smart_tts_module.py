# modules/smart_tts_module.py
"""
Smooth, natural text-to-speech using Microsoft Edge TTS.
Supports Urdu and English with auto-detection.
Sounds like the ChatGPT voice assistant — not robotic.
"""
import os
import asyncio
import re
from pathlib import Path
from .base import ModuleBase

try:
    import edge_tts
    EDGE_TTS_AVAILABLE = True
except ImportError:
    EDGE_TTS_AVAILABLE = False


class SmartTTSModule(ModuleBase):
    """Natural, smooth text-to-speech with auto language detection (Urdu + English)."""

    # Natural-sounding voices
    VOICES = {
        "en_male": "en-US-GuyNeural",
        "en_female": "en-US-JennyNeural",
        "ur_male": "ur-PK-AsadNeural",
        "ur_female": "ur-PK-UzmaNeural",
    }

    def __init__(self):
        super().__init__("smart_tts")
        self.output_dir = Path("memory/audio/tts")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.default_voice_gender = "male"  # Jarvis = male voice

    def _detect_language(self, text):
        """Detect if text is primarily Urdu or English."""
        # Urdu script characters range
        urdu_pattern = re.compile(r'[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]')
        urdu_chars = len(urdu_pattern.findall(text))

        # Roman Urdu detection — common words
        roman_urdu_words = [
            'kya', 'hai', 'mein', 'aap', 'yeh', 'woh', 'kaise', 'kaisa',
            'haan', 'nahi', 'nhi', 'bhai', 'yaar', 'acha', 'theek',
            'kahan', 'kab', 'kyun', 'bohot', 'bahut', 'bilkul',
            'shukriya', 'mashallah', 'inshallah', 'assalamualaikum',
            'walaikum', 'ji', 'abhi', 'mujhe', 'tumhe', 'humein',
            'kar', 'karo', 'bata', 'batao', 'chal', 'chalo', 'ruk',
            'sun', 'suno', 'dekh', 'dekho', 'samajh', 'pata',
        ]
        words = text.lower().split()
        roman_urdu_count = sum(1 for w in words if w.strip('.,!?') in roman_urdu_words)

        if urdu_chars > 3:
            return "ur"
        if len(words) > 0 and roman_urdu_count / len(words) > 0.25:
            return "ur"
        return "en"

    async def _speak_async(self, text, voice, output_path):
        """Generate speech audio file using edge-tts."""
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(output_path)

    def _speak(self, text, voice=None, output_path=None):
        """Speak text with auto language detection."""
        if not EDGE_TTS_AVAILABLE:
            return {"error": "edge-tts not installed. Run: pip install edge-tts"}

        # auto-detect language
        lang = self._detect_language(text)

        # pick voice
        if voice:
            selected_voice = voice
        elif lang == "ur":
            selected_voice = self.VOICES[f"ur_{self.default_voice_gender}"]
        else:
            selected_voice = self.VOICES[f"en_{self.default_voice_gender}"]

        # output path
        if not output_path:
            output_path = str(self.output_dir / "jarvis_speech.mp3")

        try:
            # run async edge-tts
            loop = None
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                pass

            if loop and loop.is_running():
                # we're inside an async context (like FastAPI)
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(
                        asyncio.run,
                        self._speak_async(text, selected_voice, output_path)
                    )
                    future.result(timeout=30)
            else:
                asyncio.run(self._speak_async(text, selected_voice, output_path))

            # play the audio
            self._play_audio(output_path)

            return {
                "status": "ok",
                "spoken": text,
                "language": lang,
                "voice": selected_voice,
                "audio_file": output_path
            }
        except Exception as e:
            return {"error": f"TTS failed: {str(e)}"}

    def _play_audio(self, path):
        """Play audio file using system player."""
        import subprocess
        import shutil
        try:
            # try pygame first (low latency)
            try:
                import pygame
                if not pygame.mixer.get_init():
                    pygame.mixer.init()
                pygame.mixer.music.load(path)
                pygame.mixer.music.play()
                while pygame.mixer.music.get_busy():
                    pygame.time.wait(100)
                return
            except ImportError:
                pass

            for player in ["ffplay", "paplay", "aplay", "mpg123", "play"]:
                exe = shutil.which(player)
                if exe:
                    cmd = []
                    if player == "ffplay":
                        cmd = [exe, "-nodisp", "-autoexit", "-loglevel", "quiet", path]
                    elif player == "paplay":
                        cmd = [exe, path]
                    elif player == "aplay":
                        cmd = [exe, path]
                    elif player == "mpg123":
                        cmd = [exe, path]
                    elif player == "play":
                        cmd = [exe, path]
                    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
                    return

            # last resort: xdg-open
            subprocess.run(["xdg-open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        except Exception:
            pass

    def process(self, input_data):
        action = input_data.get("action", "speak")
        text = input_data.get("text", "")
        voice = input_data.get("voice")
        output_path = input_data.get("output_path")

        if action == "speak":
            if not text:
                return {"error": "Missing 'text' to speak"}
            return self._speak(text, voice, output_path)

        elif action == "list_voices":
            return {"status": "ok", "voices": self.VOICES}

        elif action == "set_gender":
            gender = input_data.get("gender", "male")
            if gender in ("male", "female"):
                self.default_voice_gender = gender
                return {"status": "ok", "message": f"Voice set to {gender}"}
            return {"error": "Gender must be 'male' or 'female'"}

        else:
            return {"error": f"Unknown action: {action}. Use: speak, list_voices, set_gender"}
