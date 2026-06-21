"""AutoGen multi-agent debate system for complex tasks.

When a task is classified as complex, spawns an AutoGen group chat
where Planner, Executor, and Critic agents debate approaches before executing.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.llm_client import LLMClient


class AutoGenDebate:
    """Lightweight multi-agent debate using AutoGen's group chat pattern.

    Uses our own LLMClient instead of OpenAI to keep Ollama compatibility.
    """

    def __init__(self, llm: LLMClient):
        self.llm = llm

    async def debate(
        self,
        task: str,
        context: str = "",
        rounds: int = 3,
    ) -> dict[str, Any]:
        """Run a multi-agent debate to solve a complex task.

        Each round: Planner proposes → Executor critiques → Critic evaluates
        """
        messages = []
        if context:
            messages.append({"role": "system", "content": f"Context:\n{context}"})

        debate_log = []
        final_plan = ""

        for round_num in range(rounds):
            round_entries = {"round": round_num + 1}

            planner_prompt = f"""You are the Planner. Task: {task}
Previous discussion: {json.dumps(debate_log[-2:] if len(debate_log) > 2 else debate_log)}
Propose a clear execution plan with specific steps."""

            messages.append({"role": "user", "content": planner_prompt})
            plan_resp = await self.llm.chat(messages)
            plan = plan_resp.text
            round_entries["plan"] = plan

            executor_prompt = f"""You are the Executor. Review this plan for feasibility:
{plan}
Point out any issues, missing steps, or tool requirements."""

            messages.append({"role": "user", "content": executor_prompt})
            exec_resp = await self.llm.chat(messages)
            exec_feedback = exec_resp.text
            round_entries["executor_feedback"] = exec_feedback

            critic_prompt = f"""You are the Critic. Evaluate:
Plan: {plan}
Executor feedback: {exec_feedback}

Score the plan -1.0 to 1.0 and suggest final refinements.
If score >= 0.5, output FINAL_PLAN: followed by the refined plan."""

            messages.append({"role": "user", "content": critic_prompt})
            critic_resp = await self.llm.chat(messages)
            critic_output = critic_resp.text
            round_entries["critic_output"] = critic_output

            debate_log.append(round_entries)

            if "FINAL_PLAN:" in critic_output:
                final_plan = critic_output.split("FINAL_PLAN:")[-1].strip()
                break

            messages.append({
                "role": "user",
                "content": "Continue debate. Planner, refine your plan based on feedback."
            })

        if not final_plan and debate_log:
            final_plan = debate_log[-1].get("plan", "")

        return {
            "final_plan": final_plan,
            "debate_log": debate_log,
            "rounds_completed": len(debate_log),
            "consensus_reached": bool(final_plan),
        }
