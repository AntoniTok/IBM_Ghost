#!/usr/bin/env python3
"""
queue_consumer.py
=================
Granite Ghost — closes the loop between scheduler.py and the voice stack.

What it does
------------
The scheduler ([scheduler.py]) writes rows into `utterance_queue` whenever
it decides something should be said (a medication reminder, an activity
prompt, a wellbeing check-in, an SMS summary…). Nothing currently reads
that queue, so the scheduler's decisions never reach the speaker.

This consumer is the missing reader. Each tick it:
  1. SELECTs the highest-priority utterance whose `deliver_after <= now`
     and `expires_at > now` and `delivered_at IS NULL`.
  2. Renders the named template into a spoken sentence using the row's
     `context_query`.
  3. Speaks it via Piper (`llm_tts_bridge.TTSBridge`).
  4. UPDATEs `delivered_at` so the row is not picked up again.

Run as a standalone process alongside main.py. They share the audio device
(serially — TTSBridge.play() is blocking) so they don't talk over each other
as long as both wait their turn.

CLI
---
    # Speak every pending utterance, then loop forever:
    python queue_consumer.py

    # Process one pending row, print what would be spoken, exit:
    python queue_consumer.py --once --simulate

    # On the Mac (no audio device): force simulate so it doesn't try to open Piper:
    SENTINEL_SIMULATE=1 python queue_consumer.py

Phase 2 (not in this file)
--------------------------
Capturing the user's reply via STT and writing it back into
`activity_responses` requires coordination with `stt_listener.on_utterance`
in `main.py` — that's a follow-up edit on the voice-loop side, not a queue
concern.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Config — kept simple; no dependency on the larger config.py so this can
# be tested on the Mac without pulling in Pi-specific paths.
# ---------------------------------------------------------------------------

DB_PATH = Path(os.environ.get("GHOST_DB", "ghost.db"))
POLL_SECONDS = float(os.environ.get("CONSUMER_POLL_SECONDS", "5"))
USER_NAME = os.environ.get("GHOST_USER_NAME", "Margaret")
SIMULATE = bool(int(os.environ.get("SENTINEL_SIMULATE", "0")))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
)
log = logging.getLogger("queue_consumer")


# ---------------------------------------------------------------------------
# DB helpers — connection is opened/closed per tick so SQLite WAL stays
# happy when other writers (scheduler, sentinel_api) touch the file.
# ---------------------------------------------------------------------------

def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


# ---------------------------------------------------------------------------
# Template renderers
#
# Each function takes the parsed `context_query` dict and returns a
# string ready for TTS. Keep them short — Piper sounds best on one or
# two sentences at a time, and the user shouldn't have to listen long.
# ---------------------------------------------------------------------------

def _greeting(ctx: dict) -> str:
    tod = ctx.get("time_of_day", "")
    name = USER_NAME if ctx.get("user_name") else ""
    parts = []
    if tod == "morning":
        parts.append("Good morning")
    elif tod == "afternoon":
        parts.append("Good afternoon")
    elif tod == "evening":
        parts.append("Good evening")
    if name:
        parts.append(name)
    return ", ".join(parts).strip(", ") if parts else ""


def render_activity_prompt(ctx: dict) -> str:
    activity = ctx.get("activity_name", "an activity")
    greeting = _greeting(ctx)
    if ctx.get("is_followup"):
        return (f"{greeting}, just checking back about {activity} — "
                f"have you had a chance yet?").lstrip(", ").strip()
    return (f"{greeting}, it's time for {activity}. "
            f"Have you done that yet?").lstrip(", ").strip()


def render_medication_reminder(ctx: dict) -> str:
    med = ctx.get("medication_name", "your medication")
    greeting = _greeting(ctx)
    return (f"{greeting}, a reminder to take {med}.").lstrip(", ").strip()


def render_appointment_reminder(ctx: dict) -> str:
    title = ctx.get("title", "an appointment")
    name = USER_NAME if ctx.get("user_name") else ""
    prefix = f"{name}, " if name else ""
    return f"{prefix}don't forget — you have {title} coming up."


def render_wellbeing_check_in(ctx: dict) -> str:
    greeting = _greeting(ctx)
    return (f"{greeting}, I haven't heard from you in a little while. "
            f"Are you doing okay?").lstrip(", ").strip()


def render_morning_briefing(ctx: dict) -> str:
    """Static MVP. Phase 2: call llm_pipeline.run() with cached data feeds
    to produce a one-paragraph summary (weather + calendar + email)."""
    greeting = _greeting(ctx) or f"Good morning, {USER_NAME}"
    return f"{greeting}. Here's your morning briefing — ask me anything."


def render_sms_summary(ctx: dict) -> str:
    n = len(ctx.get("sms_event_ids", []) or [])
    name = USER_NAME if ctx.get("user_name") else ""
    prefix = f"{name}, " if name else ""
    if n == 0:
        return f"{prefix}you have a new text message."
    if n == 1:
        return f"{prefix}you have one new text message."
    return f"{prefix}you have {n} new text messages."


def render_custom(ctx: dict) -> str:
    title = ctx.get("title", "a reminder")
    name = USER_NAME if ctx.get("user_name") else ""
    prefix = f"{name}, " if name else ""
    return f"{prefix}{title}."


TEMPLATES: dict[str, callable] = {
    "activity_prompt.txt":      render_activity_prompt,
    "medication_reminder.txt":  render_medication_reminder,
    "appointment_reminder.txt": render_appointment_reminder,
    "wellbeing_check_in.txt":   render_wellbeing_check_in,
    "morning_briefing.txt":     render_morning_briefing,
    "sms_summary.txt":          render_sms_summary,
    "custom.txt":               render_custom,
}


def render(template_name: str, context_query: str) -> Optional[str]:
    try:
        ctx = json.loads(context_query) if context_query else {}
    except (TypeError, ValueError):
        log.warning("could not parse context_query as JSON: %r", context_query)
        ctx = {}
    fn = TEMPLATES.get(template_name)
    if fn is None:
        log.warning("no renderer for template %r — skipping", template_name)
        return None
    try:
        text = fn(ctx).strip()
    except Exception:
        log.exception("renderer for %s failed", template_name)
        return None
    return text or None


# ---------------------------------------------------------------------------
# Voice output — lazy-imported so this file is importable on a Mac (no
# Piper / sounddevice) for testing the queue logic itself.
# ---------------------------------------------------------------------------

_tts = None


def _get_tts():
    global _tts
    if _tts is not None:
        return _tts
    from llm_tts_bridge import TTSBridge
    _tts = TTSBridge()
    return _tts


def speak(text: str, simulate: bool) -> None:
    if simulate:
        log.info("[simulate] would speak: %s", text)
        return
    tts = _get_tts()
    tts.speak(text)


# ---------------------------------------------------------------------------
# Queue tick
# ---------------------------------------------------------------------------

SELECT_NEXT = """
    SELECT id, priority, template_name, context_query, source_event_id,
           deliver_after, expires_at
      FROM utterance_queue
     WHERE delivered_at IS NULL
       AND deliver_after <= ?
       AND (expires_at IS NULL OR expires_at > ?)
     ORDER BY priority ASC, deliver_after ASC
     LIMIT 1
