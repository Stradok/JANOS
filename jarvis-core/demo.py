"""
JAN Demo — Terminal Chat + Voice
Run: python demo.py
Talks to JAN directly in your terminal. No server, no install needed.
Just Ollama running + basic pip packages.

Press Enter on empty line = voice input (speak to JAN)
Type text = text input
"""

import sys
import os
import signal
import time
import json
import wave
import struct
import tempfile
import threading
import yaml

# ── Ensure we're in the right directory ──
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# ── Quick dependency check ──
MISSING = []
for pkg in ["requests", "yaml"]:
    try:
        __import__(pkg)
    except ImportError:
        MISSING.append(pkg.replace("yaml", "pyyaml"))
if MISSING:
    print(f"[!] Missing packages: {', '.join(MISSING)}")
    print(f"    Run: pip install {' '.join(MISSING)}")
    sys.exit(1)

import requests

# Optional audio
try:
    import sounddevice as sd
    import numpy as np
    AUDIO_OK = True
except ImportError:
    AUDIO_OK = False


# ══════════════════════════════════════════
# Banner
# ══════════════════════════════════════════
BANNER = r"""
     ██╗ █████╗ ███╗   ██╗
     ██║██╔══██╗████╗  ██║
     ██║███████║██╔██╗ ██║
██   ██║██╔══██║██║╚██╗██║
╚█████╔╝██║  ██║██║ ╚████║
 ╚════╝ ╚═╝  ╚═╝╚═╝  ╚═══╝
  Joint Autonomous Neural Agent
"""

HELP_TEXT = """
  Commands:
    [Enter]        — press Enter on empty line to speak (voice input)
    /voice on|off  — toggle auto-voice (JAN speaks responses)
    /devices       — re-select audio input/output devices
    /modules       — list loaded modules
    /clear         — clear conversation history
    /status        — system status
    /help          — show this help
    /exit or /quit — exit demo
    Ctrl+C         — exit demo

  Just type anything else to chat with JAN!
"""

DEVICE_CONFIG_PATH = "config_devices.json"


# ══════════════════════════════════════════
# Audio device management
# ══════════════════════════════════════════

def list_input_devices():
    """Return list of (index, name) for input devices."""
    devs = sd.query_devices()
    result = []
    seen = set()
    for i, d in enumerate(devs):
        if d["max_input_channels"] > 0:
            name = d["name"]
            # skip duplicates with same name
            if name not in seen:
                seen.add(name)
                result.append((i, name))
    return result


def list_output_devices():
    """Return list of (index, name) for output devices."""
    devs = sd.query_devices()
    result = []
    seen = set()
    for i, d in enumerate(devs):
        if d["max_output_channels"] > 0:
            name = d["name"]
            if name not in seen:
                seen.add(name)
                result.append((i, name))
    return result


def pick_device(device_list, kind="input"):
    """Interactive device picker. Returns device index."""
    print_colored(f"\n  Select {kind} device:", "yellow")
    for idx, (dev_id, name) in enumerate(device_list):
        marker = " ← default" if dev_id == sd.default.device[0 if kind == "input" else 1] else ""
        print_colored(f"    {idx + 1}. [{dev_id}] {name}{marker}", "white")

    while True:
        try:
            choice = input(f"\n  Pick {kind} (1-{len(device_list)}, Enter=default): ").strip()
            if not choice:
                # use default
                default_id = sd.default.device[0 if kind == "input" else 1]
                for dev_id, name in device_list:
                    if dev_id == default_id:
                        print_colored(f"  ✓ Using default: {name}", "green")
                        return dev_id
                # fallback to first
                print_colored(f"  ✓ Using: {device_list[0][1]}", "green")
                return device_list[0][0]
            num = int(choice)
            if 1 <= num <= len(device_list):
                dev_id, name = device_list[num - 1]
                print_colored(f"  ✓ Selected: {name}", "green")
                return dev_id
        except (ValueError, IndexError):
            pass
        print_colored("  Invalid choice, try again.", "red")


def save_device_config(input_id, output_id):
    """Save selected devices to file."""
    data = {"input_device": input_id, "output_device": output_id}
    with open(DEVICE_CONFIG_PATH, "w") as f:
        json.dump(data, f)


