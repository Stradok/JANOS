from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional
import os
import yaml
import asyncio
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
# Startup: auto-launch daemon + Phase 1 init
# ========================
@app.on_event("startup")
async def on_startup():
    """Auto-start background services and Phase 1 components."""

    # Phase 1: Initialize new architecture
    try:
        from core.hardware_monitor import HardwareMonitor
        from core.episodic_memory import EpisodicMemory
        from core.log_bootstrap import LogBootstrap
        from core.llm_client import LLMClient

        # Init LLM client
        app.state.llm = LLMClient(config)

        # Init episodic memory
        app.state.episodic_memory = EpisodicMemory()
        await app.state.episodic_memory.start()
        print(f"[JAN] Episodic memory initialized")

        # Init hardware monitor
        hw_config = config.get("hardware", {})
        app.state.hardware_monitor = HardwareMonitor(
            poll_interval=hw_config.get("poll_interval", 5.0)
        )
        await app.state.hardware_monitor.start()
        print(f"[JAN] Hardware monitor started")

        # Bootstrap from logs
        bootstrap = LogBootstrap(
            logs_dir=os.path.join(os.path.dirname(__file__), "logs"),
            episodic_memory=app.state.episodic_memory,
        )
        bootstrap_result = await bootstrap.bootstrap()
        if bootstrap_result.get("parsed_files", 0) > 0:
            print(f"[JAN] Log bootstrap: {bootstrap_result['parsed_files']} files, "
                  f"{bootstrap_result['total_entries']} entries")

        # Phase 2-5: Initialize new architecture layers
        try:
            from core.langgraph_machine import build_full_machine
            from core.model_router import ModelRouter
            from core.routing import RoutingEngine
            from core.reasoning_pipeline import ReasoningPipeline, CriticValidator
            from core.commands import CommandHandler, SystemDescriptor, parse_command
            from core.strategy_refiner import StrategyRefiner
            from agents.crew_agents import initialize_agents
            from agents.autogen_debate import AutoGenDebate
            from tools.privileged_shell import PrivilegedShell

            llm = app.state.llm
            mem = app.state.episodic_memory
            hw = app.state.hardware_monitor

            router = ModelRouter(llm, hw)
            app.state.model_router = router

            app.state.routing_engine = RoutingEngine()

            agents = initialize_agents(llm, mem)
            app.state.agents = agents

            app.state.debate = AutoGenDebate(llm)

            app.state.critic = CriticValidator(llm, mem)

            app.state.reasoning_pipeline = ReasoningPipeline(
                llm, mem, router,
                planner=agents.get("planner"),
                executor=agents.get("executor"),
                critic=agents.get("critic"),
            )

            app.state.state_machine = build_full_machine()

            cmd_handler = CommandHandler()
            cmd_handler.register("help", lambda _: cmd_handler.help_text(), "List all commands", "/help")
            cmd_handler.register("agents", lambda _: f"Agents: {', '.join(agents.keys())}", "List registered agents", "/agents")
            cmd_handler.register("tools", lambda _: "Tools: privileged_shell, registry_v2", "List available tools", "/tools")
            async def cmd_plan(args):
                plan = await agents["planner"].think(args)
                return f"Plan: {plan[:500]}"
            cmd_handler.register("plan", cmd_plan, "Plan a task", "/plan <task>")
            cmd_handler.register("memory", lambda _: f"Memory stats coming soon", "Memory operations", "/memory")
            async def cmd_scores(_):
                rankings = app.state.routing_engine.get_agent_rankings() if hasattr(app.state, 'routing_engine') else []
                return f"Agent rankings: {rankings}"
            cmd_handler.register("scores", cmd_scores, "Show agent scores", "/scores")
            cmd_handler.register("status", lambda _: f"Phase1={getattr(app.state,'llm',None) is not None}, Phase2={hasattr(app.state,'agents')}, Phase3={hasattr(app.state,'critic')}, Phase4=active, Phase5={hasattr(app.state,'strategy_refiner')}", "Show system status", "/status")
            cmd_handler.register("describe", lambda _: app.state.descriptor.describe(), "Describe system capabilities", "/describe")
            async def cmd_exec(args):
                shell = app.state.privileged_shell
                confirm = "--confirm" in args
                cmd = args.replace("--confirm", "").strip()
                return await shell.execute(cmd, confirm=confirm)
            cmd_handler.register("exec", cmd_exec, "Execute shell command (add --confirm to run)", "/exec <cmd> [--confirm]")
            async def cmd_pull(args):
                llm = app.state.llm
                return await llm.ensure_model(args.strip())
            cmd_handler.register("pull", cmd_pull, "Pull an Ollama model", "/pull <model>")
            app.state.command_handler = cmd_handler

            app.state.descriptor = SystemDescriptor()
            app.state.descriptor.command_handler = cmd_handler
            app.state.descriptor.agent_names = list(agents.keys())
            app.state.descriptor.hardware_info = hw.current_load.to_dict() if hw else {}

            app.state.privileged_shell = PrivilegedShell()

            app.state.strategy_refiner = StrategyRefiner(
                memory=mem,
                router=router,
                routing_engine=app.state.routing_engine,
                llm=llm,
            )

            print(f"[JAN] Phase 2-5 initialized: {len(agents)} agents, command interface, privilege system, strategy refiner")
        except ImportError as e:
            print(f"[JAN] Phase 2-5 init skipped (install deps: {e})")
        except Exception as e:
            import traceback
            print(f"[JAN] Phase 2-5 init error: {e}\n{traceback.format_exc()}")

    except ImportError as e:
        print(f"[JAN] Phase 1 init skipped (install deps: {e})")
    except Exception as e:
        print(f"[JAN] Phase 1 init error: {e}")

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
async def on_shutdown():
    """Graceful shutdown of background services."""
    # Stop Phase 1 hardware monitor
    hw = getattr(app.state, "hardware_monitor", None)
    if hw:
        await hw.stop()
    refiner = getattr(app.state, "strategy_refiner", None)
    if refiner:
        await refiner.stop()
    # Stop legacy services
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

