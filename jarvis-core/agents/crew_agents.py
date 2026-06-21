"""CrewAI-style agent roles for the JANOS agent layer.

Uses crewai library for role definitions but routes LLM calls through
our own LLMClient for Ollama compatibility.

6 agent roles: Planner, Executor, Critic, Searcher, MemoryAgent, FileOperator
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.llm_client import LLMClient
    from core.episodic_memory import EpisodicMemory


class AgentRole:
    """Base class for agent roles. Follows CrewAI pattern: role, goal, backstory, tools."""

    def __init__(
        self,
        name: str,
        role: str,
        goal: str,
        backstory: str,
        llm: LLMClient | None = None,
        memory: EpisodicMemory | None = None,
    ):
        self.name = name
        self.role = role
        self.goal = goal
        self.backstory = backstory
        self.llm = llm
        self.memory = memory
        self.tools: dict[str, Any] = {}

    def register_tool(self, name: str, tool: Any):
        self.tools[name] = tool

    async def think(self, task: str, context: str = "") -> str:
        """Think about a task and produce a response."""
        if not self.llm:
            return f"[{self.name}] No LLM available"

        system = f"""You are {self.name}, acting as {self.role}.
Goal: {self.goal}
Backstory: {self.backstory}
Available tools: {list(self.tools.keys()) or 'none'}"""

        messages = [
            {"role": "system", "content": system},
        ]
        if context:
            messages.append({"role": "system", "content": f"Context:\n{context}"})
        messages.append({"role": "user", "content": task})

        response = await self.llm.chat(messages)
        return response.text

    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "role": self.role,
            "goal": self.goal,
            "tools": list(self.tools.keys()),
        }


# ---- Agent Role Definitions ----


class PlannerAgent(AgentRole):
    def __init__(self, llm=None, memory=None):
        super().__init__(
            name="planner",
            role="Task Decomposition Specialist",
            goal="Break complex tasks into clear, executable steps with dependencies and success criteria",
            backstory="Expert at analyzing requests and creating optimal execution plans. "
                      "Never leaves ambiguity — every step is concrete and achievable.",
            llm=llm,
            memory=memory,
        )

    async def create_plan(self, user_input: str, rag_context: str = "") -> str:
        context = f"Relevant past experiences:\n{rag_context}" if rag_context else ""
        prompt = f"""Analyze this request and create a step-by-step plan:

Request: {user_input}

For each step specify:
1. What to do
2. Which tool or agent to use
3. Success criteria
4. Fallback if step fails

Return the plan as a numbered list."""
        return await self.think(prompt, context)


class ExecutorAgent(AgentRole):
    def __init__(self, llm=None, memory=None):
        super().__init__(
            name="executor",
            role="Task Execution Specialist",
            goal="Execute plans precisely using available tools, with error handling and validation",
            backstory="Reliable executor that follows plans exactly, catches errors, "
                      "and logs every action for audit. Prefers to use tools over guessing.",
            llm=llm,
            memory=memory,
        )

    async def execute_step(self, step: str, context: str = "") -> str:
        prompt = f"""Execute this step:

Step: {step}
Available tools: {list(self.tools.keys()) or 'none'}

If a tool is needed, specify: USE_TOOL: tool_name | args
If no tool is needed, just respond with what you'd do."""
        return await self.think(prompt, context)


class CriticAgent(AgentRole):
    def __init__(self, llm=None, memory=None):
        super().__init__(
            name="critic",
            role="Quality Assurance & Error Analysis Specialist",
            goal="Detect errors, analyze root causes, suggest corrections, and validate outputs",
            backstory="Meticulous reviewer who catches edge cases and failures. "
                      "Never lets incorrect output pass without flagging it. "
                      "Maintains a catalog of failure patterns.",
            llm=llm,
            memory=memory,
        )

    async def validate(self, output: str, task: str, errors: list[str]) -> dict[str, Any]:
        prompt = f"""Validate this execution result:

Task: {task}
Output: {output[:500]}
Errors: {'; '.join(errors) if errors else 'none'}

Respond in this format:
VALID: yes/no
ISSUES: comma-separated list
SCORE: -1.0 to 1.0
SUGGESTION: how to fix (if issues found)"""
        result = await self.think(prompt)
        return {"raw": result, "valid": "yes" in result.lower().split("\n")[0] if result else True}

    async def diagnose_failure(self, task: str, errors: list[str], past_failures: str = "") -> str:
        context = f"Similar past failures:\n{past_failures}" if past_failures else ""
        prompt = f"""Diagnose this failure:

Task: {task}
Errors: {'; '.join(errors)}

Identify root cause and suggest a concrete fix."""
        return await self.think(prompt, context)


