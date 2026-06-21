from typing import Any
from agents.base import BaseAgent


class AgentRegistry:
    _agents: dict[str, BaseAgent] = {}

    @classmethod
    def register(cls, agent: BaseAgent) -> None:
        cls._agents[agent.name] = agent

    @classmethod
    def get(cls, name: str) -> BaseAgent | None:
        return cls._agents.get(name)

    @classmethod
    def list(cls) -> list[str]:
        return list(cls._agents.keys())

    @classmethod
    def all(cls) -> dict[str, Any]:
        return {n: type(a).__name__ for n, a in cls._agents.items()}
