from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from latency_debug import Timer

log = logging.getLogger("llm_tools")

# ─── DB path (same as the rest of the system) ────────────────────────────────
import os
DB_PATH = Path(os.environ.get("GHOST_DB", "ghost.db"))

# ─── Client ──────────────────────────────────────────────────────────────────

SERVICE_MANAGER_URL = "http://127.0.0.1:8080"


class ServiceManagerClient:
    def __init__(self, base_url: str = SERVICE_MANAGER_URL, timeout: int = 70):
        self.base_url = base_url.rstrip("/")
        self.timeout  = timeout

    def status(self) -> dict:
        return requests.get(f"{self.base_url}/status", timeout=5).json()

    def get_data(self, service: str) -> dict:
        """Return cached data without re-fetching."""
        r = requests.get(f"{self.base_url}/data/{service}", timeout=5)
        r.raise_for_status()
        return r.json()

    def run_service(self, service: str) -> dict:
        """Trigger a fresh fetch and return the result."""
        with Timer(f"http_run_service:{service}"):
            r = requests.post(f"{self.base_url}/run/{service}", timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def spotify(self, intent: str, query: str = "") -> dict:
        payload = {"intent": intent, "query": query}
        with Timer(f"http_spotify:{intent}"):
            r = requests.post(f"{self.base_url}/spotify", json=payload, timeout=15)
        r.raise_for_status()
        return r.json()


_client = ServiceManagerClient()


# ─── Tool definitions ─────────────────────────────────────────────────────────
#
# Ollama's chat-with-tools API expects the OpenAI envelope:
#     {"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}
# A flat {"name": ..., ...} entry is parsed but the model never sees the name
# — Ollama returns tool_calls with `function.name = ""`, which is what made
# the `_infer_tool_name` keyword fallback in llm_pipeline.py necessary.
# With the wrapped form below, Granite returns the real name and the
# inference path becomes a redundant safety net.

def _fn(name: str, description: str, parameters: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": parameters,
        },
    }


_EMPTY_PARAMS = {"type": "object", "properties": {}, "required": []}


SERVICE_MANAGER_TOOLS: list[dict[str, Any]] = [
    _fn(
        "get_weather",
        "Fetch the current weather. Returns a voice-ready summary plus raw data. "
        "Use when the user asks about weather, temperature, or what to wear.",
        _EMPTY_PARAMS,
    ),
    _fn(
        "get_emails",
        "Fetch recent emails from the inbox. Returns a count of unread messages "
        "and brief summaries. Use when the user asks about email or messages.",
        _EMPTY_PARAMS,
    ),
    _fn(
        "get_calendar",
        "Fetch today's calendar events. Returns a voice-ready summary and event list. "
        "Use when the user asks what's on today, about appointments, or their schedule.",
        _EMPTY_PARAMS,
    ),
    _fn(
        "get_sms",
        "Call this tool whenever the user asks to read, check, fetch, or "
        "hear their SMS / text messages / texts / unread messages. "
        "Do NOT answer conversationally first — invoke the tool immediately "
        "and use its result. Example triggers: 'can you read my sms', "
        "'check my messages', 'any new texts', 'read my texts to me'.",
        _EMPTY_PARAMS,
    ),
    _fn(
        "spotify",
        "Control Spotify playback or search for music. "
        "Use for any music-related request: playing songs, pausing, skipping, "
        "adjusting volume, checking what's playing, managing playlists, etc.",
        {
            "type": "object",
            "properties": {
                "intent": {
                    "type": "string",
                    "enum": [
                        "play", "pause", "next", "previous", "volume",
                        "now_playing", "favourites", "save", "playlist",
                        "recent", "similar", "queue", "repeat", "shuffle", "restart",
                    ],
                    "description": "The playback action to perform.",
                },
                "query": {
                    "type": "string",
                    "description": (
                        "For 'play': song/artist name. "
                        "For 'volume': number 0-100. "
                        "For 'playlist': playlist name. "
                        "Leave empty for pause/next/previous/now_playing/favourites."
                    ),
                    "default": "",
                },
            },
            "required": ["intent"],
        },
    ),
    _fn(
        "log_activity",
        "Log that the user has completed a daily activity. Use when the user "
        "says they've done something like 'I just had breakfast', 'I've taken "
        "my medication', 'I went for a walk', 'I'm going to bed', etc. "
        "Do NOT use this for general conversation — only when the user "
        "clearly states they have done or are doing a specific routine activity.",
        {
            "type": "object",
            "properties": {
                "activity_name": {
                    "type": "string",
                    "enum": [
                        "wake up", "breakfast", "medication", "walk",
                        "lunch", "dinner", "bedtime", "chess", "read", "call",
                    ],
                    "description": "The activity the user completed.",
                },
                "sentiment": {
                    "type": "string",
                    "enum": ["positive", "neutral", "low"],
                    "description": (
                        "How the user seems to feel about it. "
                        "Default to 'neutral' if unclear."
                    ),
                },
            },
            "required": ["activity_name"],
        },
    ),
]


# ─── Dispatcher ───────────────────────────────────────────────────────────────

