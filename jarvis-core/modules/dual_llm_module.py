# modules/dual_llm_module.py
import re
import time
import json
import threading
import requests
from datetime import datetime
from .base import ModuleBase

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False


class DualLLMModule(ModuleBase):
    """
    Manages two LLMs — a small always-on model for simple tasks and a big
    on-demand model for complex reasoning. Routes queries automatically based
    on complexity analysis and system resources.
    """

    COMPLEX_KEYWORDS = [
        "code", "analyze", "analyse", "generate", "research", "plan",
        "explain", "compare", "create", "build", "implement", "design",
        "debug", "refactor", "optimize", "write a", "write me",
        "how to", "how do", "how does", "how would", "why does", "why is",
        "what if", "step by step", "in detail", "elaborate",
        "translate", "summarize", "summarise", "review", "evaluate",
        "architecture", "algorithm", "function", "class", "module",
        "script", "program", "essay", "story", "poem", "article",
    ]

    SIMPLE_KEYWORDS = [
        "hi", "hello", "hey", "thanks", "thank you", "bye", "goodbye",
        "yes", "no", "ok", "okay", "sure", "good", "fine",
        "what time", "what date", "what day", "status", "ping",
    ]

    FORCE_BIG_PHRASES = [
        "think harder", "use big model", "use large model",
        "deep think", "think deeply", "think more",
    ]

    def __init__(self):
        super().__init__("dual_llm")
        self.small_model = "qwen2.5:7b-instruct"
        self.big_model = "llama3.1:8b"
        self.ollama_url = "http://localhost:11434"
        self.big_model_loaded = False
        self.last_big_model_use = None
        self.idle_timeout = 600  # seconds
        self.stats = {
            "small_queries": 0,
            "big_queries": 0,
            "small_avg_ms": 0.0,
            "big_avg_ms": 0.0,
        }
        self._lock = threading.Lock()
        self._idle_timer = None
        self._available_models = self._fetch_available_models()

    def _fetch_available_models(self):
        """Fetch available models from Ollama, fall back to defaults on failure."""
        try:
            resp = requests.get(f"{self.ollama_url}/api/tags", timeout=5)
            if resp.status_code == 200:
                models = [m["name"] for m in resp.json().get("models", [])]
                if models:
                    self.big_model = next((m for m in models if "llama" in m or "gemma" in m or "qwen3" in m), models[0])
                    self.small_model = next((m for m in models if "qwen2.5" in m and "instruct" in m), models[-1])
                    return models
            return []
        except Exception:
            return []

    # ── Public interface ──────────────────────────────────────────────

    def process(self, input_data):
        if isinstance(input_data, str):
            input_data = {"action": "chat", "message": input_data}

        action = input_data.get("action", "chat")

        try:
            if action == "route":
                return self._action_route(input_data)
            elif action == "chat":
                return self._action_chat(input_data)
            elif action == "load_big":
                return self._action_load_big()
            elif action == "unload_big":
                return self._action_unload_big()
            elif action == "set_models":
                return self._action_set_models(input_data)
            elif action == "stats":
                return self._action_stats()
            elif action == "check_resources":
                return self._action_check_resources()
            elif action == "set_timeout":
                return self._action_set_timeout(input_data)
            else:
                return {"error": f"Unknown action: {action}"}
        except Exception as e:
            return {"error": str(e)}

    # ── Action handlers ───────────────────────────────────────────────

    def _action_route(self, input_data):
        message = input_data.get("message", "")
        if not message:
            return {"error": "No message provided"}
        complexity, reason = self._classify_complexity(message)
        model = self.big_model if complexity == "complex" else self.small_model
        return {"status": "ok", "model": model, "complexity": complexity, "reason": reason}

    def _action_chat(self, input_data):
        message = input_data.get("message", "")
        if not message:
            return {"error": "No message provided"}

        system_prompt = input_data.get("system_prompt")
        force_model = input_data.get("force_model")

        # Determine which model to use
        if force_model == "big":
            model = self.big_model
            complexity = "complex"
            reason = "forced by user (big)"
        elif force_model == "small":
            model = self.small_model
            complexity = "simple"
            reason = "forced by user (small)"
        else:
            complexity, reason = self._classify_complexity(message)
            model = self.big_model if complexity == "complex" else self.small_model

        # Resource gate: if big model requested but resources are tight, downgrade
        if model == self.big_model:
            resources = self._check_resources()
            available_ram = resources.get("available_ram_gb", 999)
            cpu_percent = resources.get("cpu_percent", 0)
            if available_ram < 4.0:
                model = self.small_model
                reason = f"auto-downgraded: low RAM ({available_ram:.1f} GB available)"
            elif cpu_percent > 90:
                model = self.small_model
                reason = f"auto-downgraded: high CPU ({cpu_percent:.0f}%)"

        # Ensure the chosen model is loaded
        load_result = self._ensure_model_loaded(model)
        if "error" in load_result:
            # If big model fails to load, try small model as fallback
            if model == self.big_model:
                model = self.small_model
                reason = f"fallback to small: {load_result['error']}"
                load_result = self._ensure_model_loaded(model)
                if "error" in load_result:
                    return {"error": f"Failed to load any model: {load_result['error']}"}
            else:
                return load_result

        # Build messages payload
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": message})

        # Send chat request and measure time
        start = time.time()
        result = self._chat(model, messages)
        elapsed_ms = (time.time() - start) * 1000

        if "error" in result:
            # Auto-downgrade on timeout / slow response from big model
            if model == self.big_model and elapsed_ms > 30000:
                model = self.small_model
                reason = f"auto-downgraded: big model too slow ({elapsed_ms:.0f}ms)"
                start = time.time()
                result = self._chat(model, messages)
                elapsed_ms = (time.time() - start) * 1000
                if "error" in result:
                    return result
            else:
                return result

        # Update stats
        self._update_stats(model, elapsed_ms)

        # Track big model usage for idle timeout
        if model == self.big_model:
            self.last_big_model_use = time.time()
            self._schedule_idle_check()

        return {
            "status": "ok",
            "response": result.get("response", ""),
            "model_used": model,
            "complexity": complexity,
            "reason": reason,
            "time_ms": round(elapsed_ms, 1),
        }

    def _action_load_big(self):
        result = self._ensure_model_loaded(self.big_model)
        if "error" in result:
            return result
        self.big_model_loaded = True
        self.last_big_model_use = time.time()
        self._schedule_idle_check()
        return {"status": "ok", "message": f"{self.big_model} loaded"}

    def _action_unload_big(self):
        result = self._unload_model(self.big_model)
        if "error" in result:
            return result
        self.big_model_loaded = False
        self.last_big_model_use = None
        return {"status": "ok", "message": f"{self.big_model} unloaded"}

    def _action_set_models(self, input_data):
        changed = []
        if "small_model" in input_data:
            self.small_model = input_data["small_model"]
            changed.append(f"small={self.small_model}")
        if "big_model" in input_data:
            self.big_model = input_data["big_model"]
            changed.append(f"big={self.big_model}")
        if not changed:
            return {"error": "Provide small_model and/or big_model"}
        return {"status": "ok", "message": f"Models updated: {', '.join(changed)}"}

    def _action_stats(self):
        return {
            "status": "ok",
            "small_model": self.small_model,
            "big_model": self.big_model,
            "big_model_loaded": self.big_model_loaded,
            "idle_timeout_minutes": self.idle_timeout / 60,
            **self.stats,
        }

    def _action_check_resources(self):
        resources = self._check_resources()
        return {"status": "ok", **resources}

    def _action_set_timeout(self, input_data):
        minutes = input_data.get("minutes")
        if minutes is None:
            return {"error": "Provide 'minutes' (int)"}
        try:
            minutes = int(minutes)
        except (TypeError, ValueError):
            return {"error": "'minutes' must be an integer"}
        if minutes < 1:
            return {"error": "'minutes' must be >= 1"}
        self.idle_timeout = minutes * 60
        return {"status": "ok", "message": f"Idle timeout set to {minutes} minutes"}

    # ── Complexity classification ─────────────────────────────────────

    def _classify_complexity(self, message):
        msg_lower = message.lower().strip()
        words = msg_lower.split()
        word_count = len(words)

        # Explicit "think harder" / force-big phrases
        for phrase in self.FORCE_BIG_PHRASES:
            if phrase in msg_lower:
                return "complex", f"user requested deeper reasoning ('{phrase}')"

        # Very short messages are almost always simple
        if word_count <= 3:
            for kw in self.SIMPLE_KEYWORDS:
                if kw in msg_lower:
                    return "simple", "short greeting/response"
            # Still short but might be a complex keyword
            for kw in self.COMPLEX_KEYWORDS:
                if kw in msg_lower:
                    return "complex", f"complex keyword '{kw}' detected"
            return "simple", "very short query"

        # Check for complex keywords / patterns
        for kw in self.COMPLEX_KEYWORDS:
            if kw in msg_lower:
                return "complex", f"complex keyword '{kw}' detected"

        # Code indicators: backticks, common programming tokens
        if re.search(r'```|def |class |import |function |const |let |var |=>|&&|\|\|', message):
            return "complex", "code content detected"

        # Long messages are likely complex
        if word_count > 50:
            return "complex", f"long message ({word_count} words)"

        # Question complexity
        if msg_lower.startswith(("who ", "what ", "when ", "where ")) and word_count < 15:
            return "simple", "short factual question"
        if msg_lower.startswith(("why ", "how ")) and word_count > 10:
            return "complex", "open-ended how/why question"

        # Medium length, no strong signals → default simple
        if word_count < 20:
            return "simple", f"short message ({word_count} words), no complexity signals"

        return "simple", "no strong complexity signals"

    # ── Resource monitoring ───────────────────────────────────────────

    def _check_resources(self):
        if not HAS_PSUTIL:
            return {
                "available_ram_gb": -1,
                "total_ram_gb": -1,
                "cpu_percent": -1,
                "psutil_available": False,
            }
        try:
            ram = psutil.virtual_memory()
            available_gb = ram.available / (1024 ** 3)
            total_gb = ram.total / (1024 ** 3)
            cpu_percent = psutil.cpu_percent(interval=0.5)
            return {
                "available_ram_gb": round(available_gb, 2),
                "total_ram_gb": round(total_gb, 2),
                "ram_percent_used": ram.percent,
                "cpu_percent": cpu_percent,
                "psutil_available": True,
            }
        except Exception:
            return {
                "available_ram_gb": -1,
                "total_ram_gb": -1,
                "cpu_percent": -1,
                "psutil_available": False,
            }

    # ── Ollama model management ───────────────────────────────────────

    def _ensure_model_loaded(self, model_name):
        try:
            resp = requests.post(
                f"{self.ollama_url}/api/generate",
                json={"model": model_name, "prompt": "", "keep_alive": "10m"},
                timeout=120,
            )
            if resp.status_code == 200:
                if model_name == self.big_model:
                    self.big_model_loaded = True
                return {"status": "ok"}
            return {"error": f"Ollama returned {resp.status_code}: {resp.text[:200]}"}
        except requests.ConnectionError:
            return {"error": "Cannot connect to Ollama — is it running?"}
        except requests.Timeout:
            return {"error": f"Timeout loading model {model_name}"}
        except Exception as e:
            return {"error": f"Failed to load {model_name}: {e}"}

    def _unload_model(self, model_name):
        try:
            resp = requests.post(
                f"{self.ollama_url}/api/generate",
                json={"model": model_name, "keep_alive": 0},
                timeout=30,
            )
            if resp.status_code == 200:
                if model_name == self.big_model:
                    self.big_model_loaded = False
                return {"status": "ok"}
            return {"error": f"Ollama returned {resp.status_code}: {resp.text[:200]}"}
        except requests.ConnectionError:
            return {"error": "Cannot connect to Ollama — is it running?"}
        except Exception as e:
            return {"error": f"Failed to unload {model_name}: {e}"}

    def _chat(self, model, messages, options=None):
        payload = {"model": model, "messages": messages, "stream": False}
        if options:
            payload["options"] = options
        try:
            resp = requests.post(
                f"{self.ollama_url}/api/chat",
                json=payload,
                timeout=300,
            )
            if resp.status_code != 200:
                return {"error": f"Ollama chat error {resp.status_code}: {resp.text[:200]}"}
            data = resp.json()
            content = data.get("message", {}).get("content", "")
            return {"response": content}
        except requests.ConnectionError:
            return {"error": "Cannot connect to Ollama — is it running?"}
        except requests.Timeout:
            return {"error": f"Chat request timed out for model {model}"}
        except Exception as e:
            return {"error": f"Chat failed: {e}"}

    # ── Idle timeout management ───────────────────────────────────────

    def _schedule_idle_check(self):
        with self._lock:
            if self._idle_timer is not None:
                self._idle_timer.cancel()
            self._idle_timer = threading.Timer(self.idle_timeout, self._check_idle_timeout)
            self._idle_timer.daemon = True
            self._idle_timer.start()

    def _check_idle_timeout(self):
        if not self.big_model_loaded or self.last_big_model_use is None:
            return
        elapsed = time.time() - self.last_big_model_use
        if elapsed >= self.idle_timeout:
            self._unload_model(self.big_model)
            self.big_model_loaded = False
            self.last_big_model_use = None

    # ── Stats tracking ────────────────────────────────────────────────

    def _update_stats(self, model, elapsed_ms):
        with self._lock:
            if model == self.small_model:
                n = self.stats["small_queries"]
                avg = self.stats["small_avg_ms"]
                self.stats["small_avg_ms"] = round((avg * n + elapsed_ms) / (n + 1), 1)
                self.stats["small_queries"] = n + 1
            else:
                n = self.stats["big_queries"]
                avg = self.stats["big_avg_ms"]
                self.stats["big_avg_ms"] = round((avg * n + elapsed_ms) / (n + 1), 1)
                self.stats["big_queries"] = n + 1
