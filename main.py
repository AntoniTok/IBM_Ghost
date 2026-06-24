#!/usr/bin/env python3
"""
main.py
=======
Granite Ghost — Main entry point.

Wires together:
  - stt_listener.py  (Vosk speech-to-text, wake word + GPIO trigger)
  - llm_pipeline.py  (IBM Granite 4.0-H-350M with tool calling)
  - llm_tts_bridge.py (Piper text-to-speech)
  - queue consumer   (reads utterance_queue, speaks scheduled reminders)

The queue consumer (previously queue_consumer.py) now runs as a background
thread inside this process. It shares the same TTS instance and yields
when a live voice conversation is in progress.

Start everything with:
    python main.py

Make sure service_manager.py is already running before starting this.

CLI flags (inherited from queue_consumer):
    --simulate   Print spoken text instead of opening Piper / audio.
    --no-queue   Disable the queue consumer thread entirely.
"""

import argparse
import json
import logging
import os
import random
import signal
import sqlite3
import sys
import time
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from latency_debug import Timer, log_mem

# ─── Logging ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
)
log = logging.getLogger("main")

# ─── Config ──────────────────────────────────────────────────────────────────

PIPER_MODEL  = "./en_US-lessac-medium.onnx"
PIPER_CONFIG = "./en_US-lessac-medium.onnx.json"
THINKING_PHRASES = [
    "Let me check that for you.",
    "One moment, please.",
    "Hmm, let me have a look.",
    "Just a second.",
    "Let me see what I can find.",
]

# Queue consumer config
DB_PATH = Path(os.environ.get("GHOST_DB", "ghost.db"))
POLL_SECONDS = float(os.environ.get("CONSUMER_POLL_SECONDS", "30"))
USER_NAME = os.environ.get("GHOST_USER_NAME", "Margaret")
SIMULATE = bool(int(os.environ.get("SENTINEL_SIMULATE", "0")))


# ─── Shared state ────────────────────────────────────────────────────────────
#
# _processing: held while the voice loop is handling a live conversation.
#              The queue consumer checks this before speaking so it doesn't
#              talk over the user.
# _running:    set to False on SIGINT/SIGTERM to shut everything down cleanly.

_processing = threading.Lock()
_running = True


def _shutdown(signum, _frame):
    global _running
    log.info("signal %s — shutting down", signum)
    _running = False


# ═══════════════════════════════════════════════════════════════════════════════
# QUEUE CONSUMER  (merged from queue_consumer.py)
# ═══════════════════════════════════════════════════════════════════════════════

# ─── DB helpers ───────────────────────────────────────────────────────────────

def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


# ─── Template renderers ──────────────────────────────────────────────────────

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


# ─── Queue SQL ────────────────────────────────────────────────────────────────

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


def queue_tick(tts, simulate: bool) -> bool:
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
        # Wait if a live conversation is in progress
        with _processing:
            if simulate:
                log.info("[simulate] would speak: %s", text)
            else:
                tts.speak(text)
        delivered_at = _iso_now()
        with _connect() as conn:
            conn.execute(MARK_DELIVERED, (delivered_at, row["id"]))
        log.info("delivered utterance id=%d", row["id"])
    except Exception:
        log.exception("speak() failed for utterance id=%d", row["id"])
        with _connect() as conn:
            conn.execute(MARK_FAILED, (row["id"],))
    return True


def _queue_loop(tts, simulate: bool, poll: float):
    """Background thread: drains utterance_queue forever."""
    log.info("queue consumer thread started: poll=%.1fs", poll)
    while _running:
        try:
            had_work = queue_tick(tts, simulate=simulate)
        except Exception:
            log.exception("queue tick failed")
            had_work = False
        # Respond immediately when busy; slow down when idle.
        time.sleep(0 if had_work else poll)
    log.info("queue consumer thread stopped.")


# ═══════════════════════════════════════════════════════════════════════════════
# VOICE LOOP  (original main.py)
# ═══════════════════════════════════════════════════════════════════════════════

