# Simple registry of available module instances.
from .echo_module import EchoModule
from .math_module import MathModule
from .time_module import TimeModule
from .weather_module import WeatherModule
from .notes_module import NotesModule
from .stt_module import STTModule
from .tts_module import TTSModule
from .speaker_module import SpeakerModule
from .orchestrator_module import OrchestratorModule
from .app_launcher_module import AppLauncherModule
from .keyboard_mouse_module import KeyboardMouseModule
from .file_manager_module import FileManagerModule
from .system_control_module import SystemControlModule
from .browser_module import BrowserModule
from .web_search_module import WebSearchModule
from .youtube_module import YouTubeModule
from .spotify_module import SpotifyModule
from .memory_module import MemoryModule
from .smart_tts_module import SmartTTSModule
from .research_agent_module import ResearchAgentModule
from .module_generator_module import ModuleGeneratorModule
from .vision_module import VisionModule
from .proactive_learning_module import ProactiveLearningModule
from .dual_llm_module import DualLLMModule
from .person_recognition_module import PersonRecognitionModule
from .ar_module import ARModule
from .daemon_module import DaemonModule
from .wake_word_module import WakeWordModule
from .learning_engine import LearningEngine

# v2: Agent-based architecture
from .screen_reader import ScreenReader
from .orchestrator_v2_module import OrchestratorV2Module
from .agents import (
    AGENT_CLASSES,
    ChatAgent, BrowserAgent, MediaAgent, CommunicationAgent,
    ResearchAgentV2, MemoryAgent, ProductivityAgent, FileAgent,
    SystemAgent, CodingAgent, CreativeAgent, AutomationAgent,
    VisionAgent, SelfImprovementAgent,
)


