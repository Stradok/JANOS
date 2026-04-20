from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional
import os
import yaml
import modules as modules_pkg

app = FastAPI(title="JAN - Joint Autonomous Neural Agent v2.0")

# Serve frontend static files
_frontend_dir = os.path.join(os.path.dirname(__file__), "frontend")
app.mount("/static", StaticFiles(directory=_frontend_dir), name="frontend")

@app.get("/")
def serve_frontend():
    """Serve the JAN chat interface."""
    return FileResponse(os.path.join(_frontend_dir, "index.html"))

def load_config(path="config.yaml"):
    with open(path, "r") as f:
        return yaml.safe_load(f)

config = load_config()

# Build enabled modules from config and registry
ENABLED_MODULES = {}
for name, enabled in config.get("features", {}).items():
    if enabled and name in modules_pkg.MODULES:
        ENABLED_MODULES[name] = modules_pkg.MODULES[name]

# Apply settings
settings = config.get("settings", {})
modules_pkg.ORCHESTRATOR.auto_voice = settings.get("auto_voice", True)
modules_pkg.ORCHESTRATOR.default_city = settings.get("default_city", "Islamabad")

# Apply v2 settings from config
agent_config = config.get("agents", {})
modules_pkg.ORCHESTRATOR_V2.auto_voice = settings.get("auto_voice", True)
modules_pkg.ORCHESTRATOR_V2.default_city = settings.get("default_city", "Islamabad")

# Apply per-agent config overrides
agent_models = agent_config.get("models", {})
agent_max_steps = agent_config.get("max_steps_override", {})
default_max_steps = agent_config.get("max_steps", 15)
step_timeout = agent_config.get("step_timeout", 30)

for agent_name, agent_instance in modules_pkg.ORCHESTRATOR_V2.agents.items():
    if agent_name in agent_models:
        agent_instance.model = agent_models[agent_name]
    if agent_name in agent_max_steps:
        agent_instance.max_steps = agent_max_steps[agent_name]
    elif agent_instance.max_steps == 15:  # only override default
        agent_instance.max_steps = default_max_steps
    agent_instance.step_timeout = step_timeout

# Determine which orchestrator to use by default
USE_V2 = settings.get("orchestrator", "v2") == "v2"


# ========================
# Startup: auto-launch daemon + wake word
# ========================
@app.on_event("startup")
def on_startup():
    """Auto-start background daemon and wake word listener."""
    # Start daemon
    if "daemon" in modules_pkg.MODULES:
        try:
            result = modules_pkg.MODULES["daemon"].process({"action": "start"})
            print(f"[JAN] Daemon: {result.get('status', 'unknown')}")
        except Exception as e:
            print(f"[JAN] Daemon start failed: {e}")

    # Start wake word listener
    if settings.get("wake_word", True) and "wake_word" in modules_pkg.MODULES:
        try:
            result = modules_pkg.MODULES["wake_word"].process({"action": "start"})
            print(f"[JAN] Wake word listener: {result.get('status', 'unknown')}")
        except Exception as e:
            print(f"[JAN] Wake word start failed: {e}")

    # Start AR server if enabled
    if settings.get("ar_server", False) and "ar" in modules_pkg.MODULES:
        try:
            result = modules_pkg.MODULES["ar"].process({"action": "start_server"})
            print(f"[JAN] AR server: {result.get('status', 'unknown')}")
        except Exception as e:
            print(f"[JAN] AR server start failed: {e}")

    # Start background learning if enabled
    learning_config = config.get("learning", {})
    if learning_config.get("auto_start", True) and "learning_engine" in modules_pkg.MODULES:
        try:
            result = modules_pkg.MODULES["learning_engine"].process({
                "action": "start_background",
                "duration_minutes": learning_config.get("session_duration", 30),
                "interval_hours": learning_config.get("interval_hours", 6),
            })
            print(f"[JAN] Learning engine: {result.get('status', 'unknown')}")
        except Exception as e:
            print(f"[JAN] Learning engine start failed: {e}")

    print(f"[JAN] v2.0 ready — {len(modules_pkg.MODULES)} modules, {len(modules_pkg.ORCHESTRATOR_V2.agents)} agents")
    print(f"[JAN] Default orchestrator: {'v2 (agent-based)' if USE_V2 else 'v1 (single-shot)'}")