# ========================
# Phase 1 — MVP Architecture (core/)
# ========================
class MVPRequest(BaseModel):
    input: str
    task_type: str = "auto"


@app.get("/api/status")
async def phase1_status():
    """Phase 1 system status."""
    hw = getattr(app.state, "hardware_monitor", None)
    ep = getattr(app.state, "episodic_memory", None)
    llm = getattr(app.state, "llm", None)

    hw_load = hw.current_load.to_dict() if hw else {}
    ep_stats = await ep.get_stats() if ep else {}
    llm_health = await llm.health() if llm else {}

    return {
        "phase1": True,
        "hardware": hw_load,
        "episodic_memory": ep_stats,
        "llm": llm_health,
        "models_available": llm_model_names if llm_model_names else [],
    }


@app.on_event("startup")
async def cache_models():
    """Cache available model names on startup."""
    global llm_model_names
    llm = getattr(app.state, "llm", None)
    if llm:
        try:
            llm_model_names = await llm.available_model_names()
        except Exception:
            llm_model_names = []


llm_model_names: list[str] = []


@app.post("/api/chat")
async def mvp_chat(req: MVPRequest):
    """MVP chat endpoint using Phase 1 pipeline.

    Pipeline: INPUT → RAG_RECALL → MODEL_SELECT → RESPOND
    Full LangGraph state machine comes in Phase 2.
    """
    from core.state_machine import create_mvp_machine, WorkflowContext, State

    llm = getattr(app.state, "llm", None)
    ep = getattr(app.state, "episodic_memory", None)

    ctx = WorkflowContext(user_input=req.input)

    # RAG recall
    if ep:
        rag_results = await ep.search(req.input, k=3)
        ctx.rag_results = rag_results

    # Model selection
    model = ""
    if llm:
        available = await llm.available_model_names()
        if available:
            model = available[0]
    ctx.selected_model = model or "unknown"

    # Build response with context
    rag_context = ""
    if ctx.rag_results:
        rag_context = "\n".join(
            [r.get("compressed_summary", "")[:200] for r in ctx.rag_results[:2]]
        )

    response = f"[JANOS Phase 1 MVP] Model: {ctx.selected_model}"
    if rag_context:
        response += f"\n[Memory recall: {len(ctx.rag_results)} relevant episodes]"

    ctx.response = response

    # Store episode
    if ep:
        ep_id = await ep.store_episode(
            user_input=req.input,
            output=response,
            task_type=req.task_type,
            metadata={"model": ctx.selected_model},
        )
        ctx.episode_id = ep_id

    return {
        "response": response,
        "model": ctx.selected_model,
        "rag_results_count": len(ctx.rag_results),
        "episode_id": ctx.episode_id,
        "hardware": getattr(app.state, "hardware_monitor", None).current_load.to_dict()
        if getattr(app.state, "hardware_monitor", None) else {},
    }


