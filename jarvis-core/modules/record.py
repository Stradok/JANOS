# record.py
import sounddevice as sd
import soundfile as sf
import requests
import sys
import os

def record_and_send(filename="memory/audio/input.wav", duration=5, fs=16000):
    # make sure folder exists
    os.makedirs(os.path.dirname(filename), exist_ok=True)

    print("🎙 Recording... speak now")
    audio = sd.rec(int(duration * fs), samplerate=fs, channels=1, dtype="float32")
    sd.wait()
    sf.write(filename, audio, fs)
    print(f"✅ Saved to {filename}")

    # Send to STT
    url = "http://127.0.0.1:8000/process"
    payload = {
        "module": "stt",
        "input": {"file_path": filename, "model": "small"}
    }
    r = requests.post(url, json=payload)
    print("📝 STT Response:", r.json())

if __name__ == "__main__":
    duration = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    record_and_send(duration=duration)
