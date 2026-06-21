# modules/app_launcher_module.py
import subprocess
import os
import json
import shutil
import webbrowser
from pathlib import Path
from .base import ModuleBase


class AppLauncherModule(ModuleBase):
    """Launch, close, minimize, maximize any application on Linux."""

    DEFAULT_APPS = {
        "browser": {"cmd": ["xdg-open", "https://google.com"], "type": "cmd"},
        "chrome": {"cmd": ["google-chrome"], "type": "which", "fallback": ["google-chrome-stable"]},
        "firefox": {"cmd": ["firefox"], "type": "which"},
        "brave": {"cmd": ["brave-browser"], "type": "which"},
        "terminal": {"cmd": ["gnome-terminal"], "type": "which"},
        "file manager": {"cmd": ["nautilus", "."], "type": "which", "fallback": ["dolphin", "thunar", "nemo"]},
        "calculator": {"cmd": ["gnome-calculator"], "type": "which", "fallback": ["kcalc", "qalculate-gtk"]},
        "vscode": {"cmd": ["code"], "type": "which"},
        "cursor": {"cmd": ["cursor"], "type": "which"},
        "spotify": {"cmd": ["spotify"], "type": "which"},
        "settings": {"cmd": ["gnome-control-center"], "type": "which", "fallback": ["systemsettings"]},
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
                if app["type"] == "which":
                    cmd = shutil.which(app["cmd"][0])
                    if not cmd and "fallback" in app:
                        for fb in app["fallback"]:
                            cmd = shutil.which(fb)
                            if cmd:
                                break
                    if cmd:
                        subprocess.Popen([cmd] + app["cmd"][1:] + (args if isinstance(args, list) else [args] if args else []))
                    else:
                        return {"error": f"'{name}' not found on system"}
                elif app["type"] == "cmd":
                    subprocess.Popen(app["cmd"])
                else:
                    subprocess.Popen(app["cmd"])
                return {"status": "ok", "message": f"Opened {name}"}
            except Exception as e:
                return {"error": f"Failed to open {name}: {str(e)}"}
        else:
            try:
                cmd = shutil.which(name)
                if cmd:
                    subprocess.Popen([cmd])
                    return {"status": "ok", "message": f"Opened '{name}' via PATH"}
                return {"error": f"App '{name}' not found in registry or PATH"}
            except Exception as e:
                return {"error": f"App '{name}' not found: {str(e)}"}

    def _close_app(self, name):
        try:
            subprocess.run(["wmctrl", "-c", name], capture_output=True, text=True, timeout=5)
            return {"status": "ok", "message": f"Requested close of '{name}'"}
        except FileNotFoundError:
            try:
                import i3ipc
                conn = i3ipc.Connection()
                for w in conn.get_tree():
                    if name.lower() in w.name.lower():
                        w.command("kill")
                return {"status": "ok", "message": f"Closed '{name}' via i3"}
            except ImportError:
                try:
                    subprocess.run(["xdotool", "search", "--name", name, "windowkill"], capture_output=True, timeout=5)
                    return {"status": "ok", "message": f"Closed '{name}' via xdotool"}
                except (FileNotFoundError, Exception):
                    return {"error": "Install wmctrl, i3ipc, or xdotool for window management"}

    def _minimize_app(self, name):
        try:
            subprocess.run(["xdotool", "search", "--name", name, "windowminimize"], capture_output=True, timeout=5)
            return {"status": "ok", "message": f"Minimized {name}"}
        except FileNotFoundError:
            return {"error": "xdotool not installed"}

    def _maximize_app(self, name):
        try:
            subprocess.run(["xdotool", "search", "--name", name, "windowstate", "--add", "maximized_vert", "maximized_horz"], capture_output=True, timeout=5)
            return {"status": "ok", "message": f"Maximized {name}"}
        except FileNotFoundError:
            return {"error": "xdotool not installed"}

    def _focus_app(self, name):
        try:
            subprocess.run(["xdotool", "search", "--name", name, "windowactivate"], capture_output=True, timeout=5)
            return {"status": "ok", "message": f"Focused on {name}"}
        except FileNotFoundError:
            return {"error": "xdotool not installed"}
        except Exception as e:
            return {"error": str(e)}

    def _list_windows(self):
        try:
            result = subprocess.run(["wmctrl", "-l"], capture_output=True, text=True, timeout=5)
            windows = [line.strip() for line in result.stdout.split("\n") if line.strip()]
            return {"status": "ok", "windows": windows}
        except FileNotFoundError:
            return {"error": "wmctrl not installed"}

    def _register_app(self, name, path_or_cmd):
        self.apps[name.lower()] = {"cmd": path_or_cmd.split() if isinstance(path_or_cmd, str) else path_or_cmd, "type": "which"}
        custom = {}
        if self.custom_apps_file.exists():
            try:
                with open(self.custom_apps_file, "r") as f:
                    custom = json.load(f)
            except Exception:
                pass
        custom[name.lower()] = path_or_cmd
        self._save_custom_apps(custom)
        return {"status": "ok", "message": f"Registered '{name}' → {path_or_cmd}"}

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
