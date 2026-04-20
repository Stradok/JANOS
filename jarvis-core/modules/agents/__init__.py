# modules/agents/__init__.py
"""
Agent registry — all 14 specialized agents for JAN v2.
"""
from .base_agent import BaseAgent
from .chat_agent import ChatAgent
from .browser_agent import BrowserAgent
from .media_agent import MediaAgent
from .communication_agent import CommunicationAgent
from .research_agent import ResearchAgentV2
from .memory_agent import MemoryAgent
from .productivity_agent import ProductivityAgent
from .file_agent import FileAgent
from .system_agent import SystemAgent
from .coding_agent import CodingAgent
from .creative_agent import CreativeAgent
from .automation_agent import AutomationAgent
from .vision_agent import VisionAgent
from .self_improvement_agent import SelfImprovementAgent

# Agent registry: name → class
AGENT_CLASSES = {
    "chat": ChatAgent,
    "browser": BrowserAgent,
    "media": MediaAgent,
    "communication": CommunicationAgent,
    "research": ResearchAgentV2,
    "memory": MemoryAgent,
    "productivity": ProductivityAgent,
    "file": FileAgent,
    "system": SystemAgent,
    "coding": CodingAgent,
    "creative": CreativeAgent,
    "automation": AutomationAgent,
    "vision": VisionAgent,
    "self_improvement": SelfImprovementAgent,
}

__all__ = [
    "BaseAgent",
    "AGENT_CLASSES",
    "ChatAgent",
    "BrowserAgent",
    "MediaAgent",
    "CommunicationAgent",
    "ResearchAgentV2",
    "MemoryAgent",
    "ProductivityAgent",
    "FileAgent",
    "SystemAgent",
    "CodingAgent",
    "CreativeAgent",
    "AutomationAgent",
    "VisionAgent",
    "SelfImprovementAgent",
]
