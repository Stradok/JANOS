import os

import requests

from core.config import Config
from tools.base import BaseTool


class WeatherTool(BaseTool):
    name = "weather"
    description = "Get weather for a city. Params: city (str)"

    async def execute(self, city: str = "London", **kwargs) -> str:
        api_key = os.getenv("OPENWEATHER_API_KEY") or Config().get("api_keys.openweather", "")
        if not api_key:
            return "Weather unavailable: no OPENWEATHER_API_KEY set"
        url = "https://api.openweathermap.org/data/2.5/weather"
        params = {"q": city, "appid": api_key, "units": "metric"}
        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            d = resp.json()
            temp = d["main"]["temp"]
            desc = d["weather"][0]["description"]
            return f"{city}: {temp}°C, {desc}"
        except Exception as e:
            return f"Weather error: {e}"