@app.on_event("shutdown")
def on_shutdown():
    """Graceful shutdown of background services."""
    for name in ["daemon", "wake_word"]:
        if name in modules_pkg.MODULES:
            try:
                modules_pkg.MODULES[name].process({"action": "stop"})
            except Exception:
                pass
    if "ar" in modules_pkg.MODULES:
        try:
            modules_pkg.MODULES["ar"].process({"action": "stop_server"})
        except Exception:
            pass


# ========================
# API Routes
# ========================
class ProcessRequest(BaseModel):
    module: str
    input: dict = {}

class ChatRequest(BaseModel):
    message: str

def _mark_activity():
    """Mark user activity for idle detection."""
    if "daemon" in modules_pkg.MODULES:
        try:
            modules_pkg.MODULES["daemon"].process({"action": "mark_activity"})
        except Exception:
            pass

@app.get("/modules")
def list_modules():
    return {
        "enabled": list(ENABLED_MODULES.keys()),
        "available": list(modules_pkg.MODULES.keys())
    }

@app.post("/process")
def process(req: ProcessRequest):
    _mark_activity()
    module_name = req.module
    if module_name not in ENABLED_MODULES:
        raise HTTPException(status_code=404, detail=f"Module '{module_name}' is not enabled or not found.")
    module = ENABLED_MODULES[module_name]
    try:
        output = module.process(req.input)
        return {"module": module_name, "output": output}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/chat")
def chat(req: ChatRequest):
    """Talk to JAN naturally. Uses the configured orchestrator (v1 or v2)."""
    _mark_activity()
    if USE_V2:
        result = modules_pkg.ORCHESTRATOR_V2.process({"message": req.message})
    else:
        result = modules_pkg.ORCHESTRATOR.process({"message": req.message})
    return result

@app.post("/chat/v1")
def chat_v1(req: ChatRequest):
    """Legacy v1 single-shot orchestrator."""
    _mark_activity()
    orchestrator = modules_pkg.ORCHESTRATOR
    result = orchestrator.process({"message": req.message})
    return result

@app.post("/chat/v2")
def chat_v2(req: ChatRequest):
    """v2 agent-based orchestrator (explicit)."""
    _mark_activity()
    result = modules_pkg.ORCHESTRATOR_V2.process({"message": req.message})
    return result


# ========================
# v2 Agent API Routes
# ========================
class AgentRequest(BaseModel):
    agent: str
    task: str

class ClassifyRequest(BaseModel):
    message: str

@app.get("/agents")
def list_agents():
    """List all registered v2 agents and their configuration."""
    agents_info = {}
    for name, agent in modules_pkg.ORCHESTRATOR_V2.agents.items():
        agents_info[name] = {
            "model": agent.model,
            "max_steps": agent.max_steps,
            "tools": list(agent.tools.keys()),
            "has_screen_reader": agent.screen_reader is not None,
        }
    return {
        "count": len(agents_info),
        "agents": agents_info,
    }

@app.post("/agents/run")
def run_agent(req: AgentRequest):
    """Run a specific agent directly with a task."""
    _mark_activity()
    result = modules_pkg.ORCHESTRATOR_V2.run_agent(req.agent, req.task)
    return result

@app.post("/agents/classify")
def classify_intent(req: ClassifyRequest):
    """Classify a message to see which agent would handle it (without executing)."""
    agent, reason = modules_pkg.ORCHESTRATOR_V2.classify_intent(req.message)
    return {
        "message": req.message,
        "agent": agent,
        "reason": reason,
        "agent_info": {
            "model": modules_pkg.ORCHESTRATOR_V2.agents[agent].model,
            "tools": list(modules_pkg.ORCHESTRATOR_V2.agents[agent].tools.keys()),
        } if agent in modules_pkg.ORCHESTRATOR_V2.agents else None,
    }


# ========================
# Learning Engine API
# ========================
class LearnRequest(BaseModel):
    action: str = "stats"
    topic: Optional[str] = None
    url: Optional[str] = None
    query: Optional[str] = None
    duration_minutes: Optional[int] = 30