# ========================
# Module Schemas (for LLM/orchestrator)
# ========================
MODULE_SCHEMAS = {
    "echo": {
        "description": "Echoes back whatever you send. For testing.",
        "input": {"text": "string"},
        "output": {
            "status": "ok",
            "module": "echo",
            "received": "dict",
            "message": "string"
        }
    },
    "math": {
        "description": "Perform basic math operations.",
        "input": {
            "a": "number",
            "b": "number",
            "op": "string (add/sub/mul/div)"
        },
        "output": {
            "status": "ok",
            "operation": "string",
            "a": "number",
            "b": "number",
            "result": "number"
        }
    },
    "time": {
        "description": "Get current date and/or time.",
        "input": {"mode": "string (time/date/both)"},
        "output": {
            "status": "ok",
            "mode": "string",
            "output": {"time": "HH:MM:SS", "date": "YYYY-MM-DD"}
        }
    },
    "weather": {
        "description": "Get current weather and forecast for a city.",
        "input": {
            "city": "string (optional)",
            "lat": "float (optional)",
            "lon": "float (optional)"
        },
        "output": {
            "status": "ok",
            "city": "string",
            "summary": "string",
            "forecast": "string"
        }
    },
    "notes": {
        "description": "Save, list, or delete personal notes.",
        "input": {
            "action": "string (add/list/delete)",
            "text": "string (for add)",
            "speaker": "string (optional, who said it)",
            "index": "int (for delete)"
        },
        "output": {
            "status": "ok",
            "message": "string or notes list"
        }
    },
    "tts": {
        "description": "Speak text out loud using text-to-speech.",
        "input": {"text": "string to speak"},
        "output": {"status": "ok", "spoken": "string"}
    },
    "app_launcher": {
        "description": "Open, close, minimize, maximize, focus any application. Can also list open windows and register new apps.",
        "input": {
            "action": "string (open/close/minimize/maximize/focus/list_windows/list_apps/register)",
            "name": "string (app name like 'spotify', 'chrome', 'vscode', 'notepad', 'calculator', 'file explorer', 'terminal')",
            "args": "string or list (optional, extra args for open)",
            "path": "string (exe path, only for register action)"
        },
        "output": {"status": "ok", "message": "string"}
    },
    "keyboard_mouse": {
        "description": "Control keyboard and mouse. Type text, press keys, hotkeys, click, move mouse, scroll, take screenshots.",
        "input": {
            "action": "string (type/hotkey/press/click/move/scroll/screenshot/mouse_position/screen_size)",
            "text": "string (for type)",
            "keys": "list of strings (for hotkey, e.g. ['ctrl','c'])",
            "key": "string (for press, e.g. 'enter', 'tab', 'space', 'escape')",
            "x": "int (for click/move)",
            "y": "int (for click/move)",
            "button": "string (left/right, for click)",
            "amount": "int (for scroll, positive=up negative=down)",
            "path": "string (for screenshot save path)"
        },
        "output": {"status": "ok", "message": "string"}
    },
    "file_manager": {
        "description": "Manage files and folders. List directory contents, read files, create/move/copy/delete files, search for files.",
        "input": {
            "action": "string (list/read/create_file/create_dir/move/copy/delete/search/info)",
            "path": "string (file or directory path)",
            "destination": "string (for move/copy)",
            "content": "string (for create_file)",
            "pattern": "string (for search, e.g. '*.py', '*.txt')",
            "confirm": "bool (required true for delete)"
        },
        "output": {"status": "ok", "message": "string or file data"}
    },
    "system_control": {
        "description": "Control system settings. Volume, mute, screenshot, clipboard, lock screen, shutdown, restart, sleep, open URLs.",
        "input": {
            "action": "string (get_volume/set_volume/volume_up/volume_down/mute/unmute/screenshot/clipboard_read/clipboard_write/lock/shutdown/restart/sleep/open_url)",
            "level": "int 0-100 (for set_volume)",
            "step": "int (for volume_up/down, default 10)",
            "text": "string (for clipboard_write)",
            "url": "string (for open_url)",
            "confirm": "bool (required true for shutdown/restart)"
        },
        "output": {"status": "ok", "message": "string"}
    },
    "browser": {
        "description": "Control a real browser. Open URLs, read page text, click elements or links by visible text, type into fields, scroll, manage tabs, take screenshots, get links. Use click_link to click a link by its visible text (e.g. 'Pricing', 'Shop iPhone').",
        "input": {
            "action": "string (open/read/click/click_link/type/screenshot/scroll/new_tab/close_tab/list_tabs/switch_tab/get_links/close_browser)",
            "url": "string (for open/new_tab)",
            "selector": "string CSS selector (for click/type)",
            "link_text": "string visible text of a link to click (for click_link, e.g. 'Pricing', 'iPhone 17')",
            "text": "string (for type)",
            "press_enter": "bool (for type, submit after typing)",
            "direction": "string up/down (for scroll)",
            "amount": "int pixels (for scroll)",
            "index": "int (for switch_tab)"
        },
        "output": {"status": "ok", "url": "string", "title": "string"}
    },
    "web_search": {
        "description": "Search the internet using DuckDuckGo. Returns results with titles, URLs, snippets, and an LLM-generated summary.",
        "input": {
            "action": "string (search/read_page)",
            "query": "string (what to search for)",
            "url": "string (for read_page)",
            "max_results": "int (default 5)",
            "summarize": "bool (default true, use LLM to summarize results)"
        },
        "output": {"status": "ok", "query": "string", "results": "list", "summary": "string"}
    },
    "youtube": {
        "description": "Search YouTube for videos and play the best one. LLM picks the best video based on relevance, views, and quality.",
        "input": {
            "action": "string (search/search_and_play/play)",
            "query": "string (what to search for, e.g. 'best butter chicken recipe')",
            "url": "string (for play, a YouTube URL)",
            "max_results": "int (default 5)"
        },
        "output": {"status": "ok", "picked": "video object", "reason": "why this video"}
    },
    "spotify": {
        "description": "Control Spotify. Open it, search & play songs/artists/playlists, play/pause, skip, volume.",
        "input": {
            "action": "string (open/play_pause/play/pause/next/previous/volume_up/volume_down/search/play_uri/focus)",
            "query": "string (for search — song name, artist, playlist, etc.)",
            "uri": "string (for play_uri — e.g. spotify:playlist:xxxxx)"
        },
        "output": {"status": "ok", "message": "string"}
    },
    "memory": {
        "description": "Long-term memory. Save and recall conversations, save knowledge/learnings, manage user preferences. Jarvis remembers everything.",
        "input": {
            "action": "string (save_conversation/recall/save_knowledge/search_knowledge/set_preference/get_preference/get_all_preferences/stats)",
            "content": "string (for save_conversation/save_knowledge)",
            "role": "string user/assistant (for save_conversation)",
            "topic": "string (for save_knowledge)",
            "source": "string (for save_knowledge, where you learned it)",
            "query": "string (for recall/search_knowledge — semantic search)",
            "key": "string (for preferences, e.g. 'favorite_music', 'favorite_food')",
            "value": "any (for set_preference)",
            "limit": "int (for recall/search, default 10)"
        },
        "output": {"status": "ok", "memories or results": "list"}
    },
    "smart_tts": {
        "description": "Smooth, natural text-to-speech. Auto-detects Urdu vs English and uses the right voice. Sounds like ChatGPT voice assistant.",
        "input": {
            "action": "string (speak/list_voices/set_gender)",
            "text": "string (what to say out loud)",
            "voice": "string (optional override, e.g. 'en-US-GuyNeural' or 'ur-PK-AsadNeural')",
            "gender": "string male/female (for set_gender)"
        },
        "output": {"status": "ok", "spoken": "string", "language": "en or ur"}
    },
    "research_agent": {
        "description": "Research anything on the internet. Searches DuckDuckGo, asks ChatGPT or Gemini like a human, reads pages, and saves knowledge to memory. Use when you don't know something or need fresh/accurate information.",
        "input": {
            "action": "string (research/search_web/ask_chatgpt/ask_gemini/read_url/check_memory_first)",
            "question": "string (what to research or ask)",
            "strategy": "string (auto/duckduckgo/chatgpt/gemini — default: auto tries all)",
            "url": "string (for read_url)",
            "save_to_memory": "bool (default true — save findings to long-term memory)"
        },
        "output": {"status": "ok", "answer": "string", "strategy_used": "string", "saved_to_memory": "bool"}
    },
    "module_generator": {
        "description": "Create new modules/capabilities for JAN. When you encounter a task you can't handle, generate a new module. Researches how to do it, writes Python code, validates, and hot-loads it.",
        "input": {
            "action": "string (generate/list/load_all/delete)",
            "task": "string (describe the capability to add, e.g. 'convert PDF to text', 'check stock prices')",
            "module_name": "string (for delete — name of module to remove)",
            "auto_install": "bool (default true — auto pip install needed packages)"
        },
        "output": {"status": "ok", "module_name": "string", "steps": "list of progress steps"}
    },
    "proactive_learning": {
        "description": "Detect user behavior patterns, track habits, suggest automations, manage scheduled tasks, and learn user preferences from conversation history.",
        "input": {
            "action": "string (analyze_patterns/get_habits/suggest_automations/add_scheduled_task/list_scheduled/remove_scheduled/get_due_tasks/learn_preferences)",
            "hours": "int (lookback window in hours, default 168 = 7 days)",
            "min_frequency": "int (for suggest_automations, default 3)",
            "task_type": "string (for add_scheduled_task, e.g. 'weather', 'spotify')",
            "task_data": "dict (for add_scheduled_task, e.g. {\"city\": \"Lahore\"})",
            "schedule": "string (for add_scheduled_task, e.g. 'daily_09:00', 'every_30min')",
            "task_id": "int (for remove_scheduled)"
        },
        "output": {"status": "ok", "patterns or habits or suggestions or tasks": "list"}
    },
    "vision": {
        "description": "Camera, face detection/recognition, OCR, and image description. Capture photos, detect and recognize faces, enroll faces, read text from images, describe images via LLM, and stream webcam video.",
        "input": {
            "action": "string (capture/detect_faces/recognize/enroll_face/enroll_from_camera/list_known_faces/delete_face/read_text/describe/stream_start/stream_stop/stream_capture)",
            "image_path": "string (path to image for detect_faces/recognize/enroll_face/read_text/describe)",
            "name": "string (for enroll_face/enroll_from_camera/delete_face)",
            "camera_id": "int (default 0, for capture/enroll_from_camera/stream_start)",
            "save_path": "string (optional, for capture/stream_capture)",
            "language": "string (default 'en', for read_text OCR)"
        },
        "output": {"status": "ok", "message": "string or detection/recognition results"}
    },
    "dual_llm": {
        "description": "Smart dual-model router. Uses small LLM (1-2B) for simple tasks and big LLM (6-8B) for complex reasoning. Auto-routes based on task complexity. Monitors system resources.",
        "input": {
            "action": "string (route/chat/load_big/unload_big/set_models/stats/check_resources/set_timeout)",
            "message": "string (for route/chat — the message to process)",
            "system_prompt": "string (optional, for chat)",
            "force_model": "string (optional, 'small' or 'big' to override auto-routing)",
            "small_model": "string (for set_models, e.g. 'qwen2.5:1.5b')",
            "big_model": "string (for set_models, e.g. 'llama3.1:8b')",
            "minutes": "int (for set_timeout, idle minutes before unloading big model)"
        },
        "output": {"status": "ok", "response": "string", "model_used": "string"}
    },
    "person_recognition": {
        "description": "Multi-modal person identification using face + voice. Enroll people, identify by face or voice, manage per-user preferences, auto-greet known people.",
        "input": {
            "action": "string (identify/enroll_person/enroll_voice/update_preferences/get_person/list_persons/delete_person/greet/who_is_this)",
            "name": "string (person name for enroll/get/delete)",
            "image_path": "string (for identify/enroll_person — path to face image)",
            "audio_path": "string (for identify/enroll_voice — path to voice audio)",
            "preferences": "dict (for update_preferences, e.g. {'language': 'urdu', 'music': 'lofi'})",
            "source": "string (for who_is_this — 'camera'/'audio'/'both')",
            "camera_id": "int (default 0, for who_is_this with camera)"
        },
        "output": {"status": "ok", "name": "string", "confidence": "float", "method": "face|voice|both"}
    },
    "ar": {
        "description": "Augmented Reality via phone or VR headset. Start AR server, translate text in camera view, navigate with path overlays, label objects and faces. Clients connect via WebSocket.",
        "input": {
            "action": "string (start_server/stop_server/server_status/translate_image/navigate_to/get_direction/send_overlay/process_frame)",
            "host": "string (default '0.0.0.0', for start_server)",
            "port": "int (default 8765, for start_server)",
            "image_path": "string (for translate_image)",
            "target_language": "string (default 'en', for translate_image)",
            "lat": "float (latitude, for navigate_to/get_direction)",
            "lon": "float (longitude, for navigate_to/get_direction)",
            "name": "string (destination name, for navigate_to)",
            "current_lat": "float (for get_direction)",
            "current_lon": "float (for get_direction)",
            "elements": "list (overlay elements, for send_overlay)",
            "frame_data": "string (base64 jpeg, for process_frame)",
            "mode": "string (translate/detect/navigate/label_faces, for process_frame)"
        },
        "output": {"status": "ok", "message": "string or overlay data"}
    },
    "daemon": {
        "description": "JAN's always-on background brain. Runs scheduled tasks, monitors system health, detects user patterns, auto-greets via camera. Start it and JAN becomes fully autonomous.",
        "input": {
            "action": "string (start/stop/status/set_interval/enable_camera_watch/mark_activity/get_log/force_check)",
            "task_name": "string (for set_interval/force_check — e.g. 'scheduled_tasks', 'system_monitor', 'pattern_analysis')",
            "seconds": "int (for set_interval)",
            "enabled": "bool (for enable_camera_watch)",
            "camera_id": "int (default 0, for enable_camera_watch)",
            "lines": "int (default 50, for get_log)",
            "check_name": "string (for force_check)"
        },
        "output": {"status": "ok", "running": "bool", "uptime": "float"}
    },
    "wake_word": {
        "description": "Always-listening voice activation. Detects 'Hey JAN' wake word, records speech, transcribes via Whisper, sends to orchestrator. JAN listens and responds hands-free.",
        "input": {
            "action": "string (start/stop/status/set_wake_word/set_sensitivity/set_silence_duration/test_mic)",
            "wake_word": "string (openwakeword model name, for set_wake_word)",
            "threshold": "int (energy threshold, for set_sensitivity)",
            "seconds": "float (silence duration before stop recording, for set_silence_duration)"
        },
        "output": {"status": "ok", "running": "bool", "listening": "bool"}
    },
}

