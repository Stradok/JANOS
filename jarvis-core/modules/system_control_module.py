# modules/system_control_module.py
import subprocess
import os
from .base import ModuleBase

try:
    import pyautogui
    PYAUTOGUI_AVAILABLE = True
except ImportError:
    PYAUTOGUI_AVAILABLE = False

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

    def _get_volume_interface(self):
        if not PYCAW_AVAILABLE:
            return None, {"error": "pycaw not installed. Run: pip install pycaw comtypes"}
        try:
            devices = AudioUtilities.GetSpeakers()
            # newer pycaw: use .EndpointVolume property directly
            if hasattr(devices, 'EndpointVolume'):
                return devices.EndpointVolume, None
            # older pycaw: use COM Activate
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume = cast(interface, POINTER(IAudioEndpointVolume))
            return volume, None
        except Exception as e:
            return None, {"error": f"Failed to get audio interface: {str(e)}"}

    def _get_volume(self):
        vol, err = self._get_volume_interface()
        if err:
            return err
        current = vol.GetMasterVolumeLevelScalar()
        muted = vol.GetMute()
        return {"status": "ok", "volume": round(current * 100), "muted": bool(muted)}

    def _set_volume(self, level):
        vol, err = self._get_volume_interface()
        if err:
            return err
        level = max(0, min(100, level))
        vol.SetMasterVolumeLevelScalar(level / 100.0, None)
        return {"status": "ok", "volume": level}

    def _mute(self):
        vol, err = self._get_volume_interface()
        if err:
            return err
        vol.SetMute(1, None)
        return {"status": "ok", "muted": True}

    def _unmute(self):
        vol, err = self._get_volume_interface()
        if err:
            return err
        vol.SetMute(0, None)
        return {"status": "ok", "muted": False}

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
            subprocess.Popen(["rundll32.exe", "user32.dll,LockWorkStation"])
            return {"status": "ok", "message": "Screen locked"}
        except Exception as e:
            return {"error": str(e)}

    def _shutdown(self, confirm=False):
        if not confirm:
            return {"status": "waiting_confirmation", "message": "Are you sure you want to SHUT DOWN? Send again with confirm=true"}
        subprocess.Popen(["shutdown", "/s", "/t", "5"])
        return {"status": "ok", "message": "Shutting down in 5 seconds..."}

    def _restart(self, confirm=False):
        if not confirm:
            return {"status": "waiting_confirmation", "message": "Are you sure you want to RESTART? Send again with confirm=true"}
        subprocess.Popen(["shutdown", "/r", "/t", "5"])
        return {"status": "ok", "message": "Restarting in 5 seconds..."}

    def _sleep(self):
        try:
            subprocess.Popen(["rundll32.exe", "powrprof.dll,SetSuspendState", "0", "1", "0"])
            return {"status": "ok", "message": "Going to sleep"}
        except Exception as e:
            return {"error": str(e)}

    def _open_url(self, url):
        try:
            os.startfile(url)
            return {"status": "ok", "message": f"Opened {url} in default browser"}
        except Exception as e:
            return {"error": str(e)}

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
        else:
            return {"error": f"Unknown action: {action}. Use: get_volume, set_volume, volume_up, volume_down, mute, unmute, screenshot, clipboard_read, clipboard_write, lock, shutdown, restart, sleep, open_url"}
