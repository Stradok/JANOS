"""RAG-enhanced reasoning pipeline.

Every major decision follows this pipeline:
1. Retrieve relevant episodic memories (RAG)
2. Analyze current task
3. Select appropriate LLM(s)
4. Generate plan
5. Execute via tools/agents
6. Store full episode
7. Assign utility score
8. Update memory index
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.llm_client import LLMClient
    from core.episodic_memory import EpisodicMemory
    from core.model_router import ModelRouter
    from core.langgraph_machine import WorkflowContext
    from agents.crew_agents import PlannerAgent, ExecutorAgent, CriticAgent


class ReasoningPipeline:
    """The core decision pipeline — runs before every significant action."""

    def __init__(
        self,
        llm: LLMClient,
        memory: EpisodicMemory,
        model_router: ModelRouter,
        planner: PlannerAgent | None = None,
        executor: ExecutorAgent | None = None,
        critic: CriticAgent | None = None,
    ):
        self.llm = llm
        self.memory = memory
        self.model_router = model_router
        self.planner = planner
        self.executor = executor
        self.critic = critic

    async def run(self, ctx: WorkflowContext) -> WorkflowContext:
        """Execute the full reasoning pipeline for a user request."""

        ctx.reasoning_steps.append("Pipeline: RAG recall")
        ctx.rag_results = await self.memory.search(ctx.user_input, k=5)

        ctx.reasoning_steps.append("Pipeline: model selection")
        model_info = await self.model_router.select_for_task(ctx.user_input)
        ctx.task_type = model_info.get("task_type", "general")
        ctx.selected_model = model_info.get("model", "")
        ctx.selected_provider = model_info.get("provider", "ollama")

        ctx.reasoning_steps.append("Pipeline: plan generation")
        rag_context = self._format_rag_context(ctx.rag_results)
        if self.planner:
            ctx.task_plan = await self.planner.create_plan(ctx.user_input, rag_context)
        else:
            ctx.task_plan = f"Execute: {ctx.user_input}"

        ctx.reasoning_steps.append("Pipeline: execution")
        ctx.selected_agent = self.executor.name if self.executor else "executor"
        if self.executor:
            ctx.agent_output = await self.executor.execute_step(ctx.task_plan, rag_context)
        else:
            ctx.agent_output = f"Would execute: {ctx.task_plan}"

        ctx.reasoning_steps.append("Pipeline: validation")
        if self.critic:
            validation = await self.critic.validate(
                output=ctx.agent_output,
                task=ctx.user_input,
                errors=ctx.errors,
            )
            ctx.outcome_score = validation.get("score", 0.7)
            if not validation.get("valid", True):
                ctx.errors.append(validation.get("raw", "Critic rejected output")[:200])
        else:
            ctx.outcome_score = 0.7 if ctx.agent_output else 0.0

        ctx.reasoning_steps.append("Pipeline: store episode")
        ctx.episode_id = await self.memory.store_episode(
            user_input=ctx.user_input,
            reasoning_steps=ctx.reasoning_steps,
            tool_usage=[],
            agent_selection=ctx.selected_agent,
            output=ctx.agent_output,
            errors=ctx.errors,
            corrections=ctx.corrections,
            outcome_score=ctx.outcome_score,
            task_type=ctx.task_type,
            duration_ms=ctx.duration_ms,
            metadata={
                "model": ctx.selected_model,
                "provider": ctx.selected_provider,
                "retries": ctx.retry_count,
            },
        )

        ctx.reasoning_steps.append(f"Pipeline: complete (episode {ctx.episode_id})")
        return ctx

    def _format_rag_context(self, results: list[dict]) -> str:
        if not results:
            return ""
        parts = ["Relevant past experiences:"]
        for r in results[:3]:
            summary = r.get("compressed_summary", "")[:300]
            score = r.get("outcome_score", 0)
            marker = "✅" if score > 0 else "❌" if score < 0 else "➖"
            parts.append(f"  {marker} [{score:.1f}] {summary}")
        return "\n".join(parts)


class CriticValidator:
    """Validates agent outputs and drives self-healing."""

    def __init__(self, llm: LLMClient, memory: EpisodicMemory):
        self.llm = llm
        self.memory = memory

    async def validate_output(
        self, output: str, task: str, errors: list[str]
    ) -> dict[str, Any]:
        score = 1.0
        issues = []

        if errors:
            score -= 0.3 * len(errors)
            issues.extend(errors)

        if not output or len(output.strip()) < 5:
            score -= 0.5
            issues.append("Empty or very short output")

        return {
            "score": max(-1.0, score),
            "valid": score >= 0,
            "issues": issues,
        }

    async def self_heal(
        self, task: str, errors: list[str], past_failures: str = ""
    ) -> dict[str, Any]:
        """Analyze failure and suggest a fix."""
        context = f"Similar past failures:\n{past_failures}" if past_failures else ""
        prompt = f"""A task failed. Diagnose and suggest a fix.

Task: {task}
Errors: {'; '.join(errors)}
{context}

Root cause analysis:
Fix strategy:"""
        response = await self.llm.chat([
            {"role": "system", "content": "You are a debugging expert. Diagnose failures and suggest fixes."},
            {"role": "user", "content": prompt},
        ])
        text = response.text
        return {
            "diagnosis": text[:500],
            "fix_proposed": len(text) > 50,
        }