def handle_tool_call(name: str, args: dict[str, Any]) -> str:
    """
    Dispatch a parsed LLM tool call to the Service Manager and return
    a JSON string ready to feed back to the LLM as the tool result.

    Always fetches fresh data — never relies on cache — since Granite 4.0
    via Ollama doesn't reliably pass through the refresh argument.
    """
    try:
        if name == "get_weather":
            result = _client.run_service("weather")

        elif name == "get_emails":
            result = _client.run_service("email")

        elif name == "get_calendar":
            result = _client.run_service("calendar")

        elif name == "get_sms":
            result = _client.run_service("sms")

        elif name == "spotify":
            result = _client.spotify(
                intent=args.get("intent", "now_playing"),
                query=args.get("query", ""),
            )

        elif name == "log_activity":
            result = _handle_log_activity(args)

        else:
            result = {"error": f"Unknown tool: {name}"}

    except requests.exceptions.ConnectionError:
        result = {
            "error": "service_manager_offline",
            "message": "The local service manager is not running. "
                       "Start it with: python service_manager.py",
        }
    except Exception as exc:
        result = {"error": str(exc)}

    payload = json.dumps(result)
    log.info(f"[debug] tool_result for {name}: {len(payload)} chars going back to LLM")
    return payload


# ─── Activity logging handler ─────────────────────────────────────────────────

def _handle_log_activity(args: dict) -> dict:
    """
    Log a confirmed activity to ghost.db.
    Called when Granite detects the user mentioning they did something.

    Granite 4.0 often sends wrong argument keys (e.g. 'activity' instead of
    'activity_name', or puts the whole phrase as a value). We extract the
    real activity name by fuzzy-matching against known activities.
    """
    KNOWN_ACTIVITIES = [
        "wake up", "breakfast", "medication", "walk",
        "lunch", "dinner", "bedtime", "chess", "read", "call",
    ]

    # Try the correct key first, then common wrong keys, then any value
    raw = (args.get("activity_name")
           or args.get("activity")
           or args.get("name")
           or " ".join(str(v) for v in args.values())
           or "")
    raw = raw.lower().strip()

    # Match against known activity names
    activity_name = None
    for known in KNOWN_ACTIVITIES:
        if known in raw:
            activity_name = known
            break

    if not activity_name:
        log.warning("could not extract activity from args=%s", args)
        return {"error": f"Could not identify activity from: {raw}"}

    sentiment = args.get("sentiment", "neutral")
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")

    try:
        # Look up the activity
        row = conn.execute(
            "SELECT id FROM activities WHERE name = ?", (activity_name,)
        ).fetchone()
        if not row:
            conn.close()
            return {"error": f"Unknown activity: {activity_name}"}
        activity_id = row["id"]

        local_now = datetime.now()
        current_minute = local_now.hour * 60 + local_now.minute
        day_of_week = local_now.weekday()

        # Find today's prompt for this activity (if scheduler already created one)
        today_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_start_iso = today_start.strftime("%Y-%m-%dT%H:%M:%S.%fZ")

        prompt = conn.execute("""
            SELECT ap.id FROM activity_prompts ap
             WHERE ap.activity_id = ? AND ap.prompted_at >= ?
               AND NOT EXISTS (
                   SELECT 1 FROM activity_responses ar WHERE ar.prompt_id = ap.id
               )
             ORDER BY ap.prompted_at DESC LIMIT 1
        """, (activity_id, today_start_iso)).fetchone()

        if prompt:
            prompt_id = prompt["id"]
        else:
            # No prompt exists yet — create one (activity was done before scheduler asked)
            # Get expected_minute from routine_template if available
            tmpl = conn.execute("""
                SELECT expected_minute FROM routine_template
                 WHERE activity_id = ? AND day_of_week = ? AND active = 1
            """, (activity_id, day_of_week)).fetchone()
            expected_minute = tmpl["expected_minute"] if tmpl else current_minute

            cur = conn.execute("""
                INSERT INTO activity_prompts (activity_id, expected_minute, prompted_at)
                VALUES (?, ?, ?)
            """, (activity_id, expected_minute, now_iso))
            prompt_id = cur.lastrowid

        # Record the confirmed response
        conn.execute("""
            INSERT OR IGNORE INTO activity_responses
                (prompt_id, responded_at, status, sentiment, raw_reply)
            VALUES (?, ?, 'confirmed', ?, ?)
        """, (prompt_id, now_iso, sentiment, f"voice:{activity_name}"))

        # Update wellbeing state — user just interacted
        conn.execute("""
            UPDATE wellbeing_state
               SET last_interaction_at = ?,
                   consecutive_misses = 0,
                   updated_at = ?
             WHERE id = 1
        """, (now_iso, now_iso))

        # Log to events table (for baseline learning)
        conn.execute("""
            INSERT INTO events (source, payload)
            VALUES ('interaction', ?)
        """, (json.dumps({"kind": "activity_confirmed", "activity": activity_name}),))

        conn.commit()
        log.info("logged activity %r via voice (prompt_id=%d, sentiment=%s)",
                 activity_name, prompt_id, sentiment)
        return {
            "status": "logged",
            "activity": activity_name,
            "message": f"{activity_name} has been recorded.",
        }

    except Exception as exc:
        log.exception("failed to log activity %r", activity_name)
        return {"error": str(exc)}
    finally:
        conn.close()


# ─── Quick smoke-test ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    tool  = sys.argv[1] if len(sys.argv) > 1 else "get_weather"
    query = sys.argv[2] if len(sys.argv) > 2 else ""

    args_map: dict[str, dict] = {
        "get_weather":  {},
        "get_emails":   {},
        "get_calendar": {},
        "get_sms":      {},
        "spotify":      {"intent": "now_playing", "query": query},
    }

    print(handle_tool_call(tool, args_map.get(tool, {})))
