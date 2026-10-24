"""The supervisor — the single point of control.

One request flows through one loop:

    recall -> triage -> plan -> delegate -> synthesise -> verify
                                  ^                          |
                                  +------ self-heal ---------+
                                                             |
                                                          learn

* recall     pulls similar past episodes and distilled lessons into context
* triage     classifies the task and picks a starting agent, preferring the
             agent that has measurably done best on this task type before
* plan       decomposes anything non-trivial into agent-assigned steps
* delegate   runs each step through AgentRunner (agents may hand off to peers)
* verify     a critic pass scores the answer against the original request
* self-heal  a failing score re-runs execution with the diagnosis injected
* learn      the episode is stored and a lesson is distilled from it
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from janos.agents import Agent, AgentRunner, DEFAULT_AGENTS
from janos.config import Config
from janos import sandbox
from janos.employee import Employee
from janos.forge import ToolForge
from janos.playbooks import PlaybookForge
from janos.policy import Policy, reward
from janos.llm import LLM, LLMError
from janos.memory import Memory
from janos.tools import Tool, Toolbox

TRIAGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "task_type": {"type": "string"},
        "complexity": {"type": "string", "enum": ["simple", "complex"]},
        "agent": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": ["task_type", "complexity", "agent"],
}

PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"step": {"type": "string"}, "agent": {"type": "string"}},
                "required": ["step", "agent"],
            },
        }
    },
    "required": ["steps"],
}

VERIFY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "score": {"type": "number"},
        "ok": {"type": "boolean"},
        "issues": {"type": "array", "items": {"type": "string"}},
        "fix": {"type": "string"},
    },
    "required": ["score", "ok"],
}

LESSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "worth_saving": {"type": "boolean"},
        "lesson": {"type": "string"},
    },
    "required": ["worth_saving", "lesson"],
}


# "5679 MiB of its total 8188 MiB", "12 out of 60", "12.1 / 14.0". A short run
# of filler words may sit between the "of" and the second figure. The slash
# form requires surrounding spaces so that "6C/12T", "24/7" and paths do not
# read as ratios.
_UNIT = r"(?:MiB|MB|GiB|GB|KiB|KB|TB|bytes)?"
_FILLER = r"(?:(?:its|the|a|an|total|available|maximum|max|combined|overall)\s+){0,3}"
_RATIO = re.compile(
    rf"(\d[\d,]*(?:\.\d+)?)\s*{_UNIT}\s*"
    rf"(?:\bout of\b|\bof\b|\s/\s)\s*{_FILLER}"
    rf"(\d[\d,]*(?:\.\d+)?)\s*{_UNIT}",
    re.IGNORECASE,
)
_PERCENT = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(?:%|percent)", re.IGNORECASE)
# A claim is only checked against figures in its own clause. Comparing every
# percentage in an answer against every ratio in it produces false alarms —
# "6 cores at 0.8% load" has nothing to do with "159 of 233 GiB".
# Sentence breaks only: a full stop between two digits is a decimal point.
_SEGMENT = re.compile(r"(?<!\d)\.(?!\d)|[\n;•]|,\s+(?=[A-Z])")


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def check_arithmetic(answer: str) -> list[str]:
    """Deterministically catch percentages that contradict their own figures.

    A small model states "5679 of 8188 = 95%" with total confidence, and an
    LLM reviewer often waves it through. The division happens in Python, so
    the check does not depend on the model's competence at all.
    """
    problems: list[str] = []

    for segment in _SEGMENT.split(answer or ""):
        if not segment or "%" not in segment and "percent" not in segment.lower():
            continue

        expected: list[float] = []
        for a, b in _RATIO.findall(segment):
            try:
                top, bottom = _num(a), _num(b)
            except ValueError:
                continue
            if bottom > 0 and top <= bottom:
                expected.append(top / bottom * 100.0)
        if not expected:
            continue

        for raw in _PERCENT.findall(segment):
            try:
                claimed = _num(raw)
            except ValueError:
                continue
            if claimed > 100:
                continue
            if all(abs(claimed - e) > 2.0 for e in expected):
                best = min(expected, key=lambda e: abs(claimed - e))
                problems.append(
                    f"stated {claimed:g}% but the figures beside it work out to {best:.1f}%"
                )

    return problems[:3]


# A filename the request explicitly names, e.g. "save it to models-8gb.md".
_NAMED_FILE = re.compile(
    r"\b([\w./-]+\.(?:md|txt|json|csv|ya?ml|py|html|log|sh|tsv|ini|toml))\b",
    re.IGNORECASE,
)


@dataclass
class Turn:
    """Everything that happened while answering one request."""

    task: str
    answer: str = ""
    task_type: str = "general"
    complexity: str = "simple"
    plan: list[dict[str, str]] = field(default_factory=list)
    agents_used: list[str] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    score: float = 0.0
    issues: list[str] = field(default_factory=list)
    heal_attempts: int = 0
    duration_ms: int = 0
    episode_id: str = ""
    lesson: str = ""
    recalled: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "task": self.task, "answer": self.answer, "task_type": self.task_type,
            "complexity": self.complexity, "plan": self.plan,
            "agents": self.agents_used, "tool_calls": self.tool_calls,
            "errors": self.errors, "score": round(self.score, 3),
            "issues": self.issues, "self_healed": self.heal_attempts,
            "duration_ms": self.duration_ms, "episode_id": self.episode_id,
            "lesson": self.lesson, "recalled_episodes": self.recalled,
        }


class Supervisor:
    def __init__(
        self,
        config: Config | None = None,
        *,
        agents: list[Agent] | None = None,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ):
        self.config = config or Config.load()
        self.memory = Memory(self.config.db_path)
        self.llm = LLM(self.config)
        self.toolbox = Toolbox(self.config, self.memory)
        self.runner = AgentRunner(self.config, self.llm, self.toolbox,
                                  agents or DEFAULT_AGENTS)
        self.on_event = on_event

        # Self-extension. Tools written in earlier sessions are reloaded here,
        # so a capability only has to be invented once.
        self.forge = ToolForge(self.config, self.llm, self.toolbox, self.memory)
        self._install_forge()
        for name in self.forge.load_all():
            self._grant(name)

        # Learned routing. Each outcome is stored under its episode id, so a
        # later human rating replaces the critic's reward for that decision.
        self.policy = Policy(self.config.memory_dir / "policy.npz") if self.config.rl_policy else None
        self.explore = self.config.rl_explore

        # Second module type: tool-calling playbooks (JSON, no code).
        self.playbooks = PlaybookForge(self.config, self.llm, self.toolbox, self.memory)
        self._install_playbooks()
        for name in self.playbooks.load_all():
            self._grant(name)
        self._install_employee()

    # --------------------------------------------------- self-extension

    def _grant(self, tool_name: str) -> None:
        """Make a self-written tool usable by the agents that build things."""
        for agent_name in ("engineer", "operator"):
            agent = self.runner.agents.get(agent_name)
            if agent and tool_name not in agent.tools:
                agent.tools.append(tool_name)

    def _install_forge(self) -> None:
        async def create_tool(purpose: str = "", name: str = "") -> str:
            if not purpose.strip():
                return "Error: describe what the new tool must do in `purpose`."
            self._emit({"type": "forge", "stage": "start", "purpose": purpose})
            result = await self.forge.create(purpose, name)
            self._emit({"type": "forge", "stage": "done", "ok": result.ok,
                        "name": result.name, "reason": result.reason})
            if not result.ok:
                return f"Could not build that tool: {result.reason}"
            self._grant(result.name)
            return (f"Built and registered a new tool `{result.name}`. "
                    f"It is available now — call it directly. "
                    f"Smoke test output: {result.smoke_output[:300]}")

        self.toolbox.add(Tool(
            name="create_tool",
            description=("Write a brand-new tool when no existing tool can do the job. "
                         "It is validated, smoke-tested and registered immediately."),
            params={"purpose": "str: precisely what the tool must do",
                    "name": "str: optional snake_case name"},
            run=create_tool,
            danger=True,
        ))
        for agent_name in ("engineer",):
            agent = self.runner.agents.get(agent_name)
            if agent and "create_tool" not in agent.tools:
                agent.tools.append("create_tool")

    def _install_playbooks(self) -> None:
        async def create_playbook(purpose: str = "", name: str = "") -> str:
            if not purpose.strip():
                return "Error: describe the workflow in `purpose`."
            self._emit({"type": "forge", "stage": "start", "purpose": purpose, "kind": "playbook"})
            result = await self.playbooks.create(purpose, name)
            self._emit({"type": "forge", "stage": "done", "ok": result.ok,
                        "name": result.name, "reason": result.reason, "kind": "playbook"})
            if not result.ok:
                return f"Could not build that playbook: {result.reason}"
            self._grant(result.name)
            return (f"Built and registered playbook `{result.name}`. Call it directly. "
                    f"Output of a trial run: {result.smoke_output[:300]}")

        self.toolbox.add(Tool(
            name="create_playbook",
            description=("Save a repeatable workflow made only of existing tools (no code). "
                         "Prefer this over create_tool when the job is chaining tools."),
            params={"purpose": "str: the workflow, step by step",
                    "name": "str: optional snake_case name"},
            run=create_playbook,
            danger=True,
        ))
        agent = self.runner.agents.get("engineer")
        if agent and "create_playbook" not in agent.tools:
            agent.tools.append("create_playbook")

    def _install_employee(self) -> None:
        async def delegate_coding(task: str = "", repo: str = "", test_cmd: str = "") -> str:
            if not task.strip():
                return "Error: describe the coding task in `task`."
            janos_repo = Path(__file__).resolve().parents[2]
            root = Path(repo).expanduser().resolve() if repo else janos_repo
            # The model picks the path; only JANOS itself and the workspace are allowed.
            if not (root == janos_repo or root.is_relative_to(self.config.workspace.resolve())):
                return (f"Refused: {root} is outside the JANOS repository and the workspace. "
                        "Put the project under the workspace first.")
            try:
                emp = Employee(self.config, root)
            except ValueError as e:
                return f"Error: {e}"
            self._emit({"type": "employee", "stage": "start", "task": task})
            r = await emp.run(task, test_cmd=test_cmd)
            self._emit({"type": "employee", "stage": "done", "ok": r.ok, "branch": r.branch})
            tests = "not run" if r.tests_ok is None else "passed" if r.tests_ok else "failed"
            out = (f"Verdict {r.verdict}; branch {r.branch}; changed {', '.join(r.changed) or 'nothing'}; "
                   f"tests {tests}. Review: {r.review[-400:]}")
            if r.error:
                out += f" Error: {r.error}."
            if r.changed:
                out += f" Review and merge it yourself with: git -C {emp.repo} merge {r.branch}"
            return out

        self.toolbox.add(Tool(
            name="delegate_coding",
            description=("Have a sandboxed coding agent (OpenCode) do one coding task on its own git "
                         "branch, run tests and review it. Never merges; the human merges."),
            params={"task": "str: the coding task", "repo": "str: optional git repo path",
                    "test_cmd": "str: optional command that must pass"},
            run=delegate_coding,
            danger=True,
        ))
        agent = self.runner.agents.get("engineer")
        if agent and "delegate_coding" not in agent.tools:
            agent.tools.append("delegate_coding")

    # ------------------------------------------------------------ plumbing

    def _emit(self, event: dict[str, Any]) -> None:
        if self.on_event:
            try:
                self.on_event(event)
            except Exception:
                pass

    def close(self) -> None:
        self.memory.close()

    async def health(self) -> dict[str, Any]:
        llm = await self.llm.health()
        return {
            "ok": llm["reachable"] and llm["model_ready"],
            "llm": llm,
            "agents": [a["name"] for a in self.runner.roster()],
            "tools": self.toolbox.names(),
            "self_written_tools": self.forge.generated_names(),
            "playbooks": self.playbooks.names(),
            "memory": self.memory.stats(),
            "sandbox": sandbox.describe(self.config),
            "policy": self.policy.stats() if self.policy else "off",
            "config": {"model": self.config.model, "max_steps": self.config.max_steps,
                       "max_heal_attempts": self.config.max_heal_attempts},
        }

    # --------------------------------------------------------------- recall

    def _context(self, task: str) -> tuple[str, int]:
        """Assemble prior experience for this task."""
        blocks: list[str] = []

        lessons = self.memory.lessons_for(task, k=self.config.lesson_k)
        if lessons:
            blocks.append("WHAT YOU HAVE LEARNED BEFORE:\n" +
                          "\n".join(f"- {l}" for l in lessons))

        episodes = self.memory.recall(task, k=self.config.recall_k)
        if episodes:
            lines = []
            for e in episodes:
                mark = "worked" if (e["score"] or 0) >= self.config.min_pass_score else "went badly"
                lines.append(f"- [{mark}, {e['score']:.2f}] {e['task'][:120]}"
                             f" -> {(e['answer'] or '')[:200]}")
            blocks.append("SIMILAR PAST REQUESTS:\n" + "\n".join(lines))

        return "\n\n".join(blocks), len(episodes)

    # --------------------------------------------------------------- triage

    async def _triage(self, task: str, context: str) -> dict[str, Any]:
        prompt = f"""Classify this request for an assistant that has these agents:

{self.runner.catalogue()}

Request: {task}

- task_type: one short lowercase label (research, calculation, system, coding,
  writing, memory, chat, ...)
- complexity: "simple" only if ONE agent, using only the tools listed beside
  it, can finish the whole request in a few calls — or if it is small talk
  needing no tools. Choose "complex" whenever the request contains more than
  one distinct action (gather something AND write/save it somewhere, research
  AND compute, inspect AND change), or spans tools that no single agent owns.
- agent: the best agent to start with, from the list above. It must actually
  own the tools the first action needs.
"""
        msgs = [{"role": "system", "content":
                 "You route work inside an autonomous assistant. Be decisive."}]
        if context:
            msgs.append({"role": "system", "content": context})
        msgs.append({"role": "user", "content": prompt})

        try:
            out = await self.llm.chat_json(msgs, TRIAGE_SCHEMA)
        except LLMError:
            return {"task_type": "general", "complexity": "simple",
                    "agent": "researcher", "reason": "triage failed"}

        agent = (out.get("agent") or "").strip()
        if agent not in self.runner.agents:
            agent = "researcher"

        task_type = (out.get("task_type") or "general").strip().lower()[:32] or "general"

        complexity = "complex" if out.get("complexity") == "complex" else "simple"

        # Evidence beats the model's guess. With the learned policy, a Q-network
        # trained on past rewards may override the suggestion; without it, the
        # agent with the best running average on this task type does.
        decision = None
        needed = self._required_tools(task)
        if self.policy is not None:
            allowed = {n for n, a in self.runner.agents.items() if needed <= set(a.tools)} if needed else None
            d = self.policy.choose(task, task_type, agent, complexity,
                                   allowed=allowed or None, explore=self.explore)
            if d.agent in self.runner.agents:
                agent, complexity, decision = d.agent, d.mode, d
        else:
            proven = self.memory.best_agent_for(task_type)
            if proven and proven in self.runner.agents:
                agent = proven

        # Deterministic capability guard. The model happily routes "…and save it
        # to a file" to an agent with no write_file and then improvises with
        # shell echo. Whether an agent owns a tool is a fact, so it is settled
        # here rather than left to the model's self-assessment.
        if complexity == "simple" and needed:
            owned = set(self.runner.agents[agent].tools)
            if not needed <= owned:
                complexity = "complex"

        return {
            "task_type": task_type,
            "complexity": complexity,
            "agent": agent,
            "reason": (out.get("reason") or "")[:200],
            "decision": decision,
        }

    def _required_tools(self, task: str) -> set[str]:
        """Tools the wording of a request plainly implies."""
        low = task.lower()
        needed: set[str] = set()
        # A write verb whose object, within the same clause, is a file-ish thing
        # or something with a file extension. Requiring the verb keeps "read
        # notes.md" from being treated as a write.
        if re.search(
            r"\b(write|save|store|export|dump|append|create|generate|put)\b"
            r"[^.!?]{0,80}?(\bfiles?\b|\bdocument\b|\breport\b|\bnotes?\b|\.\w{1,5}\b)",
            low,
        ):
            needed.add("write_file")
        if re.search(r"\b(search|look up|google|latest|current news|find out online)\b", low):
            needed.add("web_search")
        if re.search(
            r"\b(cpu|ram|memory|disk|gpu|vram|hardware|specs?|processor|storage|"
            r"uptime|temperature)\b", low
        ) and re.search(r"\b(check|what|how much|show|report|tell|inspect|my|this machine)\b", low):
            needed.add("system_info")
        # Arithmetic is computed, never recalled: a model doing 47*89 "in its
        # head" is sometimes right, and a right guess would teach the routing
        # policy that skipping the calculator pays.
        # Dates, ranges, sizes and phone numbers look like operators (2026-10-21,
        # 3-5, 1920x1080, 555-1234), so dates are removed and "-"/"x" only count
        # with spaces around them.
        arith = re.sub(r"\b\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}\b", " ", low)
        if re.search(r"(?<![\w.])\d+(?:\.\d+)?\s*[+*/×^]\s*\d"
                     r"|\d\s+[-x]\s+\d|\bpercent of\b|%\s*of\b", arith):
            needed.add("calculate")
        # Opening apps/URLs and driving music need the desktop tool: the shell
        # sandbox has no display, so improvising with shell can only fail or lie.
        if re.search(
            r"\b(open|launch|start)\b[^.!?]{0,30}\b(app|application|spotify|firefox|chrome|chromium|"
            r"browser|vlc|steam|discord|terminal)\b|\bopen\b[^.!?]{0,20}(https?://|www\.|spotify:)"
            r"|\b(play|pause|resume|skip|stop)\b[^.!?]{0,40}\b(songs?|music|tracks?|playlist|album|spotify)\b"
            r"|\b(next|previous) (song|track)\b|\bplay\b[^.!?]{0,40}\bon (spotify|youtube)\b", low
        ):
            needed.add("desktop")
        # An explicit request to build a tool must reach create_tool. Left alone
        # the agent writes Python that *describes* a tool and calls it done.
        if "create_tool" in low or re.search(
            r"\b(build|create|write|make)\b[^.!?]{0,40}\bnew tool\b", low
        ):
            needed.add("create_tool")
        return needed

    # Which agent owns a given tool — used to repair plans deterministically.
    def _missing_files(self, task: str) -> list[str]:
        """Files the request asked for that do not exist on disk afterwards.

        An agent will report "saved to models-8gb.md" having written nothing,
        and the reviewer takes its word for it. Whether the file exists is a
        fact, so it is checked here — otherwise autonomous mode ticks goals off
        for work it never did.
        """
        if "write_file" not in self._required_tools(task):
            return []
        missing = []
        for name in dict.fromkeys(_NAMED_FILE.findall(task)):
            candidate = Path(name).expanduser()
            if not candidate.is_absolute():
                candidate = self.config.workspace / name
            if not candidate.exists():
                missing.append(name)
        return missing[:3]

    def _owner_of(self, tool: str) -> str | None:
        for name, agent in self.runner.agents.items():
            if tool in agent.tools:
                return name
        return None

    _STEP_TEXT = {
        "system_info": "Inspect this machine and report the real CPU, RAM, disk and GPU figures.",
        "web_search": "Search the web for the information this request needs.",
        "write_file": "Write the result to the file named in the request.",
        "desktop": "Call the desktop tool to do what the request asks (open_app, open_url or media), "
                   "then report only what it actually returned.",
        "create_tool": "Call the create_tool tool to build the tool this request asks for, "
                       "then call the tool it returns to prove it works.",
    }

    def _repair_plan(self, task: str, steps: list[dict[str, str]]) -> list[dict[str, str]]:
        """Guarantee the plan can actually reach the tools the request needs.

        The planner will happily hand a 'check my hardware and save it' task to
        an agent that owns neither system_info nor write_file, and that agent
        then guesses. Tool ownership is a fact, so it is enforced in code.
        """
        needed = self._required_tools(task)
        if not needed:
            return steps

        covered: set[str] = set()
        for s in steps:
            agent = self.runner.agents.get(s["agent"])
            if agent:
                covered |= set(agent.tools)

        for tool in sorted(needed - covered):
            owner = self._owner_of(tool)
            if not owner:
                continue
            new_step = {"step": self._STEP_TEXT.get(tool, f"Use {tool} for this request."),
                        "agent": owner}
            # Gather before writing; a write step belongs at the end.
            if tool == "write_file":
                steps = steps + [new_step]
            else:
                steps = [new_step] + steps

        return steps[: self.config.max_steps]

    # ----------------------------------------------------------------- plan

    async def _plan(self, task: str, context: str, task_type: str) -> list[dict[str, str]]:
        prompt = f"""Break this request into the fewest steps that fully complete it.

