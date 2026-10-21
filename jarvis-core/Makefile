# ============================================================
#  JAN — Joint Autonomous Neural Agent
#  Makefile — primary entry point for all project operations
#
#  Usage:  make <target>
#  Help:   make help
#
#  Prerequisites: Python 3.10+, pip, ollama
# ============================================================

# --- Configuration (override on command line: make dev PORT=9000) ---
PYTHON   := python3
VENV     := venv
BIN      := $(VENV)/bin
PY       := $(BIN)/python
PIP      := $(BIN)/pip
UVICORN  := $(BIN)/uvicorn
HOST     := 0.0.0.0
# JANOS agents have shell access: loopback only unless you override JANOS_HOST.
JANOS_HOST ?= 127.0.0.1
PORT     := 8000
MEMORY   := memory

# Detect OS for browser open command
UNAME := $(shell uname -s 2>/dev/null || echo Unknown)
ifeq ($(UNAME),Linux)
    OPEN := xdg-open
else ifeq ($(UNAME),Darwin)
    OPEN := open
else
    OPEN := echo "Open browser at"
endif

.DEFAULT_GOAL := help
.PHONY: help \
        janos janos-setup janos-serve janos-test janos-ask \
        janos-employee janos-stats janos-lessons janos-reset janos-tools \
        janos-auto janos-auto-night janos-auto-stop \
        setup install install-dev install-optional \
        dev prod start \
        chat chat-v1 demo open \
        health status rankings scores audit \
        test test-imports test-pipeline test-audit \
        lint format format-check check \
        db-init db-reset \
        ollama-check ollama-list ollama-pull \
        refine generate-tool pull-model \
        logs-view logs-tail \
        clean clean-cache clean-logs clean-memory clean-all \
        docs _venv-check


# ============================================================
#  JANOS v2 — text-only autonomous core (janos/)
#  Self-contained: its own venv, its own deps, one Ollama model.
# ============================================================

JVENV  := .venv
JPY    := $(JVENV)/bin/python
JMODEL := qwen2.5:7b-instruct

janos-setup: ## JANOS: create .venv, install deps, pull the model
	@echo "  Creating $(JVENV) ..."
	@$(PYTHON) -m venv $(JVENV)
	@$(JVENV)/bin/pip install --quiet --upgrade pip
	@$(JVENV)/bin/pip install --quiet -r requirements-janos.txt
	@echo "  Pulling $(JMODEL) (~4.7 GB, skipped if present) ..."
	@ollama list 2>/dev/null | grep -q "$(JMODEL)" || ollama pull $(JMODEL)
	@echo "  Ready. Run: make janos"

janos: _janos-check ## JANOS: interactive REPL
	@$(JPY) -m janos.cli

janos-ask: _janos-check ## JANOS: one-shot question — make janos-ask Q="what is my GPU?"
	@$(JPY) -m janos.cli $(Q)

janos-serve: _janos-check ## JANOS: HTTP API on $(HOST):$(PORT)
	@$(JVENV)/bin/uvicorn janos.server:app --host $(JANOS_HOST) --port $(PORT)

janos-test: _janos-check ## JANOS: self-test — add OFFLINE=1 to skip model/network
	@$(JPY) -m janos.selftest $(if $(OFFLINE),--offline,)

janos-employee: _janos-check ## JANOS: have OpenCode do a coding task on a new branch — TASK="..." [REPO=path] [TEST="cmd"]
	@$(JPY) -m janos.employee "$(TASK)" $(if $(REPO),--repo "$(REPO)",) $(if $(TEST),--test "$(TEST)",)

janos-stats: _janos-check ## JANOS: memory statistics and agent rankings
	@$(JPY) -c "from janos.config import Config; from janos.memory import Memory; \
	m=Memory(Config.load().db_path); s=m.stats(); \
	print(); [print(f'  {k:<14} {v}') for k,v in s.items() if k!='tools']; \
	print('\n  agent rankings'); \
	[print(f\"    {r['agent']:<12} {r['task_type']:<14} {r['runs']:>3} runs  avg {r['avg_score']}\") for r in m.rankings()]; \
	print()"

janos-lessons: _janos-check ## JANOS: show everything it has learned
	@$(JPY) -c "from janos.config import Config; from janos.memory import Memory; \
	m=Memory(Config.load().db_path); ls=m.all_lessons(); \
	print(); print(f'  {len(ls)} lesson(s)'); \
	[print(f\"    [{l['task_type']}] {l['lesson']}\") for l in ls]; print()"