@app.get("/api/memory/search")
async def memory_search(query: str, k: int = 5):
    """Search episodic memory."""
    ep = getattr(app.state, "episodic_memory", None)
    if not ep:
        return {"error": "Episodic memory not available"}
    results = await ep.search(query, k=k)
    return {"results": results}


@app.get("/api/memory/stats")
async def memory_stats():
    """Episodic memory statistics."""
    ep = getattr(app.state, "episodic_memory", None)
    if not ep:
        return {"error": "Episodic memory not available"}
    return await ep.get_stats()


@app.get("/api/memory/failures")
async def memory_failures(task_type: str = "general"):
    """Get failure patterns for a task type."""
    ep = getattr(app.state, "episodic_memory", None)
    if not ep:
        return {"error": "Episodic memory not available"}
    patterns = await ep.get_failure_patterns(task_type)
    return {"task_type": task_type, "patterns": patterns}


@app.get("/api/models")
async def list_models():
    """List available Ollama models."""
    llm = getattr(app.state, "llm", None)
    if not llm:
        return {"models": [], "error": "LLM client not initialized"}
    names = await llm.available_model_names()
    return {"models": names}


@app.post("/api/models/validate")
async def validate_ollama():
    """Validate Ollama endpoint."""
    llm = getattr(app.state, "llm", None)
    if not llm or not llm.ollama:
        return {"status": "error", "message": "Ollama provider not initialized"}
    result = await llm.ollama.validate()
    return result


# ========================
# Phase 2 — Full LangGraph + Agent Layer
# ========================
class V2ChatRequest(BaseModel):
    input: str
    use_debate: bool = False


@app.post("/api/v2/chat")
async def v2_chat(req: V2ChatRequest):
    """Full pipeline: RAG recall → model select → plan → execute → validate → store."""
    from core.langgraph_machine import WorkflowContext, State

    llm = getattr(app.state, "llm", None)
    mem = getattr(app.state, "episodic_memory", None)
    pipeline = getattr(app.state, "reasoning_pipeline", None)
    sm = getattr(app.state, "state_machine", None)
    agents = getattr(app.state, "agents", {})
    debate = getattr(app.state, "debate", None)

    ctx = WorkflowContext(user_input=req.input)

    if pipeline:
        ctx = await pipeline.run(ctx)

        if req.use_debate and debate:
            debate_result = await debate.debate(req.input, context=ctx.task_plan)
            ctx.task_plan = debate_result.get("final_plan", ctx.task_plan)
            ctx.metadata["debate"] = debate_result

        if agents.get("executor"):
            ctx.agent_output = await agents["executor"].execute_step(ctx.task_plan)

        if agents.get("critic"):
            val = await agents["critic"].validate(ctx.agent_output, req.input, ctx.errors)
            ctx.outcome_score = val.get("score", 0.0)
    else:
        ctx.final_output = f"[Phase 2] Pipeline not initialized. Input: {req.input[:100]}"

    response_text = ctx.agent_output or ctx.final_output or ctx.task_plan

    if mem and not ctx.episode_id:
        ctx.episode_id = await mem.store_episode(
            user_input=req.input,
            reasoning_steps=ctx.reasoning_steps,
            output=response_text,
            outcome_score=ctx.outcome_score,
            task_type=ctx.task_type or "general",
            duration_ms=ctx.duration_ms,
            errors=ctx.errors,
        )

    return {
        "response": response_text,
        "model": ctx.selected_model,
        "task_type": ctx.task_type,
        "reasoning_steps": ctx.reasoning_steps[-5:],
        "episode_id": ctx.episode_id,
        "score": ctx.outcome_score,
        "retries": ctx.retry_count,
    }