Agents available:
{self.runner.catalogue()}

Request: {task}

Rules:
- At most {self.config.max_steps} steps; prefer 2-4.
- Each step names one agent and states a concrete, self-contained action.
- Later steps may rely on earlier results; say so in the step text.
- Do not add steps for greeting, planning or summarising — that is handled.
"""
        msgs = [{"role": "system", "content": "You plan work for specialist agents."}]
        if context:
            msgs.append({"role": "system", "content": context})
        msgs.append({"role": "user", "content": prompt})

        try:
            out = await self.llm.chat_json(msgs, PLAN_SCHEMA)
        except LLMError as e:
            return [{"step": task, "agent": "researcher", "note": f"planner failed: {e}"}]

        steps: list[dict[str, str]] = []
        for raw in (out.get("steps") or [])[: self.config.max_steps]:
            if not isinstance(raw, dict):
                continue
            text = (raw.get("step") or "").strip()
            if not text:
                continue
            agent = (raw.get("agent") or "").strip()
            if agent not in self.runner.agents:
                agent = "researcher"
            steps.append({"step": text, "agent": agent})

        return self._repair_plan(task, steps or [{"step": task, "agent": "researcher"}])

    # -------------------------------------------------------------- execute

    async def _execute(
        self, turn: Turn, steps: list[dict[str, str]], context: str, heal_hint: str = ""
    ) -> list[str]:
        """Run every step, following any agent-to-agent handoffs."""
        findings: list[str] = []

        for i, step in enumerate(steps, 1):
            step_context = context
            if findings:
                step_context += "\n\nRESULTS SO FAR:\n" + "\n\n".join(findings[-3:])
            if heal_hint:
                step_context += f"\n\nA PREVIOUS ATTEMPT FAILED. Fix this: {heal_hint}"

            agent_name = step["agent"]
            self._emit({"type": "step", "index": i, "total": len(steps),
                        "agent": agent_name, "step": step["step"]})

            result = await self.runner.run(
                agent_name, step["step"], context=step_context, on_event=self.on_event
            )

            # Agent-to-agent handoff, bounded to one hop per step so a pair of
            # agents cannot bounce a task back and forth forever.
            hops = 0
            while result.wants_delegation and hops < 2:
                hops += 1
                target, sub = result.delegate_to, result.delegate_task
                self._emit({"type": "delegate", "from": agent_name,
                            "to": target, "task": sub})
                turn.agents_used.append(f"{agent_name}->{target}")
                result = await self.runner.run(
                    target, sub, context=step_context, on_event=self.on_event
                )
                agent_name = target

            if agent_name not in turn.agents_used:
                turn.agents_used.append(agent_name)
            turn.tool_calls.extend(result.tool_calls)
            turn.errors.extend(result.errors)
            self.memory.record_agent(agent_name, turn.task_type,
                                     0.0 if result.errors else 1.0)

            if result.answer:
                findings.append(f"[step {i} · {agent_name}] {result.answer}")

        return findings

    # ------------------------------------------------------------ synthesis

    async def _synthesise(self, task: str, findings: list[str]) -> str:
        if not findings:
            return "I was not able to produce a result for that."
        if len(findings) == 1:
            # Single step: its answer already is the answer.
            return findings[0].split("] ", 1)[-1]
        try:
            return await self.llm.chat(
                [
                    {"role": "system", "content":
                     "Combine the step results into one direct answer to the user's "
                     "request. Use only what the steps found. Do not mention steps, "
                     "agents or tools. Plain text."},
                    {"role": "user", "content":
                     f"REQUEST: {task}\n\nSTEP RESULTS:\n" + "\n\n".join(findings)},
                ],
                temperature=0.3,
            )
        except LLMError:
            return "\n\n".join(f.split("] ", 1)[-1] for f in findings)

    # --------------------------------------------------------------- verify

    async def _verify(
        self, task: str, answer: str, errors: list[str],
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if not answer.strip():
            return {"score": 0.0, "ok": False, "issues": ["empty answer"],
                    "fix": "Produce an actual answer."}

        # Deterministic first: a maths error and a missing file are facts, not
        # matters of opinion, so both are settled before the model is consulted.
        bad_maths = check_arithmetic(answer)
        missing = self._missing_files(task)

        # Side effects live in the tool log, not the prose. Without this the
        # reviewer marks "write it to specs.md" unmet even when the file exists.
        evidence = "none"
        if tool_calls:
            evidence = "\n".join(
                f"- {c['tool']}({', '.join(f'{k}={str(v)[:40]}' for k, v in (c.get('args') or {}).items())})"
                f" -> {'ok' if c.get('ok') else 'FAILED'}: {str(c.get('output', ''))[:160]}"
                for c in tool_calls[-8:]
            )

        # Fast path: deterministic guards clean, and the answer is grounded in
        # tools that all ran without error. The critic almost never overturns
        # this, and its call plus any heal retry are most of the latency — so
        # accept directly. Knowledge-only answers (no tool) and anything with a
        # maths, file or execution problem still go to the critic below.
        if (self.config.fast_verify and not bad_maths and not missing and not errors
                and tool_calls and all(c.get("ok") for c in tool_calls)):
            return {"score": 0.9, "ok": True, "issues": [], "fix": "", "fast": True}

        prompt = f"""Judge whether this answer genuinely satisfies the request.

