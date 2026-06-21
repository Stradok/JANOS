from tools.base import BaseTool


class MediaTool(BaseTool):
    name = "media"
    description = "Control media playback. Params: action (play|pause|next|prev|volume)"

    async def execute(self, action: str = "", **kwargs) -> str:
        try:
            import subprocess
            playerctl = subprocess.run(
                ["which", "playerctl"], capture_output=True, text=True
            )
            if playerctl.returncode != 0:
                return "Media control requires playerctl (install: sudo apt install playerctl)"

            commands = {
                "play": "play-pause",
                "pause": "pause",
                "next": "next",
                "prev": "previous",
                "stop": "stop",
                "volume": "volume 0.5",
            }
            cmd = commands.get(action, action)
            result = subprocess.run(
                ["playerctl", *cmd.split()],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                return f"Media {action}: ok"
            return f"Media {action}: {result.stderr.strip() or 'no active player'}"
        except FileNotFoundError:
            return "Media control requires playerctl"
        except Exception as e:
            return f"Media error: {e}"
