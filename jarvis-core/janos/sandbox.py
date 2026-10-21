"""Run tool processes inside bubblewrap.

The shell and code-running tools act as your user. Without a boundary, one bad
command or one prompt-injected page can read ~/.ssh, browser profiles and API
keys, or write anywhere in your home. bubblewrap puts each process in its own
mount namespace, unprivileged, in a few milliseconds.

Two profiles:

  observe   for `shell`. The machine stays visible: processes, disks and GPU,
            because inspecting the machine is the operator's job. The filesystem
            is read-only, $HOME and /run are empty, only the workspace is
            writable, the environment is cleared, and there is no network unless
            `shell_network: true`. Hiding /run matters as much as hiding $HOME:
            the session bus there (`systemd-run --user`) would run any command
            outside the sandbox, and the SSH agent and keyring sockets live there.

  isolated  for code: `run_python` and the forge's smoke test. Only /usr, /etc,
            the workspace, the venv and any extra read-only paths exist. Own
            process tree, clean environment, and no network unless asked for.
            With network (the smoke test), code can reach services on localhost
            such as Ollama, which has no authentication. Accepted for now: the
            smoke test runs model-written code that is already AST-scanned.

  worker    for a coding employee (janos/employee.py). Like observe, but the only
            writable places are the task's own git worktree and the employee's
            private state directory, and network is on so the CLI can reach its
            model. Commits happen outside, on the host, after the run.
            Open risk: the network namespace is shared, so the worker can reach
            unauthenticated services on localhost (e.g. Ollama). Fixing it needs
            an egress-filtered namespace (pasta / slirp4netns), not installed.

When bubblewrap is missing or `sandbox: false` is configured, prefix() returns
[] and the caller runs the process directly. health() reports which, so the
fallback is never silent.
"""

from __future__ import annotations

import functools
import glob
import shutil
import subprocess
import sys
from pathlib import Path

from janos.config import Config


@functools.lru_cache(maxsize=1)
def available() -> bool:
    """True when bubblewrap exists and can create namespaces on this kernel."""
    exe = shutil.which("bwrap")
    if not exe:
        return False
    try:
        probe = subprocess.run(
            [exe, "--ro-bind", "/", "/", "--unshare-all", "--die-with-parent", "true"],
            capture_output=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return probe.returncode == 0


def active(config: Config) -> bool:
    return config.sandbox and available()


def _venv() -> Path | None:
    """The running virtualenv, which code inside the sandbox needs to import packages."""
    return Path(sys.prefix) if sys.prefix != sys.base_prefix else None


def prefix(config: Config, profile: str, *, network: bool = False,
           extra_ro: tuple[Path, ...] = (), extra_rw: tuple[Path, ...] = (),
           workdir: Path | None = None, env: dict[str, str] | None = None) -> list[str]:
    """argv to put in front of a command, or [] to run it unsandboxed.

    `workdir` replaces the workspace as the one writable, current directory.
    """
    if not active(config):
        return []
    ws = str((workdir or config.workspace).resolve())

    if profile in ("observe", "worker"):
        home = str(Path.home())
        # A minimal /dev plus the GPU nodes only: the full host /dev exposes a
        # shared writable /dev/shm and, for users in `input`, the keyboard.
        gpu = [a for d in sorted(glob.glob("/dev/nvidia*")) + ["/dev/dri"]
               for a in ("--dev-bind-try", d, d)]
        # Order matters: the empty $HOME is mounted first, then the workspace
        # (which lives under $HOME) is bound back on top of it.
        # Own PID namespace with the host's /proc bound read-only: `ps` and `top`
        # still list every host process, but kill() resolves PIDs in the
        # sandbox's namespace, so host processes cannot be signalled.
        args = ["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", *gpu,
                "--unshare-pid", "--ro-bind", "/proc", "/proc",
                "--tmpfs", "/run", "--ro-bind-try", "/run/systemd/resolve", "/run/systemd/resolve",
                "--tmpfs", home, "--unshare-ipc",
                # A shared network namespace also shares abstract sockets (X11)
                # and every service on localhost.
                *([] if (profile == "worker" or config.shell_network) else ["--unshare-net"]),
                "--clearenv", "--setenv", "PATH", "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
                "--setenv", "HOME", home, "--setenv", "LANG", "C.UTF-8", "--setenv", "TERM", "dumb"]
    elif profile == "isolated":
        args = ["bwrap", "--ro-bind", "/usr", "/usr",
                "--symlink", "usr/lib", "/lib", "--symlink", "usr/lib64", "/lib64",
                "--symlink", "usr/bin", "/bin", "--symlink", "usr/sbin", "/sbin",
                "--ro-bind", "/etc", "/etc", "--dev", "/dev", "--proc", "/proc",
                "--unshare-all",
                # resolv.conf points into /run/systemd/resolve; without it DNS fails.
                *(["--share-net", "--ro-bind-try", "/run/systemd/resolve", "/run/systemd/resolve"]
                  if network else []),
                "--clearenv", "--setenv", "PATH", "/usr/bin:/bin",
                "--setenv", "HOME", "/tmp", "--setenv", "LANG", "C.UTF-8"]
    else:
        raise ValueError(f"unknown sandbox profile {profile!r}")

    args += ["--tmpfs", "/tmp", "--bind", ws, ws]
    venv = _venv()
    for p in ([venv] if venv else []) + [Path(x) for x in extra_ro]:
        if p.exists():
            args += ["--ro-bind", str(p), str(p)]
    for p in (Path(x) for x in extra_rw):
        if p.exists():
            args += ["--bind", str(p), str(p)]
    for k, v in (env or {}).items():
        args += ["--setenv", k, v]
    return args + ["--chdir", ws, "--die-with-parent", "--new-session"]


def describe(config: Config) -> str:
    if not config.sandbox:
        return "off (sandbox: false in config)"
    return "bubblewrap" if available() else "unavailable — bwrap missing, tools run unsandboxed"
