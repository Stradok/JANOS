"""HTTP API for JANOS.

    python3 -m janos.server            # http://127.0.0.1:8000
    uvicorn janos.server:app --reload

Endpoints
    GET  /health            model / agents / tools / memory status
    POST /chat              {"input": "..."} -> full turn record
    POST /chat/stream       same, streamed as server-sent events
    POST /feedback          {"episode_id": "...", "rating": 1-5}
    GET  /agents /tools
    GET  /memory/stats /memory/recent /memory/lessons /rankings
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from janos.config import Config
from janos.supervisor import Supervisor

_state: dict[str, Any] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = Config.load()
    sup = Supervisor(config)
    _state["sup"] = sup
    health = await sup.health()
    if not health["ok"]:
        llm = health["llm"]
        print("  ! JANOS started degraded:", flush=True)
        if not llm["reachable"]:
            print(f"    Ollama unreachable at {config.ollama_url} — run `ollama serve`")
        elif not llm["model_ready"]:
            print(f"    Model missing — run `ollama pull {llm['model']}`")
    else:
        print(f"  JANOS ready · {config.model} · {len(sup.runner.agents)} agents "
              f"· {len(sup.toolbox.names())} tools", flush=True)
    try:
        yield
    finally:
        sup.close()


app = FastAPI(title="JANOS", version="2.0.0",
              description="Local autonomous, self-healing agent system", lifespan=lifespan)


def sup() -> Supervisor:
    s = _state.get("sup")
    if s is None:
        raise HTTPException(503, "Supervisor not initialised")
    return s


class ChatIn(BaseModel):
    input: str = Field(..., min_length=1, description="the task or question")


class FeedbackIn(BaseModel):
    episode_id: str
    rating: int = Field(..., ge=1, le=5)
    comment: str = ""


@app.get("/")
async def root() -> dict[str, Any]:
    return {
        "name": "JANOS",
        "version": "2.0.0",
        "description": "Local autonomous, self-healing agent system with one supervisor",
        "endpoints": ["/health", "/chat", "/chat/stream", "/feedback", "/agents",
                      "/tools", "/memory/stats", "/memory/recent", "/memory/lessons",
                      "/rankings"],
    }


@app.get("/health")
async def health() -> dict[str, Any]:
    return await sup().health()


@app.post("/chat")
async def chat(body: ChatIn) -> dict[str, Any]:
    turn = await sup().handle(body.input)
    return turn.as_dict()


@app.post("/chat/stream")
async def chat_stream(body: ChatIn) -> StreamingResponse:
    """Stream reasoning events as they happen, then the final turn."""
    s = sup()
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def on_event(ev: dict[str, Any]) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, ev)

    async def produce() -> None:
        previous = s.on_event
        s.on_event = on_event
        try:
            turn = await s.handle(body.input)
            await queue.put({"type": "result", **turn.as_dict()})
        except Exception as e:
            await queue.put({"type": "error", "error": f"{type(e).__name__}: {e}"})
        finally:
            s.on_event = previous
            await queue.put(None)

    async def stream():
        task = asyncio.create_task(produce())
        try:
            while True:
                ev = await queue.get()
                if ev is None:
                    break
                yield f"data: {json.dumps(ev, default=str)}\n\n"
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/feedback")
async def feedback(body: FeedbackIn) -> dict[str, Any]:
    """Human rating overrides the critic's score and feeds the learning loop."""
    s = sup()
    ep = s.memory.episode(body.episode_id)
    if ep is None:
        raise HTTPException(404, f"No episode {body.episode_id!r}")

    score = (body.rating - 1) / 4.0  # 1..5 -> 0.0..1.0
    with s.memory._lock:
        s.memory._conn.execute(
            "UPDATE episodes SET score=? WHERE episode_id=?", (score, body.episode_id)
        )
        s.memory._conn.commit()
    for agent in ep.get("agents") or []:
        s.memory.record_agent(str(agent).split("->")[-1], ep.get("task_type", "general"), score)

    learned = ""
    if body.comment.strip():
        note = f"For {ep.get('task_type', 'general')} tasks: {body.comment.strip()}"
        if s.memory.add_lesson(note, task_type=ep.get("task_type", "general"), source="user"):
            learned = note

    return {"episode_id": body.episode_id, "score": round(score, 2), "learned": learned}


@app.get("/agents")
async def agents() -> dict[str, Any]:
    return {"agents": sup().runner.roster()}


@app.get("/tools")
async def tools() -> dict[str, Any]:
    s = sup()
    return {"tools": [
        {"name": n, "description": s.toolbox.get(n).description,
         "params": s.toolbox.get(n).params}
        for n in s.toolbox.names()
    ]}


@app.get("/memory/stats")
async def memory_stats() -> dict[str, Any]:
    return sup().memory.stats()


@app.get("/memory/recent")
async def memory_recent(limit: int = 10) -> dict[str, Any]:
    return {"episodes": sup().memory.recent(max(1, min(limit, 100)))}


@app.get("/memory/lessons")
async def memory_lessons(limit: int = 50) -> dict[str, Any]:
    return {"lessons": sup().memory.all_lessons(max(1, min(limit, 200)))}


@app.get("/memory/episode/{episode_id}")
async def memory_episode(episode_id: str) -> dict[str, Any]:
    ep = sup().memory.episode(episode_id)
    if ep is None:
        raise HTTPException(404, f"No episode {episode_id!r}")
    return ep


@app.get("/rankings")
async def rankings() -> dict[str, Any]:
    return {"rankings": sup().memory.rankings()}


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")


if __name__ == "__main__":
    main()
