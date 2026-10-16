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
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

from janos.auto import AutonomousLoop
from janos.config import Config
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
    if saved is None:
        os.environ.pop("JANOS_MEMORY_DIR", None)
    else:
        os.environ["JANOS_MEMORY_DIR"] = saved


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

    if not args.offline:
        await test_network()
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
