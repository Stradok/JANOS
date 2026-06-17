"""
Autonomous Recovery Engine — JAN self-healing layer.

When any module fails, this engine intercepts the error, classifies it,
tries a prioritized stack of fixes, retries the original action, and
caches successful solutions for instant replay next time.

Recovery hierarchy:
  1. Solution cache — instant replay of previously solved errors
  2. pip install missing Python package
  3. apt install missing system package
  4. Set DISPLAY / fix headless environment
  5. Start Ollama if offline
  6. Map unknown action names to real module actions
  7. Retry after transient failures
  8. Research fix online via web_search
  9. Generate new module capability via module_generator
 10. Escalate to user with structured diagnosis
"""

import re
import sys
import json
import time
import sqlite3
import hashlib
import subprocess
from datetime import datetime
from pathlib import Path
from .base import ModuleBase


# Python import name → PyPI package name
IMPORT_TO_PACKAGE = {
    "cv2": "opencv-python",
    "PIL": "Pillow",
    "sklearn": "scikit-learn",
    "bs4": "beautifulsoup4",
    "yaml": "pyyaml",
    "dotenv": "python-dotenv",
    "whisper": "openai-whisper",
    "edge_tts": "edge-tts",
    "chromadb": "chromadb",
    "resemblyzer": "resemblyzer",
    "face_recognition": "face-recognition",
    "pyautogui": "pyautogui",
    "pyaudio": "pyaudio",
    "sounddevice": "sounddevice",
    "pulsectl": "pulsectl",
    "openwakeword": "openwakeword",
    "easyocr": "easyocr",
    "pytesseract": "pytesseract",
    "webrtcvad": "webrtcvad",
    "psutil": "psutil",
    "sentence_transformers": "sentence-transformers",
    "yt_dlp": "yt-dlp",
    "playwright": "playwright",
    "websockets": "websockets",
    "httpx": "httpx",
    "librosa": "librosa",
    "soundfile": "soundfile",
}

# System command → apt package
CMD_TO_APT = {
    "ffmpeg": "ffmpeg",
    "ffplay": "ffmpeg",
    "tesseract": "tesseract-ocr",
    "wmctrl": "wmctrl",
    "xdotool": "xdotool",
    "paplay": "pulseaudio-utils",
    "aplay": "alsa-utils",
    "mpg123": "mpg123",
    "xdg-open": "xdg-utils",
    "loginctl": "systemd",
    "spotify": "spotify-client",
}

# Unknown action alias → (real_module, real_action)
ACTION_ALIASES = {
    "install":          ("system_control", "pip_install"),
    "install_package":  ("system_control", "pip_install"),
    "pip":              ("system_control", "pip_install"),
    "run_file":         ("file_manager", "run"),
    "execute":          ("file_manager", "run"),
    "exec":             ("file_manager", "run"),
    "shell":            ("system_control", "run_shell"),
    "bash":             ("system_control", "run_shell"),
    "navigate":         ("browser", "open"),
    "visit":            ("browser", "open"),
    "goto":             ("browser", "open"),
    "speak_text":       ("smart_tts", "speak"),
    "say":              ("smart_tts", "speak"),
    "tts":              ("smart_tts", "speak"),
    "search_web":       ("web_search", "search"),
    "google":           ("web_search", "search"),
    "launch":           ("app_launcher", "open"),
    "start":            ("app_launcher", "open"),
}

