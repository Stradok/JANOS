# modules/daemon_module.py
"""
Daemon Module for JAN (Joint Autonomous Neural Agent).
Always-on background brain that runs scheduled tasks, monitors system health,
detects patterns, learns preferences, optionally watches via camera, and
tracks user activity for idle/low-power management.
"""
import json
import time
import threading
import logging
import os
from datetime import datetime
from pathlib import Path
from logging.handlers import RotatingFileHandler

from .base import ModuleBase

# ---------------------------------------------------------------------------
# Logging setup — dedicated daemon logger writing to memory/logs/daemon.log
# ---------------------------------------------------------------------------
_log_dir = Path("memory/logs")
_log_dir.mkdir(parents=True, exist_ok=True)

_daemon_logger = logging.getLogger("jan.daemon")
_daemon_logger.setLevel(logging.DEBUG)

if not _daemon_logger.handlers:
    _handler = RotatingFileHandler(
        str(_log_dir / "daemon.log"),
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=3,
        encoding="utf-8",
    )
    _handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    )
    _daemon_logger.addHandler(_handler)

log = _daemon_logger


class DaemonModule(ModuleBase):
    """JAN's always-on background daemon — scheduled tasks, monitoring,
    proactive learning, camera watch, health pings, and idle detection."""

    def __init__(self):
        super().__init__("daemon")

        # External dependencies (wired from __init__.py after construction)
        self.orchestrator = None
        self.proactive = None
        self.dual_llm = None
        self.vision = None
        self.person_recognition = None
        self.memory = None

        # Internal state
        self._thread = None
        self._running = False
        self._last_user_activity = time.time()
        self._start_time = None

        # Configurable intervals (seconds)
        self._intervals = {
            "scheduled_tasks": 60,       # check every 1 min
            "system_monitor": 300,       # check every 5 min
            "pattern_analysis": 3600,    # check every 1 hour
            "preference_learning": 7200, # check every 2 hours
            "camera_watch": 30,          # check every 30 sec (if enabled)
            "health_ping": 300,          # log every 5 min
        }

        # Track when each check last ran
        self._last_run = {}

        # Camera watch
        self._camera_watch_enabled = False
        self._camera_id = 0

        # Idle detection
        self._idle_threshold = 1800  # 30 min before low-power mode
        self._low_power = False

    # ------------------------------------------------------------------
    # process() — public API
    # ------------------------------------------------------------------
    def process(self, input_data):
        action = input_data.get("action", "") if isinstance(input_data, dict) else str(input_data)

        dispatch = {
            "start": self._action_start,
            "stop": self._action_stop,
            "status": self._action_status,
            "set_interval": self._action_set_interval,
            "enable_camera_watch": self._action_enable_camera_watch,
            "mark_activity": self._action_mark_activity,
            "get_log": self._action_get_log,
            "force_check": self._action_force_check,
        }

        handler = dispatch.get(action)
        if handler is None:
            return {"status": "error", "error": f"Unknown action: {action}"}

        try:
            return handler(input_data if isinstance(input_data, dict) else {})
        except Exception as e:
            log.error(f"[Daemon] Action '{action}' failed: {e}")
            return {"status": "error", "error": str(e)}

    # ------------------------------------------------------------------
    # Action handlers
    # ------------------------------------------------------------------
    def _action_start(self, data):
        if self._running:
            return {"status": "ok", "message": "Daemon already running"}

        self._running = True
        self._start_time = time.time()
        self._last_run = {}
        self._low_power = False

        self._thread = threading.Thread(target=self._run_loop, name="JAN-Daemon")
        self._thread.daemon = True
        self._thread.start()

        log.info("[Daemon] JAN background daemon started")
        return {"status": "ok", "message": "Daemon started"}

    def _action_stop(self, data):
        if not self._running:
            return {"status": "ok", "message": "Daemon is not running"}

        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=15)
        self._thread = None

        log.info("[Daemon] JAN background daemon stopped")
        return {"status": "ok", "message": "Daemon stopped"}

    def _action_status(self, data):
        uptime = time.time() - self._start_time if self._start_time and self._running else 0
        idle_seconds = time.time() - self._last_user_activity

        return {
            "status": "ok",
            "running": self._running,
            "uptime_seconds": round(uptime, 1),
            "last_user_activity_ago": round(idle_seconds, 1),
            "low_power_mode": self._low_power,
            "camera_watch_enabled": self._camera_watch_enabled,
            "intervals": dict(self._intervals),
            "last_run": {
                k: datetime.fromtimestamp(v).isoformat()
                for k, v in self._last_run.items()
            },
        }

    def _action_set_interval(self, data):
        task_name = data.get("task_name", "")
        seconds = data.get("seconds")

        if task_name not in self._intervals:
            return {"status": "error", "error": f"Unknown task: {task_name}. Valid: {list(self._intervals.keys())}"}
        if not isinstance(seconds, (int, float)) or seconds <= 0:
            return {"status": "error", "error": "seconds must be a positive number"}

        self._intervals[task_name] = int(seconds)
        log.info(f"[Daemon] Interval for '{task_name}' set to {seconds}s")
        return {"status": "ok", "task_name": task_name, "seconds": int(seconds)}

    def _action_enable_camera_watch(self, data):
        enabled = data.get("enabled", True)
        self._camera_id = data.get("camera_id", 0)
        self._camera_watch_enabled = bool(enabled)

        state = "enabled" if self._camera_watch_enabled else "disabled"
        log.info(f"[Daemon] Camera watch {state} (camera_id={self._camera_id})")
        return {"status": "ok", "camera_watch_enabled": self._camera_watch_enabled, "camera_id": self._camera_id}

    def _action_mark_activity(self, data):
        self._last_user_activity = time.time()
        if self._low_power:
            self._low_power = False
            log.info("[Daemon] User activity detected — exiting low-power mode")
        return {"status": "ok", "last_user_activity": self._last_user_activity}

    def _action_get_log(self, data):
        lines = data.get("lines", 50)
        log_path = _log_dir / "daemon.log"

        if not log_path.exists():
            return {"status": "ok", "lines": []}

        try:
            with open(log_path, "r", encoding="utf-8") as f:
                all_lines = f.readlines()
            tail = all_lines[-lines:] if len(all_lines) > lines else all_lines
            return {"status": "ok", "lines": [l.rstrip("\n") for l in tail]}
        except Exception as e:
            return {"status": "error", "error": f"Failed to read log: {e}"}

    def _action_force_check(self, data):
        check_name = data.get("check_name", "")
        valid = [
            "scheduled_tasks", "system_monitor", "pattern_analysis",
            "preference_learning", "camera_watch", "health_ping",
        ]
        if check_name not in valid:
            return {"status": "error", "error": f"Unknown check: {check_name}. Valid: {valid}"}

        try:
            self._execute_check(check_name)
            self._last_run[check_name] = time.time()
            return {"status": "ok", "check": check_name, "executed": True}
        except Exception as e:
            return {"status": "error", "error": f"Check '{check_name}' failed: {e}"}

    # ------------------------------------------------------------------
    # Main daemon loop
    # ------------------------------------------------------------------
    def _run_loop(self):
        log.info("[Daemon] JAN background daemon loop running")
        while self._running:
            now = time.time()
            try:
                # Idle detection
                idle_seconds = now - self._last_user_activity
                if idle_seconds >= self._idle_threshold and not self._low_power:
                    self._enter_low_power()

                # Check each task type based on its interval
                for task_name, interval in self._intervals.items():
                    # Skip camera_watch if not enabled
                    if task_name == "camera_watch" and not self._camera_watch_enabled:
                        continue

                    # In low-power mode, double all intervals
                    effective_interval = interval * 2 if self._low_power else interval

                    if now - self._last_run.get(task_name, 0) >= effective_interval:
                        self._execute_check(task_name)
                        self._last_run[task_name] = now
            except Exception as e:
                log.error(f"[Daemon] Loop error: {e}")

            time.sleep(10)  # main loop tick every 10 seconds

        log.info("[Daemon] JAN background daemon loop exited")

    # ------------------------------------------------------------------
    # Check dispatcher
    # ------------------------------------------------------------------
    def _execute_check(self, task_name):
        handlers = {
            "scheduled_tasks": self._check_scheduled_tasks,
            "system_monitor": self._check_system_health,
            "pattern_analysis": self._check_patterns,
            "preference_learning": self._check_preferences,
            "camera_watch": self._check_camera,
            "health_ping": self._health_ping,
        }

        handler = handlers.get(task_name)
        if handler:
            try:
                handler()
            except Exception as e:
                log.error(f"[Daemon] Check '{task_name}' failed: {e}")

    # ------------------------------------------------------------------
    # Individual check implementations
    # ------------------------------------------------------------------
    def _check_scheduled_tasks(self):
        """Get due tasks from proactive_learning, execute each through orchestrator."""
        if not self.proactive:
            return

        try:
            due = self.proactive.process({"action": "get_due_tasks"})
        except Exception as e:
            log.error(f"[Daemon] Failed to get due tasks: {e}")
            return

        tasks = due.get("tasks", []) if isinstance(due, dict) else []
        for task in tasks:
            task_type = task.get("task_type", "")
            raw_data = task.get("task_data", "{}")
            task_data = json.loads(raw_data) if isinstance(raw_data, str) else raw_data

            try:
                if self.orchestrator:
                    prompt = f"Execute scheduled task: {task_type} with data {task_data}"
                    self.orchestrator.process({"message": prompt})
                    log.info(f"[Daemon] Executed scheduled task: {task_type}")
            except Exception as e:
                log.error(f"[Daemon] Failed to execute task {task_type}: {e}")

    def _check_system_health(self):
        """Check CPU/RAM/disk via psutil, log stats, warn if resources are low."""
        try:
            import psutil
        except ImportError:
            log.warning("[Daemon] psutil not installed — skipping system health check")
            return

        try:
            cpu_percent = psutil.cpu_percent(interval=1)
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage("/") if os.name != "nt" else psutil.disk_usage("C:\\")

            ram_available_gb = mem.available / (1024 ** 3)
            disk_free_gb = disk.free / (1024 ** 3)

            log.info(
                f"[Daemon] System health — CPU: {cpu_percent}%, "
                f"RAM: {mem.percent}% used ({ram_available_gb:.1f} GB free), "
                f"Disk: {disk.percent}% used ({disk_free_gb:.1f} GB free)"
            )

            # Warn on high resource usage
            if ram_available_gb < 2.0:
                log.warning(f"[Daemon] LOW RAM: only {ram_available_gb:.1f} GB available")
                self._try_free_memory()

            if cpu_percent > 90:
                log.warning(f"[Daemon] HIGH CPU: {cpu_percent}%")

            if disk.percent > 95:
                log.warning(f"[Daemon] DISK ALMOST FULL: {disk.percent}% used")

        except Exception as e:
            log.error(f"[Daemon] System health check error: {e}")

    def _try_free_memory(self):
        """Attempt to free memory by unloading large models or closing unused resources."""
        log.info("[Daemon] Attempting to free memory...")

        # Try unloading big LLM via dual_llm module
        if self.dual_llm:
            try:
                self.dual_llm.process({"action": "unload_model"})
                log.info("[Daemon] Unloaded large LLM to free memory")
            except Exception as e:
                log.warning(f"[Daemon] Could not unload LLM: {e}")

    def _check_patterns(self):
        """Run pattern analysis via proactive learning module."""
        if not self.proactive:
            return

        try:
            result = self.proactive.process({"action": "analyze_patterns"})
            patterns_found = result.get("patterns_found", 0) if isinstance(result, dict) else 0
            log.info(f"[Daemon] Pattern analysis complete — {patterns_found} patterns found")
        except Exception as e:
            log.error(f"[Daemon] Pattern analysis failed: {e}")

    def _check_preferences(self):
        """Run preference learning via proactive learning module."""
        if not self.proactive:
            return

        try:
            result = self.proactive.process({"action": "learn_preferences"})
            log.info(f"[Daemon] Preference learning complete — {result}")
        except Exception as e:
            log.error(f"[Daemon] Preference learning failed: {e}")

    def _check_camera(self):
        """Capture frame from webcam, detect faces, greet if known."""
        if not self._camera_watch_enabled:
            return

        if not self.vision:
            log.debug("[Daemon] Camera watch enabled but VisionModule not wired")
            return

        try:
            # Capture a frame via vision module
            capture_result = self.vision.process({
                "action": "capture",
                "camera_id": self._camera_id,
            })

            if not capture_result or capture_result.get("status") == "error":
                return

            image_path = capture_result.get("image_path", "")
            if not image_path:
                return

            # Run person recognition if available
            if self.person_recognition:
                recognition_result = self.person_recognition.process({
                    "action": "identify",
                    "image_path": image_path,
                })

                persons = recognition_result.get("persons", []) if isinstance(recognition_result, dict) else []
                for person in persons:
                    name = person.get("name", "Unknown")
                    confidence = person.get("confidence", 0)
                    if name != "Unknown" and confidence > 0.6:
                        log.info(f"[Daemon] Recognized {name} (confidence: {confidence:.2f}) — sending greeting")
                        self._greet_person(name)

            # Clean up temp capture
            try:
                if image_path and os.path.exists(image_path):
                    os.remove(image_path)
            except OSError:
                pass

        except Exception as e:
            log.error(f"[Daemon] Camera watch error: {e}")

    def _greet_person(self, name):
        """Send a greeting through the orchestrator for a recognized person."""
        if not self.orchestrator:
            return

        try:
            greeting_prompt = f"Greet {name} warmly — they were just detected by camera."
            self.orchestrator.process({"message": greeting_prompt})
            log.info(f"[Daemon] Greeting sent for {name}")
        except Exception as e:
            log.error(f"[Daemon] Failed to greet {name}: {e}")

    def _health_ping(self):
        """Log heartbeat with uptime, module count, and memory stats."""
        uptime = time.time() - self._start_time if self._start_time else 0
        hours, remainder = divmod(int(uptime), 3600)
        minutes, seconds = divmod(remainder, 60)

        # Count wired modules
        deps = [self.orchestrator, self.proactive, self.dual_llm,
                self.vision, self.person_recognition, self.memory]
        wired_count = sum(1 for d in deps if d is not None)

        # Memory stats via psutil
        mem_info = ""
        try:
            import psutil
            proc = psutil.Process(os.getpid())
            rss_mb = proc.memory_info().rss / (1024 ** 2)
            mem_info = f", process RSS: {rss_mb:.1f} MB"
        except Exception:
            pass

        log.info(
            f"[Daemon] ♥ Heartbeat — uptime: {hours}h {minutes}m {seconds}s, "
            f"modules wired: {wired_count}/6, "
            f"low_power: {self._low_power}, "
            f"camera_watch: {self._camera_watch_enabled}"
            f"{mem_info}"
        )

    # ------------------------------------------------------------------
    # Idle / low-power management
    # ------------------------------------------------------------------
    def _enter_low_power(self):
        """Enter low-power mode: unload heavy models, reduce check frequency."""
        self._low_power = True
        log.info("[Daemon] User idle — entering low-power mode (intervals doubled)")

        # Try unloading big LLM to save resources
        if self.dual_llm:
            try:
                self.dual_llm.process({"action": "unload_model"})
                log.info("[Daemon] Unloaded large LLM for low-power mode")
            except Exception as e:
                log.warning(f"[Daemon] Could not unload LLM for low-power: {e}")
