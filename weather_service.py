"""
Weather Service for Granite Ghost - Elderly Companion Device
Uses Open-Meteo API (free, no API key needed)
Fetches weather once, writes to file, and exits.
"""
import json
import requests
from datetime import datetime, timezone

from config import WEATHER_LOCATION, WEATHER_OUTPUT

WEATHER_CODES = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "foggy", 48: "foggy", 51: "light drizzle", 53: "drizzle",
    55: "heavy drizzle", 61: "light rain", 63: "rain", 65: "heavy rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
    80: "light showers", 81: "showers", 82: "heavy showers",
    85: "light snow showers", 86: "snow showers", 95: "thunderstorm",
    96: "thunderstorm with hail", 99: "thunderstorm with hail"
}


def get_coordinates(location):
    url = "https://geocoding-api.open-meteo.com/v1/search"
    params = {"name": location, "count": 1, "language": "en", "format": "json"}
    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()
    data = response.json()
    if not data.get("results"):
        raise ValueError(f"Location '{location}' not found")
    result = data["results"][0]
    return {
        "lat": result["latitude"],
        "lon": result["longitude"],
        "name": result["name"],
        "country": result.get("country", "")
    }


def get_weather(location):
    coords = get_coordinates(location)
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": coords["lat"],
        "longitude": coords["lon"],
        "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
        "timezone": "auto"
    }
    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()
    current = response.json()["current"]
    return {
        "location": coords["name"],
        "country": coords["country"],
        "temperature": current["temperature_2m"],
        "humidity": current["relative_humidity_2m"],
        "wind_speed": current["wind_speed_10m"],
        "condition": WEATHER_CODES.get(current.get("weather_code", 0), "unknown")
    }


def format_description(data):
    location_str = f"{data['location']}, {data['country']}" if data['country'] else data['location']
    return (
        f"The weather in {location_str} is currently {round(data['temperature'])} degrees Celsius. "
        f"The conditions are {data['condition']}, with {round(data['humidity'])} percent humidity "
        f"and wind speeds of {round(data['wind_speed'])} kilometers per hour."
    )


if __name__ == "__main__":
    data = get_weather(WEATHER_LOCATION)

    output = {
        "service": "weather",
        "status": "success",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": {
            "content": format_description(data),
            "raw_data": {
                "location": data["location"],
                "country": data["country"],
                "temperature": round(data["temperature"], 1),
                "condition": data["condition"],
                "humidity": round(data["humidity"]),
                "wind_speed": round(data["wind_speed"], 1)
            }
        },
        "error": None
    }

    WEATHER_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    WEATHER_OUTPUT.write_text(json.dumps(output, indent=2))
    print(f"Weather written to {WEATHER_OUTPUT}")