janos-auto: _janos-check ## JANOS: autonomous mode — INTERVAL=300 CYCLES=0 (0 = unbounded)
	@$(JPY) -m janos.auto --interval $(or $(INTERVAL),300) --cycles $(or $(CYCLES),0)

janos-auto-night: _janos-check ## JANOS: run autonomously in the background, logging to workspace/
	@nohup $(JPY) -m janos.auto --interval 300 --quiet \
		> $(MEMORY)/../workspace/autorun.out 2>&1 & echo $$! > /tmp/janos-auto.pid
	@echo "  Running in background (pid $$(cat /tmp/janos-auto.pid))."
	@echo "  Watch:  tail -f workspace/autorun-$$(date +%F).md"
	@echo "  Stop:   make janos-auto-stop"

janos-voice-setup: _janos-check ## JANOS: install voice extras and download speech models (~0.6 GB)
	@$(JVENV)/bin/pip install -q -r requirements-voice.txt
	@mkdir -p memory/models && cd memory/models && for f in kokoro-v1.0.int8.onnx voices-v1.0.bin; do \
	  [ -s $$f ] || curl -sSL -o $$f https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/$$f; done
	@echo "voice ready: make janos-voice"

janos-voice: _janos-check ## JANOS: talk to it — say "Hey Jarvis" (TEXT=1 to type instead)
	@$(JVENV)/bin/python -m janos.voice $(if $(TEXT),--text,)

janos-auto-stop: ## JANOS: stop a background autonomous run
	@touch workspace/STOP && echo "  STOP file created — it will finish the current cycle and exit."

janos-tools: _janos-check ## JANOS: list all tools, including self-written ones
	@$(JPY) -c "from janos.config import Config; from janos.supervisor import Supervisor; \
	s=Supervisor(Config.load()); print(); print(s.toolbox.describe()); \
	g=s.forge.generated_names(); \
	print(f'\n  self-written: {\", \".join(g) if g else \"(none yet)\"}\n'); s.close()"

janos-reset: ## JANOS: erase all episodes and lessons (IRREVERSIBLE)
	@printf "  Delete all JANOS memory? [y/N] " && read a && [ "$$a" = "y" ] || exit 1
	@rm -f $(MEMORY)/janos.db && echo "  Memory cleared."

_janos-check:
	@test -x $(JPY) || { echo "  $(JVENV) missing — run: make janos-setup"; exit 1; }


# ============================================================
#  HELP
# ============================================================

