# JANOS Architecture & Data Flow Report

> **JAN** = Joint Autonomous Neural Agent  
> **OS** = Operating System (Linux-native after full rewrite)

---

## 1. Project Structure

```
jarvis-core/
│
├── main.py                  # FastAPI entry
├── chat.py                  # Server CLI — Phase 2-5 chat via HTTP
├── demo.py                  # Terminal chat + voice mode (standalone) — legacy v1/v2 + new Phases 1-5 API
├── config.yaml              # Central config: ollama, hardware, memory, agents
├── setup.sh                 # Linux one-click installer
├── requirements.txt         # Dependencies
├── ARCHITECTURE.md          # This document
├── ARCHITECTURE.html        # Visual SVG architecture diagram
│
├── core/                    # ★ SYSTEM CORE (Phases 1-5) ★
│   ├── config.py            #   Singleton config reader (config.yaml → Python)
│   ├── llm_client.py        #   Unified LLM client (Ollama + OpenRouter providers)
│   ├── model_router.py      #   Dynamic model selection from installed models
│   ├── hardware_monitor.py  #   nvidia-smi + psutil background task
│   ├── episodic_memory.py   #   ChromaDB + SQLite with RAG retrieval
│   ├── log_bootstrap.py     #   Parses logs/*.md at startup → seed memory
│   ├── state_machine.py     #   MVP 12-state pipeline (Phase 1)
│   ├── langgraph_machine.py #   Full LangGraph 13-state machine (Phase 2)
│   ├── reasoning_pipeline.py#   RAG → plan → execute → validate → store
│   ├── routing.py           #   Scoring feedback loop, agent/model rankings
│   ├── commands.py          #   /command interface + self-description
│   ├── scoring.py           #   RL-inspired utility scoring engine
│   ├── memory.py            #   Short-term (buffer) + long-term (SQLite)
│   ├── logger.py            #   Structured JSON logger
│   └── llm.py               #   Legacy LLM interface (preserved for v3 compat)
│
├── agents/                  # ★ AGENT LAYER (Phase 2) ★
│   ├── crew_agents.py       #   6 CrewAI-style agent roles
│   │                           PlannerAgent, ExecutorAgent, CriticAgent,
│   │                           SearcherAgent, MemoryAgent, FileOperatorAgent
│   ├── autogen_debate.py    #   Multi-agent debate for complex tasks
│   ├── base.py              #   Legacy base agent (think → act → observe loop)
│   ├── registry.py          #   Legacy global agent register
│   ├── planner.py           #   Legacy planner
│   ├── executor.py          #   Legacy executor
│   ├── researcher.py        #   Legacy researcher
│   ├── reflector.py         #   Legacy reflector
│   └── orchestrator.py      #   Legacy orchestrator
│
├── tools/                   # ★ TOOL LAYER (Phases 1-5) ★
│   ├── privileged_shell.py  #   Sudo-aware shell with audit log (Phase 4)
│   ├── registry_v2.py       #   Extended tool registry
│   ├── base.py              #   Base tool contract
│   ├── registry.py          #   Legacy tool registry
│   ├── math_tool.py         #   Evaluate math expressions
│   ├── time_tool.py         #   Current date/time
│   ├── weather_tool.py      #   OpenWeather API
│   ├── web_search_tool.py   #   DuckDuckGo HTML search
│   ├── file_tool.py         #   Read/write/list files
│   ├── system_tool.py       #   OS info (cpu/mem/disk)
│   ├── browser_tool.py      #   Fetch & extract text from URLs
│   └── media_tool.py        #   playerctl media control
│
├── modules/                 # ★ LEGACY modules (v1 + v2 — preserved) ★
│   ├── __init__.py          #   Registry of 27+ modules + 14 agents
│   ├── orchestrator_module.py     # v1 single-shot LLM orchestrator
│   ├── orchestrator_v2_module.py  # v2 agent dispatcher
│   ├── screen_reader.py           # Screenshot + OCR
│   ├── agents/                    # 14 specialized agents
│   │   └── base_agent.py          # Base agent class
│   └── *.py                  # 27+ feature modules
│
├── memory/                  # Runtime data (gitignored)
│   ├── episodic.db          # Episodic memory SQLite
│   ├── routing.db           # Agent/model scoring SQLite
│   ├── scoring.db           # v3 scoring SQLite
│   ├── long_term.db         # v3 long-term memory SQLite
│   ├── chroma_episodic/     # ChromaDB persistent for episodic memory
│   ├── chroma_db/           # Legacy ChromaDB
│   ├── privilege_audit.jsonl# Privilege escalation audit log
│   ├── undo_log.jsonl       # Undo log for destructive operations
│   └── logs/                # Structured JSON logs
│
├── logs/                    # Historical logs + phase documentation
│   ├── 2026-06-16_Phase01.md # Phase 1: Infrastructure
│   ├── 2026-06-16_Phase02.md # Phase 2: LangGraph + Agents
│   ├── 2026-06-16_Phase03.md # Phase 3: Memory + Self-Healing
│   ├── 2026-06-16_Phase04.md # Phase 4: Commands + Privilege
│   ├── 2026-06-16_Phase05.md # Phase 5: Continuous Learning
│   └── PLANNING/            # Planning artifacts
│
├── frontend/                # Chat UI (HTML/JS/CSS)
└── venv/                    # Python virtual environment
```

