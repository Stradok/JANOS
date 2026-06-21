from datetime import datetime, timezone

from tools.base import BaseTool


class TimeTool(BaseTool):
    name = "time"
    description = "Get current date/time. Params: timezone (str, optional)"

    async def execute(self, **kwargs) -> str:
        now = datetime.now(tz=timezone.utc)
        return now.strftime("%Y-%m-%d %H:%M:%S UTC")
