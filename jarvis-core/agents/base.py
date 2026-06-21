from abc import ABC, abstractmethod
from typing import Any

from core.llm import LLM
from core.memory import Memory
from core.scoring import ScoringEngine
from core.logger import get_logger


class BaseAgent(ABC):
    def __init__(
        self,
        name: str,
        llm: LLM | None = None,
        memory: Memory | None = None,
        scoring: ScoringEngine | None = None,
    ):
        self.name = name
        self.llm = llm or LLM()
        self.memory = memory or Memory()
        self.scoring = scoring or ScoringEngine()
        self.log = get_logger(f"agent.{name}")

    @abstractmethod
    def system_prompt(self) -> str:
        ...

    async def think(self, prompt: str, **kwargs) -> str:
        context = self.memory.short.get_context(limit=10)
        messages = [{"role": "system", "content": self.system_prompt()}]
        messages.extend(context)
        messages.append({"role": "user", "content": prompt})
        resp = self.llm.chat(messages=messages, **kwargs)
        self.memory.short.add("user", prompt)
        self.memory.short.add("assistant", resp.text)
        return resp.text

    async def run(self, input_data: Any) -> Any:
        return await self.think(str(input_data))
