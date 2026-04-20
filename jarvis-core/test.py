from resemblyzer import VoiceEncoder, preprocess_wav
from pathlib import Path
import numpy as np
import os

# Path to your test audio file (record something first)
audio_path = Path("memory/audio/hello.wav")

if not audio_path.exists():
    print(f"❌ Audio file not found at {audio_path}. Please record one first.")
    exit()

print("🔍 Loading and processing audio...")
wav = preprocess_wav(audio_path)

print("🎙 Encoding voice...")
encoder = VoiceEncoder()
embedding = encoder.embed_utterance(wav)

print("✅ Resemblyzer working correctly!")
print(f"Embedding shape: {embedding.shape}")
print(f"First 10 values:\n{embedding[:10]}")

# Optionally save the embedding
np.save("memory/audio/voice_embedding.npy", embedding)
print("💾 Saved embedding to memory/audio/voice_embedding.npy")