# Ordered error classification patterns: (type, regex)
ERROR_PATTERNS = [
    ("import_error",     r"No module named ['\"]([^'\"]+)['\"]"),
    ("import_error",     r"cannot import name ['\"]([^'\"]+)['\"]"),
    ("import_error",     r"ImportError.*?['\"]([^'\"]+)['\"]"),
    ("not_installed",    r"(\w[\w\-]*)[\s:]+not\s+installed"),
    ("cmd_not_found",    r"(['\"]?)(\w[\w\-]*)(\1):\s+command not found"),
    ("cmd_not_found",    r"No such file or directory.*?['\"]([^'\"]+)['\"]"),
    ("display_error",    r"(DisplayConnectionError|Cannot connect to display|DISPLAY environment variable)"),
    ("permission_error", r"(Permission denied|PermissionError)"),
    ("ollama_offline",   r"(11434|ollama).*?(refused|unavailable|offline|not running)"),
    ("connection_error", r"(ConnectionRefusedError|ConnectionError|ECONNREFUSED)"),
    ("timeout",          r"(TimeoutError|timed out|Read timed out)"),
    ("unknown_action",   r"Unknown action:\s*['\"]?(\w+)['\"]?"),
    ("attribute_error",  r"'(\w+)' object has no attribute '(\w+)'"),
]

# Human-readable diagnosis templates
DIAGNOSIS_TEMPLATES = {
    "import_error":     "Missing Python package '{extracted}'. Fix: pip install {pkg}",
    "not_installed":    "'{extracted}' is not installed. Fix: pip install {pkg} or sudo apt install {apt}",
    "cmd_not_found":    "System command '{extracted}' not found. Fix: sudo apt install {apt}",
    "display_error":    "No display connection (Wayland/headless). pyautogui GUI automation requires X11 or a virtual display.",
    "ollama_offline":   "Ollama is not running. Fix: run `ollama serve` in a terminal.",
    "connection_error": "Network/service connection refused. The target service may be down.",
    "timeout":          "Operation timed out. The module took too long to respond.",
    "unknown_action":   "Module doesn't recognize action '{extracted}'. Check the module's action list.",
    "permission_error": "Permission denied. The operation may require elevated privileges.",
    "attribute_error":  "Module API mismatch — possibly an outdated or wrong package version.",
}