def _log_interaction(user_text: str):
    """Record a voice interaction to events + wellbeing_state.

    This ensures:
      - The routine baseline learns mic activity alongside PIR.
      - The scheduler's wellbeing check knows the user is alive.
    """
    try:
        now = _iso_now()
        with _connect() as conn:
            conn.execute(
                "INSERT INTO events (source, payload) VALUES ('mic', ?)",
                (json.dumps({"text": user_text[:100]}),),
            )
            conn.execute("""
                UPDATE wellbeing_state
                   SET last_interaction_at = ?,
                       consecutive_misses = 0,
                       updated_at = ?
                 WHERE id = 1
            """, (now, now))
    except Exception:
        log.debug("interaction log failed (non-critical)", exc_info=True)

def on_utterance(text: str, tts, llm_run):
    """
    Called by stt_listener every time a complete utterance is transcribed.
    Runs the LLM and speaks the response. Holds _processing to block the
    queue consumer from speaking at the same time.
    """
    if not _processing.acquire(blocking=False):
        log.info("Already processing a request, ignoring new trigger.")
        return

    try:
        log.info(f"Utterance received: {text!r}")
        utterance_start = time.monotonic()
        log_mem("utterance start")

        # Acknowledge immediately so the user isn't left in silence
        with Timer("speak_thinking_phrase"):
            tts.speak(random.choice(THINKING_PHRASES))

        # Run LLM (may call service_manager tools internally)
        with Timer("llm_run_total"):
            response = llm_run(text)
        # temp check before speakers
        print(f"\n>>> {response}\n")
        # Speak the response
        tts.speak(response)

        # Record this interaction for wellbeing + baseline learning
        _log_interaction(text)

        log.info(f"[timing] on_utterance TOTAL           |   {time.monotonic() - utterance_start:6.2f}s")

    except Exception as exc:
        log.error(f"Error during processing: {exc}", exc_info=True)
        tts.speak("Sorry, something went wrong. Please try again.")

    finally:
        _processing.release()


# ═══════════════════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Granite Ghost — voice + queue consumer.")
    parser.add_argument("--simulate", action="store_true",
                        help="Print spoken text instead of opening Piper / audio.")
    parser.add_argument("--no-queue", action="store_true",
                        help="Disable the background queue consumer thread.")
    parser.add_argument("--poll", type=float, default=POLL_SECONDS,
                        help=f"Queue poll interval in seconds (default {POLL_SECONDS}).")
    args = parser.parse_args()

    simulate = args.simulate or SIMULATE

    signal.signal(signal.SIGINT,  _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # ── Boot sequence ────────────────────────────────────────────────────
    log.info("Starting Granite Ghost …")

    # 1. TTS — load Piper voice first so we can speak status messages
    log.info("Loading TTS …")
    from llm_tts_bridge import TTSBridge
    tts = TTSBridge(model_path=PIPER_MODEL, config_path=PIPER_CONFIG)

    if not simulate:
        tts.speak("Good morning. Granite Ghost is starting up.")

    # 2. LLM — loads Granite model (~20-40s on Pi 4)
    log.info("Loading LLM …")
    if not simulate:
        tts.speak("Loading the language model, this will take a moment.")
    from llm_pipeline import run as llm_run
    if not simulate:
        tts.speak("Language model ready.")

    # 3. STT — import listener components (model loads inside run())
    log.info("Preparing STT …")
    import stt_listener

    # ── Start queue consumer thread ──────────────────────────────────────
    if not args.no_queue:
        if not DB_PATH.exists():
            log.warning("DB not found at %s — queue consumer disabled.", DB_PATH)
        else:
            t = threading.Thread(
                target=_queue_loop,
                args=(tts, simulate, args.poll),
                daemon=True,
                name="queue-consumer",
            )
            t.start()
            log.info("Queue consumer thread running.")
    else:
        log.info("Queue consumer disabled (--no-queue).")

    # ── Patch the STT listener and start ─────────────────────────────────
    stt_listener.on_utterance = lambda text: on_utterance(text, tts, llm_run)

    log.info("All systems ready.")
    if not simulate:
        tts.speak("Ready. You can say 'hey nova' or use the sensor to ask me something.")

    # Hand off to the STT listener loop (runs forever until Ctrl+C)
    stt_listener.run()


if __name__ == "__main__":
    main()
