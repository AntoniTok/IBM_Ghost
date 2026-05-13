# fetch_calendar.py

Part of IBM Ghost. Fetches today's Google Calendar events → `calendar.json` every morning via cron.

## Files in this repo

```
fetch_calendar.py   ← the script
requirements.txt    ← pip deps
README.md
```

Files on the Pi only (gitignored — never commit these):
```
credentials.json    ← downloaded from Google Cloud Console
token.json          ← auto-created on first run
calendar.json       ← output, regenerated daily
```

---

## Google Cloud setup (one-time, ~5 min)

1. [console.cloud.google.com](https://console.cloud.google.com) → **New Project**
2. **APIs & Services → Library** → **Google Calendar API** → Enable
3. **APIs & Services → Credentials → + Create Credentials → OAuth client ID**
   - Consent screen if prompted: External, fill in your email, save
   - Application type: **Desktop app** → Create
4. Download the JSON → rename to `credentials.json` → copy to this folder on the Pi

---

## Pi setup

```bash
cd ~/your-project
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 fetch_calendar.py   # opens browser for Google login on first run
```

After login, `token.json` and `calendar.json` are created. Won't prompt again.

---

## Schedule (cron at 06:00)

```bash
crontab -e
```

Add (update path to match your project folder):
```
0 0 * * * /home/pi/your-project/venv/bin/python /home/pi/your-project/fetch_calendar.py >> /home/pi/your-project/calendar.log 2>&1
```

---

## Output format

`data.content` is a ready-to-speak sentence, matching the weather service pattern:

```json
{
  "service": "calendar",
  "status": "success",
  "generated_at": "2026-05-13T06:00:00+01:00",
  "data": {
    "content": "Today you have: Lecture at 9:00 AM, at Room 201. Then, Doctor at 2:00 PM.",
    "events": [
      { "title": "Lecture", "start": "2026-05-13T09:00:00+01:00", "location": "Room 201", "content": "Lecture at 9:00 AM, at Room 201." },
      { "title": "Doctor",  "start": "2026-05-13T14:00:00+01:00", "location": "",         "content": "Doctor at 2:00 PM."              }
    ]
  }
}
```

Read it in another script:
```python
import json
data = json.load(open("calendar.json"))
print(data["data"]["content"])
# → "Today you have: Lecture at 9:00 AM, at Room 201. Then, Doctor at 2:00 PM."
```

---

## Troubleshooting

| Error | Fix |
|-------|-----|
| `credentials.json not found` | Download from Google Cloud Console (step 3 above) |
| `Token refresh failed` | Delete `token.json`, re-run to login again |
| `403 forbidden` | Google Calendar API not enabled in your Cloud project |
| `No module named google` | Run `source venv/bin/activate` first |