@app.get("/api/v2/agents")
async def v2_list_agents():
    """List all Phase 2 agents."""
    agents = getattr(app.state, "agents", {})
    return {
        "count": len(agents),
        "agents": {k: v.schema() for k, v in agents.items()},
    }


@app.post("/api/v2/agents/run")
async def v2_run_agent(name: str, task: str):
    """Run a specific agent."""
    agents = getattr(app.state, "agents", {})
    agent = agents.get(name)
    if not agent:
        return {"error": f"Agent '{name}' not found"}
    result = await agent.think(task)
    return {"agent": name, "response": result}


@app.post("/api/v2/debate")
async def v2_debate(req: V2ChatRequest):
    """Run AutoGen debate on a complex task."""
    debate = getattr(app.state, "debate", None)
    if not debate:
        return {"error": "Debate system not initialized"}
    result = await debate.debate(req.input)
    return result


# ========================
# Phase 3 — Self-Healing + Validation
# ========================
class ValidateRequest(BaseModel):
    output: str
    task: str
    errors: list[str] = []


@app.post("/api/v3/validate")
async def v3_validate(req: ValidateRequest):
    """Validate an agent output."""
    critic = getattr(app.state, "critic", None)
    if not critic:
        return {"error": "Critic not initialized"}
    result = await critic.validate_output(req.output, req.task, req.errors)
    return result


@app.post("/api/v3/heal")
async def v3_heal(req: ValidateRequest):
    """Self-heal: diagnose failure and suggest fix."""
    mem = getattr(app.state, "episodic_memory", None)
    critic = getattr(app.state, "critic", None)
    if not critic:
        return {"error": "Critic not initialized"}

    past = ""
    if mem:
        patterns = await mem.get_failure_patterns(req.task.split()[0] if req.task else "general")
        past = "\n".join([p.get("summary", "") for p in patterns[:2]])

    result = await critic.self_heal(req.task, req.errors, past)
    return result


@app.get("/api/v3/rankings")
async def v3_rankings():
    """Get agent and model rankings."""
    routing = getattr(app.state, "routing_engine", None)
    if not routing:
        return {"error": "Routing engine not initialized"}
    return {
        "agents": routing.get_agent_rankings(),
        "models": routing.get_model_rankings(),
    }


# ========================
# Phase 4 — Commands + Privilege
# ========================
@app.post("/api/v4/command")
async def v4_command(input: str):
    """Execute a /command."""
    from core.commands import parse_command

    parsed = parse_command(input)
    if not parsed["is_command"]:
        return {"is_command": False, "response": "Not a command. Use /help to see commands."}

    cmd_handler = getattr(app.state, "command_handler", None)
    descriptor = getattr(app.state, "descriptor", None)

    cmd = parsed["command"]
    args = parsed["args"]

    if cmd == "help":
        return {"response": cmd_handler.help_text() if cmd_handler else "No commands registered"}

    if cmd == "describe" or cmd == "who":
        if descriptor:
            descriptor.hardware_info = getattr(app.state, "hardware_monitor", None).current_load.to_dict() or {}
            llm = getattr(app.state, "llm", None)
            if llm:
                descriptor.model_names = await llm.available_model_names()
            return {"response": descriptor.describe()}
        return {"response": "Self-description not available"}

    if cmd_handler:
        result = await cmd_handler.execute(cmd, args)
        return {"response": result}

    return {"response": f"Command /{cmd} not handled"}


@app.post("/api/v4/exec")
async def v4_exec(command: str, confirm: bool = False, justification: str = ""):
    """Execute a privileged shell command."""
    pshell = getattr(app.state, "privileged_shell", None)
    if not pshell:
        return {"error": "Privileged shell not initialized"}
    result = await pshell.execute(
        command=command,
        confirm=confirm,
        justification=justification or f"User requested: {command[:100]}",
    )
    return result


@app.get("/api/v4/audit")
async def v4_audit(limit: int = 20):
    """Get privilege audit log."""
    pshell = getattr(app.state, "privileged_shell", None)
    if not pshell:
        return {"error": "Privileged shell not initialized"}
    return {"entries": pshell.get_audit_log(limit=limit)}