help: ## Show this help
	@echo ""
	@echo "  JAN — Joint Autonomous Neural Agent"
	@echo "  ====================================="
	@echo ""
	@echo "  JANOS v2  (text-only core — start here)"
	@printf "  %-30s %s\n" "make janos-setup"              "One-time: venv, deps, and pull the model"
	@printf "  %-30s %s\n" "make janos"                    "Interactive REPL"
	@printf "  %-30s %s\n" "make janos-ask Q=\"...\""        "Ask one question and exit"
	@printf "  %-30s %s\n" "make janos-serve"              "HTTP API on port $(PORT)"
	@printf "  %-30s %s\n" "make janos-test"               "Self-test (add OFFLINE=1 to skip the model)"
	@printf "  %-30s %s\n" "make janos-auto"               "Autonomous mode — picks its own goals, learns"
	@printf "  %-30s %s\n" "make janos-auto-night"         "Autonomous in the background (make janos-auto-stop)"
	@printf "  %-30s %s\n" "make janos-stats"              "Episodes, scores and agent rankings"
	@printf "  %-30s %s\n" "make janos-lessons"            "What JANOS has learned so far"
	@printf "  %-30s %s\n" "make janos-tools"              "All tools, including ones it wrote itself"
	@echo ""
	@echo "  SETUP  (legacy multimodal stack)"
	@printf "  %-30s %s\n" "make setup"                    "Full first-time setup (venv + deps + dirs)"
	@printf "  %-30s %s\n" "make install"                  "Install Python dependencies"
	@printf "  %-30s %s\n" "make install-dev"              "Install dev tools (ruff, black, pytest)"
	@printf "  %-30s %s\n" "make install-optional"         "Install optional extras (wake word, face, playwright)"
	@echo ""
	@echo "  SERVER"
	@printf "  %-30s %s\n" "make dev"                      "Dev server — port $(PORT), auto-reload"
	@printf "  %-30s %s\n" "make prod"                     "Production server — 2 workers, no reload"
	@printf "  %-30s %s\n" "make start"                    "Alias for: make dev"
	@echo ""
	@echo "  CHAT / CLI"
	@printf "  %-30s %s\n" "make chat"                     "Server CLI — Phase 2-5 full pipeline (server must run)"
	@printf "  %-30s %s\n" "make chat-v1"                  "Server CLI — legacy v1 orchestrator"
	@printf "  %-30s %s\n" "make demo"                     "Standalone terminal demo (no server needed)"
	@printf "  %-30s %s\n" "make open"                     "Open browser UI at http://localhost:$(PORT)"
	@echo ""
	@echo "  HEALTH / STATUS  (server must be running)"
	@printf "  %-30s %s\n" "make health"                   "GET /health — phase status + agent list"
	@printf "  %-30s %s\n" "make status"                   "GET /api/status — hardware + memory + LLM"
	@printf "  %-30s %s\n" "make rankings"                 "GET /api/v3/rankings — agent/model scores"
	@printf "  %-30s %s\n" "make scores"                   "GET /api/v5/scores — ScoringEngine utility scores"
	@printf "  %-30s %s\n" "make audit"                    "Run all four health checks in sequence"
	@echo ""
	@echo "  TESTING"
	@printf "  %-30s %s\n" "make test"                     "Run all tests (imports + pipeline)"
	@printf "  %-30s %s\n" "make test-imports"             "Verify all module imports load cleanly"
	@printf "  %-30s %s\n" "make test-pipeline"            "Run Phase 3-5 integration audit (13 checks)"
	@echo ""
	@echo "  LINT / FORMAT"
	@printf "  %-30s %s\n" "make lint"                     "Lint with ruff (needs make install-dev)"
	@printf "  %-30s %s\n" "make format"                   "Format with black (needs make install-dev)"
	@printf "  %-30s %s\n" "make check"                    "lint + format-check (CI gate)"
	@echo ""
	@echo "  DATABASE"
	@printf "  %-30s %s\n" "make db-init"                  "Create SQLite tables — idempotent"
	@printf "  %-30s %s\n" "make db-reset"                 "Drop + recreate all DBs (CAUTION: data loss)"
	@echo ""
	@echo "  OLLAMA"
	@printf "  %-30s %s\n" "make ollama-check"             "Check Ollama is running + list models"
	@printf "  %-30s %s\n" "make ollama-list"              "List installed models via ollama CLI"
	@printf "  %-30s %s\n" "make ollama-pull MODEL=name"   "Pull a specific model"
	@echo ""
	@echo "  PHASE 5 — LEARNING  (server must be running)"
	@printf "  %-30s %s\n" "make refine"                   "POST /api/v5/refine — strategy refinement cycle"
	@printf "  %-30s %s\n" "make generate-tool CAP=desc"   "Generate a new tool stub for a capability"
	@printf "  %-30s %s\n" "make pull-model MODEL=name"    "Pull model via JANOS API"
	@echo ""
	@echo "  LOGS"
	@printf "  %-30s %s\n" "make logs-view"                "Show last 50 lines of daemon log"
	@printf "  %-30s %s\n" "make logs-tail"                "Live-tail daemon log (Ctrl+C to stop)"
	@echo ""
	@echo "  CLEANUP"
	@printf "  %-30s %s\n" "make clean"                    "Remove __pycache__ and .pyc files"
	@printf "  %-30s %s\n" "make clean-logs"               "Clear daemon log content"
	@printf "  %-30s %s\n" "make clean-memory"             "Reset all SQLite DBs (IRREVERSIBLE)"
	@printf "  %-30s %s\n" "make clean-all"                "cache + logs cleanup (keeps DBs)"
	@echo ""
	@echo "  DOCS"
	@printf "  %-30s %s\n" "make docs"                     "View docs/ARCHITECTURE.md in terminal pager"
	@echo ""


# ============================================================
#  SETUP & INSTALL
# ============================================================

setup: ## Full first-time setup via setup.sh
	bash setup.sh

install: _venv-check ## Install Python dependencies from requirements.txt
	@echo "[JAN] Installing dependencies..."
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	@echo "[JAN] Done. Run 'make dev' to start."

install-dev: _venv-check ## Install dev tools (ruff, black, pytest, pytest-asyncio)
	@echo "[JAN] Installing dev tools..."
	$(PIP) install ruff black pytest pytest-asyncio httpx
	@echo "[JAN] Dev tools ready. Use: make lint, make format, make test"

install-optional: _venv-check ## Install optional extras interactively
	@echo "[JAN] Installing optional packages..."
	$(PIP) install pyaudio openwakeword || echo "  wake word: skipped (needs portaudio)"
	$(PIP) install face-recognition resemblyzer || echo "  face recognition: skipped (needs cmake+dlib)"
	$(PIP) install playwright && $(BIN)/playwright install chromium || echo "  playwright: skipped"
	$(PIP) install yt-dlp
	@echo "[JAN] Optional packages done."

