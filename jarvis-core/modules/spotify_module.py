# modules/spotify_module.py
import subprocess
import time
import os
from .base import ModuleBase

try:
    import pyautogui
    PYAUTOGUI_AVAILABLE = True
except ImportError:
    PYAUTOGUI_AVAILABLE = False

try:
    import pygetwindow as gw
    GW_AVAILABLE = True
except ImportError:
    GW_AVAILABLE = False


class SpotifyModule(ModuleBase):
    """Control Spotify — open, search, play, pause, skip, volume, playlists.
    Uses a combo of app launching + keyboard shortcuts for reliable control."""

    def __init__(self):
        super().__init__("spotify")

    def _is_spotify_running(self):
        if not GW_AVAILABLE:
            return False
        windows = gw.getWindowsWithTitle("Spotify")
        return len(windows) > 0

    def _open_spotify(self):
        if self._is_spotify_running():
            return self._focus_spotify()
        try:
            # try Windows Store version first
            subprocess.Popen(["explorer", r"shell:AppsFolder\SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify"])
            time.sleep(3)
            if self._is_spotify_running():
                return {"status": "ok", "message": "Spotify opened"}
            # try standard exe path
            appdata = os.environ.get("APPDATA", "")
            spotify_path = os.path.join(appdata, "Spotify", "Spotify.exe")
            if os.path.exists(spotify_path):
                subprocess.Popen([spotify_path])
                time.sleep(3)
                return {"status": "ok", "message": "Spotify opened"}
            # try spotify: URI protocol (registered by Spotify installer)
            try:
                os.startfile("spotify:")
                time.sleep(3)
                return {"status": "ok", "message": "Spotify opened via protocol"}
            except Exception:
                pass
            # try start menu search
            try:
                subprocess.Popen(["start", "spotify:"], shell=True)
                time.sleep(2)
                return {"status": "ok", "message": "Spotify opened via start"}
            except Exception:
                pass
            return {"error": "Could not find Spotify. Is it installed?"}
        except Exception as e:
            return {"error": str(e)}

    def _focus_spotify(self):
        if not GW_AVAILABLE:
            return {"error": "pygetwindow not installed"}
        windows = gw.getWindowsWithTitle("Spotify")
        if windows:
            try:
                windows[0].activate()
                return {"status": "ok", "message": "Spotify focused"}
            except Exception:
                pass
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
            os.startfile(uri)
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