REQUEST: {task}

ANSWER:
{answer[:2500]}

WHAT THE AGENTS ACTUALLY DID (tool log — trust this for side effects such as
files written or commands run; the answer text may not mention them):
{evidence}

TOOL ERRORS DURING EXECUTION: {'; '.join(errors[:5]) if errors else 'none'}

Check in this order:
0. If the request asked for a side effect (write a file, run something), the
   tool log above decides whether it happened — not whether the answer
   mentions it.
1. Does it answer what was actually asked?
2. Is every number consistent? Re-derive any ratio, percentage or total
   yourself. A stated percentage that does not follow from the stated figures
   is a factual error — score it below 0.5 no matter how confident it sounds.
3. Are claims grounded in the tool output, or invented?

Judge only against what was actually asked. Detail the user did not request is
not missing, and a short answer to a short question is not thin. "Could have
included more" is NOT a valid issue — only raise something the request itself
asked for and the answer failed to deliver. Your "fix" must never introduce a
requirement the user did not state: demanding extra specifics pushes the next
attempt into guessing, which is worse than a brief correct answer.

Score 0.0-1.0:
  1.0 fully answers the request, specific and arithmetically correct
  0.7 answers it but thin or partially unsupported
  0.4 partly relevant, misses the point, or contains a wrong number
  0.0 fails, refuses, or is an error message
