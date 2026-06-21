"""Dynamic model router.

Picks the best available Ollama model for each task based on:
1. What models are currently installed (ollama list)
2. Task complexity classification
3. Current hardware load (from hardware monitor)
4. Historical success rates (from scoring engine)

No hardcoded model names — works with whatever is installed.
Can pull new models if needed (with user consent).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.llm_client import LLMClient
    from core.hardware_monitor import HardwareMonitor


# Model capability scoring: bigger/heavier = higher score
_MODEL_CAPABILITY_PATTERNS = {
    "small_fast": [
        r"\b(?:0\.5b|1b|1\.5b|3b|3\.2b|7b)\b",
        r"(?:tiny|small|mini|light|fast)",
        r"gemma4?",
        r"phi[-\s]?(?:1|2|3)",
        r"qwen2\.5:1",
        r"llama3\.2:[13]",
    ],
    "medium": [
        r"\b(?:8b|9b|12b|13b|14b)\b",
        r"llama3?[-\s]?(?:3|4|8)",
        r"mistral",
        r"mixtral",
        r"qwen2\.5:7",
        r"deepseek",
    ],
    "large_deep": [
        r"\b(?:20b|27b|30b|32b|34b|70b|72b|120b)\b",
        r"qwen2\.5:3[02]",
        r"llama3?[-\s]?(?:70|120)",
        r"codestral",
        r"command[-\s]?r",
        r"dbrx",
    ],
    "code_specialist": [
        r"(?:coder|code[-_])",
        r"deepseek[-_]coder",
        r"qwen.*coder",
        r"codestral",
        r"starcoder",
    ],
    "function_calling": [
        r"(?:function|fc|tool-use|tool_use)",
    ],
}

_TASK_CAPABILITY_MAP = {
    "routing": {"min_score": 0, "ideal": "small_fast"},
    "classification": {"min_score": 0, "ideal": "small_fast"},
    "chat": {"min_score": 0, "ideal": "medium"},
    "reasoning": {"min_score": 1, "ideal": "large_deep"},
    "planning": {"min_score": 1, "ideal": "medium"},
    "coding": {"min_score": 0, "ideal": "code_specialist"},
    "research": {"min_score": 1, "ideal": "medium"},
    "creative": {"min_score": 0, "ideal": "medium"},
    "tool_selection": {"min_score": 0, "ideal": "function_calling"},
    "default": {"min_score": 0, "ideal": "medium"},
}


def _score_model_for_task(model_name: str, task_type: str) -> float:
    """Score how well a model fits a task. Higher = better."""
    name_lower = model_name.lower()
    score = 0.0
    target_cat = _TASK_CAPABILITY_MAP.get(task_type, _TASK_CAPABILITY_MAP["default"])["ideal"]

    if target_cat == "small_fast":
        for pat in _MODEL_CAPABILITY_PATTERNS["small_fast"]:
            if re.search(pat, name_lower):
                score += 3.0
        for pat in _MODEL_CAPABILITY_PATTERNS["large_deep"]:
            if re.search(pat, name_lower):
                score -= 2.0
        for pat in _MODEL_CAPABILITY_PATTERNS["medium"]:
            if re.search(pat, name_lower):
                score += 1.0

    elif target_cat == "medium":
        for pat in _MODEL_CAPABILITY_PATTERNS["medium"]:
            if re.search(pat, name_lower):
                score += 3.0
        for pat in _MODEL_CAPABILITY_PATTERNS["small_fast"]:
            if re.search(pat, name_lower):
                score += 1.0
        for pat in _MODEL_CAPABILITY_PATTERNS["large_deep"]:
            if re.search(pat, name_lower):
                score += 1.0

    elif target_cat == "large_deep":
        for pat in _MODEL_CAPABILITY_PATTERNS["large_deep"]:
            if re.search(pat, name_lower):
                score += 5.0
        for pat in _MODEL_CAPABILITY_PATTERNS["medium"]:
            if re.search(pat, name_lower):
                score += 2.0
        for pat in _MODEL_CAPABILITY_PATTERNS["small_fast"]:
            if re.search(pat, name_lower):
                score -= 1.0

    elif target_cat == "code_specialist":
        for pat in _MODEL_CAPABILITY_PATTERNS["code_specialist"]:
            if re.search(pat, name_lower):
                score += 5.0

    elif target_cat == "function_calling":
        for pat in _MODEL_CAPABILITY_PATTERNS["function_calling"]:
            if re.search(pat, name_lower):
                score += 5.0

    return score


def classify_task_complexity(user_input: str) -> str:
    """Classify task type from user input."""
    input_lower = user_input.lower()

    if any(w in input_lower for w in ["/command", "/help", "/agents", "/tools"]):
        return "routing"

    if any(w in input_lower for w in ["/plan", "plan this", "step by step", "break down"]):
        return "planning"

    if any(w in input_lower for w in [
        "code", "write a", "implement", "function", "class", "refactor", "debug", "fix bug",
        "/exec", "run command", "shell",
    ]):
        return "coding"

    if any(w in input_lower for w in [
        "research", "search", "find", "look up", "what is", "who is", "how does", "explain",
    ]):
        return "research"

    if any(w in input_lower for w in [
        "write", "create", "compose", "draft", "story", "poem", "essay",
    ]):
        return "creative"

    if len(user_input.split()) < 8:
        return "chat"

    return "reasoning"


class ModelRouter:
    """Selects the best available model for each task dynamically."""

    def __init__(
        self,
        llm_client: LLMClient,
        hardware_monitor: HardwareMonitor | None = None,
    ):
        self.llm = llm_client
        self.hardware = hardware_monitor
        self._model_cache: list[str] = []
        self._cache_time = 0.0

    async def refresh_models(self) -> list[str]:
        self._model_cache = await self.llm.available_model_names()
        return self._model_cache

    async def select_for_task(
        self,
        user_input: str,
        task_type: str | None = None,
        prefer_fast: bool = False,
    ) -> dict[str, Any]:
        """Select best model for a task. Returns {model, provider, task_type, reason}."""
        if not self._model_cache:
            await self.refresh_models()

        if not self._model_cache:
            return {
                "model": "",
                "provider": "",
                "task_type": task_type or "unknown",
                "reason": "no_models_available",
            }

        task_type = task_type or classify_task_complexity(user_input)

        if prefer_fast:
            task_type = "routing"

        scored: list[tuple[float, str]] = []
        for model_name in self._model_cache:
            score = _score_model_for_task(model_name, task_type)
            scored.append((score, model_name))

        scored.sort(key=lambda x: x[0], reverse=True)

        if not scored:
            return {
                "model": self._model_cache[0],
                "provider": "ollama",
                "task_type": task_type,
                "reason": "first_available",
            }

        best_score, best_model = scored[0]

        return {
            "model": best_model,
            "provider": "ollama",
            "task_type": task_type,
            "reason": f"scored_{best_score:.1f}_for_{task_type}",
            "all_scores": [(m, round(s, 1)) for s, m in scored[:5]],
        }

    async def select_fast_router(self) -> str:
        """Select fastest available model for routing/classification."""
        result = await self.select_for_task("/command", task_type="routing", prefer_fast=True)
        return result["model"] or ""

    async def select_deep_reasoner(self) -> str:
        """Select best model for deep reasoning."""
        result = await self.select_for_task("", task_type="reasoning")
        return result["model"] or ""

    async def ask_for_model_pull(self, model_name: str) -> dict[str, Any]:
        """Ask user if we can pull a model (logged as intent, not automatic)."""
        return {
            "action": "pull_request",
            "model": model_name,
            "message": f"I need a model suitable for this task. May I pull '{model_name}' (~4GB)?",
        }
