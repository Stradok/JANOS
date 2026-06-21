"""Log system integration — reads @logs/ directory at startup.

Bootstrap logic:
1. Scan all .md files in logs/
2. Parse structured entries (headers, sections, code blocks)
3. Extract unfinished tasks, past errors, key decisions
4. Seed episodic memory with historical context
5. Reconstruct previous state for continuity
"""

from __future__ import annotations

import re
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.episodic_memory import EpisodicMemory


def parse_log_file(path: Path) -> list[dict[str, Any]]:
    """Parse a markdown log file into structured entries."""
    entries: list[dict[str, Any]] = []
    current_section = "preamble"
    current_entry: dict[str, Any] = {"section": "preamble", "content": []}

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return entries

    for line in text.split("\n"):
        header_match = re.match(r"^#{2,4}\s+(.+)$", line)
        if header_match:
            if current_entry["content"]:
                current_entry["text"] = "\n".join(current_entry["content"])
                entries.append(current_entry)
            current_section = header_match.group(1).strip()
            current_entry = {"section": current_section, "content": [], "source": path.name}
        elif line.strip().startswith("- **") or line.strip().startswith("* **"):
            current_entry["content"].append(line)
        elif line.strip().startswith("|"):
            current_entry["content"].append(line)
        else:
            current_entry["content"].append(line)

    if current_entry["content"]:
        current_entry["text"] = "\n".join(current_entry["content"])
        entries.append(current_entry)

    return entries


def extract_unfinished_tasks(entries: list[dict[str, Any]]) -> list[str]:
    """Find tasks that are marked as in-progress or blocked."""
    unfinished: list[str] = []
    for entry in entries:
        text = entry.get("text", "")
        if re.search(r"(in progress|blocked|pending|todo|next steps)", text, re.IGNORECASE):
            unfinished.append(text[:300])
    return unfinished


def extract_errors(entries: list[dict[str, Any]]) -> list[str]:
    """Extract error descriptions from logs."""
    errors: list[str] = []
    for entry in entries:
        text = entry.get("text", "")
        error_lines = re.findall(r"(?:error|exception|fail|crash|bug)[^.]*\.", text, re.IGNORECASE)
        errors.extend(error_lines[:5])
    return errors


def extract_key_decisions(entries: list[dict[str, Any]]) -> list[str]:
    """Extract architectural decisions from log entries."""
    decisions: list[str] = []
    for entry in entries:
        text = entry.get("text", "")
        if re.search(r"(decision|chosen|selected|opted|reason)", text, re.IGNORECASE):
            decisions.append(text[:400])
    return decisions[:10]


class LogBootstrap:
    """Reads @logs/ directory and seeds episodic memory with historical context."""

    def __init__(self, logs_dir: str | Path, episodic_memory: EpisodicMemory | None = None):
        self.logs_dir = Path(logs_dir)
        self.episodic = episodic_memory

    async def bootstrap(self) -> dict[str, Any]:
        """Run bootstrap sequence. Returns summary of what was ingested."""
        if not self.logs_dir.exists():
            return {"status": "no_logs_dir", "path": str(self.logs_dir)}

        all_entries: list[dict[str, Any]] = []
        parsed_files = 0

        for f in sorted(self.logs_dir.glob("*.md")):
            if f.name.startswith("."):
                continue
            try:
                entries = parse_log_file(f)
                all_entries.extend(entries)
                parsed_files += 1
            except Exception:
                continue

        unfinished = extract_unfinished_tasks(all_entries)
        errors = extract_errors(all_entries)
        decisions = extract_key_decisions(all_entries)

        if self.episodic is not None and all_entries:
            await self.episodic.store_episode(
                user_input="[SYSTEM BOOTSTRAP] Log ingestion at startup",
                reasoning_steps=[
                    f"Parsed {parsed_files} log files",
                    f"Found {len(unfinished)} unfinished tasks",
                    f"Found {len(errors)} historical errors",
                    f"Found {len(decisions)} key decisions",
                ],
                output=f"Bootstrapped from {parsed_files} log files with {len(all_entries)} entries",
                outcome_score=0.0,
                task_type="system_bootstrap",
                metadata={
                    "parsed_files": parsed_files,
                    "total_entries": len(all_entries),
                    "unfinished_tasks": unfinished[:5],
                    "historical_errors": errors[:5],
                },
            )

        return {
            "status": "ok",
            "parsed_files": parsed_files,
            "total_entries": len(all_entries),
            "unfinished_tasks": unfinished[:5],
            "historical_errors": errors[:5],
            "key_decisions": decisions,
        }

    def get_reconstruction_context(self) -> str:
        """Build a context string for the LLM about past session state."""
        if not self.logs_dir.exists():
            return "No previous logs found."

        parts: list[str] = []
        last_logs = sorted(self.logs_dir.glob("*.md"))[-3:]

        for log_file in last_logs:
            entries = parse_log_file(log_file)
            unfinished = extract_unfinished_tasks(entries)
            if unfinished:
                parts.append(f"From {log_file.name}:")
                for task in unfinished[:3]:
                    parts.append(f"  - Unfinished: {task[:200]}")

        if not parts:
            return "No unfinished tasks found in recent logs."

        return "\n".join(parts)
