from typing import Any

from agents.base import BaseAgent


class ExecutorAgent(BaseAgent):
    def __init__(self, tools: dict[str, Any] | None = None, **kwargs):
        super().__init__(name="executor", **kwargs)
        self.tools = tools or {}

    def register_tool(self, name: str, tool: Any) -> None:
        self.tools[name] = tool

    def system_prompt(self) -> str:
        tool_descs = "\n".join(
            f"- {name}: {getattr(t, 'description', 'no description')}"
            for name, t in self.tools.items()
        )
        return f"""You are a tool executor. Given a step from the planner, execute it
using the available tools. Available tools:
{tool_descs or "(no tools registered)"}

Return the result of execution. Be precise."""

    async def execute_step(self, step: dict[str, Any]) -> Any:
        action = step.get("action")
        params = step.get("params", {})
        if action in self.tools:
            self.log.info("Executing %s with %s", action, params)
            try:
                result = await self.tools[action].execute(**params)
                self.scoring.record_action(action, success=True)
                return result
            except Exception as e:
                self.log.error("Tool %s failed: %s", action, e)
                self.scoring.record_action(action, success=False)
                return {"error": str(e)}
        else:
            return {"error": f"Unknown tool: {action}"}
