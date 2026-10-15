"""Interactive terminal for JANOS.

    python3 -m janos.cli              # REPL
    python3 -m janos.cli "a question" # one shot
    python3 -m janos.cli --quiet ...  # answer only, no trace
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Any

from janos.config import Config
from janos.supervisor import Supervisor

C = {
    "dim": "\033[2m", "bold": "\033[1m", "reset": "\033[0m",
    "cyan": "\033[36m", "green": "\033[32m", "yellow": "\033[33m",
    "red": "\033[31m", "blue": "\033[34m", "magenta": "\033[35m",
}


def _paint(enabled: bool):
    if enabled and sys.stdout.isatty():
        return lambda s, c: f"{C.get(c, '')}{s}{C['reset']}"
    return lambda s, c: s


BANNER = r"""
     ██  █████  ███    ██  ██████  ███████
     ██ ██   ██ ████   ██ ██    ██ ██
     ██ ███████ ██ ██  ██ ██    ██ ███████
██   ██ ██   ██ ██  ██ ██ ██    ██      ██
 █████  ██   ██ ██   ████  ██████  ███████
"""

HELP = """
Commands
  /help                this message
  /health              model, agents, tools, memory status
  /stats               memory and learning statistics
  /agents              the agent roster
  /tools               available tools
  /lessons             what JANOS has learned so far
  /recent [n]          recent episodes
  /rankings            which agent performs best per task type
  /trace on|off        show or hide the live reasoning trace
  /quit                exit

