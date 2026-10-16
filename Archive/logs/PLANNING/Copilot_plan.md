# Jarvis Expansion Plan — The Full Companion

## Vision
Transform Jarvis from a modular API server into a **fully autonomous PC companion** that:
- Thinks with a local LLM (Ollama)
- Controls the entire PC (apps, files, system)
- Browses the internet like a human (browser automation)
- Finds, suggests, and does things for you proactively
- Learns and remembers everything — acts like a friend

## Current State
- FastAPI core brain with module plugin system ✅
- STT (Whisper), TTS (pyttsx3), Speaker ID (Resemblyzer) ✅
- Utility modules (weather, notes, math, time, echo) ✅
- Push-to-talk recording ✅
- MODULE_SCHEMAS for LLM integration ✅
- **Phase 1 — LLM Orchestrator (Ollama + llama3.1:8b) ✅**
- **Phase 2 — PC Control (app launcher, keyboard/mouse, file manager, system control) ✅**
- **Phase 3 — Browser & Internet (browser automation, web search, YouTube, Spotify) ✅**
- **Improvement: YouTube ad-skip, click_link browser nav, Urdu/English auto-detect ✅**

## Architecture Overview

```
  You (voice/text) 
       ↓
  [Orchestrator — Local LLM via Ollama]
       ↓ thinks, plans, picks tools
  [Tool Router]
       ↓
  ┌─────────────────────────────────────────────┐
  │ pc_control   │ browser    │ web_search      │
  │ app_launcher │ spotify    │ youtube          │
  │ file_manager │ clipboard  │ screen_reader    │
  │ stt / tts    │ speaker_id │ memory/learning  │
  └─────────────────────────────────────────────┘
       ↓
  [Memory Layer — conversation history + semantic search]
```

---

## Phase 1 — The Brain (LLM Orchestrator)
**Goal:** Give Jarvis the ability to *think* and decide which module to use.

### 1a. Install & configure Ollama
- Install Ollama on Windows
- Pull a good reasoning model (e.g., `llama3.1:8b` or `mistral`)
- Test basic prompt → response locally

### 1b. Build orchestrator module
- New `orchestrator_module.py` that:
  - Takes natural language input from user
  - Sends it to Ollama with system prompt containing MODULE_SCHEMAS
  - LLM decides which module(s) to call and with what parameters
  - Executes the module(s) and returns a natural response
- Conversation history tracking (context window)
- Personality prompt: friendly, helpful, proactive

### 1c. Update main.py flow
- New `/chat` endpoint: text in → orchestrator thinks → action + response out
- New `/voice` endpoint: audio in → STT → orchestrator → TTS → audio out
- The orchestrator becomes the default entry point (not manual module calls)

---

## Phase 2 — PC Control (Hands on the Machine)
**Goal:** Jarvis can open apps, manage files, control the system.

### 2a. App Launcher module
- Open any installed application by name (Spotify, Chrome, VS Code, etc.)
- Uses `subprocess` + Windows `start` command + known app paths
- Close/minimize/maximize windows via `pygetwindow`
- Config file mapping friendly names → executable paths

### 2b. File Manager module
- Browse, search, create, move, copy, delete files/folders
- Read file contents (text, PDF, images)
- Search files by name or content across drives
- Safety: confirmation before destructive actions (delete, overwrite)

### 2c. System Control module
- Volume control (up/down/mute)
- Brightness control
- Screenshot capture
- Clipboard read/write
- Lock screen, shutdown, restart (with confirmation)
- WiFi toggle, Bluetooth toggle

### 2d. Keyboard & Mouse module (low-level)
- `pyautogui` for typing, clicking, scrolling
- Hotkey simulation (Alt+Tab, Win+D, etc.)
- This is the fallback — when no specific module exists, Jarvis can still "use" any app by controlling keyboard/mouse

---

## Phase 3 — Browser Automation (The Internet Human)
**Goal:** Jarvis browses the web like a real person.

### 3a. Browser Controller module
- Uses `playwright` (headless or visible Chrome)
- Open URLs, navigate, click, type, scroll, read page content
- Take screenshots of pages for visual context
- Handle tabs (open, switch, close)

### 3b. Web Search module
- Google/DuckDuckGo search automation
- Read search results, extract relevant info
- Summarize findings using the LLM
- Return answers with source links

### 3c. YouTube module
- Search YouTube for videos
- Pick the best result based on LLM reasoning (views, relevance, rating)
- Open/play the video in browser
- Example: "Find me the best butter chicken recipe video"

### 3d. Spotify module
- Open Spotify desktop app or web player
- Search for songs/playlists/artists
- Play/pause/skip/volume control
- Uses Spotify keyboard shortcuts or Spotify Web API (free tier)

---

## Phase 4 — Memory & Learning (The Friend)
**Goal:** Jarvis remembers everything and gets smarter over time.

### 4a. Conversation Memory
- Store all conversations in a local database (SQLite)
- Semantic search over past conversations using embeddings
- "Remember when I told you about...?" → Jarvis recalls

### 4b. Knowledge Base
- Jarvis can save learnings from web research
- Vector store (ChromaDB or FAISS) for semantic retrieval
- When asked something, checks memory first before searching

### 4c. User Profile & Preferences
- Learns your preferences over time (favorite music, food, work habits)
- Stores in `memory/profile.json`
- Uses preferences to make proactive suggestions
- "It's 7pm, you usually like to listen to lofi — should I play some?"

### 4d. Proactive Mode
- Background task that checks time-based triggers
- Morning briefing (weather, calendar, news)
- Reminders, suggestions, "Hey, you haven't taken a break in 2 hours"

---

## Phase 5 — Self-Evolution (The Learner)
**Goal:** Jarvis can research and build new capabilities.

### 5a. Module Generator
- LLM generates new module code based on MODULE_SCHEMAS template
- Tests in sandboxed subprocess before installing
- Requires your approval before adding to the system

### 5b. Web Research Agent
- Given a topic, Jarvis autonomously:
  - Searches the web
  - Reads multiple pages
  - Summarizes and stores findings
  - Can create step-by-step guides

### 5c. Skill Discovery
- "I wish you could..." → Jarvis searches GitHub/PyPI/web for solutions
- Proposes a new module to add the capability
- Builds and tests it with your approval

---

## Implementation Order (Suggested)

1. **Phase 1** — Brain (Ollama + Orchestrator) — *foundation for everything*
2. **Phase 2a+2d** — App Launcher + Keyboard/Mouse — *quick wins, impressive*
3. **Phase 3a+3b** — Browser + Web Search — *Jarvis goes online*
4. **Phase 3c+3d** — YouTube + Spotify — *the fun stuff*
5. **Phase 2b+2c** — File Manager + System Control — *full PC access*
6. **Phase 4** — Memory & Learning — *becomes a friend*
7. **Phase 5** — Self-Evolution — *becomes alive*

---

## Tech Stack Summary
| Component | Tool |
|-----------|------|
| Brain | Ollama (llama3.1:8b or mistral) |
| Core | FastAPI (existing) |
| Browser | Playwright (Python) |
| PC Control | pyautogui, pygetwindow, subprocess |
| Audio | Whisper STT, pyttsx3 TTS (existing) |
| Memory | SQLite + ChromaDB/FAISS embeddings |
| Identity | Resemblyzer voice + face_recognition (existing) |

## Notes
- Every new capability = a new module following ModuleBase pattern
- Orchestrator LLM sees all MODULE_SCHEMAS and picks the right tool
- Safety: destructive actions always require confirmation
- All data stays local — no cloud dependency except optional web browsing