class SearcherAgent(AgentRole):
    def __init__(self, llm=None, memory=None):
        super().__init__(
            name="searcher",
            role="Information Retrieval Specialist",
            goal="Find accurate, relevant information from web search and episodic memory",
            backstory="Expert at formulating search queries and synthesizing information "
                      "from multiple sources. Knows when to search memory vs the web.",
            llm=llm,
            memory=memory,
        )

    async def search_memory(self, query: str, k: int = 5) -> list[dict[str, Any]]:
        if self.memory:
            return await self.memory.search(query, k=k)
        return []

    async def synthesize(self, query: str, memory_results: list[dict], web_results: str = "") -> str:
        prompt = f"""Synthesize information for:

Query: {query}
Memory results: {len(memory_results)} relevant episodes
Web results: {web_results[:500] if web_results else 'none'}

Provide a concise, accurate summary."""
        return await self.think(prompt)


class MemoryAgent(AgentRole):
    def __init__(self, llm=None, memory=None):
        super().__init__(
            name="memory_agent",
            role="Memory & Knowledge Management Specialist",
            goal="Store, retrieve, and organize episodic memories and long-term knowledge efficiently",
            backstory="Librarian of the system's experience. Knows exactly what was learned, "
                      "what failed, what succeeded, and how to find it again.",
            llm=llm,
            memory=memory,
        )

    async def store(self, key: str, value: str, tags: list[str] | None = None):
        if self.memory:
            await self.memory.store_episode(
                user_input=key,
                output=value,
                task_type="memory_operation",
            )

    async def recall_relevant(self, query: str, k: int = 5) -> str:
        if not self.memory:
            return ""
        results = await self.memory.search(query, k=k)
        if not results:
            return "No relevant memories found."
        parts = [f"Episode {i+1}: {r.get('compressed_summary', '')[:200]}" for i, r in enumerate(results)]
        return "\n".join(parts)


class FileOperatorAgent(AgentRole):
    def __init__(self, llm=None, memory=None):
        super().__init__(
            name="file_operator",
            role="File System Management Specialist",
            goal="Read, write, edit, and organize files safely with backups and audit trails",
            backstory="Expert at file operations with safety-first approach. "
                      "Always creates backups before edits, validates paths, and logs all changes.",
            llm=llm,
            memory=memory,
        )

    async def read_file(self, path: str) -> str:
        try:
            with open(path) as f:
                return f.read()
        except Exception as e:
            return f"Error reading {path}: {e}"

    async def write_file(self, path: str, content: str, backup: bool = True) -> str:
        from pathlib import Path
        p = Path(path)
        if backup and p.exists():
            bak = p.with_suffix(p.suffix + ".bak")
            p.rename(bak)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
            return f"Written {len(content)} bytes to {path}"
        except Exception as e:
            return f"Error writing {path}: {e}"


# ---- Agent Registry ----

class AgentRegistry:
    _agents: dict[str, AgentRole] = {}

    @classmethod
    def register(cls, agent: AgentRole):
        cls._agents[agent.name] = agent

    @classmethod
    def get(cls, name: str) -> AgentRole | None:
        return cls._agents.get(name)

    @classmethod
    def all(cls) -> dict[str, Any]:
        return {k: v.schema() for k, v in cls._agents.items()}

    @classmethod
    def list(cls) -> list[str]:
        return list(cls._agents.keys())


def initialize_agents(llm=None, memory=None) -> dict[str, AgentRole]:
    agents = {
        "planner": PlannerAgent(llm, memory),
        "executor": ExecutorAgent(llm, memory),
        "critic": CriticAgent(llm, memory),
        "searcher": SearcherAgent(llm, memory),
        "memory_agent": MemoryAgent(llm, memory),
        "file_operator": FileOperatorAgent(llm, memory),
    }

    # Wire tools into agents — import lazily to avoid hard deps at module load
    try:
        from tools.web_search_tool import WebSearchTool
        ws = WebSearchTool()
        agents["executor"].register_tool("web_search", ws)
        agents["searcher"].register_tool("web_search", ws)
        agents["planner"].register_tool("web_search", ws)
    except Exception:
        pass

    try:
        from tools.file_tool import FileTool
        ft = FileTool()
        agents["executor"].register_tool("file", ft)
        agents["file_operator"].register_tool("file", ft)
    except Exception:
        pass

    try:
        from tools.browser_tool import BrowserTool
        bt = BrowserTool()
        agents["executor"].register_tool("browser", bt)
        agents["searcher"].register_tool("browser", bt)
    except Exception:
        pass

    try:
        from tools.system_tool import SystemTool
        st = SystemTool()
        agents["executor"].register_tool("system", st)
    except Exception:
        pass

    try:
        from tools.time_tool import TimeTool
        agents["executor"].register_tool("time", TimeTool())
    except Exception:
        pass

    try:
        from tools.math_tool import MathTool
        agents["executor"].register_tool("math", MathTool())
    except Exception:
        pass

    try:
        from tools.weather_tool import WeatherTool
        agents["executor"].register_tool("weather", WeatherTool())
    except Exception:
        pass

    for name, agent in agents.items():
        AgentRegistry.register(agent)
    return agents
