"""Command interface — /command style invocation plus self-description.

Supports:
  /help          — List all commands and agents
  /agents        — List all registered agents
  /tools         — List all available tools
  /plan <task>   — Explicitly plan a task
  /run <agent>   — Run a specific agent
  /memory        — Memory operations
  /scores        — Show action scores
  /exec <cmd>    — Safe shell execution
  /pull <model>  — Pull an Ollama model
  /status        — Show system status
"""

from __future__ import annotations

import shlex
from typing import Any


def parse_command(input_str: str) -> dict[str, Any]:
    """Parse input string into command + args.

    Returns {"is_command": bool, "command": str, "args": str, "raw_args": list}
    """
    stripped = input_str.strip()
    if not stripped.startswith("/"):
        return {"is_command": False, "command": "", "args": "", "raw_args": []}

    parts = shlex.split(stripped)
    command = parts[0][1:].lower()  # remove leading /
    args = " ".join(parts[1:]) if len(parts) > 1 else ""
    return {
        "is_command": True,
        "command": command,
        "args": args,
        "raw_args": parts[1:],
    }


class CommandHandler:
    """Handles registered commands by dispatching to the right subsystem."""

    def __init__(self):
        self._commands: dict[str, dict[str, Any]] = {}

    def register(
        self,
        name: str,
        handler: Any,
        description: str,
        usage: str = "",
    ):
        self._commands[name] = {
            "handler": handler,
            "description": description,
            "usage": usage or f"/{name}",
        }

    async def execute(self, command: str, args: str, context: Any = None) -> str:
        cmd = self._commands.get(command)
        if not cmd:
            return f"Unknown command: /{command}. Try /help"

        handler = cmd["handler"]
        if callable(handler):
            if context is not None:
                result = handler(args, context)
            else:
                result = handler(args)
            if hasattr(result, "__await__"):
                result = await result
            return str(result)
        return str(handler)

    def list_commands(self) -> list[dict[str, str]]:
        return [
            {"command": f"/{name}", "description": info["description"], "usage": info["usage"]}
            for name, info in self._commands.items()
        ]

    def help_text(self) -> str:
        lines = ["Available commands:"]
        for cmd in self.list_commands():
            lines.append(f"  {cmd['command']:20s} {cmd['description']}")
        return "\n".join(lines)


class SystemDescriptor:
    """Self-description system — answers 'what can you do?'"""

    def __init__(self):
        self.command_handler: CommandHandler | None = None
        self.agent_names: list[str] = []
        self.tool_names: list[str] = []
        self.model_names: list[str] = []
        self.hardware_info: dict[str, Any] = {}

    def describe(self) -> str:
        parts = ["I am JANOS — a fully autonomous Linux-native AI operating system."]
        parts.append("")
        parts.append(f"I have {len(self.agent_names)} agents: {', '.join(self.agent_names)}")
        parts.append(f"I have {len(self.tool_names)} tools available")
        parts.append(f"I have {len(self.model_names)} models available")
        if self.hardware_info:
            hw = self.hardware_info
            parts.append(
                f"Hardware: GPU={hw.get('gpu_count', 0)}x "
                f"({hw.get('vram_used_gb', 0):.1f}/{hw.get('vram_total_gb', 0):.1f}GB VRAM), "
                f"RAM={hw.get('ram_used_gb', 0):.1f}/{hw.get('ram_total_gb', 0):.1f}GB"
            )
        parts.append("")
        if self.command_handler:
            parts.append(self.command_handler.help_text())
        parts.append("")
        parts.append("I can also autonomously plan multi-step tasks, search my episodic memory, heal from errors, and learn from experience.")
        return "\n".join(parts)