def load_device_config():
    """Load saved device config. Returns (input_id, output_id) or None."""
    if not os.path.exists(DEVICE_CONFIG_PATH):
        return None
    try:
        with open(DEVICE_CONFIG_PATH, "r") as f:
            data = json.load(f)
        inp = data.get("input_device")
        out = data.get("output_device")
        # verify devices still exist
        devs = sd.query_devices()
        if inp is not None and inp < len(devs) and devs[inp]["max_input_channels"] > 0:
            if out is not None and out < len(devs) and devs[out]["max_output_channels"] > 0:
                return inp, out
    except Exception:
        pass
    return None


def setup_audio():
    """Interactive audio device setup. Returns (input_id, output_id)."""
    # Check for saved config
    saved = load_device_config()
    if saved:
        inp_id, out_id = saved
        devs = sd.query_devices()
        inp_name = devs[inp_id]["name"]
        out_name = devs[out_id]["name"]
        print_colored(f"  🎤 Input:  {inp_name}", "dim")
        print_colored(f"  🔊 Output: {out_name}", "dim")
        print_colored("  (use /devices to change)", "dim")
        return inp_id, out_id

    # First time — pick devices
    print_colored("\n  ╔═══════════════════════════════════╗", "yellow")
    print_colored("  ║   Audio Device Setup (first run)  ║", "yellow")
    print_colored("  ╚═══════════════════════════════════╝", "yellow")

    inputs = list_input_devices()
    outputs = list_output_devices()

    if not inputs:
        print_colored("  ⚠ No input devices found!", "red")
        return None, None
    if not outputs:
        print_colored("  ⚠ No output devices found!", "red")
        return None, None

    inp_id = pick_device(inputs, "input")
    out_id = pick_device(outputs, "output")

    save_device_config(inp_id, out_id)
    print_colored("\n  ✓ Audio config saved. Use /devices to change later.\n", "green")
    return inp_id, out_id


# ══════════════════════════════════════════
# Voice recording
# ══════════════════════════════════════════

def record_voice(input_device, samplerate=16000, silence_thresh=0.01, silence_duration=1.5, max_duration=15):
    """
    Record from mic until silence detected.
    Returns path to WAV file, or None if no speech detected.
    """
    print_colored("  🎤 Listening... (speak now, silence to stop)", "magenta")

    chunks = []
    silent_frames = 0
    has_speech = False
    frames_per_check = int(samplerate * 0.1)  # 100ms chunks
    max_frames = int(max_duration * samplerate)
    silence_frames_needed = int(silence_duration / 0.1)
    total_frames = 0
    recording = True

    def callback(indata, frames, time_info, status):
        nonlocal silent_frames, has_speech, total_frames, recording
        if not recording:
            return
        chunk = indata[:, 0].copy()
        chunks.append(chunk)
        total_frames += len(chunk)

        # Check energy
        energy = float(np.sqrt(np.mean(chunk ** 2)))
        if energy > silence_thresh:
            has_speech = True
            silent_frames = 0
        else:
            silent_frames += 1

        # Stop conditions
        if has_speech and silent_frames > silence_frames_needed:
            recording = False
        if total_frames > max_frames:
            recording = False

    try:
        stream = sd.InputStream(
            device=input_device,
            channels=1,
            samplerate=samplerate,
            blocksize=frames_per_check,
            callback=callback
        )
        stream.start()

        # Wait for recording to finish
        while recording:
            time.sleep(0.05)

        stream.stop()
        stream.close()
    except Exception as e:
        print_colored(f"  ✗ Recording error: {e}", "red")
        return None

    if not has_speech or not chunks:
        print_colored("  (no speech detected)", "dim")
        return None

    # Save as WAV
    audio = np.concatenate(chunks)
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav", dir="memory/audio")
    tmp.close()

    with wave.open(tmp.name, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(samplerate)
        # convert float32 -> int16
        audio_int16 = np.clip(audio * 32767, -32768, 32767).astype(np.int16)
        wf.writeframes(audio_int16.tobytes())

    duration = len(audio) / samplerate
    print_colored(f"  ✓ Recorded {duration:.1f}s", "green")
    return tmp.name


# ══════════════════════════════════════════
# Utilities
# ══════════════════════════════════════════

def check_ollama():
    """Check if Ollama is running."""
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=3)
        models = [m["name"] for m in r.json().get("models", [])]
        return True, models
    except Exception:
        return False, []


