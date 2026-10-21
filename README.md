# JANOS — Joint Autonomous Neural Agent

A local, self-healing, self-extending agent system that runs entirely on your own
machine. One supervisor coordinates five specialist agents that **actually execute
tools** (web, files, shell, Python, system inspection), verify their own answers,
learn lessons from every task, and write new modules for themselves when they hit
a capability gap.

No cloud, no API keys required, no telemetry. One Ollama model does all the
reasoning.

```
request ─► recall ─► triage ─► plan ─► delegate ─► verify ─► self-heal ─► learn
              ▲                              │                              │
              └──────────── memory (SQLite FTS5) ◄──────────────────────────┘
```

## Highlights

- **Real tool execution.** Agents call tools and read the results. Nothing is
  "described" and then assumed to have happened.
- **Verified answers.** A critic scores every answer. Checkable facts (arithmetic,
  files that must exist) are settled in Python, never left to the model's opinion.
- **Self-healing.** A failing score re-runs execution with the diagnosis. A retry
  is kept only if it is at least as good, and the loop stops when it stops improving.
- **Self-learning.** Each task distils a lesson that is recalled on similar tasks.
  Routing (which agent, plan or direct) is learned by a small Q-network trained on
  verification scores and your `/feedback` ratings.
- **Self-extending, two ways.**
  - *Skills* — Python modules JANOS writes for itself, AST-scanned and smoke-tested
    in a separate process before registration.
  - *Playbooks* — JSON workflows that chain existing tools with no code at all.
- **Autonomous mode.** It picks its own goals (your checklist, past failures,
  research topics, capability gaps) and works unattended, logging every cycle.
- **Small footprint.** Six runtime dependencies. Retrieval is SQLite FTS5 (BM25):
  no vector database and no embedding model.

## Requirements