---

## 2. Architecture Overview (Three Parallel Systems)

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                         FASTAPI SERVER (main.py)                                  │
│  uvicorn :8000                                                                    │
└──────┬──────────────────────────────────┬────────────────────────────────────────┘
       │                                  │
       ▼                                  ▼
┌──────────────┐                 ┌──────────────────────────────────────┐
│  LEGACY API  │                 │  NEW API (Phases 1-5)                │
│  /chat       │                 │  /api/status            (P1 system)  │
│  /process    │                 │  /api/chat              (P1 MVP)     │
│  /agents/*   │                 │  /api/memory/*          (P1 memory)  │
│  /learning/* │                 │  /api/models/*          (P1 LLM)     │
│  /voice/*    │                 │  /api/v2/chat           (P2 full)    │
│  /health     │                 │  /api/v2/agents/*       (P2 agents)  │
│              │                 │  /api/v2/debate         (P2 debate)  │
│              │                 │  /api/v3/validate       (P3 critic)  │
│              │                 │  /api/v3/heal           (P3 healing) │
│              │                 │  /api/v3/rankings       (P3 routing) │
│              │                 │  /api/v4/command        (P4 commands)│
│              │                 │  /api/v4/exec           (P4 privilege│
│              │                 │  /api/v4/audit          (P4 audit)   │
│              │                 │  /api/v5/refine         (P5 learning)│
│              │                 │  /api/v5/generate-tool  (P5 generate)│
└──────┬───────┘                 └──────────────────┬───────────────────┘
       │                                            │
       ▼                                            ▼
┌──────────────────────┐          ┌─────────────────────────────────────────────┐
│   LEGACY ENGINE       │          │   NEW ENGINE (Phases 1-5)                    │
│                       │          │                                              │
│  v1 Orchestrator      │          │   LangGraph State Machine (13 states)       │
│   (single-shot)       │          │    INPUT → RAG_RECALL → MODEL_SELECT →      │
│                       │          │    TASK_DECOMPOSE → AGENT_ALLOCATE →        │
│  v2 Orchestrator      │          │    EXECUTE → CRITIC_VALIDATE →              │
│   (agent-based)       │          │    STORE_EPISODE → RESPOND                  │
│   14 agents           │          │    → END (with RETRY/ESCALATE/FAIL)          │
│   27+ modules         │          │                                              │
│                       │          │   CrewAI Agents:                             │
│  ScreenReader         │          │    Planner, Executor, Critic,               │
│  SQLite Memory        │          │    Searcher, MemoryAgent, FileOperator       │
│  ChromaDB (legacy)    │          │                                              │
│                       │          │   AutoGen Debate (for complex tasks)         │
│                       │          │                                              │
│                       │          │   Episodic Memory (ChromaDB + SQLite)        │
│                       │          │   Hardware Monitor (nvidia-smi + psutil)     │
│                       │          │   Command Interface (/command)               │
│                       │          │   Privilege System (sudo-aware shell)        │
│                       │          │   Strategy Refiner (startup + 24h loop) [P5]     │
│                       │          │   Routing Engine (wired to v2/chat) [P3]     │
│                       │          │   Log Bootstrap (@logs/*.md)                 │
└──────────────────────┘          └─────────────────────────────────────────────┘
```

---

## 3. Data Flow Diagrams

### 3a. New Full Pipeline (Phases 1-5)

```
                    ┌─────────────────────────────────────────────┐
                    │                  USER INPUT                   │
                    │         "what's the weather in Tokyo?"        │
                    └─────────────────────┬───────────────────────┘
                                          │
                    ┌─────────────────────▼───────────────────────┐
                    │      1. RAG RECALL (EpisodicMemory)          │
                    │         Search for similar past episodes     │
                    │         "weather tokyo" → 3 relevant results │
                    └─────────────────────┬───────────────────────┘
                                          │
                    ┌─────────────────────▼───────────────────────┐
                    │      2. MODEL SELECT (ModelRouter)           │
                    │         ollama list → score models → pick    │
                    │         task="research", model="qwen3.6"     │
                    └─────────────────────┬───────────────────────┘
                                          │
                    ┌─────────────────────▼───────────────────────┐
                    │      3. TASK DECOMPOSE (PlannerAgent)        │
                    │         With RAG context injected:           │
                    │         "Past experiences with weather: ..." │
                    │         Returns step-by-step plan            │
                    └─────────────────────┬───────────────────────┘
                                          │
                    ┌─────────────────────▼───────────────────────┐
                    │      4. EXECUTE (ExecutorAgent + Tools)      │
                    │         weather_tool.execute(city="Tokyo")   │
                    │         → "22°C, clear sky"                 │
                    │         → routing.record(result)            │
                    └─────────────────────┬───────────────────────┘
                                          │
              ┌───────────────────────────┤
              ▼                           ▼
  ┌──────────────────────┐   ┌──────────────────────────┐
  │  5a. VALIDATE         │   │  5b. SELF-HEAL (if err)  │
  │  CriticAgent:         │   │  CriticAgent:             │
  │  "Output valid,       │   │  "Error detected,        │
  │   score 0.9"          │   │   root cause: API down,  │
  └──────────┬───────────┘   │   fix: retry with cache"  │
             │               └──────────┬───────────────┘
             │                          │
             └────────────┬─────────────┘
                          ▼
          ┌──────────────────────────────┐
          │  6. STORE EPISODE            │
          │  EpisodicMemory:             │
          │   save {input, reasoning,    │
          │   tools, output, score}      │
          └──────────────┬───────────────┘
                          │
          ┌──────────────▼───────────────┐
          │  7. RESPOND                  │
          │  "Tokyo is 22°C with clear   │
          │   sky. I've saved this for   │
          │   future reference."         │
          └──────────────────────────────┘
```

### 3b. AutoGen Debate Flow (Phase 2 — Complex Tasks)

```
User: "Design and deploy a REST API for my blog"

  ┌─────────────────────────────────────────────┐
  │  AutoGen Debate (3 rounds max)               │
  │                                              │
  │  Round 1:                                    │
  │    Planner: "Step 1: Choose framework..."     │
  │    Executor: "Flask is simpler for a blog..." │
  │    Critic: "Score 0.3, need database plan"   │
  │                                              │
  │  Round 2:                                    │
  │    Planner: "Refined: Flask + SQLite + ..."  │
  │    Executor: "Better, but add auth..."       │
  │    Critic: "Score 0.7, add error handling"   │
  │                                              │
  │  Round 3:                                    │
  │    Planner: "FINAL PLAN: Flask + SQLite +..."│
  │    Critic: "FINAL_PLAN: accepted, score 0.9" │
  │                                              │
  │  → Consensus reached, plan sent to Executor  │
  └──────────────────────────────────────────────┘
```

### 3c. Command Interface Flow (Phase 4)

```
  User Input
       │
       ├── parse_command()
       │
       ├── Starts with "/"? ─── No ──► Send to NL orchestrator
       │
       │   Yes
       │
       ├── /help      ──► CommandHandler.help_text()
       ├── /agents    ──► AgentRegistry.all()
       ├── /plan ...  ──► PlannerAgent.create_plan()
       ├── /exec ...  ──► PrivilegedShell.execute(confirm=...)
       ├── /memory    ──► EpisodicMemory.search()
       ├── /scores    ──► RoutingEngine.get_rankings()
       ├── /describe  ──► SystemDescriptor.describe()
       └── /status    ──► HardwareMonitor + Memory stats
```

---

## 4. Config-Driven Architecture

```
config.yaml
    │
    ├── features:       27+ toggleable modules (legacy)
    ├── settings:       auto_voice, wake_word, orchestrator version
    ├── models:         LLM, STT, TTS, router (gemma4), coder (qwen3.6)
    │
    ├── ollama:         ★ NEW: url, timeout, auto_pull
    ├── openrouter:     ★ NEW: api_key (optional)
    ├── memory:         ★ NEW: path, compact_episodes, max_episodes
    ├── hardware:       ★ NEW: vram_limit_gb, ram_limit_gb, poll_interval, max_concurrent_models
    │
    ├── agents:         per-agent model overrides, max_steps, vision settings
    └── learning:       auto_start, session_duration, interval_hours, topics
         │
         ▼
core/config.py (singleton)
    ├── .ollama       → {url, model, timeout}
    ├── .router_model → "gemma4:12b"
    ├── .coder_model  → "pleasecech/qwen3.6-plus:latest"
    ├── .features     → dict of bools
    └── .get("agents.models.chat") → "qwen2.5:7b-instruct"
```

---

## 5. Scoring & Learning Loop (Closed Feedback)

```
                    ┌──────────────────────────────┐
                    │     EPISODIC MEMORY           │
                    │  Every interaction stored as  │
                    │  an episode with: input,      │
                    │  reasoning, tools, output,    │
                    │  errors, score                │
                    └──────────┬───────────────────┘
                               │
          ┌────────────────────┤
          ▼                    ▼
┌─────────────────┐  ┌──────────────────┐
│ RAG RETRIEVAL   │  │ ROUTING ENGINE   │
│ Before every    │  │ Tracks per-agent │
│ decision, query │  │ and per-model    │
│ memory for      │  │ success rates    │
│ relevant past   │  │ → picks best     │
│ experiences     │  │   for each task  │
└────────┬────────┘  └────────┬─────────┘
         │                    │
         └──────┬─────────────┘
                ▼
      ┌─────────────────────┐
      │  STRATEGY REFINER   │
      │  Background job:    │
      │  • Refresh models   │
      │  • Analyze failures │
      │  • Compact memory   │
      │  • Generate tools   │
      └─────────────────────┘
```

---

## 6. Request Lifecycle Example (Full Pipeline)

**User says:** *"what's the weather in Tokyo and save a note about it"*

### New Pipeline Path:
```
1. POST /api/v2/chat {"input": "what's the weather in Tokyo and save a note"}

2. RAG RECALL (EpisodicMemory)
   └── search("weather Tokyo note") → 3 past episodes found

3. MODEL SELECT (ModelRouter)
   └── classify_task → "research"
   └── score models → "qwen3.6" best fit (score 3.5)
   └── HardwareMonitor check: VRAM 3.2/8GB → OK to run

4. PLAN (PlannerAgent)
   └── With RAG context: "Past weather queries succeeded ✅"
   └── Returns:
       Step 1: Get weather via weather_tool(city="Tokyo")
       Step 2: Save note via file_tool(write, path="notes/tokyo.txt")
       Step 3: Report results

5. EXECUTE (ExecutorAgent)
   └── Step 1: weather_tool.execute(city="Tokyo")
   │          → "Tokyo: 22°C, clear sky"
   │          → RoutingEngine.record("weather", success=True)
   └── Step 2: file_tool.execute(action="write", path=...)
              → "Written to notes/tokyo.txt"
              → RoutingEngine.record("file", success=True)

6. VALIDATE (CriticAgent)
   └── "Output matches task, score 0.9, no issues"

7. STORE EPISODE (EpisodicMemory)
   └── episode_id: "ep_2026-06-16_a1b2c3d4e5f6"
   └── Fields: input, reasoning_steps, tools, output, score

8. RESPOND
   └── "Tokyo is 22°C with clear skies. I've saved it to notes/tokyo.txt.
        (RAG context: 3 past episodes, model: qwen3.6, score: 0.9)"
```

---

## 7. API Endpoint Map

### Legacy (v1/v2 — preserved)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Serve frontend UI |
| GET | `/health` | System health |
| POST | `/chat` | v1 or v2 chat |
| POST | `/chat/v1` | v1 single-shot |
| POST | `/chat/v2` | v2 agent-based |
| POST | `/process` | Direct module call |
| GET | `/modules` | List modules |
| GET | `/agents` | List v2 agents |
| POST | `/agents/run` | Run specific agent |
| GET/POST | `/learning/*` | Learning engine |
| POST | `/voice/toggle` | Toggle auto-voice |

### Phase 1 — Infrastructure
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/status` | System status (hardware, memory, LLM) |
| POST | `/api/chat` | MVP pipeline (RAG → model → respond) |
| GET | `/api/memory/search` | Semantic memory search |
| GET | `/api/memory/stats` | Memory statistics |
| GET | `/api/memory/failures` | Failure patterns |
| GET | `/api/models` | Available Ollama models |
| POST | `/api/models/validate` | Validate Ollama endpoint |

### Phase 2 — LangGraph + Agents
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v2/chat` | Full pipeline (RAG → plan → execute → validate → store) |
| GET | `/api/v2/agents` | List Phase 2 agents |
| POST | `/api/v2/agents/run` | Run specific agent |
| POST | `/api/v2/debate` | AutoGen debate on complex task |

### Phase 3 — Self-Healing
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v3/validate` | Validate agent output |
| POST | `/api/v3/heal` | Diagnose failure + suggest fix |
| GET | `/api/v3/rankings` | Agent/model rankings |

### Phase 4 — Commands + Privilege
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v4/command` | Execute /command |
| POST | `/api/v4/exec` | Privileged shell execution |
| GET | `/api/v4/audit` | Privilege audit log |

### Phase 5 — Continuous Learning
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v5/refine` | Trigger strategy refinement |
| POST | `/api/v5/generate-tool` | Generate new tool stub |
| GET | `/api/v5/scores` | Utility scores for all agents/actions (ScoringEngine) |

---

## 8. Technology Stack

```
┌────────────────────────────────────────────────────────────────────┐
│                         JANOS STACK                                 │
├────────────────────────────────────────────────────────────────────┤
│  Interface:   FastAPI + Uvicorn + HTML/JS frontend                  │
│  LLM Engine:  Ollama (localhost:11434), OpenRouter (optional)       │
│  Models:      Dynamic — whatever ollama list returns                │
│               Auto-pull on request with user consent                │
│  State Machine: LangGraph 1.2.5 (13-state conditional graph)       │
│  Agent Framework: CrewAI 0.11.2 + AutoGen 0.10.0 (via LLMClient)  │
│  Memory:      EpisodicMemory (ChromaDB vectors + SQLite metadata)  │
│               RoutingEngine (per-agent/model scoring SQLite)        │
│               ShortTermMemory (in-process buffer)                  │
│  Monitoring:  nvidia-smi (GPU) + psutil (RAM/CPU)                  │
│  Privilege:   Sudo-aware shell + audit log + undo log              │
│  Logging:     Structured JSON (core/logger.py) + Markdown logs     │
│  Audio:       edge-tts, ffplay/paplay                              │
│  Browser:     Playwright (optional)                                 │
│  OS:          Linux only (fully migrated from Windows)              │
└────────────────────────────────────────────────────────────────────┘
```

---

## 9. Development Workflow (Makefile)

`Makefile` is the primary entry point for all project operations.

```bash
# First-time setup
make setup              # runs setup.sh: venv + deps + dirs
make install            # pip install -r requirements.txt (venv already exists)
make install-dev        # adds ruff, black, pytest, httpx

# Daily workflow
make dev                # uvicorn main:app --reload  → http://localhost:8000
make chat               # python chat.py --full  (Phase 2-5 pipeline CLI)
make demo               # python demo.py  (standalone, no server needed)
make open               # xdg-open http://localhost:8000

# Health checks (server must be running)
make health             # GET /health
make status             # GET /api/status
make rankings           # GET /api/v3/rankings
make scores             # GET /api/v5/scores
make audit              # runs all four above

# Testing
make test               # test-imports + test-pipeline
make test-imports       # verify all 17 module imports
make test-pipeline      # 13 Phase 3-5 integration checks (no server needed)

# Code quality
make lint               # ruff check
make format             # black in-place
make check              # lint + format-check (CI gate)

# Database
make db-init            # create routing.db + scoring.db tables (idempotent)
make db-reset           # drop + recreate all DBs (with confirmation prompt)

# Ollama
make ollama-check       # curl /api/tags + show installed models
make ollama-pull MODEL=llama3.1:8b

# Phase 5 learning (server must be running)
make refine             # POST /api/v5/refine
make generate-tool CAP="description"

# Cleanup
make clean              # remove __pycache__ + .pyc
make clean-logs         # clear daemon.log
make clean-all          # cache + logs (keeps databases)
```

All targets self-document via `make help`.

### Script files (`scripts/`)

| File | Purpose |
|------|---------|
| `scripts/test_imports.py` | `make test-imports` — verifies 17 core/agent/tool imports |
| `scripts/test_pipeline.py` | `make test-pipeline` — 13 Phase 3-5 integration checks |
| `scripts/db_init.py` | `make db-init` — creates SQLite tables idempotently |

---

## 10. Key Architectural Decisions

| Decision | Rationale |
|----------|-----------|
| **No hardcoded model names** | Models change frequently; `ollama list` determines what's available at runtime |
| **LangGraph for state machine** | Need conditional retry/escalate/fail edges; cleaner than nested if/else |
| **CrewAI for agent roles** | Role-based agents with goals and backstories improve LLM output quality |
| **AutoGen for complex tasks** | Multi-agent debate catches edge cases single agents miss |
| **Episodic memory with RAG** | Every decision gets context from past successes/failures — prevents repeating mistakes |
| **Hardware monitor** | 8GB VRAM / 16GB RAM require active throttling — don't load 2 heavy models simultaneously |
| **Privilege escalation** | Full OS autonomy requires safety — every sudo action logged, destructive ops need --confirm |
| **Log bootstrap** | Historical logs contain unfinished tasks, past errors, key decisions — treat them as bootstrap memory |
| **Strategy refiner** | Continuous background refinement ensures system improves without manual tuning |
