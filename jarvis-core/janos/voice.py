"""Voice loop: wake word → listen → transcribe → JANOS → speak. Local, English.

    python -m janos.voice              # say "Hey Jarvis", then your request
    python -m janos.voice --text       # type instead of speaking (no microphone)

Everything runs on this machine. The LLM keeps the GPU; speech runs on the CPU:

  wake word   openWakeWord "hey_jarvis"   ~5 MB  (a "Hey JANOS" model needs training data)
  end of turn Silero VAD (bundled with faster-whisper)
  speech→text faster-whisper small.en, int8
  text→speech Kokoro 82M int8, voice bm_george

The microphone is ignored while JANOS is speaking, so it cannot wake itself.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import time
from pathlib import Path

import numpy as np

from janos.config import Config
from janos import persona as personas

SR = 16000          # wake word, VAD and Whisper all expect 16 kHz mono
FRAME = 1280        # 80 ms, the chunk size openWakeWord is trained on


def to_16k(audio: np.ndarray, sr: int) -> np.ndarray:
    """Linear resample to 16 kHz float32. Adequate for speech; avoids a scipy dependency."""
    if sr == SR:
        return audio.astype(np.float32)
    idx = np.linspace(0, len(audio) - 1, int(len(audio) * SR / sr))
    return np.interp(idx, np.arange(len(audio)), audio).astype(np.float32)


class Endpointer:
    """Decides when the speaker has finished, from VAD over the audio so far.

    Fed 80 ms frames; returns True once speech has been followed by
    `silence_s` of silence, or the turn hits `max_s`, or nobody spoke
    within `no_speech_s`. Check `has_speech` to tell the last case apart.
    """

    def __init__(self, silence_s: float = 0.8, max_s: float = 15.0, no_speech_s: float = 6.0):
        from faster_whisper.vad import VadOptions, get_speech_timestamps
        self._vad, self._opts = get_speech_timestamps, VadOptions(min_silence_duration_ms=300)
        self.silence, self.max, self.no_speech = silence_s * SR, max_s * SR, no_speech_s * SR
        self.frames: list[np.ndarray] = []
        self.n = 0
        self._checked = 0
        self.has_speech = False

    def feed(self, frame: np.ndarray) -> bool:
        self.frames.append(frame)
        self.n += len(frame)
        if self.n >= self.max:
            return True
        if self.n - self._checked < 0.4 * SR:      # VAD every 400 ms is plenty
            return False
        self._checked = self.n
        segments = self._vad(self.audio(), self._opts)
        if not segments:
            return self.n >= self.no_speech
        self.has_speech = True
        return self.n - segments[-1]["end"] >= self.silence

    def audio(self) -> np.ndarray:
        pcm = np.concatenate(self.frames) if self.frames else np.zeros(0, np.int16)
        return pcm.astype(np.float32) / 32768.0


class Voice:
    """Loads the speech models once and runs conversation turns."""

    def __init__(self, config: Config | None = None):
        self.config = config or Config.load()
        self.models = self.config.memory_dir / "models"
        os.environ.setdefault("HF_HOME", str(self.models / "hf"))
        self._sup = None

        self.persona = personas.get(self.config.persona)
        from kokoro_onnx import Kokoro
        self.tts = Kokoro(str(self.models / "kokoro-v1.0.int8.onnx"),
                          str(self.models / "voices-v1.0.bin"))
        from faster_whisper import WhisperModel
        self.stt = WhisperModel("small.en", device="cpu", compute_type="int8",
                                download_root=str(self.models / "whisper"))

    # ------------------------------------------------------------- speech

    def synth(self, text: str) -> tuple[np.ndarray, int]:
        return self.tts.create(text, voice=self.persona.voice, speed=self.persona.speed, lang="en-gb")

    def transcribe(self, audio16: np.ndarray) -> str:
        segments, _ = self.stt.transcribe(audio16, language="en", beam_size=1,
                                          vad_filter=False, condition_on_previous_text=False)
        return " ".join(s.text.strip() for s in segments).strip()

    def speak(self, text: str) -> None:
        import sounddevice as sd
        # ponytail: whole reply synthesised before playback (~1 s per 3 s of speech);
        # stream sentence by sentence if latency on long answers matters.
        audio, sr = self.synth(text)
        sd.play(audio, sr)
        sd.wait()

    # -------------------------------------------------------------- brain

    @property
    def sup(self):
        if self._sup is None:
            from janos.supervisor import Supervisor
            self._sup = Supervisor(self.config)
        return self._sup

    async def respond(self, heard: str) -> str:
        """Run the request through JANOS, then phrase the result for speaking."""
        turn = await self.sup.handle(heard)
        # A short, plain answer is already speakable; rephrasing it costs a model call.
        if len(turn.answer) <= 280 and not re.search(r"[*#`|\n]|https?://", turn.answer):
            return _plain(turn.answer)
        try:
            spoken = await self.sup.llm.chat([
                {"role": "system", "content": self.persona.system},
                {"role": "user", "content":
                    f"The user said: {heard}\n\nYour full answer was:\n{turn.answer}\n\n"
                    "Say this aloud in at most three short sentences. No markdown, lists, "
                    "code or URLs. Keep every number, name and fact exactly as written."},
            ], temperature=0.4)
        except Exception:
            spoken = turn.answer
        return _plain(spoken) or _plain(turn.answer)

    # --------------------------------------------------------------- loop

    async def listen_forever(self) -> None:
        import openwakeword
        import sounddevice as sd

        path = next(p for p in openwakeword.get_pretrained_model_paths() if "hey_jarvis" in p)
        wake = openwakeword.Model(wakeword_model_paths=[path])
        ack = self.synth("Yes?")
        q: asyncio.Queue[np.ndarray] = asyncio.Queue()
        loop = asyncio.get_running_loop()
        muted = False

        def on_audio(indata, frames, t, status):      # PortAudio thread
            if not muted:
                loop.call_soon_threadsafe(q.put_nowait, indata[:, 0].copy())

        await self.warm_up()
        print(f"JANOS voice · say \"Hey Jarvis\" · Ctrl-C to stop", flush=True)
        with sd.InputStream(samplerate=SR, channels=1, dtype="int16", blocksize=FRAME,
                            callback=on_audio):
            while True:
                frame = await q.get()
                if max(wake.predict(frame).values()) < self.config.wake_threshold:
                    continue
                muted = True
                try:
                    sd.play(*ack); sd.wait()
                except Exception as e:                 # output device busy
                    print(f"  ! {type(e).__name__}: {e}", flush=True)
                finally:
                    _drain(q); wake.reset(); muted = False

                ep = Endpointer()
                while not ep.feed(await q.get()):
                    pass
                muted = True
                try:
                    if not ep.has_speech:
                        print("  (nothing heard)", flush=True)
                    else:
                        await self._turn(self.transcribe(ep.audio()))
                except Exception as e:                 # transcription failure
                    print(f"  ! {type(e).__name__}: {e}", flush=True)
                finally:
                    _drain(q); wake.reset(); muted = False

    async def warm_up(self) -> None:
        """Load the LLM into VRAM now, so the first request is not also a cold start."""
        try:
            await self.sup.llm.chat([{"role": "user", "content": "ok"}], max_tokens=1)
        except Exception as e:
            print(f"  ! model warm-up failed: {e}", flush=True)

    async def _turn(self, heard: str) -> None:
        """One request. Never raises: a failed turn must not end the session."""
        if not heard:
            return
        print(f"  you:   {heard}", flush=True)
        t = time.perf_counter()
        try:
            reply = await self.respond(heard)
        except Exception as e:
            print(f"  ! request failed: {type(e).__name__}: {e}", flush=True)
            reply = "Sorry, something went wrong with that request."
        print(f"  janos: {reply}  ({time.perf_counter() - t:.1f}s)", flush=True)
        try:
            await asyncio.to_thread(self.speak, reply)
        except Exception as e:
            print(f"  ! could not play audio: {type(e).__name__}: {e}", flush=True)

    async def type_forever(self) -> None:
        await self.warm_up()
        print("JANOS voice (typed input) · empty line to stop", flush=True)
        while (heard := (await asyncio.to_thread(input, "> ")).strip()):
            await self._turn(heard)


def _drain(q: asyncio.Queue) -> None:
    while not q.empty():
        q.get_nowait()


def _plain(text: str) -> str:
    """Strip markdown and URLs that a TTS voice would read out literally."""
    text = re.sub(r"https?://\S+", "", text or "")
    text = re.sub(r"[`*_#>|]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def main() -> int:
    ap = argparse.ArgumentParser(prog="janos.voice", description="Talk to JANOS")
    ap.add_argument("--text", action="store_true", help="type requests instead of speaking")
    args = ap.parse_args()
    v = Voice()
    try:
        asyncio.run(v.type_forever() if args.text else v.listen_forever())
    except KeyboardInterrupt:
        pass
    finally:
        if v._sup is not None:
            v._sup.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