# Module instances
MODULES = {
    "echo": EchoModule(),
    "math": MathModule(),
    "time": TimeModule(),
    "weather": WeatherModule(),
    "notes": NotesModule(),
    "stt": STTModule(),
    "tts": TTSModule(),
    "speaker": SpeakerModule(),
    "app_launcher": AppLauncherModule(),
    "keyboard_mouse": KeyboardMouseModule(),
    "file_manager": FileManagerModule(),
    "system_control": SystemControlModule(),
    "browser": BrowserModule(),
    "web_search": WebSearchModule(),
    "youtube": YouTubeModule(),
    "spotify": SpotifyModule(),
    "memory": MemoryModule(),
    "smart_tts": SmartTTSModule(),
    "research_agent": ResearchAgentModule(),
    "module_generator": ModuleGeneratorModule(),
    "proactive_learning": ProactiveLearningModule(),
    "vision": VisionModule(),
    "dual_llm": DualLLMModule(),
    "person_recognition": PersonRecognitionModule(),
    "ar": ARModule(),
    "daemon": DaemonModule(),
    "wake_word": WakeWordModule(),
}

# Orchestrator gets access to all other modules + schemas
ORCHESTRATOR = OrchestratorModule(modules_registry=MODULES, schemas=MODULE_SCHEMAS)
# Wire memory into orchestrator for auto-saving conversations
ORCHESTRATOR.memory = MODULES["memory"]
# Wire smart_tts into orchestrator for auto-speaking responses
ORCHESTRATOR.smart_tts = MODULES["smart_tts"]
# Wire dual_llm into orchestrator for smart model routing
ORCHESTRATOR.dual_llm = MODULES["dual_llm"]

