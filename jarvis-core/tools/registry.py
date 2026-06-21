from typing import Any
from tools.base import BaseTool


class ToolRegistry:
    _tools: dict[str, BaseTool] = {}

    @classmethod
    def register(cls, tool: BaseTool) -> None:
        cls._tools[tool.name] = tool

    @classmethod
    def get(cls, name: str) -> BaseTool | None:
        return cls._tools.get(name)

    @classmethod
    def list(cls) -> list[str]:
        return list(cls._tools.keys())

    @classmethod
    def all(cls) -> dict[str, Any]:
        return cls._tools

    @classmethod
    def schemas(cls) -> list[dict[str, Any]]:
        return [t.schema() for t in cls._tools.values()]
