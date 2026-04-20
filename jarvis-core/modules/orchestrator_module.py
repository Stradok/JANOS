# modules/orchestrator_module.py
import json
import re
import requests
from datetime import datetime
from .base import ModuleBase


class OrchestratorModule(ModuleBase):
    """
    The brain of JAN. Takes natural language, thinks via Ollama LLM,
    decides which module(s) to call, executes them, and responds naturally.
    """

    OLLAMA_URL = "http://localhost:11434/api/chat"
    DEFAULT_MODEL = "qwen2.5:7b-instruct"

    # Fuzzy name map: common LLM mistakes → correct module name
    MODULE_ALIASES = {
        "search_web": "web_search",
        "websearch": "web_search",
        "internet_search": "web_search",
        "google": "web_search",
        "search": "web_search",
        "file_search": "file_manager",
        "files": "file_manager",
        "email": "browser",
        "gmail": "browser",
        "open_app": "app_launcher",
        "launch": "app_launcher",
        "volume": "system_control",
        "clipboard": "system_control",
        "screenshot": "keyboard_mouse",
        "type": "keyboard_mouse",
        "speak": "smart_tts",
        "voice": "smart_tts",
        "tts_speak": "smart_tts",
        "listen": "stt",
        "camera": "vision",
        "face": "person_recognition",
        "research": "research_agent",
        "learn": "research_agent",
        "generate_module": "module_generator",
        "create_module": "module_generator",
        "play_music": "spotify",
        "music": "spotify",
        "play_video": "youtube",
        "video": "youtube",
        "remember": "memory",
        "recall": "memory",
        "navigate": "browser",
    }

    SYSTEM_PROMPT = """You are JAN (Joint Autonomous Neural Agent). You are a personal AI assistant running on a Windows PC in Islamabad, Pakistan. You are loyal, warm, and proactive.

RULES:
- Your name is Jan. Your creator is a person named Amman (NOT the city). Call him "Sir".
- If user speaks Urdu/Roman Urdu → reply in same style. English → English.
- ALWAYS reply with ONLY valid JSON, nothing else.
- Module input values must be in English.
- Be concise. DO the thing, don't talk about doing it.

YOUR MODULES (use EXACT names):
- weather: get weather. Input: {{"city": "{default_city}"}}
- web_search: search internet. Input: {{"action": "search", "query": "..."}}
- youtube: play/search YouTube. Input: {{"action": "search_and_play", "query": "song name artist"}}
- spotify: control Spotify. Input: {{"action": "open"}} or {{"action": "search", "query": "song name"}}
- browser: open any URL. Input: {{"action": "open", "url": "https://..."}}
- app_launcher: open/close any app on PC. Input: {{"action": "open", "name": "spotify"}} — apps: spotify, opera gx, chrome, vscode, cursor, notepad, calculator, terminal, file explorer, task manager, settings
- file_manager: list/read/search files. Input: {{"action": "search", "path": "C:\\Users", "pattern": "*.pdf"}}
- keyboard_mouse: type text, press keys, click, screenshot. Input: {{"action": "type", "text": "..."}}
- system_control: volume, clipboard, lock, shutdown, open URLs. Input: {{"action": "set_volume", "level": 50}} or {{"action": "open_url", "url": "https://..."}}
- notes: save/list notes. Input: {{"action": "add", "text": "..."}}
- memory: remember/recall things. Input: {{"action": "recall", "query": "..."}}
- smart_tts: speak out loud. Input: {{"action": "speak", "text": "..."}}
- research_agent: deep research online. Input: {{"action": "check_memory_first", "question": "..."}}
- module_generator: create new abilities. Input: {{"action": "generate", "task": "..."}}
- math: calculate. Input: {{"a": 5, "b": 3, "op": "add"}}
- time: get date/time. Input: {{"mode": "both"}}

RESPONSE FORMAT (always valid JSON, nothing else):

When using a module:
{{"thought": "brief reason", "action": {{"module": "NAME", "input": {{...}}}}, "response": "what to say"}}

Just chatting (no module needed):
{{"thought": "casual", "action": null, "response": "your reply"}}

CRITICAL RULES:
- To OPEN AN APP (spotify, browser, etc): use app_launcher with action "open"
- To OPEN A WEBSITE: use browser with action "open" and a "url"
- For weather: ALWAYS use weather module with "city". Default city: {default_city}
- For YouTube: ALWAYS include "query" in input
- For Spotify search: use spotify module with action "search" and "query"
- For "search X" / "look up X" / "find info about X": ALWAYS use web_search, NOT research_agent
- research_agent is for deep multi-step research only. Simple searches → web_search.
- DO NOT invent module names. Only use names from the list above.
- DO NOT invent action names. Only use actions listed for each module.
- User's name is Amman (a person, NOT the city in Jordan). He built you.
- You are running on his PC. You have full control. Act like you own the PC.

Date: {datetime}

EXAMPLES:

User: "what is the weather"
{{"thought": "check weather", "action": {{"module": "weather", "input": {{"city": "{default_city}"}}}}, "response": "Let me check the weather."}}

User: "play adakaari by hassan raheem on youtube"
{{"thought": "play on youtube", "action": {{"module": "youtube", "input": {{"action": "search_and_play", "query": "Adakaari Hassan Raheem"}}}}, "response": "Playing Adakaari by Hassan Raheem on YouTube."}}

User: "open spotify"
{{"thought": "open the app", "action": {{"module": "app_launcher", "input": {{"action": "open", "name": "spotify"}}}}, "response": "Opening Spotify."}}

User: "play adakaari on spotify"
{{"thought": "search on spotify", "action": {{"module": "spotify", "input": {{"action": "search", "query": "Adakaari Hassan Raheem"}}}}, "response": "Searching for Adakaari on Spotify."}}

User: "open youtube"
{{"thought": "open youtube in browser", "action": {{"module": "browser", "input": {{"action": "open", "url": "https://youtube.com"}}}}, "response": "Opening YouTube."}}

User: "search petrol price in pakistan"
{{"thought": "search web", "action": {{"module": "web_search", "input": {{"action": "search", "query": "petrol price Pakistan today"}}}}, "response": "Searching for petrol prices."}}

User: "open my email"
{{"thought": "open gmail", "action": {{"module": "browser", "input": {{"action": "open", "url": "https://mail.google.com"}}}}, "response": "Opening your email."}}

User: "what is my name"
{{"thought": "I know my creator", "action": null, "response": "Your name is Amman, Sir."}}

User: "hello Jan"
{{"thought": "casual greeting", "action": null, "response": "Hello Sir! Kya haal hain? How can I help?"}}"""

    def __init__(self, modules_registry=None, schemas=None):
        super().__init__("orchestrator")
        self.modules_registry = modules_registry or {}
        self.schemas = schemas or {}
        self.conversation_history = []
        self.max_history = 20  # keep last 20 exchanges
        self.memory = None  # will be set after memory module is created
        self.smart_tts = None  # will be set after smart_tts module is created
        self.dual_llm = None  # will be set for smart model routing
        self.auto_voice = True  # auto-speak every response
        self.default_city = "Islamabad"  # user's default location

    def _build_system_prompt(self):
        return self.SYSTEM_PROMPT.format(
            default_city=self.default_city,
            datetime=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )

    def _call_ollama(self, user_message):
        """Send message to Ollama, routing through dual_llm if available."""
        system_prompt = self._build_system_prompt()

        messages = [{"role": "system", "content": system_prompt}]
        for entry in self.conversation_history[-self.max_history:]:
            messages.append(entry)
        messages.append({"role": "user", "content": user_message})

        # Route through dual_llm for smart model selection
        if self.dual_llm:
            try:
                route = self.dual_llm.process({"action": "route", "message": user_message})
                model = route.get("model", self.DEFAULT_MODEL)
            except Exception:
                model = self.DEFAULT_MODEL
        else:
            model = self.DEFAULT_MODEL

        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": 0.7,
                "num_predict": 1024,
            }
        }

        try:
            resp = requests.post(self.OLLAMA_URL, json=payload, timeout=120)
            resp.raise_for_status()
            data = resp.json()
            return data["message"]["content"]
        except requests.exceptions.ConnectionError:
            return json.dumps({
                "thought": "Ollama is not running",
                "action": None,
                "response": "Sir, I can't reach my brain (Ollama). Please make sure it's running with `ollama serve`."
            })
        except Exception as e:
            return json.dumps({
                "thought": f"LLM error: {str(e)}",
                "action": None,
                "response": f"I encountered an error thinking about that: {str(e)}"
            })

    def _parse_llm_response(self, raw_response):
        """Parse the LLM's JSON response, handling common formatting issues."""
        text = raw_response.strip()

        # strip markdown code fences if present
        if "```" in text:
            # extract content between fences
            match = re.search(r'```(?:json)?\s*\n?(.*?)\n?\s*```', text, re.DOTALL)
            if match:
                text = match.group(1).strip()
            else:
                text = re.sub(r'```(?:json)?', '', text).strip()

        # Try direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try to find the outermost JSON object
        brace_depth = 0
        start = -1
        for i, ch in enumerate(text):
            if ch == '{':
                if brace_depth == 0:
                    start = i
                brace_depth += 1
            elif ch == '}':
                brace_depth -= 1
                if brace_depth == 0 and start != -1:
                    try:
                        return json.loads(text[start:i+1])
                    except json.JSONDecodeError:
                        break

        # Try to fix common issues: trailing commas, single quotes
        cleaned = text
        if start != -1:
            cleaned = text[start:text.rfind('}')+1]
        cleaned = re.sub(r',\s*}', '}', cleaned)
        cleaned = re.sub(r',\s*]', ']', cleaned)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # Last resort: treat entire response as conversational
        return {
            "thought": "casual",
            "action": None,
            "response": raw_response.strip()
        }

    def _execute_action(self, action):
        """Execute a module action and return the result."""
        if action is None:
            return None

        # LLM sometimes returns just a module name string
        if isinstance(action, str):
            action = {"module": action, "input": {}}

        # handle list of actions (chained)
        if isinstance(action, list):
            results = []
            for single_action in action:
                if isinstance(single_action, str):
                    single_action = {"module": single_action, "input": {}}
                if isinstance(single_action, dict):
                    result = self._execute_single_action(single_action)
                    results.append(result)
            return results

        if isinstance(action, dict):
            return self._execute_single_action(action)

        return None

    def _resolve_module_name(self, name):
        """Resolve a module name, handling common LLM mistakes."""
        if not name:
            return None
        name = name.strip().lower()
        # direct match
        if name in self.modules_registry:
            return name
        # alias match
        if name in self.MODULE_ALIASES:
            return self.MODULE_ALIASES[name]
        # partial match (e.g. "web" → "web_search")
        for real_name in self.modules_registry:
            if name in real_name or real_name in name:
                return real_name
        return name  # return as-is, let the error happen naturally

    def _patch_module_input(self, module_name, module_input):
        """Fix common LLM input mistakes before sending to module."""
        inp = dict(module_input)  # copy

        if module_name == "weather":
            if "city" not in inp and "lat" not in inp:
                inp["city"] = self.default_city

        if module_name == "web_search":
            if "action" not in inp:
                inp["action"] = "search"

        if module_name == "youtube":
            if "action" not in inp:
                inp["action"] = "search_and_play"

        if module_name == "spotify":
            # if they have a query, it's a search
            if inp.get("query") and "action" not in inp:
                inp["action"] = "search"
            elif "action" not in inp:
                inp["action"] = "open"

        if module_name == "browser":
            if "action" not in inp:
                inp["action"] = "open"

        if module_name == "app_launcher":
            if "action" not in inp:
                inp["action"] = "open"

        if module_name == "file_manager":
            if "action" not in inp:
                inp["action"] = "list"

        return inp

    def _execute_single_action(self, action):
        """Execute a single module call."""
        module_name = action.get("module")
        module_input = action.get("input", {})

        # LLM sometimes puts input fields directly in action (no "input" wrapper)
        if not module_input and module_name:
            flat_input = {k: v for k, v in action.items() if k != "module"}
            if flat_input:
                module_input = flat_input

        # resolve aliases and typos
        module_name = self._resolve_module_name(module_name)

        if not module_name:
            return {"error": "No module specified in action"}

        if module_name not in self.modules_registry:
            return {"error": f"Module '{module_name}' not found. Available: {list(self.modules_registry.keys())}"}

        # patch common input mistakes
        module_input = self._patch_module_input(module_name, module_input)

        try:
            module = self.modules_registry[module_name]
            result = module.process(module_input)
            return {"module": module_name, "result": result}
        except Exception as e:
            return {"module": module_name, "error": str(e)}

    def _keyword_route(self, message):
        """Fallback: infer module action from user message keywords when LLM fails to produce JSON."""
        msg = message.lower().strip()

        # Weather
        if any(w in msg for w in ["weather", "temperature", "forecast", "mausam"]):
            city = self.default_city
            # Try to extract city name after "in"
            m = re.search(r'\bin\s+([a-zA-Z\s]+?)(?:\s*(?:today|tomorrow|now|please|\?|$))', msg)
            if m:
                city = m.group(1).strip().title()
            return {"module": "weather", "input": {"city": city}}

        # Open app (must check before browser)
        app_names = {
            "spotify": "spotify", "chrome": "chrome", "opera": "opera gx",
            "vscode": "vscode", "code": "vscode", "cursor": "cursor",
            "notepad": "notepad", "calculator": "calculator",
            "terminal": "terminal", "explorer": "file explorer",
            "task manager": "task manager", "settings": "settings",
            "discord": "discord", "steam": "steam", "whatsapp": "whatsapp",
        }
        if re.search(r'\bopen\b', msg):
            for kw, app in app_names.items():
                if kw in msg:
                    return {"module": "app_launcher", "input": {"action": "open", "name": app}}

        # YouTube play
        if "youtube" in msg and any(w in msg for w in ["play", "search", "find"]):
            query = re.sub(r'\b(play|search|find|on|youtube|please)\b', '', msg).strip()
            return {"module": "youtube", "input": {"action": "search_and_play", "query": query or msg}}

        # Open website
        if re.search(r'\bopen\b', msg) and any(w in msg for w in ["youtube", "gmail", "email", "google", "reddit", "twitter"]):
            urls = {
                "youtube": "https://youtube.com", "gmail": "https://mail.google.com",
                "email": "https://mail.google.com", "google": "https://google.com",
                "reddit": "https://reddit.com", "twitter": "https://twitter.com",
            }
            for kw, url in urls.items():
                if kw in msg:
                    return {"module": "browser", "input": {"action": "open", "url": url}}

        # Web search
        if any(w in msg for w in ["search", "look up", "find out", "google"]):
            query = re.sub(r'\b(search|look up|find out|google|for|me|please|on the web|online)\b', '', msg).strip()
            return {"module": "web_search", "input": {"action": "search", "query": query or msg}}

        # Spotify
        if "spotify" in msg:
            if any(w in msg for w in ["play", "search"]):
                query = re.sub(r'\b(play|search|on|spotify|please)\b', '', msg).strip()
                return {"module": "spotify", "input": {"action": "search", "query": query or msg}}
            return {"module": "app_launcher", "input": {"action": "open", "name": "spotify"}}

        # Time
        if any(w in msg for w in ["what time", "date today", "current time", "kya waqt"]):
            return {"module": "time", "input": {"mode": "both"}}

        return None  # No keyword match — treat as pure chat

    def process(self, input_data):
        """
        Main entry point.
        input_data: {"message": "user's natural language message"}
        Returns: {"response": "...", "thought": "...", "action_result": ...}
        """
        user_message = input_data.get("message", "")
        if not user_message:
            return {"error": "No message provided. Send {'message': 'your text here'}"}

        # 1. Ask the LLM to think
        raw_llm = self._call_ollama(user_message)

        # 2. Parse the response
        parsed = self._parse_llm_response(raw_llm)

        # Safety: ensure parsed is always a dict
        if not isinstance(parsed, dict):
            parsed = {"thought": "casual", "action": None, "response": str(parsed)}

        thought = parsed.get("thought", "")
        action = parsed.get("action")
        response = parsed.get("response", "")

        # ── Fallback router: if LLM didn't return JSON with action, try keyword routing ──
        if action is None:
            fallback = self._keyword_route(user_message)
            if fallback:
                action = fallback
                if not thought:
                    thought = "auto-routed"

        # Fix malformed actions: if action is a string, try to reconstruct
        if isinstance(action, str) and action:
            resolved = self._resolve_module_name(action)
            if resolved and resolved in self.modules_registry:
                # pull any extra keys from parsed as input
                extra = {k: v for k, v in parsed.items()
                         if k not in ("thought", "action", "response")}
                action = {"module": resolved, "input": extra}
            else:
                action = None

        # 3. Execute any module actions
        action_result = self._execute_action(action)

        # 4. Build final response — include module result data when useful
        final_response = response
        if action_result and not isinstance(action_result, list):
            result_data = action_result.get("result", action_result)
            if isinstance(result_data, dict):
                if result_data.get("error"):
                    final_response = f"{response}\n\n⚠️ Module error: {result_data['error']}"
                elif result_data.get("status") == "ok":
                    # Append useful result info to response
                    useful = result_data.get("summary") or result_data.get("message") or result_data.get("output") or result_data.get("answer")
                    if useful and str(useful) not in response:
                        final_response = f"{response}\n\n{useful}"
        elif action_result and isinstance(action_result, list):
            extras = []
            for ar in action_result:
                if ar.get("error"):
                    extras.append(f"⚠️ {ar.get('module','?')}: {ar['error']}")
                elif isinstance(ar.get("result"), dict):
                    rd = ar["result"]
                    u = rd.get("summary") or rd.get("message") or rd.get("output")
                    if u:
                        extras.append(str(u))
            if extras:
                final_response = response + "\n\n" + "\n".join(extras)

        # 5. Update conversation history
        self.conversation_history.append({"role": "user", "content": user_message})
        assistant_content = json.dumps({"response": final_response, "action_result": action_result})
        self.conversation_history.append({"role": "assistant", "content": assistant_content})

        # trim history
        if len(self.conversation_history) > self.max_history * 2:
            self.conversation_history = self.conversation_history[-(self.max_history * 2):]

        # 6. Auto-save to long-term memory
        if self.memory:
            try:
                self.memory.save_conversation("user", user_message)
                self.memory.save_conversation("assistant", final_response)
            except Exception:
                pass  # don't let memory errors break the chat

        # 7. Auto-speak response via smart_tts
        voice_status = None
        if self.auto_voice and self.smart_tts and final_response:
            try:
                # strip markdown/emoji artifacts that sound weird when spoken
                speak_text = final_response.split("\n\n⚠️")[0].strip()
                if speak_text:
                    voice_result = self.smart_tts.process({"action": "speak", "text": speak_text})
                    voice_status = voice_result.get("status", "error")
            except Exception:
                voice_status = "error"

        return {
            "status": "ok",
            "thought": thought,
            "response": final_response,
            "action": action,
            "action_result": action_result,
            "voice": voice_status,
            "raw_llm": raw_llm
        }
