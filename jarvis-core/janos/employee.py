"""An employee: a coding CLI working on one task, isolated.

Each task gets its own git branch and worktree and runs inside the bubblewrap
"worker" profile, so the CLI can edit only that worktree. Git writes (the
commit) happen on the host afterwards. Tests run in a network-less sandbox and
a read-only reviewer agent judges the diff. The employee never merges and never
touches the repo's current branch: a human approves the merge.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import json
import re
import shutil
import time
from dataclasses import dataclass, asdict
from pathlib import Path

from janos import sandbox
from janos.config import Config

SNAP_BIN = Path("/snap/opencode/current/bin/opencode")  # the /snap/bin launcher refuses to run in bwrap


@dataclass
class Result:
    ok: bool
    task: str
    branch: str
    worktree: str
    summary: str
    changed: list[str]
    tests_ok: bool | None
    tests_output: str
    verdict: str  # "APPROVE" | "REJECT" | "UNKNOWN"
    review: str
    tokens: int
    cost: float
    seconds: float
    error: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def parse_events(lines: str) -> tuple[str, int, float, int]:
    """(assistant text, total tokens, total cost, tool calls) from OpenCode JSON lines."""
    text, tokens, cost, tools = [], 0, 0.0, 0
    for line in lines.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if not isinstance(ev, dict):
            continue
        part = ev.get("part") or {}
        kind = ev.get("type")
        if kind == "text":
            text.append(part.get("text", ""))
        elif kind in ("tool_use", "tool"):
            tools += 1
        elif kind == "step_finish":
            tokens += int((part.get("tokens") or {}).get("total") or 0)
            cost += float(part.get("cost") or 0)
    return "\n".join(text).strip(), tokens, cost, tools


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


async def _exec(argv: list[str], timeout: float, cwd: Path | None = None,
                env: dict[str, str] | None = None) -> tuple[int, str]:
    """Run argv, return (exit code, stdout+stderr). Kills on timeout (code -9)."""
    proc = await asyncio.create_subprocess_exec(
        *argv, cwd=cwd, env=env, stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return -9, "timed out"
    return proc.returncode or 0, out.decode("utf-8", "replace")


# Config that can execute a program during an ordinary git operation. Our own
# -c flags override the first three even if the repo sets them, but filter
# drivers, ssh commands and include files have no override, so a repo carrying
# any of them is refused rather than trusted.
_GIT_ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0"}
_GIT_SAFE = ["git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false",
             "-c", "protocol.ext.allow=never", "-c", "core.sshCommand=false"]
_GIT_DANGER = re.compile(r"^(filter\.|core\.sshcommand|core\.hookspath|core\.fsmonitor"
                         r"|include\.|includeif|.*\.sshcommand=|diff\..*\.command|.*\.textconv)",
                         re.IGNORECASE)


async def _repo_is_safe(repo: Path) -> str:
    """Empty string if the repo has no code-executing config, else why it is refused.

    A repo under the workspace could have been written by a sandboxed tool, so
    its committed `.git/config` (and anything it includes) is untrusted input to
    the host git that worktree-add runs.
    """
    code, out = await _exec([*_GIT_SAFE, "-C", str(repo), "config", "--list",
                             "--show-origin"], 15, env=_GIT_ENV)
    if code:
        return ""   # not listable (fresh repo): nothing dangerous to find
    for line in out.splitlines():
        origin, _, rest = line.partition("\t")
        # Only the repo's own config files are untrusted; skip our own
        # command-line -c flags and anything from a safe origin.
        if not origin.startswith(("file:", "blob:", "includeif:")):
            continue
        key = rest.split("=", 1)[0].strip()
        if _GIT_DANGER.match(key):
            return f"repo config sets {key!r}, which can run code on the host"
    return ""


class Employee:
    def __init__(self, config: Config, repo: Path):
        self.config = config
        self.repo = Path(repo).resolve()
        if not (self.repo / ".git").exists():
            raise ValueError(f"{self.repo} is not a git repository")
        self._gitdirs: dict[Path, Path] = {}

    def _binary(self) -> str | None:
        if self.config.employee_cli:
            return self.config.employee_cli
        if SNAP_BIN.exists():
            return str(SNAP_BIN)
        return shutil.which("opencode")

    def _git(self, path: Path, *args: str, timeout: float = 60):
        """Run git on the host for a worktree the sandboxed agent could write to.

        The agent can rewrite anything in its worktree, including the `.git`
        file, and could replace it with a directory holding its own config and
        hooks; a plain `git -C worktree commit` on the host would then run that
        code unsandboxed. So the real gitdir (recorded before the agent ran) is
        named explicitly, and every code-executing config vector is disabled.
        """
        return _exec([*_GIT_SAFE, f"--git-dir={self._gitdirs[path]}", f"--work-tree={path}", *args],
                     timeout, cwd=path, env=_GIT_ENV)

    async def _agent(self, binary: str, path: Path, prompt: str, model: str,
                     timeout: int, plan: bool = False) -> tuple[int, str]:
        home = Path.home()
        # Private state: the agent never writes the user's own OpenCode sessions,
        # caches or credentials, so nothing it does persists into the user's tools.
        state = self.config.memory_dir / "employee-state"
        data, cache = state / "data", state / "cache"
        for d in (data / "opencode", cache):
            d.mkdir(parents=True, exist_ok=True)
        argv = sandbox.prefix(
            self.config, "worker", workdir=path,
            extra_ro=(home / ".config/opencode", self.repo / ".git", Path(binary).resolve().parent),
            extra_rw=(state,),
            env={"XDG_DATA_HOME": str(data), "XDG_CACHE_HOME": str(cache)})
        argv += [binary, "run", "--format", "json", "--model", model or self.config.employee_model,
                 *(["--agent", "plan"] if plan else []), "--dir", str(path), prompt]
        return await _exec(argv, timeout, cwd=path)

    async def run(self, task: str, *, test_cmd: str = "", model: str = "", timeout: int = 0) -> Result:
        t0 = time.time()
        wid = format(int(t0 * 1000) % 36**6, "x") + format(int(t0 * 1e6) % 4096, "x")
        branch = f"janos/{_slug(task)[:30].strip('-')}-{wid}"
        path = self.config.memory_dir / "worktrees" / wid
        r = Result(False, task, branch, str(path), "", [], None, "", "UNKNOWN", "", 0, 0.0, 0.0)
        try:
            if not sandbox.active(self.config):
                r.error = "sandbox unavailable"
                return r
            binary = self._binary()
            if not binary or not Path(binary).exists():
                r.error = "coding CLI not found"
                return r
            unsafe = await _repo_is_safe(self.repo)
            if unsafe:
                r.error = f"refusing repo: {unsafe}"
                return r
            path.parent.mkdir(parents=True, exist_ok=True)
            code, out = await _exec([*_GIT_SAFE, "-C", str(self.repo), "worktree", "add",
                                     "-b", branch, str(path), "HEAD"], 60, env=_GIT_ENV)
            if code:
                r.error = f"worktree failed: {out[-300:]}"
                return r
            # Record the real gitdir now, before the agent can touch the worktree.
            pointer = (path / ".git").read_text(encoding="utf-8").strip()
            gitdir = Path(pointer.removeprefix("gitdir:").strip())
            if not gitdir.is_absolute():
                gitdir = (path / gitdir).resolve()
            self._gitdirs[path] = gitdir

            rules = ("\n\nRules: work only inside the current directory; make the smallest change "
                     "that satisfies the task; "
                     + (f"make this command pass: {test_cmd}; " if test_cmd else "")
                     + "do not commit; finish with a 2-3 sentence summary of what you changed.")
            code, out = await self._agent(binary, path, task + rules, model,
                                          timeout or self.config.employee_timeout)
            r.summary, r.tokens, r.cost, _ = parse_events(out)
            if code:
                r.error = "coding step timed out" if code == -9 else f"coding step exited {code}: {out[-300:]}"

            await self._git(path, "add", "-A", "--", ".", ":(exclude,glob)**/__pycache__/**", ":(exclude,glob)**/*.pyc")
            _, names = await self._git(path, "diff", "--cached", "--name-only")
            r.changed = [n for n in names.splitlines() if n.strip()]
            if not r.changed:
                r.error = r.error or "no changes"
                return r
            await self._git(path, "-c", "user.name=JANOS", "-c", "user.email=janos@localhost",
                            "commit", "-q", "-m", f"janos: {task[:60]}")

            if test_cmd:
                code, out = await _exec(
                    sandbox.prefix(self.config, "observe", workdir=path) + ["bash", "-c", test_cmd],
                    300, cwd=path)
                r.tests_ok, r.tests_output = code == 0, out[-2000:]

            _, diff = await self._git(path, "show", "--stat", "--patch", "HEAD")
            state = "not run" if r.tests_ok is None else "passed" if r.tests_ok else "failed"
            prompt = ("You are a strict code reviewer. Review this diff for bugs, security problems "
                      f"and whether it does the task: {task}. Test result: {state}. Reply with your "
                      "reasons, then a final line that is exactly VERDICT: APPROVE or VERDICT: REJECT."
                      f"\n\n{diff[:20000]}")
            _, rout = await self._agent(binary, path, prompt, model, 600, plan=True)
            r.review, tok, cost, _ = parse_events(rout)
            r.tokens += tok
            r.cost += cost
            verdicts = re.findall(r"VERDICT:\s*(APPROVE|REJECT)", r.review)
            r.verdict = verdicts[-1] if verdicts else "UNKNOWN"
            r.ok = r.tests_ok is not False and r.verdict == "APPROVE" and not r.error
        except Exception as e:  # never raise from run()
            r.error = f"{type(e).__name__}: {e}"
        finally:
            r.seconds = round(time.time() - t0, 1)
        return r

    def cleanup(self, result: Result) -> None:
        """Remove the worktree; the branch stays for the human."""
        import subprocess
        subprocess.run([*_GIT_SAFE, "-C", str(self.repo), "worktree", "remove", "--force",
                        result.worktree], capture_output=True, env=_GIT_ENV)


def main() -> int:
    ap = argparse.ArgumentParser(description="Have OpenCode do one coding task on a new branch")
    ap.add_argument("task")
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parents[2]))
    ap.add_argument("--test", default="")
    ap.add_argument("--model", default="")
    a = ap.parse_args()
    res = asyncio.run(Employee(Config.load(), Path(a.repo)).run(a.task, test_cmd=a.test, model=a.model))
    print(json.dumps(res.as_dict(), indent=2))
    return 0 if res.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