def print_colored(text, color="cyan"):
    """Print with ANSI colors."""
    colors = {
        "red": "\033[91m",
        "green": "\033[92m",
        "yellow": "\033[93m",
        "blue": "\033[94m",
        "magenta": "\033[95m",
        "cyan": "\033[96m",
        "white": "\033[97m",
        "dim": "\033[90m",
        "reset": "\033[0m",
        "bold": "\033[1m",
    }
    c = colors.get(color, "")
    reset = colors["reset"]
    print(f"{c}{text}{reset}")


def send_to_jan(orchestrator, message, mod):
    """Send a message to JAN and display the response."""
    print_colored("  JAN is thinking...", "dim")

    start = time.time()
    try:
        result = orchestrator.process({"message": message})
    except Exception as e:
        print_colored(f"\n  ✗ Error: {e}", "red")
        return

    elapsed = time.time() - start
    response = result.get("response", "...")
    thought = result.get("thought", "")
    action = result.get("action")
    action_result = result.get("action_result")
    voice_status = result.get("voice")

    # Clear "thinking" line
    sys.stdout.write("\033[A\033[K")

    # Show thought (dimmed)
    if thought and thought.lower() not in ("casual", "this is casual conversation", "casual conversation", "casual greeting"):
        print_colored(f"  💭 {thought}", "dim")

    # Show module action
    if action:
        if isinstance(action, list):
            mods_used = [a.get("module", "?") for a in action if isinstance(a, dict)]
            if mods_used:
                print_colored(f"  ⚡ Used: {', '.join(mods_used)}", "magenta")
        elif isinstance(action, dict) and action.get("module"):
            print_colored(f"  ⚡ Used: {action['module']}", "magenta")

    # Main response
    print_colored(f"\n  JAN: {response}", "cyan")

    # Footer
    footer_parts = [f"{elapsed:.1f}s"]
    if voice_status:
        footer_parts.append(f"🔊 {voice_status}")
    print_colored(f"  {'  '.join(footer_parts)}", "dim")


# ══════════════════════════════════════════
# Main
# ══════════════════════════════════════════

