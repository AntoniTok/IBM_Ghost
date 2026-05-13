"""
Calendar Service for IBM Ghost - Elderly Companion Device
Fetches Google Calendar events and saves them to calendar.json
Run manually or via cron: 0 6 * * * /path/to/venv/bin/python /path/to/fetch_calendar.py
"""

import json, sys, logging
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Configuration
CALENDAR_ID  = "primary"
TIMEZONE     = "Europe/London"
RANGE        = "today"       # "today" or "next_7_days"
OUTPUT       = Path("calendar.json")
MAX_RESULTS  = 20

# Internals
SCOPES     = ["https://www.googleapis.com/auth/calendar.readonly"]
HERE       = Path(__file__).parent
CREDS_FILE = HERE / "credentials.json"
TOKEN_FILE = HERE / "token.json"

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)


def auth():
    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDS_FILE.exists():
                sys.exit("✗ credentials.json not found. See README.")
            creds = InstalledAppFlow.from_client_secrets_file(
                CREDS_FILE, SCOPES
            ).run_local_server(port=0)
        TOKEN_FILE.write_text(creds.to_json())
    return creds


def time_range():
    tz    = ZoneInfo(TIMEZONE)
    start = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    end   = start + timedelta(days=7 if RANGE == "next_7_days" else 1)
    return start.isoformat(), end.isoformat()


def format_event(e, tz):
    title     = e.get("summary", "Untitled event")
    location  = e.get("location", "")
    raw_start = e["start"].get("dateTime") or e["start"].get("date")
    all_day   = "dateTime" not in e["start"]

    if all_day:
        time_str = "all day"
    else:
        time_str = datetime.fromisoformat(raw_start).astimezone(tz).strftime("%I:%M %p").lstrip("0")

    sentence = f"{title} at {time_str}"
    if location:
        sentence += f", at {location}"

    return {
        "title":    title,
        "start":    raw_start,
        "location": location,
        "content":  sentence + ".",
    }


def main():
    creds        = auth()
    svc          = build("calendar", "v3", credentials=creds)
    t_min, t_max = time_range()
    tz           = ZoneInfo(TIMEZONE)

    items = svc.events().list(
        calendarId=CALENDAR_ID,
        timeMin=t_min, timeMax=t_max,
        maxResults=MAX_RESULTS,
        singleEvents=True, orderBy="startTime",
    ).execute().get("items", [])

    events = [
        format_event(e, tz)
        for e in items if e.get("status") != "cancelled"
    ]

    if events:
        content = "Today you have: " + " Then, ".join(e["content"] for e in events)
    else:
        content = "You have no events today."

    output = {
        "service":      "calendar",
        "status":       "success",
        "generated_at": datetime.now(tz).isoformat(),
        "data": {
            "content": content,
            "events":  events,
        },
    }

    OUTPUT.write_text(json.dumps(output, indent=2))
    log.info(f"✓ {len(events)} event(s) → {OUTPUT}")


if __name__ == "__main__":
    main()
