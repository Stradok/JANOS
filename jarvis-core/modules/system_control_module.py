# modules/system_control_module.py
import subprocess
import sys
import os
from .base import ModuleBase

try:
    import pyautogui
    PYAUTOGUI_AVAILABLE = True
except Exception:
    PYAUTOGUI_AVAILABLE = False

try:
    import pulsectl
    PULSE_AVAILABLE = True
except ImportError:
    PULSE_AVAILABLE = False

try:
    from ctypes import cast, POINTER
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    PYCAW_AVAILABLE = True
except ImportError:
    PYCAW_AVAILABLE = False


class SystemControlModule(ModuleBase):
    """Control system settings: volume, brightness, clipboard, lock, shutdown, etc."""

    def __init__(self):
        super().__init__("system_control")

    def _get_volume(self):
        if PULSE_AVAILABLE:
            try:
                with pulsectl.Pulse('jarvis-vol') as pulse:
                    sink = pulse.get_sink_by_name(pulse.get_sink_list()[0].name)
                    vol = round(sink.volume.value_flat * 100)
                    muted = sink.mute
                    return {"status": "ok", "volume": vol, "muted": muted}
            except Exception as e:
                pass
        if PYCAW_AVAILABLE:
            try:
                devices = AudioUtilities.GetSpeakers()
                vol_iface = devices.EndpointVolume if hasattr(devices, 'EndpointVolume') else cast(devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None), POINTER(IAudioEndpointVolume))
                current = vol_iface.GetMasterVolumeLevelScalar()
                muted = vol_iface.GetMute()
                return {"status": "ok", "volume": round(current * 100), "muted": bool(muted)}
            except Exception as e:
                pass
        return {"error": "Volume control requires pulsectl (Linux) or pycaw (Windows)"}

    def _set_volume(self, level):
        level = max(0, min(100, level))
        if PULSE_AVAILABLE:
            try:
                with pulsectl.Pulse('jarvis-vol') as pulse:
                    sink = pulse.get_sink_by_name(pulse.get_sink_list()[0].name)
                    pulse.volume_set_all_chans(sink, level / 100.0)
                    return {"status": "ok", "volume": level}
            except Exception as e:
                pass
        if PYCAW_AVAILABLE:
            try:
                devices = AudioUtilities.GetSpeakers()
                vol_iface = devices.EndpointVolume if hasattr(devices, 'EndpointVolume') else cast(devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None), POINTER(IAudioEndpointVolume))
                vol_iface.SetMasterVolumeLevelScalar(level / 100.0, None)
                return {"status": "ok", "volume": level}
            except Exception as e:
                pass
        return {"error": "Volume control requires pulsectl (Linux) or pycaw (Windows)"}

    def _mute(self):
        if PULSE_AVAILABLE:
            try:
                with pulsectl.Pulse('jarvis-vol') as pulse:
                    sink = pulse.get_sink_by_name(pulse.get_sink_list()[0].name)
                    pulse.mute(sink, True)
                    return {"status": "ok", "muted": True}
            except Exception as e:
                pass
        if PYCAW_AVAILABLE:
            try:
                devices = AudioUtilities.GetSpeakers()
                vol_iface = devices.EndpointVolume if hasattr(devices, 'EndpointVolume') else cast(devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None), POINTER(IAudioEndpointVolume))
                vol_iface.SetMute(1, None)
                return {"status": "ok", "muted": True}
            except Exception as e:
                pass
        return {"error": "Volume control requires pulsectl (Linux) or pycaw (Windows)"}

    def _unmute(self):
        if PULSE_AVAILABLE:
            try:
                with pulsectl.Pulse('jarvis-vol') as pulse:
                    sink = pulse.get_sink_by_name(pulse.get_sink_list()[0].name)
                    pulse.mute(sink, False)
                    return {"status": "ok", "muted": False}
            except Exception as e:
                pass
        if PYCAW_AVAILABLE:
            try:
                devices = AudioUtilities.GetSpeakers()
                vol_iface = devices.EndpointVolume if hasattr(devices, 'EndpointVolume') else cast(devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None), POINTER(IAudioEndpointVolume))
                vol_iface.SetMute(0, None)
                return {"status": "ok", "muted": False}
            except Exception as e:
                pass
        return {"error": "Volume control requires pulsectl (Linux) or pycaw (Windows)"}

    def _volume_up(self, step=10):
        current = self._get_volume()
        if "error" in current:
            return current
        new_level = min(100, current["volume"] + step)
        return self._set_volume(new_level)

    def _volume_down(self, step=10):
        current = self._get_volume()
        if "error" in current:
            return current
        new_level = max(0, current["volume"] - step)
        return self._set_volume(new_level)

    def _screenshot(self, path="memory/screenshot.png"):
        if not PYAUTOGUI_AVAILABLE:
            return {"error": "pyautogui not installed"}
        os.makedirs(os.path.dirname(path), exist_ok=True)
        img = pyautogui.screenshot()
        img.save(path)
        return {"status": "ok", "saved": path}

    def _clipboard_read(self):
        try:
            import pyperclip
            content = pyperclip.paste()
            return {"status": "ok", "clipboard": content}
        except ImportError:
            return {"error": "pyperclip not installed"}
        except Exception as e:
            return {"error": str(e)}

    def _clipboard_write(self, text):
        try:
            import pyperclip
            pyperclip.copy(text)
            return {"status": "ok", "message": f"Copied to clipboard ({len(text)} chars)"}
        except ImportError:
            return {"error": "pyperclip not installed"}
        except Exception as e:
            return {"error": str(e)}

    def _lock_screen(self):
        try:
            for cmd in [
                ["loginctl", "lock-session"],
                ["gnome-screensaver-command", "-l"],
                ["xdg-screensaver", "lock"],
            ]:
                try:
                    subprocess.run(cmd, capture_output=True, timeout=5)
                    return {"status": "ok", "message": "Screen locked"}
                except (FileNotFoundError, Exception):
                    continue
            return {"error": "No screen locker found (try loginctl, gnome-screensaver-command)"}
        except Exception as e:
            return {"error": str(e)}

    def _shutdown(self, confirm=False):
        if not confirm:
            return {"status": "waiting_confirmation", "message": "Are you sure you want to SHUT DOWN? Send again with confirm=true"}
        subprocess.Popen(["systemctl", "poweroff", "-i"])
        return {"status": "ok", "message": "Shutting down..."}

    def _restart(self, confirm=False):
        if not confirm:
            return {"status": "waiting_confirmation", "message": "Are you sure you want to RESTART? Send again with confirm=true"}
        subprocess.Popen(["systemctl", "reboot", "-i"])
        return {"status": "ok", "message": "Restarting..."}

    def _sleep(self):
        try:
            subprocess.Popen(["systemctl", "suspend"])
            return {"status": "ok", "message": "Going to sleep"}
        except FileNotFoundError:
            try:
                subprocess.Popen(["loginctl", "suspend"])
                return {"status": "ok", "message": "Going to sleep"}
            except Exception as e:
                return {"error": str(e)}

    def _open_url(self, url):
        try:
            import webbrowser
            webbrowser.open(url)
            return {"status": "ok", "message": f"Opened {url} in default browser"}
        except Exception as e:
            return {"error": str(e)}

    def _pip_install(self, package, upgrade=False):
        """Install a Python package using pip from the current environment."""
        try:
            cmd = [sys.executable, "-m", "pip", "install"]
            if upgrade:
                cmd.append("--upgrade")
            cmd.append(package)
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.returncode == 0:
                return {"status": "ok", "message": f"Installed {package}", "output": result.stdout[-300:]}
            return {"error": f"pip install failed: {result.stderr[-300:]}"}
        except subprocess.TimeoutExpired:
            return {"error": f"pip install timed out for {package}"}
        except Exception as e:
            return {"error": f"pip install error: {e}"}

    def _run_shell(self, command, timeout=30):
        """Execute an arbitrary shell command and return output."""
        try:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True, timeout=timeout
            )
            return {
                "status": "ok",
                "returncode": result.returncode,
                "stdout": result.stdout[-1000:],
                "stderr": result.stderr[-500:],
            }
        except subprocess.TimeoutExpired:
            return {"error": f"Command timed out ({timeout}s)"}
        except Exception as e:
            return {"error": f"Shell error: {e}"}

    def process(self, input_data):
        action = input_data.get("action", "")

        if action == "get_volume":
            return self._get_volume()
        elif action == "set_volume":
            return self._set_volume(input_data.get("level", 50))
        elif action == "volume_up":
            return self._volume_up(input_data.get("step", 10))
        elif action == "volume_down":
            return self._volume_down(input_data.get("step", 10))
        elif action == "mute":
            return self._mute()
        elif action == "unmute":
            return self._unmute()
        elif action == "screenshot":
            return self._screenshot(input_data.get("path", "memory/screenshot.png"))
        elif action == "clipboard_read":
            return self._clipboard_read()
        elif action == "clipboard_write":
            return self._clipboard_write(input_data.get("text", ""))
        elif action == "lock":
            return self._lock_screen()
        elif action == "shutdown":
            return self._shutdown(input_data.get("confirm", False))
        elif action == "restart":
            return self._restart(input_data.get("confirm", False))
        elif action == "sleep":
            return self._sleep()
        elif action == "open_url":
            return self._open_url(input_data.get("url", ""))
        elif action == "pip_install":
            return self._pip_install(
                input_data.get("package", ""),
                upgrade=input_data.get("upgrade", False)
            )
        elif action == "run_shell":
            return self._run_shell(
                input_data.get("command", ""),
                timeout=input_data.get("timeout", 30)
            )
        else:
            return {"error": f"Unknown action: {action}. Use: get_volume, set_volume, volume_up, volume_down, mute, unmute, screenshot, clipboard_read, clipboard_write, lock, shutdown, restart, sleep, open_url, pip_install, run_shell"}