@app.get("/learning/stats")
def learning_stats():
    """Get learning engine statistics — RAG docs, skills, sessions."""
    if "learning_engine" in modules_pkg.MODULES:
        return modules_pkg.MODULES["learning_engine"].process({"action": "stats"})
    return {"error": "Learning engine not loaded"}

@app.post("/learning/start")
def start_learning(req: LearnRequest):
    """Start a learning session (explore topics, build RAG, analyze failures)."""
    _mark_activity()
    if "learning_engine" not in modules_pkg.MODULES:
        return {"error": "Learning engine not loaded"}
    return modules_pkg.MODULES["learning_engine"].process({
        "action": "learn",
        "duration_minutes": req.duration_minutes or 30,
    })

@app.post("/learning/explore")
def explore_topic(req: LearnRequest):
    """Explore a specific topic and add to RAG knowledge."""
    _mark_activity()
    if "learning_engine" not in modules_pkg.MODULES:
        return {"error": "Learning engine not loaded"}
    return modules_pkg.MODULES["learning_engine"].process({
        "action": "explore_topic",
        "topic": req.topic,
    })

@app.post("/learning/ingest")
def ingest_url(req: LearnRequest):
    """Ingest a URL into the RAG knowledge base."""
    _mark_activity()
    if "learning_engine" not in modules_pkg.MODULES:
        return {"error": "Learning engine not loaded"}
    return modules_pkg.MODULES["learning_engine"].process({
        "action": "ingest_url",
        "url": req.url or "",
        "topic": req.topic,
    })

@app.post("/learning/search")
def rag_search(req: LearnRequest):
    """Search the RAG knowledge base."""
    if "learning_engine" not in modules_pkg.MODULES:
        return {"error": "Learning engine not loaded"}
    return modules_pkg.MODULES["learning_engine"].process({
        "action": "rag_search",
        "query": req.query or "",
    })

@app.get("/learning/skills")
def get_skills():
    """Get learned skill patterns (what works, what doesn't)."""
    if "learning_engine" in modules_pkg.MODULES:
        return modules_pkg.MODULES["learning_engine"].process({
            "action": "get_skill_tips",
            "limit": 20,
        })
    return {"error": "Learning engine not loaded"}

@app.post("/voice/toggle")
def toggle_voice():
    """Toggle auto-voice on/off (both v1 and v2)."""
    orch = modules_pkg.ORCHESTRATOR
    orch.auto_voice = not orch.auto_voice
    # sync v2
    modules_pkg.ORCHESTRATOR_V2.auto_voice = orch.auto_voice
    return {"auto_voice": orch.auto_voice}

@app.get("/voice/status")
def voice_status():
    """Check auto-voice status."""
    return {"auto_voice": modules_pkg.ORCHESTRATOR.auto_voice}

@app.get("/daemon/status")
def daemon_status():
    """Check daemon status."""
    if "daemon" in modules_pkg.MODULES:
        return modules_pkg.MODULES["daemon"].process({"action": "status"})
    return {"error": "Daemon module not loaded"}

@app.get("/health")
def health():
    daemon_running = False
    wake_word_running = False
    if "daemon" in modules_pkg.MODULES:
        ds = modules_pkg.MODULES["daemon"].process({"action": "status"})
        daemon_running = ds.get("running", False)
    if "wake_word" in modules_pkg.MODULES:
        ws = modules_pkg.MODULES["wake_word"].process({"action": "status"})
        wake_word_running = ws.get("running", False)
    return {
        "status": "ok",
        "version": "2.0",
        "brain": "agent-based orchestrator" if USE_V2 else "ollama (single-shot)",
        "orchestrator": "v2" if USE_V2 else "v1",
        "modules": len(modules_pkg.MODULES),
        "agents": len(modules_pkg.ORCHESTRATOR_V2.agents),
        "daemon": daemon_running,
        "wake_word": wake_word_running,
        "auto_voice": modules_pkg.ORCHESTRATOR_V2.auto_voice if USE_V2 else modules_pkg.ORCHESTRATOR.auto_voice,
    }
