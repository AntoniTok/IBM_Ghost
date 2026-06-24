"""
Calendar Service for Granite Ghost - Elderly Companion Device
Fetches Google Calendar events and saves them to calendar.json
"""
import json
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from google.oauth2 import service_account
from googleapiclient.discovery import build

from config import (
    CALENDAR_ID, CALENDAR_TIMEZONE, CALENDAR_RANGE,
    CALENDAR_MAX, CALENDAR_OUTPUT, SERVICE_ACCOUNT_FILE,
)

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)


def auth():
    if not SERVICE_ACCOUNT_FILE.exists():
        raise FileNotFoundError(f"service_account.json not found at {SERVICE_ACCOUNT_FILE}")
    return service_account.Credentials.from_service_account_file(
        str(SERVICE_ACCOUNT_FILE), scopes=SCOPES
    )


def time_range():
    tz    = ZoneInfo(CALENDAR_TIMEZONE)
    start = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    end   = start + timedelta(days=7 if CALENDAR_RANGE == "next_7_days" else 1)
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
    tz           = ZoneInfo(CALENDAR_TIMEZONE)

    items = svc.events().list(
        calendarId=CALENDAR_ID,
        timeMin=t_min, timeMax=t_max,
        maxResults=CALENDAR_MAX,
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

    CALENDAR_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    CALENDAR_OUTPUT.write_text(json.dumps(output, indent=2))
    log.info(f"✓ {len(events)} event(s) → {CALENDAR_OUTPUT}")


if __name__ == "__main__":
    main()
