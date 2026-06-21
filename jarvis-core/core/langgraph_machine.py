"""Full LangGraph state machine replacing the MVP.

States: INPUT → RAG_RECALL → MODEL_SELECT → TASK_DECOMPOSE →
        AGENT_ALLOCATE → EXECUTE → CRITIC_VALIDATE →
        STORE_EPISODE → RESPOND → END

Conditional edges: RETRY, ESCALATE, FAIL
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class State(str, Enum):
    INPUT = "INPUT"
    RAG_RECALL = "RAG_RECALL"
    MODEL_SELECT = "MODEL_SELECT"
    TASK_DECOMPOSE = "TASK_DECOMPOSE"
    AGENT_ALLOCATE = "AGENT_ALLOCATE"
    EXECUTE = "EXECUTE"
    CRITIC_VALIDATE = "CRITIC_VALIDATE"
    STORE_EPISODE = "STORE_EPISODE"
    RESPOND = "RESPOND"
    RETRY = "RETRY"
    ESCALATE = "ESCALATE"
    FAIL = "FAIL"
    END = "END"


@dataclass
class WorkflowContext:
    user_input: str = ""
    task_type: str = ""
    selected_model: str = ""
    selected_provider: str = ""
    rag_results: list[dict[str, Any]] = field(default_factory=list)
    task_plan: str = ""
    selected_agent: str = ""
    agent_output: str = ""
    tool_usage: list[dict[str, Any]] = field(default_factory=list)
    reasoning_steps: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    corrections: list[str] = field(default_factory=list)
    final_output: str = ""
    outcome_score: float = 0.0
    retry_count: int = 0
    max_retries: int = 3
    duration_ms: int = 0
    episode_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    response: str = ""

    @property
    def failed(self) -> bool:
        return len(self.errors) > 0 and self.retry_count >= self.max_retries


class NodeHandler:
    """A single node in the state graph with conditions."""

    def __init__(
        self,
        name: str,
        handler: Callable,
        edges: dict[str, str] | None = None,
        condition: Callable | None = None,
    ):
        self.name = name
        self.handler = handler
        self.edges = edges or {}
        self.condition = condition


class LangGraphMachine:
    """LangGraph-style state machine with conditional routing."""

    def __init__(self):
        self._nodes: dict[str, NodeHandler] = {}
        self._entry_point: str = State.INPUT

    def add_node(
        self,
        state: State | str,
        handler: Callable,
        edges: dict[str, State | str] | None = None,
    ):
        name = state.value if isinstance(state, State) else state
        edges_str = {k: v.value if isinstance(v, State) else v for k, v in (edges or {}).items()}
        self._nodes[name] = NodeHandler(name=name, handler=handler, edges=edges_str)

    def add_conditional_edges(
        self, state: State | str, condition: Callable, edge_map: dict[str, State | str]
    ):
        name = state.value if isinstance(state, State) else state
        if name in self._nodes:
            self._nodes[name].condition = condition
            self._nodes[name].edges = {
                k: v.value if isinstance(v, State) else v for k, v in edge_map.items()
            }

    def set_entry_point(self, state: State | str):
        self._entry_point = state.value if isinstance(state, State) else state

    async def run(self, ctx: WorkflowContext) -> str:
        current = self._entry_point
        ctx.reasoning_steps = []
        start = time.monotonic()

        while current != State.END.value:
            node = self._nodes.get(current)
            if not node:
                raise ValueError(f"No handler for state {current}")

            try:
                ctx.reasoning_steps.append(f"Entering {current}")
                result = await node.handler(ctx)

                if node.condition:
                    next_state = node.condition(ctx, result)
                else:
                    next_state = result

                if isinstance(next_state, State):
                    next_state = next_state.value

                if next_state not in node.edges.values() and next_state != State.END.value:
                    allowed = list(node.edges.values()) + [State.END.value]
                    raise ValueError(
                        f"State {current} returned '{next_state}' "
                        f"but allowed edges are {allowed}"
                    )

                if next_state == State.RETRY.value:
                    if ctx.retry_count >= ctx.max_retries:
                        next_state = State.FAIL.value
                    else:
                        ctx.retry_count += 1
                        ctx.reasoning_steps.append(
                            f"Retry {ctx.retry_count}/{ctx.max_retries}"
                        )
                        next_state = State.TASK_DECOMPOSE.value

                if next_state == State.ESCALATE.value:
                    ctx.reasoning_steps.append("Escalating to user")
                    ctx.final_output = (
                        "I've exhausted my options. Here's what I know:\n"
                        + f"Task: {ctx.user_input[:200]}\n"
                        + f"Errors: {'; '.join(ctx.errors[-3:])}\n"
                        + f"Steps tried: {' → '.join(ctx.reasoning_steps[-5:])}"
                    )
                    next_state = State.STORE_EPISODE.value

                current = next_state

            except Exception as e:
                ctx.errors.append(f"State machine error in {current}: {e}")
                if ctx.retry_count >= ctx.max_retries:
                    current = State.FAIL.value
                else:
                    ctx.retry_count += 1
                    current = State.TASK_DECOMPOSE.value

        ctx.duration_ms = int((time.monotonic() - start) * 1000)
        ctx.outcome_score = 1.0 if not ctx.errors else -1.0
        return ctx.response or ctx.final_output


# ---- Default Handlers ----

async def input_handler(ctx: WorkflowContext) -> str:
    ctx.task_type = ""
    return State.RAG_RECALL.value


async def rag_recall_handler(ctx: WorkflowContext) -> str:
    if ctx.rag_results:
        return State.MODEL_SELECT.value
    return State.MODEL_SELECT.value


async def model_select_handler(ctx: WorkflowContext) -> str:
    return State.TASK_DECOMPOSE.value


async def task_decompose_handler(ctx: WorkflowContext) -> str:
    return State.AGENT_ALLOCATE.value


async def agent_allocate_handler(ctx: WorkflowContext) -> str:
    return State.EXECUTE.value


async def execute_handler(ctx: WorkflowContext) -> str:
    if ctx.errors and ctx.retry_count < ctx.max_retries:
        return State.RETRY.value
    return State.CRITIC_VALIDATE.value


async def critic_validate_handler(ctx: WorkflowContext) -> str:
    return State.STORE_EPISODE.value


async def store_episode_handler(ctx: WorkflowContext) -> str:
    return State.RESPOND.value


async def respond_handler(ctx: WorkflowContext) -> str:
    return State.END.value


async def fail_handler(ctx: WorkflowContext) -> str:
    ctx.response = f"I encountered errors and could not complete this task.\nErrors: {'; '.join(ctx.errors[-3:])}"
    return State.END.value


def build_full_machine() -> LangGraphMachine:
    sm = LangGraphMachine()

    for state, handler, edges in [
        (State.INPUT, input_handler, {"RAG_RECALL": State.RAG_RECALL}),
        (State.RAG_RECALL, rag_recall_handler, {"MODEL_SELECT": State.MODEL_SELECT}),
        (State.MODEL_SELECT, model_select_handler, {"TASK_DECOMPOSE": State.TASK_DECOMPOSE}),
        (State.TASK_DECOMPOSE, task_decompose_handler, {"AGENT_ALLOCATE": State.AGENT_ALLOCATE}),
        (State.AGENT_ALLOCATE, agent_allocate_handler, {"EXECUTE": State.EXECUTE}),
        (State.EXECUTE, execute_handler, {"RETRY": State.RETRY, "CRITIC_VALIDATE": State.CRITIC_VALIDATE}),
        (State.CRITIC_VALIDATE, critic_validate_handler, {"STORE_EPISODE": State.STORE_EPISODE}),
        (State.STORE_EPISODE, store_episode_handler, {"RESPOND": State.RESPOND}),
        (State.RESPOND, respond_handler, {"END": State.END}),
        (State.FAIL, fail_handler, {"END": State.END}),
    ]:
        sm.add_node(state, handler, edges)

    return sm