Set ok=true only if score >= {self.config.min_pass_score}.
If not ok, "issues" must name the specific defect and "fix" must say
concretely what to do differently. Never return a failing score with no issues.
"""
        try:
            out = await self.llm.chat_json(
                [{"role": "system", "content":
                  "You are a strict reviewer. An answer that states no real "
                  "information scores low, however fluent it is. You check "
                  "arithmetic rather than trusting it."},
                 {"role": "user", "content": prompt}],
                VERIFY_SCHEMA,
            )
        except LLMError:
            # Reviewer unavailable: don't block the answer, but don't trust it
            # either — and the arithmetic check still stands on its own.
            hard = bad_maths + [f"{f} was never created" for f in missing]
            return {
                "score": 0.3 if hard else 0.5,
                "ok": not hard,
                "issues": hard + ["verification unavailable"],
                "fix": "; ".join(hard),
            }

        try:
            score = max(0.0, min(1.0, float(out.get("score", 0.0))))
        except (TypeError, ValueError):
            score = 0.5
        issues = [str(i)[:200] for i in (out.get("issues") or []) if i][:5]
        fix = (out.get("fix") or "")[:400]

        if bad_maths:
            # The reviewer's opinion cannot overrule arithmetic.
            issues = bad_maths + issues
            score = min(score, 0.4)
            fix = ("Recompute the figure with the calculate tool and restate it. "
                   + "; ".join(bad_maths))

        if missing:
            names = ", ".join(missing)
            issues = [f"claimed to write {names}, but the file does not exist"] + issues
            score = min(score, 0.3)
            fix = (f"The file {names} was never created. Call write_file with the full "
                   f"content and the exact filename. Do not claim it is saved otherwise.")

        return {
            "score": score,
            # Derived from the score rather than the model's own `ok` flag: it
            # regularly returns score 0.7 alongside ok=false, and honouring that
            # contradiction spends two more executions to no purpose.
            "ok": (score >= self.config.min_pass_score and not bad_maths and not missing),
            "issues": issues,
            "fix": fix,
        }

    # ----------------------------------------------------------------- learn

    async def _distil(self, turn: Turn) -> str:
        """Extract a durable lesson from what just happened."""
        if not self.config.learn:
            return ""
        # Small talk that touched no tool has nothing to teach, and asking
        # anyway yields confident nonsense that then pollutes future recall.
        if not turn.tool_calls and turn.task_type in {
            "chat", "greeting", "smalltalk", "conversation", "general"
        }:
            return ""
        tools = ", ".join(sorted({c["tool"] for c in turn.tool_calls})) or "none"
        outcome = "succeeded" if turn.score >= self.config.min_pass_score else "failed"
        struggled = turn.heal_attempts > 0 or bool(turn.errors) or bool(turn.issues)
        prompt = f"""Write one reusable operating lesson from this interaction.

