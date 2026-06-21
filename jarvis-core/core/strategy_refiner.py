"""Continuous learning and strategy refinement system.

Runs as a background job:
1. Analyzes episodic memory for low-scoring patterns
2. Adjusts agent/model/tool weights based on success rates
3. Periodically compresses old episodes
4. Generates new tool stubs for capability gaps
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.episodic_memory import EpisodicMemory
    from core.model_router import ModelRouter
    from core.routing import RoutingEngine
    from core.llm_client import LLMClient


class StrategyRefiner:
    """Background strategy refinement — runs periodically to improve system behavior."""

    def __init__(
        self,
        memory: EpisodicMemory,
        router: ModelRouter,
        routing_engine: RoutingEngine | None = None,
        llm: LLMClient | None = None,
        interval_hours: float = 24.0,
    ):
        self.memory = memory
        self.router = router
        self.routing = routing_engine
        self.llm = llm
        self.interval_hours = interval_hours
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self, run_immediately: bool = False):
        if self._running:
            return
        self._running = True
        if run_immediately:
            try:
                await self.run_refinement()
            except Exception as e:
                print(f"[StrategyRefiner] Startup refinement error: {e}")
        self._task = asyncio.create_task(self._loop())

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None

    async def _loop(self):
        while self._running:
            await asyncio.sleep(self.interval_hours * 3600)
            try:
                await self.run_refinement()
            except Exception as e:
                print(f"[StrategyRefiner] Error: {e}")

    async def run_refinement(self) -> dict[str, Any]:
        """Run a single refinement cycle."""
        results = {}

        results["fresh_models"] = await self.router.refresh_models()

        stats = await self.memory.get_stats()
        results["episode_count"] = stats.get("total_episodes", 0)

        patterns = []
        for task_type in ["routing", "reasoning", "coding", "research", "chat"]:
            failures = await self.memory.get_failure_patterns(task_type, limit=3)
            if failures:
                patterns.append({"task_type": task_type, "count": len(failures)})
        results["failure_patterns"] = patterns

        if stats.get("total_episodes", 0) > 100:
            await self.memory.compact(max_age_days=30, max_episodes=200)
            results["compacted"] = True

        if self.routing:
            agent_ranks = self.routing.get_agent_rankings()
            model_ranks = self.routing.get_model_rankings()
            results["agent_rankings"] = agent_ranks[:5]
            results["model_rankings"] = model_ranks[:5]

        return results

    async def generate_module_stub(
        self, capability_description: str, llm: LLMClient | None = None
    ) -> dict[str, Any]:
        """Generate a new tool module stub for a missing capability."""
        cl = llm or self.llm
        if not cl:
            return {"status": "error", "message": "No LLM available for stub generation"}

        prompt = f"""Generate a Python tool module stub for this capability:

Capability: {capability_description}

The module must:
- Follow the BaseTool pattern (name, description, async execute(**params))
- Be self-contained with no external dependencies
- Include error handling
- Have a clean API with typed parameters

Return ONLY the Python code, no explanation."""

        response = await cl.chat([
            {"role": "system", "content": "You generate Python tool stubs."},
            {"role": "user", "content": prompt},
        ])
        code = response.text

        if "```python" in code:
            code = code.split("```python")[1].split("```")[0]
        elif "```" in code:
            code = code.split("```")[1].split("```")[0]

        return {
            "status": "generated",
            "code": code.strip(),
            "capability": capability_description,
        }
