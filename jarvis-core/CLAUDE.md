# JANOS (project instructions)

Local autonomous agent system. Code is in `janos/`; docs in `../docs/`; history in `../Archive/`.
Global engineering rules still apply; this file adds only JANOS specifics.

## Run and test
- Always use `.venv/bin/python` (bare `python3` may resolve to another venv without httpx).
- `make janos-test` is the check. Use `OFFLINE=1` to skip model and network. Baseline: 113/113 passing.
- Model is `qwen2.5:7b-instruct` via Ollama; it is the only model. Do not change it casually.

## Rules
- Checkable facts belong in Python, not in prompts. If a check is decidable in code, put it in code.
- Control flow uses schema-constrained JSON (`LLM.chat_json`). Request code as fenced text, never as a JSON string.
- Two self-written module kinds: skills (`janos/generated/*.py`, via `forge.py`) and playbooks (`janos/playbooks/*.json`, via `playbooks.py`). Do not add a third path.
- `shell`, `run_python` and skill smoke tests run in bubblewrap (`janos/sandbox.py`). Never bypass it; prove any change with `JANOS_SANDBOX=false` making the sandbox checks fail.
- The server binds `127.0.0.1` and needs the token in `memory/api_token`. Never commit tokens or `.brave_key`.
- The routing policy (`janos/policy.py`) never bypasses `_required_tools` masking. Prove policy changes with the multi-seed selftest check, never a single seed.
- Legacy v1 (`core/ modules/ agents/ tools/ main.py`) is dead code. Do not edit or import it.

## Search
Brave (if key) → Yahoo → DuckDuckGo → Wikipedia. Google/Bing/DDG block plain clients; do not add bot-detection evasion.
