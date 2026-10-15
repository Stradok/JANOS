"""JANOS — a local, text-only, self-healing autonomous agent system.

One supervisor, several specialist agents, real tools, persistent memory,
and a single local Ollama model.

    from janos import Supervisor
    sup = Supervisor()
    turn = await sup.handle("what is my GPU doing right now?")
    print(turn.answer)
"""

from janos.agents import Agent, AgentRunner, DEFAULT_AGENTS
from janos.config import Config
from janos.llm import LLM, LLMError
from janos.memory import Memory
from janos.supervisor import Supervisor, Turn
from janos.tools import Toolbox

__version__ = "2.0.0"

__all__ = [
    "Agent", "AgentRunner", "DEFAULT_AGENTS", "Config", "LLM", "LLMError",
    "Memory", "Supervisor", "Turn", "Toolbox", "__version__",
]
