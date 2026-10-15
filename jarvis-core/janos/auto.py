"""Autonomous mode — JANOS working unattended.

    python3 -m janos.auto                      # run until stopped
    python3 -m janos.auto --cycles 20          # bounded run
    python3 -m janos.auto --interval 120       # seconds between cycles

Each cycle it chooses its own goal, runs the full supervisor pipeline on it,
and keeps what it learned. Goals come from four sources, used in rotation so
the night's work stays varied:

  goals        the next unfinished line of workspace/goals.md, if you left any
  repair       a past request that scored badly, retried with what it now knows
  research     a topic it decides is worth learning, researched on the web
  extend       a capability gap it noticed, closed by writing itself a tool

Stopping: Ctrl-C, or create the file workspace/STOP. Both finish the cycle in
progress and shut down cleanly. Every cycle is appended to a dated log in the
workspace, so there is a readable record waiting in the morning.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import signal
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from janos.config import Config
from janos.llm import LLMError
from janos.supervisor import Supervisor

GOAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "goal": {"type": "string"},
        "why": {"type": "string"},
    },
    "required": ["goal"],
}

GAP_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "needed": {"type": "boolean"},
        "kind": {"type": "string", "enum": ["skill", "playbook"]},
        "tool_name": {"type": "string"},
        "purpose": {"type": "string"},
    },
    "required": ["needed"],
}

SEED_TOPICS = [
    "practical Linux command-line techniques worth knowing",
    "how local LLM inference performance is tuned on consumer GPUs",
    "useful free public APIs that need no API key",
    "recent developments in open-weight language models",
    "Python asyncio patterns that avoid common mistakes",
    "SQLite features that replace heavier databases",
]


@dataclass
class Cycle:
    n: int
    kind: str
    goal: str
    answer: str = ""
    score: float = 0.0
    tools: list[str] = field(default_factory=list)
    agents: list[str] = field(default_factory=list)
    lesson: str = ""
    seconds: float = 0.0
    error: str = ""


class AutonomousLoop:
    def __init__(self, config: Config | None = None, *, interval: int = 300,
                 cycles: int = 0, verbose: bool = True):
        self.config = config or Config.load()
        self.interval = max(10, interval)
        self.max_cycles = cycles          # 0 = unbounded
        self.verbose = verbose
        self.sup = Supervisor(self.config)
        self.stop_file = self.config.workspace / "STOP"
        self.goals_file = self.config.workspace / "goals.md"
        self.lock_file = self.config.memory_dir / "autorun.pid"
        self.log_file = (self.config.workspace /
                         f"autorun-{datetime.now().strftime('%Y-%m-%d')}.md")
        self._stopping = False
        self._rotation = ["goals", "repair", "research", "extend"]
        self._history: list[Cycle] = []

    # ---------------------------------------------------------------- output

    def _say(self, text: str, dim: bool = False) -> None:
        if self.verbose:
            stamp = datetime.now().strftime("%H:%M:%S")
            print(f"\033[2m{stamp}\033[0m {'\033[2m' if dim else ''}{text}"
                  f"{'\033[0m' if dim else ''}", flush=True)

    def _log(self, cycle: Cycle) -> None:
        first = not self.log_file.exists()
        with open(self.log_file, "a", encoding="utf-8") as fh:
            if first:
                fh.write(f"# JANOS autonomous run — {datetime.now():%Y-%m-%d}\n")
            fh.write(f"\n## Cycle {cycle.n} · {cycle.kind} · {datetime.now():%H:%M:%S}\n\n")
            fh.write(f"**Goal:** {cycle.goal}\n\n")
            if cycle.error:
                fh.write(f"**Error:** {cycle.error}\n")
                return
            fh.write(f"**Score:** {cycle.score:.2f} · "
                     f"{cycle.seconds:.0f}s · agents: {', '.join(cycle.agents) or '—'} · "
                     f"tools: {', '.join(cycle.tools) or '—'}\n\n")
            fh.write(f"{cycle.answer}\n")
            if cycle.lesson:
                fh.write(f"\n> **Learned:** {cycle.lesson}\n")

    # ----------------------------------------------------------- goal choice

    def _pending_user_goals(self) -> list[str]:
        """Unchecked markdown checklist items from workspace/goals.md."""
        if not self.goals_file.exists():
            return []
        out = []
        for line in self.goals_file.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s.startswith(("- [ ]", "* [ ]")):
                out.append(s[5:].strip())
            elif s.startswith(("- ", "* ")) and not s.startswith(("- [x]", "* [x]")):
                out.append(s[2:].strip())
        return [g for g in out if g]

    def _tick_off(self, goal: str) -> None:
        """Mark a user goal done so it is not repeated."""
        if not self.goals_file.exists():
            return
        text = self.goals_file.read_text(encoding="utf-8")
        for prefix in ("- [ ] ", "* [ ] ", "- ", "* "):
            if f"{prefix}{goal}" in text:
                text = text.replace(f"{prefix}{goal}", f"- [x] {goal}", 1)
                self.goals_file.write_text(text, encoding="utf-8")
                return

    async def _research_goal(self) -> str:
        """Decide what is worth learning next, grounded in what it already knows."""
        known = self.sup.memory.all_lessons(limit=12)
        recent = self.sup.memory.recent(8)
        context = ""
        if known:
            context += "Already learned:\n" + "\n".join(f"- {l['lesson'][:120]}" for l in known)
        if recent:
            context += "\n\nRecently worked on:\n" + "\n".join(
                f"- {e['task'][:90]}" for e in recent)

        try:
            out = await self.sup.llm.chat_json(
                [{"role": "system", "content":
                  "You choose what an autonomous assistant should research next. "
                  "Pick something concrete and useful that it does not already know."},
                 {"role": "user", "content":
                  f"{context}\n\nChoose ONE specific thing to research on the web now. "
                  f"Phrase `goal` as an instruction beginning 'Search the web and ...'. "
                  f"Do not repeat anything already learned above."}],
                GOAL_SCHEMA, temperature=0.7,
            )
            goal = (out.get("goal") or "").strip()
            if len(goal) > 15:
                return goal
        except LLMError:
            pass
        return f"Search the web and summarise the key points about {random.choice(SEED_TOPICS)}."

    async def _extend_goal(self) -> str | None:
        """Notice a capability gap and turn it into a tool-building goal."""
        # Full descriptions, not just names: given bare names the model proposes
        # tools that duplicate ones it already has (a "gpu_vram_usage" beside
        # system_info, which already reports exactly that).
        have = self.sup.toolbox.describe()
        failures = self.sup.memory.unresolved(k=5, threshold=self.config.min_pass_score)
        failure_text = "\n".join(
            f"- {f['task'][:100]} (best score {f['best']:.2f} over {f['tries']} tries)"
            for f in failures) or "none — everything attempted has eventually succeeded"

        try:
            out = await self.sup.llm.chat_json(
                [{"role": "system", "content":
                  "You decide whether an autonomous assistant needs a new tool. "
                  "You are conservative: a new tool is justified only by a capability "
                  "that no listed tool provides."},
                 {"role": "user", "content":
                  f"Tools it already has:\n{have}\n\n"
                  f"Requests it has never managed to answer well:\n{failure_text}\n\n"
                  f"Is there ONE genuinely missing capability worth building?\n"
                  f"Read the tool list carefully first. Set needed=false if ANY listed "
                  f"tool already covers it, even partially — duplicating an existing "
                  f"tool is worse than building nothing. Note that system_info already "
                  f"reports CPU, RAM, disk and GPU; shell can run any command; "
                  f"run_python can compute anything; web_search and web_fetch cover "
                  f"the open internet.\n"
                  f"If something is genuinely missing, give a snake_case tool_name and a "
                  f"precise purpose stating what it does and what it returns.\n"
                  f"Set kind='playbook' when the capability is only a sequence of the "
                  f"existing tools above (search then fetch then summarise, etc.). Set "
                  f"kind='skill' only when it needs NEW code such as a new API or parser."}],
                GAP_SCHEMA, temperature=0.3,
            )
        except LLMError:
            return None

        if not out.get("needed"):
            return None
        purpose = (out.get("purpose") or "").strip()
        name = (out.get("tool_name") or "").strip()
        if len(purpose) < 20:
            return None
        builder = "create_playbook" if out.get("kind") == "playbook" else "create_tool"
        return (f"Use the {builder} tool to build a new tool named {name!r} that does "
                f"this: {purpose}. Then call it once to prove it works.")

    async def _next_goal(self, n: int) -> tuple[str, str] | None:
        """Pick this cycle's goal, rotating through the four sources."""
        order = self._rotation[(n - 1) % len(self._rotation):] + \
                self._rotation[: (n - 1) % len(self._rotation)]

        for kind in order:
            if kind == "goals":
                pending = self._pending_user_goals()
                if pending:
                    return "goals", pending[0]

            elif kind == "repair":
                for f in self.sup.memory.unresolved(k=5,
                                                    threshold=self.config.min_pass_score):
                    task = f["task"]
                    # Don't re-attempt something already retried this session.
                    if not any(c.goal == task for c in self._history):
                        return "repair", task

            elif kind == "research":
                return "research", await self._research_goal()

            elif kind == "extend":
                goal = await self._extend_goal()
                if goal:
                    return "extend", goal

        return "research", await self._research_goal()

    # ------------------------------------------------------------------ loop

    def request_stop(self, *_: Any) -> None:
        if not self._stopping:
            self._stopping = True
            self._say("\033[33mstopping after this cycle…\033[0m")

    def _should_stop(self) -> bool:
        if self._stopping:
            return True
        if self.stop_file.exists():
            self._say("\033[33mSTOP file found — shutting down.\033[0m")
            return True
        return False

    def _claim_lock(self) -> bool:
        """Refuse to start if another loop is already running.

        Two loops share one SQLite file and one goals.md; they tick the same
        goals off twice and interleave their episodes. Easy to do by accident
        when starting it in the background.
        """
        if self.lock_file.exists():
            try:
                pid = int(self.lock_file.read_text().strip())
            except (ValueError, OSError):
                pid = 0
            if pid > 0:
                try:
                    os.kill(pid, 0)          # signal 0 only tests existence
                except ProcessLookupError:
                    pass                      # stale lock from a killed run
                except PermissionError:
                    return False              # alive, owned by someone else
                else:
                    print(f"Autonomous mode is already running (pid {pid}).")
                    print(f"Stop it first:  touch {self.stop_file}")
                    return False
        self.lock_file.write_text(str(os.getpid()), encoding="utf-8")
        return True

    def _release_lock(self) -> None:
        try:
            if self.lock_file.exists() and self.lock_file.read_text().strip() == str(os.getpid()):
                self.lock_file.unlink()
        except OSError:
            pass

    async def run(self) -> int:
        health = await self.sup.health()
        if not health["ok"]:
            print("Cannot start autonomous mode: model or Ollama not ready.")
            print(json.dumps(health["llm"], indent=2))
            return 1
        if not self._claim_lock():
            return 1

        self._say(f"\033[1mautonomous mode\033[0m · {self.config.model} · "
                  f"every {self.interval}s · "
                  f"{'unbounded' if not self.max_cycles else f'{self.max_cycles} cycles'}")
        self._say(f"log: {self.log_file}", dim=True)
        self._say(f"stop with Ctrl-C or: touch {self.stop_file}", dim=True)

        n = 0
        while not self._should_stop():
            if self.max_cycles and n >= self.max_cycles:
                break
            n += 1
            started = time.perf_counter()

            try:
                picked = await self._next_goal(n)
            except Exception as e:
                self._say(f"\033[31mgoal selection failed: {e}\033[0m")
                await self._wait()
                continue
            if picked is None:
                break
            kind, goal = picked

            self._say(f"\033[36m[{n}] {kind}\033[0m {goal[:110]}")
            cycle = Cycle(n=n, kind=kind, goal=goal)

            try:
                turn = await self.sup.handle(goal)
                cycle.answer = turn.answer
                cycle.score = turn.score
                cycle.tools = sorted({c["tool"] for c in turn.tool_calls})
                cycle.agents = turn.agents_used
                cycle.lesson = turn.lesson
            except Exception as e:
                cycle.error = f"{type(e).__name__}: {e}"
                self._say(f"\033[31m    failed: {cycle.error}\033[0m")

            cycle.seconds = time.perf_counter() - started
            self._history.append(cycle)
            self._log(cycle)

            if not cycle.error:
                self._say(f"    score {cycle.score:.2f} · {cycle.seconds:.0f}s · "
                          f"tools: {', '.join(cycle.tools) or '—'}", dim=True)
                if cycle.lesson:
                    self._say(f"    \033[35m★ {cycle.lesson[:100]}\033[0m")
                if kind == "goals" and cycle.score >= self.config.min_pass_score:
                    self._tick_off(goal)

            if self._should_stop():
                break
            await self._wait()

        self._summarise()
        self._release_lock()
        self.sup.close()
        return 0

    async def _wait(self) -> None:
        """Sleep between cycles, checking for the stop signal as we go."""
        for _ in range(self.interval):
            if self._should_stop():
                return
            await asyncio.sleep(1)

    def _summarise(self) -> None:
        done = [c for c in self._history if not c.error]
        lessons = [c.lesson for c in self._history if c.lesson]
        stats = self.sup.memory.stats()

        self._say("")
        self._say(f"\033[1mran {len(self._history)} cycle(s)\033[0m")
        if done:
            avg = sum(c.score for c in done) / len(done)
            self._say(f"  average score   {avg:.2f}")
        self._say(f"  lessons learned {len(lessons)} this run, {stats['lessons']} total")
        self._say(f"  episodes stored {stats['episodes']}")
        built = self.sup.forge.generated_names() + self.sup.playbooks.names()
        if built:
            self._say(f"  self-written tools: {', '.join(built)}")
        self._say(f"  full log: {self.log_file}")

        with open(self.log_file, "a", encoding="utf-8") as fh:
            fh.write(f"\n---\n\n## Session summary\n\n")
            fh.write(f"- cycles: {len(self._history)}\n")
            if done:
                fh.write(f"- average score: {sum(c.score for c in done)/len(done):.2f}\n")
            fh.write(f"- lessons this run: {len(lessons)}\n")
            fh.write(f"- total episodes: {stats['episodes']}, lessons: {stats['lessons']}\n")
            if built:
                fh.write(f"- self-written tools: {', '.join(built)}\n")
            for l in lessons:
                fh.write(f"  - {l}\n")


async def main_async() -> int:
    ap = argparse.ArgumentParser(prog="janos.auto", description="Run JANOS autonomously")
    ap.add_argument("--interval", type=int, default=300, help="seconds between cycles")
    ap.add_argument("--cycles", type=int, default=0, help="stop after N cycles (0 = unbounded)")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    loop = AutonomousLoop(interval=args.interval, cycles=args.cycles, verbose=not args.quiet)
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            asyncio.get_running_loop().add_signal_handler(sig, loop.request_stop)
        except (NotImplementedError, RuntimeError):
            signal.signal(sig, loop.request_stop)

    # A leftover STOP file from a previous run would halt this one immediately.
    loop.stop_file.unlink(missing_ok=True)
    return await loop.run()


def main() -> int:
    try:
        return asyncio.run(main_async())
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
