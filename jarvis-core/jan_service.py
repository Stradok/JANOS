"""
JAN (Joint Autonomous Neural Agent) — Windows Service / Startup Wrapper
Runs JAN autonomously from boot.

Usage:
    python jan_service.py                  # standalone mode (default)
    python jan_service.py standalone       # same as above
    python jan_service.py install          # install Windows service (requires pywin32 + admin)
    python jan_service.py start            # start the Windows service
    python jan_service.py stop             # stop the Windows service
    python jan_service.py remove           # uninstall the Windows service
"""

import sys
import os
import time
import subprocess
import logging
from pathlib import Path

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "memory" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    filename=str(LOG_DIR / "service.log"),
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("JAN")

# ---------------------------------------------------------------------------
# Optional pywin32 imports
# ---------------------------------------------------------------------------
try:
    import win32serviceutil
    import win32service
    import win32event
    import servicemanager
    WIN32_AVAILABLE = True
except ImportError:
    WIN32_AVAILABLE = False


# ---------------------------------------------------------------------------
# Core service logic (used by both standalone and Windows-service modes)
# ---------------------------------------------------------------------------
class JANService:
    """JAN core service — starts Ollama + FastAPI, monitors health."""

    _svc_name_ = "JAN_Agent"
    _svc_display_name_ = "JAN - Joint Autonomous Neural Agent"
    _svc_description_ = (
        "Autonomous AI assistant running locally. "
        "Monitors PC, responds to commands, learns and evolves."
    )

    HEALTH_INTERVAL = 30  # seconds between health checks

    def __init__(self):
        self.running = False
        self.ollama_process = None
        self.jan_process = None
        self.base_dir = BASE_DIR

    # -- Ollama management ---------------------------------------------------

    def _start_ollama(self):
        """Start Ollama server if it is not already running."""
        # Check if Ollama is already up
        try:
            import requests
            requests.get("http://localhost:11434/api/tags", timeout=3)
            logger.info("Ollama already running")
            return True
        except Exception:
            pass

        username = os.getenv("USERNAME", "")
        ollama_paths = [
            rf"C:\Users\{username}\AppData\Local\Programs\Ollama\ollama.exe",
            r"C:\Program Files\Ollama\ollama.exe",
            "ollama",  # fallback: on PATH
        ]

        creation_flags = 0
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            creation_flags = subprocess.CREATE_NO_WINDOW

        for path in ollama_paths:
            try:
                self.ollama_process = subprocess.Popen(
                    [path, "serve"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=creation_flags,
                )
                logger.info("Started Ollama from %s (pid %s)", path, self.ollama_process.pid)
                time.sleep(5)  # give Ollama time to bind its port
                return True
            except FileNotFoundError:
                continue
            except Exception as exc:
                logger.error("Failed to start Ollama from %s: %s", path, exc)

        logger.error("Could not start Ollama — not found in any known location")
        return False

    # -- JAN FastAPI server --------------------------------------------------

    def _start_jan(self):
        """Start JAN's FastAPI server via uvicorn."""
        creation_flags = 0
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            creation_flags = subprocess.CREATE_NO_WINDOW

        try:
            self.jan_process = subprocess.Popen(
                [
                    sys.executable, "-m", "uvicorn",
                    "main:app",
                    "--host", "127.0.0.1",
                    "--port", "8000",
                ],
                cwd=str(self.base_dir),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creation_flags,
            )
            logger.info("JAN FastAPI server started on port 8000 (pid %s)", self.jan_process.pid)
            return True
        except Exception as exc:
            logger.error("Failed to start JAN: %s", exc)
            return False

    # -- Health monitoring ---------------------------------------------------

    def _log_health(self):
        """Log basic system health stats."""
        try:
            import psutil
            cpu = psutil.cpu_percent(interval=1)
            ram = psutil.virtual_memory()
            logger.info(
                "Health — CPU: %.1f%%  RAM: %.1f%% (%.0f MB free)",
                cpu, ram.percent, ram.available / (1024 * 1024),
            )
        except ImportError:
            pass  # psutil not installed; skip silently

    # -- Start / Stop --------------------------------------------------------

    def start(self):
        """Main entry: start dependencies, then monitor in a loop."""
        logger.info("=" * 50)
        logger.info("JAN Service starting...")
        self.running = True

        self._start_ollama()
        time.sleep(2)
        self._start_jan()

        health_counter = 0
        while self.running:
            # Restart JAN if it crashed
            if self.jan_process and self.jan_process.poll() is not None:
                logger.warning("JAN process died (exit %s), restarting...", self.jan_process.returncode)
                self._start_jan()

            # Periodic health log
            health_counter += 1
            if health_counter >= 10:  # every ~5 minutes (10 × 30 s)
                self._log_health()
                health_counter = 0

            time.sleep(self.HEALTH_INTERVAL)

    def stop(self):
        """Graceful shutdown of JAN and Ollama."""
        logger.info("JAN Service stopping...")
        self.running = False

        if self.jan_process:
            self.jan_process.terminate()
            try:
                self.jan_process.wait(timeout=10)
            except Exception:
                self.jan_process.kill()
            logger.info("JAN process stopped")

        if self.ollama_process:
            self.ollama_process.terminate()
            try:
                self.ollama_process.wait(timeout=10)
            except Exception:
                self.ollama_process.kill()
            logger.info("Ollama process stopped")

        logger.info("JAN Service stopped")


# ---------------------------------------------------------------------------
# Standalone runner (no Windows-service dependency)
# ---------------------------------------------------------------------------
def run_standalone():
    """Run JAN interactively — press Ctrl+C to stop."""
    service = JANService()
    print("=" * 50)
    print("  JAN - Joint Autonomous Neural Agent")
    print("  Running in standalone mode")
    print("  Press Ctrl+C to stop")
    print("=" * 50)
    try:
        service.start()
    except KeyboardInterrupt:
        print("\nShutting down...")
        service.stop()
        print("JAN stopped.")


# ---------------------------------------------------------------------------
# Windows Service class (requires pywin32)
# ---------------------------------------------------------------------------
if WIN32_AVAILABLE:
    class JANWindowsService(win32serviceutil.ServiceFramework):
        _svc_name_ = "JAN_Agent"
        _svc_display_name_ = "JAN - Joint Autonomous Neural Agent"
        _svc_description_ = "Autonomous AI assistant running locally."

        def __init__(self, args):
            win32serviceutil.ServiceFramework.__init__(self, args)
            self.stop_event = win32event.CreateEvent(None, 0, 0, None)
            self.service = JANService()

        def SvcStop(self):
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            win32event.SetEvent(self.stop_event)
            self.service.stop()

        def SvcDoRun(self):
            servicemanager.LogMsg(
                servicemanager.EVENTLOG_INFORMATION_TYPE,
                servicemanager.PYS_SERVICE_STARTED,
                (self._svc_name_, ""),
            )
            self.service.start()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "standalone":
        run_standalone()
    elif len(sys.argv) > 1 and WIN32_AVAILABLE:
        # Delegate install / start / stop / remove to pywin32
        win32serviceutil.HandleCommandLine(JANWindowsService)
    elif len(sys.argv) > 1:
        print("pywin32 is not installed — service commands unavailable.")
        print("Install it with:  pip install pywin32")
        print("Or run in standalone mode:  python jan_service.py standalone")
        sys.exit(1)
    else:
        run_standalone()
