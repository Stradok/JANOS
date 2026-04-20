from resemblyzer import VoiceEncoder, preprocess_wav
from pathlib import Path

# Path to your recorded audio file
wav_fpath = Path("memory/audio/input.wav")

print("🔍 Loading and preprocessing audio...")
wav = preprocess_wav(wav_fpath)

print("🎙 Creating voice embedding...")
encoder = VoiceEncoder()
embed = encoder.embed_utterance(wav)

print("✅ Voice embedding created successfully!")
print("Embedding shape:", embed.shape)