"""

MARK_DELIVERED = """
    UPDATE utterance_queue
       SET delivered_at = ?
     WHERE id = ?
"""

MARK_FAILED = """
    UPDATE utterance_queue
       SET delivered_at = 'failed'
     WHERE id = ?
"""


def tick_once(simulate: bool) -> bool:
    """Process at most one queued utterance. Returns True if it spoke one."""
    now = _iso_now()
    with _connect() as conn:
        row = conn.execute(SELECT_NEXT, (now, now)).fetchone()
        if row is None:
            return False
        log.info(
            "picked utterance id=%d priority=%d template=%s",
            row["id"], row["priority"], row["template_name"],
        )

    text = render(row["template_name"], row["context_query"])
    if text is None:
        with _connect() as conn:
            conn.execute(MARK_FAILED, (row["id"],))
        log.warning("marked utterance id=%d as failed (no renderable text)", row["id"])
        return True

    try:
        speak(text, simulate=simulate)
        delivered_at = _iso_now()
        with _connect() as conn:
            conn.execute(MARK_DELIVERED, (delivered_at, row["id"]))
        log.info("delivered utterance id=%d", row["id"])
    except Exception:
        log.exception("speak() failed for utterance id=%d", row["id"])
        with _connect() as conn:
            conn.execute(MARK_FAILED, (row["id"],))
    return True


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

_running = True


def _shutdown(signum, _frame):
    global _running
    log.info("signal %s — shutting down after current tick", signum)
    _running = False


def main() -> None:
    parser = argparse.ArgumentParser(description="Granite Ghost utterance queue consumer.")
    parser.add_argument("--once", action="store_true",
                        help="Process one row (if any) and exit.")
    parser.add_argument("--simulate", action="store_true",
                        help="Print spoken text instead of opening Piper / audio.")
    parser.add_argument("--poll", type=float, default=POLL_SECONDS,
                        help=f"Seconds between polls (default {POLL_SECONDS}).")
    args = parser.parse_args()

    simulate = args.simulate or SIMULATE
    if simulate:
        log.info("running in SIMULATE mode — no audio output")
    if not DB_PATH.exists():
        log.error("DB not found at %s — set GHOST_DB env var.", DB_PATH)
        sys.exit(1)

    signal.signal(signal.SIGINT,  _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    log.info("queue_consumer started: db=%s poll=%.1fs", DB_PATH, args.poll)
    if args.once:
        tick_once(simulate=simulate)
        return

    while _running:
        try:
            had_work = tick_once(simulate=simulate)
        except Exception:
            log.exception("tick failed")
            had_work = False
        # Slow down when idle; respond immediately when busy.
        time.sleep(0 if had_work else args.poll)
    log.info("queue_consumer stopped.")


if __name__ == "__main__":
    main()
