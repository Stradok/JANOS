# JANOS Architecture

How JANOS v2 is built. For the reasoning behind these choices see
[SYSTEM_DESIGN.md](SYSTEM_DESIGN.md). Everything here describes the code in
`jarvis-core/janos/`.

## 1. Overview

JANOS is a single Python process built around one **Supervisor**. The supervisor
turns a request into a plan, hands steps to specialist **agents**, checks the result,
retries when the result is poor, and records what happened so later requests
benefit. All reasoning goes to one local model through **Ollama**.

```
                 ┌───────────── entry points ──────────────┐
                 │  cli.py (REPL)   server.py (HTTP)       │
                 │  auto.py (autonomous loop)              │
                 └───────────────────┬─────────────────────┘
                                     ▼
                      ┌─────────────────────────────┐
                      │  Supervisor  supervisor.py  │
                      └──┬───────┬───────┬───────┬──┘
              recall/learn│  plan │ delegate│ extend│
                         ▼       ▼        ▼       ▼
                   ┌────────┐ ┌───────┐ ┌─────────────┐ ┌──────────────────┐
                   │ Memory │ │  LLM  │ │ AgentRunner │ │ ToolForge        │
                   │ SQLite │ │ llm.py│ │ agents.py   │ │ PlaybookForge    │
                   │ FTS5   │ │Ollama │ └──────┬──────┘ │ forge/playbooks  │
                   └────────┘ └───────┘        ▼        └────────┬─────────┘
                                          ┌─────────┐            │ registers
                                          │ Toolbox │◄───────────┘
                                          │tools.py │
                                          └─────────┘
```

## 2. Modules

| Module | Responsibility |
|---|---|
| `supervisor.py` | The control loop. Owns triage, planning, execution, verification, healing, learning, and registration of self-written modules. |
| `agents.py` | Defines the five agents and `AgentRunner`, the tool loop each agent runs. |
| `tools.py` | `Toolbox` and the twelve built-in tools. Normalises every result to a string and never raises into the agent loop. |
| `forge.py` | **Skills.** Authors, validates, smoke-tests and registers new Python tools. |
| `playbooks.py` | **Playbooks.** Authors, validates and registers JSON tool chains. |
| `policy.py` | Learned routing: a small numpy Q-network that picks the agent and plan/direct mode, trained on rewards. State in `memory/policy.npz`. |
| `memory.py` | SQLite store for episodes, lessons, agent statistics and tool statistics, with FTS5 search. |
| `llm.py` | Ollama client. `chat` for text, `chat_json` for schema-constrained JSON with retry. Tracks token usage. |
| `auto.py` | Autonomous loop: chooses goals, runs them through the supervisor, logs each cycle. |
| `server.py` | FastAPI application with bearer-token authentication and host checking. |
| `sandbox.py` | Builds the bubblewrap command line that `shell`, `run_python` and the forge smoke test run inside. |
| `cli.py` | Interactive REPL and one-shot commands. |
| `voice.py` | Voice loop: wake word, end-of-turn detection, speech-to-text, JANOS, spoken reply. |
| `config.py` | Single configuration source: `janos.yaml`, overridden by `JANOS_*` environment variables. |
| `selftest.py` | The test suite (`make janos-test`). |

## 3. Request lifecycle

`Supervisor.handle(task)` is the whole pipeline:

1. **Recall** (`_context`). Retrieves similar past episodes and learned lessons by BM25
   search and formats them as context (`recall_k` and `lesson_k`, both 4 by default).
2. **Triage** (`_triage`). One schema-constrained model call returns `task_type`,
   `complexity` (`simple` or `complex`) and a starting `agent`. The learned policy (section 11) may override the
   suggestion; its choices are masked to agents that own the tools `_required_tools`
   implies (arithmetic expressions require `calculate`). With `rl_policy: false`, Memory's
   proven-agent record for that task type overrides instead. `_required_tools` then
   applies the deterministic capability check (see section 6).
3. **Plan** (`_plan`). For complex tasks, the model decomposes the request into
   `{step, agent}` pairs, capped at `max_steps`. `_repair_plan` fixes assignments that
   give a step to an agent which lacks the required tool.
4. **Delegate** (`_execute`). Each step runs through `AgentRunner.run`, which loops
   for up to `agent_max_turns`: the agent emits a tool call, the toolbox runs it, the
   output returns as an observation, repeat until the agent answers or hands off.
5. **Synthesise** (`_synthesise`). Findings from all steps become one answer.
6. **Verify** (`_verify`). Deterministic checks run first: `check_arithmetic` and
   `_missing_files`. The model critic then scores the answer using the tool log as
   evidence. Deterministic findings override the critic.
