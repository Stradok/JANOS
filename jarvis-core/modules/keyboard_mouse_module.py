# modules/keyboard_mouse_module.py
import time
from .base import ModuleBase

try:
    import pyautogui
    pyautogui.FAILSAFE = True  # move mouse to corner to abort
    pyautogui.PAUSE = 0.1
    PYAUTOGUI_AVAILABLE = True
except Exception:
    PYAUTOGUI_AVAILABLE = False


class KeyboardMouseModule(ModuleBase):
    """Low-level keyboard and mouse control using pyautogui."""

    def __init__(self):
        super().__init__("keyboard_mouse")

    def _check(self):
        if not PYAUTOGUI_AVAILABLE:
            return {"error": "pyautogui not installed. Run: pip install pyautogui"}
        return None

    def _type_text(self, text, interval=0.02):
        err = self._check()
        if err:
            return err
        pyautogui.typewrite(text, interval=interval) if text.isascii() else pyautogui.write(text)
        return {"status": "ok", "typed": text}

    def _hotkey(self, keys):
        """Press a hotkey combination like ['ctrl', 'c'] or ['alt', 'tab']."""
        err = self._check()
        if err:
            return err
        pyautogui.hotkey(*keys)
        return {"status": "ok", "hotkey": "+".join(keys)}

    def _press(self, key):
        err = self._check()
        if err:
            return err
        pyautogui.press(key)
        return {"status": "ok", "pressed": key}

    def _click(self, x=None, y=None, button="left", clicks=1):
        err = self._check()
        if err:
            return err
        if x is not None and y is not None:
            pyautogui.click(x, y, clicks=clicks, button=button)
        else:
            pyautogui.click(clicks=clicks, button=button)
        return {"status": "ok", "clicked": {"x": x, "y": y, "button": button, "clicks": clicks}}

    def _move(self, x, y, duration=0.3):
        err = self._check()
        if err:
            return err
        pyautogui.moveTo(x, y, duration=duration)
        return {"status": "ok", "moved_to": {"x": x, "y": y}}

    def _scroll(self, amount, x=None, y=None):
        err = self._check()
        if err:
            return err
        pyautogui.scroll(amount, x, y)
        return {"status": "ok", "scrolled": amount}

    def _screenshot(self, path="memory/screenshot.png"):
        err = self._check()
        if err:
            return err
        import os
        os.makedirs(os.path.dirname(path), exist_ok=True)
        img = pyautogui.screenshot()
        img.save(path)
        return {"status": "ok", "saved": path}

    def _get_mouse_pos(self):
        err = self._check()
        if err:
            return err
        pos = pyautogui.position()
        return {"status": "ok", "x": pos.x, "y": pos.y}

    def _get_screen_size(self):
        err = self._check()
        if err:
            return err
        size = pyautogui.size()
        return {"status": "ok", "width": size.width, "height": size.height}

    def process(self, input_data):
        action = input_data.get("action", "")

        if action == "type":
            text = input_data.get("text", "")
            interval = input_data.get("interval", 0.02)
            return self._type_text(text, interval)

        elif action == "hotkey":
            keys = input_data.get("keys", [])
            if not keys:
                return {"error": "Missing 'keys' list, e.g. ['ctrl', 'c']"}
            return self._hotkey(keys)

        elif action == "press":
            key = input_data.get("key", "")
            if not key:
                return {"error": "Missing 'key' to press"}
            return self._press(key)

        elif action == "click":
            x = input_data.get("x")
            y = input_data.get("y")
            button = input_data.get("button", "left")
            clicks = input_data.get("clicks", 1)
            return self._click(x, y, button, clicks)

        elif action == "move":
            x = input_data.get("x", 0)
            y = input_data.get("y", 0)
            duration = input_data.get("duration", 0.3)
            return self._move(x, y, duration)

        elif action == "scroll":
            amount = input_data.get("amount", 0)
            return self._scroll(amount, input_data.get("x"), input_data.get("y"))

        elif action == "screenshot":
            path = input_data.get("path", "memory/screenshot.png")
            return self._screenshot(path)

        elif action == "mouse_position":
            return self._get_mouse_pos()

        elif action == "screen_size":
            return self._get_screen_size()

        else:
            return {"error": f"Unknown action: {action}. Use: type, hotkey, press, click, move, scroll, screenshot, mouse_position, screen_size"}
