"""LangGraph state machine for the main orchestrator.

Defines the execution pipeline as a state graph:
    INPUT → RAG_RECALL → MODEL_SELECT → TASK_DECOMPOSE →
    AGENT_ALLOCATE → EXECUTE → CRITIC_VALIDATE →
    STORE_EPISODE → RESPOND

With conditional edges for retry, escalate, and fail.

MVP version: minimal states (INPUT → RAG_RECALL → RESPOND).
"""

from __future__ import annotations

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
    """Mutable context passed through the state machine."""

    user_input: str = ""
    task_type: str = ""
    selected_model: str = ""
    selected_provider: str = ""
    rag_results: list[dict[str, Any]] = field(default_factory=list)
    task_plan: str = ""
    selected_agent: str = ""
    agent_output: str = ""
    errors: list[str] = field(default_factory=list)
    corrections: list[str] = field(default_factory=list)
    final_output: str = ""
    outcome_score: float = 0.0
    retry_count: int = 0
    duration_ms: int = 0
    episode_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    response: str = ""


class StateMachine:
    """Minimal state machine for MVP.

    Full LangGraph integration will replace this in Phase 2.
    For MVP, this provides the same pipeline logic without the
    graph dependency.
    """

    def __init__(self):
        self._handlers: dict[State, Callable] = {}
        self._transitions: dict[State, dict[str, State]] = {}

    def register(
        self,
        state: State,
        handler: Callable,
        transitions: dict[str, State] | None = None,
    ):
        self._handlers[state] = handler
        if transitions:
            self._transitions[state] = transitions

    async def run(self, ctx: WorkflowContext) -> str:
        """Execute the state machine from INPUT to END."""
        current = State.INPUT

        while current != State.END:
            handler = self._handlers.get(current)
            if not handler:
                raise ValueError(f"No handler registered for state {current}")

            next_state = await handler(ctx)

            if isinstance(next_state, State):
                current = next_state
            elif isinstance(next_state, str):
                current = State(next_state)
            else:
                raise ValueError(f"Handler returned invalid next state: {next_state}")

            if current == State.RETRY:
                if ctx.retry_count >= 3:
                    current = State.FAIL
                else:
                    ctx.retry_count += 1
                    current = State.MODEL_SELECT

            if current == State.END:
                break

        return ctx.response or ctx.final_output


# ---- MVP Pipeline Handlers ----

async def handle_input(ctx: WorkflowContext) -> State:
    return State.RAG_RECALL


async def handle_rag_recall(ctx: WorkflowContext) -> State:
    return State.MODEL_SELECT


async def handle_model_select(ctx: WorkflowContext) -> State:
    return State.TASK_DECOMPOSE


async def handle_task_decompose(ctx: WorkflowContext) -> State:
    return State.AGENT_ALLOCATE


async def handle_agent_allocate(ctx: WorkflowContext) -> State:
    return State.EXECUTE


async def handle_execute(ctx: WorkflowContext) -> State:
    return State.CRITIC_VALIDATE


async def handle_critic_validate(ctx: WorkflowContext) -> State:
    return State.STORE_EPISODE


async def handle_store_episode(ctx: WorkflowContext) -> State:
    return State.RESPOND


async def handle_respond(ctx: WorkflowContext) -> State:
    return State.END


async def handle_fail(ctx: WorkflowContext) -> State:
    ctx.response = f"I encountered an error and could not complete this task.\nErrors: {'; '.join(ctx.errors)}"
    return State.END


def create_mvp_machine() -> StateMachine:
    """Create the MVP state machine with minimal states."""
    sm = StateMachine()

    sm.register(State.INPUT, handle_input, {"RAG_RECALL": State.RAG_RECALL})
    sm.register(State.RAG_RECALL, handle_rag_recall, {"MODEL_SELECT": State.MODEL_SELECT})
    sm.register(State.MODEL_SELECT, handle_model_select, {"TASK_DECOMPOSE": State.TASK_DECOMPOSE})
    sm.register(State.TASK_DECOMPOSE, handle_task_decompose, {"AGENT_ALLOCATE": State.AGENT_ALLOCATE})
    sm.register(State.AGENT_ALLOCATE, handle_agent_allocate, {"EXECUTE": State.EXECUTE})
    sm.register(State.EXECUTE, handle_execute, {"CRITIC_VALIDATE": State.CRITIC_VALIDATE})
    sm.register(State.CRITIC_VALIDATE, handle_critic_validate, {"STORE_EPISODE": State.STORE_EPISODE})
    sm.register(State.STORE_EPISODE, handle_store_episode, {"RESPOND": State.RESPOND})
    sm.register(State.RESPOND, handle_respond, {"END": State.END})
    sm.register(State.FAIL, handle_fail, {"END": State.END})

    return sm