7. **Self-heal.** While the score is below `min_pass_score` and attempts remain, execution
   re-runs with the critic's diagnosis and recalled past mistakes injected. A retry is
   adopted only if its score is at least as high; if it is not strictly better, the loop stops.
8. **Learn.** `Memory.remember` stores the episode, `record_agent` updates rankings, the routing policy is updated with the reward
   (section 11), and `_distil` extracts a one-sentence lesson (skipped for small talk that used no tools).

`handle` returns a `Turn` carrying the answer, score, plan, tool calls, errors, heal
attempts and lesson. Events are emitted at each stage for the streaming API.

## 4. Agents and tools

| Agent | Purpose | Tools |
|---|---|---|
| `researcher` | current facts from the web | web_search, web_fetch, recall_memory, save_note, now, calculate |
| `analyst` | exact computation | calculate, run_python, recall_memory, web_search |
| `operator` | inspect and operate this machine | shell, system_info, list_dir, read_file, now, calculate |
| `engineer` | code and files; builds new modules | read_file, write_file, list_dir, run_python, shell, create_tool, create_playbook |
| `scribe` | prose and notes | recall_memory, save_note, write_file |

Agents delegate to each other when a task needs tools they do not own. The runner
detects an identical repeated tool call and refuses it, which stops a small model
retrying the same broken command until its turn budget is spent.

Tools are declared as `Tool(name, description, params, run, danger)`. Self-written skills
and playbooks register through the same interface, so agents call them like any other tool.

## 5. Self-extension

JANOS has two module types, chosen by whether the capability needs new code.

### Skills — `forge.py` (Python)

`ToolForge.create(purpose)`:

1. **Research.** `web_search` and `web_fetch` find candidate API endpoints; each is probed,
   and only endpoints that really answer JSON are offered to the model.
2. **Generate.** The model writes a module with `NAME`, `DESCRIPTION`, `PARAMS`
   and `async def run(...)` as plain fenced code (not a JSON string, which small models corrupt).
3. **Static scan** (`_scan`). The module must parse and expose the required symbols. An AST walk
   rejects banned calls (`eval`, `exec`, `__import__`…), banned imports (`ctypes`, `pickle`…),
   file deletion and mutation attributes, and file writes.
4. **Smoke test.** The module runs in a separate interpreter with a timeout. Failure-shaped
   output ("Lookup failed: …") is rejected, so a tool with a dead endpoint cannot pass.
5. **Register.** The file is written to `janos/generated/` and imported into the process.

Up to three attempts; each failure's reason is fed back to the model. Skills are reloaded
at startup.

### Playbooks — `playbooks.py` (JSON, no code)

A playbook is an ordered list of calls to existing tools:

```json
{"name": "web_brief",
 "params": {"topic": "str=AI ethics", "chars": "int=3000"},
 "steps": [{"tool": "web_search", "args": {"query": "{{topic}}", "max_results": "5"}},
           {"tool": "web_fetch",  "args": {"url": "{{step1.url}}", "max_chars": "{{chars}}"}}],
 "output": "{{step2}}"}
```

Placeholders are `{{param}}`, `{{stepN}}`, `{{stepN.url}}`, `{{stepN.line}}`. Validation
(`validate`) checks that every tool and parameter exists, every param has a default,
references only point backward, and no step uses `shell`, `run_python`, `write_file` or a builder.
`_normalise` repairs placeholder forms small models invent. A trial run with default
arguments must succeed before the playbook is saved and registered.

## 6. Deterministic guards

Checkable facts are decided in Python, not by the model:

| Guard | Where | What it settles |
|---|---|---|
| `check_arithmetic` | `supervisor.py` | recomputes percentages against the figures beside them, per clause |
| `_required_tools` / `_repair_plan` | `supervisor.py` | tool ownership: a task needing `write_file` goes to an agent that has it |
| `_missing_files` | `supervisor.py` | a named output file either exists or the answer fails |
| repeated-call detection | `agents.py` | stops a loop of identical failing calls |
| derived values in tools | `tools.py` | `system_info` prints percentages computed from its own printed totals |
| forge validation | `forge.py` | AST scan, smoke test, failure-shape rejection |

## 7. Memory

SQLite database `jarvis-core/memory/janos.db` (git-ignored, personal).

| Table | Purpose |
|---|---|
| `episodes` | every task: plan, agents, tool calls, answer, errors, score, heal count, duration |
| `episodes_fts` | FTS5 index over episode text; BM25 ranking for recall |
| `lessons` / `lessons_fts` | distilled one-sentence lessons and their index; duplicates rejected |
| `agent_stats` | running average score per agent and task type (drives `best_agent_for`) |
| `tool_stats` | success counts per tool |

