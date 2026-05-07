"""
Weather Service for IBM Ghost - Elderly Companion Device
Uses Open-Meteo API (free, no API key needed)
"""
import os
import requests
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration
PORT = int(os.getenv("WEATHER_SERVICE_PORT", "5001"))
DEFAULT_LOCATION = os.getenv("DEFAULT_LOCATION", "London")
CACHE_TTL = int(os.getenv("CACHE_TTL", "1800"))  # 30 minutes

# Simple in-memory cache
_cache = {}

# Create FastAPI app
app = FastAPI(title="Weather Service")

# Weather code descriptions (WMO Weather interpretation codes)
WEATHER_CODES = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "foggy", 48: "foggy", 51: "light drizzle", 53: "drizzle", 
    55: "heavy drizzle", 61: "light rain", 63: "rain", 65: "heavy rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
    80: "light showers", 81: "showers", 82: "heavy showers",
    85: "light snow showers", 86: "snow showers", 95: "thunderstorm",
    96: "thunderstorm with hail", 99: "thunderstorm with hail"
}


def get_coordinates(location: str):
    """Get latitude and longitude for a location"""
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


def get_weather(location: str):
    """Fetch weather from Open-Meteo API"""
    
    # Check cache first
    if location in _cache:
        data, timestamp = _cache[location]
        if datetime.now() - timestamp < timedelta(seconds=CACHE_TTL):
            return data
    
    # Get coordinates for the location
    coords = get_coordinates(location)
    
    # Fetch weather data
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": coords["lat"],
        "longitude": coords["lon"],
        "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
        "timezone": "auto"
    }
    
    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()
    weather_data = response.json()
    
    # Combine location and weather data
    current = weather_data["current"]
    result = {
        "location": coords["name"],
        "country": coords["country"],
        "temperature": current["temperature_2m"],
        "humidity": current["relative_humidity_2m"],
        "wind_speed": current["wind_speed_10m"],
        "condition": WEATHER_CODES.get(current.get("weather_code", 0), "unknown")
    }
    
    # Cache the result
    _cache[location] = (result, datetime.now())
    
    return result


def format_weather_description(weather_data):
    """Create a human-readable weather description"""
    location = weather_data["location"]
    country = weather_data["country"]
    temp = round(weather_data["temperature"])
    condition = weather_data["condition"]
    humidity = round(weather_data["humidity"])
    wind_speed = round(weather_data["wind_speed"])
    
    location_str = f"{location}, {country}" if country else location
    
    return (
        f"The weather in {location_str} is currently {temp} degrees Celsius. "
        f"The conditions are {condition}, with {humidity} percent humidity "
        f"and wind speeds of {wind_speed} kilometers per hour."
    )


@app.get("/")
def root():
    """Service information"""
    return {
        "service": "weather",
        "status": "running",
        "provider": "Open-Meteo (free, no API key needed)",
        "endpoints": ["/health", "/weather"]
    }


@app.get("/health")
def health():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "weather",
        "provider": "Open-Meteo"
    }


@app.get("/weather")
def weather(location: str = None):
    """
    Get current weather for a location.
    
    Args:
        location: City name (e.g., "London", "Paris", "New York")
                 If not provided, uses DEFAULT_LOCATION from config
    
    Returns:
        Standardized weather response with human-readable content
    """
    
    if not location:
        location = DEFAULT_LOCATION
    
    try:
        # Get weather data
        data = get_weather(location)
        
        # Create standardized response
        return {
            "service": "weather",
            "status": "success",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "data": {
                "content": format_weather_description(data),
                "raw_data": {
                    "location": data["location"],
                    "country": data["country"],
                    "temperature": round(data["temperature"], 1),
                    "condition": data["condition"],
                    "humidity": round(data["humidity"]),
                    "wind_speed": round(data["wind_speed"], 1)
                }
            },
            "metadata": {
                "cache_ttl": CACHE_TTL,
                "priority": "normal",
                "provider": "Open-Meteo"
            },
            "error": None
        }
        
    except ValueError as e:
        # Location not found
        raise HTTPException(status_code=404, detail=str(e))
    
    except requests.exceptions.RequestException as e:
        # API connection error
        raise HTTPException(status_code=503, detail=f"Weather service unavailable: {str(e)}")
    
    except Exception as e:
        # Unexpected error
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    
    print("=" * 60)
    print("🌤️  IBM Ghost - Weather Service")
    print("=" * 60)
    print(f"🌍 Provider: Open-Meteo (free, no API key needed)")
    print(f"🔌 Port: {PORT}")
    print(f"📍 Default location: {DEFAULT_LOCATION}")
    print(f"⏱️  Cache TTL: {CACHE_TTL} seconds")
    print(f"📚 API Docs: http://localhost:{PORT}/docs")
    print("=" * 60)
    print()
    
    uvicorn.run(app, host="0.0.0.0", port=PORT)

# Made with Bob
