from agents.base import BaseAgent


class PlannerAgent(BaseAgent):
    def __init__(self, **kwargs):
        super().__init__(name="planner", **kwargs)

    def system_prompt(self) -> str:
        return """You are a task planner. Given a user request, break it down into
sequential steps. For each step specify:
- action: the tool or capability needed
- params: required parameters as JSON
- depends_on: step index this depends on (or -1)

Output a JSON list of steps. Be concise and practical."""