# Wire cross-module dependencies
MODULES["research_agent"].memory = MODULES["memory"]
MODULES["module_generator"].memory = MODULES["memory"]
MODULES["module_generator"].research_agent = MODULES["research_agent"]
MODULES["module_generator"].orchestrator = ORCHESTRATOR
MODULES["proactive_learning"].memory = MODULES["memory"]
MODULES["vision"].memory = MODULES["memory"]
MODULES["person_recognition"].memory = MODULES["memory"]
MODULES["person_recognition"].vision = MODULES["vision"]
MODULES["ar"].vision = MODULES["vision"]
MODULES["ar"].memory = MODULES["memory"]

# Wire daemon dependencies
MODULES["daemon"].orchestrator = ORCHESTRATOR
MODULES["daemon"].proactive = MODULES["proactive_learning"]
MODULES["daemon"].dual_llm = MODULES["dual_llm"]
MODULES["daemon"].vision = MODULES["vision"]
MODULES["daemon"].person_recognition = MODULES["person_recognition"]
MODULES["daemon"].memory = MODULES["memory"]

# Wire wake word dependencies
MODULES["wake_word"].orchestrator = ORCHESTRATOR
MODULES["wake_word"].stt = MODULES["stt"]
MODULES["wake_word"].smart_tts = MODULES["smart_tts"]
MODULES["wake_word"].daemon = MODULES["daemon"]

