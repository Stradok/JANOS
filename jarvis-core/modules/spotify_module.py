# modules/spotify_module.py
"""
Spotify control for Linux.
Priority chain for each operation:
  1. playerctl (if installed)  — cleanest MPRIS2 interface
  2. dbus-send                 — available on all D-Bus-enabled desktops (no extra install)
  3. xdotool                   — keyboard injection (if installed)
  4. pyautogui                 — fallback keyboard injection
  5. xdg-open spotify: URI     — opens app to a specific search/track (always available)
"""
import subprocess
import time
import os
import shutil
from urllib.parse import quote_plus
from .base import ModuleBase

try:
    import pyautogui
    PYAUTOGUI_AVAILABLE = True
except Exception:
    PYAUTOGUI_AVAILABLE = False

_SPOTIFY_MPRIS = "org.mpris.MediaPlayer2.spotify"
_MPRIS_OBJ     = "/org/mpris/MediaPlayer2"
_MPRIS_IFACE   = "org.mpris.MediaPlayer2.Player"


class SpotifyModule(ModuleBase):
    """Control Spotify — open, search, play, pause, skip, volume, playlists.
    Uses D-Bus MPRIS2 / playerctl / xdotool / spotify: URIs — no web browser needed."""

    def __init__(self):
        super().__init__("spotify")

    # ── Availability checks ────────────────────────────────────────────

    def _is_spotify_running(self):
        try:
            r = subprocess.run(["pgrep", "-f", "spotify"], capture_output=True, text=True, timeout=5)
            return r.returncode == 0
        except (FileNotFoundError, Exception):
            return False

    def _has(self, cmd):
        return shutil.which(cmd) is not None

    # ── Open / Focus ───────────────────────────────────────────────────

    def _open_spotify(self):
        if self._is_spotify_running():
            return self._focus_spotify()
        for launcher in [
            [shutil.which("spotify")] if shutil.which("spotify") else None,
            ["snap", "run", "spotify"],
            ["flatpak", "run", "com.spotify.Client"],
            ["xdg-open", "spotify:"],
        ]:
            if launcher and launcher[0]:
                try:
                    subprocess.Popen(launcher)
                    time.sleep(4)
                    return {"status": "ok", "message": f"Spotify opened"}
                except (FileNotFoundError, Exception):
                    continue
        return {"error": "Could not open Spotify. Install: snap install spotify"}

    def _focus_spotify(self):
        try:
            subprocess.run(["wmctrl", "-a", "Spotify"], capture_output=True, timeout=5)
            return {"status": "ok", "message": "Spotify focused via wmctrl"}
        except (FileNotFoundError, Exception):
            pass
        if self._has("xdotool"):
            try:
                r = subprocess.run(["xdotool", "search", "--name", "Spotify"],
                                   capture_output=True, text=True, timeout=5)
                if r.returncode == 0 and r.stdout.strip():
                    wid = r.stdout.strip().split("\n")[-1]
                    subprocess.run(["xdotool", "windowactivate", "--sync", wid], timeout=5)
                    return {"status": "ok", "message": "Spotify focused via xdotool"}
            except Exception:
                pass
        return {"status": "ok", "message": "Spotify is running"}

    # ── D-Bus MPRIS2 control (dbus-send) ──────────────────────────────

    def _dbus_player_cmd(self, method):
        """Send a void MPRIS2 player command via dbus-send."""
        try:
            r = subprocess.run([
                "dbus-send", "--print-reply",
                f"--dest={_SPOTIFY_MPRIS}",
                _MPRIS_OBJ,
                f"{_MPRIS_IFACE}.{method}",
            ], capture_output=True, text=True, timeout=5)
            return r.returncode == 0, r.stderr.strip()
        except FileNotFoundError:
            return False, "dbus-send not found"
        except Exception as e:
            return False, str(e)

    def _dbus_metadata(self):
        """Return current track info from MPRIS2 metadata."""
        try:
            r = subprocess.run([
                "dbus-send", "--print-reply",
                f"--dest={_SPOTIFY_MPRIS}",
                _MPRIS_OBJ,
                "org.freedesktop.DBus.Properties.Get",
                "string:org.mpris.MediaPlayer2.Player",
                "string:Metadata",
            ], capture_output=True, text=True, timeout=5)
            if r.returncode == 0 and "xesam:title" in r.stdout:
                lines = r.stdout.splitlines()
                title = artist = ""
                for i, line in enumerate(lines):
                    if "xesam:title" in line and i + 1 < len(lines):
                        title = lines[i + 1].strip().strip('"')
                    if "xesam:artist" in line and i + 1 < len(lines):
                        artist = lines[i + 1].strip().strip('"[]')
                return f"{artist} - {title}".strip(" -") or "Unknown"
        except Exception:
            pass
        return ""

    # ── playerctl ─────────────────────────────────────────────────────

    def _playerctl(self, *args):
        """Run a playerctl command for Spotify. Returns (ok, output)."""
        try:
            r = subprocess.run(
                ["playerctl", "--player=spotify"] + list(args),
                capture_output=True, text=True, timeout=5
            )
            return r.returncode == 0, r.stdout.strip()
        except FileNotFoundError:
            return False, "playerctl not installed"
        except Exception as e:
            return False, str(e)

    # ── xdotool window typing ─────────────────────────────────────────

    def _get_spotify_wid(self):
        try:
            r = subprocess.run(["xdotool", "search", "--name", "Spotify"],
                               capture_output=True, text=True, timeout=5)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip().split("\n")[-1]
        except Exception:
            pass
        return None

    def _xdotool_search(self, query):
        wid = self._get_spotify_wid()
        if not wid:
            return {"error": "Spotify window not found for xdotool"}
        try:
            subprocess.run(["xdotool", "windowactivate", "--sync", wid], timeout=5)
            time.sleep(0.4)
            subprocess.run(["xdotool", "key", "--window", wid, "ctrl+k"], timeout=5)
            time.sleep(0.6)
            subprocess.run(["xdotool", "key", "--window", wid, "ctrl+a"], timeout=5)
            time.sleep(0.15)
            subprocess.run(["xdotool", "type", "--window", wid,
                            "--clearmodifiers", "--delay", "40", query], timeout=15)
            time.sleep(0.9)
            subprocess.run(["xdotool", "key", "--window", wid, "Return"], timeout=5)
            time.sleep(2)
            subprocess.run(["xdotool", "key", "--window", wid, "Tab", "Return"], timeout=5)
            return {"status": "ok", "message": f"Searched and playing '{query}' in Spotify app"}
        except FileNotFoundError:
            return {"error": "xdotool not installed — sudo apt install xdotool"}
        except Exception as e:
            return {"error": f"xdotool search failed: {e}"}

    # ── Search and play ────────────────────────────────────────────────

    def _search_and_play(self, query):
        """Open Spotify app and search/play a track — never uses the web browser."""
        if not self._is_spotify_running():
            result = self._open_spotify()
            if "error" in result:
                return result
            time.sleep(3)
        self._focus_spotify()
        time.sleep(0.5)

        # Option 1: xdotool keyboard injection (if installed)
        if self._has("xdotool"):
            result = self._xdotool_search(query)
            if result.get("status") == "ok":
                return result

        # Option 2: pyautogui keyboard injection (if installed)
        if PYAUTOGUI_AVAILABLE:
            try:
                pyautogui.hotkey("ctrl", "k")
                time.sleep(0.5)
                pyautogui.hotkey("ctrl", "a")
                time.sleep(0.2)
                if query.isascii():
                    pyautogui.typewrite(query, interval=0.03)
                else:
                    pyautogui.write(query)
                time.sleep(1)
                pyautogui.press("enter")
                time.sleep(2)
                return {"status": "ok", "message": f"Searched for '{query}' in Spotify"}
            except Exception as e:
                return {"error": f"pyautogui search failed: {e}"}

        # Option 3: Spotify search URI — opens search directly in the app
        encoded = quote_plus(query)
        uri = f"spotify:search:{encoded}"
        try:
            subprocess.Popen(["xdg-open", uri])
            return {"status": "ok", "message": f"Opened search for '{query}' in Spotify app via URI"}
        except Exception as e:
            return {"error": f"All search methods failed. Last error: {e}. Install xdotool: sudo apt install xdotool"}

    # ── Playback controls ──────────────────────────────────────────────

    def _play_pause(self):
        # 1. playerctl
        ok, _ = self._playerctl("play-pause")
        if ok:
            return {"status": "ok", "message": "Toggled play/pause via playerctl"}
        # 2. dbus-send
        ok, err = self._dbus_player_cmd("PlayPause")
        if ok:
            return {"status": "ok", "message": "Toggled play/pause via D-Bus"}
        # 3. pyautogui
        if PYAUTOGUI_AVAILABLE:
            pyautogui.press("playpause")
            return {"status": "ok", "message": "Toggled play/pause via media key"}
        # 4. xdotool media key
        if self._has("xdotool"):
            try:
                subprocess.run(["xdotool", "key", "XF86AudioPlay"], timeout=5)
                return {"status": "ok", "message": "Sent play/pause key"}
            except Exception:
                pass
        return {"error": f"Could not control Spotify. Install playerctl: sudo apt install playerctl"}

    def _next_track(self):
        ok, _ = self._playerctl("next")
        if ok:
            return {"status": "ok", "message": "Next track via playerctl"}
        ok, _ = self._dbus_player_cmd("Next")
        if ok:
            return {"status": "ok", "message": "Next track via D-Bus"}
        if PYAUTOGUI_AVAILABLE:
            pyautogui.press("nexttrack")
            return {"status": "ok", "message": "Next track"}
        if self._has("xdotool"):
            subprocess.run(["xdotool", "key", "XF86AudioNext"], timeout=5)
            return {"status": "ok", "message": "Next track via media key"}
        return {"error": "Install playerctl: sudo apt install playerctl"}

    def _prev_track(self):
        ok, _ = self._playerctl("previous")
        if ok:
            return {"status": "ok", "message": "Previous track via playerctl"}
        ok, _ = self._dbus_player_cmd("Previous")
        if ok:
            return {"status": "ok", "message": "Previous track via D-Bus"}
        if PYAUTOGUI_AVAILABLE:
            pyautogui.press("prevtrack")
            return {"status": "ok", "message": "Previous track"}
        if self._has("xdotool"):
            subprocess.run(["xdotool", "key", "XF86AudioPrev"], timeout=5)
            return {"status": "ok", "message": "Previous track via media key"}
        return {"error": "Install playerctl: sudo apt install playerctl"}

    def _volume_up(self):
        ok, _ = self._playerctl("volume", "0.1+")
        if ok:
            return {"status": "ok", "message": "Volume up via playerctl"}
        if PYAUTOGUI_AVAILABLE:
            for _ in range(3):
                pyautogui.press("volumeup")
            return {"status": "ok", "message": "Volume up"}
        return {"error": "Install playerctl: sudo apt install playerctl"}

    def _volume_down(self):
        ok, _ = self._playerctl("volume", "0.1-")
        if ok:
            return {"status": "ok", "message": "Volume down via playerctl"}
        if PYAUTOGUI_AVAILABLE:
            for _ in range(3):
                pyautogui.press("volumedown")
            return {"status": "ok", "message": "Volume down"}
        return {"error": "Install playerctl: sudo apt install playerctl"}

    def _now_playing(self):
        ok, track = self._playerctl("metadata", "--format", "{{ artist }} - {{ title }}")
        if ok and track:
            return {"status": "ok", "now_playing": track}
        track = self._dbus_metadata()
        if track:
            return {"status": "ok", "now_playing": track}
        return {"status": "ok", "now_playing": "Spotify is running (install playerctl for track info: sudo apt install playerctl)"}

    # ── URI / direct open ─────────────────────────────────────────────

    def _play_uri(self, uri):
        """Open a Spotify URI directly in the installed app (spotify:playlist:xxxx, spotify:search:query)."""
        try:
            subprocess.Popen(["xdg-open", uri])
            return {"status": "ok", "message": f"Opened Spotify URI: {uri}"}
        except Exception as e:
            return {"error": str(e)}

    # ── Module entry point ─────────────────────────────────────────────

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
                return {"error": "Missing 'query' to search in Spotify"}
            return self._search_and_play(query)
        elif action == "play_uri":
            if not uri:
                return {"error": "Missing 'uri' (e.g. spotify:playlist:xxxxx or spotify:search:query)"}
            return self._play_uri(uri)
        elif action == "focus":
            return self._focus_spotify()
        elif action == "now_playing":
            return self._now_playing()
        else:
            return {"error": f"Unknown action: {action}. Use: open, play, pause, next, previous, volume_up, volume_down, search, search_and_play, play_uri, focus, now_playing"}
