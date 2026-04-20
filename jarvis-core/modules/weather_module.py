import requests
from .base import ModuleBase

class WeatherModule(ModuleBase):
    def __init__(self):
        super().__init__("weather")

    WEATHER_CODES = {
        0: "☀️ Clear sky",
        1: "🌤 Mostly clear",
        2: "⛅ Partly cloudy",
        3: "☁️ Overcast",
        45: "🌫 Fog",
        48: "🌫 Fog with frost",
        51: "🌦 Light drizzle",
        61: "🌧 Light rain",
        63: "🌧 Moderate rain",
        65: "🌧 Heavy rain",
        71: "❄️ Light snow",
        73: "❄️ Moderate snow",
        75: "❄️ Heavy snow",
        95: "⛈ Thunderstorm",
        99: "🌩 Severe thunderstorm"
    }

    def get_coordinates(self, city):
        """Convert city name → latitude & longitude using Open-Meteo Geocoding API"""
        try:
            url = f"https://geocoding-api.open-meteo.com/v1/search?name={city}&count=1"
            response = requests.get(url)
            data = response.json()
            if "results" in data and len(data["results"]) > 0:
                result = data["results"][0]
                return result["latitude"], result["longitude"]
            return None, None
        except Exception as e:
            print("Geocoding error:", e)
            return None, None

    def process(self, input_data):
        city = input_data.get("city")
        lat = input_data.get("lat")
        lon = input_data.get("lon")

        if city and (lat is None or lon is None):
            lat, lon = self.get_coordinates(city)

        if lat is None or lon is None:
            return {"error": "Please provide either 'city' or 'lat' & 'lon'."}

        try:
            # Request both current weather and forecast (next 12 hours, hourly)
            url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true&hourly=temperature_2m,windspeed_10m,weathercode"
            response = requests.get(url)
            data = response.json()

            if "current_weather" not in data:
                return {"error": "Could not fetch weather."}

            weather = data["current_weather"]
            description = self.WEATHER_CODES.get(weather["weathercode"], "Unknown")

            current_report = (
                f"Right now in {city}: {description}, "
                f"🌡 {weather['temperature']}°C, "
                f"💨 wind {weather['windspeed']} km/h."
            )

            # Forecast: look ahead 6 hours for change
            forecast_text = "The weather is expected to stay about the same."
            if "hourly" in data:
                temps = data["hourly"]["temperature_2m"][:6]
                winds = data["hourly"]["windspeed_10m"][:6]
                codes = data["hourly"]["weathercode"][:6]

                if max(temps) - min(temps) >= 3:
                    forecast_text = "🌡 Temperature will change soon."
                if max(winds) > weather["windspeed"] + 5:
                    forecast_text += " 💨 A stronger breeze is expected."
                if any(code != weather["weathercode"] for code in codes):
                    forecast_text += " 🌦 Weather conditions may shift."

            return {
                "status": "ok",
                "city": city,
                "summary": current_report,
                "forecast": forecast_text,
                "raw": {
                    "temperature": weather["temperature"],
                    "windspeed": weather["windspeed"],
                    "weathercode": weather["weathercode"]
                }
            }
        except Exception as e:
            return {"error": str(e)}