class AutonomousRecovery(ModuleBase):
    """Intercepts module failures and autonomously applies fixes."""

    MAX_STRATEGIES = 6   # max fixes to try before giving up
    PIP_TIMEOUT    = 120 # seconds
    APT_TIMEOUT    = 120
    OLLAMA_WAIT    = 4   # seconds to wait after starting Ollama

    def __init__(self):
        super().__init__("autonomous_recovery")
        self.db_path = Path("memory/jarvis_memory.db")
        self._init_db()
        # Wired from __init__.py
        self.web_search        = None
        self.module_generator  = None
        self.learning_engine   = None
        self.modules_registry  = None

    # ── DB Setup ──────────────────────────────────────────────────────

    def _init_db(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS solution_cache (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    error_hash     TEXT UNIQUE,
                    error_sample   TEXT,
                    error_type     TEXT,
                    fix_type       TEXT,
                    fix_params     TEXT,
                    attempt_count  INTEGER DEFAULT 1,
                    success_count  INTEGER DEFAULT 0,
                    last_used      TEXT,
                    created        TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS recovery_log (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp       TEXT,
                    error_type      TEXT,
                    error_msg       TEXT,
                    module_name     TEXT,
                    fix_applied     TEXT,
                    fix_params      TEXT,
                    outcome         TEXT,
                    retry_succeeded INTEGER DEFAULT 0
                )
            """)

    # ── Error Classification ──────────────────────────────────────────

    def classify_error(self, error_msg: str) -> tuple[str, str]:
        """Return (error_type, extracted_value) for the given error string."""
        for error_type, pattern in ERROR_PATTERNS:
            m = re.search(pattern, error_msg, re.IGNORECASE)
            if m:
                # Take the last non-empty group as the extracted value
                groups = [g for g in m.groups() if g]
                return error_type, groups[-1] if groups else ""
        return "unknown", ""

    # ── Solution Cache ────────────────────────────────────────────────

    def _error_hash(self, error_msg: str) -> str:
        normalized = re.sub(r'0x[0-9a-fA-F]+', 'ADDR', error_msg)
        normalized = re.sub(r'line \d+', 'LINE', normalized)
        return hashlib.md5(normalized[:300].encode()).hexdigest()[:16]

    def _lookup_cached(self, error_msg: str) -> dict | None:
        eh = self._error_hash(error_msg)
        with sqlite3.connect(str(self.db_path)) as conn:
            row = conn.execute(
                "SELECT fix_type, fix_params, success_count FROM solution_cache WHERE error_hash = ?",
                (eh,)
            ).fetchone()
        if row and row[2] > 0:
            return {"fix_type": row[0], "fix_params": json.loads(row[1] or "{}")}
        return None

    def _cache_result(self, error_msg: str, error_type: str, fix_type: str, fix_params: dict, success: bool):
        eh = self._error_hash(error_msg)
        now = datetime.now().isoformat()
        with sqlite3.connect(str(self.db_path)) as conn:
            existing = conn.execute(
                "SELECT id FROM solution_cache WHERE error_hash = ?", (eh,)
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE solution_cache SET attempt_count = attempt_count + 1, "
                    "success_count = success_count + ?, last_used = ? WHERE error_hash = ?",
                    (1 if success else 0, now, eh)
                )
            else:
                conn.execute(
                    "INSERT INTO solution_cache "
                    "(error_hash, error_sample, error_type, fix_type, fix_params, success_count, last_used, created) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (eh, error_msg[:200], error_type, fix_type, json.dumps(fix_params),
                     1 if success else 0, now, now)
                )

    def _log_recovery(self, error_type: str, error_msg: str, module_name: str,
                      fix_type: str, fix_params: dict, outcome: str, retry_ok: bool):
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                "INSERT INTO recovery_log "
                "(timestamp, error_type, error_msg, module_name, fix_applied, fix_params, outcome, retry_succeeded) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (datetime.now().isoformat(), error_type, error_msg[:300], module_name,
                 fix_type, json.dumps(fix_params), outcome, 1 if retry_ok else 0)
            )

    # ── Fix Implementations ───────────────────────────────────────────

    def _pip_install(self, package: str) -> tuple[bool, str]:
        pypi = IMPORT_TO_PACKAGE.get(package, package)
        try:
            r = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--quiet", pypi],
                capture_output=True, text=True, timeout=self.PIP_TIMEOUT
            )
            if r.returncode == 0:
                return True, f"pip install {pypi} succeeded"
            return False, f"pip install {pypi} failed: {r.stderr[:150]}"
        except subprocess.TimeoutExpired:
            return False, f"pip install {pypi} timed out"
        except Exception as e:
            return False, str(e)

    def _apt_install(self, package: str) -> tuple[bool, str]:
        apt = CMD_TO_APT.get(package, package)
        try:
            r = subprocess.run(
                ["sudo", "apt-get", "install", "-y", "-q", apt],
                capture_output=True, text=True, timeout=self.APT_TIMEOUT
            )
            if r.returncode == 0:
                return True, f"apt install {apt} succeeded"
            return False, f"apt install {apt} failed: {r.stderr[:150]}"
        except subprocess.TimeoutExpired:
            return False, f"apt install timed out"
        except Exception as e:
            return False, str(e)

    def _set_display(self) -> tuple[bool, str]:
        import os
        for display in [":0", ":1", ":0.0"]:
            try:
                r = subprocess.run(["xdpyinfo", "-display", display],
                                   capture_output=True, timeout=2)
                if r.returncode == 0:
                    os.environ["DISPLAY"] = display
                    return True, f"Set DISPLAY={display}"
            except Exception:
                continue
        os.environ.setdefault("DISPLAY", ":0")
        return True, "Set DISPLAY=:0 (best guess)"

    def _start_ollama(self) -> tuple[bool, str]:
        try:
            import requests as req
            try:
                req.get("http://localhost:11434/api/tags", timeout=2)
                return True, "Ollama was already running"
            except Exception:
                pass
            subprocess.Popen(["ollama", "serve"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(self.OLLAMA_WAIT)
            try:
                req.get("http://localhost:11434/api/tags", timeout=5)
                return True, "Started Ollama successfully"
            except Exception:
                return False, "Started Ollama process but it is not responding yet"
        except Exception as e:
            return False, f"Could not start Ollama: {e}"

    def _map_unknown_action(self, bad_action: str, module_name: str,
                             original_action: dict) -> tuple[bool, str]:
        """Rewrite the action dict in-place to a real module.action pair."""
        alias = ACTION_ALIASES.get(bad_action)
        if not alias:
            return False, f"No mapping found for action '{bad_action}'"
        real_module, real_action = alias
        original_action["module"] = real_module
        original_action.setdefault("input", {})["action"] = real_action
        return True, f"Mapped '{bad_action}' → {real_module}.{real_action}"

    def _research_fix(self, error_msg: str, module_name: str) -> tuple[bool, str]:
        if not self.web_search:
            return False, "web_search not available"
        query = f"python fix: {error_msg[:120]} {module_name}"
        try:
            result = self.web_search.process({"action": "search", "query": query})
            if result.get("status") == "ok":
                summary = result.get("summary") or result.get("answer", "")
                if summary:
                    return True, summary[:500]
        except Exception:
            pass
        return False, "No useful research results"

    def _generate_capability(self, error_msg: str, module_name: str) -> tuple[bool, str]:
        if not self.module_generator:
            return False, "module_generator not available"
        try:
            result = self.module_generator.process({
                "action": "generate",
                "task": f"Handle this error in {module_name}: {error_msg[:200]}",
                "auto_install": True,
            })
            if result.get("status") == "ok":
                return True, f"Generated module: {result.get('module_name', '?')}"
        except Exception:
            pass
        return False, "Module generation failed"

    # ── Strategy Selection ────────────────────────────────────────────

    def _strategies_for(self, error_type: str, extracted: str,
                         module_name: str, original_action: dict) -> list[tuple]:
        """Return list of (fix_type, params, description) in priority order."""
        s = []
        if error_type == "import_error":
            pkg = IMPORT_TO_PACKAGE.get(extracted, extracted)
            s.append(("pip_install", {"package": pkg}, f"pip install {pkg}"))

        elif error_type == "not_installed":
            pkg = IMPORT_TO_PACKAGE.get(extracted, extracted)
            apt = CMD_TO_APT.get(extracted)
            s.append(("pip_install", {"package": pkg}, f"pip install {pkg}"))
            if apt:
                s.append(("apt_install", {"package": apt}, f"apt install {apt}"))

        elif error_type == "cmd_not_found":
            apt = CMD_TO_APT.get(extracted, extracted)
            s.append(("apt_install", {"package": apt}, f"apt install {apt}"))
            pkg = IMPORT_TO_PACKAGE.get(extracted, extracted)
            s.append(("pip_install", {"package": pkg}, f"pip install {pkg}"))

        elif error_type == "display_error":
            s.append(("set_display", {}, "Set DISPLAY env variable"))

        elif error_type == "ollama_offline":
            s.append(("start_ollama", {}, "Start Ollama service"))
            s.append(("retry", {"delay": 3}, "Wait and retry"))

        elif error_type == "connection_error":
            s.append(("retry", {"delay": 2}, "Wait and retry"))
            s.append(("start_ollama", {}, "Start Ollama if relevant"))

        elif error_type == "timeout":
            s.append(("retry", {"delay": 1}, "Retry once"))

        elif error_type == "unknown_action":
            s.append(("map_action", {"bad_action": extracted}, f"Map unknown action '{extracted}'"))
            s.append(("generate_module", {}, "Generate module for missing capability"))

        return s[:self.MAX_STRATEGIES]

    def _apply_fix(self, fix_type: str, params: dict, error_type: str,
                   extracted: str, module_name: str, original_action: dict) -> tuple[bool, str]:
        if fix_type == "pip_install":
            return self._pip_install(params.get("package", extracted))
        if fix_type == "apt_install":
            return self._apt_install(params.get("package", extracted))
        if fix_type == "set_display":
            return self._set_display()
        if fix_type == "start_ollama":
            return self._start_ollama()
        if fix_type == "map_action":
            return self._map_unknown_action(params.get("bad_action", extracted),
                                             module_name, original_action)
        if fix_type == "retry":
            time.sleep(params.get("delay", 1))
            return True, "Waited before retry"
        if fix_type == "generate_module":
            return self._generate_capability("", module_name)
        return False, f"Unknown fix type: {fix_type}"

    # ── Main Recovery Entry Point ─────────────────────────────────────

    def recover(self, error_msg: str, module_name: str,
                original_action: dict, execute_fn) -> dict:
        """
        Try to recover from a module failure and re-execute the action.

        Args:
            error_msg:       The error string from the failed call.
            module_name:     Which module failed.
            original_action: The action dict that was passed to the module.
            execute_fn:      Callable — execute_fn(action) → result dict.

        Returns:
            {
                "recovered":   bool,
                "fix_applied": str,       # human-readable description
                "result":      dict|None, # new result after successful fix
                "diagnosis":   str,       # structured explanation if unrecovered
            }
        """
        error_type, extracted = self.classify_error(error_msg)
        print(f"[Recovery] Error type={error_type} extracted='{extracted}' module={module_name}")

        # ── 1. Try solution cache first ───────────────────────────────
        cached = self._lookup_cached(error_msg)
        if cached:
            ok, msg = self._apply_fix(
                cached["fix_type"], cached["fix_params"],
                error_type, extracted, module_name, original_action
            )
            if ok:
                new_result = execute_fn(original_action)
                retry_ok = not _is_error(new_result)
                self._cache_result(error_msg, error_type, cached["fix_type"],
                                   cached["fix_params"], retry_ok)
                self._log_recovery(error_type, error_msg, module_name,
                                   f"cached:{cached['fix_type']}", cached["fix_params"],
                                   "ok" if retry_ok else "cache_miss", retry_ok)
                self._record_skill(error_type, module_name, cached["fix_type"], retry_ok)
                if retry_ok:
                    return {"recovered": True, "fix_applied": f"[cached] {msg}",
                            "result": new_result, "diagnosis": ""}

        # ── 2. Try each strategy in priority order ────────────────────
        strategies = self._strategies_for(error_type, extracted, module_name, original_action)

        for fix_type, params, description in strategies:
            print(f"[Recovery] Trying {fix_type}: {description}")
            ok, msg = self._apply_fix(fix_type, params, error_type, extracted,
                                       module_name, original_action)
            if not ok:
                print(f"[Recovery] {fix_type} failed: {msg}")
                continue

            new_result = execute_fn(original_action)
            retry_ok = not _is_error(new_result)
            self._cache_result(error_msg, error_type, fix_type, params, retry_ok)
            self._log_recovery(error_type, error_msg, module_name, fix_type,
                               params, "ok" if retry_ok else "fix_did_not_help", retry_ok)
            self._record_skill(error_type, module_name, fix_type, retry_ok)

            if retry_ok:
                print(f"[Recovery] Recovered via {fix_type}: {msg}")
                return {"recovered": True, "fix_applied": f"{description}: {msg}",
                        "result": new_result, "diagnosis": ""}

        # ── 3. Research fallback (informational, no retry) ────────────
        research_ok, research_info = self._research_fix(error_msg, module_name)
        self._log_recovery(error_type, error_msg, module_name, "research",
                           {}, "info_only" if research_ok else "failed", False)

        # ── 4. Build escalation diagnosis ─────────────────────────────
        pkg  = IMPORT_TO_PACKAGE.get(extracted, extracted)
        apt  = CMD_TO_APT.get(extracted, extracted)
        tmpl = DIAGNOSIS_TEMPLATES.get(error_type, "Unrecognized error in '{module}': {error}")
        diagnosis = tmpl.format(
            extracted=extracted, pkg=pkg, apt=apt,
            module=module_name, error=error_msg[:150]
        )
        if research_ok:
            diagnosis += f"\n\nResearch suggestion: {research_info}"

        return {"recovered": False, "fix_applied": "research" if research_ok else "none",
                "result": None, "diagnosis": diagnosis}

    def _record_skill(self, error_type: str, module_name: str, fix_type: str, success: bool):
        if not self.learning_engine:
            return
        try:
            self.learning_engine.process({
                "action": "record_skill",
                "agent": "autonomous_recovery",
                "tool": module_name,
                "tool_action": "recover",
                "input_pattern": {"error_type": error_type, "fix": fix_type},
                "outcome": "success" if success else "error",
            })
        except Exception:
            pass

    # ── Module API ────────────────────────────────────────────────────

    def process(self, input_data: dict) -> dict:
        action = input_data.get("action", "stats")
        if action == "stats":
            return self._stats()
        if action == "log":
            return self._recovery_log(input_data.get("limit", 20))
        if action == "cache":
            return self._solution_cache()
        return {"error": f"Unknown action: {action}"}

    def _stats(self) -> dict:
        with sqlite3.connect(str(self.db_path)) as conn:
            total    = conn.execute("SELECT COUNT(*) FROM recovery_log").fetchone()[0]
            success  = conn.execute("SELECT COUNT(*) FROM recovery_log WHERE retry_succeeded=1").fetchone()[0]
            by_type  = conn.execute(
                "SELECT error_type, COUNT(*), SUM(retry_succeeded) FROM recovery_log GROUP BY error_type"
            ).fetchall()
            cached   = conn.execute("SELECT COUNT(*) FROM solution_cache").fetchone()[0]
        return {
            "total_attempts": total,
            "successful":     success,
            "success_rate":   f"{round(success / max(total,1) * 100, 1)}%",
            "cached_solutions": cached,
            "by_error_type":  [{"type": r[0], "attempts": r[1], "successes": r[2] or 0} for r in by_type],
        }

    def _recovery_log(self, limit: int = 20) -> dict:
        with sqlite3.connect(str(self.db_path)) as conn:
            rows = conn.execute(
                "SELECT timestamp, error_type, module_name, fix_applied, outcome, retry_succeeded "
                "FROM recovery_log ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return {"log": [{"ts": r[0], "type": r[1], "module": r[2],
                          "fix": r[3], "outcome": r[4], "ok": bool(r[5])} for r in rows]}

    def _solution_cache(self) -> dict:
        with sqlite3.connect(str(self.db_path)) as conn:
            rows = conn.execute(
                "SELECT error_sample, fix_type, success_count, attempt_count, last_used "
                "FROM solution_cache ORDER BY success_count DESC"
            ).fetchall()
        return {"solutions": [{"error": r[0][:80], "fix": r[1],
                                "successes": r[2], "attempts": r[3], "last_used": r[4]}
                               for r in rows]}


# ── Helpers ───────────────────────────────────────────────────────────

def _is_error(result) -> bool:
    """Return True if a module result dict contains an error."""
    if not result:
        return True
    if isinstance(result, dict):
        if result.get("error"):
            return True
        inner = result.get("result", {})
        if isinstance(inner, dict) and inner.get("error"):
            return True
    return False


def extract_error_from_result(action_result) -> tuple[str, str]:
    """Return (error_msg, module_name) from an action result."""
    if isinstance(action_result, dict):
        if action_result.get("error"):
            return str(action_result["error"]), action_result.get("module", "")
        inner = action_result.get("result", {})
        if isinstance(inner, dict) and inner.get("error"):
            return str(inner["error"]), action_result.get("module", "")
    if isinstance(action_result, list):
        for ar in action_result:
            if ar.get("error"):
                return str(ar["error"]), ar.get("module", "")
            inner = ar.get("result", {})
            if isinstance(inner, dict) and inner.get("error"):
                return str(inner["error"]), ar.get("module", "")
    return "", ""
