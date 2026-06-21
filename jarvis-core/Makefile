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
#  HELP
# ============================================================

help: ## Show this help
	@echo ""
	@echo "  JAN — Joint Autonomous Neural Agent"
	@echo "  ====================================="
	@echo ""
	@echo "  SETUP"
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
	@printf "  %-30s %s\n" "make docs"                     "View ARCHITECTURE.md in terminal pager"
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

docs: ## View ARCHITECTURE.md in terminal pager
	@less ARCHITECTURE.md 2>/dev/null || more ARCHITECTURE.md 2>/dev/null || cat ARCHITECTURE.md