def main():
    print_colored(BANNER, "cyan")

    # ── Check Ollama ──
    print_colored("  Checking Ollama...", "dim")
    ollama_ok, models = check_ollama()
    if not ollama_ok:
        print_colored("  ✗ Ollama is not running!", "red")
        print_colored("    Start it with: ollama serve", "yellow")
        print_colored("    Then run this demo again.", "yellow")
        sys.exit(1)
    print_colored(f"  ✓ Ollama running — {len(models)} model(s) available", "green")

    # ── Load config ──
    config = {}
    if os.path.exists("config.yaml"):
        with open("config.yaml", "r") as f:
            config = yaml.safe_load(f) or {}

    # ── Load modules ──
    print_colored("  Loading modules...", "dim")
    try:
        import modules as mod
        orchestrator = mod.ORCHESTRATOR
        auto_voice = config.get("settings", {}).get("auto_voice", True)
        orchestrator.auto_voice = auto_voice
        orchestrator.default_city = config.get("settings", {}).get("default_city", "Islamabad")
        module_count = len(mod.MODULES)
        print_colored(f"  ✓ {module_count} modules loaded", "green")
    except Exception as e:
        print_colored(f"  ✗ Failed to load modules: {e}", "red")
        sys.exit(1)

    # ── Audio setup ──
    input_device = None
    output_device = None
    if AUDIO_OK:
        print_colored("  Setting up audio...", "dim")
        input_device, output_device = setup_audio()
        if input_device is not None:
            sd.default.device = (input_device, output_device)
    else:
        print_colored("  ⚠ Audio not available (install: pip install sounddevice numpy)", "yellow")
        print_colored("    Voice input disabled. Text-only mode.", "yellow")

    # ── Ready ──
    voice_label = "ON" if orchestrator.auto_voice else "OFF"
    mic_label = "ON" if (AUDIO_OK and input_device is not None) else "OFF"
    print_colored(f"\n  Voice output: {voice_label}  |  Mic input: {mic_label}  |  Model: {orchestrator.DEFAULT_MODEL}", "dim")
    if AUDIO_OK and input_device is not None:
        print_colored("  💡 Press Enter on empty line = voice input", "yellow")
    print_colored("  Type /help for commands.\n", "dim")
    print_colored("─" * 55, "dim")

    # ── Chat loop ──
    def handle_exit(*_):
        print_colored("\n\n  JAN: Goodbye Sir! 👋\n", "cyan")
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_exit)

    while True:
        try:
            user_input = input("\n  You: ").strip()
        except (EOFError, KeyboardInterrupt):
            handle_exit()
            break

        # ── Empty Enter = voice input ──
        if not user_input:
            if AUDIO_OK and input_device is not None:
                wav_path = record_voice(input_device)
                if wav_path is None:
                    continue
                # Transcribe via STT module
                print_colored("  Transcribing...", "dim")
                try:
                    stt_result = mod.MODULES["stt"].process({"file_path": wav_path})
                    text = stt_result.get("text", "").strip()
                    if not text:
                        print_colored("  (couldn't understand audio)", "dim")
                        continue
                    # Clear transcribing line
                    sys.stdout.write("\033[A\033[K")
                    print_colored(f"  🗣️ You said: {text}", "white")
                    user_input = text
                except Exception as e:
                    print_colored(f"  ✗ STT error: {e}", "red")
                    continue
                finally:
                    # cleanup temp wav
                    try:
                        os.remove(wav_path)
                    except Exception:
                        pass
            else:
                continue

        # ── Slash commands ──
        lower = user_input.lower()

        if lower in ("/exit", "/quit", "/q"):
            handle_exit()
            break

        if lower == "/help":
            print_colored(HELP_TEXT, "yellow")
            continue

        if lower.startswith("/voice"):
            parts = lower.split()
            if len(parts) >= 2 and parts[1] == "off":
                orchestrator.auto_voice = False
                print_colored("  Voice output: OFF", "yellow")
            elif len(parts) >= 2 and parts[1] == "on":
                orchestrator.auto_voice = True
                print_colored("  Voice output: ON", "green")
            else:
                state = "ON" if orchestrator.auto_voice else "OFF"
                print_colored(f"  Voice output: {state}  (use /voice on or /voice off)", "yellow")
            continue

        if lower == "/devices":
            if AUDIO_OK:
                print_colored("\n  Re-selecting audio devices...", "yellow")
                # Delete saved config to force re-pick
                if os.path.exists(DEVICE_CONFIG_PATH):
                    os.remove(DEVICE_CONFIG_PATH)
                input_device, output_device = setup_audio()
                if input_device is not None:
                    sd.default.device = (input_device, output_device)
            else:
                print_colored("  Audio not available (pip install sounddevice numpy)", "red")
            continue

        if lower == "/modules":
            names = sorted(mod.MODULES.keys())
            print_colored(f"\n  Loaded modules ({len(names)}):", "green")
            for i, name in enumerate(names, 1):
                print_colored(f"    {i:2}. {name}", "dim")
            print()
            continue

        if lower == "/clear":
            orchestrator.conversation_history.clear()
            print_colored("  ✓ Conversation history cleared", "green")
            continue

        if lower == "/status":
            voice = "ON" if orchestrator.auto_voice else "OFF"
            mic = "ON" if (AUDIO_OK and input_device is not None) else "OFF"
            hist = len(orchestrator.conversation_history) // 2
            _, models_now = check_ollama()
            print_colored(f"\n  Modules : {len(mod.MODULES)}", "dim")
            print_colored(f"  Voice   : {voice}", "dim")
            print_colored(f"  Mic     : {mic}", "dim")
            print_colored(f"  History : {hist} exchanges", "dim")
            print_colored(f"  Models  : {', '.join(models_now) if models_now else 'none'}", "dim")
            if AUDIO_OK and input_device is not None:
                devs = sd.query_devices()
                print_colored(f"  Input   : {devs[input_device]['name']}", "dim")
                print_colored(f"  Output  : {devs[output_device]['name']}", "dim")
            print()
            continue

        # ── Send to JAN ──
        send_to_jan(orchestrator, user_input, mod)


if __name__ == "__main__":
    main()
