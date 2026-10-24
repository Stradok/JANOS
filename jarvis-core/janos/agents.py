"""Specialist agents.

An agent is a role, a subset of the toolbox, and a loop that really runs
tools. Each turn the model returns one JSON decision:

    use_tool      -> Toolbox executes it, the observation is appended, loop
    delegate      -> hand the step to a better-suited agent (agent-to-agent)
    final_answer  -> done

The loop is bounded by `agent_max_turns`, and a turn that fails to produce a
usable decision is fed back as an observation instead of aborting the run.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from janos.config import Config
from janos.llm import LLM, LLMError
from janos.tools import Toolbox, ToolResult

DECISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "thought": {"type": "string"},
        "action": {"type": "string", "enum": ["use_tool", "final_answer", "delegate"]},
        "tool": {"type": "string"},
        "args": {"type": "object"},
        "answer": {"type": "string"},
        "delegate_to": {"type": "string"},
        "delegate_task": {"type": "string"},
    },
    "required": ["thought", "action"],
}


@dataclass
class AgentResult:
    agent: str
    answer: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    turns: int = 0
    errors: list[str] = field(default_factory=list)
    delegate_to: str = ""
    delegate_task: str = ""

    @property
    def wants_delegation(self) -> bool:
        return bool(self.delegate_to)


@dataclass
class Agent:
    name: str
    role: str
    purpose: str
    tools: list[str]
    guidance: str = ""

    def system_prompt(self, toolbox: Toolbox, peers: list[str]) -> str:
        tool_text = toolbox.describe(self.tools) or "(none — answer from your own knowledge)"
        peer_text = ", ".join(p for p in peers if p != self.name) or "(none)"
        return f"""You are {self.name}, the {self.role} of the JANOS assistant.
Your purpose: {self.purpose}

TOOLS YOU CAN USE:
{tool_text}

OTHER AGENTS you may delegate to: {peer_text}

Reply with exactly ONE JSON object each turn:
  {{"thought": "...", "action": "use_tool", "tool": "<name>", "args": {{...}}}}
  {{"thought": "...", "action": "final_answer", "answer": "<the full answer>"}}
  {{"thought": "...", "action": "delegate", "delegate_to": "<agent>", "delegate_task": "<what they should do>"}}

RULES:
- Use a tool whenever the answer depends on live data, files, the machine, or
  exact arithmetic.
- NEVER invent a fact you did not obtain from a tool or from the context. Model
  numbers, hardware names, versions, speeds, prices, dates and quantities must
  come from a tool result. If you cannot obtain something, either delegate to
  an agent that can, or say plainly that you could not determine it. A stated
  guess is the worst possible outcome — far worse than an incomplete answer.
- Never copy a specific value from a previous answer in the context unless you
  are certain it came from a tool. Re-measure instead.
- Look at each OBSERVATION before deciding again. If a tool failed, read the
  error and try a corrected call or a different tool.
- Do not repeat a tool call that already succeeded.
- If the task needs a capability you do not have, delegate to the agent that
  does. Improvising a worse substitute with the tools you happen to have is a
  failure, not a workaround.
