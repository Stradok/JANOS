"""HTTP API for JANOS.

    python3 -m janos.server            # http://127.0.0.1:8000
    uvicorn janos.server:app --reload

Endpoints
    GET  /health            model / agents / tools / memory status
    POST /chat              {"input": "..."} -> full turn record
    POST /chat/stream       same, streamed as server-sent events
    POST /feedback          {"episode_id": "...", "rating": 1-5}
    GET  /telemetry         CPU / RAM / GPU for the HUD
    POST /speak             {"text": "..."} -> audio/wav (Kokoro TTS)
    POST /login-code        one-time code to open the HUD (POST /auth/session trades it for the token)
    GET  /ui/               the HUD (static; the API routes above still need the token)
    GET  /agents /tools
    GET  /memory/stats /memory/recent /memory/lessons /rankings
"""

from __future__ import annotations

import asyncio
import hmac
import io
import json
import os
import secrets
import time
import wave
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from janos.config import Config
from janos import persona as personas
from janos.policy import reward
from janos.supervisor import Supervisor

_state: dict[str, Any] = {}


def api_token() -> str:
    """The per-install bearer token, created on first use and readable only by you.

    /chat runs agents that have shell access, so the endpoint must never be
    reachable without proof of ownership, even from another process on this
    machine (a web page can POST to localhost).
    """
    path = Config.load().memory_dir / "api_token"
    try:
        # Created 0600 in one step: write-then-chmod leaves a readable window,
        # and O_EXCL stops two first requests writing different tokens.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        path.chmod(0o600)
    else:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(secrets.token_urlsafe(32))
    return path.read_text(encoding="utf-8").strip()


def require_token(authorization: str = Header(default="")) -> None:
    supplied = authorization.removeprefix("Bearer ").strip()
    # Compare bytes: compare_digest raises on non-ASCII str, which would be a 500.
    if not supplied or not hmac.compare_digest(supplied.encode(), api_token().encode()):
        raise HTTPException(401, "Missing or invalid bearer token "
                                 "(see memory/api_token)")


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
    api_token()
    _state["persona"] = config.persona
    print(f"  API token: {config.memory_dir / 'api_token'}  "
          f"(send as 'Authorization: Bearer <token>')", flush=True)
    try:
        yield
    finally:
        sup.close()


app = FastAPI(title="JANOS", version="2.0.0",
              description="Local autonomous, self-healing agent system", lifespan=lifespan,
              dependencies=[Depends(require_token)])

# A page on the web can make your browser call http://localhost:8000 under a
# hostname it controls (DNS rebinding). Only accept the names we expect.
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=[h.strip() for h in os.environ.get(
        "JANOS_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",") if h.strip()],
)


def sup() -> Supervisor:
    s = _state.get("sup")
    if s is None:
        raise HTTPException(503, "Supervisor not initialised")
    return s


class ChatIn(BaseModel):
    input: str = Field(..., min_length=1, description="the task or question")


class SpeakIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=1000)
    persona: str = ""


class PersonaIn(BaseModel):
    persona: str


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
                      "/tools", "/persona", "/memory/stats", "/memory/recent", "/memory/lessons",
                      "/rankings", "/telemetry", "/speak", "/login-code", "/ui/"],
    }


@app.get("/health")
async def health() -> dict[str, Any]:
    return await sup().health()


# Single-use login codes: let `make janos-ui` open the browser without putting the
# long-lived token in argv or a URL. {code: expiry (time.monotonic)}
_codes: dict[str, float] = {}
CODE_TTL = 60
CODE_MAX = 5


@app.post("/login-code")
async def login_code() -> dict[str, Any]:
    now = time.monotonic()
    for c in [c for c, t in _codes.items() if t <= now]:
        del _codes[c]
    while len(_codes) >= CODE_MAX:
        del _codes[next(iter(_codes))]      # dicts keep insertion order: oldest first
    code = secrets.token_urlsafe(16)
    _codes[code] = now + CODE_TTL
    return {"code": code, "expires_in": CODE_TTL}