`Memory.unresolved` returns tasks that never reached the pass score; autonomous mode
retries these.

## 8. Autonomous mode

`AutonomousLoop` runs cycles of: choose a goal → `Supervisor.handle` → log → wait.
Goal sources rotate: **goals** (unchecked items in `workspace/goals.md`), **repair**
(past low-scoring tasks), **research** (a topic it has not learned), and **extend**
(a capability gap, resolved as a skill or a playbook). A PID lock prevents two loops
sharing one database. Stop with Ctrl-C or by creating `workspace/STOP`; the current cycle
finishes first. Each run appends to `workspace/autorun-YYYY-MM-DD.md`.

## 9. Web search chain

`web_search` tries providers in order and uses the first that returns results:
Brave API (only if a key is configured) → Yahoo (Bing-backed, parsed by `_yahoo_results`)
→ DuckDuckGo HTML → Wikipedia. Google and Bing block plain HTTP clients and bot-detect
headless browsers, so they are deliberately not used.

## 10. HTTP surface

`server.py` wraps one `Supervisor` created in the FastAPI lifespan. Every route requires
`Authorization: Bearer <token>` (`require_token`, constant-time compare), and
`TrustedHostMiddleware` admits only `127.0.0.1` and `localhost` unless
`JANOS_ALLOWED_HOSTS` says otherwise.

## 11. Learned routing

`policy.py` replaces the old running-average override (`Memory.best_agent_for`, still used when `rl_policy` is false). A one-step decision (contextual bandit), numpy only.

| | |
|---|---|
| **Sees** | Hashed words and word pairs of the request, the task type, and the action the LLM suggested (522 inputs). |
| **Decides** | One of 10 actions (5 agents x simple/complex): argmax Q plus a 0.15 trust bonus on the LLM's suggestion, so an untrained network follows the LLM. Untried actions start at an optimistic prior of 1.0; with probability `rl_explore` (0.05 interactive, `rl_explore_auto` 0.2 autonomous) a random allowed action is tried. Actions are masked by `_required_tools`. |
| **Learns** | Reward = verification score minus a latency cost capped at 0.1. A `/feedback` rating replaces that episode's reward rather than adding a second sample. Server, voice and autonomous mode share the file under a lock (reload → train → save). Each outcome enters a 2000-entry replay buffer; the 522 -> 64 (tanh) -> 10 network trains on minibatches with Adam and is saved to `memory/policy.npz`. |

## 12. Sandbox

`sandbox.prefix(config, profile)` returns the bubblewrap arguments to put in front of a
command, or nothing when the sandbox is off or bubblewrap is missing (`health()` reports
which).

| Profile | Used by | Sees | Writes | Network |
|---|---|---|---|---|
| `observe` | `shell` | processes (listed, not signalable), disks and GPU; filesystem read-only; `$HOME` and `/run` empty; environment cleared | workspace only | no (`shell_network: true` to allow) |
| `isolated` | `run_python`, forge smoke test | `/usr`, `/etc`, workspace, venv | workspace only | no (smoke test: yes) |

`/run` is hidden as deliberately as `$HOME`: the session bus there lets `systemd-run --user`
start a process outside any sandbox, and the SSH agent and keyring sockets live there too.
A shared network namespace would also expose abstract sockets (X11) and every unauthenticated
service on localhost, which is why the shell has no network by default.

The self-test proves the boundary both ways: with the sandbox on, the home folder is
invisible and writes outside the workspace fail; with `JANOS_SANDBOX=false`, those same
checks fail.

## 13. Extension points

| To add… | Do this |
|---|---|
| a built-in tool | add an entry to the `spec` list in `Toolbox._register_all` and grant it to an agent in `agents.py` |
| an agent | add an `Agent(...)` to `DEFAULT_AGENTS` with its tools and guidance |
| a verification fact | add a deterministic check beside `check_arithmetic` and call it from `_verify` |
| a search provider | add a branch in `web_search` before the Wikipedia fallback |
| a goal source | add a branch in `AutonomousLoop._next_goal` |

## 14. Data and files at runtime

| Path | Contents | In git |
|---|---|---|
| `jarvis-core/memory/janos.db` | episodes, lessons, stats | no |
| `jarvis-core/memory/api_token` | API bearer token | no |
| `jarvis-core/workspace/` | notes, goals, autonomous-run logs | no |
| `jarvis-core/janos/generated/` | skills JANOS wrote | no |
| `jarvis-core/janos/playbooks/` | playbooks JANOS wrote | no |
