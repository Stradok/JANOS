# modules/app_launcher_module.py
import subprocess
import os
import json
from pathlib import Path
from .base import ModuleBase

try:
    import pygetwindow as gw
    GW_AVAILABLE = True
except ImportError:
    GW_AVAILABLE = False


class AppLauncherModule(ModuleBase):
    """Launch, close, minimize, maximize any application on Windows."""

    # Default app registry — maps friendly names to executable paths / commands
    DEFAULT_APPS = {
        "spotify": {
            "path": r"shell:AppsFolder\SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify",
            "type": "shell"
        },
        "opera": {
            "path": r"C:\Users\strad\AppData\Local\Programs\Opera GX\opera.exe",
            "type": "exe"
        },
        "opera gx": {
            "path": r"C:\Users\strad\AppData\Local\Programs\Opera GX\opera.exe",
            "type": "exe"
        },
        "browser": {
            "path": r"C:\Users\strad\AppData\Local\Programs\Opera GX\opera.exe",
            "type": "exe"
        },
        "chrome": {
            "path": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            "type": "exe"
        },
        "brave": {
            "path": r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
            "type": "exe"
        },
        "firefox": {
            "path": r"C:\Program Files\Mozilla Firefox\firefox.exe",
            "type": "exe"
        },
        "notepad": {"path": "notepad.exe", "type": "exe"},
        "calculator": {"path": "calc.exe", "type": "exe"},
        "file explorer": {"path": "explorer.exe", "type": "exe"},
        "explorer": {"path": "explorer.exe", "type": "exe"},
        "terminal": {"path": "wt.exe", "type": "exe"},
        "powershell": {"path": "powershell.exe", "type": "exe"},
        "cmd": {"path": "cmd.exe", "type": "exe"},
        "task manager": {"path": "taskmgr.exe", "type": "exe"},
        "settings": {"path": "ms-settings:", "type": "shell"},
        "vscode": {
            "path": r"C:\Users\strad\AppData\Local\Programs\Microsoft VS Code\Code.exe",
            "type": "exe"
        },
        "cursor": {
            "path": r"C:\Users\strad\AppData\Local\Programs\cursor\Cursor.exe",
            "type": "exe"
        },
    }

    def __init__(self):
        super().__init__("app_launcher")
        self.apps = dict(self.DEFAULT_APPS)
        # load custom app mappings if they exist
        self.custom_apps_file = Path("memory/app_registry.json")
        self._load_custom_apps()

    def _load_custom_apps(self):
        if self.custom_apps_file.exists():
            try:
                with open(self.custom_apps_file, "r") as f:
                    custom = json.load(f)
                self.apps.update(custom)
            except Exception:
                pass

    def _save_custom_apps(self, custom):
        self.custom_apps_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.custom_apps_file, "w") as f:
            json.dump(custom, f, indent=2)

    def _find_app(self, name):
        """Find app by name (case-insensitive, partial match)."""
        name_lower = name.lower().strip()
        # exact match
        if name_lower in self.apps:
            return self.apps[name_lower]
        # partial match
        for key, val in self.apps.items():
            if name_lower in key or key in name_lower:
                return val
        return None

    def _open_app(self, name, args=None):
        app = self._find_app(name)
        if app:
            try:
                if app["type"] == "shell":
                    subprocess.Popen(["explorer", app["path"]])
                else:
                    cmd = [app["path"]]
                    if args:
                        cmd.extend(args if isinstance(args, list) else [args])
                    subprocess.Popen(cmd)
                return {"status": "ok", "message": f"Opened {name}"}
            except Exception as e:
                return {"error": f"Failed to open {name}: {str(e)}"}
        else:
            # try opening directly as a command
            try:
                subprocess.Popen(["start", name], shell=True)
                return {"status": "ok", "message": f"Attempted to open '{name}' via Windows start"}
            except Exception as e:
                return {"error": f"App '{name}' not found in registry and could not start directly: {str(e)}"}

    def _close_app(self, name):
        if not GW_AVAILABLE:
            return {"error": "pygetwindow not installed"}
        windows = gw.getWindowsWithTitle(name)
        if not windows:
            return {"error": f"No window found with title containing '{name}'"}
        closed = []
        for w in windows:
            try:
                w.close()
                closed.append(w.title)
            except Exception:
                pass
        return {"status": "ok", "message": f"Closed: {closed}"}

    def _minimize_app(self, name):
        if not GW_AVAILABLE:
            return {"error": "pygetwindow not installed"}
        windows = gw.getWindowsWithTitle(name)
        if not windows:
            return {"error": f"No window found with title containing '{name}'"}
        for w in windows:
            try:
                w.minimize()
            except Exception:
                pass
        return {"status": "ok", "message": f"Minimized {name}"}

    def _maximize_app(self, name):
        if not GW_AVAILABLE:
            return {"error": "pygetwindow not installed"}
        windows = gw.getWindowsWithTitle(name)
        if not windows:
            return {"error": f"No window found with title containing '{name}'"}
        for w in windows:
            try:
                w.maximize()
                w.activate()
            except Exception:
                pass
        return {"status": "ok", "message": f"Maximized {name}"}

    def _focus_app(self, name):
        if not GW_AVAILABLE:
            return {"error": "pygetwindow not installed"}
        windows = gw.getWindowsWithTitle(name)
        if not windows:
            return {"error": f"No window found with title containing '{name}'"}
        try:
            windows[0].activate()
            return {"status": "ok", "message": f"Focused on {windows[0].title}"}
        except Exception as e:
            return {"error": str(e)}

    def _list_windows(self):
        if not GW_AVAILABLE:
            return {"error": "pygetwindow not installed"}
        titles = [w.title for w in gw.getAllWindows() if w.title.strip()]
        return {"status": "ok", "windows": titles}

    def _register_app(self, name, path):
        """Register a new app mapping."""
        self.apps[name.lower()] = {"path": path, "type": "exe"}
        # save to custom file
        custom = {}
        if self.custom_apps_file.exists():
            try:
                with open(self.custom_apps_file, "r") as f:
                    custom = json.load(f)
            except Exception:
                pass
        custom[name.lower()] = {"path": path, "type": "exe"}
        self._save_custom_apps(custom)
        return {"status": "ok", "message": f"Registered '{name}' → {path}"}

    def process(self, input_data):
        action = input_data.get("action", "open")
        name = input_data.get("name", "")
        args = input_data.get("args")
        path = input_data.get("path", "")

        if action == "open":
            if not name:
                return {"error": "Missing 'name' of application to open"}
            return self._open_app(name, args)
        elif action == "close":
            return self._close_app(name)
        elif action == "minimize":
            return self._minimize_app(name)
        elif action == "maximize":
            return self._maximize_app(name)
        elif action == "focus":
            return self._focus_app(name)
        elif action == "list_windows":
            return self._list_windows()
        elif action == "list_apps":
            return {"status": "ok", "apps": list(self.apps.keys())}
        elif action == "register":
            if not name or not path:
                return {"error": "Need 'name' and 'path' to register an app"}
            return self._register_app(name, path)
        else:
            return {"error": f"Unknown action: {action}. Use: open, close, minimize, maximize, focus, list_windows, list_apps, register"}
