# JAN — Joint Autonomous Neural Agent

**v2.1 · Linux-native · 29 modules · 14 specialized agents · fully offline · self-learning · BYO LLM**

JAN is a locally-running AI assistant that runs entirely on your machine via [Ollama](https://ollama.com). It controls your Linux PC, browses the web, sends emails, plays Spotify, remembers everything, and autonomously learns new skills — no cloud APIs required.

---

## What JAN Can Do

| Capability | How |
|---|---|
| Natural language chat | Ollama LLM (bring your own model) |
| Speaks every response | Microsoft Edge TTS — Urdu + English auto-detect |
| Always listening | Wake word "Hey JAN" → Whisper STT |
| PC control + terminal | Full shell access via `system_control.run_shell`, app launcher |
| Spotify (desktop app) | D-Bus MPRIS2 / xdotool / `spotify:search:` URI — never opens browser |
| YouTube | Search and open via browser |
| Email (Gmail) | Gmail compose URL → opens in your logged-in browser → Ctrl+Enter sends |
| WhatsApp / Discord | WhatsApp Web, Discord via browser agent |
| Web research | DuckDuckGo scraping → LLM summary |
| Long-term memory | SQLite + ChromaDB vector search |
| Self-learning RAG | Reads web pages → chunks → stores → injects into future prompts |
| Generates new modules | Writes, validates, and hot-loads new Python modules at runtime |
| Vision + face recognition | Webcam → OpenCV → face_recognition |
| AR overlay | WebSocket server — phone camera streams to JAN |
| Background daemon | Scheduled tasks, system monitoring, habit detection |

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
        ├── Agent executes tools (up to 15 steps per task)
        ├── RAG knowledge injected into every agent prompt
        ├── Skill memory: "what works" tips from past runs
        ├── System probe at startup → saves installed tools to memory
        ├── Auto-recall from long-term memory before each run
        ├── Auto-save conversation + result to memory after run
        └── Auto-speak response via Edge TTS

 ┌─────────────┐
 │   Daemon    │  (background: schedules, monitoring, patterns)
 └─────────────┘
```

### 14 Agents

| Agent | Max Steps | Tools | Handles |
|---|---|---|---|
| chat | 5 | memory, notes, time, weather, math | General Q&A, conversation |
| browser | 15 | browser, keyboard_mouse, screen_reader | Web navigation, forms |
| media | 10 | **spotify**, youtube, keyboard_mouse, app_launcher | Spotify app control, YouTube |
| communication | 15 | **system_control**, keyboard_mouse, browser, screen_reader | Gmail, WhatsApp, Discord |
| research | 15 | web_search, browser, memory | Multi-step web research |
| memory | 5 | memory, notes, proactive_learning | Memory recall and storage |
| productivity | 8 | notes, time, weather, file_manager | Notes, reminders, files |
| file | 10 | file_manager, keyboard_mouse, screen_reader | File/folder operations |
| system | 15 | app_launcher, **system_control**, **file_manager**, keyboard_mouse | Shell commands, app control, system discovery |
| coding | 15 | file_manager, browser, system_control, module_generator | Code writing, debugging |
| creative | 12 | file_manager, browser, notes, memory | Writing, brainstorming |
| automation | 20 | memory, time, system_control, file_manager | Scheduled tasks, workflows |
| vision | 8 | screen_reader, keyboard_mouse, vision | Screen reading, face recognition |
| self_improvement | 10 | module_generator, file_manager, memory, system_control, web_search | Generates new modules, learns new skills |

---

## Prerequisites

### 1. Ollama + models

```bash
# Install Ollama from https://ollama.com
ollama pull qwen2.5:7b-instruct    # default model for most agents
ollama pull qwen2.5-coder:7b       # recommended for coding agent
```

Set your chosen models in `config.yaml` under `models:` — you can assign different models to different agents.

### 2. System dependencies

```bash
# Core (required)
sudo apt install ffmpeg tesseract-ocr portaudio19-dev wmctrl

# Recommended: better Spotify control (search without keyboard injection)
sudo apt install xdotool playerctl

# Optional: face recognition
sudo apt install cmake libdlib-dev
```

> **Spotify**: JAN controls the **desktop app** via D-Bus MPRIS2 (`dbus-send`, built-in) + `wmctrl` for focusing + `xdg-open spotify:search:QUERY` for search. Install `playerctl` for the best experience. JAN never opens the web browser for Spotify.

> **Email**: JAN opens your real Chrome/Firefox (where you're logged in to Gmail) using a pre-filled compose URL. No password access needed.

### 3. Python 3.10+

```bash
python --version   # must be 3.10 or higher
```

---

## Installation

```bash
cd jarvis-core

# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

> **One-click setup:** `chmod +x setup.sh && ./setup.sh` — installs system deps, creates venv, installs pip packages, initializes directories.

### Optional extras

```bash
# Wake word ("Hey JAN")
pip install pyaudio openwakeword

# Face / voice recognition
pip install face-recognition resemblyzer

# Playwright for full browser automation (email compose, WhatsApp)
pip install playwright && playwright install chromium
```

---

## Running JAN

The Makefile is the primary entry point for everything. Run `make help` to see all targets.

```
make <target>                   # default port 8000
make <target> PORT=9000         # override port
```

### Setup

| Command | What it does |
|---|---|
| `make setup` | Full first-time setup — runs `setup.sh` (venv + deps + dirs) |
| `make install` | Install Python dependencies from `requirements.txt` |
| `make install-dev` | Install dev tools: ruff, black, pytest |
| `make install-optional` | Install wake word, face recognition, Playwright |

### Running the server

| Command | What it does |
|---|---|
| `make dev` | Dev server on port 8000, auto-reload on file changes |
| `make prod` | Production server, 2 workers, no reload |
| `make start` | Alias for `make dev` |
| `make open` | Open `http://localhost:8000` in your browser |

### Chatting with JAN

| Command | What it does |
|---|---|
| `make demo` | Standalone terminal chat — no server needed |
| `make chat` | CLI against the running server (full Phase 2–5 pipeline) |
| `make chat-v1` | CLI against the legacy v1 orchestrator |

### Health & status *(server must be running)*

| Command | What it does |
|---|---|
| `make health` | `GET /health` — all phase status + agent list |
| `make status` | `GET /api/status` — hardware, memory, LLM health |
| `make rankings` | `GET /api/v3/rankings` — agent and model score rankings |
| `make scores` | `GET /api/v5/scores` — ScoringEngine utility scores |
| `make audit` | Runs all four checks in sequence |

### Testing

| Command | What it does |
|---|---|
| `make test` | Run all tests (imports + pipeline) |
| `make test-imports` | Verify all module imports load cleanly |
| `make test-pipeline` | Phase 3–5 integration audit (13 checks) |

### Lint & format

| Command | What it does |
|---|---|
| `make lint` | Lint with ruff |
| `make format` | Format with black (in-place) |
| `make check` | lint + format-check (CI gate) |

### Database

| Command | What it does |
|---|---|
| `make db-init` | Create all SQLite tables — idempotent, safe to re-run |
| `make db-reset` | Drop + recreate all DBs — **irreversible, prompts for confirmation** |

### Ollama

| Command | What it does |
|---|---|
| `make ollama-check` | Check Ollama is running and list installed models |
| `make ollama-list` | List models via the `ollama` CLI |
| `make ollama-pull MODEL=llama3.1:8b` | Pull a specific model |

### Phase 5 — learning *(server must be running)*

| Command | What it does |
|---|---|
| `make refine` | Trigger a strategy refinement cycle |
| `make generate-tool CAP="read RSS feeds"` | Generate a new tool stub for a capability |
| `make pull-model MODEL=llama3.1:8b` | Pull a model via the JANOS API |

### Logs

| Command | What it does |
|---|---|
| `make logs-view` | Last 50 lines of the daemon log |
| `make logs-tail` | Live-tail the daemon log (Ctrl+C to stop) |

### Cleanup

| Command | What it does |
|---|---|
| `make clean` | Remove `__pycache__` and `.pyc` files |
| `make clean-logs` | Clear daemon log content (keeps the file) |
| `make clean-all` | Cache + logs cleanup (keeps databases) |
| `make clean-memory` | Reset all SQLite DBs — **irreversible** |

### Docs

| Command | What it does |
|---|---|
| `make docs` | View `ARCHITECTURE.md` in terminal pager |

---

## Configuration

Edit `config.yaml` before starting:

```yaml
settings:
  auto_voice: true          # JAN speaks every response via Edge TTS
  wake_word: true           # always-listening "Hey JAN" (needs pyaudio)
  ar_server: false          # AR WebSocket server
  default_city: Islamabad   # default location for weather
  orchestrator: v2          # v2 = agent-based (recommended) | v1 = single-shot

models:
  llm: "qwen2.5:7b-instruct"       # main model for most agents
  router: "qwen2.5:7b-instruct"    # intent classification
  coder: "qwen2.5-coder:7b"        # coding + self-improvement agents

# Per-agent model overrides
agents:
  max_steps: 15                     # default max steps per agent run
  models:
    coding: "qwen2.5-coder:7b"
    # override any agent's model here

learning:
  auto_start: true          # start background RAG learning on boot
  session_duration: 30      # minutes per learning session
  interval_hours: 6         # hours between sessions
```

Toggle any module on/off under `features:` without touching code.

---

## How Key Features Work

### Spotify

JAN controls the **installed Spotify desktop app** — never the web browser.

Control chain (tries each in order until one works):

1. **`playerctl`** — cleanest MPRIS2 interface (`sudo apt install playerctl`)
2. **`dbus-send`** — D-Bus MPRIS2, zero extra install (built into every D-Bus desktop)
3. **`xdotool`** — keyboard injection into the app window (`sudo apt install xdotool`)
4. **`spotify:search:QUERY` URI** — `xdg-open` opens search directly inside the app

For search specifically: starts Spotify if not running → focuses the window → types into search bar via xdotool, or falls back to opening `spotify:search:QUERY` URI which the app handles natively.

```
"play Blinding Lights on Spotify"
  → media agent → spotify.search_and_play("Blinding Lights")
    → open app → xdotool type → Enter
    OR → xdg-open spotify:search:Blinding+Lights
```

### Email

JAN opens your real browser (Chrome/Firefox where you're already logged in):

```
"email John about the meeting tomorrow"
  → communication agent
    → builds: https://mail.google.com/mail/?view=cm&fs=1&to=john@...&su=Meeting+Tomorrow&body=Hi+John%2C...
    → system_control.open_url → opens in YOUR browser (you're logged in)
    → waits 2s
    → keyboard_mouse Ctrl+Enter → sent
```

No Playwright, no login prompt. Falls back to `mailto:` URI for non-Gmail setups.

### Terminal / System Access

The system agent has full shell access via `system_control.run_shell`:

```
"is Spotify installed?"
  → system agent → run_shell: "which spotify || snap list | grep spotify"
  → returns: "/snap/bin/spotify"
  → "Yes, Spotify is installed at /snap/bin/spotify"

"what's eating my CPU?"
  → system agent → run_shell: "ps aux --sort=-%cpu | head -10"
  → returns: top processes table
```

At startup, JAN probes the system (installed tools, GPU, package managers) and saves findings to long-term memory so future responses are aware of your setup.

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
  -d '{"message": "Play Bohemian Rhapsody on Spotify"}'
```

### Agents

| Method | Endpoint | Description |
|---|---|---|
| GET | `/agents` | List all agents + their tools and config |
| POST | `/agents/run` | Run a specific agent with a task |
| POST | `/agents/classify` | Preview which agent handles a message |

```bash
# Run a specific agent
curl -X POST http://localhost:8000/agents/run \
  -H "Content-Type: application/json" \
  -d '{"agent": "system", "task": "What GPU does this machine have?"}'

# Preview routing
curl -X POST http://localhost:8000/agents/classify \
  -H "Content-Type: application/json" \
  -d '{"message": "Send an email to john about the project"}'
```

### Learning Engine

| Method | Endpoint | Description |
|---|---|---|
| GET | `/learning/stats` | RAG doc count, skills learned, session count |
| POST | `/learning/start` | Trigger a learning session |
| POST | `/learning/explore` | Research a specific topic into RAG |
| POST | `/learning/ingest` | Add a URL to the knowledge base |
| POST | `/learning/search` | Semantic search across RAG |
| GET | `/learning/skills` | View learned skill patterns |

### System

| Method | Endpoint | Description |
|---|---|---|
| GET | `/health` | Full system health — modules, agents, services |
| GET | `/modules` | List enabled/available modules |
| POST | `/process` | Call any module directly by name |
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
| app_launcher | ✅ | Open / close / focus any application |
| keyboard_mouse | ✅ | Type, click, hotkeys via pyautogui |
| file_manager | ✅ | File/folder CRUD, search, run shell commands |
| system_control | ✅ | Volume, clipboard, lock, shutdown, **run any shell command** |
| browser | ✅ | Browser automation via Playwright (webbrowser fallback) |
| web_search | ✅ | DuckDuckGo scraping + LLM summary |
| youtube | ✅ | Search and play YouTube videos |
| spotify | ✅ | **Desktop app control** via D-Bus MPRIS2 / xdotool / spotify: URI |
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

⚠️ = works but requires optional deps or hardware (camera, microphone, Playwright)

---

## Memory Structure

```
memory/
├── jarvis_memory.db      # SQLite: conversations, knowledge, user preferences
├── chroma_db/            # ChromaDB vector store (semantic search)
├── chroma_episodic/      # Episodic memory (recent events)
├── episodic.db           # Episodic memory SQLite
├── long_term.db          # Long-term fact storage
├── routing.db            # Agent routing history + scores
├── scoring.db            # Task scoring records
├── privilege_audit.jsonl # All shell commands run (audit trail)
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

1. **Startup probe** — on every boot, scans for installed tools (playerctl, xdotool, GPU, snap/flatpak apps) and saves to memory so agents know what's available
2. **Skill memory** — records every tool call outcome (agent / tool / input / success / error) and builds "what works" tips injected into future agent prompts
3. **RAG pipeline** — web search → read page → chunk (500 words, 50-word overlap) → MD5 dedup → ChromaDB vectors
4. **Knowledge explorer** — picks topics, searches the web, ingests into RAG on a configurable schedule
5. **Overnight sessions** — analyze past failures, explore new topics, extract user preferences

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
| STT | OpenAI Whisper |
| TTS | Microsoft Edge TTS (edge-tts) |
| Vector memory | ChromaDB + sentence-transformers (all-MiniLM-L6-v2) |
| Relational memory | SQLite |
| Spotify control | D-Bus MPRIS2 (`dbus-send`) + `xdg-open spotify:` URI |
| PC automation | subprocess, wmctrl, xdotool (optional), pyautogui (optional) |
| CV / vision | OpenCV, face_recognition |
| OCR | pytesseract / EasyOCR |
| Audio | sounddevice, soundfile, librosa |
| AR transport | WebSocket (websockets) |
| Web scraping | requests + BeautifulSoup |
| Browser automation | Playwright (optional, for deep web interaction) |

---

## Troubleshooting

**Spotify opens in browser instead of app**
JAN now uses D-Bus MPRIS2 — it never opens the browser for Spotify. If search isn't working, install xdotool: `sudo apt install xdotool`. For best experience install playerctl: `sudo apt install playerctl`.

**Email loops on email.com / doesn't compose**
JAN now uses Gmail's compose URL (`?view=cm&fs=1`) opened in your real browser. Make sure you're logged in to Gmail in Chrome/Firefox. If `system_control.open_url` doesn't open your browser, check `xdg-open` works: `xdg-open https://google.com`.

**LLM not responding**
Ensure Ollama is running (`ollama serve`) and your model is pulled (`ollama pull qwen2.5:7b-instruct`).

**`ffplay` not found (TTS silent)**
Install ffmpeg: `sudo apt install ffmpeg`.

**`pyautogui` fails on Linux**
Install display deps: `sudo apt install python3-tk python3-dev`. Note: Spotify and email no longer require pyautogui — only keyboard_mouse agent actions need it.

**Tesseract OCR not found**
`sudo apt install tesseract-ocr`

**`No module named 'chromadb'`**
`pip install chromadb sentence-transformers`

**`webrtcvad` fails to compile**
Optional — wake word detection falls back to energy-based VAD automatically.

**Shell commands not working in system agent**
The system agent uses `system_control.run_shell`. Test it directly:
```bash
curl -X POST http://localhost:8000/process \
  -H "Content-Type: application/json" \
  -d '{"module": "system_control", "input": {"action": "run_shell", "command": "whoami"}}'
```

---

## Project Layout

```
jarvis-core/
├── main.py                    # FastAPI app — all API routes + startup
├── config.yaml                # Feature toggles + model + agent settings
├── demo.py                    # Terminal chat (no server needed)
├── Makefile                   # 40-target developer entry point
├── setup.sh                   # One-click Linux installer
├── requirements.txt           # Core pip deps
├── requirements_full.txt      # Full dep list including optional packages
├── core/                      # New architecture backbone
│   ├── config.py              # Config singleton
│   ├── llm.py / llm_client.py # Unified Ollama interface
│   ├── memory.py              # Short + long-term memory
│   ├── episodic_memory.py     # Episodic event store
│   ├── hardware_monitor.py    # GPU/CPU/RAM monitoring
│   ├── model_router.py        # Smart model routing by load
│   ├── reasoning_pipeline.py  # Think → plan → execute → critique pipeline
│   ├── scoring.py             # Task scoring engine
│   └── logger.py              # Structured JSON logging
├── agents/                    # Top-level agent framework (LangGraph / AutoGen)
│   ├── planner.py, executor.py, reflector.py
│   ├── crew_agents.py         # CrewAI-style multi-agent crews
│   └── autogen_debate.py      # AutoGen debate pattern
├── tools/                     # Pluggable tool interface
│   ├── privileged_shell.py    # Sudo-aware shell with audit log
│   └── *.py                   # math, time, weather, web_search, file, system, browser, media
├── modules/
│   ├── __init__.py            # Module registry + dependency wiring + startup probe
│   ├── base.py                # ModuleBase class
│   ├── orchestrator_v2_module.py  # v2 agent dispatcher (keyword → LLM routing)
│   ├── learning_engine.py     # RAG + skill memory + background learning
│   ├── spotify_module.py      # D-Bus / xdotool / spotify: URI control
│   ├── agents/                # 14 specialized agent classes
│   └── *.py                   # 29 individual modules
├── frontend/
│   ├── index.html             # JARVIS-style dark chat UI
│   ├── style.css
│   └── app.js
├── ar_client/
│   └── index.html             # Phone AR web app
├── memory/                    # Runtime data (SQLite, ChromaDB, audio, faces)
└── logs/                      # Dev logs and session records
```

---

## Roadmap

- [ ] `llava` / vision model for real screen understanding (not just OCR)
- [ ] `playerctl` auto-install check on startup with user prompt
- [ ] Custom wake word training for "Hey JAN"
- [ ] WhatsApp desktop app integration (not just Web)
- [ ] Telegram bot integration
- [ ] Docker deployment option
- [ ] GPU load balancing across Ollama model calls
- [ ] Interactive terminal session (persistent PTY, not just one-shot run_shell)
