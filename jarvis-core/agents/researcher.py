from agents.base import BaseAgent


class ResearcherAgent(BaseAgent):
    def __init__(self, **kwargs):
        super().__init__(name="researcher", **kwargs)

    def system_prompt(self) -> str:
        return """You are a research agent. Given a topic or question:
1. If you have relevant knowledge, answer directly.
2. If you need current information, state what you would search for.
3. Always cite sources when possible.
4. Synthesize information into clear, actionable answers.

Be thorough but concise."""
