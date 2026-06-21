import json

from agents.base import BaseAgent


class ReflectorAgent(BaseAgent):
    def __init__(self, **kwargs):
        super().__init__(name="reflector", **kwargs)

    def system_prompt(self) -> str:
        return """You are a reflection agent. After a task completes:
1. Evaluate what worked well and what didn't.
2. Extract learnings that should be stored in long-term memory.
3. Identify patterns in user behavior or preferences.
4. Suggest improvements for next time.

Output a JSON object with 'learnings' (list), 'patterns' (list),
and 'improvements' (list)."""

    async def reflect(self, task: str, result: str) -> dict:
        prompt = f"Task: {task}\nResult: {result}\n\nReflect on this interaction."
        text = await self.think(prompt)
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = {"learnings": [text], "patterns": [], "improvements": []}
        learnings = parsed.get("learnings", [])
        for l in learnings:
            self.memory.long.save(f"learning:{hash(l)}", l, tags=["learning"])
        return parsed