# Load any previously generated modules
try:
    load_result = MODULES["module_generator"].load_all_generated()
    if load_result.get("loaded"):
        print(f"[JAN] Loaded {len(load_result['loaded'])} generated modules: {load_result['loaded']}")
except Exception as e:
    print(f"[JAN] Warning: Could not load generated modules: {e}")


# ========================
# v2: Agent-based orchestrator
# ========================
SCREEN_READER = ScreenReader()
MODULES["screen_reader"] = SCREEN_READER

# Learning engine — self-learning, RAG, skill memory
LEARNING_ENGINE = LearningEngine()
LEARNING_ENGINE.memory = MODULES["memory"]
LEARNING_ENGINE.web_search = MODULES["web_search"]
MODULES["learning_engine"] = LEARNING_ENGINE

# Tool sets for each agent (which modules each agent can use)
_AGENT_TOOL_MAP = {
    "chat": ["memory", "notes", "time", "weather", "math"],
    "browser": ["browser", "keyboard_mouse", "screen_reader"],
    "media": ["spotify", "youtube", "browser", "keyboard_mouse", "screen_reader", "app_launcher"],
    "communication": ["browser", "keyboard_mouse", "screen_reader", "smart_tts"],
    "research": ["web_search", "browser", "memory", "screen_reader", "keyboard_mouse"],
    "memory": ["memory", "notes", "proactive_learning"],
    "productivity": ["notes", "time", "weather", "memory", "smart_tts", "file_manager"],
    "file": ["file_manager", "keyboard_mouse", "screen_reader"],
    "system": ["app_launcher", "system_control", "keyboard_mouse", "screen_reader"],
    "coding": ["file_manager", "browser", "keyboard_mouse", "screen_reader", "module_generator"],
    "creative": ["file_manager", "browser", "keyboard_mouse", "notes", "memory"],
    "automation": ["memory", "time", "notes"],
    "vision": ["screen_reader", "keyboard_mouse", "vision", "person_recognition"],
    "self_improvement": ["module_generator", "file_manager", "memory"],
}

