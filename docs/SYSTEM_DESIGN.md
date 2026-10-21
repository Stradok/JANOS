# JANOS System Design

Why JANOS is built the way it is: goals, constraints, the decisions made, what
was rejected, and what each choice costs. How it is built is in
[ARCHITECTURE.md](ARCHITECTURE.md).

## 1. Problem and goals

Run a useful autonomous assistant on one consumer machine, with no cloud
dependency, that:

1. **does things** — executes tools and reports what really happened;
2. **checks itself** — notices a bad answer and repairs it;
3. **improves** — remembers what worked and extends its own capabilities;
4. **can run unattended** — chooses goals and leaves a readable record.

**Non-goals (for v2):** voice, vision, screen control, multi-user serving, multiple
models, distributed execution. These were part of the retired v1 stack and are out of
scope here.

## 2. Constraints

| Constraint | Consequence |
|---|---|
| One consumer GPU (RTX 4060, 8 GB VRAM), 14 GB RAM | a 7B model; no model swapping; small context (`num_ctx` 8192) |
| Local only, no API keys required | web access through keyless providers; no hosted LLM |
| A 7B model is unreliable at open-ended judgement | control flow is schema-constrained JSON; checkable facts are computed in code |
| Python 3.14 | several v1 dependencies (chromadb, crewai, langgraph, pyautogui) do not install, so v2 uses six small packages |
| Unattended operation | every failure must be survivable, bounded and logged |

## 3. Key design decisions

Each entry: the choice, why, what was rejected, and what it costs.

### 3.1 One supervisor, five agents, one model
- **Choice.** A single control loop (`Supervisor`) delegates to five role-limited agents. All use the same model.
- **Why.** Role-limited tool sets make routing a checkable fact. One model fits in VRAM with no load/unload latency.
- **Rejected.** A framework with a graph or crew abstraction (LangGraph, CrewAI): it adds a dependency that does not install here and hides the loop that this system most needs to inspect.
- **Cost.** The loop is hand-written, so every improvement is ours to maintain. The same model is both author and critic, so correlated mistakes are possible; the deterministic guards exist to limit that.

### 3.2 Schema-constrained JSON for control flow
- **Choice.** Triage, planning, verification and goal selection use Ollama's `format` parameter with a JSON schema (`LLM.chat_json`), re-parsed and retried on failure.
- **Why.** A 7B model reliably follows a schema and unreliably follows prose instructions about format.
- **Rejected.** Free-text parsing with regular expressions; function-calling APIs that this model handles inconsistently.
- **Cost.** Code is requested as a fenced block instead, because a model asked to put source inside a JSON string returns an empty string.

### 3.3 Deterministic guards over prompts
- **Choice.** Arithmetic, tool ownership, file existence and loop detection are decided in Python; the model's opinion loses.
- **Why.** Each of these was first tried as a prompt instruction and failed in testing. A 7B model approves "5679 of 8188 = 95%".
- **Cost.** Each guard is narrow code that must be written and tested. The rule when extending: if a check is decidable in code, put it in code.

### 3.4 SQLite FTS5 instead of a vector database
- **Choice.** Episodes and lessons are indexed with FTS5 and ranked with BM25.
- **Why.** No embedding model to load beside the LLM, no service, one file, and recall over short task text works well enough.
- **Rejected.** ChromaDB with sentence-transformer embeddings (the v1 design). The v1 code re-instantiated the embedding model on every call, and the package does not install on Python 3.14.
- **Cost.** Keyword recall misses paraphrases. Revisit when the episode count makes recall quality the bottleneck.

### 3.5 Verification with bounded healing
- **Choice.** Score each answer; below 0.6, re-run with the diagnosis. Keep a retry only if it is at least as good; stop when it is not strictly improving; cap at two attempts.
- **Why.** Re-running an unchanged plan costs about 20 seconds and changes nothing. Without a stop rule a small model loops.
- **Cost.** The critic is sometimes harsh, occasionally scoring 0.4 with no stated issue. Deriving `ok` from the score, not from a separate flag, reduces inconsistent verdicts.

### 3.6 Two kinds of self-written module
- **Choice.** *Skills* are Python files; *playbooks* are JSON chains of existing tools.
- **Why.** Most missing capabilities are workflows over tools that already exist. A playbook needs no code review and cannot do more than its parts, so it needs only validation. New code (a new API, a parser) is the exception, and it carries more risk.
- **Rejected.** Letting the model write Python for everything: more power than needed and a larger attack surface for the common case.
- **Cost.** Two formats and two validators. Playbooks cannot branch or loop by design.

### 3.7 Grounding self-written code in reality
- **Choice.** Before generating a skill, the forge searches the web, probes candidate endpoints, and offers only those that answered. A smoke test rejects failure-shaped output.
- **Why.** Left to its own memory the model invents plausible but dead endpoints and then fails its own test repeatedly.
- **Cost.** Slower creation (network probing), and dependence on a working search provider.

