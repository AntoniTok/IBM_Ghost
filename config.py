# config.py
# =========
# Central configuration for all Granite Ghost services.
# Every script reads from here — edit this file only.

from pathlib import Path

# ─── Paths ───────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
LOG_FILE = BASE_DIR / "service_manager.log"

# Output files (where each service writes its JSON)
WEATHER_OUTPUT  = DATA_DIR / "weather.json"
EMAIL_OUTPUT    = DATA_DIR / "emails.json"
CALENDAR_OUTPUT = DATA_DIR / "calendar.json"
SMS_OUTPUT      = DATA_DIR / "sms_unread.json"

# Google service account key (used by fetch_calendar.py)
SERVICE_ACCOUNT_FILE = BASE_DIR / "service_account.json"

# Spotify token store (written by onboard.py, read by spotify_handler.py)
SPOTIFY_TOKEN_STORE = Path.home() / ".granite_ghost" / "spotify_tokens.json"

# ─── Schedule ─────────────────────────────────────────────────────────────────

MORNING_HOUR     = 7
MORNING_MINUTE   = 30
AFTERNOON_HOUR   = 14
AFTERNOON_MINUTE = 0

# ─── Weather ──────────────────────────────────────────────────────────────────

WEATHER_LOCATION = "London"   # city name passed to Open-Meteo

# ─── Email (IMAP) ─────────────────────────────────────────────────────────────

EMAIL_ADDRESS       = "antoni.tokarski7@gmail.com"
EMAIL_PASSWORD      = "iesf mhlm hyjz jmop"   # Gmail App Password (16 chars)
IMAP_SERVER         = "imap.gmail.com"
IMAP_PORT           = 993
EMAIL_MAX_FETCH     = 5
EMAIL_LOOKBACK_DAYS = 7   # 0 = no date filter

# ─── Calendar ─────────────────────────────────────────────────────────────────

CALENDAR_ID       = "antoni.tokarski7@gmail.com"
CALENDAR_TIMEZONE = "Europe/London"
CALENDAR_RANGE    = "today"   # "today" or "next_7_days"
CALENDAR_MAX      = 20

# ─── SMS / Bluetooth ──────────────────────────────────────────────────────────

BT_DEVICE_ADDRESS = "6C:AC:C2:11:D9:C8"   # ← replace with your phone's BT MAC
SMS_MARK_READ     = False                  # mark messages as read after fetching?

# ─── Spotify ──────────────────────────────────────────────────────────────────

SPOTIFY_CLIENT_ID     = "eeb838b780824e3787703122897d1b86"
SPOTIFY_CLIENT_SECRET = "712607c8364b4f0eac14264d941265b9"
SPOTIFY_REDIRECT_URI  = "http://127.0.0.1:8765/callback"
SPOTIFY_DEVICE_NAME   = "Granite Ghost"   # must match LIBRESPOT_NAME in raspotify

# ─── API server ───────────────────────────────────────────────────────────────

API_HOST = "127.0.0.1"
API_PORT = 8080

# ─── Text-to-speech (Piper) ───────────────────────────────────────────────────

PIPER_MODEL          = str(BASE_DIR / "en_GB-alan-medium.onnx")
PIPER_CONFIG         = str(BASE_DIR / "en_GB-alan-medium.onnx.json")
PIPER_LENGTH_SCALE   = 1.15    # > 1.0 = slower; 1.1–1.3 comfortable for elderly
PIPER_SENTENCE_PAUSE = 0.25    # seconds of silence between sentences

# ─── Speech-to-text (Vosk) ────────────────────────────────────────────────────

VOSK_MODEL_PATH        = str(BASE_DIR / "models" / "vosk-model-small-en-us-0.15")
WAKE_WORDS             = ["hello ghost", "hey ghost", "ghost"]
STT_SAMPLE_RATE        = 16000
STT_CHUNK              = 4000
STT_SILENCE_TIMEOUT    = 1.8   # seconds of silence before ending utterance
STT_MAX_RECORD_SECS    = 15    # hard cap on recording length
STT_MIN_UTTERANCE_SECS = 0.4   # ignore blips shorter than this

# ─── GPIO ─────────────────────────────────────────────────────────────────────

SENSOR_GPIO_PIN = 17           # BCM pin for PIR/button trigger; set None to disable
GPIO_BOUNCETIME_MS = 200

# ─── LLM (Ollama) ─────────────────────────────────────────────────────────────

OLLAMA_HOST       = "http://127.0.0.1:11434"   # Ollama's default local address
OLLAMA_MODEL      = "jewelzufo/unsloth_granite-4.0-h-350m-GGUF:Q4_K_XL"  # exactly as shown in ollama list
OLLAMA_TIMEOUT    = 180                         # seconds — Pi 350M Granite needs headroom for cold-start
