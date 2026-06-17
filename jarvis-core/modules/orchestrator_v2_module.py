# modules/orchestrator_v2_module.py
"""
Orchestrator v2 — Agent Dispatcher
The brain of JAN v2. Classifies user intent → picks the right agent → delegates.
Keeps conversation context across turns. Supports agent-to-agent communication.
"""
import json
import re
import uuid
import requests
from datetime import datetime
from .base import ModuleBase
from .autonomous_recovery import AutonomousRecovery, _is_error


class OrchestratorV2Module(ModuleBase):
    """
    JAN v2 Orchestrator — dispatches tasks to specialized agents.
    Replaces the single-shot v1 orchestrator with a multi-agent dispatcher.
    """

    OLLAMA_URL = "http://localhost:11434/api/chat"
    ROUTER_MODEL = "qwen2.5:7b-instruct"

    # ── Agent categories for routing ──────────────────────────────

    AGENT_DESCRIPTIONS = {
        "chat": "Casual conversation, greetings, humor, simple Q&A, personality",
        "browser": "Navigate websites, click buttons, fill forms, read web pages, interact with web apps",
        "media": "Play music/videos on YouTube or Spotify, skip tracks, control playback, media control",
        "communication": "Send/read/reply emails, WhatsApp messages, Discord, messaging, notifications",
        "research": "Deep web research, search multiple sources, read articles, summarize findings",
        "memory": "Remember things, recall past conversations, manage preferences, user profiling",
        "productivity": "Reminders, timers, to-do lists, daily briefings, scheduling, focus mode",
        "file": "File management, organize folders, search/read/create/move/delete files, documents",
        "system": "Open/close apps, manage windows, volume, brightness, system settings, process control",
        "coding": "Write code, debug, create scripts, build modules, programming tasks",
        "creative": "Write emails/essays/reports/posts, draft content, brainstorm ideas, content creation",
        "automation": "Complex multi-step workflows, chain multiple tasks, scheduled operations",
        "vision": "Analyze screenshots, identify UI elements, camera, face recognition, OCR on images",
        "self_improvement": "Create new JAN modules, learn from failures, improve capabilities",
    }

    # ── Keyword routing (fast path, no LLM needed) ────────────────

    KEYWORD_ROUTES = {
        "chat": [
            "hello", "hi ", "hey ", "hey!", "howdy", "salam", "assalam",
            "thank", "thanks", "shukriya", "bye", "goodbye",
            "who are you", "what is your name", "what's your name",
            "what is my name", "how are you", "kaise ho", "kya haal",
            "good morning", "good night", "good evening",
            "what is the weather", "what's the weather", "weather in ",
            "weather today", "kya mausam",
            "what time", "what date", "what day",
            "joke", "tell me a joke",
        ],
        "media": [
            "play ", "play music", "play song", "play video",
            "spotify", "youtube", "next track", "skip song", "skip track",
            "previous track", "previous song",
            "pause music", "pause song", "resume music", "resume song",
            "volume up", "volume down",
            "next song", "stop music", "stop playing",
            "bajao", "gaana", "gana",
        ],
        "communication": [
            "send email", "write email", "compose email", "reply email",
            "write a mail", "send a mail", "compose a mail", "email to",
            "check email", "read email", "open email", "gmail",
            "whatsapp", "send message to", "text to ", "discord",
            "mail bhejo", "email bhejo",
        ],
        "research": [
            "research ", "look up ", "find out about",
            "search for ", "search about ", "tell me about ",
            "explain ", "how does ", "how do ", "why does ", "why is ",
            "what is a ", "what are ", "what is the ",
        ],
        "memory": [
            "remember ", "recall ", "forget ", "what did i say",
            "i prefer", "my preference", "save this", "yaad rakh",
        ],
        "productivity": [
            "remind me", "reminder", "timer", "to-do", "todo",
            "briefing", "daily briefing", "morning briefing",
            "schedule", "focus mode", "pomodoro",
        ],
        "file": [
            "find file", "search file", "open file", "read file",
            "create file", "delete file", "move file", "copy file",
            "organize files", "downloads folder", "documents folder",
        ],
        "system": [
            "open chrome", "open vscode", "open terminal",
            "close chrome", "close vscode",
            "open google chrome", "close app", "launch app",
            "minimize window", "maximize window",
            "set volume", "mute", "unmute", "brightness",
            "shutdown", "restart", "lock screen", "lock computer",
            "system settings",
        ],
        "coding": [
            "write code", "code for ", "debug ", "fix bug", "create module",
            "write a script", "write a function", "write a class",
            "python code", "javascript code",
            "program ", "implement ", "refactor ",
        ],
        "creative": [
            "draft an email", "draft a ", "write an essay",
            "write a report", "write an article",
            "blog post", "social media post", "write a letter",
            "brainstorm ", "write a story",
        ],
        "browser": [
            "go to ", "navigate to ", "open website", "open page",
            "open url", "browse ", "open site",
            "open chatgpt", "open github",
        ],
    }

    # ── Priority order for keyword disambiguation ─────────────────
    # agents that handle real tasks (not pure chat) — feedback is worth collecting
    FEEDBACK_AGENTS = {
        "browser", "media", "communication", "research", "file",
        "system", "coding", "creative", "automation", "vision", "self_improvement",
    }

    KEYWORD_PRIORITY = [
        "media", "communication", "system", "chat", "creative", "coding",
        "productivity", "file", "memory", "browser", "research",
    ]

    def __init__(self):
        super().__init__("orchestrator_v2")
        self.agents = {}                  # name → agent instance
        self.modules_registry = {}        # name → module instance (for backwards compat)
        self.conversation_history = []
        self.max_history = 30
        self.memory = None
        self.smart_tts = None
        self.learning_engine = None
        self.feedback = None              # wired from __init__.py
        self.recovery = AutonomousRecovery()
        self.auto_voice = True
        self.default_city = "Islamabad"

    # ── Agent Registration ─────────────────────────────────────────

    def register_agent(self, name, agent_instance):
        """Register a specialized agent."""
        self.agents[name] = agent_instance
        agent_instance.dispatcher = self  # allow agent-to-agent calls

    # ── Intent Classification ──────────────────────────────────────

    def _classify_keyword(self, message):
        """Fast keyword-based intent classification (no LLM call)."""
        msg_lower = message.lower().strip()

        # Check keywords in priority order
        for agent_name in self.KEYWORD_PRIORITY:
            keywords = self.KEYWORD_ROUTES.get(agent_name, [])
            for kw in keywords:
                if kw in msg_lower:
                    return agent_name, f"keyword match: '{kw}'"

        return None, None

    def _classify_llm(self, message):
        """LLM-based intent classification for ambiguous messages."""
        agent_list = "\n".join(
            f"  - {name}: {desc}" for name, desc in self.AGENT_DESCRIPTIONS.items()
        )

        prompt = f"""Classify this user message into exactly ONE agent category.

AGENTS:
{agent_list}

USER MESSAGE: "{message}"

Respond with ONLY a JSON object:
{{"agent": "agent_name", "reason": "brief reason"}}

Pick the MOST specific agent. If it's casual talk → chat. If it involves a website → browser.
If it's about playing music/videos → media. If it chains multiple tasks → automation."""

        try:
            resp = requests.post(self.OLLAMA_URL, json={
                "model": self.ROUTER_MODEL,
                "messages": [
                    {"role": "system", "content": "You classify user intents. Respond ONLY with JSON."},
                    {"role": "user", "content": prompt}
                ],
                "stream": False,
                "options": {"temperature": 0.2, "num_predict": 128}
            }, timeout=30)
            raw = resp.json()["message"]["content"].strip()

            # Parse JSON
            if "```" in raw:
                match = re.search(r'```(?:json)?\s*\n?(.*?)\n?\s*```', raw, re.DOTALL)
                if match:
                    raw = match.group(1).strip()

            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start != -1 and end > start:
                data = json.loads(raw[start:end])
                agent = data.get("agent", "chat")
                reason = data.get("reason", "LLM classified")
                if agent in self.AGENT_DESCRIPTIONS:
                    return agent, reason
                # Try fuzzy match
                for name in self.AGENT_DESCRIPTIONS:
                    if name in agent or agent in name:
                        return name, reason

            return "chat", "LLM parse fallback"
        except Exception as e:
            return "chat", f"LLM classification error: {e}"

    def classify_intent(self, message):
        """Classify user intent: try keywords first, then LLM."""
        # Fast path: keyword match
        agent, reason = self._classify_keyword(message)
        if agent:
            return agent, reason

        # Slow path: LLM classification
        agent, reason = self._classify_llm(message)
        return agent, reason

    # ── Agent Execution ────────────────────────────────────────────

    def run_agent(self, agent_name, task, context=None):
        """Run a specific agent. On failure, attempt autonomous recovery and retry."""
        if agent_name not in self.agents:
            return {
                "status": "error",
                "error": f"Agent '{agent_name}' not found. Available: {list(self.agents.keys())}",
                "response": f"I don't have a {agent_name} agent.",
            }

        agent = self.agents[agent_name]
        if context is None:
            context = {"conversation_history": self.conversation_history[-10:]}

        try:
            result = agent.run(task, context)
        except Exception as e:
            result = {"status": "error", "agent": agent_name,
                      "error": str(e), "response": f"Agent '{agent_name}' crashed: {e}"}

        # ── Autonomous recovery on agent error ────────────────────────
        if result.get("status") == "error":
            error_msg = result.get("error", "")
            # Also check the last step's observation for module-level errors
            steps = result.get("steps", [])
            if steps:
                last_obs = steps[-1].get("observation", {})
                if isinstance(last_obs, dict) and last_obs.get("error"):
                    error_msg = str(last_obs["error"])

            if error_msg:
                self.recovery.modules_registry = self.modules_registry
                self.recovery.web_search       = self.modules_registry.get("web_search")
                self.recovery.module_generator = self.modules_registry.get("module_generator")
                self.recovery.learning_engine  = self.learning_engine

                # After any fix, re-run the agent on the same task
                def execute_fn(_action):
                    try:
                        return agent.run(task, context)
                    except Exception as ex:
                        return {"status": "error", "error": str(ex)}

                recovery = self.recovery.recover(
                    error_msg, agent_name,
                    {"module": agent_name, "input": {"task": task}},
                    execute_fn,
                )
                if recovery["recovered"]:
                    result = recovery["result"]
                    if isinstance(result, dict):
                        result["auto_recovered"] = recovery["fix_applied"]
                    print(f"[v2] Agent '{agent_name}' recovered: {recovery['fix_applied']}")
                elif recovery["diagnosis"]:
                    result["diagnosis"] = recovery["diagnosis"]

        return result

    # ── Main Process ───────────────────────────────────────────────

    def process(self, input_data):
        """
        Main entry point. Takes a natural language message, classifies it,
        dispatches to the right agent, and returns the result.
        """
        user_message = input_data.get("message", "")
        if not user_message:
            return {"error": "No message provided. Send {'message': 'your text here'}"}

        # 1. Classify intent
        agent_name, classification_reason = self.classify_intent(user_message)

        # 2. Check if agent exists, fall back to chat
        if agent_name not in self.agents:
            agent_name = "chat"
            classification_reason = f"agent '{agent_name}' not registered, falling back to chat"

        # 3. Build context
        context = {
            "conversation_history": self.conversation_history[-self.max_history:],
            "default_city": self.default_city,
        }

        # 4. Run the agent
        result = self.run_agent(agent_name, user_message, context)

        # 4b. FALLBACK: If agent failed or hit max steps, try research agent
        if result.get("status") in ("error", "max_steps_reached") and agent_name not in ("research", "chat", "browser"):
            print(f"[orchestrator_v2] Agent '{agent_name}' failed ({result.get('status')}), trying research agent as fallback")
            fallback_task = f"The {agent_name} agent couldn't handle this request. Please help: {user_message}"
            fallback_result = self.run_agent("research", fallback_task, context)
            if fallback_result.get("status") == "ok" and fallback_result.get("response"):
                result = fallback_result
                agent_name = "research"
                classification_reason += " → fallback to research"

        # 5. Extract response
        response = result.get("response", "")
        if not response and result.get("error"):
            response = f"Something went wrong: {result['error']}"

        # 6. Update conversation history
        self.conversation_history.append({"role": "user", "content": user_message})
        self.conversation_history.append({"role": "assistant", "content": response})
        if len(self.conversation_history) > self.max_history * 2:
            self.conversation_history = self.conversation_history[-(self.max_history * 2):]

        # 7. Save to long-term memory
        if self.memory:
            try:
                self.memory.save_conversation("user", user_message)
                self.memory.save_conversation("assistant", response)
            except Exception:
                pass

        # 8. Auto-speak response
        voice_status = None
        if self.auto_voice and self.smart_tts and response:
            try:
                speak_text = response.split("\n\n⚠️")[0].strip()[:500]
                if speak_text:
                    voice_result = self.smart_tts.process({"action": "speak", "text": speak_text})
                    voice_status = voice_result.get("status", "error")
            except Exception:
                voice_status = "error"

        # 9. Register with feedback module
        task_id = str(uuid.uuid4())[:8]
        if self.feedback and agent_name in self.FEEDBACK_AGENTS:
            try:
                self.feedback.register_task(
                    task_id=task_id,
                    user_input=user_message,
                    agent_used=agent_name,
                    modules_used=list(self.agents[agent_name].tools.keys())
                                 if agent_name in self.agents else [],
                    response_text=response,
                )
            except Exception:
                pass

        return {
            "status": result.get("status", "ok"),
            "agent": agent_name,
            "classification_reason": classification_reason,
            "response": response,
            "steps_taken": result.get("steps_taken", 0),
            "steps": result.get("steps", []),
            "voice": voice_status,
            "task_id": task_id,
            "auto_recovered": result.get("auto_recovered"),
            "diagnosis": result.get("diagnosis"),
        }