# Model assignments per agent
_AGENT_MODELS = {
    "chat": "qwen2.5:7b-instruct",
    "browser": "qwen2.5:7b-instruct",
    "media": "qwen2.5:7b-instruct",
    "communication": "qwen2.5:7b-instruct",
    "research": "qwen2.5:7b-instruct",
    "memory": "qwen2.5:7b-instruct",
    "productivity": "qwen2.5:7b-instruct",
    "file": "qwen2.5:7b-instruct",
    "system": "qwen2.5:7b-instruct",
    "coding": "qwen2.5-coder:7b",
    "creative": "qwen2.5:7b-instruct",
    "automation": "qwen2.5:7b-instruct",
    "vision": "qwen2.5:7b-instruct",
    "self_improvement": "qwen2.5-coder:7b",
}

# Create the v2 orchestrator
ORCHESTRATOR_V2 = OrchestratorV2Module()
ORCHESTRATOR_V2.memory = MODULES["memory"]
ORCHESTRATOR_V2.smart_tts = MODULES["smart_tts"]
ORCHESTRATOR_V2.auto_voice = ORCHESTRATOR.auto_voice
ORCHESTRATOR_V2.default_city = ORCHESTRATOR.default_city

# Instantiate and register all 14 agents
for agent_name, AgentClass in AGENT_CLASSES.items():
    # Build tool dict for this agent
    tool_names = _AGENT_TOOL_MAP.get(agent_name, [])
    tools = {name: MODULES[name] for name in tool_names if name in MODULES}
    model = _AGENT_MODELS.get(agent_name, "qwen2.5:7b-instruct")

    agent_instance = AgentClass(tools=tools, model=model)
    agent_instance.screen_reader = SCREEN_READER
    agent_instance.memory = MODULES.get("memory")
    agent_instance.learning_engine = LEARNING_ENGINE
    ORCHESTRATOR_V2.register_agent(agent_name, agent_instance)

LEARNING_ENGINE.orchestrator = ORCHESTRATOR_V2
print(f"[JAN] v2 Agent orchestrator ready — {len(ORCHESTRATOR_V2.agents)} agents registered")
