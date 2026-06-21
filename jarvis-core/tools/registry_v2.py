"""Tool registry update — adds privileged shell to available tools.
"""

from __future__ import annotations

from typing import Any


class ToolRegistryPhase2:
    """Extended tool registry for Phase 2+ tools."""

    _tools: dict[str, Any] = {}

    @classmethod
    def register(cls, name: str, tool: Any):
        cls._tools[name] = tool

    @classmethod
    def get(cls, name: str) -> Any | None:
        return cls._tools.get(name)

    @classmethod
    def list(cls) -> list[str]:
        return list(cls._tools.keys())

    @classmethod
    def all(cls) -> dict[str, Any]:
        return cls._tools

    @classmethod
    def describe(cls) -> str:
        lines = ["Available tools:"]
        for name, tool in cls._tools.items():
            desc = getattr(tool, "description", "") or getattr(tool, "__doc__", "") or ""
            lines.append(f"  {name}: {desc[:80]}")
        return "\n".join(lines)
