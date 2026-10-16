# JAN — Joint Autonomous Neural Agent

**v2.0 · 29 modules · 14 specialized agents · fully offline · self-learning**

JAN is a locally-running AI assistant that runs entirely on your machine via [Ollama](https://ollama.com). It controls your PC, browses the web, remembers everything, and autonomously learns new skills — no cloud APIs required.

---

## What JAN Can Do

| Capability | How |
|---|---|
| Natural language chat | Ollama LLM (qwen2.5:7b / llama3.1:8b) |
| Speaks every response | Microsoft Edge TTS — Urdu + English auto-detect |
| Always listening | Wake word "Hey JAN" → Whisper STT |
| PC control | Open apps, type, click, screenshots, file ops |
| Web research | DuckDuckGo scraping → LLM summary (no Playwright needed) |
| YouTube + Spotify | Search and play via browser / pyautogui |
| Long-term memory | SQLite + ChromaDB vector search |
| Self-learning RAG | Reads web pages → chunks → stores → injects into future prompts |
| Generates new modules | Writes, validates, and hot-loads new Python modules at runtime |
| Vision + face recognition | Webcam → OpenCV → face_recognition |
| AR overlay | WebSocket server — phone camera streams to JAN |
| Background daemon | Scheduled tasks, system monitoring, habit detection |
| Windows service | Auto-starts on boot, auto-restarts on crash |

---

## Architecture

```
User speaks / types
        │
        ▼
 ┌─────────────┐
 │  Wake Word   │  (always listening "Hey JAN")
 │  or /chat    │  (API endpoint)
 │  or demo.py  │  (terminal)
 └──────┬──────┘
        ▼
 ┌──────────────────────────────────────────┐
 │         Orchestrator v2 (Brain)          │
 │  keyword-first routing → LLM fallback    │
 │  14 specialized agents, agentic loops    │
 └──────┬───────────────────────────────────┘
        │
        ├── Agent executes tools (up to 20 steps per task)
        ├── RAG knowledge injected into every agent prompt
        ├── Skill memory: "what works" tips from past runs
        ├── Auto-recall from long-term memory before run
        ├── Auto-save conversation + result to memory after run
        ├── Auto-speak response via Edge TTS
        │
        ▼
 ┌─────────────┐
 │   Daemon    │  (background: schedules, monitoring, patterns)
 └─────────────┘
```

### 14 Agents (7 Tiers)

| Tier | Agent | Model | Max Steps | Handles |
|---|---|---|---|---|
| 1 | chat | qwen2.5:7b-instruct | 5 | General Q&A, notes, time, weather, math |
| 2 | browser | qwen2.5:7b-instruct | 15 | Web navigation, form filling |
| 2 | media | qwen2.5:7b-instruct | 12 | Spotify, YouTube, app launcher |
| 2 | communication | qwen2.5:7b-instruct | 20 | Email, messaging via browser |
| 3 | research | qwen2.5:7b-instruct | 15 | Multi-step web research, summarization |
| 3 | memory_agent | qwen2.5:7b-instruct | 5 | Memory recall and storage |
| 4 | productivity | qwen2.5:7b-instruct | 8 | Notes, files, calendar, weather |
| 4 | file | qwen2.5:7b-instruct | 10 | File/folder operations |
| 5 | system | qwen2.5:7b-instruct | 10 | App management, system control |
| 6 | coding | qwen2.5-coder:7b | 15 | Code writing, file editing, module generation |
| 6 | creative | qwen2.5:7b-instruct | 12 | Writing, brainstorming |
| 7 | automation | qwen2.5:7b-instruct | 20 | Scheduled tasks, habit automation |
| 7 | vision | qwen2.5:7b-instruct | 8 | Screen reading, face recognition |
| 7 | self_improvement | qwen2.5-coder:7b | 10 | Generates + hot-loads new modules |

---

## Prerequisites

### 1. System dependencies

**Linux / Ubuntu:**
```bash
sudo apt install ffmpeg tesseract-ocr portaudio19-dev
```

**macOS:**
```bash
brew install ffmpeg tesseract portaudio
```

**Windows:**
- [ffmpeg](https://ffmpeg.org/download.html) → add to PATH
- [Tesseract](https://github.com/UB-Mannheim/tesseract/wiki) → add to PATH

### 2. Ollama + models

```bash
# Install Ollama from https://ollama.com
ollama pull qwen2.5:7b-instruct   # primary router + 12 agents
ollama pull qwen2.5-coder:7b      # coding + self_improvement agents
ollama pull llama3.1:8b           # big model for complex reasoning
```

Minimum: just `qwen2.5:7b-instruct` (~4.7 GB). The system runs fine without the others — dual_llm falls back gracefully.

### 3. Python 3.10+

```bash
python --version   # must be 3.10 or higher
```

---

## Installation

```bash
# Clone / enter the project
cd jarvis-core

# Create virtual environment
python -m venv venv

# Activate it
source venv/bin/activate          # Linux / macOS
venv\Scripts\activate             # Windows

# Install dependencies
pip install -r requirements.txt
```

> **Windows one-click install:** run `install.bat` — checks Python, installs deps, pulls Ollama models.

### Optional: face recognition

```bash
# Requires cmake + dlib headers
pip install face-recognition resemblyzer
```

### Optional: wake word (always-listening "Hey JAN")

```bash
pip install pyaudio openwakeword
```

---

## Running JAN

### Option A — Terminal chat (quickest, no server)

```bash
python demo.py
```

Type messages directly. No browser needed. Good for testing modules.

### Option B — Full server (recommended)

```bash
# Make sure Ollama is running first
ollama serve   # in a separate terminal if not auto-started

# Start JAN
uvicorn main:app --host 0.0.0.0 --port 8000
```

Open **http://localhost:8000** — the JARVIS-style dark chat UI loads automatically.

### Option C — Windows service (boot-time auto-start)

```bash
# Standalone mode (no service install needed)
python jan_service.py standalone

# Or copy startup.bat to your Windows Startup folder for boot-time launch
```

### Option D — EXE package

```bash
pip install pyinstaller
python build_exe.py
# Output: dist/JAN.exe
```

---

## Configuration

Edit `config.yaml` before starting:

```yaml
settings:
  auto_voice: true          # JAN speaks every response via Edge TTS
  wake_word: true           # always-listening "Hey JAN" (needs pyaudio)
  ar_server: false          # AR WebSocket server (enable for phone/VR use)
  camera_watch: false       # auto-detect faces via webcam on startup
  default_city: Islamabad   # default city for weather
  orchestrator: v2          # v2 = agent-based (recommended) | v1 = single-shot

models:
  llm: "llama3.1:8b"               # big model (complex reasoning)
  router: "qwen2.5:7b-instruct"    # agent routing + most tasks
  coder: "qwen2.5-coder:7b"        # coding / self-improvement agents

learning:
  auto_start: true          # start background RAG learning on boot
  session_duration: 30      # minutes per learning session
  interval_hours: 6         # hours between sessions
  topics:                   # custom topics to research automatically
    - "latest AI news and developments"
    - "Pakistan current events"
```

Toggle any module on/off under `features:` without touching code.

---

## API Reference

Base URL: `http://localhost:8000`

### Chat

| Method | Endpoint | Description |
|---|---|---|
| POST | `/chat` | Send a message to JAN (uses configured orchestrator) |
| POST | `/chat/v1` | Legacy single-shot orchestrator |
| POST | `/chat/v2` | Agent-based orchestrator (explicit) |

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What is the weather in Islamabad?"}'
```

### Agents

| Method | Endpoint | Description |
|---|---|---|
| GET | `/agents` | List all agents + their tools and config |
| POST | `/agents/run` | Run a specific agent with a task |
| POST | `/agents/classify` | Classify which agent would handle a message |

```bash
# Run a specific agent
curl -X POST http://localhost:8000/agents/run \
  -H "Content-Type: application/json" \
  -d '{"agent": "research", "task": "What is quantum computing?"}'

# Preview routing without executing
curl -X POST http://localhost:8000/agents/classify \
  -H "Content-Type: application/json" \
  -d '{"message": "Play something on Spotify"}'
```

### Learning Engine

| Method | Endpoint | Description |
|---|---|---|
| GET | `/learning/stats` | RAG doc count, skills learned, session count |
| POST | `/learning/start` | Trigger a learning session |
| POST | `/learning/explore` | Research a specific topic into RAG |
| POST | `/learning/ingest` | Add a URL to the knowledge base |
| POST | `/learning/search` | Semantic search across RAG |
| GET | `/learning/skills` | View learned skill patterns ("what works") |

### System

| Method | Endpoint | Description |
|---|---|---|
| GET | `/health` | Full system health — modules, agents, services |
| GET | `/modules` | List enabled/available modules |
| POST | `/process` | Call any module directly |
| POST | `/voice/toggle` | Toggle auto-voice on/off |
| GET | `/daemon/status` | Background daemon status |

---

## Modules (29 total)

| Module | Status | Description |
|---|---|---|
| echo | ✅ | Test echo |
| math | ✅ | Calculator |
| time | ✅ | Date/time queries |
| weather | ✅ | Forecast via Open-Meteo API (no key needed) |
| notes | ✅ | Personal notes (file-based) |
| stt | ✅ | Whisper speech-to-text |
| tts | ✅ | Legacy pyttsx3 fallback |
| smart_tts | ✅ | Edge TTS — natural Urdu + English voices |
| speaker | ✅ | Speaker audio output |
| app_launcher | ✅ | Open / close any application |
| keyboard_mouse | ✅ | Type, click, hotkeys, pyautogui |
| file_manager | ✅ | File/folder CRUD and search |
| system_control | ⚠️ | Volume (needs pycaw), clipboard, lock, shutdown |
| browser | ✅ | Browser automation (webbrowser fallback) |
| web_search | ✅ | DuckDuckGo scraping + LLM summary |
| youtube | ✅ | Search and open YouTube videos |
| spotify | ✅ | Search + play via pyautogui keyboard |
| memory | ✅ | SQLite + ChromaDB long-term memory |
| research_agent | ✅ | Multi-step web research |
| module_generator | ⚠️ | Self-writes and hot-loads new Python modules |
| proactive_learning | ⚠️ | Habit tracking, pattern analysis, scheduled tasks |
| dual_llm | ✅ | Smart small/big model routing by complexity |
| vision | ⚠️ | Webcam, face detection, OCR, image description |
| person_recognition | ⚠️ | Multi-modal face + voice person ID |
| ar | ⚠️ | WebSocket AR overlay server |
| daemon | ⚠️ | Background scheduled task + monitoring loop |
| wake_word | ⚠️ | Always-listening "Hey JAN" activation |
| screen_reader | ✅ | Screenshot + OCR via pytesseract |
| learning_engine | ✅ | RAG pipeline + skill memory + overnight learning |

⚠️ = works but requires optional deps or hardware (camera, microphone, pycaw)

---

## Memory Structure

```
memory/
├── jarvis_memory.db      # SQLite: conversations, knowledge, user preferences
├── chroma_db/            # ChromaDB vector store (semantic search)
├── notes.json            # User notes
├── audio/tts/            # Edge TTS output
├── vision/captures/      # Webcam captures
├── vision/known_faces/   # Enrolled face encodings
├── voices/               # Voice embeddings for person recognition
└── logs/daemon.log       # Background daemon heartbeat log
```

The memory module uses `all-MiniLM-L6-v2` (~79 MB, auto-downloaded on first run) for semantic embeddings.

---

## Self-Learning Engine (RAG)

JAN builds a knowledge base automatically:

1. **Skill memory** — records every tool call outcome (agent / tool / input / success / error) and builds "what works" tips injected into future agent prompts
2. **RAG pipeline** — web search → read page → chunk (500 words, 50-word overlap) → MD5 dedup → ChromaDB vectors
3. **Knowledge explorer** — picks topics, searches the web, ingests into RAG on a configurable schedule
4. **Overnight sessions** — analyze past failures, explore new topics, extract user preferences

Configure under `learning:` in `config.yaml`. Disable with `auto_start: false`.

---

## AR Phone Client

JAN includes a standalone phone AR app (`ar_client/index.html`). Open it on your phone's browser while on the same WiFi network.

Features:
- Full-screen rear camera stream sent to JAN over WebSocket
- Real-time overlay: translated text, navigation arrows, object labels, face names
- 4 modes: Translate, Navigate, Detect Objects, Label Faces
- GPS tracking for navigation mode

Enable in `config.yaml`:
```yaml
settings:
  ar_server: true
```

Then open `ar_client/index.html` on your phone and enter your PC's local IP.

---

## Key Technologies

| Layer | Tech |
|---|---|
| API server | FastAPI + Uvicorn |
| LLM inference | Ollama (fully local, no cloud) |
| Primary model | qwen2.5:7b-instruct |
| Big model | llama3.1:8b (on-demand) |
| Coder model | qwen2.5-coder:7b |
| STT | OpenAI Whisper |
| TTS | Microsoft Edge TTS (edge-tts) |
| Vector memory | ChromaDB + sentence-transformers (all-MiniLM-L6-v2) |
| Relational memory | SQLite |
| PC automation | pyautogui, subprocess, os |
| CV / vision | OpenCV, face_recognition |
| OCR | pytesseract / EasyOCR |
| Audio | sounddevice, soundfile, librosa |
| AR transport | WebSocket (websockets) |
| Web scraping | requests + BeautifulSoup (no Playwright needed) |
| Packaging | PyInstaller |

---

## Troubleshooting

**`scipy>=1.17.1` not found**
The `requirements.txt` has been fixed to `scipy>=1.13.0`. Run `pip install -r requirements.txt` again.

**`webrtcvad` fails to compile**
It's now listed as optional. Skip it — wake word detection falls back to energy-based VAD automatically.

**`No module named 'chromadb'`**
Run `pip install chromadb sentence-transformers`.

**`ffplay` not found (TTS silent)**
Install ffmpeg and ensure it's in your PATH. On Windows: `winget install ffmpeg`.

**LLM not responding**
Ensure Ollama is running (`ollama serve`) and the model is pulled (`ollama pull qwen2.5:7b-instruct`).

**`pyautogui` fails on Linux**
Install `python3-tk` and `python3-dev`: `sudo apt install python3-tk python3-dev`.

**Tesseract OCR not found**
Install tesseract-ocr system package and ensure it's in PATH.

---

## Project Layout

```
jarvis-core/
├── main.py                    # FastAPI app — all API routes
├── config.yaml                # Feature toggles + model + agent settings
├── demo.py                    # Terminal chat (no server needed)
├── jan_service.py             # Windows service / standalone launcher
├── build_exe.py               # PyInstaller EXE builder
├── install.bat                # Windows one-click installer
├── startup.bat                # Windows Startup folder launcher
├── requirements.txt           # Core pip deps
├── requirements_full.txt      # Full dep list including optional packages
├── modules/
│   ├── __init__.py            # Module registry + dependency wiring
│   ├── base.py                # ModuleBase class
│   ├── orchestrator_module.py # v1 single-shot LLM orchestrator
│   ├── orchestrator_v2_module.py  # v2 agent dispatcher
│   ├── learning_engine.py     # RAG + skill memory + background learning
│   ├── agents/                # 14 specialized agent classes
│   └── *.py                   # 29 individual modules
├── frontend/
│   ├── index.html             # JARVIS-style dark chat UI
│   ├── style.css
│   └── app.js
├── ar_client/
│   └── index.html             # Phone AR web app (no build step)
├── memory/                    # Runtime data (SQLite, ChromaDB, audio, faces)
└── logs/                      # Development logs and planning docs
```

---

## Roadmap

- [ ] End-to-end testing with live Ollama on clean machine
- [ ] `llava` vision model integration for screen understanding
- [ ] Custom wake word training for "Hey JAN"
- [ ] Mobile companion app (beyond AR client)
- [ ] WhatsApp / Telegram bot integration
- [ ] Docker deployment option
