# JANOS v2 — text-only autonomous core

A local, self-healing, self-learning agent system: one supervisor, five
specialist agents, twelve real tools, persistent memory, and a single Ollama
model. No cloud, no API keys, no telemetry.

Lives in `janos/`. Text only — voice, vision and screen control are out of
scope here (see [Deliberately excluded](#deliberately-excluded)).

---

## Quick start

```bash
make janos-setup     # venv + deps + pull qwen2.5:7b-instruct (~4.7 GB)
make janos           # interactive REPL
```

Ollama must be running (`ollama serve`). Everything else is handled.

```bash
make janos-ask Q="how much VRAM is my GPU using?"
make janos-serve                 # HTTP API on :8000
make janos-auto                  # autonomous mode — picks its own goals
make janos-auto-night            # same, in the background
make janos-auto-stop             # ask it to stop after the current cycle
make janos-test                  # full self-test
make janos-test OFFLINE=1        # skip model + network checks
make janos-stats                 # episodes, scores, agent rankings
make janos-lessons               # what it has learned
make janos-tools                 # all tools, including self-written ones
```

---

## How a request is handled

```
                    ┌──────────────────────────────────┐
   your request ───►│           SUPERVISOR             │
                    │  the single point of control     │
                    └──────────────────────────────────┘
                                   │
      ①  recall      similar past episodes + learned lessons → context
      ②  triage      task type, complexity, starting agent
      ③  plan        decompose into agent-assigned steps (complex only)
      ④  delegate    each step runs a real tool loop; agents may hand off
      ⑤  verify      critic scores the answer against the request
      ⑥  self-heal   a failing score re-runs execution with the diagnosis
      ⑦  learn       store the episode, distil a lesson, update rankings
```

Steps ④–⑥ form the loop that makes it autonomous: the supervisor keeps
working until the answer passes verification or stops improving.

### Agents

Each agent is a role, a subset of the toolbox, and a loop that genuinely
executes tools. Agents delegate to each other when a task needs tools they
do not own.

| agent | purpose | tools |
|---|---|---|
| `researcher` | find current facts on the web | web_search, web_fetch, recall_memory, save_note, now, calculate |
| `analyst` | exact computation and data reasoning | calculate, run_python, recall_memory, web_search |
| `operator` | inspect and operate this machine | shell, system_info, list_dir, read_file, now, calculate |
| `engineer` | read, write and run code | read_file, write_file, list_dir, run_python, shell |
| `scribe` | synthesise prose, record notes | recall_memory, save_note, write_file |

### Self-healing

Three layers, innermost first:

1. **Inside a tool loop** — a failed tool returns its error as an observation,
   so the agent reads it and corrects course. Identical repeated calls are
   detected and blocked, which is what stops a small model looping on a
   command that does not work.
2. **After verification** — a score below `min_pass_score` (0.6) re-runs
   execution with the critic's diagnosis injected, up to `max_heal_attempts`.
   A retry is kept only if it scores at least as well as the previous answer,
   and the loop stops early once retries stop improving.
3. **Across sessions** — past failures on similar tasks are pulled into
   context so the same mistake is less likely twice.

### Self-learning

Four things persist in `memory/janos.db` and change future behaviour:

- **Episodes** — every request, plan, tool call, answer and score. Recalled by
  BM25 relevance on the next similar request.
- **Lessons** — one-sentence generalisations distilled after each episode
  ("For hardware questions call system_info rather than parsing nvidia-smi").
  Injected as context on related tasks.
- **Agent rankings** — per-agent, per-task-type running averages. Once an
  agent has ≥3 runs and a ≥0.6 average on a task type, routing prefers it over
  the model's guess.
- **Your feedback** — `POST /feedback` with a 1–5 rating overrides the critic's
  score, and a comment becomes a lesson.

---

## Writing its own tools

When nothing in the toolbox fits, JANOS builds what it needs. `create_tool`
is available to the `engineer` agent, and autonomous mode uses it on its own.

```
purpose ──► search the web
             │
             ├─ fetch the pages the search returned
             ├─ extract candidate endpoints from them
             └─ PROBE each one live, keep only those answering JSON
                          │
             ┌────────────┘
             ▼
        write the module  ──►  validate  ──►  smoke-test  ──►  register
                                  │              │
                          AST + safety scan   separate interpreter,
                          (no eval/exec/       45s timeout, output that
                           pickle/deletion)    reads as a failure is rejected
```

A failed stage is fed back with a specific diagnosis — *that hostname does not
exist, use one from the research*; *that was a redirect, pass
`follow_redirects=True`* — and it retries up to three times.

The web-probing step matters: asked to invent an endpoint from memory, a 7B
model produces plausible hostnames that do not resolve. Grounding it in URLs
verified to answer *right now* is the difference between a tool that works and
one that never did.

Generated tools land in `janos/generated/`, are re-validated and reloaded at
every startup, and show up in `make janos-tools` marked `[self-written]`.

**Note on trust:** generated code is validated and sandbox-smoke-tested, but it
does run in-process afterwards. The scan blocks `eval`, `exec`, `compile`,
`__import__`, `ctypes`, `pickle`, and file-deleting or process-killing calls.
Everything it writes is plain Python in `janos/generated/` — readable, and
deletable if you dislike it.

---

## Autonomous mode

```bash
make janos-auto                       # foreground, a cycle every 5 minutes
make janos-auto INTERVAL=120 CYCLES=20
make janos-auto-night                 # background, logs to workspace/
make janos-auto-stop                  # finish the current cycle, then exit
```

Each cycle it chooses its own goal, rotating through four sources:

| source | what it does |
|---|---|
| `goals` | the next unfinished line of `workspace/goals.md` |
| `repair` | a request that has never once been answered well, retried |
| `research` | a topic it decides is worth learning, researched on the web |
| `extend` | a capability gap it noticed, closed by writing itself a tool |

Leave it work by writing `workspace/goals.md`:

```markdown
- [ ] Find out which Ollama models fit in 8 GB of VRAM and save a comparison
- [ ] Summarise what changed in Python 3.14
```

Items are ticked off once answered successfully. Every cycle is appended to
`workspace/autorun-YYYY-MM-DD.md` with the goal, score, tools used and what
was learned, so there is a readable record in the morning.

Stop it with Ctrl-C or `touch workspace/STOP`; either way it finishes the
cycle in progress rather than dying mid-task.

---

## Why some checks are code, not prompts

A 7B model is confidently wrong about things that are cheap to verify, so
those are settled deterministically rather than left to its judgement:

- **Arithmetic** — a stated percentage is re-derived in Python from the figures
  beside it. `5679 of 8188 = 95%` is caught and forced into a retry regardless
  of how the critic scored it. Checked per clause, so unrelated numbers in a
  spec sheet do not produce false alarms.
- **Claimed side effects** — if the request names a file, verification checks
  the filesystem. An agent will report "saved to models-8gb.md" having written
  nothing, and an LLM reviewer takes its word for it; the file either exists or
  it does not. Without this, autonomous mode ticks goals off for work it never
  did — which is exactly what happened before the check existed.
- **Tool ownership** — whether an agent owns `write_file` is a fact. If the
  request implies writing a file and the chosen agent cannot, the task is
  escalated to a multi-step plan and a step is assigned to an agent that can.
- **Derived values in tools** — `system_info` computes its own percentages from
  the numbers it prints, so its output is never internally inconsistent and the
  model is never asked to divide.
- **Loop detection** — a repeated identical tool call is recognised and refused
  with the previous result, instead of burning the turn budget.

---

## Tools

| tool | what it does |
|---|---|
| `web_search` | DuckDuckGo search (stdlib HTML parsing, no scraping stack) |
| `web_fetch` | download a URL and extract readable text |
| `read_file` / `write_file` / `list_dir` | filesystem access |
| `calculate` | exact arithmetic via a restricted AST evaluator — never `eval()` |
| `run_python` | run a snippet in a fresh interpreter, with timeout |
| `shell` | bash commands, with timeout and a destructive-command blocklist |
| `system_info` | CPU, RAM, disk, GPU with self-consistent percentages |
| `now` | current local date and time |
| `recall_memory` | search past episodes |
| `save_note` | persist a note |
| `create_tool` | research, write, validate and register a brand-new tool |

Relative paths resolve inside `workspace/`. `shell` refuses disk-wiping,
power and account-modification commands, and honours `allow_shell: false`.

---

## HTTP API

```bash
make janos-serve
```

| endpoint | purpose |
|---|---|
| `GET /health` | model, agents, tools, memory status |
| `POST /chat` | `{"input": "..."}` → full turn record |
| `POST /chat/stream` | same, streamed as server-sent events |
| `POST /feedback` | `{"episode_id": "...", "rating": 1-5, "comment": "..."}` |
| `GET /agents`, `/tools` | roster and tool schemas |
| `GET /memory/stats`, `/memory/recent`, `/memory/lessons` | memory |
| `GET /rankings` | which agent performs best per task type |

---

## Configuration

`janos.yaml`, or any value as `JANOS_<NAME>` in the environment (env wins).

| key | default | meaning |
|---|---|---|
| `model` | `qwen2.5:7b-instruct` | the one model used for everything |
| `max_steps` | 8 | most plan steps per request |
| `max_heal_attempts` | 2 | retries after failed verification |
| `agent_max_turns` | 6 | tool-loop turns inside one agent |
| `min_pass_score` | 0.6 | score needed to accept an answer |
| `recall_k` / `lesson_k` | 4 / 4 | episodes and lessons injected as context |
| `learn` | true | distil lessons from episodes |
| `allow_shell` | true | set false to remove shell access entirely |

### Model choice

`qwen2.5:7b-instruct` was picked for this machine (RTX 4060, 8 GB VRAM): it
loads fully onto the GPU at ~5.5 GB and follows JSON schemas reliably, which
the supervisor depends on for every routing, planning and verification
decision. Smaller GPU → `qwen2.5:3b-instruct`; more VRAM → `qwen2.5:14b-instruct`.

---

## Dependencies

Six packages (`requirements-janos.txt`): httpx, fastapi, uvicorn, pydantic,
psutil, PyYAML.

Retrieval is SQLite **FTS5/BM25** and HTML parsing is `html.parser`, both
standard library. There is no vector database, no embedding model and no
scraping stack — so the only download JANOS needs is the one LLM.

---

## Spotify playback by name

"play travis scott" searches Spotify and starts the first matching track. Without keys it only opens Spotify's search page and says so.

1. Create an app at <https://developer.spotify.com/dashboard>; any redirect URI works, e.g. `http://127.0.0.1:8000/cb`.
2. Put the client id on line 1 and the client secret on line 2 of `memory/.spotify_key`.
3. `chmod 600 memory/.spotify_key` (a group/world-readable file is refused).

Limits: needs the Spotify desktop app, logged in; free accounts may refuse playback started from outside the app (JANOS then reports what Spotify says, not "playing"). The file is git-ignored; the secret is never logged or returned.

## What it can and cannot reach on the internet

**Works:** DuckDuckGo search (HTML endpoint plus the instant-answer API),
fetching and extracting text from any public page, and calling public JSON
APIs — including ones it discovers and verifies at tool-writing time.

**Does not work, by design or by their design:**

| target | why |
|---|---|
| ChatGPT / Claude / Gemini web UIs | require a logged-in account, block automation, and are against their terms. Driving them would also need a real browser, which is not installed. |
| Google search results | actively blocks scraping; returns consent walls and CAPTCHAs to non-browser clients. DuckDuckGo serves the same purpose without that. |
| anything needing a login | JANOS holds no credentials and is not asked to. |

The practical consequence is small: asking another chatbot is a way of doing
web research, and JANOS does the research directly. When it does not know
something — including how to build a tool it has never built — it searches,
reads the pages, verifies what it found, and keeps the result. That is the
same loop, without borrowing someone else's assistant.

---

## Deliberately excluded

Text only, as scoped. The legacy multimodal stack (`modules/`, `agents/`,
`core/`, `main.py`) is untouched and still present, but it is not what runs
here — it depends on `chromadb`, `crewai`, `langgraph`, `pyautogui`,
`playwright` and others that have no working install on this machine's
Python 3.14.

Not included: voice (STT/TTS), vision and screen reading, wake word, face
recognition, browser automation, Windows service wrappers.

The most important structural difference from the legacy pipeline: that one
asked the model to *describe* using a tool and stored `tool_usage=[]` — no
tool was ever executed. Here, every tool call in the trace really ran.

---

## Layout

```
janos/
  config.py       one config object; janos.yaml + JANOS_* env
  llm.py          Ollama client; schema-constrained JSON with repair
  memory.py       episodes, lessons, rankings — SQLite + FTS5
  tools.py        twelve text-only tools that actually execute
  agents.py       specialist agents and the real tool loop
  supervisor.py   the single control loop + deterministic guards
  forge.py        self-extension: research → write → validate → register
  auto.py         autonomous mode: picks its own goals and learns
  server.py       FastAPI
  cli.py          REPL
  selftest.py     the self-test suite
  generated/      tools JANOS wrote for itself
```
