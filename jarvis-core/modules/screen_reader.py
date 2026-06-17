# modules/screen_reader.py
"""
ScreenReader — Gives JAN agents eyes.
Takes screenshots and reads what's on screen via OCR.
Used by all agents in the think → act → observe → decide loop.
"""
import os
import json
import time
import base64
import shutil
import requests
from pathlib import Path
from .base import ModuleBase

try:
    import pyautogui
    PYAUTOGUI_AVAILABLE = True
except Exception:
    PYAUTOGUI_AVAILABLE = False

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

# Try pytesseract first (lightweight)
try:
    import pytesseract
    _tess_path = shutil.which("tesseract")
    if _tess_path:
        pytesseract.pytesseract.tesseract_cmd = _tess_path
    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False

# Fallback: easyocr (heavier but no external binary needed)
try:
    import easyocr
    EASYOCR_AVAILABLE = True
except ImportError:
    EASYOCR_AVAILABLE = False


class ScreenReader(ModuleBase):
    """Screenshot + OCR — the observation layer for all agents."""

    OLLAMA_URL = "http://localhost:11434/api/chat"
    SCREENSHOT_DIR = Path("memory/screenshots")

    def __init__(self):
        super().__init__("screen_reader")
        self.SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        self._easyocr_reader = None

    # ── Screenshot ──────────────────────────────────────────────────

    def take_screenshot(self, region=None, path=None):
        """Capture the screen (or a region). Returns the saved file path."""
        if not PYAUTOGUI_AVAILABLE:
            return None, "pyautogui not installed"
        try:
            if region:
                img = pyautogui.screenshot(region=region)
            else:
                img = pyautogui.screenshot()
            if not path:
                path = str(self.SCREENSHOT_DIR / f"screen_{int(time.time())}.png")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            img.save(path)
            return path, None
        except Exception as e:
            return None, str(e)

    # ── OCR ─────────────────────────────────────────────────────────

    def ocr_image(self, image_path):
        """Extract text from an image using available OCR engine."""
        if TESSERACT_AVAILABLE:
            return self._ocr_tesseract(image_path)
        if EASYOCR_AVAILABLE:
            return self._ocr_easyocr(image_path)
        return None, "No OCR engine available. Install pytesseract or easyocr."

    def _ocr_tesseract(self, image_path):
        try:
            if PIL_AVAILABLE:
                img = Image.open(image_path)
            else:
                img = image_path
            text = pytesseract.image_to_string(img)
            return text.strip(), None
        except Exception as e:
            return None, f"Tesseract OCR failed: {e}"

    def _ocr_easyocr(self, image_path):
        try:
            if self._easyocr_reader is None:
                self._easyocr_reader = easyocr.Reader(['en'], gpu=False)
            results = self._easyocr_reader.readtext(image_path)
            text = "\n".join([r[1] for r in results])
            return text.strip(), None
        except Exception as e:
            return None, f"EasyOCR failed: {e}"

    # ── Vision Model (Ollama) ──────────────────────────────────────

    def describe_screen(self, image_path, prompt=None, model="llava"):
        """Use an Ollama vision model to describe what's on screen."""
        if not prompt:
            prompt = (
                "Describe what you see on this computer screen. "
                "List all visible UI elements: buttons, text fields, links, menus, "
                "and any text content. Be specific about positions (top, center, bottom, left, right). "
                "If there are clickable elements, describe their labels and approximate positions."
            )
        try:
            with open(image_path, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode("utf-8")

            resp = requests.post(self.OLLAMA_URL, json={
                "model": model,
                "messages": [{
                    "role": "user",
                    "content": prompt,
                    "images": [img_b64]
                }],
                "stream": False,
                "options": {"temperature": 0.3, "num_predict": 1024}
            }, timeout=120)

            if resp.status_code == 200:
                data = resp.json()
                description = data.get("message", {}).get("content", "")
                return description.strip(), None
            return None, f"Vision model returned {resp.status_code}"
        except requests.ConnectionError:
            return None, "Ollama not running"
        except Exception as e:
            return None, f"Vision model error: {e}"

    # ── Combined Observation ───────────────────────────────────────

    def observe(self, use_vision=False, vision_model="llava", vision_prompt=None, region=None):
        """
        Full observation: screenshot → OCR (+ optional vision model).
        Returns a dict with screenshot path, OCR text, and optional description.
        This is the main method agents call after performing an action.
        """
        # Take screenshot
        screenshot_path, err = self.take_screenshot(region=region)
        if err:
            return {"error": f"Screenshot failed: {err}", "ocr_text": "", "screenshot": None}

        # OCR
        ocr_text, ocr_err = self.ocr_image(screenshot_path)
        if ocr_err:
            ocr_text = ""

        result = {
            "screenshot": screenshot_path,
            "ocr_text": ocr_text or "",
            "timestamp": time.time(),
        }

        # Optional: vision model for rich description
        if use_vision:
            description, vis_err = self.describe_screen(
                screenshot_path, prompt=vision_prompt, model=vision_model
            )
            result["vision_description"] = description or ""
            if vis_err:
                result["vision_error"] = vis_err

        return result

    # ── Find UI Element (OCR-based) ────────────────────────────────

    def find_text_on_screen(self, target_text, image_path=None):
        """
        Find the position of specific text on screen using OCR with bounding boxes.
        Returns approximate center coordinates of the text.
        """
        if not image_path:
            image_path, err = self.take_screenshot()
            if err:
                return None, err

        if TESSERACT_AVAILABLE and PIL_AVAILABLE:
            return self._find_text_tesseract(target_text, image_path)
        if EASYOCR_AVAILABLE:
            return self._find_text_easyocr(target_text, image_path)
        return None, "No OCR engine available"

    def _find_text_tesseract(self, target_text, image_path):
        try:
            img = Image.open(image_path)
            data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
            target_lower = target_text.lower()
            matches = []
            for i, text in enumerate(data['text']):
                if text.strip() and target_lower in text.lower():
                    x = data['left'][i] + data['width'][i] // 2
                    y = data['top'][i] + data['height'][i] // 2
                    matches.append({
                        "text": text,
                        "x": x, "y": y,
                        "width": data['width'][i],
                        "height": data['height'][i],
                        "confidence": data['conf'][i]
                    })
            if matches:
                best = max(matches, key=lambda m: m['confidence'])
                return best, None
            return None, f"Text '{target_text}' not found on screen"
        except Exception as e:
            return None, str(e)

    def _find_text_easyocr(self, target_text, image_path):
        try:
            if self._easyocr_reader is None:
                self._easyocr_reader = easyocr.Reader(['en'], gpu=False)
            results = self._easyocr_reader.readtext(image_path)
            target_lower = target_text.lower()
            for bbox, text, conf in results:
                if target_lower in text.lower():
                    # bbox is list of 4 corners, get center
                    xs = [p[0] for p in bbox]
                    ys = [p[1] for p in bbox]
                    cx = int(sum(xs) / len(xs))
                    cy = int(sum(ys) / len(ys))
                    return {
                        "text": text, "x": cx, "y": cy,
                        "confidence": conf
                    }, None
            return None, f"Text '{target_text}' not found on screen"
        except Exception as e:
            return None, str(e)

    # ── Module Interface ───────────────────────────────────────────

    def process(self, input_data):
        action = input_data.get("action", "observe")

        if action == "observe":
            return self.observe(
                use_vision=input_data.get("use_vision", False),
                vision_model=input_data.get("vision_model", "llava"),
                vision_prompt=input_data.get("vision_prompt"),
                region=input_data.get("region"),
            )
        elif action == "screenshot":
            path, err = self.take_screenshot(
                region=input_data.get("region"),
                path=input_data.get("path"),
            )
            if err:
                return {"error": err}
            return {"status": "ok", "screenshot": path}

        elif action == "ocr":
            image_path = input_data.get("image_path")
            if not image_path:
                image_path, err = self.take_screenshot()
                if err:
                    return {"error": err}
            text, err = self.ocr_image(image_path)
            if err:
                return {"error": err}
            return {"status": "ok", "text": text}

        elif action == "find_text":
            target = input_data.get("text", "")
            if not target:
                return {"error": "Missing 'text' to find on screen"}
            result, err = self.find_text_on_screen(
                target, input_data.get("image_path")
            )
            if err:
                return {"error": err}
            return {"status": "ok", "match": result}

        elif action == "describe":
            image_path = input_data.get("image_path")
            if not image_path:
                image_path, err = self.take_screenshot()
                if err:
                    return {"error": err}
            desc, err = self.describe_screen(
                image_path,
                prompt=input_data.get("prompt"),
                model=input_data.get("model", "llava"),
            )
            if err:
                return {"error": err}
            return {"status": "ok", "description": desc}

        else:
            return {"error": f"Unknown action: {action}. Use: observe, screenshot, ocr, find_text, describe"}