class SessionIn(BaseModel):
    code: str = Field(..., max_length=200)


# Mounted sub-apps skip the parent's token dependency, which is the point: this
# is how the page trades a one-time code for the token. TrustedHost still applies.
auth_app = FastAPI(title="JANOS auth")


@auth_app.post("/session")
async def auth_session(body: SessionIn) -> dict[str, str]:
    now = time.monotonic()
    hit = next((c for c in _codes if hmac.compare_digest(c.encode(), body.code.encode())), None)
    expiry = _codes.pop(hit, 0.0) if hit else 0.0      # popped even if expired: single use
    if not hit or expiry <= now:
        raise HTTPException(401, "Login code invalid or expired")
    return {"token": api_token()}


app.mount("/auth", auth_app)


@app.get("/telemetry")
async def telemetry() -> dict[str, Any]:
    import psutil
    vm = psutil.virtual_memory()
    gpu = None
    try:
        proc = await asyncio.create_subprocess_exec(
            "nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used,memory.total",
            "--format=csv,noheader,nounits",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), 3)
        except asyncio.TimeoutError:
            proc.kill()
            raise
        name, util, used, total = [x.strip() for x in out.decode().splitlines()[0].split(",")]
        gpu = {"name": name, "util_percent": float(util),
               "vram_used_mb": float(used), "vram_total_mb": float(total)}
    except Exception:       # no NVIDIA GPU, driver hiccup, timeout: HUD shows "no GPU"
        gpu = None
    return {"cpu_percent": psutil.cpu_percent(interval=None),
            "ram_used_gb": round(vm.used / 2**30, 2),
            "ram_total_gb": round(vm.total / 2**30, 2), "gpu": gpu}


def _tts():
    """Kokoro only (no Whisper), loaded on first /speak and cached."""
    if "tts" not in _state:
        config = Config.load()
        models = config.memory_dir / "models"
        os.environ.setdefault("HF_HOME", str(models / "hf"))
        from kokoro_onnx import Kokoro
        _state["tts"] = Kokoro(str(models / "kokoro-v1.0.int8.onnx"),
                               str(models / "voices-v1.0.bin"))
    return _state["tts"]


def _wav(text: str, persona_name: str = "") -> bytes:
    import numpy as np
    tts = _tts()
    p = personas.get(persona_name or _state.get("persona"))
    audio, sr = tts.create(text, voice=p.voice, speed=p.speed, lang="en-gb")
    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


@app.post("/speak")
async def speak(body: SpeakIn) -> Response:
    try:
        data = await asyncio.to_thread(_wav, body.text, body.persona or "")
    except (ImportError, FileNotFoundError, ValueError, OSError) as e:
        raise HTTPException(503, f"Speech unavailable (run `make janos-voice-setup`): {e}")
    return Response(data, media_type="audio/wav")


@app.get("/persona")
async def get_persona() -> dict[str, Any]:
    active = personas.get(_state.get("persona"))
    return {"active": active.name,
            "available": [{"name": p.name, "label": p.label} for p in personas.PERSONAS.values()]}


@app.post("/persona")
async def set_persona(body: PersonaIn) -> dict[str, Any]:
    p = personas.get(body.persona)
    _state["persona"] = p.name
    return {"active": p.name, "label": p.label}


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
    if s.policy is not None:
        s.policy.relabel(body.episode_id, reward(score, (ep.get("duration_ms") or 0) / 1000))

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


# Static HUD. A mounted sub-app skips the app-level token dependency on purpose:
# the page loads without a token, every API route above still requires one.
_UI = Path(__file__).parent / "ui_dist"
if _UI.is_dir():
    app.mount("/ui", StaticFiles(directory=_UI, html=True), name="ui")


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")


if __name__ == "__main__":
    main()