- When you have enough information, answer directly and completely in
  "answer". Write for the user, not about your process.
{self.guidance}"""


DEFAULT_AGENTS: list[Agent] = [
    Agent(
        name="researcher",
        role="information gatherer",
        purpose="Find current, accurate facts from the web and from memory, then summarise them with sources.",
        tools=["web_search", "web_fetch", "browser_fetch", "recall_memory", "save_note", "now", "calculate"],
        guidance="- Search first, then fetch the most promising URL for detail.\n"
                 "- Cite the URLs you actually used.\n"
                 "- Any arithmetic goes through calculate, never your head.",
    ),
    Agent(
        name="analyst",
        role="calculation and data reasoner",
        purpose="Answer quantitative questions exactly, using real computation rather than mental arithmetic.",
        tools=["calculate", "run_python", "recall_memory", "web_search"],
        guidance="- Use calculate for arithmetic and run_python for anything longer.\n"
                 "- Show the number you computed, not an estimate.",
    ),
    Agent(
        name="operator",
        role="system operator",
        purpose="Inspect and operate this Linux machine: processes, hardware, packages, files on disk.",
        tools=["shell", "system_info", "list_dir", "read_file", "now", "calculate", "desktop"],
        guidance="- To open or launch an app, open a URL, or play/pause/skip music, use\n"
                 "  desktop (shell cannot reach the screen). Never say you did it\n"
                 "  unless desktop returned success.\n"
                 "- For CPU, RAM, disk or GPU status use system_info first: it is\n"
                 "  already parsed and reliable. Only fall back to shell if it is\n"
                 "  missing something you specifically need.\n"
                 "- Probe before concluding: `which x`, `ls`, `ps aux`, `df -h`.\n"
                 "- Prefer read-only commands. Never run destructive ones.\n"
                 "- Percentages, ratios and totals go through calculate. Never do\n"
                 "  arithmetic in your head — you will get it wrong.",
    ),
    Agent(
        name="engineer",
        role="code and file engineer",
        purpose="Read, write and run code and files, and build new tools when none fit.",
        tools=["read_file", "write_file", "list_dir", "run_python", "shell"],
        guidance="- Read a file before you edit it.\n"
                 "- After writing code, run it to prove it works.\n"
                 "- If no existing tool can do what the task needs, use create_tool to\n"
                 "  write one, then call the tool it gives you back. Build a tool only\n"
                 "  for a real gap, not for something run_python already covers.\n"
                 "- If the job is just chaining tools that already exist, use\n"
                 "  create_playbook instead: it saves the workflow with no code.",
    ),
    Agent(
        name="scribe",
        role="writer and synthesiser",
        purpose="Turn gathered material into clear, well-structured prose, and record notes.",
        tools=["recall_memory", "save_note", "write_file"],
        guidance="- Prefer plain, direct language. Structure long answers with headings.",
    ),
]


class AgentRunner:
    """Executes one agent's tool loop against a task."""

    def __init__(self, config: Config, llm: LLM, toolbox: Toolbox,
                 agents: list[Agent] | None = None):
        self.config = config
        self.llm = llm
        self.toolbox = toolbox
        self.agents: dict[str, Agent] = {a.name: a for a in (agents or DEFAULT_AGENTS)}

    def get(self, name: str) -> Agent | None:
        return self.agents.get(name)

    def roster(self) -> list[dict[str, Any]]:
        return [
            {"name": a.name, "role": a.role, "purpose": a.purpose, "tools": a.tools}
            for a in self.agents.values()
        ]

    def catalogue(self) -> str:
        return "\n".join(f"- {a.name}: {a.purpose} (tools: {', '.join(a.tools)})"
                         for a in self.agents.values())

    async def run(
        self,
        agent_name: str,
        task: str,
        *,
        context: str = "",
        on_event: Any = None,
    ) -> AgentResult:
        agent = self.agents.get(agent_name)
        if agent is None:
            return AgentResult(agent_name, f"Unknown agent {agent_name!r}.",
                               errors=[f"unknown agent {agent_name}"])

        messages: list[dict[str, str]] = [
            {"role": "system", "content": agent.system_prompt(self.toolbox, list(self.agents))},
        ]
        if context:
            messages.append({"role": "system", "content": f"CONTEXT YOU MAY USE:\n{context}"})
        messages.append({"role": "user", "content": f"TASK: {task}"})

        result = AgentResult(agent=agent.name, answer="")
        # Signature -> output, so an identical call can be recognised instead of
        # being run again. A 7B model will otherwise retry the same broken
        # command until it runs out of turns.
        seen: dict[str, str] = {}
        repeats = 0

        for turn in range(1, self.config.agent_max_turns + 1):
            result.turns = turn
            try:
                decision = await self.llm.chat_json(messages, DECISION_SCHEMA)
            except LLMError as e:
                result.errors.append(f"llm: {e}")
                result.answer = result.answer or f"The model failed to respond: {e}"
                return result

            action = (decision.get("action") or "").strip()
            thought = (decision.get("thought") or "").strip()
            if on_event:
                on_event({"type": "thought", "agent": agent.name, "turn": turn,
                          "text": thought, "action": action})

            if action == "final_answer":
                result.answer = (decision.get("answer") or "").strip()
                if not result.answer and result.tool_calls:
                    # Model signalled done without writing anything: fall back to
                    # the last useful observation rather than returning nothing.
                    result.answer = result.tool_calls[-1].get("output", "")
                return result

            if action == "delegate":
                target = (decision.get("delegate_to") or "").strip()
                if target in self.agents and target != agent.name:
                    result.delegate_to = target
                    result.delegate_task = (decision.get("delegate_task") or task).strip()
                    return result
                messages.append({"role": "assistant", "content": _brief(decision)})
                messages.append({"role": "user", "content":
                                 f"OBSERVATION: cannot delegate to {target!r}. "
                                 f"Valid agents: {', '.join(n for n in self.agents if n != agent.name)}. "
                                 f"Continue yourself or pick a valid agent."})
                continue

            if action == "use_tool":
                tool_name = (decision.get("tool") or "").strip()
                raw_args = decision.get("args")
                args = raw_args if isinstance(raw_args, dict) else {}

                if tool_name not in agent.tools:
                    allowed = ", ".join(agent.tools)
                    messages.append({"role": "assistant", "content": _brief(decision)})
                    messages.append({"role": "user", "content":
                                     f"OBSERVATION: {tool_name!r} is not available to you. "
                                     f"Your tools: {allowed}. Pick one of those, delegate, or answer."})
                    continue

                signature = f"{tool_name}:{json.dumps(args, sort_keys=True, default=str)}"
                if signature in seen:
                    repeats += 1
                    if repeats >= 2:
                        result.errors.append(f"{tool_name}: repeated the same call")
                        result.answer = await self._summarise(task, result)
                        return result
                    others = ", ".join(t for t in agent.tools if t != tool_name)
                    messages.append({"role": "assistant", "content": _brief(decision)})
                    messages.append({"role": "user", "content":
                                     f"OBSERVATION: you already ran that exact call and got:\n"
                                     f"{seen[signature][:500]}\n\n"
                                     f"Repeating it will not help. Either change the arguments "
                                     f"substantially, use a different tool ({others}), or give "
                                     f"final_answer with what you already know."})
                    continue

                call = await self.toolbox.run(tool_name, args)
                seen[signature] = call.output
                result.tool_calls.append(call.as_dict())
                if not call.ok:
                    result.errors.append(f"{tool_name}: {call.output[:160]}")
                if on_event:
                    on_event({"type": "tool", "agent": agent.name, "turn": turn,
                              "tool": tool_name, "args": args, "ok": call.ok,
                              "output": call.output[:400]})

                messages.append({"role": "assistant", "content": _brief(decision)})
                messages.append({"role": "user", "content":
                                 f"OBSERVATION from {tool_name}:\n{call.output}\n\n"
                                 f"(turn {turn}/{self.config.agent_max_turns}) "
                                 f"Use another tool if needed, otherwise give final_answer."})
                continue

            # Unrecognised action — nudge and retry.
            messages.append({"role": "assistant", "content": _brief(decision)})
            messages.append({"role": "user", "content":
                             'OBSERVATION: "action" must be use_tool, delegate or final_answer. '
                             "Try again."})

        # Ran out of turns: salvage the best material we have.
        result.errors.append(f"reached turn limit ({self.config.agent_max_turns})")
        result.answer = await self._summarise(task, result)
        return result

    async def _summarise(self, task: str, result: AgentResult) -> str:
        """Turn-limit fallback: force one plain-text answer from what was gathered."""
        if not result.tool_calls:
            return "I could not complete this task within the allowed number of steps."
        findings = "\n\n".join(
            f"{c['tool']} -> {c['output'][:600]}" for c in result.tool_calls[-4:]
        )
        try:
            return await self.llm.chat([
                {"role": "system", "content":
                 "Answer the user's task using only the findings below. Plain text, no JSON."},
                {"role": "user", "content": f"TASK: {task}\n\nFINDINGS:\n{findings}"},
            ])
        except LLMError:
            return findings


def _brief(decision: dict[str, Any]) -> str:
    """Compact echo of the model's own decision, to keep context small."""
    keep = {k: v for k, v in decision.items() if k in
            ("thought", "action", "tool", "args") and v}
    return json.dumps(keep, default=str)[:600]
