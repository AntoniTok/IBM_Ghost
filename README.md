# IBM Ghost - Weather Service

Weather service for the IBM Ghost elderly companion device. Provides current weather information with voice-friendly summaries.

## Features

- ✅ Current weather conditions
- ✅ Temperature, humidity, wind speed
- ✅ Voice-friendly descriptions
- ✅ Standardized response format
- ✅ 30-minute caching
- ✅ Free API (Open-Meteo, no key needed)
- ✅ Location-based queries

## Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Run
```bash
python weather_service.py
```

### 3. Test
```bash
# Get weather for default location (London)
curl http://localhost:5001/weather/

# Get weather for specific location
curl "http://localhost:5001/weather/?location=Paris"
```

## Response Format

```json
{
  "service": "weather",
  "status": "success",
  "timestamp": "2026-05-14T12:47:24.498Z",
  "data": {
    "content": "The weather in London is currently 15 degrees Celsius. The conditions are partly cloudy, with 65 percent humidity and wind speeds of 12 kilometers per hour.",
    "raw_data": {
      "location": "London",
      "country": "UK",
      "temperature": 15.0,
      "condition": "partly cloudy",
      "humidity": 65,
      "wind_speed": 12.5
    }
  },
  "metadata": {
    "cache_ttl": 1800,
    "priority": "normal",
    "provider": "Open-Meteo"
  },
  "error": null
}
```

## Configuration

Optional environment variables (create `.env` file):
```bash
WEATHER_SERVICE_PORT=5001
DEFAULT_LOCATION=London
CACHE_TTL=1800
```

## API Endpoints

- `GET /weather/` - Get current weather
  - Query param: `location` (optional, defaults to DEFAULT_LOCATION)
- `GET /weather/health` - Health check

## Files

- `weather_service.py` - Main service implementation
- `requirements.txt` - Python dependencies

## Provider

Uses [Open-Meteo](https://open-meteo.com/) - a free weather API with no API key required.

## Branch

This is the `feature-weather` branch. See other branches for:
- `feature-music` - Spotify integration
- `feature-email` - Email service
- `feature-calendar` - Calendar integration