REQUEST: {turn.task}
TASK TYPE: {turn.task_type}
AGENTS USED: {', '.join(turn.agents_used) or 'none'}
TOOLS USED: {tools}
OUTCOME: {outcome} (score {turn.score:.2f}, self-heal attempts {turn.heal_attempts})
PROBLEMS: {'; '.join(turn.issues + turn.errors[:3]) or 'none'}

Good lessons read like these:
- "For CPU, RAM, disk or GPU questions call system_info instead of parsing
   nvidia-smi output by hand."
- "This machine reports 8188 MiB of total VRAM."
- "When a request asks for output saved to a file, give the write step to an
   agent that owns write_file."
- "Never state a percentage that was not produced by the calculate tool."

Write it as one self-contained sentence a future run could act on. Name the
specific tool, agent, or fact — a vague lesson is useless.
Set worth_saving=true by default. Set it to false ONLY if this was small talk,
or the only available lesson is a truism.
{"This run needed self-healing or hit errors, so there IS a lesson here: say what should be done differently next time." if struggled else ""}
"""
        try:
            out = await self.llm.chat_json(
                [{"role": "system", "content":
                  "You distil operating lessons for an autonomous assistant."},
                 {"role": "user", "content": prompt}],
                LESSON_SCHEMA,
            )
        except LLMError:
            return ""

        lesson = (out.get("lesson") or "").strip()
        if out.get("worth_saving") and len(lesson) >= 12:
            if self.memory.add_lesson(lesson, task_type=turn.task_type,
                                      source=turn.episode_id):
                return lesson
        return ""

    # ----------------------------------------------------------------- main

    async def handle(self, task: str) -> Turn:
        started = time.perf_counter()
        turn = Turn(task=task.strip())
        if not turn.task:
            turn.answer = "Say something and I'll get to work."
            return turn

        context, recalled = self._context(turn.task)
        turn.recalled = recalled
        self._emit({"type": "recall", "episodes": recalled})

        triage = await self._triage(turn.task, context)
        decision = triage.pop("decision", None)     # not JSON; kept out of the event stream
        turn.task_type = triage["task_type"]
        turn.complexity = triage["complexity"]
        self._emit({"type": "triage", **triage})

        if turn.complexity == "simple":
            turn.plan = [{"step": turn.task, "agent": triage["agent"]}]
        else:
            turn.plan = await self._plan(turn.task, context, turn.task_type)
            self._emit({"type": "plan", "steps": turn.plan})

        findings = await self._execute(turn, turn.plan, context)
        turn.answer = await self._synthesise(turn.task, findings)

        verdict = await self._verify(turn.task, turn.answer, turn.errors, turn.tool_calls)
        turn.score, turn.issues = verdict["score"], verdict["issues"]
        self._emit({"type": "verify", **verdict})

        # ---- self-healing -------------------------------------------------
        while not verdict["ok"] and turn.heal_attempts < self.config.max_heal_attempts:
            turn.heal_attempts += 1
            hint = verdict.get("fix") or "; ".join(verdict["issues"]) or "Be specific and use tools."
            self._emit({"type": "heal", "attempt": turn.heal_attempts, "hint": hint})

            past_failures = self.memory.recall(turn.task, k=2, min_score=None)
            heal_context = context
            if past_failures:
                heal_context += "\n\nAVOID REPEATING THESE PAST MISTAKES:\n" + "\n".join(
                    f"- {p['task'][:80]}: {'; '.join(p['errors'][:2]) or 'low score'}"
                    for p in past_failures if (p["score"] or 0) < self.config.min_pass_score
                )

            retry_findings = await self._execute(turn, turn.plan, heal_context, heal_hint=hint)
            if retry_findings:
                candidate = await self._synthesise(turn.task, retry_findings)
                new_verdict = await self._verify(turn.task, candidate, turn.errors,
                                                 turn.tool_calls)
                self._emit({"type": "verify", "retry": turn.heal_attempts, **new_verdict})
                improved = new_verdict["score"] > turn.score
                # Only accept the retry if it is actually better.
                if new_verdict["score"] >= turn.score:
                    turn.answer, verdict = candidate, new_verdict
                    turn.score, turn.issues = new_verdict["score"], new_verdict["issues"]
                if verdict["ok"]:
                    break
                if not improved:
                    # Re-running the same plan is not converging. Another
                    # identical attempt costs ~20s and changes nothing.
                    turn.issues = turn.issues or ["did not converge on retry"]
                    break
            else:
                break

        turn.duration_ms = int((time.perf_counter() - started) * 1000)

        # ---- remember and learn -------------------------------------------
        turn.episode_id = self.memory.remember(
            task=turn.task, answer=turn.answer, task_type=turn.task_type,
            plan=turn.plan, agents=turn.agents_used, tool_calls=turn.tool_calls,
            errors=turn.errors, score=turn.score, healed=turn.heal_attempts,
            duration_ms=turn.duration_ms,
            meta={"complexity": turn.complexity, "issues": turn.issues,
                  "usage": self.llm.usage.as_dict()},
        )
        for agent in turn.agents_used:
            self.memory.record_agent(agent.split("->")[-1], turn.task_type, turn.score)
        if decision is not None:
            self.policy.learn(decision, reward(turn.score, turn.duration_ms / 1000),
                              key=turn.episode_id)

        turn.lesson = await self._distil(turn)
        if turn.lesson:
            self._emit({"type": "lesson", "text": turn.lesson})

        self._emit({"type": "done", "score": turn.score, "ms": turn.duration_ms})
        return turn
