from datetime import datetime
from .base import ModuleBase

class TimeModule(ModuleBase):
    def __init__(self):
        super().__init__("time")

    def process(self, input_data):
        # Optional: user can ask for "date", "time" or "both"
        mode = input_data.get("mode", "both")

        now = datetime.now()
        result = {}

        if mode in ("time", "both"):
            result["time"] = now.strftime("%H:%M:%S")

        if mode in ("date", "both"):
            result["date"] = now.strftime("%Y-%m-%d")

        return {
            "status": "ok",
            "mode": mode,
            "output": result
        }