Anything else is treated as a task.
"""


def make_printer(paint, state: dict[str, Any]):
    def show(ev: dict[str, Any]) -> None:
        if not state["trace"]:
            return
        t = ev.get("type")
        if t == "recall" and ev.get("episodes"):
            print(paint(f"  ⟲ recalled {ev['episodes']} similar episode(s)", "dim"))
        elif t == "triage":
            print(paint(f"  ◆ {ev.get('task_type')} / {ev.get('complexity')}"
                        f" → {ev.get('agent')}", "cyan"))
        elif t == "plan":
            print(paint("  ▸ plan:", "cyan"))
            for i, s in enumerate(ev.get("steps", []), 1):
                print(paint(f"      {i}. [{s['agent']}] {s['step']}", "dim"))
        elif t == "step":
            print(paint(f"  ▸ step {ev['index']}/{ev['total']} · {ev['agent']}", "blue"))
        elif t == "delegate":
            print(paint(f"    ⇄ {ev['from']} → {ev['to']}: {ev['task'][:70]}", "magenta"))
        elif t == "thought" and ev.get("text"):
            print(paint(f"    · {ev['text'][:110]}", "dim"))
        elif t == "tool":
            mark = "✓" if ev.get("ok") else "✗"
            colour = "green" if ev.get("ok") else "red"
            args = ", ".join(f"{k}={str(v)[:36]}" for k, v in (ev.get("args") or {}).items())
            print(paint(f"    {mark} {ev['tool']}({args})", colour))
        elif t == "verify":
            tag = f"retry {ev['retry']}" if ev.get("retry") else "verify"
            colour = "green" if ev.get("ok") else "yellow"
            print(paint(f"  ⊙ {tag}: score {ev.get('score', 0):.2f}"
                        + ("" if ev.get("ok") else f" — {'; '.join(ev.get('issues') or [])[:90]}"),
                        colour))
        elif t == "heal":
            print(paint(f"  ⟳ self-healing (attempt {ev['attempt']}): {ev['hint'][:90]}", "yellow"))
        elif t == "lesson":
            print(paint(f"  ★ learned: {ev['text']}", "magenta"))
    return show


async def run_command(sup: Supervisor, cmd: str, paint, state: dict[str, Any]) -> bool:
    """Handle a /command. Returns False to exit."""
    parts = cmd.split()
    name = parts[0].lower()

    if name in ("/quit", "/exit", "/q"):
        return False

    if name == "/help":
        print(HELP)

    elif name == "/health":
        h = await sup.health()
        llm = h["llm"]
        ok = paint("ready", "green") if h["ok"] else paint("NOT READY", "red")
        print(f"  status : {ok}")
        print(f"  model  : {llm['model']} ({'installed' if llm['model_ready'] else 'MISSING'})")
        print(f"  ollama : {'reachable' if llm['reachable'] else 'unreachable'}")
        print(f"  agents : {', '.join(h['agents'])}")
        print(f"  tools  : {', '.join(h['tools'])}")
        print(f"  memory : {h['memory']['episodes']} episodes, "
              f"{h['memory']['lessons']} lessons, avg {h['memory']['avg_score']}")
        if not llm["model_ready"]:
            print(paint(f"\n  Run: ollama pull {llm['model']}", "yellow"))

    elif name == "/stats":
        s = sup.memory.stats()
        print(f"  episodes    : {s['episodes']}")
        print(f"  avg score   : {s['avg_score']}")
        print(f"  self-healed : {s['self_healed']}")
        print(f"  lessons     : {s['lessons']}")
        if s["by_task_type"]:
            print("  task types  : " + ", ".join(f"{k}×{v}" for k, v in s["by_task_type"].items()))
        for t in s["tools"][:10]:
            print(f"    {t['tool']:<14} {t['calls']} calls, {t['failures']} failed")

    elif name == "/agents":
        for a in sup.runner.roster():
            print(f"  {paint(a['name'], 'bold')} — {a['role']}")
            print(f"      {a['purpose']}")
            print(paint(f"      tools: {', '.join(a['tools'])}", "dim"))

    elif name == "/tools":
        print(sup.toolbox.describe())

    elif name == "/lessons":
        lessons = sup.memory.all_lessons()
        if not lessons:
            print("  Nothing learned yet — give it some tasks.")
        for l in lessons:
            print(f"  [{l['task_type']}] {l['lesson']}")
            print(paint(f"      weight {l['weight']}, recalled {l['hits']}×", "dim"))

    elif name == "/recent":
        n = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 10
        for e in sup.memory.recent(n):
            heal = " ⟳" if e["healed"] else ""
            print(f"  {e['ts'][:16]}  {e['score']:.2f}{heal}  [{e['task_type']}] {e['task'][:60]}")

    elif name == "/rankings":
        rows = sup.memory.rankings()
        if not rows:
            print("  No routing data yet.")
        for r in rows:
            print(f"  {r['agent']:<12} {r['task_type']:<14} {r['runs']:>3} runs  avg {r['avg_score']}")

    elif name == "/trace":
        if len(parts) > 1:
            state["trace"] = parts[1].lower() in ("on", "true", "1", "yes")
        print(f"  trace {'on' if state['trace'] else 'off'}")

    else:
        print(paint(f"  Unknown command {name}. Try /help", "yellow"))

    return True


async def main_async(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="janos", description="Local autonomous agent system")
    ap.add_argument("task", nargs="*", help="run one task and exit")
    ap.add_argument("--quiet", "-q", action="store_true", help="answer only")
    ap.add_argument("--no-color", action="store_true")
    ap.add_argument("--model", help="override the Ollama model")
    args = ap.parse_args(argv)

    paint = _paint(not args.no_color)
    config = Config.load()
    if args.model:
        config.model = args.model

    state = {"trace": not args.quiet}
    sup = Supervisor(config)
    sup.on_event = make_printer(paint, state)

    health = await sup.health()
    if not health["ok"]:
        llm = health["llm"]
        print(paint("JANOS cannot start:", "red"))
        if not llm["reachable"]:
            print(f"  Ollama is not reachable at {config.ollama_url}")
            print(paint("  Start it with:  ollama serve", "yellow"))
        elif not llm["model_ready"]:
            print(f"  Model {llm['model']!r} is not installed.")
            print(paint(f"  Install it with:  ollama pull {llm['model']}", "yellow"))
            if llm["models_installed"]:
                print(f"  Installed: {', '.join(llm['models_installed'])}")
        sup.close()
        return 1

    # ---- one-shot ------------------------------------------------------
    if args.task:
        turn = await sup.handle(" ".join(args.task))
        if not args.quiet:
            print()
        print(turn.answer)
        sup.close()
        return 0

    # ---- REPL ----------------------------------------------------------
    print(paint(BANNER, "cyan"))
    print(f"  {paint('local · autonomous · self-healing', 'dim')}")
    print(f"  model {paint(config.model, 'bold')} · "
          f"{len(sup.runner.agents)} agents · {len(sup.toolbox.names())} tools · "
          f"{sup.memory.stats()['episodes']} episodes remembered")
    print(f"  {paint('/help for commands, /quit to exit', 'dim')}\n")

    while True:
        try:
            line = input(paint("you › ", "bold")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line.startswith("/"):
            try:
                if not await run_command(sup, line, paint, state):
                    break
            except Exception as e:
                print(paint(f"  command failed: {e}", "red"))
            print()
            continue

        try:
            turn = await sup.handle(line)
        except KeyboardInterrupt:
            print(paint("\n  interrupted", "yellow"))
            continue
        except Exception as e:
            print(paint(f"  error: {type(e).__name__}: {e}", "red"))
            continue

        print(f"\n{paint('janos ›', 'green')} {turn.answer}\n")
        if state["trace"]:
            bits = [f"{turn.duration_ms/1000:.1f}s", f"score {turn.score:.2f}",
                    f"{len(turn.tool_calls)} tool calls"]
            if turn.heal_attempts:
                bits.append(f"{turn.heal_attempts} self-heal")
            print(paint("  " + " · ".join(bits) + "\n", "dim"))

    sup.close()
    print(paint("  goodbye.", "dim"))
    return 0


def main() -> int:
    try:
        return asyncio.run(main_async())
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
