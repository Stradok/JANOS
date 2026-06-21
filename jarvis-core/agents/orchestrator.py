from typing import Any

from core.llm import LLM
from core.memory import Memory
from core.scoring import ScoringEngine
from core.logger import get_logger
from agents.base import BaseAgent
from agents.registry import AgentRegistry
from agents.planner import PlannerAgent
from agents.executor import ExecutorAgent
from agents.researcher import ResearcherAgent
from agents.reflector import ReflectorAgent


class Orchestrator:
    def __init__(
        self,
        llm: LLM | None = None,
        memory: Memory | None = None,
        scoring: ScoringEngine | None = None,
        tools: dict[str, Any] | None = None,
    ):
        self.llm = llm or LLM()
        self.memory = memory or Memory()
        self.scoring = scoring or ScoringEngine()
        self.tools = tools or {}
        self.log = get_logger("orchestrator")

        self.planner = PlannerAgent(llm=self.llm, memory=self.memory, scoring=self.scoring)
        self.executor = ExecutorAgent(llm=self.llm, memory=self.memory, scoring=self.scoring, tools=self.tools)
        self.researcher = ResearcherAgent(llm=self.llm, memory=self.memory, scoring=self.scoring)
        self.reflector = ReflectorAgent(llm=self.llm, memory=self.memory, scoring=self.scoring)

        for a in [self.planner, self.executor, self.researcher, self.reflector]:
            AgentRegistry.register(a)

    async def process(self, user_input: str) -> str:
        self.log.info("Processing: %s", user_input[:80])
        self.memory.short.add("user", user_input)

        plan = await self.planner.think(user_input)
        self.log.debug("Plan: %s", plan)

        result_parts = []
        for step in self._parse_steps(plan):
            result = await self.executor.execute_step(step)
            result_parts.append(str(result))

        result = "\n".join(result_parts) or "I couldn't find a specific tool for that."

        reflection = await self.reflector.reflect(user_input, result)

        self.memory.short.add("assistant", result)
        return result

    def _parse_steps(self, plan_text: str) -> list[dict[str, Any]]:
        import json
        import re

        try:
            steps = json.loads(plan_text)
            if isinstance(steps, list):
                return steps
            return [{"action": "think", "params": {"prompt": plan_text}, "depends_on": -1}]
        except json.JSONDecodeError:
            match = re.search(r'\[.*?\]', plan_text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
            return [{"action": "think", "params": {"prompt": plan_text}, "depends_on": -1}]
