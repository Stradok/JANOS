# modules/spotify_module.py
import subprocess
import time
import os
import shutil
from .base import ModuleBase

try:
    import pyautogui
    PYAUTOGUI_AVAILABLE = True
except Exception:
    PYAUTOGUI_AVAILABLE = False


class SpotifyModule(ModuleBase):
    """Control Spotify — open, search, play, pause, skip, volume, playlists.
    Uses keyboard shortcuts via pyautogui + Linux native control."""

    def __init__(self):
        super().__init__("spotify")

    def _is_spotify_running(self):
        try:
            result = subprocess.run(["pgrep", "-f", "spotify"], capture_output=True, text=True, timeout=5)
            return result.returncode == 0
        except (FileNotFoundError, Exception):
            return False

    def _open_spotify(self):
        if self._is_spotify_running():
            return self._focus_spotify()
        try:
            spotify = shutil.which("spotify")
            if spotify:
                subprocess.Popen([spotify])
                time.sleep(3)
                return {"status": "ok", "message": "Spotify opened"}
            try:
                subprocess.Popen(["xdg-open", "spotify:"])
                time.sleep(3)
                return {"status": "ok", "message": "Spotify opened via protocol"}
            except Exception:
                pass
            # flatpak fallback
            try:
                subprocess.Popen(["flatpak", "run", "com.spotify.Client"])
                time.sleep(3)
                return {"status": "ok", "message": "Spotify opened via flatpak"}
            except Exception:
                pass
            # snap fallback
            try:
                subprocess.Popen(["snap", "run", "spotify"])
                time.sleep(3)
                return {"status": "ok", "message": "Spotify opened via snap"}
            except Exception:
                pass
            return {"error": "Could not find Spotify. Install via: snap install spotify or apt install spotify-client"}
        except Exception as e:
            return {"error": str(e)}

    def _focus_spotify(self):
        try:
            subprocess.run(["xdotool", "search", "--name", "Spotify", "windowactivate"], capture_output=True, timeout=5)
            return {"status": "ok", "message": "Spotify focused"}
        except FileNotFoundError:
            return {"error": "xdotool not installed"}
        except Exception:
            return {"error": "Spotify window not found"}

    def _play_pause(self):
        """Toggle play/pause using media key."""
        if not PYAUTOGUI_AVAILABLE:
            return {"error": "pyautogui not installed"}
        pyautogui.press("playpause")
        return {"status": "ok", "message": "Toggled play/pause"}

    def _next_track(self):
        if not PYAUTOGUI_AVAILABLE:
            return {"error": "pyautogui not installed"}
        pyautogui.press("nexttrack")
        return {"status": "ok", "message": "Skipped to next track"}

    def _prev_track(self):
        if not PYAUTOGUI_AVAILABLE:
            return {"error": "pyautogui not installed"}
        pyautogui.press("prevtrack")
        return {"status": "ok", "message": "Previous track"}

    def _volume_up(self):
        if not PYAUTOGUI_AVAILABLE:
            return {"error": "pyautogui not installed"}
        pyautogui.press("volumeup")
        pyautogui.press("volumeup")
        pyautogui.press("volumeup")
        return {"status": "ok", "message": "Volume up"}

    def _volume_down(self):
        if not PYAUTOGUI_AVAILABLE:
            return {"error": "pyautogui not installed"}
        pyautogui.press("volumedown")
        pyautogui.press("volumedown")
        pyautogui.press("volumedown")
        return {"status": "ok", "message": "Volume down"}

    def _search_and_play(self, query):
        """Open Spotify, use search to find and play something."""
        # ensure Spotify is open and focused
        if not self._is_spotify_running():
            result = self._open_spotify()
            if "error" in result:
                return result
            time.sleep(2)

        self._focus_spotify()
        time.sleep(0.5)

        if not PYAUTOGUI_AVAILABLE:
            return {"error": "pyautogui not installed"}

        # Ctrl+L to focus search bar in Spotify (or Ctrl+K in newer versions)
        pyautogui.hotkey("ctrl", "l")
        time.sleep(0.5)

        # clear existing search and type new query
        pyautogui.hotkey("ctrl", "a")
        time.sleep(0.2)
        pyautogui.typewrite(query, interval=0.03) if query.isascii() else pyautogui.write(query)
        time.sleep(1)

        # press Enter to search, then Enter again to play top result
        pyautogui.press("enter")
        time.sleep(2)

        return {"status": "ok", "message": f"Searched for '{query}' in Spotify"}

    def _play_uri(self, uri):
        """Open a Spotify URI directly (e.g., spotify:playlist:xxxxx)."""
        try:
            subprocess.Popen(["xdg-open", uri])
            return {"status": "ok", "message": f"Opening {uri}"}
        except Exception as e:
            return {"error": str(e)}

    def process(self, input_data):
        action = input_data.get("action", "play_pause")
        query = input_data.get("query", "")
        uri = input_data.get("uri", "")

        if action == "open":
            return self._open_spotify()
        elif action in ("play_pause", "play", "pause"):
            return self._play_pause()
        elif action in ("next", "next_track"):
            return self._next_track()
        elif action in ("previous", "prev_track", "prev"):
            return self._prev_track()
        elif action == "volume_up":
            return self._volume_up()
        elif action == "volume_down":
            return self._volume_down()
        elif action in ("search", "search_and_play"):
            if not query:
                return {"error": "Missing 'query' to search for in Spotify"}
            return self._search_and_play(query)
        elif action == "play_uri":
            if not uri:
                return {"error": "Missing 'uri' (e.g. spotify:playlist:xxxxx)"}
            return self._play_uri(uri)
        elif action == "focus":
            return self._focus_spotify()
        else:
            return {"error": f"Unknown action: {action}. Use: open, play, pause, next, previous, volume_up, volume_down, search, search_and_play, play_uri, focus"}
