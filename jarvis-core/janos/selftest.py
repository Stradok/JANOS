"""End-to-end self-test.

    python3 -m janos.selftest          # everything, including live model calls
    python3 -m janos.selftest --offline # skip anything needing Ollama or network

Exits non-zero if any check fails, so it is usable in a Makefile or CI step.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

from janos.auto import AutonomousLoop
from janos.config import Config
from janos.employee import Employee, parse_events, SNAP_BIN
from janos.forge import (_looks_like_failure, _parse_name, _parse_params, _scan)
from janos.memory import Memory
from janos.supervisor import Supervisor, check_arithmetic
from janos.tools import Toolbox

PASS, FAIL = "\033[32mPASS\033[0m", "\033[31mFAIL\033[0m"
_results: list[tuple[bool, str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    _results.append((ok, name, detail))
    print(f"  {PASS if ok else FAIL}  {name}" + (f"  — {detail}" if detail and not ok else ""))
    return ok


def section(title: str) -> None:
    print(f"\n\033[1m{title}\033[0m")


# ---------------------------------------------------------------- offline

def test_config() -> None:
    section("Configuration")
    c = Config.load()
    check("config loads", bool(c.model))
    check("single model configured", isinstance(c.model, str) and ":" in c.model, c.model)
    check("memory dir exists", c.memory_dir.is_dir(), str(c.memory_dir))
    check("workspace exists", c.workspace.is_dir(), str(c.workspace))


def test_memory() -> None:
    section("Memory (SQLite + FTS5)")
    with tempfile.TemporaryDirectory() as tmp:
        m = Memory(Path(tmp) / "t.db")

        m.remember(task="what GPU do I have", answer="RTX 4060 8GB",
                   task_type="system", score=0.9, agents=["operator"])
        m.remember(task="calculate 2+2", answer="4",
                   task_type="calculation", score=1.0, agents=["analyst"])

        check("recall finds relevant episode",
              any("GPU" in r["task"] for r in m.recall("gpu")))
        check("recall of unknown topic is empty", m.recall("zzzznothing") == [])

        # FTS5 operators in user text must not raise.
        hostile = ['what\'s "2+2"? * ^ NEAR("a" "b")', "", "???", "a AND b OR", "--;DROP"]
        ok = True
        for h in hostile:
            try:
                m.recall(h)
                m.lessons_for(h)
            except Exception as e:  # noqa: BLE001
                ok = False
                check(f"hostile FTS input {h!r}", False, str(e))
        check("hostile FTS input handled", ok)

        check("lesson stored", m.add_lesson("Use system_info for hardware questions.",
                                            task_type="system"))
        check("duplicate lesson rejected",
              not m.add_lesson("use system_info for hardware questions",
                               task_type="system"))
        check("lesson recalled", bool(m.lessons_for("hardware gpu")))

        for _ in range(4):
            m.record_agent("operator", "system", 0.9)
        check("running average correct",
              abs(m.rankings()[0]["avg_score"] - 0.9) < 0.01,
              str(m.rankings()[:1]))
        check("best_agent_for finds proven agent", m.best_agent_for("system") == "operator")
        check("best_agent_for withholds without evidence",
              m.best_agent_for("neverseen") is None)

        s = m.stats()
        check("stats report episodes", s["episodes"] == 2, str(s))
        m.close()


def test_arithmetic() -> None:
    section("Deterministic arithmetic guard")
    wrong = [
        "Using 5679 MiB of its total 8188 MiB VRAM, which is approximately 95.0%.",
        "Disk: 155 of 233 GB, that's 90%",
        "3 out of 4 tests passed, a 20% pass rate.",
    ]
    right = [
        "Using 5679 MiB of its total 8188 MiB VRAM, which is approximately 69.4%.",
        "RAM: 12.1 of 14.0 GiB used (86.4%)",
        "CPU: 6C/12T at 0.8% load\nRAM: 9.2 GiB used (61.3% of 15.0 GiB)",
        "Available 24/7 with 99% uptime.",
        "Revenue grew from 5 to 10, a 100% increase.",
        "The disk is 159 of 233 GiB full. Separately, CPU load is 3%.",
    ]
    check("catches wrong percentages", all(check_arithmetic(t) for t in wrong))
    check("no false positives", not any(check_arithmetic(t) for t in right),
          str([t for t in right if check_arithmetic(t)]))


def test_capability_guard() -> None:
    section("Capability guard")
    s = Supervisor.__new__(Supervisor)  # pure helper, no LLM needed
    cases: list[tuple[str, set[str]]] = [
        ("write a summary to specs.md", {"write_file"}),
        ("save the results to results.json", {"write_file"}),
        ("write a poem about the sea", set()),
        ("read notes.md and tell me what it says", set()),
        ("look up the weather in Islamabad", {"web_search"}),
        ("how much RAM am I using", {"system_info"}),
    ]
    ok = True
    for task, want in cases:
        got = Supervisor._required_tools(s, task)
        if got != want:
            ok = False
            check(f"required_tools({task[:34]!r})", False, f"got {sorted(got)} want {sorted(want)}")
    check("infers required tools from wording", ok)

    # Claimed side effects must be verified against the filesystem.
    cfg = Config.load()
    s.config = cfg
    present = cfg.workspace / "_selftest_present.md"
    present.write_text("x", encoding="utf-8")
    try:
        check("detects a file that was never written",
              Supervisor._missing_files(s, "save the results to _selftest_absent.md")
              == ["_selftest_absent.md"])
        check("accepts a file that exists",
              Supervisor._missing_files(s, "save the results to _selftest_present.md") == [])
        check("ignores requests that name no file",
              Supervisor._missing_files(s, "what is 2 + 2?") == [])
        check("ignores reads of a missing file",
              Supervisor._missing_files(s, "read _selftest_absent.md and summarise it") == [])
    finally:
        present.unlink(missing_ok=True)


def test_forge_validation() -> None:
    section("Self-extension guards")
    good = (
        '"""t."""\nNAME = "demo_tool"\nDESCRIPTION = "d"\nPARAMS = {"q": "str"}\n'
        'async def run(q: str = "") -> str:\n    return "ok"\n'
    )
    ok, why = _scan(good)
    check("accepts a well-formed tool", ok, why)
    check("reads NAME", _parse_name(good) == "demo_tool", _parse_name(good))
    check("reads PARAMS", _parse_params(good) == {"q": "str"}, str(_parse_params(good)))

    bad: list[tuple[str, str]] = [
        ("syntax error", 'NAME="x"\nasync def run(:\n'),
        ("sync run()", 'NAME="x"\nDESCRIPTION="d"\nPARAMS={}\ndef run() -> str:\n    return "x"\n'),
        ("missing DESCRIPTION", 'NAME="x"\nPARAMS={}\nasync def run() -> str:\n    return "x"\n'),
        ("missing PARAMS", 'NAME="x"\nDESCRIPTION="d"\nasync def run() -> str:\n    return "x"\n'),
        ("eval()", 'NAME="x"\nDESCRIPTION="d"\nPARAMS={}\nasync def run() -> str:\n    return str(eval("1"))\n'),
        ("exec()", 'NAME="x"\nDESCRIPTION="d"\nPARAMS={}\nasync def run() -> str:\n    exec("x=1")\n    return "x"\n'),
        ("pickle import", 'import pickle\nNAME="x"\nDESCRIPTION="d"\nPARAMS={}\nasync def run() -> str:\n    return "x"\n'),
        ("file deletion", 'NAME="x"\nDESCRIPTION="d"\nPARAMS={}\nasync def run() -> str:\n    import shutil\n    shutil.rmtree("/")\n    return "x"\n'),
        ("param without default", 'NAME="x"\nDESCRIPTION="d"\nPARAMS={}\nasync def run(q: str) -> str:\n    return q\n'),
        # A generated tool resolves relative paths against the CWD, not the
        # workspace, so it must return content rather than write it.
        ("writes via write_text", 'NAME="x"\nDESCRIPTION="d"\nPARAMS={}\nasync def run() -> str:\n    from pathlib import Path\n    Path("a.md").write_text("x")\n    return "ok"\n'),
        ("writes via open(w)", 'NAME="x"\nDESCRIPTION="d"\nPARAMS={}\nasync def run() -> str:\n    with open("a.md","w") as f:\n        f.write("x")\n    return "ok"\n'),
        ("scrapes google", 'NAME="x"\nDESCRIPTION="d"\nPARAMS={}\nasync def run() -> str:\n    import httpx\n    return httpx.get("https://www.google.com/search?q=x").text\n'),
    ]
    failures = [label for label, code in bad if _scan(code)[0]]
    check("rejects unsafe or malformed tools", not failures, f"wrongly accepted: {failures}")

    allowed = [
        ("reads a file", 'NAME="x"\nDESCRIPTION="d"\nPARAMS={}\nasync def run() -> str:\n    with open("a.md") as f:\n        return f.read()\n'),
        ("calls a JSON API", 'NAME="x"\nDESCRIPTION="d"\nPARAMS={}\nasync def run() -> str:\n    import httpx\n    return httpx.get("https://api.ipify.org").text\n'),
    ]
    wrongly_blocked = [label for label, code in allowed if not _scan(code)[0]]
    check("does not over-block legitimate tools", not wrongly_blocked, str(wrongly_blocked))

    fail_cases = [("Lookup failed: x", True), ("Traceback (most recent call last)", True),
                  ("Could not reach host", True), ("Error: nope", True),
                  ("100 USD = 27900 PKR", False), ("The failure rate is 3%", False),
                  ("UTC time: 12:00, Monday", False)]
    wrong = [t for t, want in fail_cases if _looks_like_failure(t) != want]
    check("detects failure-shaped tool output", not wrong, str(wrong))


def test_autonomy() -> None:
    section("Autonomous mode")
    loop = AutonomousLoop.__new__(AutonomousLoop)  # helpers only, no LLM
    loop.goals_file = Path(tempfile.mkdtemp()) / "goals.md"
    loop.goals_file.write_text(
        "# Goals\n- [ ] research quantum computing\n- [x] already done\n- plain bullet goal\n",
        encoding="utf-8",
    )
    pending = AutonomousLoop._pending_user_goals(loop)
    check("reads unchecked goals", "research quantum computing" in pending, str(pending))
    check("skips completed goals", "already done" not in pending, str(pending))

    AutonomousLoop._tick_off(loop, "research quantum computing")
    check("ticks a goal off after success",
          "- [x] research quantum computing" in loop.goals_file.read_text(),
          loop.goals_file.read_text())
    shutil.rmtree(loop.goals_file.parent, ignore_errors=True)

    # Single-instance lock: two loops would share one database and one
    # goals.md, ticking the same goals off twice.
    with tempfile.TemporaryDirectory() as tmp:
        loop.lock_file = Path(tmp) / "autorun.pid"
        loop.stop_file = Path(tmp) / "STOP"   # named in the "already running" message
        check("claims the lock when free", AutonomousLoop._claim_lock(loop))
        check("lock records this process",
              loop.lock_file.read_text().strip() == str(os.getpid()))
        check("refuses to start twice", not AutonomousLoop._claim_lock(loop))

        loop.lock_file.write_text("999999")   # a pid that cannot exist
        check("ignores a stale lock from a dead run", AutonomousLoop._claim_lock(loop))

        AutonomousLoop._release_lock(loop)
        check("releases the lock on exit", not loop.lock_file.exists())

    with tempfile.TemporaryDirectory() as tmp:
        m = Memory(Path(tmp) / "u.db")
        m.remember(task="hard task", answer="bad", score=0.2)
        m.remember(task="hard task", answer="good", score=0.9)   # later repaired
        m.remember(task="still broken", answer="bad", score=0.1)
        names = {r["task"] for r in m.unresolved()}
        check("unresolved excludes repaired tasks", "hard task" not in names, str(names))
        check("unresolved includes still-failing tasks", "still broken" in names, str(names))
        m.close()


async def test_tools() -> None:
    section("Tools")
    cfg = Config.load()
    tb = Toolbox(cfg)

    r = await tb.run("calculate", {"expression": "2**10 + 7*3"})
    check("calculate is exact", "1045" in r.output, r.output)

    r = await tb.run("calculate", {"expression": "0.18 * 340"})
    check("calculate hides float noise", r.output.endswith("= 61.2"), r.output)
    r = await tb.run("calculate", {"expression": "__import__('os').system('id')"})
    check("calculate refuses code execution", not r.output.startswith("__import__") and "error" in r.output.lower(), r.output)

    r = await tb.run("shell", {"command": "echo hello"})
    check("shell runs", "hello" in r.output, r.output)

    # Under /bin/sh, `echo -e` prints the literal "-e"; under bash it expands
    # the escape. Compare the command output only, not the echoed header.
    r = await tb.run("shell", {"command": "echo -e 'a\\nb'"})
    body = r.output.split("(exit 0)\n", 1)[-1].strip()
    check("shell is bash (echo -e expands escapes)", body == "a\nb", repr(body))

    r = await tb.run("shell", {"command": "rm -rf /"})
    check("shell refuses destructive command", "Refused" in r.output, r.output)

    r = await tb.run("shell", {"command": "sleep 30", "timeout": 2})
    check("shell honours timeout", "killed" in r.output.lower(), r.output)

    r = await tb.run("run_python", {"code": "print(sum(range(101)))"})
    check("run_python works", "5050" in r.output, r.output)

    r = await tb.run("system_info", {"what": "all"})
    check("system_info reports hardware", "RAM" in r.output and "Disk" in r.output)
    check("system_info percentages are self-consistent",
          not check_arithmetic(r.output), r.output)

    r = await tb.run("now", {})
    check("now returns a date", any(c.isdigit() for c in r.output), r.output)

    # Inside the workspace: writes outside it are refused by design, so a
    # /tmp scratch dir would exercise the guard rather than the tool.
    scratch = cfg.workspace / ".selftest"
    try:
        r = await tb.run("write_file", {"path": ".selftest/x.txt", "content": "hello janos"})
        p = scratch / "x.txt"
        check("write_file writes", p.exists() and p.read_text() == "hello janos", r.output)
        r = await tb.run("read_file", {"path": ".selftest/x.txt"})
        check("read_file reads", "hello janos" in r.output)
        r = await tb.run("list_dir", {"path": ".selftest"})
        check("list_dir lists", "x.txt" in r.output)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    r = await tb.run("write_file", {"path": "/etc/passwd", "content": "x"})
    check("write_file refuses paths outside workspace and home", "Refused" in r.output, r.output)

    r = await tb.run("shell", {"command": "sudo ss -tuln"})
    check("sudo fails fast with guidance", "sudo cannot be used here" in r.output, r.output[:160])

    r = await tb.run("does_not_exist", {})
    check("unknown tool returns error, does not raise", not r.ok and "No such tool" in r.output)

    r = await tb.run("calculate", {"wrong_arg": 1})
    check("bad arguments handled", isinstance(r.output, str))


async def test_network() -> None:
    section("Network tools")
    tb = Toolbox(Config.load())
    r = await tb.run("web_search", {"query": "capital of Kazakhstan", "max_results": 3})
    hit = "astana" in r.output.lower()
    check("web_search returns results", hit, r.output[:200])
    r = await tb.run("web_fetch", {"url": "https://example.com", "max_chars": 400})
    check("web_fetch extracts text", ("Example Domain" in r.output or "documentation examples" in r.output), r.output[:200])


# ----------------------------------------------------------------- online

async def test_llm(sup: Supervisor) -> bool:
    section("LLM")
    h = await sup.llm.health()
    ok = check("ollama reachable", h["reachable"])
    ok &= check(f"model {h['model']} installed", h["model_ready"],
                f"installed: {h['models_installed']}")
    if not ok:
        return False
    out = await sup.llm.chat_json(
        [{"role": "user", "content": "Return JSON with answer set to the number 4."}],
        {"type": "object", "properties": {"answer": {"type": "number"}}, "required": ["answer"]},
    )
    check("structured JSON output works", out.get("answer") == 4, str(out))
    return True


async def test_pipeline(sup: Supervisor) -> None:
    section("Full pipeline")

    turn = await sup.handle("what is 47 * 89 + 1234?")
    check("arithmetic task answered correctly", "5417" in turn.answer, turn.answer[:160])
    check("a tool was actually executed", len(turn.tool_calls) > 0,
          "no tool calls — the agent only talked")
    check("episode stored", bool(turn.episode_id))
    check("verification produced a score", turn.score > 0)

    turn = await sup.handle("How much RAM is in use on this machine right now?")
    check("system task used a tool",
          any(c["tool"] in ("system_info", "shell") for c in turn.tool_calls),
          str([c["tool"] for c in turn.tool_calls]))
    check("system answer has no arithmetic error",
          not check_arithmetic(turn.answer), turn.answer[:200])

    stats = sup.memory.stats()
    check("memory accumulated episodes", stats["episodes"] >= 2, str(stats))


async def test_sandbox() -> None:
    print("\n\033[1mSandbox\033[0m")
    from pathlib import Path
    from janos import sandbox
    from janos.tools import Toolbox
    cfg = Config.load()
    if not sandbox.available():
        check("bubblewrap available", False, "install bubblewrap; tools are running unsandboxed")
        return
    check("bubblewrap available", True)
    tb = Toolbox(cfg)
    home = Path.home()
    secret = home / ".claude"            # known to exist on the host
    # Read only the last line: the echoed command itself contains both words.
    r = await tb.run("shell", {"command": f"test -e {secret} && echo VISIBLE || echo HIDDEN"})
    last = r.output.strip().splitlines()[-1]
    check("shell cannot see home folder", last == "HIDDEN" and secret.exists(), last)
    r = await tb.run("shell", {"command": "touch /usr/janos_probe 2>&1; echo done"})
    check("shell cannot write outside workspace", "Read-only" in r.output, r.output[-80:])
    r = await tb.run("shell", {"command": "echo ok > sandbox_probe.txt && cat sandbox_probe.txt && rm sandbox_probe.txt"})
    check("shell can write in workspace", r.output.strip().endswith("ok"), r.output[-60:])
    r = await tb.run("shell", {"command": "ps -e --no-headers | wc -l"})
    procs = int((re.findall(r"\d+", r.output.split(")")[-1]) or ["0"])[-1])
    check("shell still sees the machine", procs > 10, f"{procs} processes")
    os.environ["JANOS_SELFTEST_SECRET"] = "leak-me"
    r = await tb.run("shell", {"command": "env | grep -c JANOS_SELFTEST_SECRET"})
    os.environ.pop("JANOS_SELFTEST_SECRET", None)
    check("shell gets no host environment", r.output.strip().splitlines()[-1] == "0", r.output[-40:])
    r = await tb.run("shell", {"command":
        "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus systemd-run --user --pipe true "
        ">/dev/null 2>&1 && echo ESCAPED || echo CONTAINED"})
    check("shell cannot escape via the session bus",
          r.output.strip().splitlines()[-1] == "CONTAINED", r.output[-60:])
    # Host processes are visible (ps works) but their root, cwd and environ must
    # not be: /proc/<pid>/root would otherwise reach the real home folder.
    me = os.getpid()
    r = await tb.run("shell", {"command":
        f"ls /proc/{me}/root/ >/dev/null 2>&1 && echo OP''EN:root; "
        f"ls /proc/{me}/cwd/ >/dev/null 2>&1 && echo OP''EN:cwd; "
        f"cat /proc/{me}/environ >/dev/null 2>&1 && echo OP''EN:environ; echo E''ND"})   # split markers: the command is echoed back
    check("shell cannot reach host processes via /proc",
          "OPEN:" not in r.output and r.output.strip().endswith("END"), r.output.splitlines()[-1])
    r = await tb.run("shell", {"command": f"kill -0 {me} 2>/dev/null && echo SIGNAL || echo NOSIGNAL"})
    check("shell cannot signal host processes", r.output.strip().splitlines()[-1] == "NOSIGNAL",
          r.output.strip().splitlines()[-1])
    probe = Path("/dev/shm/janos_selftest_probe")
    await tb.run("shell", {"command": f"touch {probe}"})
    check("shell /dev/shm is private", not probe.exists())
    probe.unlink(missing_ok=True)
    r = await tb.run("shell", {"command": "timeout 5 bash -c 'echo > /dev/tcp/1.1.1.1/443' 2>/dev/null && echo NET || echo NONET"})
    check("shell has no network by default", r.output.strip().splitlines()[-1] == "NONET", r.output[-40:])
    r = await tb.run("run_python", {"code": (
        "import socket\n"
        "try:\n    socket.create_connection(('1.1.1.1', 443), timeout=3); print('NET OPEN')\n"
        "except OSError:\n    print('NET BLOCKED')\n"
        f"import os; print('SECRET', os.path.exists({str(secret)!r}))\n"
        "import httpx; print('PKG OK')")})
    check("run_python has no network", "NET BLOCKED" in r.output, r.output)
    check("run_python cannot see home folder", "SECRET False" in r.output, r.output)
    check("run_python can import venv packages", "PKG OK" in r.output, r.output)


async def test_playbooks() -> None:
    print("\n\033[1mPlaybooks\033[0m")
    from janos.playbooks import PlaybookForge, validate
    from janos.tools import Toolbox
    tb = Toolbox(Config.load())
    good = {"name": "calc_twice", "description": "d", "params": {"x": "str=2+2"},
            "steps": [{"tool": "calculate", "args": {"expression": "{{x}}"}},
                      {"tool": "calculate", "args": {"expression": "3*3"}}],
            "output": "{{step1}} | {{step2}}"}
    check("playbook validates", validate(good, tb)[0], validate(good, tb)[1])
    bad = [({**good, "steps": [{"tool": "shell", "args": {"command": "ls"}}]}, "shell forbidden"),
           ({**good, "steps": [{"tool": "nope", "args": {}}]}, "unknown tool"),
           ({**good, "steps": [{"tool": "calculate", "args": {"expression": "{{step2}}"}}]}, "forward ref"),
           ({**good, "params": {"x": "str"}}, "param without default"),
           ({**good, "steps": [{"tool": "calculate", "args": {"bogus": "1"}}]}, "unknown arg")]
    for pb, label in bad:
        check(f"playbook rejects {label}", not validate(pb, tb)[0])
    forge = PlaybookForge(Config.load(), None, tb)  # type: ignore[arg-type]
    out = await forge.execute(good, {})
    check("playbook chains steps", out.strip() == "2+2 = 4 | 3*3 = 9", out)


async def test_voice() -> None:
    try:
        import faster_whisper, kokoro_onnx, openwakeword  # noqa: F401
        import numpy as np
        from janos.voice import FRAME, SR, Endpointer, Voice, _plain, to_16k
        cfg = Config.load()
        if not (cfg.memory_dir / "models" / "kokoro-v1.0.int8.onnx").exists():
            raise ImportError("kokoro model missing")
    except ImportError:
        print("\n\033[2m\033[33mskipping voice checks — run make janos-voice-setup\033[0m")
        return
    section("Voice (offline)")
    voice = Voice(cfg)
    i16 = lambda a: (np.clip(a, -1, 1) * 32767).astype(np.int16)
    sil = lambda s: np.zeros(int(s * SR), np.float32)
    say = lambda t: to_16k(*voice.synth(t))
    frames = lambda a: [i16(a)[i:i + FRAME] for i in range(0, len(a) - FRAME + 1, FRAME)]

    def peak(text: str) -> float:
        path = next(p for p in openwakeword.get_pretrained_model_paths() if "hey_jarvis" in p)
        m = openwakeword.Model(wakeword_model_paths=[path])
        return max(max(m.predict(f).values()) for f in frames(np.concatenate([sil(1), say(text), sil(1)])))

    audio, sr = voice.synth("Hello there, this is a test of the speech system.")
    amp = float(np.abs(audio).max())
    check("TTS produces speech", len(audio) / sr > 0.5 and amp > 0.05, f"{len(audio) / sr:.2f}s peak {amp:.3f}")
    p = peak("Hey Jarvis, what time is it?")
    check("wake word fires on 'hey jarvis'", p >= 0.5, f"peak {p:.2f}")
    p = peak("Good morning, how was your weekend?")
    check("wake word ignores other speech", p < 0.5, f"peak {p:.2f}")

    speech = say("Open the pod bay doors please.")
    ep, fed, stopped = Endpointer(), 0, False
    for f in frames(np.concatenate([speech, sil(2)])):
        fed += len(f)
        if stopped := ep.feed(f):
            break
    late = (fed - len(speech)) / SR
    check("endpointer stops after speech ends", stopped and ep.has_speech and late <= 1.6,
          f"stopped={stopped} speech={ep.has_speech} {late:.2f}s after end")
    quiet = Endpointer()
    n = next((k for k, f in enumerate(frames(sil(10)), 1) if quiet.feed(f)), None)
    check("endpointer gives up on silence", n is not None and not quiet.has_speech and n * FRAME / SR <= 7,
          f"frames={n} speech={quiet.has_speech}")
    heard = voice.transcribe(ep.audio()).lower()
    check("speech-to-text round trip", "pod" in heard and "doors" in heard, heard)
    out = _plain("**Done.** See https://x.io `code` # Title")
    check("spoken text has no markdown or URLs", not any(c in out for c in ("*", "`", "#", "http")), out)

    async def _boom(_):
        raise RuntimeError("tool crashed")
    said = []
    voice.respond, voice.speak = _boom, said.append
    try:
        await voice._turn("open the pod bay doors")
        survived = True
    except Exception:
        survived = False
    check("voice turn survives a failing request", survived and said and "sorry" in said[0].lower(), str(said))


def test_policy() -> None:
    import random
    from janos.policy import Policy, reward
    section("Routing policy")
    tmp = Path(tempfile.mkdtemp())
    sug = ("researcher", "simple")
    varied = [f"task number {i} about topic {i * 7} please" for i in range(50)]
    p = Policy(tmp / "fresh.npz", seed=0)
    ok = True
    for t in varied:
        d = p.choose(t, "general", *sug)
        ok &= (d.agent, d.mode) == sug and d.prob >= 0.8
    check("policy follows the LLM before training", ok)
    q = Policy(tmp / "other.npz", seed=5)
    args = ("how much vram is my gpu using", "system", "operator", "complex")
    check("policy features are deterministic", bool((p.features(*args) == q.features(*args)).all()))
    ok = all(p.choose("check gpu temperature", "system", *sug, allowed={"engineer"}).agent == "engineer"
             for _ in range(30))
    check("policy respects the tool mask", ok)

    gpu_t = ["how much vram is my gpu using", "check gpu temperature", "is the nvidia driver loaded",
             "show {} gpu memory usage", "what is the nvidia {} driver version"]
    web_t = ["latest news about mars rover", "who won the football match yesterday",
             "latest {} news headlines", "who won the {} election yesterday"]
    words = ["now", "today", "quickly", "please", "again", "fast"]
    rnd = random.Random(3)

    def gen(kind: str) -> str:
        t = rnd.choice(gpu_t if kind == "gpu" else web_t)
        return t.format(rnd.choice(words)) if "{}" in t else t

    def train(seed: int, right: float, wrong: float, episodes: int = 300) -> tuple[Policy, int, int]:
        pol = Policy(tmp / f"learn{seed}.npz", seed=seed)
        for _ in range(episodes):
            kind = rnd.choice(["gpu", "web"])
            d = pol.choose(gen(kind), "general", *sug, explore=0.2)   # autonomous-mode exploration
            pol.learn(d, right if d.agent == ("operator" if kind == "gpu" else "researcher") else wrong)
        g = sum(pol.choose(gen("gpu"), "general", *sug).agent == "operator" for _ in range(20))
        w = sum(pol.choose(gen("web"), "general", *sug).agent == "researcher" for _ in range(20))
        return pol, g, w

    # Every seed must pass: a check that passes only on a lucky seed proves nothing.
    runs = [train(seed, 0.9, 0.5) for seed in range(5)]
    worst = min(min(g, w) for _, g, w in runs)
    check("policy learns to override a wrong suggestion (5 seeds)", worst >= 18,
          " ".join(f"gpu={g} web={w}" for _, g, w in runs))
    _, g, _ = train(7, 0.9, 0.85)          # gain 0.05 is below the trust margin
    check("policy keeps the LLM when the gain is small", g <= 2, f"overrode on {g}/20")

    # The bug this guards: a policy trained on a few good scribe episodes routed
    # "47 * 89 + 1234" to scribe, which has no calculator, and answered from memory.
    from janos.supervisor import Supervisor
    sup = Supervisor(Config.load())
    need = sup._required_tools("what is 47 * 89 + 1234?")
    owners = {n for n, a in sup.runner.agents.items() if need <= set(a.tools)}
    sup.close()
    bp = Policy(tmp / "bias.npz", seed=3)
    for i in range(40):                       # make scribe look excellent everywhere
        bp.learn(bp.choose(f"hello there {i}", "chat", "scribe", "simple"), 1.0)
    picks = {bp.choose(f"what is {i} * 89 + 1234?", "calculation", "scribe", "simple",
                       allowed=owners, explore=0.5).agent for i in range(40)}
    check("arithmetic never reaches an agent without a calculator",
          "calculate" in need and "scribe" not in picks and picks <= owners, f"{need} {picks}")

    lp = runs[0][0]
    lp.save()
    lp2 = Policy(tmp / "learn0.npz", seed=2)
    same = all(lp.choose(t, "general", *sug).action == lp2.choose(t, "general", *sug).action
               for t in [gen("gpu") for _ in range(10)] + [gen("web") for _ in range(10)])
    check("policy survives save and load", same and lp.stats()["updates"] == lp2.stats()["updates"] == 300)
    from janos.policy import TRUST
    check("slowness alone cannot outweigh trust",
          reward(1.0, 0) == 1.0 and reward(1.0, 10) < reward(1.0, 1)
          and reward(1.0, 0) - reward(1.0, 600) < TRUST and -1.0 <= reward(0, 500) <= 1.0)

    # Server, voice and autonomous mode each hold a Policy on the same file.
    shared = tmp / "shared.npz"
    p1, p2 = Policy(shared, seed=10), Policy(shared, seed=11)
    p1.learn(p1.choose("check gpu", "system", "operator", "simple"), 0.9, key="ep1")
    p2.learn(p2.choose("hello", "chat", "scribe", "simple"), 0.8, key="ep2")
    p3 = Policy(shared)
    check("two processes share one policy without losing updates",
          p3.stats()["updates"] == 2 and sorted(p3.K.tolist()) == ["ep1", "ep2"], str(p3.stats()))
    relabeled = p3.relabel("ep1", 0.0)
    again = p3.relabel("ep1", 0.0)
    check("a rating replaces the earlier reward",
          relabeled and again and len(p3.R) == 2 and float(p3.R[p3.K == "ep1"][0]) == 0.0
          and p3.stats()["updates"] == 2 and not p3.relabel("nope", 1.0), str(p3.R))

    from janos.supervisor import Supervisor
    sp = Supervisor(Config.load())
    cases = {"save the 2026-10-21 meeting notes to a file": False, "write a 3-5 page report": False,
             "my 1920x1080 screen": False, "call 555-1234": False, "dates like 10/21/2026": False,
             "what is 47*89": True, "what is 10 - 3": True, "15 percent of 240": True, "2.5 * 4": True}
    wrong = [t for t, want in cases.items() if ("calculate" in sp._required_tools(t)) != want]
    sp.close()
    check("arithmetic rule ignores dates, ranges and sizes", not wrong, str(wrong))
    shutil.rmtree(tmp, ignore_errors=True)


def test_server_security() -> None:
    print("\n\033[1mServer security\033[0m")
    import tempfile
    saved = os.environ.get("JANOS_MEMORY_DIR")
    os.environ["JANOS_MEMORY_DIR"] = tempfile.mkdtemp()
    from fastapi.testclient import TestClient
    from janos.server import api_token, app
    tok = api_token()
    c = TestClient(app, base_url="http://127.0.0.1")   # no lifespan: no model needed
    check("token file is owner-only",
          oct((Config.load().memory_dir / "api_token").stat().st_mode & 0o777) == "0o600")
    check("/chat refuses no token", c.post("/chat", json={"input": "hi"}).status_code == 401)
    check("/chat refuses wrong token",
          c.post("/chat", json={"input": "hi"}, headers={"Authorization": "Bearer nope"}).status_code == 401)
    check("every route refuses no token",
          all(c.get(p).status_code == 401 for p in ("/", "/health", "/tools", "/memory/recent")))
    ok = c.get("/tools", headers={"Authorization": f"Bearer {tok}"})
    check("valid token passes auth", ok.status_code != 401, str(ok.status_code))
    bad = c.get("/tools", headers={"Authorization": b"Bearer t\xc3\xb6ken"})  # raw bytes, as a hostile client sends
    check("non-ASCII token gives 401, not 500", bad.status_code == 401, str(bad.status_code))
    check("rebinding host rejected",
          c.get("/health", headers={"Host": "evil.example", "Authorization": f"Bearer {tok}"}).status_code == 400)
    hud = Path(__file__).parent / "ui_dist" / "index.html"
    if hud.exists():
        r = c.get("/ui/")
        check("HUD page loads without a token",
              r.status_code == 200 and "html" in r.headers.get("content-type", ""), str(r.status_code))
    model = Path(__file__).parent / "ui_dist" / "mediapipe" / "models" / "face_landmarker.task"
    if model.exists():
        check("HUD vision assets are served locally",
              c.get("/ui/mediapipe/models/face_landmarker.task").status_code == 200)
    check("API still refuses requests without a token",
          c.get("/telemetry").status_code == 401 and c.post("/speak", json={"text": "hi"}).status_code == 401)
    t = c.get("/telemetry", headers={"Authorization": f"Bearer {tok}"})
    check("telemetry reports CPU and RAM",
          t.status_code == 200 and isinstance(t.json().get("cpu_percent"), (int, float))
          and t.json().get("ram_total_gb", 0) > 0, str(t.status_code))
    import janos.server as srv
    auth = {"Authorization": f"Bearer {tok}"}
    check("/login-code refuses requests without a token", c.post("/login-code").status_code == 401)
    code = c.post("/login-code", headers=auth).json()["code"]
    first = c.post("/auth/session", json={"code": code})
    check("login code works once",
          first.status_code == 200 and first.json()["token"] == tok
          and c.post("/auth/session", json={"code": code}).status_code == 401)
    code = c.post("/login-code", headers=auth).json()["code"]
    srv._codes[code] = 0.0
    check("login code expires", c.post("/auth/session", json={"code": code}).status_code == 401)
    check("/transcribe refuses requests without a token",
          c.post("/transcribe", content=b"x").status_code == 401)
    real = Path(__file__).resolve().parents[1] / "memory" / "models"
    if (real / "whisper").exists() and (real / "kokoro-v1.0.int8.onnx").exists():
        (Config.load().memory_dir / "models").symlink_to(real)   # reuse the cached models in the temp memory dir
        srv._state.pop("tts", None); srv._state.pop("stt", None)
        r = c.post("/transcribe", content=srv._wav("testing one two three", "jarvis"),
                   headers={**auth, "Content-Type": "audio/wav"})
        check("speech-to-text endpoint round-trips",
              r.status_code == 200 and "test" in r.json()["text"].lower(), r.text[:80])
        srv._state.pop("tts", None); srv._state.pop("stt", None)
    if saved is None:
        os.environ.pop("JANOS_MEMORY_DIR", None)
    else:
        os.environ["JANOS_MEMORY_DIR"] = saved


def _git_repo(files: dict[str, str]) -> Path:
    import subprocess
    repo = Path(tempfile.mkdtemp()) / "repo"
    repo.mkdir()
    for n, c in files.items():
        (repo / n).write_text(c)
    for a in (["init", "-q", "-b", "main"], ["add", "-A"],
              ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init"]):
        subprocess.run(["git", "-C", str(repo), *a], check=True)
    return repo


def _commits(repo: Path, ref: str) -> int:
    import subprocess
    return int(subprocess.run(["git", "-C", str(repo), "rev-list", "--count", ref],
                              capture_output=True, text=True).stdout.strip() or -1)


async def test_employee_git_hijack() -> None:
    """A sandboxed agent that plants a .git directory with hooks must not get them run on the host."""
    import dataclasses, subprocess
    from janos.employee import Employee
    tmp = Path(tempfile.mkdtemp()); repo = tmp / "repo"; repo.mkdir()
    git = lambda *a: subprocess.run(a, cwd=repo, check=True, capture_output=True)
    git("git", "init", "-q", "-b", "main"); (repo / "a.txt").write_text("a"); git("git", "add", ".")
    git("git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
    marker, bindir = tmp / "PWNED", tmp / "bin"
    bindir.mkdir()
    cli = bindir / "evil-cli"
    cli.write_text("#!/bin/bash\necho change > work.txt\nrm -f .git && git init -q . && mkdir -p .git/hooks\n"
                   f"printf '#!/bin/sh\\ntouch {marker}\\n' > .git/hooks/pre-commit\n"
                   "chmod +x .git/hooks/pre-commit\n"
                   "printf '[core]\\n\\thooksPath = .git/hooks\\n' > .git/config\n"
                   "echo '{\"type\":\"text\",\"part\":{\"text\":\"done\"}}'\n")
    cli.chmod(0o755)
    cfg = dataclasses.replace(Config.load(), employee_cli=str(cli), memory_dir=tmp / "mem")
    r = await Employee(cfg, repo).run("make a change")
    count = lambda ref: subprocess.run(["git", "rev-list", "--count", ref], cwd=repo,
                                       capture_output=True, text=True).stdout.strip()
    check("employee: a planted .git hook never runs on the host",
          not marker.exists() and r.changed == ["work.txt"] and count(r.branch) == "2" and count("main") == "1",
          f"hook ran={marker.exists()} changed={r.changed[:3]} err={r.error[:80]}")

    # A repo carrying a filter driver / sshCommand would run code during
    # `git worktree add` on the host. Such a repo must be refused.
    from janos.employee import _repo_is_safe
    subprocess.run(["git", "-C", str(repo), "config", "filter.x.clean", "touch /tmp/pwn"], check=True, capture_output=True)
    refused = await _repo_is_safe(repo)
    clean_repo = tmp / "clean"; clean_repo.mkdir()
    subprocess.run(["git", "-C", str(clean_repo), "init", "-q"], check=True, capture_output=True)
    allowed = await _repo_is_safe(clean_repo)
    check("employee refuses a repo whose config can run code",
          "filter.x.clean" in refused and allowed == "", f"refused={refused!r} allowed={allowed!r}")
    shutil.rmtree(tmp, ignore_errors=True)


async def test_worker_sandbox() -> None:
    section("Worker sandbox")
    from janos import sandbox
    if not sandbox.available():
        check("worker profile isolates the process table", False, "bubblewrap missing")
        return
    cfg = Config.load()
    def procs(profile, wd=None):
        pre = sandbox.prefix(cfg, profile, workdir=wd)
        out = subprocess.run(pre + ["bash", "-c", "ls /proc | grep -c '^[0-9]'"],
                             capture_output=True, text=True, timeout=30).stdout
        return int(out.strip() or 0)
    observe = procs("observe")
    worker = procs("worker", Path(tempfile.mkdtemp()))
    check("worker profile isolates the process table", worker <= 5 and observe > 20,
          f"observe={observe} worker={worker}")


async def test_persona_and_launcher() -> None:
    section("Personas & launcher")
    from janos import persona
    j, u = persona.get("jarvis"), persona.get("ultron")
    check("two personas with distinct voices and manner",
          j.name == "jarvis" and u.name == "ultron" and j.voice != u.voice
          and j.asks and not u.asks and u.speed < j.speed, f"{j.voice}/{u.voice}")
    check("unknown persona falls back to jarvis", persona.get("nope").name == "jarvis")
    # Ultron must stay factual despite its free manner.
    for p in (j, u):
        check(f"{p.name} prompt forbids inventing facts",
              "exactly as given" in p.system and "never claim" in p.system.lower())

    # launch_ui writes an owner-only page and never the token in it
    import importlib.util, io, contextlib, tempfile
    from pathlib import Path as _P
    mem = _P(tempfile.mkdtemp()); (mem / "api_token").write_text("TESTTOKEN123")
    code_box = {}
    import janos.launch_ui as L
    def fake_post(url, headers=None, timeout=None):
        code_box["auth"] = headers["Authorization"]
        class R:
            def raise_for_status(self): pass
            def json(self): return {"code": "ONECODE"}
        return R()
    orig = L.httpx.post; L.httpx.post = fake_post
    try:
        buf = io.StringIO()
        import sys as _s; old_argv = _s.argv; _s.argv = ["launch_ui", str(mem), "8000"]
        with contextlib.redirect_stdout(buf):
            L.main()
        _s.argv = old_argv
    finally:
        L.httpx.post = orig
    launch = mem / "launch.html"
    mode = oct(launch.stat().st_mode & 0o777)
    body = launch.read_text()
    check("launcher page is owner-only and carries the code not the token",
          mode == "0o600" and "ONECODE" in body and "TESTTOKEN123" not in body, mode)
    shutil.rmtree(mem, ignore_errors=True)


async def test_employee_offline() -> None:
    import dataclasses
    import subprocess
    section("Employee")
    sample = "\n".join([
        '{"type":"step_start","part":{}}', "not json at all",
        '{"type":"text","part":{"text":"Done."}}', '{"type":"tool_use","part":{}}',
        '{"type":"step_finish","part":{"tokens":{"total":120},"cost":0}}'])
    check("employee parses OpenCode events", parse_events(sample) == ("Done.", 120, 0.0, 1),
          str(parse_events(sample)))
    try:
        Employee(Config.load(), Path(tempfile.mkdtemp()))
        refused = False
    except ValueError:
        refused = True
    check("employee refuses a non-git directory", refused)

    repo = _git_repo({"README": "x\n"})
    bindir = repo.parent / "bin"
    bindir.mkdir()
    fake = bindir / "fakecli"
    fake.write_text('#!/bin/bash\necho hi > hello.txt\n'
                    'echo \'{"type":"text","part":{"text":"made hello.txt"}}\'\n')
    fake.chmod(0o755)
    cfg = dataclasses.replace(Config.load(), employee_cli=str(fake), memory_dir=repo.parent / "mem")
    emp = Employee(cfg, repo)
    r = await emp.run("add hello file", test_cmd="test -f hello.txt", timeout=60)
    branches = subprocess.run(["git", "-C", str(repo), "branch", "--list", r.branch],
                              capture_output=True, text=True).stdout
    check("employee works on its own branch and never touches main",
          bool(r.branch) and r.branch in branches and _commits(repo, "main") == 1
          and _commits(repo, r.branch) == 2 and r.changed == ["hello.txt"] and r.tests_ok is True,
          str(r.as_dict()))
    check("employee never assumes approval", r.verdict == "UNKNOWN" and r.ok is False, r.verdict)
    emp.cleanup(r)
    check("employee cleanup removes the worktree but keeps the branch",
          not Path(r.worktree).exists() and _commits(repo, r.branch) == 2)
    shutil.rmtree(repo.parent, ignore_errors=True)


async def test_employee_live() -> None:
    section("Employee (live OpenCode)")
    if not SNAP_BIN.exists() and not shutil.which("opencode"):
        print("  opencode not installed, skipped")
        return
    import dataclasses
    repo = _git_repo({"calc.py": "def add(a, b): return a - b\n",
                      "test_calc.py": "from calc import add; assert add(2, 3) == 5\n"})
    cfg = dataclasses.replace(Config.load(), memory_dir=repo.parent / "mem")
    emp = Employee(cfg, repo)
    r = await emp.run("Fix the add function in calc.py so test_calc.py passes",
                      test_cmd="python3 test_calc.py", timeout=600)
    print(f"  {r.seconds}s, {r.tokens} tokens, cost {r.cost}, verdict {r.verdict}")
    check("employee fixed a real bug on its own branch",
          r.tests_ok is True and "calc.py" in r.changed and _commits(repo, "main") == 1,
          str(r.as_dict()))
    check("employee review returned a verdict", r.verdict in ("APPROVE", "REJECT"), r.review[-300:])
    emp.cleanup(r)
    shutil.rmtree(repo.parent, ignore_errors=True)


async def main_async() -> int:
    ap = argparse.ArgumentParser(description="JANOS self-test")
    ap.add_argument("--offline", action="store_true", help="skip Ollama and network checks")
    args = ap.parse_args()

    print("\033[1mJANOS self-test\033[0m")

    test_config()
    test_memory()
    test_arithmetic()
    test_capability_guard()
    test_forge_validation()
    test_server_security()
    test_autonomy()
    await test_tools()
    await test_sandbox()
    await test_playbooks()
    await test_voice()
    test_policy()
    await test_employee_offline()
    await test_employee_git_hijack()
    await test_worker_sandbox()
    await test_persona_and_launcher()

    if not args.offline:
        await test_network()
        await test_employee_live()
        sup = Supervisor(Config.load())
        try:
            if await test_llm(sup):
                await test_pipeline(sup)
            else:
                print("\n  \033[33mSkipping pipeline tests — model not ready.\033[0m")
        finally:
            sup.close()

    failed = [(n, d) for ok, n, d in _results if not ok]
    total = len(_results)
    print(f"\n\033[1m{total - len(failed)}/{total} checks passed\033[0m")
    if failed:
        print("\033[31mFailures:\033[0m")
        for n, d in failed:
            print(f"  - {n}" + (f": {d}" if d else ""))
        return 1
    print("\033[32mAll checks passed.\033[0m")
    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