| | |
|---|---|
| OS | Linux (developed on Ubuntu) |
| Python | 3.14 (developed on 3.14.4) |
| LLM runtime | [Ollama](https://ollama.com), running on `localhost:11434` |
| Model | `qwen2.5:7b-instruct` (about 4.7 GB) |
| GPU | 8 GB VRAM recommended; the model uses about 5.5 GB. CPU works but is slow. |

## Quick start

```bash
cd jarvis-core
make janos-setup              # creates .venv, installs dependencies, pulls the model
make janos                    # interactive REPL
make janos-ask Q="how much VRAM is my GPU using?"
make janos-test               # self-test (113 checks)
```

Other entry points:

| Command | What it does |
|---|---|
| `make janos-voice` | Talk to it: say **"Hey Jarvis"**, then your request (`TEXT=1` to type) |
| `make janos-voice-setup` | One-time: install voice extras and download speech models (~0.6 GB) |
| `make janos-serve` | HTTP API on `127.0.0.1:8000` (bearer-token protected) |
| `make janos-auto` | Autonomous mode: chooses its own goals |
| `make janos-auto-night` | Autonomous mode in the background |
| `make janos-auto-stop` | Ask the background run to stop after the current cycle |
| `make janos-stats` | Episodes, scores, agent rankings |
| `make janos-lessons` | Everything it has learned |
| `make janos-tools` | All tools, including self-written ones |

Full command reference: [docs/USAGE.md](docs/USAGE.md).

## Voice

Fully local and English-only for now. The LLM keeps the GPU; speech runs on the CPU.

```
mic ─► wake word ("hey jarvis", openWakeWord) ─► end-of-turn (Silero VAD)
    ─► speech-to-text (faster-whisper small.en) ─► JANOS ─► text-to-speech (Kokoro, British voice)
```

A warm turn takes about 4–6 seconds from the end of your sentence to the start of the reply.
The microphone is ignored while JANOS speaks, so it cannot wake itself. The personality,
voice and wake sensitivity are set in `jarvis-core/janos.yaml` (`persona`, `voice_name`,
`wake_threshold`). A custom "Hey JANOS" wake word needs a trained model and is not included yet.

## HTTP API

The server binds to loopback and requires a per-install token. The token is created
on first start in `jarvis-core/memory/api_token` (mode `0600`).

```bash
TOKEN=$(cat jarvis-core/memory/api_token)
curl -s -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
     -d '{"input": "what is my free disk space?"}' http://127.0.0.1:8000/chat
```

Other routes: `/health`, `/chat/stream`, `/feedback`, `/agents`, `/tools`,
`/memory/stats`, `/memory/recent`, `/memory/lessons`, `/rankings`.

## Project layout

```
.
├── README.md
├── docs/
│   ├── ARCHITECTURE.md      components, flows, data model, extension points
│   ├── SYSTEM_DESIGN.md     goals, constraints, decisions, trade-offs, risks
│   └── USAGE.md             commands, configuration, operation
├── Archive/                 history, not needed to run: logs, chat logs, old docs
└── jarvis-core/
    ├── janos/               the working system (about 4.8k lines)
    │   ├── supervisor.py    recall → triage → plan → delegate → verify → heal → learn
    │   ├── agents.py        five agents and the tool loop they run
    │   ├── tools.py         twelve built-in tools
    │   ├── forge.py         skills: self-written Python tools
    │   ├── playbooks.py     playbooks: self-written JSON tool chains
    │   ├── memory.py        SQLite episodes, lessons, rankings (FTS5)
    │   ├── llm.py           Ollama client, schema-constrained JSON
    │   ├── auto.py          autonomous loop
    │   ├── server.py  cli.py  config.py  selftest.py
    │   ├── generated/       skills JANOS wrote (git-ignored)
    │   └── playbooks/       playbooks JANOS wrote
    ├── janos.yaml           configuration
    ├── Makefile             developer entry point
    └── (agents/ core/ modules/ tools/ …)   legacy v1 stack, not used by JANOS v2
```

## Configuration

Settings live in `jarvis-core/janos.yaml`; any value can be overridden with a
`JANOS_` environment variable (for example `JANOS_MODEL`). Key settings:

| Key | Default | Meaning |
|---|---|---|
| `model` | `qwen2.5:7b-instruct` | the one model used for everything |
| `max_steps` | 8 | most plan steps per request |
| `max_heal_attempts` | 2 | retries after a failed verification |
| `min_pass_score` | 0.6 | verification score needed to accept an answer |
| `allow_shell` | true | set false to remove shell access entirely |
| `sandbox` | true | run shell, run_python and smoke tests inside bubblewrap |
| `shell_network` | false | let the sandboxed shell reach the network and local services |
| `rl_policy` | true | learned routing; false falls back to the best running average per task type |
| `rl_explore` | 0.05 | how often the policy tries another route while you wait (0 disables; `rl_explore_auto` 0.2 in autonomous mode) |

Optional: a Brave Search API key (`BRAVE_API_KEY`, or the file
`jarvis-core/.brave_key`) is used first for web search when present. Without one,
search falls back to Yahoo, DuckDuckGo, then Wikipedia.

## Security model

JANOS gives a language model a shell. Treat it accordingly.

- The API listens on `127.0.0.1` only, requires a bearer token on every route, and
  rejects unexpected `Host` headers (DNS-rebinding defence).
- `shell` and `run_python` run inside a **bubblewrap sandbox** (`janos/sandbox.py`).
  `shell` can still see the machine (processes, disks, GPU), but your home folder,
  `/run` (session bus, SSH agent, keyring) and the host environment are hidden, only the
  workspace is writable, and there is no network unless `shell_network: true`.
  `run_python` also gets its own process tree. Generated skills are smoke-tested in the
  same sandbox, with network.
- Destructive shell commands are also refused by a denylist, and `sudo` fails fast.
- Generated skills are validated and smoke-tested in the sandbox, **but are then
  loaded into the supervisor process**. Do not run JANOS on content you do not trust.
- Web content is untrusted input to the agents; prompt injection through fetched
  pages is a known residual risk.

Details and the open items are in [docs/SYSTEM_DESIGN.md](docs/SYSTEM_DESIGN.md#7-security-model-and-residual-risk).

## Testing

```bash
make janos-test               # full: offline logic + model + network checks
make janos-test OFFLINE=1     # skip model and network checks
```

The self-test covers configuration, memory, arithmetic guards, capability routing,
forge validation, autonomy, tools, sandbox isolation, playbooks, server authentication, and live
pipeline runs against the model.

## Documentation

- [Architecture](docs/ARCHITECTURE.md) — how it is built
- [System design](docs/SYSTEM_DESIGN.md) — why it is built that way
- [Usage](docs/USAGE.md) — operating it
- [Archive](Archive/README.md) — development history and retired material

## Status

JANOS v2 is working and under active development. The legacy v1 stack in
`jarvis-core/` (`core/`, `modules/`, `agents/`, `tools/`) is retained for reference
only; it depends on packages that do not install on Python 3.14 and is not used.