_venv-check: ## (internal) Guard: ensure venv exists before running any target
	@test -d $(VENV) || { \
	    echo "[!] venv/ not found."; \
	    echo "    Run: make setup   (full first-time setup)"; \
	    echo "    Or:  python3 -m venv venv && make install"; \
	    exit 1; \
	}


# ============================================================
#  SERVER
# ============================================================

dev: _venv-check ## Start development server with auto-reload
	@echo "[JAN] Dev server → http://$(HOST):$(PORT)  (Ctrl+C to stop)"
	$(UVICORN) main:app --host $(HOST) --port $(PORT) --reload

prod: _venv-check ## Start production server (2 workers, no reload)
	@echo "[JAN] Production server → http://$(HOST):$(PORT)"
	$(UVICORN) main:app --host $(HOST) --port $(PORT) --workers 2

start: dev ## Alias for: make dev


# ============================================================
#  CHAT / CLI
# ============================================================

chat: _venv-check ## Server CLI — Phase 2-5 full pipeline (server must be running)
	$(PY) chat.py --full

chat-v1: _venv-check ## Server CLI — legacy v1 orchestrator
	$(PY) chat.py --v1

demo: _venv-check ## Standalone terminal demo (no server required)
	$(PY) demo.py

open: ## Open browser UI
	$(OPEN) http://localhost:$(PORT) 2>/dev/null || true


# ============================================================
#  HEALTH / STATUS  (server must be running)
# ============================================================

health: ## GET /health — all phase status
	@curl -sf http://localhost:$(PORT)/health | $(PY) -m json.tool \
	    || echo "[!] Server not responding — run: make dev"

status: ## GET /api/status — hardware + memory + LLM health
	@curl -sf http://localhost:$(PORT)/api/status | $(PY) -m json.tool \
	    || echo "[!] Server not responding."

rankings: ## GET /api/v3/rankings — agent and model score rankings
	@curl -sf http://localhost:$(PORT)/api/v3/rankings | $(PY) -m json.tool \
	    || echo "[!] Server not responding."

scores: ## GET /api/v5/scores — ScoringEngine utility scores
	@curl -sf http://localhost:$(PORT)/api/v5/scores | $(PY) -m json.tool \
	    || echo "[!] Server not responding."

audit: ## Run all four health checks in sequence
	@echo "\n=== /health ==="; $(MAKE) -s health; \
	 echo "\n=== /api/status ==="; $(MAKE) -s status; \
	 echo "\n=== /api/v3/rankings ==="; $(MAKE) -s rankings; \
	 echo "\n=== /api/v5/scores ==="; $(MAKE) -s scores


# ============================================================
#  TESTING
# ============================================================

test: test-imports test-pipeline ## Run all tests

test-imports: _venv-check ## Verify all module/core imports load without errors
	@echo "[JAN] Verifying imports..."
	PYTHONPATH=. $(PY) scripts/test_imports.py

test-pipeline: _venv-check ## Run Phase 3-5 integration audit (13 checks)
	@echo "[JAN] Running Phase 3-5 pipeline audit..."
	PYTHONPATH=. $(PY) scripts/test_pipeline.py

test-audit: test-pipeline ## Alias for: make test-pipeline


# ============================================================
#  LINT / FORMAT
# ============================================================

lint: _venv-check ## Lint with ruff (run 'make install-dev' first)
	@test -f $(BIN)/ruff || { echo "[!] ruff not installed. Run: make install-dev"; exit 1; }
	$(BIN)/ruff check core/ agents/ tools/ modules/ main.py chat.py

format: _venv-check ## Format with black in-place (run 'make install-dev' first)
	@test -f $(BIN)/black || { echo "[!] black not installed. Run: make install-dev"; exit 1; }
	$(BIN)/black core/ agents/ tools/ modules/ main.py chat.py

format-check: _venv-check ## Check formatting without applying changes (CI-safe)
	@test -f $(BIN)/black || { echo "[!] black not installed. Run: make install-dev"; exit 1; }
	$(BIN)/black --check core/ agents/ tools/ modules/ main.py chat.py

check: lint format-check ## Run lint + format-check (CI gate — exits non-zero on any issue)


# ============================================================
#  DATABASE
# ============================================================

db-init: _venv-check ## Create all SQLite DB tables — idempotent, safe to run anytime
	@echo "[JAN] Initializing databases..."
	PYTHONPATH=. $(PY) scripts/db_init.py