# ========================
# Phase 5 — Continuous Learning
# ========================
@app.post("/api/v5/refine")
async def v5_refine():
    """Trigger strategy refinement cycle."""
    refiner = getattr(app.state, "strategy_refiner", None)
    if not refiner:
        return {"error": "Strategy refiner not initialized"}
    result = await refiner.run_refinement()
    return result


@app.post("/api/v5/generate-tool")
async def v5_generate_tool(capability: str):
    """Generate a new tool module stub for a missing capability."""
    refiner = getattr(app.state, "strategy_refiner", None)
    if not refiner:
        return {"error": "Strategy refiner not initialized"}
    result = await refiner.generate_module_stub(capability)
    return result


# ========================
# Feedback API
# ========================
class FeedbackRequest(BaseModel):
    task_id: str
    rating: int
    comment: Optional[str] = None

@app.post("/feedback")
def submit_feedback(req: FeedbackRequest):
    """Rate a completed task 1-5. Use task_id from any /chat response."""
    if "feedback" not in modules_pkg.MODULES:
        raise HTTPException(status_code=503, detail="Feedback module not loaded")
    return modules_pkg.MODULES["feedback"].process({
        "action": "collect",
        "task_id": req.task_id,
        "rating": req.rating,
        "comment": req.comment or "",
    })

@app.get("/feedback/stats")
def feedback_stats():
    """Feedback statistics per agent — average rating, distribution."""
    if "feedback" not in modules_pkg.MODULES:
        return {"error": "not loaded"}
    return modules_pkg.MODULES["feedback"].process({"action": "stats"})

@app.get("/feedback/worst")
def feedback_worst():
    """Lowest-rated agents — where improvement is most needed."""
    if "feedback" not in modules_pkg.MODULES:
        return {"error": "not loaded"}
    return modules_pkg.MODULES["feedback"].process({"action": "worst"})

@app.get("/feedback/pending")
def feedback_pending():
    """Tasks awaiting user rating."""
    if "feedback" not in modules_pkg.MODULES:
        return {"error": "not loaded"}
    return modules_pkg.MODULES["feedback"].process({"action": "pending"})


# ========================
# Recovery API
# ========================
@app.get("/recovery/stats")
def recovery_stats():
    """Auto-recovery stats — how many errors were fixed autonomously."""
    return modules_pkg.ORCHESTRATOR.recovery.process({"action": "stats"})

@app.get("/recovery/log")
def recovery_log():
    """Recent autonomous recovery attempts and their outcomes."""
    return modules_pkg.ORCHESTRATOR.recovery.process({"action": "log", "limit": 30})

@app.get("/recovery/cache")
def recovery_cache():
    """Solutions JAN has cached — error patterns it can now fix instantly."""
    return modules_pkg.ORCHESTRATOR.recovery.process({"action": "cache"})


@app.get("/health")
async def health():
    daemon_running = False
    wake_word_running = False
    if "daemon" in modules_pkg.MODULES:
        ds = modules_pkg.MODULES["daemon"].process({"action": "status"})
        daemon_running = ds.get("running", False)
    if "wake_word" in modules_pkg.MODULES:
        ws = modules_pkg.MODULES["wake_word"].process({"action": "status"})
        wake_word_running = ws.get("running", False)

    hw = getattr(app.state, "hardware_monitor", None)
    phase1 = {
        "active": hasattr(app.state, "llm"),
        "hardware": hw.current_load.to_dict() if hw else {},
    }

    agents = getattr(app.state, "agents", {})
    routing = getattr(app.state, "routing_engine", None)
    phase2 = {
        "active": len(agents) > 0,
        "agents": list(agents.keys()),
        "has_debate": hasattr(app.state, "debate"),
    }
    phase3 = {"active": hasattr(app.state, "critic")}
    phase4 = {
        "active": hasattr(app.state, "command_handler"),
    }
    cmd_h = getattr(app.state, "command_handler", None)
    if cmd_h:
        phase4["commands"] = len(cmd_h.list_commands())
    phase5 = {"active": hasattr(app.state, "strategy_refiner")}

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
        "phase1": phase1,
        "phase2": phase2,
        "phase3": phase3,
        "phase4": phase4,
        "phase5": phase5,
    }
