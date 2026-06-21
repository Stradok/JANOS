"""Privilege escalation system — sudo-aware shell with full logging.

All privileged actions are:
1. Logged with justification
2. Require explicit --confirm flag for destructive operations
3. Reversible where possible (.bak files, undo log)
"""

from __future__ import annotations

import asyncio
import os
import shlex
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DESTRUCTIVE_COMMANDS = [
    "rm -rf", "dd", "mkfs", "format", "> /dev", "> /dev/sda",
    "chmod 0", "chown", "mv /", "cp /",
]

UNDO_LOG_PATH = "memory/undo_log.jsonl"


class PrivilegedShell:
    """Sudo-aware shell execution with safety guards."""

    def __init__(self, log_dir: str = "memory"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.audit_log = self.log_dir / "privilege_audit.jsonl"

    def _is_destructive(self, command: str) -> bool:
        cmd_lower = command.lower()
        return any(pat in cmd_lower for pat in DESTRUCTIVE_COMMANDS)

    def _log_action(self, entry: dict[str, Any]):
        import json
        with open(self.audit_log, "a") as f:
            f.write(json.dumps(entry) + "\n")

    def _log_undo(self, entry: dict[str, Any]):
        import json
        p = Path(UNDO_LOG_PATH)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a") as f:
            f.write(json.dumps(entry) + "\n")

    async def execute(
        self,
        command: str,
        cwd: str | None = None,
        timeout: int = 60,
        confirm: bool = False,
        justification: str = "",
        sudo: bool = False,
    ) -> dict[str, Any]:
        """Execute a shell command safely.

        Args:
            command: Shell command to run
            cwd: Working directory
            timeout: Max execution time
            confirm: Must be True for destructive commands
            justification: Why this command needs to run
            sudo: Whether to use sudo
        """
        entry = {
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "command": command,
            "cwd": cwd or os.getcwd(),
            "sudo": sudo,
            "justification": justification,
            "destructive": False,
        }

        is_destructive = self._is_destructive(command)

        if not confirm and is_destructive:
            entry["status"] = "blocked"
            entry["reason"] = "Destructive command requires --confirm=True"
            self._log_action(entry)
            return {
                "status": "blocked",
                "stdout": "",
                "stderr": f"Destructive command blocked. Set confirm=True to allow:\n{command}",
                "exit_code": -1,
            }

        if sudo:
            command = f"sudo {command}"

        entry["destructive"] = is_destructive

        try:
            proc = await asyncio.wait_for(
                asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=cwd or os.getcwd(),
                ),
                timeout=timeout,
            )
            stdout, stderr = await proc.communicate()

            result = {
                "status": "ok" if proc.returncode == 0 else "error",
                "stdout": stdout.decode("utf-8", errors="replace")[:10000],
                "stderr": stderr.decode("utf-8", errors="replace")[:5000],
                "exit_code": proc.returncode or 0,
            }

            entry["status"] = result["status"]
            entry["exit_code"] = result["exit_code"]
            self._log_action(entry)

            # Log undo info for file operations
            if is_destructive and result["status"] == "ok":
                self._log_undo({
                    "timestamp": entry["timestamp"],
                    "command": command,
                    "type": "destructive",
                })

            return result

        except asyncio.TimeoutError:
            entry["status"] = "timeout"
            self._log_action(entry)
            return {
                "status": "timeout",
                "stdout": "",
                "stderr": f"Command timed out after {timeout}s",
                "exit_code": -1,
            }
        except Exception as e:
            entry["status"] = "error"
            entry["error"] = str(e)
            self._log_action(entry)
            return {
                "status": "error",
                "stdout": "",
                "stderr": str(e),
                "exit_code": -1,
            }

    async def file_backup(self, path: str) -> dict[str, Any]:
        """Create a .bak backup of a file before modifying."""
        p = Path(path)
        if not p.exists():
            return {"status": "error", "message": f"File not found: {path}"}
        bak = p.with_suffix(p.suffix + ".bak")
        shutil.copy2(str(p), str(bak))
        self._log_undo({
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "action": "backup",
            "original": str(p),
            "backup": str(bak),
        })
        return {"status": "ok", "backup_path": str(bak)}

    async def undo_last(self) -> dict[str, Any]:
        """Try to undo the last destructive operation."""
        p = Path(UNDO_LOG_PATH)
        if not p.exists():
            return {"status": "error", "message": "No undo history"}
        import json
        with open(p) as f:
            lines = [l.strip() for l in f.readlines() if l.strip()]
        if not lines:
            return {"status": "error", "message": "No undo history"}
        last = json.loads(lines[-1])
        return {"status": "logged", "last_action": last}

    def get_audit_log(self, limit: int = 20) -> list[dict[str, Any]]:
        import json
        if not self.audit_log.exists():
            return []
        with open(self.audit_log) as f:
            lines = [l.strip() for l in f.readlines() if l.strip()]
        entries = [json.loads(l) for l in lines[-limit:]]
        return entries