db-reset: ## Drop and recreate all SQLite databases (IRREVERSIBLE — all scores + history lost)
	@echo "[!] This will DELETE: memory/routing.db, memory/scoring.db, memory/episodic.db"
	@printf "    Type 'yes' to confirm: "; read c && [ "$$c" = "yes" ] || { echo "Aborted."; exit 1; }
	rm -f $(MEMORY)/routing.db $(MEMORY)/scoring.db $(MEMORY)/episodic.db $(MEMORY)/long_term.db
	$(MAKE) -s db-init
	@echo "[JAN] Databases reset."


# ============================================================
#  OLLAMA
# ============================================================

ollama-check: ## Check Ollama is running and show installed models
	@echo "[JAN] Checking Ollama at http://localhost:11434..."
	@curl -sf http://localhost:11434/api/tags | $(PY) -c \
	    "import sys,json; d=json.load(sys.stdin); ms=[m['name'] for m in d.get('models',[])]; \
	     print(f'  Running — {len(ms)} model(s):'); [print(f'    • {m}') for m in ms]" \
	    2>/dev/null || echo "  [!] Ollama not running. Start it: ollama serve"

ollama-list: ## List installed Ollama models via CLI
	@ollama list 2>/dev/null || echo "[!] ollama CLI not found or not running."

ollama-pull: ## Pull an Ollama model: make ollama-pull MODEL=llama3.1:8b
ifndef MODEL
	@echo "[!] Usage: make ollama-pull MODEL=<model-name>"
	@echo "    Example: make ollama-pull MODEL=llama3.1:8b"
else
	ollama pull $(MODEL)
endif


# ============================================================
#  PHASE 5 — CONTINUOUS LEARNING  (server must be running)
# ============================================================

refine: ## POST /api/v5/refine — trigger strategy refinement cycle
	@curl -sf -X POST http://localhost:$(PORT)/api/v5/refine | $(PY) -m json.tool \
	    || echo "[!] Server not responding — run: make dev"

generate-tool: ## Generate a new tool stub: make generate-tool CAP="send email via SMTP"
ifndef CAP
	@echo "[!] Usage: make generate-tool CAP=\"capability description\""
	@echo "    Example: make generate-tool CAP=\"read RSS feeds\""
else
	@curl -sf -X POST "http://localhost:$(PORT)/api/v5/generate-tool?capability=$(CAP)" \
	    | $(PY) -m json.tool || echo "[!] Server not responding."
endif

pull-model: ## Pull model via JANOS API: make pull-model MODEL=llama3.1:8b
ifndef MODEL
	@echo "[!] Usage: make pull-model MODEL=<model-name>"
else
	@curl -sf -X POST "http://localhost:$(PORT)/api/v4/command?input=/pull $(MODEL)" \
	    | $(PY) -m json.tool || echo "[!] Server not responding."
endif


# ============================================================
#  LOGS
# ============================================================

logs-view: ## Show last 50 lines of daemon log
	@tail -n 50 $(MEMORY)/logs/daemon.log 2>/dev/null \
	    || echo "[!] No daemon log at $(MEMORY)/logs/daemon.log"

logs-tail: ## Live-tail daemon log (Ctrl+C to stop)
	@tail -f $(MEMORY)/logs/daemon.log 2>/dev/null \
	    || echo "[!] No daemon log at $(MEMORY)/logs/daemon.log"


# ============================================================
#  CLEANUP
# ============================================================

clean: ## Remove __pycache__ directories and .pyc files
	@find . -path ./$(VENV) -prune -o -type d -name __pycache__ -print -exec rm -rf {} + 2>/dev/null; true
	@find . -path ./$(VENV) -prune -o -name "*.pyc" -print -exec rm -f {} + 2>/dev/null; true
	@echo "[JAN] Cache cleaned."

clean-cache: clean ## Alias for: make clean

clean-logs: ## Clear daemon log content (keeps the file)
	@truncate -s 0 $(MEMORY)/logs/daemon.log 2>/dev/null || true
	@echo "[JAN] Daemon log cleared."

clean-memory: db-reset ## Reset all SQLite databases (delegates to db-reset with confirmation)

clean-all: clean clean-logs ## Remove caches and clear logs (keeps databases)
	@echo "[JAN] Full clean done."


# ============================================================
#  DOCS
# ============================================================

docs: ## View docs/ARCHITECTURE.md in terminal pager
	@less ../docs/ARCHITECTURE.md 2>/dev/null || more ../docs/ARCHITECTURE.md 2>/dev/null || cat ../docs/ARCHITECTURE.md