### 3.8 Autonomous mode as rotation, not free-running
- **Choice.** Goals rotate through four sources; one cycle at a time; a PID lock; a STOP file; a dated log per run.
- **Why.** Variety without drift, a single writer for the database, and a record you can read in the morning.
- **Cost.** Quality is bounded by the model's goal choices; the extension step is deliberately conservative about building new modules.

### 3.9 Web search without Google
- **Choice.** Brave API (optional) → Yahoo → DuckDuckGo → Wikipedia.
- **Why.** Google served a CAPTCHA to a headless browser, and DuckDuckGo now challenges plain HTTP. Defeating bot detection was rejected as brittle and not something to build in.
- **Cost.** Scraped HTML can change. A paid or keyed API is the durable option.

### 3.10 Learned routing: Q-learning with replay
- **Choice.** A small Q-network (contextual bandit) chooses agent and plan/direct mode: argmax Q plus a 0.15 trust bonus on the LLM's suggestion, an optimistic prior of 1.0 for untried actions, epsilon exploration, replay of the last 2000 outcomes. Reward is the verification score minus a latency cost capped at 0.1; a human rating from `/feedback` replaces the critic's reward for that episode instead of adding a second sample. Server, voice and autonomous mode share one policy file under a lock. The capability guard still wins: actions are masked to agents owning the tools `_required_tools` implies.
- **Why.** The running-average override could not weigh task wording or learn from ratings.
- **Rejected.** REINFORCE: with a strong prior it rarely explored and learned the right override on only about 6 of 16 random seeds; Q-learning with replay passes 20/20. A "typical" prior of 0.7: actions that had scored well then looked better than untried ones everywhere.
- **Cost.** It needs exploration, so about 5% of interactive requests try a different route (`rl_explore: 0` disables). Decisions awaiting feedback are kept in memory only and are lost on restart.

## 4. Failure modes and handling

| Failure | Handling |
|---|---|
| tool errors | returned as an observation; the agent adapts |
| repeated identical call | refused by the runner |
| low-quality answer | verify → heal, bounded, non-regressing |
| model output not valid JSON | parse error fed back, retried |
| model or Ollama missing | `health()` reports it; autonomous mode refuses to start |
| generated tool fails validation or smoke test | discarded; reason fed back; three attempts |
| two autonomous loops | PID lock refuses the second |
| search provider blocked | next provider in the chain |

## 5. Scalability and limits

- **Throughput.** One request at a time through one model; about 20 seconds per retry. Not a multi-user service.
- **Memory.** SQLite scales to many thousands of episodes; BM25 recall is quality-limited before it is speed-limited.
- **Context.** 8192 tokens bounds how much recalled context and tool output can be injected; tool output is truncated to 4000 characters.
- **Model ceiling.** A 7B model sets the quality limit of planning and critique. The architecture is model-agnostic through `config.model`.

## 6. Testing strategy

One self-test script (`make janos-test`, 113 checks) in three layers: offline logic (config, memory, guards, forge and playbook validation, autonomy, tools, server authentication), network (search and fetch), and live pipeline runs against the model. Each bug found gets a regression check. Gaps: no dedicated tests for `cli.py`, `llm.py` or `agents.py`; the autonomous loop is covered lightly.

## 7. Security model and residual risk

| Control | In place |
|---|---|
| API exposure | binds `127.0.0.1`; bearer token on every route (`memory/api_token`, 0600); host header allow-list |
| Shell | bubblewrap sandbox: home, `/run` and host environment hidden; filesystem read-only except the workspace; private `/dev` and IPC; no network by default; plus a destructive-command denylist; `sudo` fails fast |
| Code execution | `run_python` and skill smoke tests run in an isolated bubblewrap profile: no network (smoke test excepted), own process tree, clean environment |
| File writes | `write_file` confined to the workspace and home directory |
| Generated code | AST scan; separate-process smoke test; banned imports and file-write patterns |
| Playbooks | cannot call `shell`, `run_python`, `write_file`, or any builder |

**Residual risks (open):**

1. **Sandbox is a namespace boundary, not a VM.** bubblewrap hides your home, `/run` and the environment and blocks writes, but shares the kernel. `write_file` is not sandboxed and can still write in your home. The skill smoke test has network and can reach unauthenticated localhost services such as Ollama. A container or gVisor layer is the next step for untrusted work.
2. **Generated skills are imported into the supervisor process** after passing a heuristic scan. A determined injection could pass the scan.
3. **Prompt injection.** Web content that agents read can try to steer them toward dangerous tools. There is no separation between agents that read untrusted content and agents that can act.
4. **Autonomous mode** acts without a human present; combined with 1–3 this is the highest-risk configuration.

**Recommended hardening, in order:** confine `write_file` to the workspace; add a container layer for the coding workers; require approval before a new skill is persisted and loaded; run generated skills out of process behind a fixed protocol; separate "reads the web" agents from "executes" agents.

## 8. Future work

Direction and candidate technologies are tracked in the architecture roadmap (see the Archive and the project issues). In short: process isolation for execution, a multi-agent organisation with a task queue and per-agent coding-CLI workers, and a replacement review of the retired v1 components (speech, vision, orchestration frameworks).
